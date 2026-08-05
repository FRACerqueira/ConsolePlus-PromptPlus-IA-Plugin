# ConsolePlus + PromptPlus Claude Code Plugin

Helps Claude Code choose and implement the right [ConsolePlus](https://github.com/FRACerqueira/ConsolePlus)/[PromptPlus](https://github.com/FRACerqueira/PromptPlus) control for a .NET console application - which layer fits the need, whether an interactive control can even run in the target context, which of PromptPlus's 21 controls is the right fit, and how to implement it correctly - instead of you driving the decision and the API surface by hand.

## Key concepts

- **ConsolePlus** - the rendering foundation (styled output, markup, colors, widgets, cursor/screen control, capability detection). **PromptPlus** - the interactive-controls layer built on top of it (menus, inputs, pickers, progress, ...). `PromptPlus.Console` *is* the ConsolePlus driver - using PromptPlus never excludes ConsolePlus.
- **Console-type projects only** - this plugin's skill and hook only apply where the entry point project is a console app (`OutputType` `Exe`, not a web app, not a WinForms/WPF app using `WinExe`, not a library with no console entry point reachable in scope).
- **Version-pinned documentation** - both libraries publish `-rc` release candidates alongside stable versions; this plugin resolves the actual installed version (or the newest policy-acceptable one for a greenfield project) and pins every documentation fetch to the matching GitHub tag, rather than reading `main`/`develop`, which can describe unreleased API.

## Install

From a Claude Code session:
```
/plugin marketplace add /path/to/ConsolePlus-PromptPlus-claude-plugin
/plugin install consoleplus-promptplus@consoleplus-promptplus-tools
```

## Update

Installed from a **local path** (the command above): Claude Code re-reads the plugin's files
directly off disk, there is no clone/pull step to go stale - after pulling or editing this repo,
re-run `/plugin marketplace update consoleplus-promptplus-tools` and reopen `/plugin` to confirm the
installed copy picked up the change; if it still looks stale, a session restart forces a fresh read.

Installed from a **git-hosted marketplace** instead (`/plugin marketplace add owner/repo`), once
this plugin has a real remote: third-party marketplaces don't auto-update by default. After a new
version is pushed, refresh the catalog with
`/plugin marketplace update consoleplus-promptplus-tools` (the marketplace *name* from
`marketplace.json`, not the repo name), then open `/plugin`, find `consoleplus-promptplus`, and
update/reinstall it from there - a marketplace refresh alone doesn't confirm an already-installed
plugin actually moved to the newer version. Prefer not to do this by hand every time? `/plugin` →
**Marketplaces** tab → select the marketplace → enable auto-update, and Claude Code refreshes and
updates installed plugins from it in the background on startup.

Either way, see [Versioning](#versioning) below - a change with no version bump in `plugin.json`
won't be picked up as an update at all, from a local path or a git remote alike. And if you're
relying on the [doc cache](#doc-cache): it deliberately lives outside this plugin's own installed
directory precisely so an update (local or remote) never wipes it.

## How to use

You don't invoke anything by name for the everyday case - just describe what you need in plain
language while working in a console project, the same way you'd ask a colleague, and the router
skill takes it from there (version-pinned docs, the right layer, the right one of 21 controls,
correct fluent API). See **[How to use →](docs/how-to-use.md)** for real, step-by-step walkthroughs
of that everyday case plus the ambiguous-control, non-interactive-context, non-console-project,
audit, and pre-commit scenarios.

## What's included

- **Skill `select-promptplus-control`** - the router. Decides the ConsolePlus/PromptPlus layer, checks whether an interactive control can run in the target context (the `IsInputRedirected` guard and its exemptions), picks the right control among 21 (via 3 confusable clusters + 8 singles), and loads that control's implementation docs only when needed - never all 21 up front.
- **Hook (`PreToolUse` + `UserPromptExpansion`)** - deterministically gates the skill above to console-type projects only, walking the `ProjectReference` graph so a class library legitimately consumed by a console `Exe` is still allowed. Escalates to the user (`ask`) rather than guessing when it finds conflicting `.sln`/`.slnx` files defining the scope.
- **Agent `promptplus-auditor`** - full, on-demand, whole-codebase audit of existing ConsolePlus/PromptPlus usage: the redirected-input guard gap, confused `IWidgets` namespace usage, global `Config` mutation vs `.Options()`, unchecked `.IsAborted`, control choice against documented alternatives, abort-key overrides. Verifies findings against the live, version-pinned docs rather than memory. Read-only, produces a report.
- **Agent `promptplus-precommit-check`** - fast, diff-scoped counterpart: checks only pending changes, only for the two cheapest-to-fix bug-risk patterns (redirected-input guard gap, unchecked `.IsAborted`), no network/doc dependency. Meant to run proactively before every commit/PR, in the background, without slowing anything down - not a replacement for the full audit.
- **`scripts/resolve_package_version.py`** - resolves the policy-acceptable published version of a package (stable or `-rc`, never `-beta`/`-alpha`/`-preview`) and separately the GitHub tag matching what's actually installed, so "which version should I upgrade to" and "which docs describe my code" never get conflated.
- **`scripts/fetch_doc.py`** - fetches one doc file by `curl`, through a local cache keyed by repo+ref+path, and prints the local path to `Read`. Used instead of a direct WebFetch on doc pages because WebFetch runs content through a small model with a prompt and returns that model's response, not the raw file - fine for summarizing a page, not for a reference page whose exact method signatures and tables matter. A tag's content never changes, so caching it is exactly as correct as a fresh fetch; the one mutable ref this plugin ever fetches (`main`, for the greenfield case) is resolved to its current commit on a short TTL instead, so it still refreshes over time.
- **`scripts/check_console_project.py`** - the hook's console-project detector.

## Doc cache

`fetch_doc.py` caches under (in order of precedence) `$CONSOLEPLUS_PROMPTPLUS_DOC_CACHE`, `$XDG_CACHE_HOME/consoleplus-promptplus-claude-plugin`, `%LocalAppData%/consoleplus-promptplus-claude-plugin/doc-cache` (Windows), or `~/.cache/consoleplus-promptplus-claude-plugin` - deliberately **outside** this plugin's own installed directory, since a marketplace update may re-clone/replace that tree and a cache living inside it could vanish on every update. The cache is safe to delete at any time; it will just be repopulated on the next fetch.

**TTL:** doc content cached under an immutable git tag has no TTL - it never goes stale, so it's never re-fetched. The one exception is the greenfield fallback (`main`, which is actively moving - now that `v6.0.0-rc1` is tagged and released, `main` carries whatever unreleased work comes after it), where only the *ref → commit SHA* resolution has a TTL, `--main-refresh-minutes` (default `60`). A longer TTL (e.g. `1440` for 24h) costs at most one extra `api.github.com` call per hour saved - trivial against the unauthenticated 60 req/hour rate limit - but widens the window in which you could be reading yesterday's `main` without any indication it's stale. Raise it only if you've accepted that trade-off; the doc content itself is unaffected either way, since it's the ref resolution that's TTL'd, not the fetched files.

## Version acceptance policy

"Latest acceptable" means: stable, or `-rc`/`-rc<N>` - never `-beta`/`-alpha`/`-preview`/`-dev`. This is deliberate, not standard SemVer prerelease filtering - ConsolePlus.net currently sits on an `-rc1` release, with no floor on its major version.

**PromptPlus is different: this plugin only supports PromptPlus 6.0 and later.** Its 5.x line is being discontinued, so `resolve_package_version.py` is called with `--min-major-version 6` for PromptPlus specifically (never for ConsolePlus.net). A project on PromptPlus below 6.0 gets a plain "not supported, please upgrade" from the skill and both agents - not a degraded fallback. This also happens to be exactly right for the docs: PromptPlus's per-control documentation structure (`docs/controls/`, `global-behaviors.md`, `adr/`) was introduced at `v6.0.0-Beta1` and does not exist on any 5.x tag - the version floor and the doc-structure boundary line up, so there is no case left where a supported install has unstructured docs.

**As of this writing, `6.0.0-rc1` is published and is the current `latest_acceptable_version`** for PromptPlus - the steady state is now the normal case. Before it shipped, `resolve_package_version.py` had to handle the gap gracefully (an outright error with nothing installed either, or `status: "no-qualifying-version-published-yet"` with an unaccepted beta already installed) - that logic still exists and still runs correctly if it's ever needed again (e.g. a future unlisting), but it's the exception now, not the default.

## Prerequisites

- `python3` or `python` on `PATH` - both scripts are plain-stdlib Python (no `pip install` needed). The hook fails **open** (the tool call still proceeds) if neither is found, rather than blocking you on a missing interpreter - but not silently: Claude Code surfaces a visible "hook error" notice with the first line of stderr. On Windows specifically, this can trip on the default `python`/`python3` **App Execution Alias** stubs Windows ships out of the box (present on `PATH` even with no real interpreter installed) - `command -v python3` finds the stub and the hook runs it, but the stub itself exits non-zero with "Python was not found; run without arguments to install from the Microsoft Store...", which is what shows up in that notice. Disabling those aliases (Settings > Apps > Advanced app settings > App execution aliases) once a real interpreter is installed avoids the noise.
- `bash` on `PATH` for the hook commands (Git Bash on Windows).
- Network access to `api.nuget.org` and `api.github.com`/`raw.githubusercontent.com` for version resolution and (uncached) doc fetches - the skill degrades to WebFetch directly on `main` with a stated caveat if `python`/`python3` is unavailable, but the network calls themselves have no offline fallback. Once a given repo+ref+path has been fetched once, later requests for it are served from the local doc cache with no network call at all.

## Versioning

`plugin.json`'s `version` and the matching entry in `marketplace.json` must be bumped together on every meaningful change - Claude Code only picks up an update when that version string changes.
