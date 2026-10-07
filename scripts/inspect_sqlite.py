#!/usr/bin/env python3
"""Print tables/counts/schema of a SQLite database to reverse-engineer an agent's storage."""
import argparse
import json
import re
import sqlite3
import sys

KEY = re.compile(r"session|message|part|event|turn|conversation|tool|usage|project|todo|history", re.I)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--table", default=None, help="dump full schema + sample rows of one table")
    ap.add_argument("--samples", type=int, default=2)
    args = ap.parse_args()

    con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    cur = con.cursor()
    if args.table:
        row = cur.execute("select sql from sqlite_master where name=?", (args.table,)).fetchone()
        if row is None or row[0] is None:
            sys.exit(f"table not found: {args.table}")
        print(row[0])
        safe = args.table.replace('"', '""')
        cols = [r[1] for r in cur.execute(f'pragma table_info("{safe}")').fetchall()]
        for row in cur.execute(f'select * from "{safe}" limit ?', (args.samples,)):
            d = dict(zip(cols, row))
            print(json.dumps({k: (str(v)[:400] if v is not None else None) for k, v in d.items()},
                             ensure_ascii=False))
        return

    tables = [r[0] for r in cur.execute("select name from sqlite_master where type='table'").fetchall()]
    for t in tables:
        try:
            n = cur.execute(f'select count(*) from "{t}"').fetchone()[0]
        except sqlite3.Error as e:
            n = f"err: {e}"
        mark = "*" if KEY.search(t) else " "
        print(f"{mark} {t}: {n}")
    print("\n* = tables that look session/message-related; dump with --table <name>")
    con.close()


if __name__ == "__main__":
    main()
