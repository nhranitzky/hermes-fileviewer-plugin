"""Static checks for the filebrowser dashboard bundle.

These are not a replacement for browser tests, but they pin the security-critical
frontend decisions from SPEC.md: host SDK registration, authenticated SDK fetch,
sandboxed HTML iframe, raw Markdown HTML removal, and download/URL-state support.
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = PROJECT_ROOT / "filebrowser"
JS = PLUGIN_ROOT / "dashboard" / "dist" / "index.js"
CSS = PLUGIN_ROOT / "dashboard" / "dist" / "style.css"


def test_bundle_registers_filebrowser_plugin():
    js = JS.read_text(encoding="utf-8")
    assert "window.__HERMES_PLUGINS__.register(\"filebrowser\", FilebrowserPage)" in js
    assert "const API = \"/api/plugins/filebrowser\"" in js


def test_bundle_uses_sdk_fetch_json_for_auth():
    js = JS.read_text(encoding="utf-8")
    assert "SDK.fetchJSON" in js
    assert "return SDK.fetchJSON(API + path, options)" in js


def test_html_preview_is_sandboxed_without_script_permissions():
    js = JS.read_text(encoding="utf-8")
    assert "sandbox: \"allow-same-origin\"" in js
    assert "allow-scripts" not in js
    assert "dangerouslySetInnerHTML" not in js


def test_markdown_renderer_does_not_inject_raw_html():
    js = JS.read_text(encoding="utf-8")
    assert "function renderMarkdownSafe" in js
    assert "dangerouslySetInnerHTML" not in js
    assert "innerHTML" not in js
    assert "DOMParser" not in js


def test_download_and_url_state_are_present():
    js = JS.read_text(encoding="utf-8")
    css = CSS.read_text(encoding="utf-8")
    assert "mode=\" + encodeURIComponent(mode || \"inline\")" in js
    assert "rawUrl(file.path, \"download\")" in js
    assert "function rawPathUrl" in js
    assert "dashboardUrl(API + \"/raw-path/\"" in js
    assert "window.__HERMES_BASE_PATH__" in js
    assert "rawPathUrl(file.path, \"inline\")" in js
    assert "fb-download-icon" in js
    assert "}, \"⤓\")" in js
    assert ">Download<" not in js
    assert ".fb-download-icon" in css
    assert "window.history.pushState" in js
    assert "window.addEventListener(\"popstate\"" in js


def test_configurable_root_title_and_directory_meta_hidden():
    js = JS.read_text(encoding="utf-8")
    css = CSS.read_text(encoding="utf-8")
    assert "fb-root-title" in js
    assert "config && config.title ? config.title : \"Root\"" in js
    assert ".fb-root-title" in css
    assert "entry.kind === \"directory\" ? null" in js
    assert "Read-only files from the configured root" not in js


def test_parent_directory_uses_subtle_glyph_button():
    js = JS.read_text(encoding="utf-8")
    css = CSS.read_text(encoding="utf-8")
    assert "fb-up-icon" in js
    assert "Parent directory" in js
    assert "}, \"↰\")" in js
    assert "\"Up\"" not in js
    assert ".fb-up-icon" in css
    assert "background: transparent" in css


def test_markdown_frontmatter_is_hidden_by_default_and_toggleable():
    js = JS.read_text(encoding="utf-8")
    css = CSS.read_text(encoding="utf-8")
    assert "function splitMarkdownFrontmatter" in js
    assert "function renderFrontmatter" in js
    assert "showFrontmatter ? h(\"div\", { className: \"fb-frontmatter-panel\" }" in js
    assert "setShowFrontmatter(false)" in js
    assert "}, \"ⓘ\")" in js
    assert ".fb-frontmatter-toggle" in css
    assert ".fb-frontmatter-panel" in css
    assert ".fb-frontmatter-list" in css


def test_markdown_lists_have_visible_markers_and_indentation():
    js = JS.read_text(encoding="utf-8")
    css = CSS.read_text(encoding="utf-8")
    assert "let listTag = \"ul\"" in js
    assert "h(listTag" in js
    assert "const oli = line.match" in js
    assert "list-style-type: disc" in css
    assert "list-style-type: decimal" in css
    assert "display: list-item" in css
    assert "padding-left: 1.5rem" in css


def test_markdown_inline_code_has_readable_scoped_colors():
    css = CSS.read_text(encoding="utf-8")
    assert ".fb-markdown code" in css
    assert "color: var(--color-foreground) !important" in css
    assert ".fb-markdown :not(pre) > code" in css
    assert "border: 1px solid" in css


def test_markdown_tables_are_rendered_and_styled():
    js = JS.read_text(encoding="utf-8")
    css = CSS.read_text(encoding="utf-8")
    assert "function splitTableRow" in js
    assert "function parseTableSeparator" in js
    assert "function renderMarkdownTable" in js
    assert "fb-markdown-table" in js
    assert "h(\"thead\"" in js
    assert "h(\"tbody\"" in js
    assert ".fb-table-wrap" in css
    assert ".fb-markdown-table" in css
    assert "border-collapse: collapse" in css
    assert ".fb-markdown-table th," in css


def test_css_contains_split_view_and_mobile_layout():
    css = CSS.read_text(encoding="utf-8")
    assert ".fb-shell" in css
    assert "grid-template-columns: minmax(260px, 360px) minmax(0, 1fr)" in css
    assert "@media (max-width: 900px)" in css
    assert "var(--color-card)" in css
    assert "hsl(var(--card" not in css
