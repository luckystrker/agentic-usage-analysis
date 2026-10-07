#!/usr/bin/env python3
"""ZCode: extract sessions of the target repo from ~/.zcode/cli/db/db.sqlite.
Layout: session (has `directory`) -> message/part (JSON in `data`; part.message_id is a COLUMN)
plus tool_usage (statuses, exit codes, durations) and model_usage."""
import argparse
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (matches_repo, ms_iso, new_session, add_tool_call, head,  # noqa: E402
                    open_outputs, dump, is_tool_synthetic)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--out", default="agentic-audit")
    ap.add_argument("--db", default=os.path.join(os.path.expanduser("~"), ".zcode", "cli", "db", "db.sqlite"))
    ap.add_argument("--before-ms", type=int, default=None,
                    help="exclude sessions created at/after this epoch-ms (use to exclude the audit's own sessions)")
    ap.add_argument("--limit-sessions", type=int, default=None,
                    help="process only the first N matched sessions (quick probe)")
    args = ap.parse_args()

    if not os.path.isfile(args.db):
        raise SystemExit(f"database not found: {args.db} — is zcode installed? "
                         "see references/storage-layouts.md")
    con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    cur = con.cursor()

    # Filter directories in Python, not SQL: LIKE cannot express path nesting safely
    # (`_` and `%` in paths are wildcards); matches_repo handles nesting, case and slashes.
    sql = ("select id, parent_id, slug, title, directory, time_created, time_updated "
           "from session")
    params = []
    if args.before_ms is not None:
        sql += " where time_created < ?"
        params.append(args.before_ms)
    rows = cur.execute(sql, params).fetchall()
    sessions = [r for r in rows if matches_repo(r[4], args.repo)]
    if args.limit_sessions:
        sessions = sessions[:args.limit_sessions]
    if not sessions:
        print("no sessions matched; directories present:")
        for (d, n) in cur.execute("select directory, count(*) from session group by directory").fetchall():
            print("  ", d, n)
        return

    jsonl, log = open_outputs(args.out, "zcode")
    n_out = 0
    for (sid, parent, slug, title, directory, tc, tu) in sessions:
        rec = new_session("zcode", sid, parent_id=parent, title=title, directory=directory,
                          t_start=ms_iso(tc), t_end=ms_iso(tu),
                          duration_s=int((tu - tc) / 1000) if tc and tu else None)
        msg_role = {}
        for mid, data in cur.execute("select id, data from message where session_id=? order by sequence, time_created", (sid,)):
            try:
                m = json.loads(data)
            except json.JSONDecodeError:
                continue
            role = m.get("role")
            msg_role[mid] = role
            if role == "user":
                rec["n_user_msgs"] += 1
                ms = m.get("modelSelection") or {}
                if ms.get("modelId"):
                    rec["models"].append(ms["modelId"])
            elif role == "assistant":
                rec["n_assistant_msgs"] += 1
        for (pmid, pdata,) in cur.execute("select message_id, data from part where session_id=? order by sequence, time_created", (sid,)):
            try:
                pt = json.loads(pdata)
            except json.JSONDecodeError:
                continue
            typ = pt.get("type")
            ts = ms_iso((pt.get("time") or {}).get("start"))
            if typ == "text":
                txt = pt.get("text", "") or ""
                if not txt.strip():
                    continue
                if msg_role.get(pmid) == "assistant":
                    rec["assistant_texts"].append({"ts": ts, "chars": len(txt), "head": head(txt, 300)})
                elif msg_role.get(pmid) == "user" and not is_tool_synthetic(
                        txt, ("<system-reminder", "<env>", "<user_instructions", "<environment")):
                    rec["user_messages"].append({"ts": ts, "chars": len(txt), "text": txt[:8000]})
            elif typ == "tool":
                st = pt.get("state") or {}
                is_err = 1 if st.get("status") == "error" else 0
                add_tool_call(rec, ts, pt.get("tool", ""), pt.get("callID", ""),
                              st.get("input") or {}, status=st.get("status", ""), is_error=is_err)
        # tool_usage carries exit codes/durations even when part-state is empty
        rec["tool_usage_agg"] = [dict(zip(("tool_name", "status", "exit_code", "duration_ms", "approval_status"), r))
                                 for r in cur.execute(
            "select tool_name, status, exit_code, duration_ms, approval_status "
            "from tool_usage where session_id=?", (sid,))]
        rec["n_errors_exit"] = sum(1 for r in rec["tool_usage_agg"] if r["exit_code"] not in (None, 0))
        # token usage lives in model_usage (per logical request); sum per session
        tok = {"input": 0, "output": 0, "reasoning": 0, "cached": 0}
        try:
            for it, ot, rt, cr in cur.execute(
                    "select input_tokens, output_tokens, reasoning_tokens, "
                    "cache_read_input_tokens from model_usage where session_id=?", (sid,)):
                tok["input"] += it or 0
                tok["output"] += ot or 0
                tok["reasoning"] += rt or 0
                tok["cached"] += cr or 0
            rec["tokens"] = tok
        except sqlite3.Error:
            pass  # older schemas may lack the table/columns; tokens stay None
        try:
            dump(rec, jsonl)
            n_out += 1
        except Exception as e:
            print(f"{sid}: {e}", file=log)
    jsonl.close()
    log.close()
    con.close()
    print(f"zcode: {n_out} sessions -> {args.out}/data/zcode_sessions.jsonl")
    if args.before_ms is None:
        print("hint: pass --before-ms to exclude the audit's own sessions if you are running inside ZCode")


if __name__ == "__main__":
    main()
