[← Back to README](../README.md) · [← Back to How to use](how-to-use.md)

# How to use with Claude Code

You don't invoke anything by name for the everyday case - just describe what you need in plain
language while working in a console project, the same way you'd ask a colleague. The examples below
are real walkthroughs of what this plugin actually does at each step (not illustrative fluff) - they
match the exact steps in [`skills/select-promptplus-control/SKILL.md`](../skills/select-promptplus-control/SKILL.md).

All examples assume **PromptPlus 6.0+** - the version this plugin supports going forward (its 5.x
line is being discontinued) - and are verified against the current published releases,
**PromptPlus `6.0.0-rc1`** and **ConsolePlus.net `1.0.0-rc1`**. See the last scenario below if your
project hasn't upgraded yet.

## The everyday case: ask for a feature, get a control

> "Add a menu so the user picks the target environment: Dev, Staging, or Prod."

Claude will, in order:
1. Resolve which PromptPlus/ConsolePlus version your project has installed (via `resolve_package_version.py`) and pin every doc lookup to the matching tag - not to whatever's newest on GitHub.
2. Confirm `PromptPlus.Controls` is the right layer for this (not raw `ConsolePlus` output, not a widget).
3. Check whether an interactive control can even run at that call site - if the surrounding code path could run under CI/redirected input, this step catches it before a control gets picked at all (see the CI scenario below).
4. Land on `Select<string>` - one item, from a flat, known list - rather than `TableSelect` (tabular) or `TreeSelect` (hierarchical), and say why.
5. Fetch *only* `Select`'s own docs (not all 21 controls') and write the code using its real fluent API - `AddItems`, `Default`, `.Run()` - not a guessed-at signature.

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

- `ConsolePlus.Dash(text, style, dashOptions, ...)` renders immediately - no `.Run()`/`.Show()`
  needed, it's a widget, not a control.
- Markup (`[Green]...[/]`) is handled by `ConsolePlus.Console`, the same driver `PromptPlus.Console`
  wraps - this is why "the rendering is pure ConsolePlus" holds true even inside a PromptPlus-heavy
  codebase.

## When the right control is genuinely ambiguous

> "Let the user check off which of these servers to restart."

Could be `MultiSelect` (flat list), `TableMultiSelect` (if the servers have several meaningful
columns - region, status, uptime), or `TreeMultiSelect` (if they're grouped hierarchically). Rather
than silently guessing, Claude states its pick and the reason ("flat `MultiSelect`, since you
described a plain list") so you can correct it in one line if the data shape is actually richer than
described.

## When a control can't safely run where you're asking for it

> "Show the user a confirmation before this scheduled task deletes old files."

If that code runs inside an `IHostedService` hosted by a plain console app (`Microsoft.NET.Sdk`,
`OutputType Exe`, using the Generic Host) with no real keyboard attached, `Confirm.Run()` would
throw `InvalidOperationException` immediately the moment input is redirected - PromptPlus's own
documented behavior, not a guess. Claude flags this *before* writing the code and steers you toward
a `Live` control (`ProgressBar`/`Task`/`MultiTasks`/`Timer` - the four exempt from that guard) or
asks whether the call site is actually reachable from an interactive terminal after all.

Note this is different from a project scaffolded from the **Worker Service template**
(`Microsoft.NET.Sdk.Worker`) - that `OutputType` is treated as non-console and the hook declines the
skill outright for that project, before any of this reasoning happens; see the next scenario.

## Outside a console project, the skill doesn't even fire

Ask the same "add a menu" question inside an ASP.NET Core project, or a class library with no
console entry point anywhere in its solution, and the request is declined at the tool-call level,
before any PromptPlus-specific reasoning happens - with a plain explanation of why (not a console
app, or a web app despite `OutputType=Exe`, or no `.sln`/`.csproj` reachable at all). See
[`hooks/hooks.json`](../hooks/hooks.json) if you need to know exactly how this is enforced. (This
hook is Claude Code-specific - GitHub Copilot has no equivalent, see
[how-to-use-copilot.md](how-to-use-copilot.md).)

## Auditing code that already uses these libraries

> "Audit our PromptPlus usage in this repo."

Runs `promptplus-auditor`: a full, whole-codebase pass for the redirected-input guard gap, unchecked
`.IsAborted` reads, confused `ConsolePlusLibrary`/`PromptPlusLibrary` `IWidgets` usage, global
`Config` mutated where a per-call `.Options()` override belonged, control choices that fight their
own documented alternatives, and abort-key overrides with no stated reason - each finding checked
against the live, version-pinned docs, not memory. Read-only; produces a report, edits nothing.

## Catching the cheap stuff before it ships

Right before a commit or PR, `promptplus-precommit-check` runs automatically in the background (no
need to ask) - scoped to just the diff, checking only the two bug-risk patterns above that are cheap
enough to verify without a network call. It doesn't block the commit; it reports back once it's
done, the way a CI check comments on a PR after the push already went through. Ask directly ("check
my PromptPlus changes") to run it in the foreground instead and wait for the answer.

## If your project is still on PromptPlus 5.x

This plugin supports **PromptPlus 6.0 and later only** - the 5.x line is being discontinued. If your
project's `PackageReference` resolves to a 5.x version (still what `dotnet add package PromptPlus`
gives you today, without `--prerelease`):

> "Add a masked input for a phone number."

Claude stops for `PromptPlus.Controls` guidance and says so plainly - "PromptPlus 5.0.8 is below this
skill's minimum supported version (6.0); control-selection guidance doesn't apply until you upgrade"
- rather than quietly answering from an unsupported version's API. There's no degraded "proceed
anyway" mode. ConsolePlus-only work (rendering, widgets) is unaffected, since this floor is
PromptPlus-specific.

---

Using GitHub Copilot instead? See [how-to-use-copilot.md](how-to-use-copilot.md).

[← Back to README](../README.md) · [← Back to How to use](how-to-use.md)
