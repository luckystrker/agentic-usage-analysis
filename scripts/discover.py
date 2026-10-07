#!/usr/bin/env python3
"""Probe known local storage locations of AI coding agents; report what exists and
how many sessions look related to the target repo. Read-only."""
import argparse
import glob
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import matches_repo  # noqa: E402

HOME = os.path.expanduser("~")
APPDATA = os.environ.get("APPDATA", os.path.join(HOME, "AppData", "Roaming"))
LOCALAPPDATA = os.environ.get("LOCALAPPDATA", os.path.join(HOME, "AppData", "Local"))


def du(path, depth=2):
    total = 0
    for root, _dirs, files in os.walk(path):
        if root.count(os.sep) - path.count(os.sep) > depth:
            _dirs[:] = []
            continue
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def probe_dir(p):
    if not os.path.isdir(p):
        return None
    n_jsonl = len(glob.glob(os.path.join(p, "**", "*.jsonl"), recursive=True))
    n_sqlite = len(glob.glob(os.path.join(p, "**", "*.db"), recursive=True)) + \
        len(glob.glob(os.path.join(p, "**", "*.sqlite*"), recursive=True))
    return {"path": p, "type": "dir", "size_mb": round(du(p) / 1e6), "jsonl": n_jsonl, "sqlite": n_sqlite}


def probe_file(p):
    if not os.path.isfile(p):
        return None
    return {"path": p, "type": "file", "size_mb": round(os.path.getsize(p) / 1e6, 1)}


def count_codex(repo):
    root = os.path.join(HOME, ".codex", "sessions")
    if not os.path.isdir(root):
        return None
    files = glob.glob(os.path.join(root, "**", "rollout-*.jsonl"), recursive=True)
    matched = 0
    for fp in files:
        try:
            with open(fp, encoding="utf-8", errors="replace") as f:
                for line in f:
                    if '"session_meta"' in line:
                        rec = json.loads(line)
                        if matches_repo((rec.get("payload") or {}).get("cwd"), repo):
                            matched += 1
                        break
        except Exception:
            continue
    return {"path": root, "type": "dir", "size_mb": round(du(root) / 1e6),
            "jsonl": len(files), "repo_rollouts": matched}


def file_cwd_match(fp, repo):
    """Scan until a truthy cwd — leading records may carry cwd: null."""
    try:
        with open(fp, encoding="utf-8", errors="replace") as f:
            for line in f:
                if '"cwd"' in line:
                    try:
                        cwd = json.loads(line).get("cwd")
                    except json.JSONDecodeError:
                        continue
                    if cwd:
                        return matches_repo(cwd, repo)
    except OSError:
        pass
    return False


def count_claude(repo):
    root = os.path.join(HOME, ".claude", "projects")
    if not os.path.isdir(root):
        return None
    total = matched = 0
    hit_dirs = []
    for d in os.listdir(root):
        dp = os.path.join(root, d)
        if not os.path.isdir(dp):
            continue
        files = glob.glob(os.path.join(dp, "*.jsonl"))
        total += len(files)
        n = sum(1 for fp in files if file_cwd_match(fp, repo))
        if n:
            matched += n
            hit_dirs.append(d)
    return {"path": root, "type": "dir", "size_mb": round(du(root) / 1e6),
            "jsonl": total, "repo_jsonl": matched, "repo_dirs": hit_dirs[:5]}


def count_omp(repo):
    root = os.path.join(HOME, ".omp", "agent", "sessions")
    if not os.path.isdir(root):
        return None
    out = {"path": root, "type": "dir", "jsonl": 0, "repo_sessions": 0, "repo_dirs": []}
    for d in os.listdir(root):
        dp = os.path.join(root, d)
        if not os.path.isdir(dp):
            continue
        files = glob.glob(os.path.join(dp, "*.jsonl"))
        out["jsonl"] += len(files)
        hit = 0
        for fp in files:
            try:
                with open(fp, encoding="utf-8", errors="replace") as f:
                    for line in f:
                        if '"cwd"' not in line:
                            continue
                        try:
                            r = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if r.get("type") == "session" and r.get("cwd"):
                            if matches_repo(r["cwd"], repo):
                                hit += 1
                            break
            except Exception:
                continue
        if hit:
            out["repo_sessions"] += hit
            out["repo_dirs"].append(d)
    return out


def count_sqlite_sessions(db, dir_column="directory"):
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        cur = con.cursor()
        tables = [r[0] for r in cur.execute(
            "select name from sqlite_master where type='table'").fetchall()]
        info = {"tables": len(tables)}
        for t in ("session", "sessions"):
            if t in tables:
                cols = [r[1] for r in cur.execute(f"pragma table_info({t})").fetchall()]
                if dir_column in cols:
                    info["sessions_total"] = cur.execute(f"select count(*) from {t}").fetchone()[0]
                for cand in ("directory", "cwd", "path") + tuple(c for c in cols if c.endswith("_id")):
                    if cand in cols:
                        info["session_dir_column"] = cand
                        break
        con.close()
        return info
    except Exception as e:
        return {"error": str(e)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    args = ap.parse_args()

    candidates = [
        ("codex", count_codex(args.repo)),
        ("claude", count_claude(args.repo)),
        ("omp", count_omp(args.repo)),
        ("omp-agent-db", probe_file(os.path.join(HOME, ".omp", "agent", "agent.db"))),
        ("opencode-db", probe_file(os.path.join(HOME, ".local", "share", "opencode", "opencode.db"))),
        ("opencode-legacy", probe_dir(os.path.join(HOME, ".local", "share", "opencode", "storage"))),
        ("zcode-db", probe_file(os.path.join(HOME, ".zcode", "cli", "db", "db.sqlite"))),
        ("zcode-agents", probe_dir(os.path.join(HOME, ".zcode", "cli", "agents"))),
        ("antigravity-home", probe_dir(os.path.join(HOME, ".antigravity"))),
        ("antigravity-roaming", probe_dir(os.path.join(APPDATA, "Antigravity"))),
        ("antigravity-local", probe_dir(os.path.join(LOCALAPPDATA, "Antigravity"))),
        ("antigravity-codeium", probe_dir(os.path.join(HOME, ".codeium"))),
        ("pi-home", probe_dir(os.path.join(HOME, ".pi"))),
        ("pi-config", probe_dir(os.path.join(HOME, ".config", "pi"))),
        ("pi-roaming", probe_dir(os.path.join(APPDATA, "pi"))),
        ("qoder-roaming", probe_dir(os.path.join(APPDATA, "Qoder"))),
        ("qoder-local", probe_dir(os.path.join(LOCALAPPDATA, "Qoder"))),
        ("qoder-home", probe_dir(os.path.join(HOME, ".qoder"))),
    ]

    zdb = os.path.join(HOME, ".zcode", "cli", "db", "db.sqlite")
    if os.path.isfile(zdb):
        candidates.append(("zcode-db-info", count_sqlite_sessions(zdb)))
    odb = os.path.join(HOME, ".local", "share", "opencode", "opencode.db")
    if os.path.isfile(odb):
        candidates.append(("opencode-db-info", count_sqlite_sessions(odb)))

    print(f"repo: {args.repo}\n")
    print(f"{'probe':22s} {'exists':7s} detail")
    for name, info in candidates:
        if info is None:
            print(f"{name:22s} {'-':7s} not found")
        elif "error" in info:
            print(f"{name:22s} {'ERR':7s} {info['error']}")
        else:
            print(f"{name:22s} {'YES':7s} {json.dumps(info, ensure_ascii=False)}")

    print("\nhints:")
    print(" - extractors: extract_{codex,omp,opencode,zcode,claude}.py --repo <REPO> --out <OUT>")
    print(" - unknown layouts: inspect_sqlite.py --db <db> / extract_generic_jsonl.py --root <dir>")
    print(" - VS Code forks (antigravity, qoder): look under <root>/User/workspaceStorage and globalStorage")


if __name__ == "__main__":
    main()
