#!/usr/bin/env python3
"""
Gate for the "select-promptplus-control" skill: only allow it in .NET
console-type projects (an entry point with OutputType Exe/WinExe, not a web
app or a library with no console entry point anywhere in scope).

Invoked as a Claude Code hook on two distinct paths, since a skill can be
reached either way:
  - PreToolUse, matcher "Skill" - fires for ANY skill the model calls, so this
    script filters on tool_input["skill"] itself; it is a silent no-op (exit 0,
    no output) for every other skill.
  - UserPromptExpansion, matcher "select-promptplus-control" - fires only for
    a user-typed /select-promptplus-control, already scoped by the matcher.

Decision output uses both the generic, all-hooks mechanism (`continue`false` +
`stopReason`) and the PreToolUse-specific one (`hookSpecificOutput.
permissionDecision`) - the generic one is the documented fallback for events
(like UserPromptExpansion) that don't have their own specific field.

Console-project detection walks the project graph rather than checking only
the current directory's .csproj, because a class library with no OutputType
that hosts PromptPlus/ConsolePlus calls, but is referenced by a console Exe
elsewhere in the same solution/repo, is a legitimate case this gate must not
reject.

Also runnable directly (not as a hook) - e.g. GitHub Copilot's `runCommands`
tool has no hook runtime to call this script for it, so the Copilot port of
select-promptplus-control's SKILL.md tells the assistant to run it by hand
instead. With no `hook_event_name` on stdin (or no stdin at all), `main()`
detects that and prints a plain `{"decision": "allow"|"deny"|"ask", "reason":
...}` result instead of the Claude Code hook envelope below, which nothing
outside a real hook runtime knows how to interpret.
"""

import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

SKILL_NAME = "select-promptplus-control"

NON_CONSOLE_SDKS = {
    "microsoft.net.sdk.web",
    "microsoft.net.sdk.razor",
    "microsoft.net.sdk.blazorwebassembly",
    "microsoft.net.sdk.worker",  # background service, not an interactive console app
}
EXCLUDED_DIR_NAMES = {"bin", "obj", "node_modules", ".git"}

# A .csproj bigger than this is almost certainly not a hand-written project
# file - skip it rather than hand an unbounded file to ET.parse (which has no
# built-in protection against a maliciously crafted entity-expansion bomb).
MAX_CSPROJ_BYTES = 5 * 1024 * 1024

# Backstops for evaluate()'s filesystem walk. A brand-new project created
# outside a git repo with no .sln yet (a real, doc-supported scenario for
# this plugin) makes find_scope_root fall all the way back to start_dir, and
# find_all_csproj then walks the whole tree from there - on a very deep or
# very wide directory (or, pathologically, the filesystem root), that walk
# could otherwise run past the hook's own 15s timeout in hooks/hooks.json.
MAX_SCOPE_WALK_DEPTH = 60
MAX_SCAN_SECONDS = 8
MAX_SCAN_DIRS = 20000


class ScanTooLarge(Exception):
    """Raised when find_all_csproj gives up rather than risk hanging past the
    hook's timeout - evaluate() turns this into "ask" (escalate to a human
    with a narrower directory), never a silent "deny" or a silent partial
    scan that could wrongly reject a legitimate console project."""


def strip_ns(tag):
    return tag.rsplit("}", 1)[-1]


def parse_csproj(path):
    """Returns a dict describing the project, or None if unparseable.

    OutputType (and the two GUI flags) are read PropertyGroup-by-PropertyGroup
    rather than via one flat root.iter() pass, so that a value from an
    unconditioned <PropertyGroup> (no Condition="..." attribute - the normal,
    always-applies case) always wins over one from a conditioned group (e.g.
    a per-TargetFramework or per-Configuration override), instead of just
    "whichever element appears last in the file". This plugin does not
    evaluate MSBuild Condition expressions - a conditioned-only project still
    falls back to "last one wins" among those, since there's no way to know
    which condition would actually be true at build time without a real
    MSBuild evaluation.
    """
    try:
        if path.stat().st_size > MAX_CSPROJ_BYTES:
            return None
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError):
        return None

    sdk = (root.attrib.get("Sdk") or "").strip().lower()
    info = {
        "path": path,
        "sdk": sdk,
        "output_type": None,
        "use_winforms": False,
        "use_wpf": False,
        "has_aspnetcore_frameworkref": False,
        "project_references": [],
    }

    output_type_is_conditioned = True  # nothing set yet - let the first hit win regardless
    for pg in root.iter():
        if strip_ns(pg.tag) != "PropertyGroup":
            continue
        is_conditioned = "Condition" in pg.attrib
        for el in pg:
            child_tag = strip_ns(el.tag)
            text = (el.text or "").strip()
            if child_tag == "OutputType" and text:
                if info["output_type"] is None or (output_type_is_conditioned and not is_conditioned):
                    info["output_type"] = text.lower()
                    output_type_is_conditioned = is_conditioned
            elif child_tag == "UseWindowsForms" and text.lower() == "true":
                info["use_winforms"] = True
            elif child_tag == "UseWPF" and text.lower() == "true":
                info["use_wpf"] = True

    for el in root.iter():
        tag = strip_ns(el.tag)
        if tag == "FrameworkReference":
            include = el.attrib.get("Include", "")
            if include.strip().lower() == "microsoft.aspnetcore.app":
                info["has_aspnetcore_frameworkref"] = True
        elif tag == "ProjectReference":
            include = el.attrib.get("Include")
            if include:
                info["project_references"].append(include)
    return info


def normalize_ref(csproj_path, include_value, solution_dir=None):
    """Resolves a <ProjectReference Include="..."/> path to an absolute, normalized path.

    Only the `$(SolutionDir)` MSBuild macro is expanded (a common pattern in
    larger, multi-project solutions) - `solution_dir` is the directory
    find_scope_root actually resolved (the one holding the .sln/.slnx, when
    one was found). Any other macro (a custom MSBuild property, etc.) is left
    as literal text, same as before this function existed - it simply won't
    match a real file's resolved path, which is a harmless miss (no reverse-
    dependency edge added for it), not a crash or a false positive.
    """
    value = include_value.replace("\\", "/")
    if solution_dir is not None:
        value = re.sub(
            r"\$\(SolutionDir\)",
            str(solution_dir).rstrip("/\\") + "/",
            value,
            flags=re.IGNORECASE,
        )
    ref_path = (csproj_path.parent / value).resolve()
    return ref_path


def is_console_entry(info):
    """Console-type entry point: OutputType Exe, plain SDK, no GUI/web markers.

    WinExe is deliberately NOT accepted here - it is the conventional
    OutputType for WinForms/WPF apps (a console app that just wants no
    console window is rare enough, and indistinguishable from a GUI app by
    OutputType alone, that treating WinExe as "not console" is the safer
    default). This is a known simplification, not a certainty.
    """
    if info is None or info["output_type"] != "exe":
        return False
    # Sdk="A;B" (combining multiple SDKs) is valid MSBuild syntax - split
    # before membership-checking rather than comparing the whole string.
    sdk_parts = {part.strip() for part in info["sdk"].split(";") if part.strip()}
    if sdk_parts & NON_CONSOLE_SDKS:
        return False
    if info["use_winforms"] or info["use_wpf"]:
        return False
    if info["has_aspnetcore_frameworkref"]:
        return False
    return True


def find_scope_root(start_dir):
    """Nearest ancestor with .sln/.slnx file(s), else nearest ancestor with .git, else start_dir.

    Returns (scope_root, conflicting_solution_files). conflicting_solution_files
    is non-empty when the resolved directory has more than one .sln/.slnx file
    (e.g. a repo mid-migration from .sln to .slnx, or several unrelated
    solutions) - there is no reliable way to auto-pick which one defines "the"
    project scope, so the caller must escalate rather than guess.
    """
    current = start_dir
    git_root = None
    depth = 0
    while True:
        try:
            entries = list(current.iterdir())
        except OSError:
            entries = []
        sln_files = [e for e in entries if e.is_file() and e.suffix in (".sln", ".slnx")]
        if len(sln_files) > 1:
            return current, sln_files
        if len(sln_files) == 1:
            return current, []
        if git_root is None and any(e.name == ".git" for e in entries):
            git_root = current
        parent = current.parent
        if parent == current:
            break
        depth += 1
        if depth > MAX_SCOPE_WALK_DEPTH:
            break  # pathological mount/symlink depth - stop climbing, fall back below
        current = parent
    return (git_root or start_dir), []


def find_all_csproj(scope_root):
    results = []
    deadline = time.monotonic() + MAX_SCAN_SECONDS
    dirs_visited = 0
    for dirpath, dirnames, filenames in os.walk(scope_root):
        dirs_visited += 1
        if dirs_visited > MAX_SCAN_DIRS or time.monotonic() > deadline:
            raise ScanTooLarge(
                f"Directory tree under {scope_root} is too large to scan reliably "
                f"(stopped after {dirs_visited} directories) for '{SKILL_NAME}' - "
                f"re-run from a more specific project directory."
            )
        dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIR_NAMES]
        for f in filenames:
            if f.lower().endswith(".csproj"):
                results.append(Path(dirpath) / f)
    return results


def find_local_project(cwd, scope_root):
    """Nearest ancestor of cwd (up to and including scope_root) containing exactly one .csproj."""
    current = cwd
    while True:
        try:
            csprojs = [e for e in current.iterdir() if e.is_file() and e.suffix.lower() == ".csproj"]
        except OSError:
            csprojs = []
        if len(csprojs) == 1:
            return csprojs[0]
        if current == scope_root:
            break
        parent = current.parent
        if parent == current:
            break
        current = parent
    return None


def project_reachable_from_console(local_path, all_projects_by_path, solution_dir=None):
    """BFS over the reverse ProjectReference graph: is `local_path` itself a console
    entry, or is it (transitively) referenced by some project that is?
    """
    if local_path in all_projects_by_path and is_console_entry(all_projects_by_path[local_path]):
        return True

    # reverse_deps[target] = [projects that reference target]
    reverse_deps = {}
    for proj_path, info in all_projects_by_path.items():
        for raw_ref in info["project_references"]:
            target = normalize_ref(proj_path, raw_ref, solution_dir=solution_dir)
            reverse_deps.setdefault(target, []).append(proj_path)

    visited = {local_path}
    queue = [local_path]
    while queue:
        node = queue.pop()
        for referencer in reverse_deps.get(node, []):
            if referencer in visited:
                continue
            visited.add(referencer)
            info = all_projects_by_path.get(referencer)
            if info and is_console_entry(info):
                return True
            queue.append(referencer)
    return False


def evaluate(cwd_str):
    """Returns (decision, reason) where decision is "allow", "deny", or "ask".

    "ask" means this script deliberately did not decide - the scope itself is
    ambiguous (conflicting solution files), so the choice is escalated rather
    than silently guessed.
    """
    cwd = Path(cwd_str).resolve()
    scope_root, conflicting_sln = find_scope_root(cwd)

    if conflicting_sln:
        names = ", ".join(sorted(f.name for f in conflicting_sln))
        return "ask", (
            f"Found multiple solution files in {scope_root} ({names}) - can't determine which one "
            f"defines the project scope for '{SKILL_NAME}'. Please clarify which solution applies, "
            f"or re-run from a more specific project directory."
        )

    try:
        csproj_paths = find_all_csproj(scope_root)
    except ScanTooLarge as exc:
        return "ask", str(exc)

    if not csproj_paths:
        return "deny", (
            f"No .csproj found under {scope_root} - this doesn't look like a .NET project. "
            f"'{SKILL_NAME}' only applies to .NET console applications."
        )

    all_projects_by_path = {}
    for p in csproj_paths:
        info = parse_csproj(p)
        if info:
            all_projects_by_path[p.resolve()] = info

    local_project = find_local_project(cwd, scope_root)

    if local_project is not None:
        local_resolved = local_project.resolve()
        if local_resolved not in all_projects_by_path:
            return "deny", f"Could not parse {local_project} as a .csproj."
        if project_reachable_from_console(local_resolved, all_projects_by_path, solution_dir=scope_root):
            return "allow", None
        return "deny", (
            f"'{local_project.name}' is not a console entry point (OutputType Exe, non-web/GUI SDK) "
            f"and is not referenced by any console entry point found under {scope_root}. "
            f"'{SKILL_NAME}' only applies to console-type .NET projects."
        )

    # No single project maps to cwd (e.g. cwd is a multi-project repo/solution
    # root) - fall back to: allow if the scope contains at least one console
    # entry point anywhere.
    if any(is_console_entry(info) for info in all_projects_by_path.values()):
        return "allow", None
    return "deny", (
        f"No console entry point (OutputType Exe, non-web/GUI SDK) found among the "
        f"{len(all_projects_by_path)} .csproj file(s) under {scope_root}. "
        f"'{SKILL_NAME}' only applies to console-type .NET projects."
    )


def read_stdin_payload():
    """Reads and parses the hook JSON payload from stdin, or {} if there is
    none to read.

    Skips the read entirely when stdin is a live terminal (isatty()) - a
    manual/direct invocation of this script (no pipe, no redirect) would
    otherwise block forever on sys.stdin.read() waiting for input that will
    never arrive, since nothing is going to close or redirect that terminal's
    stdin for us.
    """
    try:
        if sys.stdin is None or sys.stdin.isatty():
            return {}
        raw = sys.stdin.read()
        return json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, OSError):
        return {}


def main():
    payload = read_stdin_payload()
    event = payload.get("hook_event_name") or ""

    if event == "PreToolUse":
        skill_name = (payload.get("tool_input") or {}).get("skill")
        if skill_name != SKILL_NAME:
            return  # not our skill - silent no-op, exit 0

    cwd = payload.get("cwd") or os.getcwd()
    decision, reason = evaluate(cwd)

    if not event:
        # No Claude Code hook event name on stdin - this is a direct/manual
        # invocation (GitHub Copilot's runCommands tool, or a human running
        # this script by hand), not a hook callback. Always print a plain,
        # tool-agnostic result - including on "allow", which the real hook
        # path below deliberately leaves silent - since there is no hook
        # runtime here to infer a meaning from silence or from the
        # Claude-Code-specific envelope used below.
        print(json.dumps({"decision": decision, "reason": reason}))
        return

    if decision == "allow":
        return  # silent allow, exit 0 - Claude Code hook contract

    if decision == "ask" and event == "PreToolUse":
        # "ask" (surface the normal permission prompt to the actual user) is
        # only confirmed for PreToolUse's hookSpecificOutput.permissionDecision.
        # Don't set continue:false/stopReason here - those mean "block", which
        # this isn't; this is "let a human decide", not "deny".
        output = {
            "systemMessage": reason,
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "ask",
                "permissionDecisionReason": reason,
            },
        }
        print(json.dumps(output))
        return

    # decision == "deny", or decision == "ask" on an event with no confirmed
    # "ask" mechanism (UserPromptExpansion) - block outright rather than
    # silently guess, and say why in the message the user actually sees.
    output = {
        "continue": False,
        "stopReason": reason,
        "systemMessage": reason,
        "hookSpecificOutput": {
            "hookEventName": event or "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        },
    }
    print(json.dumps(output))


if __name__ == "__main__":
    # Fail OPEN, always exit 0: a bug or an unreadable file in this detector
    # must never lock the user out of a legitimate skill, and hooks.json
    # relies on this script's exit code always being 0 to pick the right
    # python3/python fallback via shell `&&`/`||` without double-running it.
    try:
        main()
    except Exception as exc:
        print(f"select-promptplus-control gate: ignoring internal error ({exc})", file=sys.stderr)
