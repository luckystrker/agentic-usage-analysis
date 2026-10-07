#!/usr/bin/env python3
"""Aggregate stats across all <tool>_sessions.jsonl in <out>/data + per-session digests
for qualitative review. Merges codex resumed threads by session_id."""
import argparse
import collections
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import normalize_name, classify_shell, load_shell_classes, is_synthetic  # noqa: E402


def merge_sessions(sessions):
    """Merge codex continuation segments (same session_id, several rollout files).
    Keyed on (tool, session_id): ids from different tools must never collide."""
    merged = {}
    for s in sessions:
        key = (s["tool"], s["session_id"])
        if s["tool"] == "codex" and key in merged:
            m = merged[key]
            for field in ("user_messages", "assistant_texts", "tool_calls", "errors_head"):
                m[field] = m.get(field, []) + s.get(field, [])
            for f in ("n_user_msgs", "n_assistant_msgs", "n_tool_calls", "n_errors",
                      "n_compactions", "n_turn_aborted", "n_turns"):
                m[f] = m.get(f, 0) + s.get(f, 0)
            m["models"] = sorted(set(m["models"]) | set(s["models"]))
            if s.get("tokens"):
                m["tokens"] = m.get("tokens") or {}
                for k, v in s["tokens"].items():
                    m["tokens"][k] = m["tokens"].get(k, 0) + (v or 0)
            m.setdefault("segment_files", []).append(s.get("segment_file"))
            m["duration_s"] = (m.get("duration_s") or 0) + (s.get("duration_s") or 0)
            m["segments"] = m.get("segments", 1) + 1
            if (s.get("t_start") or "9999") < (m.get("t_start") or "9999"):
                m["t_start"] = s["t_start"]
            if (s.get("t_end") or "") > (m.get("t_end") or ""):
                m["t_end"] = s["t_end"]
        else:
            s = dict(s)
            s.setdefault("segments", 1)
            if s["tool"] == "codex":
                s["segment_files"] = [s.get("segment_file")]
            merged[key] = s
    return list(merged.values())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="agentic-audit")
    ap.add_argument("--digest-count", type=int, default=32)
    ap.add_argument("--shell-classes", default=None,
                    help="JSON file [[label,[keys]],...] with project-specific shell command classes")
    args = ap.parse_args()
    shell_classes = load_shell_classes(args.shell_classes) if args.shell_classes else None

    data = os.path.join(args.out, "data")
    digests = os.path.join(data, "digests")
    os.makedirs(digests, exist_ok=True)

    sessions = []
    for fp in sorted(glob.glob(os.path.join(data, "*_sessions.jsonl"))):
        tool = os.path.basename(fp).replace("_sessions.jsonl", "")
        with open(fp, encoding="utf-8") as f:
            for line in f:
                rec = json.loads(line)
                rec["tool"] = rec.get("tool") or tool
                sessions.append(rec)
    sessions = merge_sessions(sessions)
    if not sessions:
        print("no *_sessions.jsonl found; run extractors first")
        return

    # overview
    overview = {}
    for tool in sorted({s["tool"] for s in sessions}):
        ss = [s for s in sessions if s["tool"] == tool]
        entry = {
            "sessions": len(ss),
            "main_sessions": sum(1 for s in ss if not s.get("parent_id")),
            "child_sessions": sum(1 for s in ss if s.get("parent_id")),
            "total_duration_h": round(sum(s.get("duration_s") or 0 for s in ss) / 3600, 1),
            "user_msgs": sum(s["n_user_msgs"] for s in ss),
            "assistant_msgs": sum(s["n_assistant_msgs"] for s in ss),
            "tool_calls": sum(s["n_tool_calls"] for s in ss),
            "tool_errors": sum(s.get("n_errors", 0) for s in ss) + sum(s.get("n_errors_exit", 0) for s in ss),
            "tokens_in_M": round(sum((s.get("tokens") or {}).get("input", 0) for s in ss) / 1e6, 1),
            "tokens_out_M": round(sum((s.get("tokens") or {}).get("output", 0) for s in ss) / 1e6, 2),
        }
        # cost is only meaningful for tools that report it; a silent 0 would be a lie
        if any("cost" in (s.get("tokens") or {}) for s in ss):
            entry["cost_usd"] = round(sum((s.get("tokens") or {}).get("cost", 0) or 0 for s in ss), 2)
        overview[tool] = entry

    # timeline
    timeline = collections.Counter()
    for s in sessions:
        if s.get("t_start"):
            timeline[(s["t_start"][:10], s["tool"])] += 1
    days = sorted({d for d, _ in timeline})
    tools = sorted({s["tool"] for s in sessions})

    # tool breakdown + errors
    tool_breakdown = collections.defaultdict(collections.Counter)
    tool_errors_by_name = collections.defaultdict(collections.Counter)
    shell_class = collections.defaultdict(collections.Counter)
    for s in sessions:
        for tc in s["tool_calls"]:
            name = normalize_name(tc["name"])
            tool_breakdown[s["tool"]][name] += 1
            if tc.get("is_error"):
                tool_errors_by_name[s["tool"]][name] += 1
            if name == "shell":
                c = classify_shell(tc.get("args_head", "") + " " + tc.get("out_head", ""), shell_classes)
                if c:
                    shell_class[s["tool"]][c] += 1

    # retries: same shell command repeated >=2 times consecutively
    retry_events = []
    for s in sessions:
        prev_key, run = None, 0
        for tc in s["tool_calls"] + [{"name": "END"}]:
            if normalize_name(tc.get("name", "")) == "shell":
                key = (tc.get("args_head", "") or "").strip()[:120]
                if key == prev_key:
                    run += 1
                else:
                    if run >= 2:
                        retry_events.append({"tool": s["tool"], "session": s["session_id"][:20],
                                             "repeats": run, "cmd": prev_key})
                    prev_key, run = key, 1
            else:
                if run >= 2:
                    retry_events.append({"tool": s["tool"], "session": s["session_id"][:20],
                                         "repeats": run, "cmd": prev_key})
                prev_key, run = None, 0
    retry_events.sort(key=lambda x: -x["repeats"])

    # user message corpus (with child flag + synthetic pre-filter markers)
    corpus = open(os.path.join(data, "all_user_messages.jsonl"), "w", encoding="utf-8")
    for s in sorted(sessions, key=lambda x: x.get("t_start") or ""):
        for um in s["user_messages"]:
            corpus.write(json.dumps({"tool": s["tool"], "session": s["session_id"][:24],
                                     "child": bool(s.get("parent_id")),
                                     "synthetic": is_synthetic(um["text"]),
                                     "ts": um["ts"], "chars": um["chars"], "text": um["text"]},
                                    ensure_ascii=False) + "\n")
    corpus.close()

    # digests for key sessions
    def digest(s, fp):
        with open(fp, "w", encoding="utf-8") as f:
            f.write(f"# {s['tool']} session {s['session_id']}\n\n")
            f.write(f"title: {s.get('title') or '(no title)'}\ndirectory: {s.get('directory')}\n")
            f.write(f"start: {s.get('t_start')}  end: {s.get('t_end')}  duration_s: {s.get('duration_s')}\n")
            f.write(f"user_msgs: {s['n_user_msgs']}  assistant_msgs: {s['n_assistant_msgs']}  "
                    f"tool_calls: {s['n_tool_calls']}  errors: {s.get('n_errors', 0)}\n")
            f.write(f"models: {s.get('models')}\n")
            if s.get("parent_id"):
                f.write(f"parent (subagent session): {s['parent_id']}\n")
            f.write("\n## USER MESSAGES (chronological)\n\n")
            for i, um in enumerate(s["user_messages"]):
                f.write(f"### [{i+1}] {um['ts']} ({um['chars']} ch)\n{um['text'][:6000]}\n\n")
            f.write("\n## ASSISTANT TEXTS (first 300 ch each)\n\n")
            for at in s["assistant_texts"][:60]:
                f.write(f"- [{at['ts']}] {at['head']!r}\n")
            f.write("\n## TOOL CALLS (chronological; E=error)\n\n")
            for tc in s["tool_calls"]:
                mark = "E" if tc.get("is_error") else " "
                f.write(f"- [{tc.get('ts')}] {mark} {tc.get('name')} :: {tc.get('args_head', '')[:110]!r}")
                if tc.get("is_error"):
                    f.write(f"  ERR>> {tc.get('out_head', '')[:150]!r}")
                f.write("\n")
            if s.get("n_compactions"):
                f.write(f"\ncontext compactions: {s['n_compactions']}\n")
            if s.get("n_turn_aborted"):
                f.write(f"turn aborts (user interrupt): {s['n_turn_aborted']}\n")

    key = set()
    per_pred = max(4, args.digest_count // 3)
    for pred in (lambda s: -(s.get("duration_s") or 0),
                 lambda s: -s.get("n_errors", 0),
                 lambda s: -s["n_user_msgs"]):
        for s in sorted(sessions, key=pred)[:per_pred]:
            key.add(s["session_id"])
    digest_index = []
    for s in sessions:
        if s["session_id"] in key:
            safe = re.sub(r"[^a-zA-Z0-9_-]", "_", s["session_id"])[:60]
            fp = os.path.join(digests, f"{s['tool']}__{safe}.md")
            digest(s, fp)
            digest_index.append({"tool": s["tool"], "session": s["session_id"],
                                 "file": os.path.relpath(fp, args.out),
                                 "title": s.get("title"), "t_start": s.get("t_start"),
                                 "duration_s": s.get("duration_s"), "n_user": s["n_user_msgs"],
                                 "n_tools": s["n_tool_calls"], "n_errors": s.get("n_errors", 0)})

    stats = {
        "overview": overview,
        "cost_untracked_tools": sorted(t for t, e in overview.items() if "cost_usd" not in e),
        "timeline": {d: {t: timeline.get((d, t), 0) for t in tools} for d in days},
        "tool_breakdown": {t: dict(c.most_common()) for t, c in tool_breakdown.items()},
        "tool_errors_by_name": {t: dict(c.most_common()) for t, c in tool_errors_by_name.items()},
        "shell_class": {t: dict(c.most_common()) for t, c in shell_class.items()},
        "retries_top30": retry_events[:30],
        "n_retry_events": len(retry_events),
        "digests": digest_index,
    }
    with open(os.path.join(data, "stats.json"), "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=1)
    with open(os.path.join(data, "digest_index.json"), "w", encoding="utf-8") as f:
        json.dump(digest_index, f, ensure_ascii=False, indent=1)

    print(json.dumps(overview, ensure_ascii=False, indent=1))
    print("digests:", len(digest_index), "| retry events:", len(retry_events))


if __name__ == "__main__":
    main()
