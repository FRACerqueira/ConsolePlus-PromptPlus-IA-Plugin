# ConsolePlus + PromptPlus Plugin

Helps AI coding assistants choose and implement the right [ConsolePlus](https://github.com/FRACerqueira/ConsolePlus)/[PromptPlus](https://github.com/FRACerqueira/PromptPlus) control for a .NET console application - which layer fits the need, whether an interactive control can even run in the target execution context, which of PromptPlus's 21 controls is the right fit, and how to implement it correctly - instead of you driving the decision and the API surface by hand. Two integrations are maintained in this repo:

- **[Claude Code](#claude-code)** - a full plugin (1 skill, 2 agents, 1 hook), distributed through Claude Code's plugin marketplace.
- **[GitHub Copilot](#github-copilot)** - the same skill and agents, adapted to Copilot's Agent Skills / custom-agent format under `copilot/` (copied manually into your repo - there's no marketplace for Copilot, and no equivalent to the Claude Code hook; see that section for how the console-project check works there instead).

Already installed and just want to know what to actually type? See **[How to use →](docs/how-to-use.md)**.

## Key concepts

- **ConsolePlus** - the rendering foundation (styled output, markup, colors, widgets, cursor/screen control, capability detection). **PromptPlus** - the interactive-controls layer built on top of it (menus, inputs, pickers, progress, ...). `PromptPlus.Console` *is* the ConsolePlus driver - using PromptPlus never excludes ConsolePlus.
- **Console-type projects only** - this plugin's skill (and, on Claude Code, its hook) only apply where the entry point project is a console app (`OutputType` `Exe`, not a web app, not a WinForms/WPF app using `WinExe`, not a library with no console entry point reachable in scope).
- **Version-pinned documentation** - both libraries publish `-rc` release candidates alongside stable versions; this plugin resolves the actual installed version (or the newest policy-acceptable one for a greenfield project) and pins every documentation fetch to the matching GitHub tag, rather than reading `main`/`develop`, which can describe unreleased API.
- **Agent Skills** - the open standard (`SKILL.md` + frontmatter) both Claude Code and GitHub Copilot consume; it's why `skills/select-promptplus-control` and `copilot/skills/select-promptplus-control` are near-identical rather than two unrelated implementations.

## What's included

- **Skill `select-promptplus-control`** - the router. Decides the ConsolePlus/PromptPlus layer, checks whether an interactive control can run in the target context (the `IsInputRedirected` guard and its exemptions), picks the right control among 21 (via 3 confusable clusters + 8 singles), and loads that control's implementation docs only when needed - never all 21 up front.
- **Agent `promptplus-auditor`** - full, on-demand, whole-codebase audit of existing ConsolePlus/PromptPlus usage: the redirected-input guard gap, confused `IWidgets` namespace usage, global `Config` mutation vs `.Options()`, unchecked `.IsAborted`, control choice against documented alternatives, abort-key overrides. Verifies findings against the live, version-pinned docs rather than memory. Read-only, produces a report.
- **Agent `promptplus-precommit-check`** - fast, diff-scoped counterpart: checks only pending changes, only for the two cheapest-to-fix bug-risk patterns (redirected-input guard gap, unchecked `.IsAborted`), no network/doc dependency. Meant to run proactively before every commit/PR, in the background, without slowing anything down - not a replacement for the full audit.
- **`scripts/resolve_package_version.py`** - resolves the policy-acceptable published version of a package (stable or `-rc`, never `-beta`/`-alpha`/`-preview`) and separately the GitHub tag matching what's actually installed, so "which version should I upgrade to" and "which docs describe my code" never get conflated. Caches the GitHub tag list for a few minutes (see `--tags-cache-minutes`) so a session that checks both PromptPlus and ConsolePlus.net doesn't burn through the unauthenticated GitHub API rate limit.
- **`scripts/_http.py`** - shared HTTP/cache helpers the two scripts above both import (single source for the User-Agent string and a response-size guard). Not invoked directly - always travels alongside the other scripts.
- **`scripts/fetch_doc.py`** - fetches one doc file by `curl`, through a local cache keyed by repo+ref+path, and prints the local path to `Read`. Used instead of a direct URL-fetch tool call on doc pages because that kind of tool runs content through a small model with a prompt and returns that model's response, not the raw file - fine for summarizing a page, not for a reference page whose exact method signatures and tables matter. A tag's content never changes, so caching it is exactly as correct as a fresh fetch; the one mutable ref this plugin ever fetches (`main`, for the greenfield case) is resolved to its current commit on a short TTL instead, so it still refreshes over time.
- **`scripts/check_console_project.py`** - the console-project detector; drives the Claude Code hook below, and can also be run directly (e.g. via Copilot's `runCommands` tool) wherever there's no hook to run it automatically.

The canonical source for the skill and both agents lives under `skills/` and `agents/` (Claude Code format, described below). `copilot/` mirrors the same three, adapted for GitHub Copilot - see [GitHub Copilot](#github-copilot).

## Claude Code

### Install

From a Claude Code session:
```
/plugin marketplace add /path/to/ConsolePlus-PromptPlus-claude-plugin
/plugin install consoleplus-promptplus@consoleplus-promptplus-tools
```

### Update

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

### Hook

The `PreToolUse` + `UserPromptExpansion` hook (`hooks/hooks.json`) deterministically gates
`select-promptplus-control` to console-type projects only, walking the `ProjectReference` graph so a
class library legitimately consumed by a console `Exe` is still allowed. Escalates to the user
(`ask`) rather than guessing when it finds conflicting `.sln`/`.slnx` files defining the scope. This
mechanism has no equivalent on GitHub Copilot - see [GitHub Copilot](#github-copilot).

## GitHub Copilot

GitHub Copilot supports the same open [Agent Skills](https://agentskills.io/specification) standard as Claude Code, plus its own custom-agent format (`.github/agents/*.agent.md`). This repo ships a `copilot/` mirror of `skills/select-promptplus-control` and both agents, adapted for Copilot:

```
copilot/
├── skills/
│   └── select-promptplus-control/SKILL.md
└── agents/
    ├── promptplus-auditor.agent.md
    └── promptplus-precommit-check.agent.md
```

**There's no marketplace for Copilot** - unlike `/plugin install` above, there's no centralized
install. Copy the files into the repo where you're using ConsolePlus/PromptPlus, **including this
plugin's `scripts/` directory** - unlike a CLI-driven plugin, this one ships its own Python helper
scripts, and both the skill and both agents invoke them by the same relative path
(`scripts/resolve_package_version.py`, `scripts/fetch_doc.py`, `scripts/check_console_project.py`)
regardless of which assistant is running them:

```bash
mkdir -p your-repo/.github/skills your-repo/.github/agents your-repo/scripts
cp -r copilot/skills/select-promptplus-control your-repo/.github/skills/
cp copilot/agents/*.agent.md your-repo/.github/agents/
cp -r scripts/. your-repo/scripts/
```
(`mkdir -p` first matters: `cp -r src dst` behaves differently depending on whether `dst` already
exists - skipping it can leave the skill's files directly under `.github/skills/` instead of nested
under `.github/skills/select-promptplus-control/`, which Agent Skills discovery won't find. The
`scripts/.` form on the last line copies contents into `your-repo/scripts/` whether or not that
directory - or one by that name - already existed, instead of risking a nested
`your-repo/scripts/scripts/`.

Alternatively use `.claude/skills`, `.agents/skills`, or `~/.copilot/skills` for personal, cross-repo
use - see [GitHub's agent skills docs](https://docs.github.com/en/copilot/concepts/agents/about-agent-skills)
for the full discovery rules. If you place `scripts/` somewhere other than your repo root, update the
`scripts/...py` paths in the copied `SKILL.md`/`.agent.md` files to match.)

Claude Code's tool names (`Bash`, `Read`, `Glob`, `Grep`, `WebFetch`) don't map 1:1 to Copilot's
(`runCommands`, `codebase`, `search`, `fetch`, ...) - each `copilot/agents/*.agent.md` file's `tools:`
frontmatter carries the translated list. The `Bash→runCommands`, `Read→codebase`, and
`Grep`/`Glob→search` mappings were checked against Copilot's actual built-in tool set;
`WebFetch→fetch` is this plugin's own best guess and hasn't been independently verified - if `fetch`
gets rejected as an unknown tool in your Copilot version, check its current built-in tool list and
adjust `copilot/agents/promptplus-auditor.agent.md`'s `tools:` line accordingly.

**No hook on Copilot.** Claude Code's console-project hook (`hooks/hooks.json` +
`scripts/check_console_project.py`) has no Copilot equivalent - there's no hook mechanism to gate a
skill's invocation before it runs. `copilot/skills/select-promptplus-control/SKILL.md`'s "Scope
check" step is adapted accordingly: the manual entry-point check that's a documented fallback on
Claude Code (only used if the hook isn't installed) is the primary, always-on path on Copilot. You
can still run `scripts/check_console_project.py` directly via the `runCommands` tool - run this way
(no Claude Code hook payload on stdin) it prints a plain `{"decision", "reason"}` result instead of
the Claude-specific hook envelope it uses when Claude Code itself calls it.

`copilot/` is not generated from `skills/`/`agents/` - there's no sync tooling yet. If you change the
canonical Claude files, update `copilot/` by hand to keep them consistent.

## Doc cache

`fetch_doc.py` caches under (in order of precedence) `$CONSOLEPLUS_PROMPTPLUS_DOC_CACHE`, `$XDG_CACHE_HOME/consoleplus-promptplus-claude-plugin`, `%LocalAppData%/consoleplus-promptplus-claude-plugin/doc-cache` (Windows), or `~/.cache/consoleplus-promptplus-claude-plugin` - deliberately **outside** this plugin's own installed directory, since a marketplace update may re-clone/replace that tree and a cache living inside it could vanish on every update. The cache is safe to delete at any time; it will just be repopulated on the next fetch. This applies the same way regardless of which assistant is calling `fetch_doc.py` - Claude Code and GitHub Copilot share the same cache.

**TTL:** doc content cached under an immutable git tag has no TTL - it never goes stale, so it's never re-fetched. The one exception is the greenfield fallback (`main`, which is actively moving - now that `v6.0.0-rc1` is tagged and released, `main` carries whatever unreleased work comes after it), where only the *ref → commit SHA* resolution has a TTL, `--main-refresh-minutes` (default `60`). A longer TTL (e.g. `1440` for 24h) costs at most one extra `api.github.com` call per hour saved - trivial against the unauthenticated 60 req/hour rate limit - but widens the window in which you could be reading yesterday's `main` without any indication it's stale. Raise it only if you've accepted that trade-off; the doc content itself is unaffected either way, since it's the ref resolution that's TTL'd, not the fetched files.

## Version acceptance policy

"Latest acceptable" means: stable, or `-rc`/`-rc<N>` - never `-beta`/`-alpha`/`-preview`/`-dev`. This is deliberate, not standard SemVer prerelease filtering - ConsolePlus.net currently sits on an `-rc1` release, with no floor on its major version. This policy is enforced by `resolve_package_version.py` itself, so it applies identically whether the skill/agents are driven by Claude Code or GitHub Copilot.

**PromptPlus is different: this plugin only supports PromptPlus 6.0 and later.** Its 5.x line is being discontinued, so `resolve_package_version.py` is called with `--min-major-version 6` for PromptPlus specifically (never for ConsolePlus.net). A project on PromptPlus below 6.0 gets a plain "not supported, please upgrade" from the skill and both agents - not a degraded fallback. This also happens to be exactly right for the docs: PromptPlus's per-control documentation structure (`docs/controls/`, `global-behaviors.md`, `adr/`) was introduced at `v6.0.0-Beta1` and does not exist on any 5.x tag - the version floor and the doc-structure boundary line up, so there is no case left where a supported install has unstructured docs.

**As of this writing, `6.0.0-rc1` is published and is the current `latest_acceptable_version`** for PromptPlus - the steady state is now the normal case. Before it shipped, `resolve_package_version.py` had to handle the gap gracefully (an outright error with nothing installed either, or `status: "no-qualifying-version-published-yet"` with an unaccepted beta already installed) - that logic still exists and still runs correctly if it's ever needed again (e.g. a future unlisting), but it's the exception now, not the default.

## Prerequisites

- `python3` or `python` on `PATH` - both scripts are plain-stdlib Python (no `pip install` needed). On Claude Code, the hook fails **open** (the tool call still proceeds) if neither is found, rather than blocking you on a missing interpreter - but not silently: Claude Code surfaces a visible "hook error" notice with the first line of stderr. On Windows specifically, this can trip on the default `python`/`python3` **App Execution Alias** stubs Windows ships out of the box (present on `PATH` even with no real interpreter installed) - `command -v python3` finds the stub and the hook runs it, but the stub itself exits non-zero with "Python was not found; run without arguments to install from the Microsoft Store...", which is what shows up in that notice. Disabling those aliases (Settings > Apps > Advanced app settings > App execution aliases) once a real interpreter is installed avoids the noise. On GitHub Copilot, there is no hook to fail open - a missing interpreter simply makes the `python`/`python3` invocations documented in the skill/agents fail, and the assistant should say so plainly rather than guess.
- `bash` on `PATH` for the Claude Code hook commands (Git Bash on Windows). Not needed for the GitHub Copilot integration, which has no hook.
- Network access to `api.nuget.org` and `api.github.com`/`raw.githubusercontent.com` for version resolution and (uncached) doc fetches - the skill degrades to a direct fetch on `main` with a stated caveat if `python`/`python3` is unavailable, but the network calls themselves have no offline fallback. Once a given repo+ref+path has been fetched once, later requests for it are served from the local doc cache with no network call at all.

## Versioning

Applies to the Claude Code plugin only - `copilot/` has no version/update mechanism of its own (see [GitHub Copilot](#github-copilot)). `plugin.json`'s `version` and the matching entry in `marketplace.json` must be bumped together on every meaningful change - Claude Code only picks up an update when that version string changes.
