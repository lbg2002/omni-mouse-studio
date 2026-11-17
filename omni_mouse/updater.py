"""On-demand GitHub Releases update discovery for Omni Mouse Studio.

No background polling or own server. Does not download or execute remote code.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REPOSITORY = "lbg2002/omni-mouse-studio"
RELEASE_API = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
RELEASES_HOME = f"https://github.com/{REPOSITORY}/releases"
VERSION_FILE = Path(__file__).resolve().parent.parent / "VERSION"
_VERSION_RE = re.compile(r"^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


def parse_version(value: str) -> tuple[int, int, int]:
    if not isinstance(value, str):
        raise ValueError("version must be a string")
    match = _VERSION_RE.fullmatch(value.strip())
    if match is None:
        raise ValueError(f"invalid release version: {value!r}")
    return tuple(int(part) for part in match.groups())


def current_version() -> str:
    try:
        value = VERSION_FILE.read_text(encoding="utf-8").strip()
        parse_version(value)
        return value
    except (OSError, ValueError):
        return "0.0.0"


def get_latest_release() -> dict[str, Any]:
    """Return public stable release metadata. Called ONLY after explicit user action."""
    local = current_version()
    response: dict[str, Any] = {
        "ok": False,
        "current_version": local,
        "latest_version": "",
        "update_available": False,
        "has_deb": False,
        "deb_url": "",
        "release_url": RELEASES_HOME,
        "release_notes": "",
        "error": "",
    }
    request = urllib.request.Request(
        RELEASE_API,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"OmniMouseStudio/{local}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as stream:
            # Bound input even if the upstream endpoint misbehaves.
            data = stream.read(262145)
        if len(data) > 262144:
            raise ValueError("release metadata is too large")
        metadata = json.loads(data)
        if not isinstance(metadata, dict):
            raise ValueError("release metadata must be an object")
        if metadata.get("draft") or metadata.get("prerelease"):
            raise ValueError("latest release is not stable")
        tag = metadata.get("tag_name", "")
        release = parse_version(tag)
        version = ".".join(map(str, release))
        response["latest_version"] = version
        response["update_available"] = release > parse_version(local)
        response["release_url"] = f"{RELEASES_HOME}/tag/v{version}"
        notes = metadata.get("body", "")
        response["release_notes"] = str(notes)[:1200] if notes else ""
        expected_name = f"omni-mouse-studio_{version}_all.deb"
        expected_path = f"/{REPOSITORY}/releases/download/v{version}/{expected_name}"
        for asset in metadata.get("assets", []):
            if not isinstance(asset, dict) or asset.get("name") != expected_name:
                continue
            download_url = asset.get("browser_download_url", "")
            # Never expose a third-party download URL supplied by a release asset.
            if download_url == "https://github.com" + expected_path:
                response["has_deb"] = True
                response["deb_url"] = download_url
                break
        response["ok"] = True
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            response["error"] = "尚未发布稳定版本；请稍后重试。"
        elif exc.code == 403 or exc.code == 429:
            response["error"] = "GitHub API 请求受限，请稍后重试或打开 Releases 页面。"
        else:
            response["error"] = f"GitHub API 返回 HTTP {exc.code}"
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        response["error"] = f"连接 GitHub 失败：{exc}"
    except (ValueError, json.JSONDecodeError, KeyError, TypeError) as exc:
        response["error"] = f"发布信息无效：{exc}"
    return response
