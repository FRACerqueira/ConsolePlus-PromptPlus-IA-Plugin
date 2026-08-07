#!/usr/bin/env python3
"""
Shared HTTP/cache helpers for this plugin's scripts.

Single source for the User-Agent string (kept in sync with plugin.json's
version - two independent copies of this constant already drifted stale
once) and for a response-size guard, since resolve_package_version.py and
fetch_doc.py otherwise duplicate identical urllib boilerplate. Both scripts
`import _http` as a plain sibling-module import - this works whether a
script is invoked as `python scripts/resolve_package_version.py` or via an
absolute path (e.g. `${CLAUDE_PLUGIN_ROOT}/scripts/...`), because Python
always adds the invoked script's own directory to sys.path[0], regardless of
the caller's cwd.

This module is always distributed alongside the other scripts in this same
scripts/ directory - see this repo's README (GitHub Copilot section) for why
consumers must copy the whole directory, not individual files.
"""

import json
import os
import sys
import urllib.request
from pathlib import Path

USER_AGENT = "consoleplus-promptplus-claude-plugin/0.2.0"

# Generous for a single doc page or a JSON API response - just a backstop
# against an unexpectedly (or maliciously) huge response being fully
# buffered into memory before any size check happens.
MAX_RESPONSE_BYTES = 10 * 1024 * 1024


def default_cache_dir():
    env_override = os.environ.get("CONSOLEPLUS_PROMPTPLUS_DOC_CACHE")
    if env_override:
        return Path(env_override)
    xdg = os.environ.get("XDG_CACHE_HOME")
    if xdg:
        return Path(xdg) / "consoleplus-promptplus-claude-plugin"
    if sys.platform == "win32" and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "consoleplus-promptplus-claude-plugin" / "doc-cache"
    return Path.home() / ".cache" / "consoleplus-promptplus-claude-plugin"


def github_headers(token=None, accept="application/vnd.github+json"):
    headers = {"Accept": accept}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _read_capped(resp, max_bytes, url):
    raw = resp.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ValueError(f"Response from {url} exceeded {max_bytes} bytes - refusing to buffer further")
    return raw


def http_get(url, headers=None, as_json=False, max_bytes=MAX_RESPONSE_BYTES):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = _read_capped(resp, max_bytes, url)
        return json.loads(raw.decode("utf-8")) if as_json else raw


def http_get_json(url, headers=None, max_bytes=MAX_RESPONSE_BYTES):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = _read_capped(resp, max_bytes, url)
        return json.loads(raw.decode("utf-8")), resp.headers
