"""Filebrowser dashboard plugin API.

Mounted by the Hermes dashboard plugin system at /api/plugins/filebrowser/.
The API is intentionally read-only and exposes only files below one configured
root directory.
"""

from __future__ import annotations

import logging
import mimetypes
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Literal
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

try:  # Hermes runtime
    from hermes_cli.config import load_config
except Exception:  # test/import fallback outside Hermes
    def load_config() -> dict[str, Any]:  # type: ignore[no-redef]
        return {}

log = logging.getLogger(__name__)
router = APIRouter()

DEFAULT_EXTENSIONS = [".md", ".markdown", ".html", ".htm", ".pdf"]
HTML_ASSET_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}
DEFAULT_MARKDOWN_MAX_BYTES = 5 * 1024 * 1024
DEFAULT_MAX_ENTRIES = 1000

HTML_CSP = (
    "sandbox allow-same-origin; default-src 'none'; img-src 'self' data: blob:; "
    "style-src 'unsafe-inline'; font-src 'none'; script-src 'none'; "
    "connect-src 'none'; frame-ancestors 'self'; base-uri 'none'; form-action 'none'"
)
PDF_CSP = "sandbox; default-src 'none'; frame-ancestors 'self'"


@dataclass(frozen=True)
class FilebrowserConfig:
    enabled: bool
    configured: bool
    root: Path | None
    title: str
    allowed_extensions: tuple[str, ...]
    markdown_max_bytes: int
    max_entries_per_directory: int
    error: str | None = None


def _normalize_extensions(raw: Any) -> tuple[str, ...]:
    if raw is None:
        raw = DEFAULT_EXTENSIONS
    if not isinstance(raw, list):
        raise ValueError("allowed_extensions must be a list")

    out: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            raise ValueError("allowed_extensions must contain only strings")
        ext = item.strip().lower()
        if not ext:
            raise ValueError("allowed_extensions contains an empty value")
        if not ext.startswith("."):
            ext = f".{ext}"
        if ext not in out:
            out.append(ext)
    if not out:
        raise ValueError("allowed_extensions must not be empty")
    return tuple(out)


def _positive_int(raw: Any, default: int, name: str) -> int:
    if raw is None:
        return default
    try:
        value = int(raw)
    except Exception as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def _load_filebrowser_config() -> FilebrowserConfig:
    try:
        cfg = load_config() or {}
        plugins = cfg.get("plugins") if isinstance(cfg, dict) else {}
        section = plugins.get("filebrowser") if isinstance(plugins, dict) else {}
        if section is None:
            section = {}
        if not isinstance(section, dict):
            raise ValueError("plugins.filebrowser must be a mapping")

        enabled = bool(section.get("enabled", False))
        allowed = _normalize_extensions(section.get("allowed_extensions"))
        title_raw = section.get("title", "Root")
        title = title_raw.strip() if isinstance(title_raw, str) and title_raw.strip() else "Root"
        markdown_max = _positive_int(
            section.get("markdown_max_bytes"),
            DEFAULT_MARKDOWN_MAX_BYTES,
            "markdown_max_bytes",
        )
        max_entries = _positive_int(
            section.get("max_entries_per_directory"),
            DEFAULT_MAX_ENTRIES,
            "max_entries_per_directory",
        )

        root_raw = section.get("root")
        if not enabled:
            return FilebrowserConfig(
                enabled=False,
                configured=False,
                root=None,
                title=title,
                allowed_extensions=allowed,
                markdown_max_bytes=markdown_max,
                max_entries_per_directory=max_entries,
                error="Filebrowser is disabled",
            )
        if not isinstance(root_raw, str) or not root_raw.strip():
            raise ValueError("plugins.filebrowser.root is required when enabled")
        root = Path(root_raw).expanduser()
        if not root.is_absolute():
            raise ValueError("plugins.filebrowser.root must be an absolute path")
        root = root.resolve()
        if not root.exists():
            raise ValueError("configured root does not exist")
        if not root.is_dir():
            raise ValueError("configured root is not a directory")

        return FilebrowserConfig(
            enabled=True,
            configured=True,
            root=root,
            title=title,
            allowed_extensions=allowed,
            markdown_max_bytes=markdown_max,
            max_entries_per_directory=max_entries,
        )
    except Exception as exc:
        log.warning("filebrowser configuration invalid: %s", exc)
        return FilebrowserConfig(
            enabled=False,
            configured=False,
            root=None,
            title="Root",
            allowed_extensions=tuple(DEFAULT_EXTENSIONS),
            markdown_max_bytes=DEFAULT_MARKDOWN_MAX_BYTES,
            max_entries_per_directory=DEFAULT_MAX_ENTRIES,
            error=str(exc),
        )


CONFIG = _load_filebrowser_config()


def reload_config_for_tests() -> FilebrowserConfig:
    """Reload module-level config. Intended for tests only."""
    global CONFIG
    CONFIG = _load_filebrowser_config()
    return CONFIG


def _require_config() -> FilebrowserConfig:
    if not CONFIG.enabled or not CONFIG.configured or CONFIG.root is None:
        raise HTTPException(status_code=503, detail=CONFIG.error or "Filebrowser is not configured")
    return CONFIG


def _is_hidden_relative(path: PurePosixPath) -> bool:
    return any(part.startswith(".") for part in path.parts if part not in ("", ".", ".."))


def _relative_parts_for_checks(relative_path: str) -> PurePosixPath:
    if relative_path is None or relative_path == "":
        return PurePosixPath(".")
    # Treat backslash as invalid rather than as a platform separator. API paths
    # are URL/Posix-style relative paths.
    if "\\" in relative_path:
        raise HTTPException(status_code=400, detail="Malformed path")
    p = PurePosixPath(relative_path)
    if p.is_absolute():
        raise HTTPException(status_code=400, detail="Absolute paths are not allowed")
    if _is_hidden_relative(p):
        raise HTTPException(status_code=403, detail="Hidden paths are not allowed")
    return p


def _safe_resolve(relative_path: str, *, expect: Literal["any", "file", "dir"] = "any") -> tuple[Path, str]:
    cfg = _require_config()
    assert cfg.root is not None
    rel_posix = _relative_parts_for_checks(relative_path)
    candidate = cfg.root / Path(*rel_posix.parts)
    _reject_symlink_request_path(cfg.root, rel_posix)

    try:
        resolved = candidate.resolve()
    except FileNotFoundError:
        # Path.resolve(strict=False) is default, but keep this guard for unusual
        # platform behaviour.
        resolved = candidate.resolve(strict=False)

    if not resolved.is_relative_to(cfg.root):
        raise HTTPException(status_code=403, detail="Invalid path")

    if not resolved.exists():
        raise HTTPException(status_code=404, detail="Path not found")

    _reject_symlink_component(cfg.root, resolved)

    if expect == "file" and not resolved.is_file():
        raise HTTPException(status_code=415, detail="Expected a file")
    if expect == "dir" and not resolved.is_dir():
        raise HTTPException(status_code=415, detail="Expected a directory")

    rel = resolved.relative_to(cfg.root).as_posix()
    return resolved, rel


def _reject_symlink_request_path(root: Path, rel_posix: PurePosixPath) -> None:
    """Reject symlink components in the original request path.

    `Path.resolve()` follows symlinks, so checking only the resolved target would
    miss a symlink that points back inside the root. MVP policy is stricter:
    symlinks are not allowed at all, even when their target is inside root.
    """
    current = root
    for part in rel_posix.parts:
        if part in ("", "."):
            continue
        if part == "..":
            current = current.parent
            continue
        current = current / part
        try:
            if current.exists() and current.is_symlink():
                raise HTTPException(status_code=403, detail="Symlinks are not allowed")
        except HTTPException:
            raise
        except OSError as exc:
            raise HTTPException(status_code=403, detail="Path cannot be read") from exc


def _reject_symlink_component(root: Path, resolved: Path) -> None:
    try:
        rel = resolved.relative_to(root)
    except ValueError:
        raise HTTPException(status_code=403, detail="Invalid path")

    current = root
    for part in rel.parts:
        current = current / part
        try:
            if current.is_symlink():
                raise HTTPException(status_code=403, detail="Symlinks are not allowed")
        except OSError as exc:
            raise HTTPException(status_code=403, detail="Path cannot be read") from exc


def _ensure_allowed_file(path: Path) -> str:
    cfg = _require_config()
    ext = path.suffix.lower()
    if ext not in cfg.allowed_extensions:
        raise HTTPException(status_code=415, detail="File type is not allowed")
    return ext


def _ensure_raw_servable_file(path: Path) -> str:
    cfg = _require_config()
    ext = path.suffix.lower()
    if ext in cfg.allowed_extensions or ext in HTML_ASSET_EXTENSIONS:
        return ext
    raise HTTPException(status_code=415, detail="File type is not allowed")


def _kind_for_extension(ext: str) -> str:
    if ext in (".md", ".markdown"):
        return "markdown"
    if ext in (".html", ".htm"):
        return "html"
    if ext == ".pdf":
        return "pdf"
    return "file"


def _modified_at(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _entry_for(path: Path, rel: str) -> dict[str, Any]:
    if path.is_dir():
        return {
            "name": path.name,
            "path": rel,
            "kind": "directory",
            "size": None,
            "modified_at": _modified_at(path),
            "extension": None,
        }
    ext = path.suffix.lower()
    return {
        "name": path.name,
        "path": rel,
        "kind": _kind_for_extension(ext),
        "size": path.stat().st_size,
        "modified_at": _modified_at(path),
        "extension": ext,
    }


def _visible_entries(directory: Path) -> Iterable[Path]:
    cfg = _require_config()
    for child in directory.iterdir():
        try:
            if child.name.startswith("."):
                continue
            if child.is_symlink():
                continue
            if child.is_dir():
                yield child
                continue
            if child.is_file() and child.suffix.lower() in cfg.allowed_extensions:
                yield child
        except PermissionError:
            log.info("filebrowser skipping unreadable entry: %s", child)
            continue
        except OSError as exc:
            log.info("filebrowser skipping entry %s: %s", child, exc)
            continue


def _content_type_for(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in (".md", ".markdown"):
        return "text/markdown; charset=utf-8"
    if ext in (".html", ".htm"):
        return "text/html; charset=utf-8"
    if ext == ".pdf":
        return "application/pdf"
    guessed = mimetypes.guess_type(path.name)[0]
    return guessed or "application/octet-stream"


def _content_disposition(path: Path, mode: str) -> str:
    disposition = "attachment" if mode == "download" else "inline"
    # Include both simple and RFC 5987 forms. quote() prevents header injection.
    ascii_name = path.name.encode("ascii", "ignore").decode("ascii") or "download"
    safe_ascii = ascii_name.replace('"', "")
    utf8_name = quote(path.name)
    return f"{disposition}; filename=\"{safe_ascii}\"; filename*=UTF-8''{utf8_name}"


@router.get("/config")
async def get_config() -> dict[str, Any]:
    return {
        "enabled": CONFIG.enabled,
        "configured": CONFIG.configured,
        "title": CONFIG.title,
        "allowed_extensions": list(CONFIG.allowed_extensions),
        "markdown_max_bytes": CONFIG.markdown_max_bytes,
        "max_entries_per_directory": CONFIG.max_entries_per_directory,
        "error": None if CONFIG.configured else (CONFIG.error or "Filebrowser is not configured"),
    }


@router.get("/list")
async def list_directory(path: str = Query(default="")) -> dict[str, Any]:
    cfg = _require_config()
    directory, rel = _safe_resolve(path, expect="dir")

    try:
        entries = list(_visible_entries(directory))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="Directory cannot be read") from exc

    entries.sort(key=lambda p: (not p.is_dir(), p.name.lower()))
    truncated = len(entries) > cfg.max_entries_per_directory
    entries = entries[: cfg.max_entries_per_directory]

    assert cfg.root is not None
    parent = ""
    if rel:
        parent_path = directory.parent.resolve()
        if parent_path.is_relative_to(cfg.root):
            parent = parent_path.relative_to(cfg.root).as_posix()

    return {
        "path": rel,
        "parent": parent,
        "truncated": truncated,
        "entries": [_entry_for(child, child.resolve().relative_to(cfg.root).as_posix()) for child in entries],
    }


@router.get("/markdown")
async def get_markdown(path: str = Query(...)) -> dict[str, Any]:
    cfg = _require_config()
    file_path, rel = _safe_resolve(path, expect="file")
    ext = _ensure_allowed_file(file_path)
    if ext not in (".md", ".markdown"):
        raise HTTPException(status_code=415, detail="File is not Markdown")

    size = file_path.stat().st_size
    if size > cfg.markdown_max_bytes:
        raise HTTPException(status_code=413, detail="Markdown file is too large")

    try:
        content = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=422, detail="Markdown file is not UTF-8") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="File cannot be read") from exc

    return {
        "path": rel,
        "name": file_path.name,
        "kind": "markdown",
        "size": size,
        "modified_at": _modified_at(file_path),
        "content": content,
    }


@router.get("/raw")
async def get_raw(path: str = Query(...), mode: Literal["inline", "download"] = Query(default="inline")) -> FileResponse:
    file_path, _rel = _safe_resolve(path, expect="file")
    ext = _ensure_allowed_file(file_path)

    headers = {
        "X-Content-Type-Options": "nosniff",
        "Content-Disposition": _content_disposition(file_path, mode),
    }
    if mode == "inline" and ext in (".html", ".htm"):
        headers["Content-Security-Policy"] = HTML_CSP
    elif mode == "inline" and ext == ".pdf":
        headers["Content-Security-Policy"] = PDF_CSP

    return FileResponse(
        file_path,
        media_type=_content_type_for(file_path),
        filename=file_path.name,
        headers=headers,
    )


@router.get("/raw-path/{asset_path:path}")
async def get_raw_path(asset_path: str, mode: Literal["inline", "download"] = Query(default="inline")) -> FileResponse:
    """Serve files from a path-shaped URL so HTML relative assets resolve.

    Example: iframe loads `/raw-path/reports/page.html`; an `<img src="pic.png">`
    then resolves naturally to `/raw-path/reports/pic.png`.
    """
    file_path, _rel = _safe_resolve(asset_path, expect="file")
    ext = _ensure_raw_servable_file(file_path)

    headers = {
        "X-Content-Type-Options": "nosniff",
        "Content-Disposition": _content_disposition(file_path, mode),
    }
    if mode == "inline" and ext in (".html", ".htm"):
        headers["Content-Security-Policy"] = HTML_CSP
    elif mode == "inline" and ext == ".pdf":
        headers["Content-Security-Policy"] = PDF_CSP
    elif mode == "inline" and ext == ".svg":
        headers["Content-Security-Policy"] = "sandbox; default-src 'none'; img-src data:; style-src 'unsafe-inline'; script-src 'none'"

    return FileResponse(
        file_path,
        media_type=_content_type_for(file_path),
        filename=file_path.name,
        headers=headers,
    )
