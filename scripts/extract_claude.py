#!/usr/bin/env python3
"""Claude Code (experimental): extract sessions of the target repo from ~/.claude/projects/.
Layout: <munged-cwd>/<session-uuid>.jsonl; each line carries {type, message{role, content[]},
timestamp, cwd, sessionId, isSidechain}. Tool results arrive as tool_result items inside
user records, linked by tool_use_id. Formats drift between versions — verify a sample first
(inspect with: head -c 2000 <file>)."""
import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (matches_repo, new_session, add_tool_call, mark_tool_result,  # noqa: E402
                    head, open_outputs, dump, iso_duration, is_tool_synthetic)


def iter_texts(content):
    if isinstance(content, str):
        yield "text", content
    elif isinstance(content, list):
        for c in content:
            if isinstance(c, dict):
                yield c.get("type", "?"), c


def file_matches_repo(fp, repo):
    """Match on the cwd inside each session's own records: the munged dir name and
    sibling files are not proof (a project dir can hold sessions of several repos).
    Scan until a truthy cwd — leading records may carry cwd: null."""
    try:
        with open(fp, encoding="utf-8", errors="replace") as f:
            for line in f:
                if '"cwd"' not in line:
                    continue
                try:
                    cwd = json.loads(line).get("cwd")
                except json.JSONDecodeError:
                    continue
                if cwd:
                    return matches_repo(cwd, repo)
    except OSError:
        pass
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--out", default="agentic-audit")
    ap.add_argument("--root", default=os.path.join(os.path.expanduser("~"), ".claude", "projects"))
    ap.add_argument("--limit-sessions", type=int, default=None,
                    help="process only the first N matched sessions (quick probe)")
    args = ap.parse_args()

    jsonl, log = open_outputs(args.out, "claude")
    n_out = 0
    for fp in sorted(glob.glob(os.path.join(args.root, "*", "*.jsonl"))):
        if args.limit_sessions and n_out >= args.limit_sessions:
            break
        if not file_matches_repo(fp, args.repo):
            continue
        rec = new_session("claude", os.path.basename(fp).replace(".jsonl", ""))
        first_ts = last_ts = None
        with open(fp, encoding="utf-8", errors="replace") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = r.get("timestamp")
                if ts:
                    first_ts = first_ts or ts
                    last_ts = ts
                rec["directory"] = r.get("cwd") or rec["directory"]
                if r.get("isSidechain") and rec.get("parent_id") is None:
                    rec["parent_id"] = "sidechain"
                typ = r.get("type")
                msg = r.get("message") or {}
                if typ == "user":
                    for ct, c in iter_texts(msg.get("content")):
                        if ct == "text":
                            txt = c if isinstance(c, str) else c.get("text", "")
                            if txt.strip() and not is_tool_synthetic(txt, ("<local-command",)):
                                rec["n_user_msgs"] += 1
                                rec["user_messages"].append({"ts": ts, "chars": len(txt), "text": txt[:8000]})
                        elif ct == "tool_result":
                            inner = c.get("content")
                            o = inner if isinstance(inner, str) else "\n".join(
                                x.get("text", "") for x in inner if isinstance(x, dict)) if isinstance(inner, list) else ""
                            mark_tool_result(rec, c.get("tool_use_id", ""), o, is_error=c.get("is_error"))
                elif typ == "assistant":
                    rec["n_assistant_msgs"] += 1
                    if (msg.get("model") or "") and msg["model"] not in rec["models"]:
                        rec["models"].append(msg["model"])
                    u = msg.get("usage") or {}
                    if rec.get("tokens") is None:
                        rec["tokens"] = {"input": 0, "output": 0, "reasoning": 0, "cached": 0}
                    tk = rec["tokens"]
                    tk["input"] += u.get("input_tokens", 0) or 0
                    tk["output"] += u.get("output_tokens", 0) or 0
                    tk["cached"] += u.get("cache_read_input_tokens", 0) or 0
                    for ct, c in iter_texts(msg.get("content")):
                        if ct == "text":
                            txt = c if isinstance(c, str) else c.get("text", "")
                            if txt.strip():
                                rec["assistant_texts"].append({"ts": ts, "chars": len(txt), "head": head(txt, 300)})
                        elif ct == "tool_use":
                            add_tool_call(rec, ts, c.get("name", ""), c.get("id", ""), c.get("input") or {})
        rec["t_start"], rec["t_end"] = first_ts, last_ts
        rec["duration_s"] = iso_duration(first_ts, last_ts)
        try:
            dump(rec, jsonl)
            n_out += 1
        except Exception as e:
            print(f"{fp}: {e}", file=log)
    jsonl.close()
    log.close()
    print(f"claude: {n_out} sessions -> {args.out}/data/claude_sessions.jsonl")
    if n_out == 0:
        print("hint: verify the storage layout for your Claude Code version (see SKILL.md)")


if __name__ == "__main__":
    main()
