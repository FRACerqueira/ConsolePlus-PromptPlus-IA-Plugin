[← Back to README](../README.md) · [← Back to How to use](how-to-use.md)

# How to use with GitHub Copilot

This page is for the person actually building a .NET console app - not for maintaining this repo.
If you haven't set up the Copilot integration yet, do that first: [GitHub Copilot
setup](../README.md#github-copilot) (copying `copilot/skills/`, `copilot/agents/`, and this plugin's
`scripts/` into your repo's `.github/`). Come back here once that's done.

All examples assume **PromptPlus 6.0+** - the version this plugin supports going forward (its 5.x
line is being discontinued) - and are verified against the current published releases,
**PromptPlus `6.0.0-rc1`** and **ConsolePlus.net `1.0.0-rc1`**. See the last scenario below if your
project hasn't upgraded yet.

Two things to know about how this works on Copilot before you start:
- The `select-promptplus-control` **skill** (deciding the layer, the control, and the implementation)
  is picked up automatically - you don't select anything, just ask, the same way you would with
  Claude Code.
- The two **agents** (`promptplus-auditor`, `promptplus-precommit-check`) need to be selected from
  Copilot Chat's agent picker in **Agent mode** before you ask your question - they don't run just by
  mentioning what they do in plain text.
- There is **no hook** gating any of this to console-type projects the way there is on Claude Code -
  see the "Outside a console project" scenario below for what that means in practice.

## The everyday case: ask for a feature, get a control

> "Add a menu so the user picks the target environment: Dev, Staging, or Prod."

Copilot will, in order:
1. Resolve which PromptPlus/ConsolePlus version your project has installed (via
   `resolve_package_version.py`, run through the `runCommands` tool) and pin every doc lookup to the
   matching tag - not to whatever's newest on GitHub.
2. Confirm `PromptPlus.Controls` is the right layer for this (not raw `ConsolePlus` output, not a
   widget).
3. Check whether an interactive control can even run at that call site - if the surrounding code path
   could run under CI/redirected input, this step catches it before a control gets picked at all (see
   the CI scenario below).
4. Land on `Select<string>` - one item, from a flat, known list - rather than `TableSelect` (tabular)
   or `TreeSelect` (hierarchical), and say why.
5. Fetch *only* `Select`'s own docs (not all 21 controls') and write the code using its real fluent
   API - `AddItems`, `Default`, `.Run()` - not a guessed-at signature.

What actually lands in your file - real `Select<T>` API, not a paraphrase of it:

```csharp
using PromptPlusLibrary;

var env = PromptPlus.Controls
    .Select<string>("Target environment")
    .AddItems(["Dev", "Staging", "Prod"])
    .Run();

if (!env.IsAborted)
    PromptPlus.Console.WriteLine($"Deploying to [Yellow]{env.Content}[/]");
```

## When there's nothing interactive to pick - pure ConsolePlus

> "Print a section header before this report, and color the total line."

No keyboard input is involved here, so Step 1 lands on **ConsolePlus** itself, not
`PromptPlus.Controls` - a dash/banner widget for the header, styled output for the line. This works
identically whether or not the project also references PromptPlus, since `PromptPlus.Console` and
`PromptPlus.Widgets` are the same ConsolePlus driver under a different entry point.

```csharp
using ConsolePlusLibrary;

ConsolePlus.Dash("Monthly Report", Color.Yellow, DashOptions.DoubleBorderUpDown);
ConsolePlus.Console.WriteLine($"[Green]Total: {total:C}[/]");
```

## When the right control is genuinely ambiguous

> "Let the user check off which of these servers to restart."

Could be `MultiSelect` (flat list), `TableMultiSelect` (if the servers have several meaningful
columns - region, status, uptime), or `TreeMultiSelect` (if they're grouped hierarchically). Rather
than silently guessing, Copilot states its pick and the reason ("flat `MultiSelect`, since you
described a plain list") so you can correct it in one line if the data shape is actually richer than
described.

## When a control can't safely run where you're asking for it

> "Show the user a confirmation before this scheduled task deletes old files."

If that code runs inside an `IHostedService` hosted by a plain console app (`Microsoft.NET.Sdk`,
`OutputType Exe`, using the Generic Host) with no real keyboard attached, `Confirm.Run()` would throw
`InvalidOperationException` immediately the moment input is redirected - PromptPlus's own documented
behavior, not a guess. Copilot flags this *before* writing the code and steers you toward a `Live`
control (`ProgressBar`/`Task`/`MultiTasks`/`Timer` - the four exempt from that guard) or asks whether
the call site is actually reachable from an interactive terminal after all.

Note this is different from a project scaffolded from the **Worker Service template**
(`Microsoft.NET.Sdk.Worker`) - that `OutputType` is treated as non-console. On Claude Code the hook
declines the skill outright for that project before any of this reasoning happens; on Copilot,
where there's no hook, the skill's own "Scope check" step is what's supposed to catch it - see the
next scenario.

## Outside a console project, there's no hook to stop it

Claude Code has a companion hook that declines `select-promptplus-control` outright for a non-console
project (a web app, a WinForms/WPF app, a class library with no console entry point), before any
PromptPlus-specific reasoning happens. **GitHub Copilot has no equivalent hook mechanism** - the
skill's own "Scope check" step is the only thing standing between a non-console project and a wrong
recommendation. If you ask for a menu inside an ASP.NET Core project, say so plainly ("this is a web
app, not a console app") so the skill can decline correctly, rather than relying on it to notice on
its own. If you copied `scripts/check_console_project.py` alongside the skill, you can also ask
Copilot to run it directly via `runCommands` for the same deterministic answer the Claude Code hook
would have given.

## Auditing code that already uses these libraries

Switch to the **promptplus-auditor** agent, then ask:
> "Audit our PromptPlus usage in this repo."

You'll get a full, whole-codebase pass for the redirected-input guard gap, unchecked `.IsAborted`
reads, confused `ConsolePlusLibrary`/`PromptPlusLibrary` `IWidgets` usage, global `Config` mutated
where a per-call `.Options()` override belonged, control choices that fight their own documented
alternatives, and abort-key overrides with no stated reason - each finding checked against the live,
version-pinned docs, not memory. Read-only; produces a report, edits nothing.

## Catching the cheap stuff before it ships

Switch to the **promptplus-precommit-check** agent right before a commit or PR, then ask:
> "Check my PromptPlus changes."

It's scoped to just the diff, checking only the two bug-risk patterns above that are cheap enough to
verify without a network call. This agent is meant to run automatically in the background right
before a commit/PR too, the way it does on Claude Code - whether your Copilot surface supports that
non-blocking, launch-and-continue invocation depends on your setup; asking directly always works.

## If your project is still on PromptPlus 5.x

This plugin supports **PromptPlus 6.0 and later only** - the 5.x line is being discontinued. If your
project's `PackageReference` resolves to a 5.x version (still what `dotnet add package PromptPlus`
gives you today, without `--prerelease`):

> "Add a masked input for a phone number."

Copilot stops for `PromptPlus.Controls` guidance and says so plainly - "PromptPlus 5.0.8 is below
this skill's minimum supported version (6.0); control-selection guidance doesn't apply until you
upgrade" - rather than quietly answering from an unsupported version's API. There's no degraded
"proceed anyway" mode. ConsolePlus-only work (rendering, widgets) is unaffected, since this floor is
PromptPlus-specific.

## If something goes wrong

- **The agent isn't in the picker** - confirm `copilot/agents/*.agent.md` actually landed in your
  repo's `.github/agents/` (not just `copilot/agents/` - that's this repo's source copy, not a live
  location).
- **A tool gets rejected / "unknown tool" error** - Copilot's built-in tool names change over time;
  check the `tools:` list at the top of the relevant `.agent.md` file against your Copilot version's
  current built-in tools and adjust if needed.
- **"No such file or directory" running `resolve_package_version.py`/`fetch_doc.py`/`check_console_project.py`**
  - you likely copied `copilot/skills/` and `copilot/agents/` but not this plugin's `scripts/`
  directory, or placed it somewhere other than your repo root. See [GitHub Copilot
  setup](../README.md#github-copilot).
- **A command fails with an odd error instead of a normal message, or PromptPlus.Controls guidance is
  refused outright** - your PromptPlus version is probably below 6.0. See the PromptPlus 5.x scenario
  above.

Using Claude Code instead? See [how-to-use-claude-code.md](how-to-use-claude-code.md).

[← Back to README](../README.md) · [← Back to How to use](how-to-use.md)
