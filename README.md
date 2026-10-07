# agentic-usage-analysis

A skill (and standalone toolkit) that reconstructs **how AI coding agents actually worked on a repository** — from their local session logs. Built and battle-tested on a real month-long, four-tool game project.

## What it does

Reconstructs per-tool session history and turns it into an evidence-backed audit:

- **8 tools supported**: Codex CLI, Claude Code, OpenCode, OMP, ZCode have dedicated extractors; Qoder, Antigravity, Pi and other unknown layouts go through a best-effort generic extractor + storage inspection helpers.
- **Quantitative**: sessions per tool per day, tool-call profiles, error counts, retry loops (≥2 identical commands), token/cost totals, user-request classification (RU+EN defaults, per-project overrides).
- **Qualitative**: per-session digests for reading, subagent prompts for deep analysis, an escaped-defects cross-check against the repo's own validation history and git log.
- **Two final reports**: `report.md` (full analysis) and `report.html` — a standalone dashboard (KPIs, era timeline, charts) built by `scripts/make_report_page.py`, no JS dependencies.
- **Correctness care that matters**: codex resumed threads are merged by real `session_id` (not filenames), nested working directories are matched (no SQL LIKE traps), synthetic traffic (system reminders, guardian reviews, continuation injections) is filtered at extraction time with a conservative, language-neutral heuristic.

## Install as a skill

Clone into your agent's skills directory:

```bash
git clone https://github.com/luckystrker/agentic-usage-analysis ~/.zcode/skills/agentic-usage-analysis
# or ~/.claude/skills/ / ~/.agents/skills/ — anything that loads SKILL.md skills
```

Requires **Python 3.10+**, standard library only (matplotlib optional, for charts).

## Quick start (works without an agent, too)

```bash
python scripts/discover.py --repo "C:\path\to\repo"          # what log stores exist on this machine
python scripts/extract_zcode.py --repo "C:\path\to\repo" --out agentic-audit
python scripts/compute_stats.py --out agentic-audit          # + user_patterns.py, make_charts.py
python scripts/make_report_page.py --out agentic-audit       # -> agentic-audit/report.html
```

Every script is read-only against agent databases (`sqlite mode=ro`) and supports `--limit-sessions N` for quick probes. `SKILL.md` documents the full 7-phase workflow; `references/` carries the storage-layout map, subagent prompt templates, and the report structure.

## Evals

`evals/evals.json` + `evals/fixtures/` — four portable scenarios (resumed-thread merging, synthetic filtering, per-file repo matching, unknown-format resilience, empty-machine behavior) that run on any machine against bundled fixtures.

## Privacy

Dumps contain full user texts and shell command lines — including any tokens or keys agents ever typed. Keep the output directory private, sanitize before sharing, never commit reports without the repo owner's decision.

## По-русски

Скилл собирает по локальным логам, как ИИ-агенты работали над репозиторием: сессии и эпохи инструментов, затыки в циклах, поправки владельца, побеги дефектов — с выводом в `report.md` и дашборд `report.html`. Инструкции скилла на русском; код и форматы данных языконезависимы. MIT.

## License

[MIT](LICENSE) © luckystrker
