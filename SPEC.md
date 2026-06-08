# Hermes Dashboard Filebrowser Plugin Specification

Version: 0.1.0
Status: Draft / MVP specification
Plugin name: `filebrowser`
Dashboard tab label: `Filebrowser`
Dashboard tab path: `/filebrowser`
API base path: `/api/plugins/filebrowser/`
Configuration section: `plugins.filebrowser`

## 1. Goal

The `filebrowser` plugin adds read-only file browsing functionality to the Hermes dashboard.

It allows an authenticated dashboard user to browse a configured root directory and preview selected files in the dashboard.

Supported preview types for the MVP:

- Markdown (`.md`, `.markdown`) rendered client-side
- HTML (`.html`, `.htm`) displayed unchanged in a sandboxed iframe
- PDF (`.pdf`) displayed inline using the browser PDF viewer

HTML previews may load same-root relative image assets through a separate asset allowlist (`.png`, `.jpg`, `.jpeg`, `.gif`, `.webp`, `.svg`). These assets are servable for previews but are not listed as standalone documents unless explicitly configured as allowed document extensions.

The plugin is intentionally read-only. It does not support upload, edit, delete, rename, move, or file creation.

## 2. Non-goals for MVP

The MVP explicitly does not include:

- File upload
- File editing
- Delete, rename, move, or copy operations
- Multiple root directories
- Recursive search
- Full-text search
- File indexing
- Per-file or per-directory permissions
- Public share links
- Symlink support
- Server-side content cache
- PDF text extraction
- PDF thumbnails
- Markdown Mermaid/diagram rendering
- Allowing JavaScript execution in HTML previews
- Allowing external network requests from HTML previews
- Plugin-specific theme system

## 3. Security model

The plugin exposes local files through the dashboard, so the security boundary is strict.

Rules:

- The plugin is read-only.
- Exactly one root directory is configured server-side.
- All user-provided paths are relative to the configured root.
- Absolute paths from requests are rejected.
- Path traversal must be blocked using resolved filesystem paths.
- Every requested path must resolve inside the configured root.
- Hidden files and hidden directories are never shown and cannot be opened.
- Symbolic links are not shown and cannot be opened.
- Only configured document extensions are listed and previewed directly.
- A narrow built-in image asset allowlist may be served through `/raw-path` for HTML previews, but those assets are not listed by default.
- Directory names are shown, except hidden directories and symlinks.
- The browser cannot expand the allowed root or allowed extensions.
- No stack traces or absolute filesystem paths are returned to the browser.

Recommended path validation pattern:

```python
root = configured_root.resolve()
target = (root / relative_path).resolve()
if not target.is_relative_to(root):
    raise HTTPException(status_code=403, detail="Invalid path")
```

Additional checks must reject:

- hidden path components
- symlink path components or symlink final targets
- unsupported extensions
- directories requested as files
- files requested as directories

## 4. Authentication and authorization

The plugin relies on the existing Hermes dashboard authentication layer.

Requirements:

- Plugin routes are mounted under `/api/plugins/filebrowser/`.
- Routes must be protected by the dashboard's existing plugin API authentication.
- The plugin does not implement its own password/session system.
- The plugin should not expose anonymous routes.
- If the dashboard is run without authentication, this plugin should still require explicit configuration and should be treated as local/trusted-use only.

No per-user role system is part of the MVP.

## 5. Configuration

Configuration lives under `plugins.filebrowser` in the Hermes configuration.

Example:

```yaml
plugins:
  filebrowser:
    enabled: true
    root: /opt/data/documents
    title: Reports
    allowed_extensions:
      - .md
      - .markdown
      - .html
      - .htm
      - .pdf
    markdown_max_bytes: 5242880
    max_entries_per_directory: 1000
```

Fields:

- `enabled`: boolean. Default: `false` if missing.
- `root`: absolute path to the filebrowser root. Required when enabled.
- `title`: display label for the configured root in the left browser pane. Default: `Root`.
- `allowed_extensions`: list of extensions. Default: `.md`, `.markdown`, `.html`, `.htm`, `.pdf`.
- `markdown_max_bytes`: maximum Markdown file size loaded into JSON. Default: 5 MiB.
- `max_entries_per_directory`: maximum visible entries returned for a directory. Default: 1000.

Validation rules:

- `root` must be absolute.
- `root` must exist.
- `root` must be a directory.
- `allowed_extensions` are normalized to lowercase and must include a leading dot.
- Empty extensions are invalid.
- Hidden files are always hidden in the MVP; there is no `hide_hidden` toggle.
- Symlinks are always blocked in the MVP; there is no `follow_symlinks` toggle.

Configuration is read and normalized at plugin/dashboard startup. Changes require restarting the dashboard/Hermes process.

If configuration is invalid, the plugin should still load so the UI can show a readable error. API routes should return `503 Service Unavailable` for configuration errors instead of crashing the dashboard.

## 6. Plugin structure

Recommended repository layout:

```text
hermes-filebrowser-plugin/
├── filebrowser/
│   ├── plugin.yaml
│   ├── __init__.py
│   └── dashboard/
│       ├── manifest.json
│       ├── plugin_api.py
│       └── dist/
│           ├── index.js
│           └── style.css
├── tests/
│   ├── test_filebrowser_api.py
│   └── test_filebrowser_frontend_static.py
├── README.md
├── SPEC.md
└── Makefile
```

`filebrowser/dashboard/manifest.json`:

```json
{
  "name": "filebrowser",
  "label": "Filebrowser",
  "description": "Read-only file browser for a configured document root",
  "icon": "FolderOpen",
  "version": "0.1.0",
  "tab": {
    "path": "/filebrowser",
    "position": "after:skills"
  },
  "entry": "dist/index.js",
  "css": "dist/style.css",
  "api": "plugin_api.py"
}
```

## 7. Backend API

All endpoints are mounted under:

```text
/api/plugins/filebrowser/
```

### 7.1 `GET /config`

Returns sanitized plugin status and client-usable settings.

Response when configured:

```json
{
  "enabled": true,
  "configured": true,
  "title": "Reports",
  "allowed_extensions": [".md", ".markdown", ".html", ".htm", ".pdf"],
  "markdown_max_bytes": 5242880,
  "max_entries_per_directory": 1000
}
```

The absolute root path should not be returned by default.

Response when not configured:

```json
{
  "enabled": false,
  "configured": false,
  "error": "Filebrowser is not configured"
}
```

### 7.2 `GET /list?path=<relative-dir>`

Lists visible directories and supported files in a directory.

Rules:

- Missing or empty `path` means root.
- `path` must resolve to a directory inside root.
- Hidden entries are excluded.
- Symlinks are excluded.
- Directories are included.
- Files are included only if their extension is configured.
- Directories are sorted first, then files.
- Sorting is alphabetical and case-insensitive.
- If more than `max_entries_per_directory` visible entries exist, return the first entries and set `truncated: true`.

Response example:

```json
{
  "path": "reports/2026",
  "parent": "reports",
  "truncated": false,
  "entries": [
    {
      "name": "monthly",
      "path": "reports/2026/monthly",
      "kind": "directory",
      "size": null,
      "modified_at": "2026-06-08T10:30:00Z",
      "extension": null
    },
    {
      "name": "summary.md",
      "path": "reports/2026/summary.md",
      "kind": "markdown",
      "size": 12345,
      "modified_at": "2026-06-08T10:31:00Z",
      "extension": ".md"
    }
  ]
}
```

`kind` values:

- `directory`
- `markdown`
- `html`
- `pdf`

### 7.3 `GET /markdown?path=<relative-file>`

Returns Markdown content as UTF-8 text in JSON.

Rules:

- File must be inside root.
- File must not be hidden.
- File must not be a symlink.
- Extension must be `.md` or `.markdown` and must be allowed by configuration.
- File size must be less than or equal to `markdown_max_bytes`.
- File must decode as UTF-8.

Response example:

```json
{
  "path": "docs/readme.md",
  "name": "readme.md",
  "kind": "markdown",
  "size": 12345,
  "modified_at": "2026-06-08T10:31:00Z",
  "content": "# Readme\n\n..."
}
```

### 7.4 `GET /raw?path=<relative-file>&mode=inline|download`

Streams a supported file.

Rules:

- File must be inside root.
- File must not be hidden.
- File must not be a symlink.
- Extension must be allowed by configuration.
- `mode=inline` is used for preview.
- `mode=download` is used for download.
- Filename in `Content-Disposition` is derived from the real file name, not from user input.

### 7.5 `GET /raw-path/<relative-file>&mode=inline|download`

Streams a supported file from a path-shaped URL. HTML previews use this route so relative assets such as `<img src="pic.png">` resolve naturally to sibling files under the same configured root.

Rules:

- Same root, hidden-path, symlink, and read-only checks as `/raw`.
- Document extensions still come from `allowed_extensions`.
- Additional image asset extensions are servable for HTML previews but are not listed as documents by default: `.png`, `.jpg`, `.jpeg`, `.gif`, `.webp`, `.svg`.
- `/raw-path` must be used for iframe previews when documents contain relative assets, because query-style `/raw?path=...` URLs make relative asset paths resolve against the API directory rather than the document directory.
- Frontend-generated iframe/link URLs must include the dashboard base path (`window.__HERMES_BASE_PATH__`) because `SDK.fetchJSON` only handles JSON requests, not iframe `src` or download `href` attributes.
- SVG responses include restrictive CSP and `X-Content-Type-Options: nosniff`.

Content types:

- Markdown: `text/markdown; charset=utf-8`
- HTML: `text/html; charset=utf-8`
- PDF: `application/pdf`
- Images for HTML assets: appropriate `image/*` type, including `image/svg+xml` for SVG

For HTML inline preview, the response must include restrictive headers:

```text
Content-Security-Policy: sandbox allow-same-origin; default-src 'none'; img-src 'self' data: blob:; style-src 'unsafe-inline'; font-src 'none'; script-src 'none'; connect-src 'none'; frame-ancestors 'self'; base-uri 'none'; form-action 'none'
X-Content-Type-Options: nosniff
Content-Disposition: inline
```

For PDF inline preview:

```text
Content-Type: application/pdf
Content-Security-Policy: sandbox; default-src 'none'; frame-ancestors 'self'
X-Content-Type-Options: nosniff
Content-Disposition: inline
```

For downloads:

```text
Content-Disposition: attachment; filename="..."
X-Content-Type-Options: nosniff
```

## 8. Frontend behavior

The plugin adds a dashboard tab at `/filebrowser` labeled `Filebrowser`.

Layout:

- Split view.
- Left pane:
  - configured root title
  - breadcrumb navigation for the current relative path
  - current directory listing
  - client-side filter for the current directory only
- Right pane:
  - selected file preview
  - empty state when no file is selected
  - readable error state when preview fails
  - compact glyph download control for selected supported file

Preview behavior:

- Markdown:
  - loaded through `/markdown`
  - rendered client-side
  - sanitized before insertion into the DOM
  - raw HTML inside Markdown must be disabled or removed
  - YAML-style frontmatter at the beginning of a document is hidden by default
  - frontmatter can be revealed with a small glyph button and is rendered as a metadata block when it consists of simple `key: value` lines
  - unordered lists render with visible bullet markers and indentation
  - ordered lists render with visible decimal markers and indentation
  - inline code uses scoped dashboard-token colors so it stays readable in dark theme
- HTML:
  - displayed unchanged via `/raw-path/<relative-file>?mode=inline`
  - embedded only in sandboxed iframe with `allow-same-origin` so same-root relative images can load
  - no `allow-scripts`
  - no `allow-forms`
  - no `allow-popups`
- PDF:
  - displayed via iframe or embed using `/raw-path/<relative-file>?mode=inline`
- Unsupported files:
  - not shown in the MVP

The plugin should use existing dashboard theme tokens and components where possible. It should not load external fonts, external CSS, or external JavaScript. It must not duplicate the dashboard shell's top-level `Filebrowser` title inside the tab content; the configured root `title` is shown inside the browser panel instead. Secondary actions use compact glyph controls (`↰` for parent directory, `⤓` for download, `ⓘ` for frontmatter).

## 9. URL state and deep links

The current directory and selected file should be represented in the dashboard URL as relative paths.

Example:

```text
/filebrowser?path=reports/2026&file=summary.md
```

Rules:

- URL state is only UI state.
- Backend validates every request independently.
- Refresh should preserve current directory and selected file.
- Browser back/forward should work for navigation.
- If a deep-linked file no longer exists, the UI shows an error while keeping the directory visible if possible.

## 10. Error handling

The API returns clean HTTP status codes and safe error messages.

Recommended status codes:

- `400 Bad Request`: malformed query parameters
- `403 Forbidden`: path escapes root, hidden file, symlink, or permission denied
- `404 Not Found`: file or directory does not exist
- `413 Payload Too Large`: Markdown file exceeds `markdown_max_bytes`
- `415 Unsupported Media Type`: extension is not allowed or cannot be previewed
- `422 Unprocessable Entity`: Markdown cannot be decoded as UTF-8
- `503 Service Unavailable`: plugin disabled or misconfigured

The browser should show readable non-technical messages.

Server logs may include detailed exception information and absolute paths. API responses should not expose absolute filesystem paths or stack traces.

## 11. Large directory behavior

The MVP does not implement pagination.

Instead:

- The backend returns at most `max_entries_per_directory` visible entries.
- The response includes `truncated: true` if the directory contains more visible entries.
- The UI displays a warning when results are truncated.

Default limit: 1000 visible entries.

## 12. Caching

The MVP does not implement a custom server-side content cache.

Behavior:

- Directory listings are read fresh on request.
- Markdown files are read fresh on request.
- Raw files are streamed using the web framework's file response support.
- Browser-level caching and HTTP revalidation headers may be used if provided by the framework.

## 13. Testing plan

Use a temporary test root, for example:

```text
/tmp/filebrowser-root/
├── docs/
│   ├── readme.md
│   ├── page.html
│   ├── pic.png
│   ├── vector.svg
│   └── sample.pdf
├── .secret.md
├── hidden/
│   └── .env
└── link-out -> /etc
```

Backend tests:

- `/config` works when configured.
- `/config` returns safe status when not configured.
- `/list` on root shows visible directories and supported files only.
- Hidden files are not listed.
- Hidden directories are not listed.
- Unsupported file extensions are not listed.
- HTML image assets are not listed as standalone documents unless configured as document extensions.
- HTML image assets are servable through `/raw-path` with correct image content types.
- SVG asset responses include restrictive CSP/nosniff headers.
- Symlinks are not listed.
- Direct request to hidden file is rejected.
- Direct request to symlink is rejected.
- Path traversal using `..` is rejected.
- Absolute paths are rejected.
- Markdown below size limit is returned as UTF-8 JSON.
- Markdown above size limit returns 413.
- Non-UTF-8 Markdown returns 422.
- Unsupported extension returns 415 or 403.
- Missing file returns 404.
- HTML raw inline response has restrictive CSP and nosniff headers.
- PDF raw inline response has `application/pdf`.
- Download mode sets `Content-Disposition: attachment`.
- Inline mode sets `Content-Disposition: inline`.
- Misconfigured root returns 503 and does not crash.

Frontend smoke tests:

- Dashboard tab appears as `Filebrowser`.
- Root listing loads.
- Breadcrumb navigation works.
- Current-directory filter works.
- Markdown preview renders and is sanitized.
- Markdown frontmatter is hidden by default and can be revealed.
- Markdown lists show bullets/numbers and indentation despite dashboard CSS resets.
- Markdown inline code is readable in dark theme and does not inherit unreadable global code colors.
- HTML preview opens in a sandboxed iframe.
- HTML preview loads same-root relative image assets through `/raw-path`.
- PDF preview opens inline.
- Download button works.
- URL state survives refresh.
- Errors are shown clearly.

## 14. Implementation order

Recommended order:

1. Create plugin skeleton.
2. Add dashboard manifest with `/filebrowser` tab.
3. Implement backend config loader and validation.
4. Implement safe path resolution helpers.
5. Implement `/config`.
6. Implement `/list`.
7. Implement `/markdown`.
8. Implement `/raw`.
9. Add backend security tests.
10. Add minimal frontend tab.
11. Add split-view navigation.
12. Add Markdown preview with sanitization, frontmatter handling, list styling, and readable inline code.
13. Add HTML/PDF iframe previews using `/raw-path` for relative asset support.
14. Add compact glyph controls for parent navigation, frontmatter reveal, and download.
15. Add frontend static regression checks.
16. Run manual dashboard smoke test.

## 15. Installation approach

Develop first outside the active Hermes profile:

```text
/opt/data/workspace/hermes-filebrowser-plugin
```

After tests pass, install the `filebrowser/` plugin directory into the active profile. The install target is configured via project-local `.env`:

```text
PLUGIN_INSTALL_DIR=/opt/data/plugins/filebrowser
```

Then run:

```bash
make install
```

`make install` uses `rsync --delete` from `filebrowser/` to `PLUGIN_INSTALL_DIR`.

Distribution packages are built with tar:

```bash
make dist
```

This creates:

```text
dist/filebrowser-0.1.0.tar.gz
```

The tarball contains the installable `filebrowser/` plugin directory and `filebrowser/README.md`; it excludes tests, caches, `SPEC.md`, `Makefile`, and `.env`.

Temporary artifacts can be removed with:

```bash
make clean
```

Restart the Hermes dashboard/gateway after installation or configuration changes.

