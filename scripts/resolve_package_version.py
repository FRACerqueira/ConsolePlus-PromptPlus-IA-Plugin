#!/usr/bin/env python3
"""
Resolves the "latest acceptable" published version of a ConsolePlus/PromptPlus
NuGet package, and maps it to the matching GitHub release tag so the skill can
fetch documentation pinned to a version that actually matches what a consumer
would install.

Acceptance policy (deliberate, not standard SemVer prerelease filtering):
  - stable versions (no prerelease label) are accepted
  - "-rc" / "-rc<N>" / "-rc.<N>" labels are accepted (case-insensitive)
  - anything else (-beta, -alpha, -preview, -dev, ...) is rejected
  - optionally, --min-major-version rejects everything below a floor on top of
    the label policy - this plugin passes 6 for PromptPlus (its 5.x line is
    being discontinued; this plugin only supports 6.0+ going forward), and
    nothing for ConsolePlus.net (no such floor there)

Why not trust NuGet "latest" or GitHub's own prerelease flag:
  - NuGet's flat-container version list has no "latest stable" concept; it is
    just an ordered list of every published version, prereleases included.
  - GitHub's release `prerelease` flag is set manually per release and is not
    reliable here — e.g. FRACerqueira/PromptPlus tag v6.0.0-Beta9 is marked
    prerelease=false on GitHub despite the label. Acceptance is decided purely
    from the version string itself.

Tag naming caveat: tags are `v<version>`, but the prerelease label's casing in
the tag does not reliably match the NuGet version's casing (NuGet lists
"6.0.0-beta9"; the matching tag is "v6.0.0-Beta9"). Tag lookup is therefore
case-insensitive against the real tag list, never a blind f"v{version}" guess.
"""

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

NUGET_INDEX_URL = "https://api.nuget.org/v3-flatcontainer/{package_id}/index.json"
GITHUB_TAGS_URL = "https://api.github.com/repos/{repo}/tags"
USER_AGENT = "consoleplus-promptplus-claude-plugin/0.1.0"
MAX_TAG_PAGES = 10  # safety bound: 10 * 100 = up to 1000 tags scanned

VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:-([A-Za-z]+)\.?(\d*))?$")
ACCEPTABLE_LABEL_RE = re.compile(r"^rc$", re.IGNORECASE)


def http_get_json(url, headers=None):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8")), resp.headers


def parse_version(version):
    """Returns (major, minor, patch, label_lower, num) or None if unparseable."""
    m = VERSION_RE.match(version)
    if not m:
        return None
    major, minor, patch, label, num = m.groups()
    return int(major), int(minor), int(patch), (label or "").lower(), int(num) if num else 0


def is_acceptable(parsed, min_major=None):
    major, _, _, label, _ = parsed
    if min_major is not None and major < min_major:
        return False
    return label == "" or ACCEPTABLE_LABEL_RE.match(label)


def rejection_reason(parsed, min_major=None):
    """Distinguishes *why* a version fails is_acceptable(), for a clearer status
    than a single catch-all "not accepted" bucket - "your install predates the
    minimum this plugin supports" is a different, more actionable fact than
    "your install is a rejected prerelease label"."""
    major, _, _, label, _ = parsed
    if min_major is not None and major < min_major:
        return "below-minimum-major"
    if not (label == "" or ACCEPTABLE_LABEL_RE.match(label)):
        return "prerelease-not-accepted"
    return None


def sort_key(parsed):
    major, minor, patch, label, num = parsed
    # Within the same major.minor.patch, a stable release outranks any -rc build.
    is_stable = 1 if label == "" else 0
    return (major, minor, patch, is_stable, num)


def fetch_nuget_versions(package_id):
    url = NUGET_INDEX_URL.format(package_id=package_id.lower())
    try:
        data, _ = http_get_json(url)
    except urllib.error.HTTPError as e:
        raise SystemExit(f"NuGet lookup failed for '{package_id}': HTTP {e.code}")
    except urllib.error.URLError as e:
        raise SystemExit(f"NuGet lookup failed for '{package_id}': {e.reason}")
    return data.get("versions", [])


def latest_acceptable_version(versions, min_major=None):
    candidates = []
    for v in versions:
        parsed = parse_version(v)
        if parsed and is_acceptable(parsed, min_major):
            candidates.append((sort_key(parsed), v))
    if not candidates:
        return None
    candidates.sort()
    return candidates[-1][1]


def fetch_github_tags(repo, github_token=None):
    tags = []
    headers = {"Accept": "application/vnd.github+json"}
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"
    page = 1
    while page <= MAX_TAG_PAGES:
        url = GITHUB_TAGS_URL.format(repo=repo) + f"?per_page=100&page={page}"
        try:
            data, _ = http_get_json(url, headers=headers)
        except urllib.error.HTTPError as e:
            raise SystemExit(f"GitHub tags lookup failed for '{repo}': HTTP {e.code}")
        except urllib.error.URLError as e:
            raise SystemExit(f"GitHub tags lookup failed for '{repo}': {e.reason}")
        if not data:
            break
        tags.extend(t["name"] for t in data)
        if len(data) < 100:
            break
        page += 1
    return tags


def find_matching_tag(version, tags):
    """Case-insensitive lookup of the `v<version>` tag against the real tag list."""
    target = f"v{version}".lower()
    for tag in tags:
        if tag.lower() == target:
            return tag
    return None


def probe_docs_structure(repo, tag, probe_path, github_token=None):
    """Checks whether `probe_path` exists at `tag` in `repo`.

    `probe_path` is repo-specific and must be passed in - there is no single
    path that means "the docs are in the expected shape" across both
    packages. On FRACerqueira/PromptPlus, `docs/controls` is the right probe:
    the per-control doc structure (docs/controls/<name>/{index,methods,
    operations,styles}.md, plus global-behaviors.md, architecture.md, adr/)
    was introduced all at once at v6.0.0-Beta1 and is present on every tag
    since (including develop/main). Every 5.x tag - including v5.0.8, the
    current -rc-policy "latest acceptable" release - predates it entirely:
    docs/ there is the older XmlDocMarkdownGenerator-based `api/` plus a
    single `whatsnewcontrols.md`. On FRACerqueira/ConsolePlus there is no
    per-"controls" concept at all (it has widgets, not controls) - probing
    `docs/controls` there would always read "legacy" despite ConsolePlus's
    docs being complete and current; pass a path meaningful to that repo
    instead (e.g. `docs/promptplus.md`), or omit --docs-probe-path entirely.

    Returns "structured", "legacy", or "unknown" (no tag or no probe_path given).
    """
    if tag is None or probe_path is None:
        return "unknown"
    headers = {"Accept": "application/vnd.github+json"}
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"
    url = f"https://api.github.com/repos/{repo}/contents/{probe_path}?ref={tag}"
    try:
        http_get_json(url, headers=headers)
        return "structured"
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return "legacy"
        raise SystemExit(f"Docs-structure probe failed for '{repo}'@{tag}: HTTP {e.code}")
    except urllib.error.URLError as e:
        raise SystemExit(f"Docs-structure probe failed for '{repo}'@{tag}: {e.reason}")


def resolve_installed_version(package_id, project_path):
    """Best-effort scan for the installed version of `package_id`.

    Tries, in order:
      1. <PackageReference Include="..." Version="..."/> - the normal consumer case.
      2. <PackageVersion Include="..." Version="..."/> - Central Package Management
         (Directory.Packages.props), where the actual csproj only has a bare
         <PackageReference Include="..." /> with no Version attribute.
      3. <PackageId>/<Version> - the library's own csproj, matched only when
         <PackageId> equals package_id. Covers running this script inside
         ConsolePlus-PromptPlus itself, where samples use ProjectReference and
         there is no PackageReference to scan at all.
    """
    text = Path(project_path).read_text(encoding="utf-8")
    pattern = re.compile(
        rf'<PackageReference\s+Include="{re.escape(package_id)}"\s+Version="([^"]+)"',
        re.IGNORECASE,
    )
    m = pattern.search(text)
    if m:
        return m.group(1)

    pattern2 = re.compile(
        rf'<PackageVersion\s+Include="{re.escape(package_id)}"\s+Version="([^"]+)"',
        re.IGNORECASE,
    )
    m = pattern2.search(text)
    if m:
        return m.group(1)

    id_pattern = re.compile(r"<PackageId>\s*([^<\s]+)\s*</PackageId>", re.IGNORECASE)
    id_match = id_pattern.search(text)
    if id_match and id_match.group(1).strip().lower() == package_id.lower():
        version_match = re.search(r"<Version>\s*([^<\s]+)\s*</Version>", text, re.IGNORECASE)
        if version_match:
            return version_match.group(1)

    return None


def status_for(installed, latest, min_major=None):
    """Classifies `installed` relative to `latest` (the policy-acceptable pick).

    The `num` component of sort_key is only meaningfully ordered *within* a
    single label track (rc1 < rc2 < rc3, or release patch N < N+1) - it is not
    comparable across different labels. -Beta6 is not "ahead of" -rc1 just
    because 6 > 1; on the real PromptPlus/ConsolePlus release history, every
    -Beta tag predates every -rc tag for the same major.minor.patch. So an
    installed version whose label falls outside the acceptance policy
    (anything but "" or "rc") is reported distinctly rather than numerically
    ranked against `latest` - the actionable fact is "not policy-accepted",
    not a possibly-wrong ahead/behind guess.

    When `min_major` is set, a below-floor install is its own distinct status
    ("installed-below-minimum-supported") rather than folding into the generic
    prerelease-rejection bucket - "this plugin doesn't support your version at
    all" is a materially different fact from "your prerelease label isn't the
    accepted kind".
    """
    pi, pl = parse_version(installed), parse_version(latest)
    if pi is None or pl is None:
        return "installed-version-unparseable"
    reason = rejection_reason(pi, min_major)
    if reason == "below-minimum-major":
        return "installed-below-minimum-supported"
    if reason == "prerelease-not-accepted":
        return "installed-prerelease-not-accepted"
    ki, kl = sort_key(pi), sort_key(pl)
    if ki == kl:
        return "up-to-date"
    return "ahead-of-latest-acceptable" if ki > kl else "outdated"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-id", required=True, help="NuGet package id, e.g. PromptPlus or ConsolePlus.net")
    parser.add_argument("--repo", required=True, help="GitHub owner/repo, e.g. FRACerqueira/PromptPlus")
    parser.add_argument("--installed-version", help="Version string already installed (skips csproj scanning)")
    parser.add_argument("--project-path", help=".csproj or Directory.Packages.props to scan for the installed version")
    parser.add_argument("--github-token", help="Optional token to raise the unauthenticated GitHub API rate limit")
    parser.add_argument(
        "--docs-probe-path",
        help="Repo-relative path whose presence at docs_tag indicates the expected doc structure "
             "(e.g. 'docs/controls' for PromptPlus). Repo-specific - see probe_docs_structure(). "
             "Omit to skip the probe (docs_structure will be 'unknown').",
    )
    parser.add_argument(
        "--min-major-version",
        type=int,
        help="Reject any version (published or installed) with a major version below this, on top "
             "of the stable-or-rc label policy. Package-specific, not a general SemVer concept - pass "
             "this for PromptPlus (6), which will drop support for its 5.x line; omit for ConsolePlus.net, "
             "which has no such floor.",
    )
    args = parser.parse_args()

    versions = fetch_nuget_versions(args.package_id)
    if not versions:
        print(json.dumps({"error": f"No published versions found for '{args.package_id}'"}))
        sys.exit(1)

    # Resolve `installed` before checking `latest` - even when no qualifying
    # version has been published yet (the current real state for PromptPlus
    # 6.x: only betas exist, none accepted), a consumer with something already
    # installed still needs docs pinned to *that*, and still deserves to be
    # told plainly whether their install already falls below --min-major-version
    # - that fact doesn't depend on a "latest acceptable" existing at all.
    installed = args.installed_version
    if installed is None and args.project_path:
        installed = resolve_installed_version(args.package_id, args.project_path)

    latest = latest_acceptable_version(versions, args.min_major_version)

    if latest is None:
        floor_note = f" at major>={args.min_major_version}" if args.min_major_version is not None else ""
        base_error = f"No stable or -rc version{floor_note} found for '{args.package_id}' among {len(versions)} published versions"

        if installed is None:
            # Nothing installed AND nothing acceptable published - genuinely
            # nothing to pin docs to. This is the only true hard-error case.
            print(json.dumps({"error": base_error, "min_major_version": args.min_major_version}))
            sys.exit(1)

        # Something is installed - still resolve its own tag/docs so the
        # caller isn't left with nothing, even though there's no "latest
        # acceptable" to compare it against or recommend upgrading to yet.
        tags = fetch_github_tags(args.repo, github_token=args.github_token)
        installed_tag = find_matching_tag(installed, tags)
        docs_tag = installed_tag
        docs_structure = probe_docs_structure(args.repo, docs_tag, args.docs_probe_path, github_token=args.github_token)
        installed_parsed = parse_version(installed)
        below_floor = (
            installed_parsed is not None
            and args.min_major_version is not None
            and installed_parsed[0] < args.min_major_version
        )
        print(json.dumps({
            "package_id": args.package_id,
            "repo": args.repo,
            "min_major_version": args.min_major_version,
            "latest_acceptable_version": None,
            "latest_acceptable_tag": None,
            "installed_version": installed,
            "installed_tag": installed_tag,
            "status": "installed-below-minimum-supported" if below_floor else "no-qualifying-version-published-yet",
            "docs_tag": docs_tag,
            "docs_structure": docs_structure,
            "total_published_versions": len(versions),
            "note": base_error + " - reporting the installed version's own docs pin instead of an upgrade target.",
        }, indent=2))
        return

    tags = fetch_github_tags(args.repo, github_token=args.github_token)
    matched_tag = find_matching_tag(latest, tags)

    installed_tag = find_matching_tag(installed, tags) if installed else None

    status = status_for(installed, latest, args.min_major_version) if installed else "unknown"

    # docs_tag answers "which docs describe the API actually in use" - it must
    # follow what's installed, not the upgrade-advisory pick. installed_tag
    # wins whenever it resolves; latest_acceptable_tag is only a fallback for
    # greenfield projects with nothing installed yet.
    docs_tag = installed_tag or matched_tag
    docs_structure = probe_docs_structure(args.repo, docs_tag, args.docs_probe_path, github_token=args.github_token)

    result = {
        "package_id": args.package_id,
        "repo": args.repo,
        "min_major_version": args.min_major_version,
        "latest_acceptable_version": latest,
        "latest_acceptable_tag": matched_tag,
        "installed_version": installed,
        "installed_tag": installed_tag,
        "status": status,
        "docs_tag": docs_tag,
        "docs_structure": docs_structure,
        "total_published_versions": len(versions),
    }
    if docs_tag == matched_tag and installed and installed_tag is None:
        result["docs_tag_note"] = (
            "installed_version had no matching GitHub tag; docs_tag fell back to "
            "latest_acceptable_tag, which may not reflect what's actually installed."
        )
    if matched_tag is None:
        result["warning"] = (
            f"No GitHub tag matched 'v{latest}' (case-insensitive) in {args.repo}; "
            "doc fetch should fall back to the previous acceptable version or report this explicitly."
        )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
