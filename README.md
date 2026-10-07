# agentic-usage-analysis

[![npm version](https://img.shields.io/npm/v/agentic-usage-analysis?color=cb3837&label=npm)](https://www.npmjs.com/package/agentic-usage-analysis)
[![License: MIT](https://img.shields.io/badge/License-MIT-informational)](LICENSE)
[![Installer](https://img.shields.io/badge/installer-Node_18%2B-339933?logo=nodedotjs&logoColor=white)](https://nodejs.org)
[![Scripts](https://img.shields.io/badge/scripts-Python_3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey)](#quick-start)

A skill (and standalone toolkit) that reconstructs **how AI coding agents actually worked on a repository** — from their local session logs. Built and battle-tested on a real month-long, four-tool game project.

```bash
npx agentic-usage-analysis
```

_Installs the skill into your agent's skills dir (ZCode, Claude Code, OpenCode, Codex, Cursor — auto-detected). Works standalone too._

## What it does

Reconstructs per-tool session history and turns it into an evidence-backed audit:

- **8 tools supported**: Codex CLI, Claude Code, OpenCode, OMP, ZCode have dedicated extractors; Qoder, Antigravity, Pi and other unknown layouts go through a best-effort generic extractor + storage inspection helpers.
- **Quantitative**: sessions per tool per day, tool-call profiles, error counts, retry loops (≥2 identical commands), token/cost totals, user-request classification (RU+EN defaults, per-project overrides).
- **Qualitative**: per-session digests for reading, subagent prompts for deep analysis, an escaped-defects cross-check against the repo's own validation history and git log.
- **Two final reports**: `report.md` (full analysis) and `report.html` — a standalone dashboard (KPIs, era timeline, charts) built by `scripts/make_report_page.py`, no JS dependencies.
- **Correctness care that matters**: codex resumed threads are merged by real `session_id` (not filenames), nested working directories are matched (no SQL LIKE traps), synthetic traffic (system reminders, guardian reviews, continuation injections) is filtered at extraction time with a conservative, language-neutral heuristic.

## Install as a skill

Via npx — [agentic-usage-analysis on npm](https://www.npmjs.com/package/agentic-usage-analysis) (no clone needed, zero-dependency installer, Node ≥ 18):

```bash
npx agentic-usage-analysis               # install into the first detected skills dir
npx agentic-usage-analysis --all         # every detected skills dir
npx agentic-usage-analysis --dir ~/.claude/skills
npx agentic-usage-analysis uninstall     # remove
```

Detected dirs: `~/.zcode/skills`, `~/.claude/skills`, `~/.agents/skills`, `~/.config/opencode/skills` (OpenCode), `~/.codex/skills`, `~/.cursor/skills` (a candidate counts when the skills dir or its agent dir exists). Anything else — `--dir <path>`. Re-running the installer updates an existing copy.

Or clone into your agent's skills directory:

```bash
git clone https://github.com/luckystrker/agentic-usage-analysis ~/.zcode/skills/agentic-usage-analysis
# or ~/.claude/skills/ / ~/.agents/skills/ — anything that loads SKILL.md skills
```

Requires **Python 3.10+**, standard library only (matplotlib optional, for charts).

## Quick start (works without an agent, too)

```bash
npx agentic-usage-analysis                                        # install; prints where it went
python <skill-dir>/scripts/discover.py --repo "C:\path\to\repo"   # what log stores exist on this machine
python <skill-dir>/scripts/extract_zcode.py --repo "C:\path\to\repo" --out agentic-audit
python <skill-dir>/scripts/compute_stats.py --out agentic-audit   # + user_patterns.py, make_charts.py
python <skill-dir>/scripts/make_report_page.py --out agentic-audit  # -> agentic-audit/report.html
```

`<skill-dir>` is the installed location (e.g. `~/.zcode/skills/agentic-usage-analysis` — the installer prints it). In a git clone it's just the repo root, so `python scripts/discover.py ...` works as-is.

Every script is read-only against agent databases (`sqlite mode=ro`) and supports `--limit-sessions N` for quick probes. `SKILL.md` documents the full 7-phase workflow; `references/` carries the storage-layout map, subagent prompt templates, and the report structure.

## Evals

`evals/evals.json` + `evals/fixtures/` — four portable scenarios (resumed-thread merging, synthetic filtering, per-file repo matching, unknown-format resilience, empty-machine behavior) that run on any machine against bundled fixtures.

## Privacy

Dumps contain full user texts and shell command lines — including any tokens or keys agents ever typed. Keep the output directory private, sanitize before sharing, never commit reports without the repo owner's decision.

## По-русски

Скилл собирает по локальным логам, как ИИ-агенты работали над репозиторием: сессии и эпохи инструментов, затыки в циклах, поправки владельца, побеги дефектов — с выводом в `report.md` и дашборд `report.html`. Ставится одной командой `npx agentic-usage-analysis` (находит каталог скиллов ZCode / Claude Code / OpenCode / Codex / Cursor сам). Инструкции скилла на русском; код и форматы данных языконезависимы. MIT.

## License

[MIT](LICENSE) © luckystrker
