# Карта хранилищ ИИ-агентов (Windows; снапшот на 2026-10)

Форматы дрейфуют между версиями инструментов. Перед разведкой всегда запускай
`python scripts/discover.py --repo <REPO>` — не доверяй этому снапшоту вслепую; если
расходится с реальностью, обнови этот файл и дату снапшота.

## Группы инструментов

| Группа | Инструменты | Извлечение |
|---|---|---|
| Проверенные форматы | codex, omp, opencode, zcode | готовые экстракторы, см. Фазу 1 |
| Известный формат, сверься с версией | claude (Claude Code) | `extract_claude.py` (экспериментальный) |
| Формат зависит от версии/машины | antigravity, pi, qoder | `discover.py` находит кандидатов → `inspect_sqlite.py`/`extract_generic_jsonl.py` → при необходимости адаптируешь запросы вручную |

## Точки хранения

- **codex**: `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`; cwd в первой записи
  `session_meta`. Возобновлённые треды = несколько rollout-файлов на один `session_id`.
- **omp**: `~/.omp/agent/sessions/--<munged-path>--/*.jsonl`; munge = путь без `:`,
  `\`/`/` → `-`, обёрнутый в `--` с обеих сторон (`C:\projects\repo` → `--C--projects-repo--`).
  cwd также в записи `{"type":"session"}` внутри файла. Плюс `~/.omp/agent/agent.db`
  (рядом — WAL-файл, может быть заметно больше самой базы).
- **opencode**: `~/.local/share/opencode/opencode.db` (SQLite): таблицы
  `project`/`session`/`message`/`part`; данные в JSON-колонке `data`.
  Legacy-хранилище `~/.local/share/opencode/storage/` — только очень старые версии.
- **zcode**: `~/.zcode/cli/db/db.sqlite` (SQLite): `session` (есть `directory`),
  `message`/`part` (JSON в `data`), `tool_usage` (статусы, exit-коды, длительности),
  `model_usage`, `session_input`.
- **claude**: `~/.claude/projects/<munged-cwd>/<uuid>.jsonl`, munge как у omp без
  внешних `--`; каждая строка — запись `{type: user|assistant|..., message:{role, content},
  timestamp, cwd, sessionId, isSidechain}`; результаты инструментов — `tool_result`
  в content пользовательских записей, связаны `tool_use_id`.
- **antigravity**: кандидаты: `%USERPROFILE%\.antigravity`, `%APPDATA%\Antigravity`,
  `%LOCALAPPDATA%\Antigravity`, `%USERPROFILE%\.codeium\*` (родство с Codeium/Windsurf,
  форк VS Code — искать `User/workspaceStorage`, `globalStorage`, SQLite/JSONL).
- **pi**: кандидаты: `~/.pi`, `~/.config/pi`, `%APPDATA%\pi`, `%LOCALAPPDATA%\pi`
  (сессии обычно JSONL).
- **qoder**: кандидаты: `%APPDATA%\Qoder`, `%LOCALAPPDATA%\Qoder`, `%USERPROFILE%\.qoder`
  (форк VS Code — та же схема поиска, что у antigravity).

## Неизвестные форматы

- `python scripts/inspect_sqlite.py --db <путь>` — печатает таблицы с числом строк и
  помечает похожие на session/message/part/event/turn/conversation; `--table <имя>`
  даёт схему и сэмплы строк.
- `python scripts/extract_generic_jsonl.py --root <каталог> --repo <REPO> --tool <имя>
  --out <OUT>` — сканирует JSONL, находит файлы с упоминанием репо
  (cwd/projectPath/workspace) и делает best-effort извлечение;
  `--inventory-only` — только инвентарь.
- Если эвристики не сработали — читай сэмпл файла руками (`head -c 2000 <файл>`) и пиши
  точный экстрактор по образцу готовых. Это дёшево: у всех инструментов одна семантика —
  сессии, сообщения, вызовы инструментов.
