#!/usr/bin/env python3
"""OMP: extract sessions of the target repo from ~/.omp/agent/sessions/<munged-path>/*.jsonl."""
import argparse
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (matches_repo, new_session, add_tool_call, mark_tool_result,  # noqa: E402
                    head, open_outputs, dump, is_tool_synthetic)


def munge(path):
    """C:\\projects\\repo -> --C--projects-repo--  (observed OMP layout: ':' and separators become '-')."""
    s = path.replace(":", "-")
    s = re.sub(r"[\\/]+", "-", s)
    return f"--{s}--"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--out", default="agentic-audit")
    ap.add_argument("--root", default=os.path.join(os.path.expanduser("~"), ".omp", "agent", "sessions"))
    ap.add_argument("--limit-sessions", type=int, default=None,
                    help="process only the first N matched sessions (quick probe)")
    args = ap.parse_args()

    jsonl, log = open_outputs(args.out, "omp")
    n_out = 0
    roots = [os.path.join(args.root, munge(args.repo)), args.root]  # exact dir, then scan-all fallback
    seen_files = set()
    for root in roots:
        if args.limit_sessions and n_out >= args.limit_sessions:
            break
        for fp in sorted(glob.glob(os.path.join(root, "*.jsonl")) + glob.glob(os.path.join(root, "*", "*.jsonl"))):
            if args.limit_sessions and n_out >= args.limit_sessions:
                break
            if fp in seen_files:
                continue
            seen_files.add(fp)
            rec = new_session("omp", os.path.basename(fp).replace(".jsonl", ""))
            usage_acc = {"input": 0, "output": 0, "reasoning": 0, "cached": 0, "cost": 0.0}
            first_ts = last_ts = None
            keep = False
            try:
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
                        if ts:
                            first_ts = first_ts or ts
                            last_ts = ts
                        if t == "session":
                            rec["directory"] = r.get("cwd", "")
                            rec["t_start"] = r.get("timestamp")
                            if matches_repo(rec["directory"], args.repo):
                                keep = True
                        elif t == "title" or t == "title_change":
                            if r.get("title"):
                                rec["title"] = r["title"]
                        elif t == "model_change":
                            if r.get("model"):
                                rec["models"].append(r["model"])
                        elif t == "message":
                            m = r.get("message") or {}
                            role = m.get("role")
                            content = m.get("content") or []
                            if role == "user":
                                txt = "\n".join(c.get("text", "") for c in content
                                                if isinstance(c, dict) and c.get("type") == "text")
                                if txt.strip() and not is_tool_synthetic(txt, ("<system-reminder>", "<env>")):
                                    rec["n_user_msgs"] += 1
                                    rec["user_messages"].append({"ts": ts, "chars": len(txt), "text": txt[:8000]})
                            elif role == "assistant":
                                rec["n_assistant_msgs"] += 1
                                u = m.get("usage") or {}
                                usage_acc["input"] += u.get("input", 0) or 0
                                usage_acc["output"] += u.get("output", 0) or 0
                                usage_acc["reasoning"] += u.get("reasoningTokens", 0) or 0
                                usage_acc["cached"] += u.get("cacheRead", 0) or 0
                                usage_acc["cost"] += (u.get("cost") or {}).get("total", 0) or 0
                                txt = "\n".join(c.get("text", "") for c in content
                                                if isinstance(c, dict) and c.get("type") == "text")
                                if txt.strip():
                                    rec["assistant_texts"].append({"ts": ts, "chars": len(txt), "head": head(txt, 300)})
                                for c in content:
                                    if isinstance(c, dict) and c.get("type") == "toolCall":
                                        add_tool_call(rec, ts, c.get("name", ""), c.get("id", ""),
                                                      c.get("arguments") or {})
                            elif role == "toolResult":
                                o = "\n".join(c.get("text", "") for c in content if isinstance(c, dict))
                                mark_tool_result(rec, m.get("toolCallId", ""), o)
                        elif t == "custom":
                            ct = r.get("customType", "")
                            rec["custom_events"] = {**rec.get("custom_events", {}), ct: rec.get("custom_events", {}).get(ct, 0) + 1}
            except Exception as e:
                print(f"{fp}: {e}", file=log)
            if not keep:
                continue
            rec["tokens"] = usage_acc
            rec["t_end"] = last_ts
            dump(rec, jsonl)
            n_out += 1
    jsonl.close()
    log.close()
    print(f"omp: {n_out} sessions -> {args.out}/data/omp_sessions.jsonl")
    if n_out == 0:
        print("hint: layout may differ; check --root and the munged dir name (see SKILL.md)")


if __name__ == "__main__":
    main()
