"""Shared helpers for agentic-usage-analysis extractors."""
import json
import os
from datetime import datetime, timezone

SYNTHETIC_PREFIXES = (
    "<system-reminder", "<env", "<user_instructions", "<environment", "# AGENTS.md",
    "<permissions", "The following is the Codex agent history",
    "<send_user_message_question_reply>", "Continue the same review conversation",
    "<task-notification>", "This session is being continued from a previous conversation",
    "A plan file exists from plan mode",
)

# Agent-generated meta prompts (guardian/approval reviewers, continuation injections)
# share telltale phrases. is_synthetic requires two distinct markers plus a length
# guard: one common word like "assess" must not get a genuine long user message
# discarded, and the check must not assume the user's language.
BOILER_MARKERS = (
    "assess", "evaluate whether", "review the conversation", "the following is",
    "transcript", "conversation history", "guardian", "continuation of the conversation",
)


def norm_path(p):
    return os.path.normcase(os.path.normpath(p)) if p else ""


def matches_repo(path, repo):
    """True when session path equals the repo or lives inside it (any slash style/case)."""
    if not path:
        return False
    p, r = norm_path(path), norm_path(repo)
    return p == r or p.startswith(r + os.sep)


def ms_iso(ms):
    if not ms:
        return None
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")[:-4] + "Z"


def iso_duration(a_iso, b_iso):
    if not a_iso or not b_iso:
        return None
    try:
        a = datetime.fromisoformat(a_iso.replace("Z", "+00:00"))
        b = datetime.fromisoformat(b_iso.replace("Z", "+00:00"))
        return int((b - a).total_seconds())
    except ValueError:
        return None


def head(s, n):
    s = s if isinstance(s, str) else ("" if s is None else json.dumps(s, ensure_ascii=False))
    return s[:n]


def is_synthetic(text):
    t = text.lstrip()
    if t.startswith(SYNTHETIC_PREFIXES):
        return True
    if len(t) > 1200:
        low = t.lower()
        if sum(1 for m in BOILER_MARKERS if m in low) >= 2:
            return True
    return False


def is_tool_synthetic(text, extra_prefixes=()):
    """Extraction-time gate for user messages: tool-specific meta prefixes
    plus the shared conservative heuristic (is_synthetic). Extractors call
    this so n_user_msgs never counts synthetic traffic in the first place."""
    t = text.lstrip()
    return t.startswith(tuple(extra_prefixes)) or is_synthetic(text)


def new_session(tool, session_id, **extra):
    rec = {
        "tool": tool,
        "session_id": session_id,
        "parent_id": extra.get("parent_id"),
        "title": extra.get("title", ""),
        "directory": extra.get("directory", ""),
        "t_start": extra.get("t_start"),
        "t_end": extra.get("t_end"),
        "duration_s": extra.get("duration_s"),
        "n_user_msgs": 0,
        "n_assistant_msgs": 0,
        "n_tool_calls": 0,
        "models": [],
        "user_messages": [],
        "assistant_texts": [],
        "tool_calls": [],
        "n_errors": 0,
        "errors_head": [],
        "tokens": None,
    }
    rec.update({k: v for k, v in extra.items()
                if k not in ("parent_id", "title", "directory", "t_start", "t_end", "duration_s")})
    return rec


def finish_session(rec):
    rec["models"] = sorted(m for m in rec["models"] if m)
    rec["n_errors"] = sum(1 for tc in rec["tool_calls"] if tc.get("is_error"))
    if rec.get("duration_s") is None:
        rec["duration_s"] = iso_duration(rec.get("t_start"), rec.get("t_end"))
    return rec


def add_tool_call(rec, ts, name, call_id, args, status="", exit_code=None, duration_ms=None, is_error=0):
    rec["n_tool_calls"] += 1
    rec["tool_calls"].append({
        "ts": ts, "name": name, "call_id": call_id,
        "args_head": head(args, 200), "out_head": "",
        "exit_code": exit_code, "duration_ms": duration_ms,
        "is_error": is_error, "status": status,
    })


def mark_tool_result(rec, call_id, output_text, is_error=None):
    """Attach an output to the latest matching tool call; flag errors by text heuristics."""
    for tc in reversed(rec["tool_calls"]):
        if tc["call_id"] == call_id:
            tc["out_head"] = head(output_text, 300)
            err = tc.get("is_error", 0)
            if is_error is not None:
                err = 1 if is_error else 0
            elif not err:
                low = output_text[:500].lower()
                if any(k in low for k in ("script failed", "script error", "command failed",
                                          "exit code: 1", "exit code: 2", "exit code: 101",
                                          "panicked", "traceback")):
                    err = 1
            tc["is_error"] = err
            if err and len(rec["errors_head"]) < 40:
                rec["errors_head"].append({"ts": tc["ts"], "head": head(output_text, 250)})
            return True
    return False


def open_outputs(out_dir, tool):
    data_dir = os.path.join(out_dir, "data")
    os.makedirs(data_dir, exist_ok=True)
    jsonl = open(os.path.join(data_dir, f"{tool}_sessions.jsonl"), "w", encoding="utf-8")
    log = open(os.path.join(data_dir, f"{tool}_extract.log"), "w", encoding="utf-8")
    return jsonl, log


def dump(rec, fh):
    fh.write(json.dumps(finish_session(rec), ensure_ascii=False) + "\n")


# ---- tool-call name / shell-command classification (used by compute_stats) ----

def normalize_name(n):
    n = (n or "").lower()
    if n in ("exec", "shell", "local_shell", "bash", "exec_command"): return "shell"
    if n in ("apply_patch", "edit", "write", "str_replace", "multiedit"): return "edit/write"
    if n in ("read", "view", "view_image", "read_file"): return "read"
    if n in ("glob", "ls", "list", "find"): return "list/glob"
    if n in ("grep", "rg", "search", "grep_search"): return "grep/search"
    if n.startswith("update_plan") or n == "todo": return "plan/todo"
    if n in ("task", "agent", "spawn_agent", "subagent"): return "subagent"
    return n


# Generic shell-command classes. Extend per project via compute_stats.py --shell-classes
# (JSON: [["label", ["key", ...]], ...]). Project-specific script names deliberately do
# not live here — they belong to the audited repo, not to the skill.
SHELL_CLASSES_DEFAULT = (
    ("test run", ("runtests", "testplatform", "testfilter", "pytest", "unittest",
                  "jest", "vitest", "npm test", "dotnet test", "go test", "cargo test")),
    ("build/package", ("-buildtarget", "msbuild", "cmake --build", "cargo build",
                       "gradle", "dotnet build", "npm run build", "webpack", "make ")),
    ("git commit", ("git commit", "git merge", "git push")),
    ("git inspect", ("git log", "git diff", "git status", "git show", "git stash")),
    ("python", ("python", "pip ")),
    ("file ops", ("cp ", "mv ", "rm ", "mkdir", "robocopy", "copy ")),
    ("grep/find", ("rg ", "grep", "findstr", "dir ", "ls ", "get-childitem")),
)


def load_shell_classes(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return [(str(label), tuple(str(k) for k in keys)) for label, keys in data]


def classify_shell(args, classes=None):
    a = (args or "").lower()
    for label, keys in (classes or SHELL_CLASSES_DEFAULT):
        if any(k in a for k in keys):
            return label
    return None
