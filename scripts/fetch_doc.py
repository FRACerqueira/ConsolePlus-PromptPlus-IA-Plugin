#!/usr/bin/env python3
"""
Fetches one raw doc file from a GitHub repo, pinned to a ref, through a local
cache - and prints the local file path so the caller can Read it directly.

Why not WebFetch for this: WebFetch runs fetched content through a small,
fast model with a prompt and returns *that model's response*, not the raw
page - fine for "summarize this page", wrong for "give me the exact fluent
method signatures on this doc page" where paraphrasing loses precision. curl
+ a local file + Read gets the byte-for-byte content instead.

Why cache: the docs this plugin fetches (docs/controls/**, global-behaviors.md,
promptplus.md, ...) are pinned to an immutable git tag (docs_tag from
resolve_package_version.py) for almost every call - a tag's content never
changes, so a cache hit is exactly as correct as a fresh fetch and skips the
network round trip entirely. That stability is exactly what makes caching
safe here, unlike caching an arbitrary web page.

Mutable refs (only "main", used for the greenfield case in
select-promptplus-control's SKILL.md Step 0) are handled differently: `main`
moves forward over time, so it is first resolved to the commit SHA it points
at *right now* (re-resolved if that resolution is older than
--main-refresh-minutes, default 60 - fresh enough within one session,
without re-hitting the API on every single doc fetch in that session), and
the actual file is cached under that SHA - immutable once resolved, same as
any tag.
"""

import argparse
import json
import sys
import time
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _http import default_cache_dir, github_headers, http_get  # noqa: E402

RAW_URL = "https://raw.githubusercontent.com/{repo}/{ref}/{path}"
COMMIT_API_URL = "https://api.github.com/repos/{repo}/commits/{ref}"


def safe_join(base_dir, *parts):
    """Joins `parts` under `base_dir`, refusing to resolve outside it.

    pathlib's `/`/`joinpath` silently discards everything to its left when a
    later component is itself absolute, and doesn't collapse `..` segments
    before touching the filesystem - so a caller-supplied --repo/--ref/--path
    value containing an absolute path or `..` segments could otherwise make
    this script read or write far outside its own cache directory. Every
    part must resolve to a location inside `base_dir`, or this raises.
    """
    base = base_dir.resolve()
    candidate = base.joinpath(*parts).resolve()
    try:
        candidate.relative_to(base)
    except ValueError:
        raise SystemExit(
            f"Refusing to resolve outside the cache directory ({base}): {candidate} "
            f"- check --repo/--ref/--path for an absolute path or '..' segment."
        )
    return candidate


def resolve_mutable_ref(repo, ref, cache_dir, refresh_minutes, github_token=None):
    """Resolves a mutable ref (e.g. "main") to a commit SHA, cached with a TTL
    so repeated calls within one session don't re-hit the API each time.
    """
    ref_cache_file = safe_join(cache_dir, repo, "_refs", f"{ref}.json")
    if ref_cache_file.exists():
        try:
            record = json.loads(ref_cache_file.read_text(encoding="utf-8"))
            age_minutes = (time.time() - record["resolved_at"]) / 60
            if age_minutes < refresh_minutes:
                return record["sha"]
        except (json.JSONDecodeError, KeyError, OSError):
            pass  # fall through and re-resolve

    headers = github_headers(github_token)
    try:
        data = http_get(COMMIT_API_URL.format(repo=repo, ref=ref), headers=headers, as_json=True)
    except urllib.error.HTTPError as e:
        raise SystemExit(f"Could not resolve ref '{ref}' for '{repo}': HTTP {e.code}")
    except urllib.error.URLError as e:
        raise SystemExit(f"Could not resolve ref '{ref}' for '{repo}': {e.reason}")

    sha = data["sha"]
    ref_cache_file.parent.mkdir(parents=True, exist_ok=True)
    ref_cache_file.write_text(json.dumps({"sha": sha, "resolved_at": time.time()}), encoding="utf-8")
    return sha


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="owner/repo, e.g. FRACerqueira/PromptPlus")
    parser.add_argument("--ref", required=True, help="Git tag (immutable) or branch name (mutable) to fetch from")
    parser.add_argument("--path", required=True, help="Repo-relative path to the doc file, e.g. docs/controls/select/index.md")
    parser.add_argument("--mutable-ref", action="store_true", help="Pass this when --ref is a branch (e.g. main), not a tag - triggers SHA resolution instead of caching by the branch name directly")
    parser.add_argument("--main-refresh-minutes", type=int, default=60, help="How long a resolved mutable-ref SHA stays valid before re-resolving (default 60)")
    parser.add_argument("--cache-dir", help="Override the cache root (default: platform cache dir, see default_cache_dir())")
    parser.add_argument("--github-token", help="Optional token to raise the unauthenticated GitHub API rate limit (only used to resolve a mutable ref)")
    args = parser.parse_args()

    cache_dir = Path(args.cache_dir) if args.cache_dir else default_cache_dir()

    if args.mutable_ref:
        resolved_ref = resolve_mutable_ref(args.repo, args.ref, cache_dir, args.main_refresh_minutes, args.github_token)
    else:
        resolved_ref = args.ref

    local_path = safe_join(cache_dir, args.repo, resolved_ref, args.path)
    cached = local_path.exists()

    if not cached:
        url = RAW_URL.format(repo=args.repo, ref=resolved_ref, path=args.path)
        try:
            content = http_get(url)
        except urllib.error.HTTPError as e:
            print(json.dumps({"error": f"HTTP {e.code} fetching {url}"}))
            sys.exit(1)
        except urllib.error.URLError as e:
            print(json.dumps({"error": f"{e.reason} fetching {url}"}))
            sys.exit(1)
        try:
            local_path.parent.mkdir(parents=True, exist_ok=True)
            local_path.write_bytes(content)
        except OSError as e:
            print(json.dumps({"error": f"Could not write '{local_path}': {e}"}))
            sys.exit(1)

    print(json.dumps({
        "cached": cached,
        "path": str(local_path),
        "requested_ref": args.ref,
        "resolved_ref": resolved_ref,
    }))


if __name__ == "__main__":
    main()
