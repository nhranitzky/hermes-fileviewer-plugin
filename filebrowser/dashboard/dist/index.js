(function () {
  "use strict";

  const SDK = window.__HERMES_PLUGIN_SDK__;
  if (!SDK || !window.__HERMES_PLUGINS__) return;

  const React = SDK.React;
  const h = React.createElement;
  const hooks = SDK.hooks || React;
  const useState = hooks.useState;
  const useEffect = hooks.useEffect;
  const useMemo = hooks.useMemo;
  const C = SDK.components || {};
  const Card = C.Card || "div";
  const CardContent = C.CardContent || "div";
  const Input = C.Input || "input";

  const API = "/api/plugins/filebrowser";
  const BASE_PATH = (function () {
    const raw = window.__HERMES_BASE_PATH__ || "";
    if (!raw) return "";
    return (raw.charAt(0) === "/" ? raw : "/" + raw).replace(/\/+$/, "");
  })();

  function dashboardUrl(path) {
    return BASE_PATH + path;
  }

  function api(path, options) {
    if (SDK.fetchJSON) return SDK.fetchJSON(API + path, options);
    return fetch(API + path, Object.assign({ credentials: "include" }, options || {})).then(function (r) {
      if (!r.ok) return r.text().then(function (t) { throw new Error(r.status + ": " + t); });
      return r.json();
    });
  }

  function parseApiErrorMessage(err) {
    const raw = err && err.message ? String(err.message) : String(err || "");
    const m = raw.match(/^(\d{3}):\s*(.*)$/s);
    const body = m ? m[2] : raw;
    try {
      const parsed = JSON.parse(body);
      if (parsed && typeof parsed.detail === "string") return parsed.detail;
    } catch (_e) {}
    return body || raw || "Request failed";
  }

  function joinPath(a, b) {
    if (!a) return b || "";
    if (!b) return a || "";
    return a.replace(/\/+$/, "") + "/" + b.replace(/^\/+/, "");
  }

  function dirname(path) {
    const s = String(path || "").replace(/\/+$/, "");
    const i = s.lastIndexOf("/");
    return i > 0 ? s.slice(0, i) : "";
  }

  function basename(path) {
    const s = String(path || "").replace(/\/+$/, "");
    const i = s.lastIndexOf("/");
    return i >= 0 ? s.slice(i + 1) : s;
  }

  function queryState() {
    const p = new URLSearchParams(window.location.search || "");
    return { path: p.get("path") || "", file: p.get("file") || "" };
  }

  function updateUrl(path, file, replace) {
    const url = new URL(window.location.href);
    if (path) url.searchParams.set("path", path); else url.searchParams.delete("path");
    if (file) url.searchParams.set("file", file); else url.searchParams.delete("file");
    const fn = replace ? window.history.replaceState : window.history.pushState;
    fn.call(window.history, {}, "", url.toString());
  }

  function rawUrl(path, mode) {
    return dashboardUrl(API + "/raw?path=" + encodeURIComponent(path) + "&mode=" + encodeURIComponent(mode || "inline"));
  }

  function rawPathUrl(path, mode) {
    return dashboardUrl(API + "/raw-path/" + String(path || "").split("/").map(encodeURIComponent).join("/") + "?mode=" + encodeURIComponent(mode || "inline"));
  }

  function isSafeHref(href) {
    const s = String(href || "").trim().toLowerCase();
    return s.startsWith("http://") || s.startsWith("https://") || s.startsWith("mailto:") || s.startsWith("#") || s.startsWith("/") || s.startsWith("./") || s.startsWith("../");
  }

  function inlineMarkdown(text, keyPrefix) {
    const out = [];
    const re = /(`[^`]+`|\*\*[^*]+\*\*|\[[^\]]+\]\([^)]+\))/g;
    let last = 0;
    let m;
    let idx = 0;
    while ((m = re.exec(text)) !== null) {
      if (m.index > last) out.push(text.slice(last, m.index));
      const token = m[0];
      if (token.startsWith("`")) {
        out.push(h("code", { key: keyPrefix + "c" + idx++ }, token.slice(1, -1)));
      } else if (token.startsWith("**")) {
        out.push(h("strong", { key: keyPrefix + "b" + idx++ }, token.slice(2, -2)));
      } else if (token.startsWith("[")) {
        const end = token.indexOf("](");
        const label = token.slice(1, end);
        const href = token.slice(end + 2, -1);
        if (isSafeHref(href)) {
          out.push(h("a", { key: keyPrefix + "a" + idx++, href: href, target: "_blank", rel: "noreferrer" }, label));
        } else {
          out.push(label);
        }
      }
      last = re.lastIndex;
    }
    if (last < text.length) out.push(text.slice(last));
    return out;
  }

  // Minimal safe Markdown renderer. It never injects raw HTML; all user text is
  // emitted as React text nodes. That intentionally removes raw HTML from .md.
  function renderMarkdownSafe(markdown) {
    const lines = String(markdown || "").replace(/\r\n/g, "\n").split("\n");
    const nodes = [];
    let paragraph = [];
    let list = [];
    let listTag = "ul";
    let code = [];
    let inCode = false;

    function flushParagraph() {
      if (!paragraph.length) return;
      const text = paragraph.join(" ");
      nodes.push(h("p", { key: "p" + nodes.length }, inlineMarkdown(text, "p" + nodes.length)));
      paragraph = [];
    }
    function flushList() {
      if (!list.length) return;
      nodes.push(h(listTag, { key: listTag + nodes.length }, list.map(function (item, i) {
        return h("li", { key: i }, inlineMarkdown(item, "li" + nodes.length + "-" + i));
      })));
      list = [];
      listTag = "ul";
    }
    function flushCode() {
      nodes.push(h("pre", { key: "pre" + nodes.length }, h("code", null, code.join("\n"))));
      code = [];
    }

    lines.forEach(function (line) {
      if (/^```/.test(line.trim())) {
        if (inCode) { flushCode(); inCode = false; }
        else { flushParagraph(); flushList(); inCode = true; code = []; }
        return;
      }
      if (inCode) { code.push(line); return; }
      if (!line.trim()) { flushParagraph(); flushList(); return; }
      const heading = line.match(/^(#{1,6})\s+(.+)$/);
      if (heading) {
        flushParagraph(); flushList();
        const level = Math.min(6, heading[1].length);
        nodes.push(h("h" + level, { key: "h" + nodes.length }, inlineMarkdown(heading[2], "h" + nodes.length)));
        return;
      }
      const li = line.match(/^\s*[-*+]\s+(.+)$/);
      if (li) {
        flushParagraph();
        if (list.length && listTag !== "ul") flushList();
        listTag = "ul";
        list.push(li[1]);
        return;
      }
      const oli = line.match(/^\s*\d+[.)]\s+(.+)$/);
      if (oli) {
        flushParagraph();
        if (list.length && listTag !== "ol") flushList();
        listTag = "ol";
        list.push(oli[1]);
        return;
      }
      paragraph.push(line.trim());
    });
    if (inCode) flushCode();
    flushParagraph();
    flushList();
    return nodes;
  }

  function splitMarkdownFrontmatter(markdown) {
    const text = String(markdown || "").replace(/\r\n/g, "\n");
    if (!text.startsWith("---\n")) return { frontmatter: "", body: text };
    const end = text.indexOf("\n---", 4);
    if (end < 0) return { frontmatter: "", body: text };
    const after = text.slice(end + 4);
    if (after && after[0] && after[0] !== "\n") return { frontmatter: "", body: text };
    return { frontmatter: text.slice(4, end).trim(), body: after.replace(/^\n/, "") };
  }

  function renderFrontmatter(frontmatter) {
    const lines = String(frontmatter || "").split("\n").filter(function (line) { return line.trim(); });
    const rows = lines.map(function (line) {
      const m = line.match(/^([A-Za-z0-9_.-]+):\s*(.*)$/);
      return m ? { key: m[1], value: m[2] || "—" } : null;
    });
    if (rows.length && rows.every(Boolean)) {
      return h("dl", { className: "fb-frontmatter-list" }, rows.map(function (row, i) {
        return h(React.Fragment, { key: row.key + i },
          h("dt", null, row.key),
          h("dd", null, row.value)
        );
      }));
    }
    return h("pre", { className: "fb-frontmatter-raw" }, frontmatter);
  }

  function fmtSize(n) {
    if (n === null || n === undefined) return "";
    if (n < 1024) return n + " B";
    if (n < 1024 * 1024) return (n / 1024).toFixed(1) + " KB";
    return (n / (1024 * 1024)).toFixed(1) + " MB";
  }

  function iconFor(entry) {
    if (entry.kind === "directory") return "📁";
    if (entry.kind === "markdown") return "📝";
    if (entry.kind === "html") return "🌐";
    if (entry.kind === "pdf") return "📄";
    return "📦";
  }

  function Breadcrumb(props) {
    const parts = props.path ? props.path.split("/").filter(Boolean) : [];
    if (!parts.length) return h("div", { className: "fb-breadcrumb fb-breadcrumb-empty" }, "/");
    const crumbs = [];
    let acc = "";
    parts.forEach(function (part) { acc = joinPath(acc, part); crumbs.push({ label: part, path: acc }); });
    return h("div", { className: "fb-breadcrumb" }, crumbs.map(function (c, i) {
      return h(React.Fragment, { key: c.path + i },
        i > 0 ? h("span", { className: "fb-crumb-sep" }, "/") : null,
        h("button", { className: "fb-crumb", onClick: function () { props.onNavigate(c.path); } }, c.label)
      );
    }));
  }

  function EntryList(props) {
    const filter = (props.filter || "").toLowerCase();
    const entries = (props.entries || []).filter(function (e) { return !filter || e.name.toLowerCase().includes(filter); });
    if (!entries.length) return h("div", { className: "fb-empty" }, "No entries.");
    return h("div", { className: "fb-list" }, entries.map(function (entry) {
      const selected = props.selectedFile === entry.path;
      return h("button", {
        key: entry.path,
        className: "fb-entry" + (selected ? " fb-entry-selected" : ""),
        onClick: function () { entry.kind === "directory" ? props.onNavigate(entry.path) : props.onSelect(entry); },
        title: entry.path,
      },
        h("span", { className: "fb-entry-icon" }, iconFor(entry)),
          h("span", { className: "fb-entry-main" },
          h("span", { className: "fb-entry-name" }, entry.name),
          entry.kind === "directory" ? null : h("span", { className: "fb-entry-meta" }, entry.kind + (entry.size ? " · " + fmtSize(entry.size) : ""))
        )
      );
    }));
  }

  function Preview(props) {
    const file = props.file;
    const markdown = props.markdown;
    const error = props.error;
    const loading = props.loading;
    const [showFrontmatter, setShowFrontmatter] = useState(false);

    useEffect(function () {
      setShowFrontmatter(false);
    }, [file && file.path]);

    const markdownParts = file && file.kind === "markdown" && markdown ? splitMarkdownFrontmatter(markdown.content) : { frontmatter: "", body: "" };

    if (!file) {
      return h("div", { className: "fb-preview-empty" }, "Select a file to preview.");
    }
    return h("div", { className: "fb-preview" },
      h("div", { className: "fb-preview-header" },
        h("div", null,
          h("div", { className: "fb-preview-title" }, file.name),
          h("div", { className: "fb-preview-meta" }, file.kind + " · " + fmtSize(file.size))
        ),
        h("a", {
          className: "fb-download-icon",
          href: rawUrl(file.path, "download"),
          title: "Download",
          "aria-label": "Download"
        }, "⤓")
      ),
      loading ? h("div", { className: "fb-loading" }, "Loading preview…") : null,
      error ? h("div", { className: "fb-error" }, error) : null,
      !loading && !error && file.kind === "markdown" ? h("div", { className: "fb-markdown" },
        markdownParts.frontmatter ? h("div", { className: "fb-frontmatter" },
          h("button", {
            className: "fb-frontmatter-toggle",
            type: "button",
            title: showFrontmatter ? "Hide frontmatter" : "Show frontmatter",
            "aria-label": showFrontmatter ? "Hide frontmatter" : "Show frontmatter",
            onClick: function () { setShowFrontmatter(!showFrontmatter); }
          }, "ⓘ"),
          showFrontmatter ? h("div", { className: "fb-frontmatter-panel" }, renderFrontmatter(markdownParts.frontmatter)) : null
        ) : null,
        renderMarkdownSafe(markdownParts.body)
      ) : null,
      !loading && !error && file.kind === "html" ? h("iframe", { className: "fb-frame", sandbox: "allow-same-origin", src: rawPathUrl(file.path, "inline"), title: file.name }) : null,
      !loading && !error && file.kind === "pdf" ? h("iframe", { className: "fb-frame", src: rawPathUrl(file.path, "inline"), title: file.name }) : null
    );
  }

  function FilebrowserPage() {
    const initial = queryState();
    const [config, setConfig] = useState(null);
    const [path, setPath] = useState(initial.path);
    const [selectedFile, setSelectedFile] = useState(initial.file);
    const [entries, setEntries] = useState([]);
    const [filter, setFilter] = useState("");
    const [truncated, setTruncated] = useState(false);
    const [loadingList, setLoadingList] = useState(false);
    const [listError, setListError] = useState("");
    const [previewLoading, setPreviewLoading] = useState(false);
    const [previewError, setPreviewError] = useState("");
    const [markdown, setMarkdown] = useState(null);

    const selectedEntry = useMemo(function () {
      if (!selectedFile) return null;
      const inList = entries.find(function (e) { return e.path === selectedFile; });
      if (inList) return inList;
      const name = basename(selectedFile);
      const ext = name.toLowerCase().split(".").pop() || "";
      const kind = ext === "pdf" ? "pdf" : (ext === "html" || ext === "htm" ? "html" : "markdown");
      return { name: name, path: selectedFile, kind: kind, size: null };
    }, [entries, selectedFile]);

    function navigate(nextPath) {
      setPath(nextPath || "");
      setSelectedFile("");
      setMarkdown(null);
      setPreviewError("");
      setFilter("");
      updateUrl(nextPath || "", "", false);
    }

    function select(entry) {
      setSelectedFile(entry.path);
      setMarkdown(null);
      setPreviewError("");
      updateUrl(path, entry.path, false);
    }

    useEffect(function () {
      function onPop() {
        const qs = queryState();
        setPath(qs.path);
        setSelectedFile(qs.file);
      }
      window.addEventListener("popstate", onPop);
      return function () { window.removeEventListener("popstate", onPop); };
    }, []);

    useEffect(function () {
      api("/config").then(setConfig).catch(function (err) {
        setConfig({ enabled: false, configured: false, error: parseApiErrorMessage(err) });
      });
    }, []);

    useEffect(function () {
      setLoadingList(true);
      setListError("");
      api("/list?path=" + encodeURIComponent(path || "")).then(function (data) {
        setEntries(data.entries || []);
        setTruncated(!!data.truncated);
        setLoadingList(false);
      }).catch(function (err) {
        setListError(parseApiErrorMessage(err));
        setEntries([]);
        setTruncated(false);
        setLoadingList(false);
      });
    }, [path]);

    useEffect(function () {
      if (!selectedEntry) return;
      setMarkdown(null);
      setPreviewError("");
      if (selectedEntry.kind !== "markdown") return;
      setPreviewLoading(true);
      api("/markdown?path=" + encodeURIComponent(selectedEntry.path)).then(function (data) {
        setMarkdown(data);
        setPreviewLoading(false);
      }).catch(function (err) {
        setPreviewError(parseApiErrorMessage(err));
        setPreviewLoading(false);
      });
    }, [selectedEntry && selectedEntry.path]);

    if (config && !config.configured) {
      return h("div", { className: "fb-root" },
        h(Card, { className: "fb-card" }, h(CardContent, { className: "fb-card-content" },
          h("div", { className: "fb-error" }, config.error || "Filebrowser is not configured.")
        ))
      );
    }

    return h("div", { className: "fb-root" },
      h("div", { className: "fb-shell" },
        h("aside", { className: "fb-sidebar" },
          h("div", { className: "fb-root-title" }, config && config.title ? config.title : "Root"),
          h(Breadcrumb, { path: path, onNavigate: navigate }),
          h(Input, {
            className: "fb-filter",
            value: filter,
            placeholder: "Filter current directory…",
            onChange: function (e) { setFilter(e.target.value); },
          }),
          path ? h("button", {
            className: "fb-up-icon",
            type: "button",
            title: "Parent directory",
            "aria-label": "Parent directory",
            onClick: function () { navigate(dirname(path)); }
          }, "↰") : null,
          truncated ? h("div", { className: "fb-warning" }, "Directory contains more entries than shown.") : null,
          listError ? h("div", { className: "fb-error" }, listError) : null,
          loadingList ? h("div", { className: "fb-loading" }, "Loading directory…") : h(EntryList, { entries: entries, filter: filter, selectedFile: selectedFile, onNavigate: navigate, onSelect: select })
        ),
        h("main", { className: "fb-main" },
          h(Preview, { file: selectedEntry, markdown: markdown, error: previewError, loading: previewLoading })
        )
      )
    );
  }

  if (typeof window.__HERMES_PLUGINS__.register === "function") {
    window.__HERMES_PLUGINS__.register("filebrowser", FilebrowserPage);
  }
})();
