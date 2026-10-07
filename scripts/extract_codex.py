#!/usr/bin/env python3
"""Codex: scan ~/.codex/sessions for rollouts of the target repo and extract normalized sessions.
session_id is the shared id from session_meta (NOT the rollout filename): resumed threads span
several rollout files with one session_id; compute_stats.py merges them (field `segments`)."""
import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (matches_repo, new_session, add_tool_call, mark_tool_result,  # noqa: E402
                    head, open_outputs, dump, is_tool_synthetic)

SYNTH_PREFIXES = ("<user_instructions>", "<environment_context>", "<ENVIRONMENT_CONTEXT>",
                  "<turn_context>", "<app-context>", "<permissions", "<user_shell_command>")


def inventory(sessions_root, repo, out_dir):
    files = sorted(glob.glob(os.path.join(sessions_root, "**", "rollout-*.jsonl"), recursive=True))
    rows = []
    for fp in files:
        meta = {}
        try:
            with open(fp, encoding="utf-8", errors="replace") as f:
                for line in f:
                    if '"session_meta"' not in line:
                        continue
                    rec = json.loads(line)
                    if rec.get("type") == "session_meta":
                        p = rec.get("payload", {})
                        src = p.get("source") or {}
                        meta = {
                            "session_id": p.get("session_id", ""),
                            "cwd": p.get("cwd", ""),
                            "timestamp": p.get("timestamp", ""),
                            "originator": p.get("originator", ""),
                            "source": src.get("thread_source") if isinstance(src, dict) else str(src),
                        }
                        break
        except Exception as e:
            print(f"inventory err {fp}: {e}", file=sys.stderr)
            continue
        meta["file"] = fp
        meta["size_bytes"] = os.path.getsize(fp)
        meta["matched"] = matches_repo(meta.get("cwd"), repo)
        rows.append(meta)
    inv = os.path.join(out_dir, "data", "codex_inventory.tsv")
    with open(inv, "w", encoding="utf-8", newline="") as f:
        f.write("matched\ttimestamp\tsession_id\toriginator\tsource\tsize_bytes\tcwd\tfile\n")
        for r in sorted(rows, key=lambda x: (not x["matched"], x["timestamp"])):
            f.write("\t".join(str(r[k]) for k in ("matched", "timestamp", "session_id",
                                                  "originator", "source", "size_bytes", "cwd", "file")) + "\n")
    return [r for r in rows if r["matched"]]


def extract(fp, rec):
    """Stream one rollout into rec (in place)."""
    usage_acc = {"input": 0, "output": 0, "reasoning": 0, "cached": 0}
    with open(fp, encoding="utf-8", errors="replace") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = r.get("timestamp")
            t = r.get("type")
            p = r.get("payload") or {}
            if t == "session_meta":
                rec["session_id"] = p.get("session_id") or rec["session_id"]
                rec["directory"] = p.get("cwd") or rec["directory"]
                rec["t_start"] = p.get("timestamp") or rec["t_start"]
            elif t == "turn_context":
                if p.get("model"):
                    rec["models"].append(p["model"])
            elif t == "event_msg":
                pt = p.get("type")
                if pt == "task_started":
                    rec["n_turns"] = rec.get("n_turns", 0) + 1
                elif pt == "task_complete":
                    rec["t_end"] = ts
                elif pt == "turn_aborted":
                    rec["n_turn_aborted"] = rec.get("n_turn_aborted", 0) + 1
                elif pt == "item_completed":
                    item = p.get("item") or {}
                    if item.get("type") == "UserMessage":
                        txt = "\n".join(c.get("text", "") for c in item.get("content", [])
                                        if isinstance(c, dict))
                        if txt and not is_tool_synthetic(txt, SYNTH_PREFIXES):
                            rec["n_user_msgs"] += 1
                            rec["user_messages"].append({"ts": ts, "chars": len(txt), "text": txt[:8000]})
                elif pt == "token_count":
                    tu = (p.get("info") or {}).get("total_token_usage") or {}
                    usage_acc = {"input": tu.get("input_tokens", 0), "output": tu.get("output_tokens", 0),
                                 "reasoning": tu.get("reasoning_output_tokens", 0),
                                 "cached": tu.get("cached_input_tokens", 0)}
            elif t == "compacted":
                rec["n_compactions"] = rec.get("n_compactions", 0) + 1
            elif t == "response_item":
                pt = p.get("type")
                if pt == "message" and p.get("role") == "assistant":
                    txt = "\n".join(c.get("text", "") for c in p.get("content", []) if isinstance(c, dict))
                    if txt.strip():
                        rec["n_assistant_msgs"] += 1
                        rec["assistant_texts"].append({"ts": ts, "chars": len(txt), "head": head(txt, 300)})
                elif pt in ("function_call", "custom_tool_call"):
                    add_tool_call(rec, ts, p.get("name", ""), p.get("call_id", ""),
                                  p.get("input") or p.get("arguments") or "")
                elif pt in ("function_call_output", "custom_tool_call_output"):
                    o = p.get("output")
                    if isinstance(o, list):
                        o = "\n".join(c.get("text", "") for c in o if isinstance(c, dict))
                    mark_tool_result(rec, p.get("call_id", ""), o if isinstance(o, str) else json.dumps(o, ensure_ascii=False))
    rec["tokens"] = usage_acc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--out", default="agentic-audit")
    ap.add_argument("--root", "--sessions-root", dest="root",
                    default=os.path.join(os.path.expanduser("~"), ".codex", "sessions"))
    ap.add_argument("--limit-sessions", type=int, default=None,
                    help="process only the first N matched rollouts (quick probe)")
    args = ap.parse_args()

    os.makedirs(os.path.join(args.out, "data"), exist_ok=True)
    matched = inventory(args.root, args.repo, args.out)
    if args.limit_sessions:
        matched = matched[:args.limit_sessions]
    jsonl, log = open_outputs(args.out, "codex")
    for row in matched:
        seg_name = os.path.basename(row["file"]).replace("rollout-", "").replace(".jsonl", "")
        rec = new_session("codex", row.get("session_id") or seg_name,
                          directory=row.get("cwd", ""), t_start=row.get("timestamp"),
                          title="", segment_file=seg_name)
        try:
            extract(row["file"], rec)
            dump(rec, jsonl)
        except Exception as e:
            print(f"{row['file']}: {e}", file=log)
    jsonl.close()
    log.close()
    n = sum(1 for _ in open(os.path.join(args.out, "data", "codex_sessions.jsonl"), encoding="utf-8"))
    print(f"codex: {len(matched)} rollout files matched -> {n} sessions -> {args.out}/data/codex_sessions.jsonl")
    print("note: resumed threads share session_id; compute_stats merges segments (field: segments)")


if __name__ == "__main__":
    main()
