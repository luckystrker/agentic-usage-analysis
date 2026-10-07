#!/usr/bin/env python3
"""User request pattern analysis: classification, lengths, per-day/hour, steering messages.

Classification defaults are bilingual (RU+EN) and do not assume the user's language.
Override per project with --classes <file>:
    {"rules": [["label", ["key", ...]], ...], "steer_words": ["key", ...]}
The hour histogram uses this machine's local timezone unless --tz-hours is given."""
import argparse
import collections
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import is_synthetic  # noqa: E402

DEFAULT_RULES = [
    ("bugfix", ["дефект", "баг", "ошибк", "не работает", "сломал", "почин", "фикс", "fix",
                "проблема", "падает", "краш", "неправильн", "жалоб", "bug", "broken",
                "crash", "fails", "not working", "regression"]),
    ("review/verify", ["проверь", "ревью", "верифицир", "аудит", "посмотри что", "найди проблем",
                       "найди ошибк", "проанализир", "review", "verify", "check that",
                       "inspect", "audit", "look for"]),
    ("tests/build", ["запусти тест", "прогони тест", "editmode", "собери", "сборк", "пересобери",
                     "run tests", "test run", "build", "rebuild"]),
    ("planning", ["план", "этап", "беклог", "backlog", "приоритет", "roadmap", "что дальше",
                  "plan", "milestone", "priority", "next step"]),
    ("docs/writing", ["technical-decisions", "докум", "прочит", "readme", "запиши решение",
                      "решение №", "отчёт", "отчет", "document", "write up", "report"]),
    ("question/analysis", ["почему", "как работает", "объясни", "вопрос", "скажи", "что лучше",
                           "предложи", "варианты", "стоит ли", "why", "how does", "explain",
                           "propose", "options", "should we", "trade-off"]),
    ("feature-dev", ["сделай", "добавь", "переработ", "реализ", "перепиш", "измени", "переделай",
                     "убери", "поправ", "замени", "настро", "доработ", "add ", "implement",
                     "refactor", "rewrite", "update", "remove", "create"]),
]
DEFAULT_STEER = ["ты ", "опять", "снова", "зачем", "не надо", "стоп", "хватит", "я уже говорил",
                 "повторяю", "забыл", "потерял", "верни", "откат",
                 "again", "stop", "undo", "revert", "i said", "i already", "wrong"]


def classify(t, rules):
    tl = t.lower()
    for label, keys in rules:
        if any(k in tl for k in keys):
            return label
    return "other"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="agentic-audit")
    ap.add_argument("--tz-hours", type=float, default=None,
                    help="timezone offset for the hour histogram (default: this machine's offset)")
    ap.add_argument("--classes", default=None,
                    help='JSON file {"rules": [[label,[keys]],...], "steer_words": [...]}')
    args = ap.parse_args()

    rules, steer_words = DEFAULT_RULES, DEFAULT_STEER
    if args.classes:
        with open(args.classes, encoding="utf-8") as f:
            cfg = json.load(f)
        rules = [(str(label), [str(k) for k in keys]) for label, keys in cfg.get("rules", rules)]
        steer_words = [str(w) for w in cfg.get("steer_words", steer_words)]

    if args.tz_hours is not None:
        offset = datetime.timedelta(hours=args.tz_hours)
    else:
        offset = datetime.datetime.now().astimezone().utcoffset() or datetime.timedelta(0)

    data = os.path.join(args.out, "data")
    corpus_path = os.path.join(data, "all_user_messages.jsonl")
    if not os.path.isfile(corpus_path):
        raise SystemExit("all_user_messages.jsonl not found; run compute_stats.py first")
    msgs = []
    with open(corpus_path, encoding="utf-8") as f:
        for line in f:
            msgs.append(json.loads(line))

    real = [m for m in msgs if not is_synthetic(m["text"])]
    child = [m for m in real if m.get("child")]
    main_msgs = [m for m in real if not m.get("child")]

    cls = collections.Counter(classify(m["text"], rules) for m in main_msgs)
    by_tool_cls = collections.defaultdict(collections.Counter)
    for m in main_msgs:
        by_tool_cls[m["tool"]][classify(m["text"], rules)] += 1

    lens = sorted(m["chars"] for m in main_msgs)
    pct = lambda p: lens[min(int(len(lens) * p), len(lens) - 1)] if lens else 0  # noqa: E731

    per_day, per_hour = collections.Counter(), collections.Counter()
    for m in main_msgs:
        if not m["ts"]:
            continue
        try:
            dt = datetime.datetime.fromisoformat(m["ts"].replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        local = dt + offset
        per_day[local.strftime("%Y-%m-%d")] += 1
        per_hour[local.hour] += 1

    steer = [m for m in main_msgs if any(w in m["text"].lower() for w in steer_words)]

    out = {
        "total_user_msgs_all": len(msgs),
        "real_user_msgs_main": len(main_msgs),
        "child_dispatch_msgs": len(child),
        "synthetic_filtered": len(msgs) - len(real),
        "classification": dict(cls.most_common()),
        "classification_by_tool": {t: dict(c.most_common()) for t, c in by_tool_cls.items()},
        "length_p50": pct(0.50), "length_p90": pct(0.90), "length_p99": pct(0.99),
        "length_max": lens[-1] if lens else 0,
        "len_mean": round(sum(lens) / max(len(lens), 1)),
        "per_day_top": dict(per_day.most_common(15)),
        "per_hour": {h: per_hour[h] for h in range(24)},
        "steering_msgs": len(steer),
        "steering_examples": [{"tool": m["tool"], "ts": m["ts"], "head": m["text"][:220]} for m in steer[:25]],
        "top_long_examples": [{"tool": m["tool"], "ts": m["ts"], "chars": m["chars"], "head": m["text"][:300]}
                              for m in sorted(main_msgs, key=lambda x: -x["chars"])[:10]],
    }
    with open(os.path.join(data, "user_patterns.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(json.dumps({k: out[k] for k in ("total_user_msgs_all", "real_user_msgs_main",
                                          "child_dispatch_msgs", "classification",
                                          "length_p50", "length_p90", "steering_msgs")},
                     ensure_ascii=False, indent=1))
    if out["synthetic_filtered"] > max(10, 0.3 * len(msgs)):
        print("warning: synthetic filter dropped >30% of messages — inspect it before trusting stats",
              file=sys.stderr)


if __name__ == "__main__":
    main()
