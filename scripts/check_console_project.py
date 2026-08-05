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
"""

import json
import os
import re
import sys
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


def strip_ns(tag):
    return tag.rsplit("}", 1)[-1]


def parse_csproj(path):
    """Returns a dict describing the project, or None if unparseable."""
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
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
    for el in root.iter():
        tag = strip_ns(el.tag)
        text = (el.text or "").strip()
        if tag == "OutputType" and text:
            info["output_type"] = text.lower()
        elif tag == "UseWindowsForms" and text.lower() == "true":
            info["use_winforms"] = True
        elif tag == "UseWPF" and text.lower() == "true":
            info["use_wpf"] = True
        elif tag == "FrameworkReference":
            include = el.attrib.get("Include", "")
            if include.strip().lower() == "microsoft.aspnetcore.app":
                info["has_aspnetcore_frameworkref"] = True
        elif tag == "ProjectReference":
            include = el.attrib.get("Include")
            if include:
                info["project_references"].append(include)
    return info


def normalize_ref(csproj_path, include_value):
    """Resolves a <ProjectReference Include="..."/> path to an absolute, normalized path."""
    ref_path = (csproj_path.parent / include_value.replace("\\", "/")).resolve()
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
    if info["sdk"] in NON_CONSOLE_SDKS:
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
        current = parent
    return (git_root or start_dir), []


def find_all_csproj(scope_root):
    results = []
    for dirpath, dirnames, filenames in os.walk(scope_root):
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


def project_reachable_from_console(local_path, all_projects_by_path):
    """BFS over the reverse ProjectReference graph: is `local_path` itself a console
    entry, or is it (transitively) referenced by some project that is?
    """
    if local_path in all_projects_by_path and is_console_entry(all_projects_by_path[local_path]):
        return True

    # reverse_deps[target] = [projects that reference target]
    reverse_deps = {}
    for proj_path, info in all_projects_by_path.items():
        for raw_ref in info["project_references"]:
            target = normalize_ref(proj_path, raw_ref)
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

    csproj_paths = find_all_csproj(scope_root)

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
        if project_reachable_from_console(local_resolved, all_projects_by_path):
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


def main():
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, OSError):
        payload = {}

    event = payload.get("hook_event_name") or ""

    if event == "PreToolUse":
        skill_name = (payload.get("tool_input") or {}).get("skill")
        if skill_name != SKILL_NAME:
            return  # not our skill - silent no-op, exit 0

    cwd = payload.get("cwd") or os.getcwd()
    decision, reason = evaluate(cwd)

    if decision == "allow":
        return  # silent allow, exit 0

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
