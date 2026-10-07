#!/usr/bin/env python3
"""Best-effort extraction for tools with unknown/undocumented layouts (antigravity, pi, qoder, …).
Scans a root directory for JSONL files that mention the target repo (cwd/projectPath/workspace
keys), reports what record types they contain, and extracts a normalized best-effort session
record: user/assistant texts plus any tool_call/toolUse/function_call shapes it recognises.
Unknown shapes are skipped, never fatal — this script runs against formats we have never seen.
If the heuristics miss, inspect a sample manually and write a dedicated extractor."""
import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (matches_repo, new_session, add_tool_call, mark_tool_result,  # noqa: E402
                    head, open_outputs, dump)

CWD_KEYS = ("cwd", "projectPath", "workspace", "directory", "project_root", "workspaceRoot", "path")
TOOL_CALL_KEYS = ("tool_use", "toolCall", "tool_call", "function_call", "toolUses", "tool_calls")


def record_cwd(r):
    """Pull any repo-path-looking value out of a record (top level or one dict deep)."""
    for k in CWD_KEYS:
        v = r.get(k)
        if isinstance(v, str) and matches_repo(v, _repo):
            return v
    for v in r.values():
        if isinstance(v, dict):
            for k in CWD_KEYS:
                vv = v.get(k)
                if isinstance(vv, str) and matches_repo(vv, _repo):
                    return vv
    return None


_repo = None


def main():
    global _repo
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--out", default="agentic-audit")
    ap.add_argument("--tool", required=True, help="short tool name for output files, e.g. antigravity")
    ap.add_argument("--root", required=True, help="directory to scan for *.jsonl")
    ap.add_argument("--max-files", type=int, default=5000)
    ap.add_argument("--limit-sessions", type=int, default=None,
                    help="process only the first N matched files (quick probe)")
    ap.add_argument("--inventory-only", action="store_true")
    args = ap.parse_args()
    _repo = args.repo

    os.makedirs(os.path.join(args.out, "data"), exist_ok=True)
    inv_path = os.path.join(args.out, "data", f"{args.tool}_inventory.json")
    files = sorted(glob.glob(os.path.join(args.root, "**", "*.jsonl"), recursive=True))[:args.max_files]
    inventory = []

    for fp in files:
        info = {"file": fp, "size_bytes": os.path.getsize(fp), "repo": False, "types": {}, "cwd": None}
        try:
            with open(fp, encoding="utf-8", errors="replace") as f:
                for i, line in enumerate(f):
                    if not line.strip():
                        continue
                    try:
                        r = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(r, dict):
                        continue
                    t = r.get("type") or r.get("role") or "?"
                    info["types"][t] = info["types"].get(t, 0) + 1
                    cwd = record_cwd(r)
                    if cwd:
                        info["repo"] = True
                        info["cwd"] = info["cwd"] or cwd
                    if i > 2000:
                        break
        except Exception as e:
            info["error"] = str(e)
        inventory.append(info)

    with open(inv_path, "w", encoding="utf-8") as f:
        json.dump(inventory, f, ensure_ascii=False, indent=1)
    matched = [i for i in inventory if i["repo"]]
    if args.limit_sessions:
        matched = matched[:args.limit_sessions]
    print(f"{args.tool}: scanned {len(inventory)} jsonl under {args.root}; {len(matched)} mention the repo")
    for i in matched[:20]:
        print("  ", os.path.basename(i["file"]), i["size_bytes"] // 1024, "KB", dict(list(i["types"].items())[:6]))
    if args.inventory_only or not matched:
        print(f"inventory -> {inv_path}")
        return

    jsonl, log = open_outputs(args.out, args.tool)
    n_out = 0
    for info in matched:
        fp = info["file"]
        rec = new_session(args.tool, os.path.basename(fp).replace(".jsonl", ""),
                          directory=info.get("cwd") or "")
        first_ts = last_ts = None
        try:
            with open(fp, encoding="utf-8", errors="replace") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        r = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(r, dict):
                        continue
                    try:
                        ts = r.get("timestamp") or r.get("createdAt") or r.get("time")
                        if ts:
                            first_ts = first_ts or ts
                            last_ts = ts
                        msg = r.get("message") if isinstance(r.get("message"), dict) else {}
                        role = r.get("role") or msg.get("role")
                        content = r.get("content") or msg.get("content")
                        texts = []
                        if isinstance(content, str):
                            texts.append(content)
                        elif isinstance(content, list):
                            for c in content:
                                if isinstance(c, dict):
                                    if c.get("type") in ("text", "output_text", "input_text"):
                                        texts.append(c.get("text", ""))
                                    elif c.get("type") in TOOL_CALL_KEYS or c.get("name"):
                                        add_tool_call(rec, ts, c.get("name", "?"),
                                                      c.get("id", c.get("call_id", "")),
                                                      c.get("input") or c.get("arguments") or {})
                                    elif c.get("type") in ("tool_result", "function_call_output", "toolResult"):
                                        o = c.get("output") or c.get("content") or ""
                                        mark_tool_result(rec, c.get("tool_use_id") or c.get("call_id") or "", str(o))
                        txt = "\n".join(x for x in texts if x)
                        if txt.strip() and role == "user":
                            rec["n_user_msgs"] += 1
                            rec["user_messages"].append({"ts": ts, "chars": len(txt), "text": txt[:8000]})
                        elif txt.strip() and role == "assistant":
                            rec["n_assistant_msgs"] += 1
                            rec["assistant_texts"].append({"ts": ts, "chars": len(txt), "head": head(txt, 300)})
                    except Exception as e:
                        print(f"{fp}: skip record ({e.__class__.__name__}: {e})", file=log)
                        continue
            rec["t_start"], rec["t_end"] = first_ts, last_ts
            try:
                dump(rec, jsonl)
                n_out += 1
            except Exception as e:
                print(f"{fp}: {e}", file=log)
        except Exception as e:
            print(f"{fp}: {e}", file=log)
    jsonl.close()
    log.close()
    print(f"{args.tool}: {n_out} best-effort sessions -> {args.out}/data/{args.tool}_sessions.jsonl")


if __name__ == "__main__":
    main()
