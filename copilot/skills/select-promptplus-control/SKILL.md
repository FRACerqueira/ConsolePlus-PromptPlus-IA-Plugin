---
name: select-promptplus-control
description: Use when building or modifying a .NET console application that uses, or could use, ConsolePlus and/or PromptPlus - to decide which library layer fits the need, whether an interactive control can even run in the target execution context, which of PromptPlus's 21 controls is the right fit, and how to implement it using that control's actual fluent API. Triggers on requests like "add a menu/prompt/progress bar/date picker to this console app", "which PromptPlus control should I use for X", "is this safe to run under CI or redirected input", "pick between ConsolePlus and PromptPlus", "how do I validate/mask/page this input", or any interactive console input/output design question in a .NET project. Only applies to console-type projects (an entry point with OutputType Exe, not WinExe) - not web apps, not WinForms/WPF apps, not libraries with no console entry point; on GitHub Copilot there is no companion hook to enforce this, so always check the entry point yourself. Supports PromptPlus 6.0+ only (its 5.x line is being discontinued) - a project on an older PromptPlus gets a plain upgrade notice for PromptPlus.Controls guidance, not degraded fallback guidance; ConsolePlus itself has no such floor.
allowed-tools: Bash Read Glob Grep WebFetch
compatibility: Requires this plugin's scripts/ directory (resolve_package_version.py, fetch_doc.py, check_console_project.py) copied alongside this skill (or otherwise reachable at the relative paths used below) - see this repo's README, GitHub Copilot section.
metadata:
  ported-from: skills/select-promptplus-control/SKILL.md (Claude Code plugin, canonical source)
---

> Ported from this repo's Claude Code skill (`skills/select-promptplus-control/SKILL.md`). Content is functionally identical except where adapted for the GitHub Copilot / Agent Skills open standard (agentskills.io/specification): `allowed-tools` syntax; the `WebFetch` → `fetch` tool references (this mapping is this plugin's own best guess, unlike the other Claude→Copilot tool mappings used in `copilot/agents/`, which were checked against Copilot's actual built-in tools - see this repo's README); the frontmatter `description`'s hook clause, since Copilot has no hook mechanism at all (not just "sometimes not installed"); and the "Scope check" section below, which also documents `check_console_project.py`'s plain `{"decision", "reason"}` output when run outside a Claude Code hook. Script invocation paths (`scripts/...py`) are deliberately left as plain relative paths here, unlike the canonical Claude version's `${CLAUDE_PLUGIN_ROOT}`-prefixed paths - `${CLAUDE_PLUGIN_ROOT}` is a Claude Code-specific environment variable with no Copilot equivalent, which is exactly why this repo's README tells you to copy `scripts/` to your repo root: these paths resolve from there. **A caveat on `allowed-tools` above, checked against primary sources**: the Agent Skills spec (agentskills.io/specification) marks this field "Experimental — support may vary between agent implementations," and its own official example uses Claude-style names (`Bash(git:*) Read`) - which is why this line keeps Claude's tool vocabulary rather than translating to `runCommands`/`codebase`/`search`/`fetch` (the *separate* vocabulary the `copilot/agents/*.agent.md` custom agents use - a different GitHub Copilot mechanism, VS Code custom chat agents, not Agent Skills). Concretely, per surface: GitHub Copilot CLI's own docs instead expect a single `shell`/`bash` value here, specifically to skip its terminal-confirmation prompt; VS Code Copilot Chat's SKILL.md validator currently doesn't recognize `allowed-tools` at all (a confirmed VS Code bug, tracked as `microsoft/vscode-copilot-release#14131`), so this line has no effect there either way. Don't assume this field is verified/authoritative for whichever Copilot surface you're actually using - it may do nothing, or may need to become `allowed-tools: bash` instead. There is no generator yet: if the canonical Claude version changes, re-sync this file by hand. **Last synced: 2026-08-07.**

# Choosing and implementing ConsolePlus / PromptPlus controls

This skill is a **router**, not a reference manual. PromptPlus alone has 21 controls with 4 doc
pages each - loading all of it up front would blow the context budget for no benefit on any single
request. Load only what Step 3 tells you to load, for only the control(s) you actually chose.

Do the steps in order. Do not skip Step 0 or Step 2 - they change what the later steps are allowed
to recommend.

## Step 0 - Resolve versions and pin the docs you'll fetch

`scripts/resolve_package_version.py` (in this plugin) tells you which published version is
policy-acceptable, and - separately - which GitHub tag's docs actually match what's installed.
These are **not the same question**: a project on PromptPlus 6.0.1 must get docs for 6.0.1, even if
the policy-recommended upgrade target is a different version.

**This skill supports PromptPlus 6.0 and later only.** PromptPlus's 5.x line is being discontinued;
always pass `--min-major-version 6` for PromptPlus (never for ConsolePlus.net, which has no such
floor). A project on PromptPlus below 6.0 is out of scope for `PromptPlus.Controls` guidance
entirely - see the hard-stop rule below, not a degraded fallback. There is no "proceed anyway with
older docs" path anymore.

Every doc fetch in this skill (Steps 1, 2, 4, 5) goes through `scripts/fetch_doc.py`, not a direct
`fetch` tool call - `fetch` runs page content through a small model with a prompt and returns *that
model's response*, which is fine for "summarize this page" but risks paraphrasing away exact method
signatures and table contents on a reference page. `fetch_doc.py` `curl`s the raw file, caches it
locally keyed by repo+ref+path (a tag's content never changes, so a cache hit is exactly as correct
as a fresh fetch), and prints the local path - Read that path directly for the verbatim content.
Its `--mutable-ref` flag exists for exactly one case: the transitional-period `main` target below,
which *does* move over time and is re-resolved to its current commit on a short TTL rather than
cached under the branch name forever.

```bash
python scripts/resolve_package_version.py \
  --package-id PromptPlus --repo FRACerqueira/PromptPlus \
  --project-path <consumer.csproj or Directory.Packages.props> \
  --docs-probe-path docs/controls --min-major-version 6

python scripts/resolve_package_version.py \
  --package-id ConsolePlus.net --repo FRACerqueira/ConsolePlus \
  --project-path <consumer.csproj or Directory.Packages.props> \
  --docs-probe-path docs/promptplus.md
```

**As of this writing, `6.0.0-rc1` is published and is the current `latest_acceptable_version`** -
the steady state (case 3 below) is the normal path now. Cases 1 and 2 below are still real and worth
knowing (a project can still be on an unsupported <6.0 install, or - hypothetically, if every 6.x
accepted release ever got unlisted from NuGet - back in the gap this plugin was built to handle
gracefully before `6.0.0-rc1` shipped), but they are the exception now, not the default.

**Central Package Management gap:** if `--project-path` pointed at a `.csproj` and the script
returns `installed_version: null`, check the csproj yourself before concluding there's nothing
installed - under CPM the csproj only has `<PackageReference Include="PromptPlus" />` with no
`Version` attribute, and the real version lives in the nearest ancestor `Directory.Packages.props`
(a `<PackageVersion Include="PromptPlus" Version="..."/>` entry). Re-run with `--project-path`
pointed at that file instead. Don't let a null here silently fall back to `latest_acceptable_tag`
for a project that's actually on a different version - that's the exact wrong-docs failure this
two-tag design exists to prevent.

Read the JSON result (or its absence) in this order:

1. **The script exited non-zero with only an `"error"` key (no `docs_tag` at all)** - only possible
   if, hypothetically, no qualifying 6.x release exists on NuGet at all (nothing installed either) -
   not expected now that `6.0.0-rc1` is out, but if it recurs (e.g. a future unlisting), default the
   doc target to `main` (it always carries the real, in-progress 6.0 docs - `docs/controls/` has
   existed on every commit since `v6.0.0-Beta1`) and say that's what you did - don't ask, this isn't
   genuinely ambiguous. Pass `--ref main --mutable-ref` to `fetch_doc.py` for every fetch here - that
   flag is what makes it re-resolve `main`'s current commit on a TTL instead of caching under the
   branch name forever (see the caching note above). TTL defaults to 60 minutes
   (`--main-refresh-minutes 60`) - deliberately short, since `main` is the one ref this plugin treats
   as moving. Pass a larger value only if you've decided that staleness risk doesn't matter for your
   use (e.g. `--main-refresh-minutes 1440` for 24h) - don't change the default silently.
2. **`status` is `"installed-below-minimum-supported"`** - stop for `PromptPlus.Controls` guidance.
   Tell the user plainly: "PromptPlus `<installed_version>` is below this skill's minimum supported
   version (6.0); control-selection guidance doesn't apply until you upgrade." Mention
   `latest_acceptable_version` (currently `6.0.0-rc1`, or whatever is newest and accepted by the time
   you read this) as the concrete upgrade target. Don't offer a degraded "proceed anyway with old
   docs" path. ConsolePlus work (Step 1's other layers) is unaffected - this floor is
   PromptPlus-specific.
3. **Otherwise (the normal case)**: use `docs_tag` as `--ref` for every `fetch_doc.py` call in Steps
   1, 2, 4, 5. `docs_structure` should always come back `"structured"` here (every 6.x tag has the
   full per-control doc set) - if it somehow doesn't, say so rather than silently degrading; don't
   fall back to a legacy-docs path, that no longer exists in this skill. If `latest_acceptable_version`
   is not `null` and `status` is `"outdated"` or `"installed-prerelease-not-accepted"` (e.g. installed
   on a `6.0.0-Beta*` build), mention the upgrade target - no backwards-recommendation risk here
   (`latest_acceptable_version` can no longer be a worse-documented release than what's installed).

If `python`/`python3` isn't available in this environment, say so, skip this step, and fall back to
the `fetch` tool directly on the raw GitHub URL from `main` for Steps 1, 2, 4, 5 - degraded (no
version pin, and the `fetch` tool's summarize-through-a-small-model behavior risks losing exact
signatures/tables, see the fidelity note above) but still better than guessing from memory alone.
Say plainly that both degradations apply when this happens.

## Step 1 - Which layer: ConsolePlus, the two `IWidgets`, or `PromptPlus.Controls`

Don't frame this as "pick a library" - `PromptPlus.Console` *is* the ConsolePlus driver, so using
PromptPlus never excludes ConsolePlus. Frame it as "which layer for this need":

| Need | Layer |
|---|---|
| Styled/colored output, logging, reports | ConsolePlus (`ConsolePlus.Console` / `PromptPlus.Console`, identical) |
| Banners, dashes, section headers, non-interactive widgets | Either `ConsolePlusLibrary.IWidgets` or `PromptPlusLibrary.IWidgets` |
| Cursor/screen control, alternate buffer, raw ANSI | ConsolePlus |
| Any keyboard-driven interactive prompt (menu, input, confirm, ...) | `PromptPlus.Controls` |

**Namespace trap:** `ConsolePlusLibrary.IWidgets` and `PromptPlusLibrary.IWidgets` are two different
types with the same name and different arity - e.g. `Dash` takes 2 params
(`text, style`) on ConsolePlus's `IWidgets` and 5 params (`value, style, dashOptions, extralines,
applycolorbackground`) on PromptPlus's. If the project already references PromptPlus, default to
`PromptPlus.Widgets` for the larger API surface, but say which one you picked and why if it matters
to the code being written.

For anything beyond this table, fetch ConsolePlus's positioning doc pinned to ConsolePlus's
`docs_tag`:
```bash
python scripts/fetch_doc.py --repo FRACerqueira/ConsolePlus --ref <docs_tag> --path docs/promptplus.md
```
then Read the printed `path`.

## Step 2 - Can an interactive control even run here?

Check this **before** picking a control (Step 3) - it can rule out the whole
`PromptPlus.Controls` interactive surface for the current call site.

The rule (verified against PromptPlus's ADR0023 - don't cite the ADR filename itself, its
`V01R02` suffix will drift on the next revision; cite `global-behaviors.md` instead, which is
stable):

> Every interactive control's `Run()` throws `InvalidOperationException` immediately if
> `console.IsInputRedirected` is true - **not** `Profile.Interactive` (that's a CI-provider
> heuristic ConsolePlus sets on startup; it is not the signal this guard checks, and treating it as
> equivalent will produce wrong guidance). This replaces what used to be an indefinite hang with no
> diagnostic.
>
> **Exempt:** `ProgressBar`, `Task`, `MultiTasks`, `Timer` - these are "live" controls that complete
> on their own signal (progress reaching 100%, the wrapped task finishing, the countdown elapsing)
> and never actually wait on a keystroke, so they run fine under redirected input, CI, or a piped
> output. Also exempt: PromptPlus Demo Mode while a scripted key is queued.

Practical implication for this skill: if the target code runs in a context where
`Console.IsInputRedirected` may be true (CI, piped, service/daemon, scheduled task, `dotnet test`
runner, headless container) and the need is progress/status/wait-for-completion rather than a real
choice from the user, steer to the live-control cluster (Step 3, Cluster C) instead of an
interactive one - don't let the user pick `Select`/`Input`/etc. for a code path that will throw in
that context.

For deeper detail (exact exemption logic, Demo Mode interaction), only if `docs_structure` is
`"structured"`:
```bash
python scripts/fetch_doc.py --repo FRACerqueira/PromptPlus --ref <docs_tag> --path docs/global-behaviors.md
```
then Read the printed `path`.

## Step 3 - Which control

21 controls cluster into 3 confusable families plus 8 singles. Getting the cluster right is most of
the decision; within a cluster, the dimensions below almost always settle it. When it's genuinely
ambiguous, **propose your pick and the reason to the user before implementing** - don't silently
guess between, say, `Select` and `TableSelect`.

### Cluster A - pick one-or-more from a list

| Control | Cardinality | Shape |
|---|---|---|
| `Select<T>` | one | flat list |
| `MultiSelect<T>` | several (checkboxes) | flat list |
| `TableSelect<T>` | one | tabular (named columns) |
| `TableMultiSelect<T>` | several | tabular |
| `TreeSelect<T>` | one | hierarchical (expand/collapse) |
| `TreeMultiSelect<T>` | several (tri-state) | hierarchical |

Ask: (1) one item or several? (2) is the data flat, does it have multiple meaningful columns, or is
it naturally nested? That's a 2x3 grid that picks the control outright.

### Cluster B - text entry

| Control | Shape |
|---|---|
| `Input` | free-form plain text |
| `Secret` | free-form, masked while typing (passwords) |
| `MaskEdit` family (12 factories, 4 fluent interfaces) | pattern-constrained: the value must match a template |

The `MaskEdit` family: all 12 factories live on `PromptPlus.Controls`, each `(prompt, description)`:

| Interface | Factories | Mask shape |
|---|---|---|
| `IMaskEditStringControl<string>` | `MaskEdit` | free-form token mask you write via `Mask(...)` |
| `IMaskEditNumberControl<T>` | `MaskInteger`, `MaskLong` | whole-number mask via `NumberFormat(...)` |
| `IMaskEditCurrencyControl<T>` | `MaskDecimal`, `MaskDecimalCurrency`, `MaskDouble`, `MaskDoubleCurrency` | fixed-decimal mask via `NumberFormat(...)` |
| `IMaskEditDateTimeControl<T>` | `MaskDateTime`, `MaskDate`, `MaskDateOnly`, `MaskTime`, `MaskTimeOnly` | culture-ordered date/time mask, no mask string |

Ask: is the value free text (→ `Input`/`Secret`, and is it a credential → `Secret`) or must it match
a fixed shape (phone, price, date, ...) → `MaskEdit` family, then pick the factory by .NET return
type (`decimal` → `MaskDecimal`, `DateOnly` → `MaskDateOnly`, etc).

### Cluster C - live / non-blocking-on-keypress (exempt from Step 2's guard)

| Control | Use when |
|---|---|
| `ProgressBar` | you can report a determinate 0-100% value from your own work |
| `Task` | one operation (sync or async), indeterminate - show it's working |
| `MultiTasks` | several operations, sequential or parallel, each with its own status line |
| `Timer` | suspend for a fixed duration while showing a live countdown |

Ask: determinate progress you drive → `ProgressBar`. One black-box operation → `Task`. Several
independent operations → `MultiTasks`. Pure countdown, no operation attached → `Timer`.

### Singles

| Control | One-liner |
|---|---|
| `Calendar` | interactive monthly grid; user navigates day-by-day, confirms one date |
| `ChartBar` | interactive horizontal bar chart; user navigates/re-sorts/re-layouts, picks one |
| `Confirm` | yes/no; culture-specific Yes/No key, returns immediately |
| `KeyPress` | wait for one keystroke, returns immediately, no Enter needed |
| `File` | lazy-loaded file-system tree; user picks one file or folder |
| `MultiFile` | lazy-loaded file-system tree; user checks several files/folders |
| `Slider` | pick a numeric value by moving a bar between min and max |
| `Switch` | toggle a single boolean on/off with the arrow keys |

`Confirm` vs `KeyPress`: `Confirm` is specifically yes/no with culture-aware keys; `KeyPress` is any
single key you define. A yes/no question is `Confirm` even though `KeyPress` could technically do it.

## Step 4 - Load the implementation details, only for the control(s) you chose

You should only reach this step with `docs_structure: "structured"` - Step 0's rules stop for
`PromptPlus.Controls` guidance before this point whenever the installed version is below 6.0. For
each file, pinned to `docs_tag`:
```bash
python scripts/fetch_doc.py --repo FRACerqueira/PromptPlus --ref <docs_tag> --path docs/controls/<control>/index.md
python scripts/fetch_doc.py --repo FRACerqueira/PromptPlus --ref <docs_tag> --path docs/controls/<control>/methods.md
python scripts/fetch_doc.py --repo FRACerqueira/PromptPlus --ref <docs_tag> --path docs/controls/<control>/operations.md
```
then Read each printed `path`. `<control>` is the lowercase directory name (`select`, `maskedit`,
`tablemultiselect`, ...), not the C# type name. Fetch `styles.md` too only if the user asks about
theming/colors for that control. **Do not fetch docs for controls you didn't choose** - that defeats
the point of routing.

## Step 5 - Best practices while wiring it up

Apply regardless of which control was chosen:

- Every control exposes `.Options(o => ...)` for per-instance overrides (prompt text, description,
  `EnabledAbortKey`, `ShowTooltip`, `HideAfterFinish`, `HideOnAbort`, ...) rather than only global
  `PromptPlus.Config` - prefer `.Options()` when the behavior is specific to one call site, reserve
  `PromptPlus.Config` for app-wide defaults.
- Respect `EnabledAbortKey`/Esc - don't disable it without the user asking; it's the documented,
  expected abort path across every control.
- `HideAfterFinish`/`HideOnAbort` control whether the control's UI stays on screen after
  confirm/abort - relevant for wizards where only the final answers should remain visible.
- Culture (`DefaultCulture`) is applied only during `.Run()` and restored after, even on error -
  don't wrap controls in manual culture save/restore, it's redundant.
- Unhandled exceptions inside a control write to
  `%LocalAppData%/PromptPlus/PromptPlus.error.log` without throwing further - don't add your own
  duplicate logging around `.Run()` for that case unless the user wants app-specific logging too.

For the full property/behavior reference, only if `docs_structure` is `"structured"`:
```bash
python scripts/fetch_doc.py --repo FRACerqueira/PromptPlus --ref <docs_tag> --path docs/global-behaviors.md
```
then Read the printed `path` (same cached file Step 2 may have already fetched - no duplicate cost).

## Scope check

This skill applies to console-type .NET projects only (an entry point with
`<OutputType>Exe</OutputType>`, not `WinExe` - that's the conventional `OutputType` for WinForms/WPF
apps and is deliberately treated as out of scope, see `check_console_project.py`'s
`is_console_entry` - and not `Microsoft.NET.Sdk.Web`). The Claude Code build of this plugin has a
companion hook (`hooks/hooks.json` + `scripts/check_console_project.py`) that enforces this
deterministically before the skill can even be invoked - **GitHub Copilot has no equivalent hook
mechanism**, so this check is always your responsibility here, not just a fallback. Walk up from the
current project to find the one actually run (`dotnet run`), not necessarily the csproj currently
open, since a class library with no `OutputType` hosting PromptPlus calls but consumed by a console
`Exe` is a legitimate case. If you copied `scripts/check_console_project.py` alongside this skill
(see this repo's README, GitHub Copilot section), you can also run it directly via the
`runCommands` tool: with no Claude Code hook payload on stdin, it prints a plain
`{"decision": "allow"|"deny"|"ask", "reason": "..."}` result (instead of the Claude-specific hook
envelope it emits when Claude Code itself invokes it as a hook) - read `decision` directly rather
than treating silence as "allow" or any output at all as "deny". Otherwise apply the rule manually.
If no console entry point is reachable, say this skill doesn't apply and stop.
