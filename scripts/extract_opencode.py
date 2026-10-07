#!/usr/bin/env python3
"""OpenCode: extract sessions of the target repo from opencode.db (SQLite).
Layout: project(session dir) -> session -> message(JSON data) -> part(JSON data, message_id is a COLUMN)."""
import argparse
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (matches_repo, ms_iso, new_session, add_tool_call,  # noqa: E402
                    head, open_outputs, dump, is_tool_synthetic)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--out", default="agentic-audit")
    ap.add_argument("--db", default=os.path.join(os.path.expanduser("~"), ".local", "share", "opencode", "opencode.db"))
    ap.add_argument("--limit-sessions", type=int, default=None,
                    help="process only the first N matched sessions (quick probe)")
    args = ap.parse_args()

    con_src = args.db
    if not os.path.isfile(con_src):
        raise SystemExit(f"database not found: {args.db} — is opencode installed? "
                         "see references/storage-layouts.md")
    con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    cur = con.cursor()

    # project table column names vary between versions; match the repo against any string column
    proj_cols = [r[1] for r in cur.execute("pragma table_info(project)").fetchall()]
    projects = []
    for row in cur.execute("select * from project").fetchall():
        vals = dict(zip(proj_cols, row))
        if any(isinstance(v, str) and matches_repo(v, args.repo) for v in vals.values()):
            projects.append(vals.get("id"))
    projects = [p for p in projects if p]
    if not projects:
        print("no matching project rows; projects:")
        for row in cur.execute("select * from project").fetchall():
            vals = dict(zip(proj_cols, row))
            print("  ", str(vals.get("id"))[:12], {k: v for k, v in vals.items()
                                                  if isinstance(v, str) and ("/" in v or "\\" in v)})
        return

    jsonl, log = open_outputs(args.out, "opencode")
    n_out = 0
    qmarks = ",".join("?" * len(projects))
    sessions = cur.execute(
        f"select id, parent_id, title, directory, time_created, time_updated "
        f"from session where project_id in ({qmarks}) order by time_created", projects).fetchall()
    if args.limit_sessions:
        sessions = sessions[:args.limit_sessions]
    for (sid, parent, title, directory, tc, tu) in sessions:
        rec = new_session("opencode", sid, parent_id=parent, title=title, directory=directory,
                          t_start=ms_iso(tc), t_end=ms_iso(tu),
                          duration_s=int((tu - tc) / 1000) if tc and tu else None)
        rec["tokens"] = {"input": 0, "output": 0, "reasoning": 0, "cached": 0, "cost": 0.0}
        msg_role = {}
        for mid, data in cur.execute("select id, data from message where session_id=? order by time_created", (sid,)):
            try:
                m = json.loads(data)
            except json.JSONDecodeError:
                continue
            role = m.get("role")
            msg_role[mid] = role
            if role == "user":
                rec["n_user_msgs"] += 1
            elif role == "assistant":
                rec["n_assistant_msgs"] += 1
                if m.get("modelID"):
                    rec["models"].append(m["modelID"])
                tk = m.get("tokens") or {}
                rec["tokens"]["input"] += tk.get("input", 0) or 0
                rec["tokens"]["output"] += tk.get("output", 0) or 0
                rec["tokens"]["reasoning"] += tk.get("reasoning", 0) or 0
                rec["tokens"]["cached"] += (tk.get("cache") or {}).get("read", 0) or 0
                rec["tokens"]["cost"] = rec["tokens"].get("cost", 0) + (m.get("cost") or 0)
        # NB: message_id is a COLUMN of part, not a field of the data JSON
        for (pmid, pdata,) in cur.execute("select message_id, data from part where session_id=? order by time_created", (sid,)):
            try:
                pt = json.loads(pdata)
            except json.JSONDecodeError:
                continue
            typ = pt.get("type")
            ts = ms_iso((pt.get("time") or {}).get("start")) or rec["t_start"]
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
                outp = st.get("output") or ""
                if is_err:
                    for tc_rec in reversed(rec["tool_calls"]):
                        if tc_rec["call_id"] == pt.get("callID", ""):
                            tc_rec["out_head"] = head(str(outp), 300)
                            break
                    if len(rec["errors_head"]) < 40:
                        rec["errors_head"].append({"ts": ts, "head": head(str(outp), 250)})
        try:
            dump(rec, jsonl)
            n_out += 1
        except Exception as e:
            print(f"{sid}: {e}", file=log)
    jsonl.close()
    log.close()
    con.close()
    print(f"opencode: {n_out} sessions -> {args.out}/data/opencode_sessions.jsonl")


if __name__ == "__main__":
    main()
