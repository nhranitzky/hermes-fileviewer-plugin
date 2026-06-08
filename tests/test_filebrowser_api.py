"""Backend security tests for the Hermes filebrowser dashboard plugin."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = PROJECT_ROOT / "filebrowser"
PLUGIN_API = PLUGIN_ROOT / "dashboard" / "plugin_api.py"


def _write_config(
    home: Path,
    root: Path | None,
    *,
    enabled: bool = True,
    max_entries: int = 10,
    extra: str = "",
) -> None:
    home.mkdir(parents=True, exist_ok=True)
    root_line = f"    root: {root}\n" if root is not None else ""
    title_line = "    title: Reports\n"
    (home / "config.yaml").write_text(
        "plugins:\n"
        "  filebrowser:\n"
        f"    enabled: {'true' if enabled else 'false'}\n"
        f"{root_line}"
        f"{title_line}"
        "    allowed_extensions:\n"
        "      - .md\n"
        "      - .markdown\n"
        "      - .html\n"
        "      - .htm\n"
        "      - .pdf\n"
        "    markdown_max_bytes: 32\n"
        f"    max_entries_per_directory: {max_entries}\n"
        f"{extra}",
        encoding="utf-8",
    )


def _load_plugin_module(monkeypatch: pytest.MonkeyPatch, home: Path):
    monkeypatch.setenv("HERMES_HOME", str(home))

    def load_test_config() -> dict:
        return yaml.safe_load((home / "config.yaml").read_text(encoding="utf-8")) or {}

    hermes_cli_module = types.ModuleType("hermes_cli")
    config_module = types.ModuleType("hermes_cli.config")
    config_module.load_config = load_test_config
    monkeypatch.setitem(sys.modules, "hermes_cli", hermes_cli_module)
    monkeypatch.setitem(sys.modules, "hermes_cli.config", config_module)

    module_name = f"filebrowser_plugin_api_test_{id(home)}"
    spec = importlib.util.spec_from_file_location(module_name, PLUGIN_API)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def file_root(tmp_path: Path) -> Path:
    root = tmp_path / "filebrowser-root"
    docs = root / "docs"
    docs.mkdir(parents=True)
    (docs / "readme.md").write_text("# Hello\n", encoding="utf-8")
    (docs / "page.html").write_text('<h1>Hello</h1><img src="pic.png"><script>alert(1)</script>', encoding="utf-8")
    (docs / "pic.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (docs / "vector.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"></svg>', encoding="utf-8")
    (docs / "sample.pdf").write_bytes(b"%PDF-1.4\n% test pdf\n")
    (docs / "notes.txt").write_text("not allowed", encoding="utf-8")
    (docs / "large.md").write_text("# " + "x" * 64, encoding="utf-8")
    (docs / "bad.md").write_bytes(b"\xff\xfe\x00")
    (root / ".secret.md").write_text("secret", encoding="utf-8")
    (root / ".hidden-dir").mkdir()
    (root / ".hidden-dir" / "inside.md").write_text("hidden", encoding="utf-8")
    try:
        (root / "link-out").symlink_to(Path("/etc"))
        (root / "link-in.md").symlink_to(docs / "readme.md")
    except OSError:
        pass
    for idx in range(5):
        (root / f"visible-{idx}.md").write_text(f"# {idx}\n", encoding="utf-8")
    return root


@pytest.fixture
def client(tmp_path: Path, file_root: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    home = tmp_path / ".hermes"
    _write_config(home, file_root)
    module = _load_plugin_module(monkeypatch, home)
    app = FastAPI()
    app.include_router(module.router, prefix="/api/plugins/filebrowser")
    return TestClient(app)


def test_config_returns_sanitized_status(client: TestClient):
    r = client.get("/api/plugins/filebrowser/config")
    assert r.status_code == 200
    data = r.json()
    assert data["enabled"] is True
    assert data["configured"] is True
    assert data["title"] == "Reports"
    assert data["allowed_extensions"] == [".md", ".markdown", ".html", ".htm", ".pdf"]
    assert "filebrowser-root" not in r.text


def test_misconfigured_root_returns_503(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    home = tmp_path / ".hermes"
    _write_config(home, tmp_path / "missing-root")
    module = _load_plugin_module(monkeypatch, home)
    app = FastAPI()
    app.include_router(module.router, prefix="/api/plugins/filebrowser")
    c = TestClient(app)

    assert c.get("/api/plugins/filebrowser/config").json()["configured"] is False
    r = c.get("/api/plugins/filebrowser/list")
    assert r.status_code == 503


def test_list_filters_hidden_unsupported_and_symlinks(client: TestClient):
    r = client.get("/api/plugins/filebrowser/list")
    assert r.status_code == 200, r.text
    names = [entry["name"] for entry in r.json()["entries"]]
    assert ".secret.md" not in names
    assert ".hidden-dir" not in names
    assert "link-out" not in names
    assert "link-in.md" not in names

    r = client.get("/api/plugins/filebrowser/list", params={"path": "docs"})
    assert r.status_code == 200, r.text
    names = [entry["name"] for entry in r.json()["entries"]]
    assert "notes.txt" not in names
    assert "pic.png" not in names
    assert "vector.svg" not in names
    assert "readme.md" in names
    assert "page.html" in names
    assert "sample.pdf" in names


def test_list_truncates_large_directories(tmp_path: Path, file_root: Path, monkeypatch: pytest.MonkeyPatch):
    home = tmp_path / ".hermes"
    _write_config(home, file_root, max_entries=3)
    module = _load_plugin_module(monkeypatch, home)
    app = FastAPI()
    app.include_router(module.router, prefix="/api/plugins/filebrowser")
    client = TestClient(app)

    r = client.get("/api/plugins/filebrowser/list")
    assert r.status_code == 200
    data = r.json()
    assert data["truncated"] is True
    assert len(data["entries"]) == 3


def test_path_traversal_and_absolute_paths_are_rejected(client: TestClient):
    assert client.get("/api/plugins/filebrowser/list", params={"path": "../"}).status_code == 403
    assert client.get("/api/plugins/filebrowser/raw", params={"path": "/etc/passwd"}).status_code == 400


def test_hidden_direct_requests_are_rejected(client: TestClient):
    r = client.get("/api/plugins/filebrowser/markdown", params={"path": ".secret.md"})
    assert r.status_code == 403
    r = client.get("/api/plugins/filebrowser/markdown", params={"path": ".hidden-dir/inside.md"})
    assert r.status_code == 403


def test_symlink_direct_requests_are_rejected(client: TestClient, file_root: Path):
    if not (file_root / "link-out").exists() and not (file_root / "link-out").is_symlink():
        pytest.skip("symlinks unavailable")
    r = client.get("/api/plugins/filebrowser/list", params={"path": "link-out"})
    assert r.status_code == 403
    r = client.get("/api/plugins/filebrowser/markdown", params={"path": "link-in.md"})
    assert r.status_code == 403


def test_markdown_success_size_limit_and_encoding(client: TestClient):
    r = client.get("/api/plugins/filebrowser/markdown", params={"path": "docs/readme.md"})
    assert r.status_code == 200, r.text
    assert r.json()["content"] == "# Hello\n"

    assert client.get("/api/plugins/filebrowser/markdown", params={"path": "docs/large.md"}).status_code == 413
    assert client.get("/api/plugins/filebrowser/markdown", params={"path": "docs/bad.md"}).status_code == 422


def test_unsupported_and_missing_files(client: TestClient):
    assert client.get("/api/plugins/filebrowser/raw", params={"path": "docs/notes.txt"}).status_code == 415
    assert client.get("/api/plugins/filebrowser/raw", params={"path": "docs/missing.pdf"}).status_code == 404


def test_html_raw_inline_headers(client: TestClient):
    r = client.get("/api/plugins/filebrowser/raw", params={"path": "docs/page.html", "mode": "inline"})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/html")
    assert "sandbox allow-same-origin" in r.headers["content-security-policy"]
    assert "script-src 'none'" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["content-disposition"].startswith("inline")


def test_pdf_raw_inline_and_download_headers(client: TestClient):
    r = client.get("/api/plugins/filebrowser/raw", params={"path": "docs/sample.pdf", "mode": "inline"})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/pdf")
    assert "sandbox" in r.headers["content-security-policy"]
    assert r.headers["content-disposition"].startswith("inline")

    r = client.get("/api/plugins/filebrowser/raw", params={"path": "docs/sample.pdf", "mode": "download"})
    assert r.status_code == 200, r.text
    assert r.headers["content-disposition"].startswith("attachment")


def test_raw_path_serves_html_and_relative_image_assets(client: TestClient):
    r = client.get("/api/plugins/filebrowser/raw-path/docs/page.html")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/html")
    assert "sandbox allow-same-origin" in r.headers["content-security-policy"]
    assert "img-src 'self' data: blob:" in r.headers["content-security-policy"]

    r = client.get("/api/plugins/filebrowser/raw-path/docs/pic.png")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("image/png")
    assert r.headers["x-content-type-options"] == "nosniff"

    r = client.get("/api/plugins/filebrowser/raw-path/docs/vector.svg")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("image/svg+xml")
    assert "script-src 'none'" in r.headers["content-security-policy"]


def test_raw_path_keeps_security_boundaries_for_assets(client: TestClient):
    assert client.get("/api/plugins/filebrowser/raw-path/docs/notes.txt").status_code == 415
    assert client.get("/api/plugins/filebrowser/raw-path/.secret.md").status_code == 403
    assert client.get("/api/plugins/filebrowser/raw-path/%2E%2E/docs/pic.png").status_code in (403, 404)
