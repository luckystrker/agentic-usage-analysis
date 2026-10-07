#!/usr/bin/env python3
"""Build a standalone HTML summary page for an agentic audit: <OUT>/report.html.

Visual language mirrors the skill-creator eval-viewer: warm light theme
(cream bg, charcoal header band, terracotta accent), Lora serif body +
Poppins UI + SF Mono/Consolas data, white bordered section cards, uppercase
Poppins section headers, benchmark-style tables, green/red status pills.

Data-driven parts (always present, read from Phase 2 outputs):
  data/stats.json         -> overview table, per-day timeline chart, retries top,
                             cost_untracked_tools
  data/user_patterns.json -> request classification chart, steering/synthetic shares

Model-curated parts (optional, read from data/report_highlights.json — the analyst
writes it during Phases 3-6 in the owner's language; format below). Sections whose
input is missing are skipped, so the page works even for quick audits.

report_highlights.json format (all fields optional):
{
  "title": "My Project",                         # page title, defaults to repo path
  "subtitle": "stack · one-line project description",
  "repo": "C:\\path\\to\\repo",                  # shown in the overview section header
  "period": "09.09-07.10.2026",                  # defaults to timeline range
  "intro": "2-3 sentences of narrative",
  "tool_notes": {"codex": "era note", ...},     # merged into the overview table
  "kpi": [["162", "sessions"], ...],            # overrides auto-KPI row
  "stuck_loops": [["x19", "write_stdin waits"], ...],
  "owner_quotes": [["20.09 | UI", "quote text"], ...],
  "owner_notes": "paragraph after quotes",
  "defect_waves": [["MP2-1\\n30.09", 3], ...],  # bar chart of escaped defects
  "repeat_escapes": ["self-model: MP2-steam -> MP3", ...],  # red pills
  "blind_spots": "paragraph",
  "conclusions": ["<b>bold lead</b> rest of the chain", ...],
  "extra_caveats": ["..."]
}

Highlight texts carry the owner's language; template chrome labels are Russian.
Self-contained output: inline CSS + SVG, webfont link degrades gracefully offline.
Zero dependencies beyond stdlib."""
import argparse
import html as html_mod
import json
import os

# warm palette matched to the eval-viewer world (light theme, terracotta accent)
C = {"bg": "#faf9f5", "surface": "#ffffff", "border": "#e8e6dc", "text": "#141413",
     "muted": "#b0aea5", "accent": "#d97757", "green": "#788c5d", "red": "#c44",
     "svgtext": "#6f6a5e"}
TOOL_COLOR = {"codex": "#d97757", "opencode": "#788c5d", "omp": "#b08d3f",
              "zcode": "#5f7d9c", "qoder": "#a39b8b", "claude": "#c4613f",
              "antigravity": "#7c9a8a", "pi": "#8a8460"}
TOOL_ORDER = ("codex", "claude", "opencode", "omp", "zcode", "qoder", "antigravity", "pi")


def esc(s):
    return html_mod.escape(str(s), quote=True)


def load(path):
    try:
        return json.load(open(path, encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def fmt(n):
    return f"{n:,}".replace(",", " ")


def timeline_svg(tl, tools):
    days = sorted(tl)
    if not days:
        return ""
    w, lab_w, row_h, top, gap = 980, 84, 44, 18, 14
    h = top + len(tools) * (row_h + gap) + 30
    bw = (w - lab_w - 10) / len(days)
    mx = max((tl[d].get(t, 0) for d in days for t in tools), default=1) or 1
    p = [f'<svg viewBox="0 0 {w} {h}" class="chart tl" role="img" aria-label="Сессии по дням">']
    for i, d in enumerate(days):
        if i % 3 == 0:
            x = lab_w + i * bw
            p.append(f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{h-26}" '
                     f'stroke="{C["border"]}" stroke-width="1"/>')
            p.append(f'<text x="{x:.1f}" y="{h-12}" class="axis">{esc(d[5:])}</text>')
    for r, t in enumerate(tools):
        y0 = top + r * (row_h + gap)
        p.append(f'<text x="0" y="{y0 + row_h - 6}" class="ser-label" '
                 f'fill="{TOOL_COLOR.get(t, C["accent"])}">{esc(t)}</text>')
        for i, d in enumerate(days):
            v = tl[d].get(t, 0)
            if not v:
                continue
            bh = max(4, (v / mx) * (row_h - 8))
            p.append(f'<rect x="{lab_w + i * bw + bw * 0.14:.1f}" y="{y0 + row_h - bh:.1f}" '
                     f'width="{bw * 0.72:.1f}" height="{bh:.1f}" rx="2" '
                     f'fill="{TOOL_COLOR.get(t, C["accent"])}"><title>{esc(d)}: {v}</title></rect>')
    p.append("</svg>")
    return "".join(p)


def hbar_svg(items, w=440, bar_h=20, gap=10, label_w=160):
    if not items:
        return ""
    h = len(items) * (bar_h + gap)
    mx = max(v for _, v, _ in items) or 1
    p = [f'<svg viewBox="0 0 {w} {h}" class="chart" role="img">']
    for i, (label, v, color) in enumerate(items):
        y = i * (bar_h + gap)
        bw = (v / mx) * (w - label_w - 64)
        p.append(f'<text x="{label_w - 8}" y="{y + bar_h - 5}" text-anchor="end" '
                 f'class="ser-label">{esc(label)}</text>')
        p.append(f'<rect x="{label_w}" y="{y}" width="{max(bw, 2):.1f}" height="{bar_h}" '
                 f'rx="3" fill="{color}"/>')
        p.append(f'<text x="{label_w + max(bw, 2) + 8:.1f}" y="{y + bar_h - 5}" '
                 f'class="val">{fmt(v)}</text>')
    p.append("</svg>")
    return "".join(p)


def waves_svg(waves):
    w, h, base, bw, gap = 460, 190, 34, 74, 34
    mx = max((v for _, v in waves), default=1) or 1
    p = [f'<svg viewBox="0 0 {w} {h}" class="chart" role="img" aria-label="Дефекты по волнам">']
    for i, (lab, v) in enumerate(waves):
        bh = (v / mx) * (h - base - 24)
        x = 18 + i * (bw + gap)
        p.append(f'<rect x="{x}" y="{h - base - bh:.1f}" width="{bw}" height="{bh:.1f}" '
                 f'rx="3" fill="{C["red"]}"/>')
        p.append(f'<text x="{x + bw / 2}" y="{h - base - bh - 8:.1f}" text-anchor="middle" '
                 f'class="val" font-weight="700">{v}</text>')
        for j, line in enumerate(str(lab).split("\n")):
            p.append(f'<text x="{x + bw / 2}" y="{h - base + 14 + j * 13}" '
                     f'text-anchor="middle" class="axis">{esc(line)}</text>')
    p.append(f'<line x1="10" y1="{h - base}" x2="{w - 10}" y2="{h - base}" '
             f'stroke="{C["border"]}" stroke-width="1"/></svg>')
    return "".join(p)


CSS = f"""
:root{{--bg:{C["bg"]};--surface:{C["surface"]};--border:{C["border"]};--text:{C["text"]};
  --muted:{C["muted"]};--accent:{C["accent"]};--accent-hover:#c4613f;--green:{C["green"]};
  --green-bg:#eef2e8;--red:{C["red"]};--red-bg:#fceaea;--header-bg:#141413;
  --header-text:#faf9f5;--radius:6px;
  --mono:'SF Mono',SFMono-Regular,Consolas,'Liberation Mono',Menlo,monospace}}
*{{box-sizing:border-box;margin:0;padding:0}}
::selection{{background:rgba(217,119,87,.25)}}
:focus-visible{{outline:2px solid var(--accent);outline-offset:2px;border-radius:3px}}
html{{scroll-behavior:smooth}}
body{{font-family:'Lora',Georgia,serif;background:var(--bg);color:var(--text);
  font-size:16px;line-height:1.6}}
a{{color:var(--accent);text-decoration:none;text-underline-offset:3px}}
a:hover{{color:var(--accent-hover);text-decoration:underline}}
code{{font-family:var(--mono);font-size:.85em;background:var(--bg);
  border:1px solid var(--border);border-radius:4px;padding:.05em .35em}}

.header{{background:var(--header-bg);color:var(--header-text);padding:1rem 2rem;
  display:flex;justify-content:space-between;align-items:center;gap:2rem;flex-wrap:wrap}}
.header h1{{font-family:'Poppins',sans-serif;font-size:1.25rem;font-weight:600}}
.header h1 .sub{{font-weight:400;opacity:.7;font-size:.85rem;margin-left:.75rem}}
.header .instructions{{font-size:.8rem;opacity:.7;margin-top:.25rem;max-width:68ch}}
.header .meta{{font-family:'Poppins',sans-serif;font-size:.8rem;opacity:.8;text-align:right}}

.view-tabs{{display:flex;gap:0;padding:0 2rem;background:var(--bg);
  border-bottom:1px solid var(--border);position:sticky;top:0;z-index:10;flex-wrap:wrap}}
.view-tab{{font-family:'Poppins',sans-serif;padding:.625rem 1.25rem;font-size:.8125rem;
  font-weight:500;cursor:pointer;border:none;background:none;color:var(--muted);
  border-bottom:2px solid transparent;transition:all .15s}}
.view-tab:hover{{color:var(--text)}}
.view-tab.active{{color:var(--accent);border-bottom-color:var(--accent)}}

.main{{padding:1.5rem 2rem;max-width:1100px;margin:0 auto;display:flex;
  flex-direction:column;gap:1.25rem}}
.section{{background:var(--surface);border:1px solid var(--border);
  border-radius:var(--radius)}}
.section-header{{font-family:'Poppins',sans-serif;padding:.75rem 1rem;font-size:.75rem;
  font-weight:500;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);
  border-bottom:1px solid var(--border);background:var(--bg);display:flex;
  justify-content:space-between;align-items:center}}
.section-header .note{{font-size:.6875rem;letter-spacing:.03em;opacity:.8}}
.section-body{{padding:1rem}}

.kpis{{display:flex;flex-wrap:wrap;gap:0}}
.kpi{{padding:.5rem 1.5rem;border-left:1px solid var(--border);flex:1;min-width:150px}}
.kpi:first-child{{border-left:none;padding-left:.25rem}}
.kpi b{{display:block;font-family:'Poppins',sans-serif;font-weight:600;font-size:1.5rem;
  letter-spacing:-.01em}}
.kpi span{{font-family:'Poppins',sans-serif;font-size:.6875rem;text-transform:uppercase;
  letter-spacing:.04em;color:var(--muted)}}

table{{border-collapse:collapse;font-size:.8125rem;width:100%;background:var(--surface)}}
th,td{{padding:.625rem .75rem;text-align:left;border:1px solid var(--border);vertical-align:top}}
thead th{{font-family:'Poppins',sans-serif;background:var(--header-bg);
  color:var(--header-text);font-weight:500;font-size:.75rem;text-transform:uppercase;
  letter-spacing:.04em}}
tbody tr:hover{{background:var(--bg)}}
tbody th{{font-weight:600;white-space:nowrap;background:var(--surface)}}
td.num,th.num{{font-family:var(--mono);text-align:right;white-space:nowrap}}
tfoot td{{font-weight:600;border-top:2px solid var(--border);background:var(--surface)}}
.dot{{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:8px}}
.dim{{color:var(--muted);font-weight:400}}

figure{{margin:0}}
.chart{{width:100%;height:auto}}
.axis{{fill:{C["svgtext"]};font:11.5px var(--mono)}}
.ser-label{{fill:{C["svgtext"]};font:600 12.5px 'Poppins',sans-serif}}
.val{{fill:var(--text);font:12.5px var(--mono)}}
figcaption{{color:var(--muted);font-size:.75rem;margin-top:.5rem;font-style:italic}}

.assertion-list{{list-style:none}}
.assertion-item{{padding:.625rem 0;border-bottom:1px solid var(--border);font-size:.8125rem}}
.assertion-item:last-child{{border-bottom:none}}
.assertion-item b.st{{font-family:var(--mono);color:var(--accent);margin-right:.5rem}}
.assertion-item .ev{{color:var(--muted);font-size:.75rem;margin-top:.25rem;padding-left:1.5rem}}

.quote{{background:var(--bg);border:1px solid var(--border);border-radius:4px;
  padding:.625rem .75rem;margin-top:.75rem;font-size:.9375rem;line-height:1.55}}
.quote .q-label{{font-size:.7rem;font-weight:600;text-transform:uppercase;
  letter-spacing:.04em;margin-bottom:.25rem;color:var(--muted);
  font-family:'Poppins',sans-serif}}
.note-p{{color:var(--muted);font-size:.8125rem;margin-top:.75rem}}

.pills{{display:flex;flex-wrap:wrap;gap:.5rem;margin:.75rem 0}}
.pill{{display:inline-block;padding:.125rem .5rem;border-radius:9999px;font-size:.75rem;
  font-weight:600;background:var(--red-bg);color:var(--red);
  font-family:'Poppins',sans-serif}}

.two{{display:grid;grid-template-columns:1fr 1fr;gap:1.25rem;align-items:start}}
@media(max-width:860px){{.two{{grid-template-columns:1fr}}}}
.notes ul{{list-style:disc;padding-left:1.25rem}}
.notes li{{font-size:.8125rem;line-height:1.6;margin-bottom:.375rem}}
.footer-meta{{font-family:var(--mono);font-size:.75rem;color:var(--muted);
  padding:.75rem 0 3rem;text-align:center}}
@media(prefers-reduced-motion:reduce){{.tl rect{{animation:none!important}}}}
.tl rect{{animation:fade .4s ease-out backwards}}
@keyframes fade{{from{{opacity:0}}to{{opacity:1}}}}
"""

SCROLLSPY = """
const tabs=[...document.querySelectorAll('.view-tab')];
const secs=tabs.map(t=>document.getElementById(t.getAttribute('href').slice(1)));
const io=new IntersectionObserver(es=>{es.forEach(e=>{if(e.isIntersecting){
tabs.forEach((t,i)=>t.classList.toggle('active',secs[i]===e.target));}})},{rootMargin:'-30% 0px -60% 0px'});
secs.forEach(s=>s&&io.observe(s));
"""


def tool_rows(overview, tool_notes):
    order = [t for t in TOOL_ORDER if t in overview] or sorted(overview)
    rows, tot_calls, tot_err, tot_sess = [], 0, 0, 0
    for t in order:
        e = overview[t]
        tot_calls += e.get("tool_calls", 0)
        tot_err += e.get("tool_errors", 0)
        tot_sess += e.get("sessions", 0)
        sess = fmt(e["sessions"])
        if e.get("child_sessions"):
            sess += (f' <span class="dim">({e["main_sessions"]}'
                     f'+{e["child_sessions"]}child)</span>')
        cost = f'${e["cost_usd"]}' if "cost_usd" in e else '<span class="dim">нет</span>'
        tok_in, tok_out = e.get("tokens_in_M", 0), e.get("tokens_out_M", 0)
        tok = (f"{tok_in:,.1f} / {tok_out:.2f} M".replace(",", " ")
               if tok_in or tok_out else '<span class="dim">нет</span>')
        note = esc(tool_notes.get(t, "")) if tool_notes else ""
        rows.append(f'<tr><th><span class="dot" style="background:'
                    f'{TOOL_COLOR.get(t, C["accent"])}"></span>{esc(t)}</th>'
                    f'<td class="num">{sess}</td><td class="num">{fmt(e.get("tool_calls", 0))}</td>'
                    f'<td class="num">{e.get("tool_errors", 0)}</td><td class="num">{tok}</td>'
                    f'<td class="num">{cost}</td><td>{note}</td></tr>')
    foot = (f'<tfoot><tr><td>итого</td><td class="num">{fmt(tot_sess)}</td>'
            f'<td class="num">{fmt(tot_calls)}</td><td class="num">{tot_err}</td>'
            f'<td class="num">—</td><td class="num"></td><td></td></tr></tfoot>')
    return "".join(rows) + foot


def section(sid, title, note, body):
    if not body:
        return ""
    note_html = f'<span class="note">{esc(note)}</span>' if note else ""
    return (f'<div class="section" id="{sid}">'
            f'<div class="section-header">{esc(title)}{note_html}</div>'
            f'<div class="section-body">{body}</div></div>')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="agentic-audit")
    args = ap.parse_args()

    data = os.path.join(args.out, "data")
    stats = load(os.path.join(data, "stats.json"))
    patterns = load(os.path.join(data, "user_patterns.json"))
    hl = load(os.path.join(data, "report_highlights.json")) or {}
    if not stats or not stats.get("overview"):
        raise SystemExit("no data/stats.json with overview — run compute_stats.py first")

    ov, tl = stats["overview"], stats.get("timeline", {})
    tools = [t for t in TOOL_ORDER if t in ov] or sorted(ov)
    days = sorted(tl)
    period = hl.get("period") or (f"{days[0]} — {days[-1]}" if len(days) > 1 else "")
    title = hl.get("title") or "Аудит ИИ-агентов"
    tot_calls = sum(e.get("tool_calls", 0) for e in ov.values())
    tot_sess = sum(e.get("sessions", 0) for e in ov.values())
    retries_n = stats.get("n_retry_events", 0)
    steering = patterns.get("steering_msgs")
    real = patterns.get("real_user_msgs_main")
    steer_share = f"{round(100 * steering / real)}%" if steering and real else "—"

    kpi = hl.get("kpi") or [
        [fmt(tot_sess), "сессий всего"],
        [fmt(tot_calls), "вызовов инструментов"],
        [str(retries_n), "retry-событий"],
        [steer_share, "стиринг владельца"],
    ]
    kpi_html = "".join(f'<div class="kpi"><b>{esc(k[0])}</b><span>{esc(k[1])}</span></div>'
                       for k in kpi)

    tl_svg = timeline_svg(tl, tools)
    tl_fig = (f'<figure>{tl_svg}<figcaption>Начала сессий по дням; высота — число сессий. '
              f'Эпохи инструментов читаются как смены полос.</figcaption></figure>' if tl_svg else "")
    rows = tool_rows(ov, hl.get("tool_notes") or {})
    tools_body = (f'<div class="kpis">{kpi_html}</div>'
                  f'<div style="margin:1rem 0">{tl_fig}</div>'
                  f'<table><thead><tr><th>инструмент</th><th class="num">сессий</th>'
                  f'<th class="num">вызовов</th><th class="num">ошибок</th>'
                  f'<th class="num">токены in/out</th><th class="num">стоим.</th>'
                  f'<th>роль / примечание</th></tr></thead><tbody>{rows}</tbody></table>')

    retries = stats.get("retries_top30", [])[:6]
    stuck_auto = "".join(
        f'<li class="assertion-item"><b class="st">×{r["repeats"]}</b>'
        f'{esc((r.get("cmd") or "")[:95].splitlines()[0])}</li>' for r in retries)
    stuck_hl = "".join(
        f'<li class="assertion-item"><b class="st">{esc(a)}</b>{esc(b)}</li>'
        for a, b in hl.get("stuck_loops", []))
    stuck_body = ""
    if stuck_auto or stuck_hl:
        stuck_body = f'<ul class="assertion-list">{stuck_hl}{stuck_auto}</ul>'

    cls_items = []
    if patterns:
        for label, v in patterns.get("classification", {}).items():
            color = C["red"] if label == "bugfix" else C["text"]
            cls_items.append((label, v, color))
    cls_body = f'<figure>{hbar_svg(cls_items)}</figure>' if cls_items else ""

    synth = patterns.get("synthetic_filtered")
    total_msgs = patterns.get("total_user_msgs_all")
    synth_note = (f"{synth} из {total_msgs} сообщений отфильтрованы как синтетика "
                  f"({round(100 * synth / total_msgs)}%)" if synth and total_msgs else "")

    quotes = "".join(
        f'<div class="quote"><div class="q-label">{esc(w)}</div>{esc(q)}</div>'
        for w, q in hl.get("owner_quotes", []))
    owner_body = ""
    if quotes:
        owner_body = quotes + (f'<p class="note-p">{esc(hl["owner_notes"])}</p>'
                               if hl.get("owner_notes") else "")

    waves = hl.get("defect_waves") or []
    waves_html = waves_svg(waves) if waves else ""
    chips = "".join(f'<span class="pill">{esc(c)}</span>'
                    for c in hl.get("repeat_escapes", []))
    esc_body = ""
    if waves_html or chips or hl.get("blind_spots"):
        esc_body = ((f'<figure>{waves_html}</figure>' if waves_html else "")
                    + (f'<div class="pills">{chips}</div>' if chips else "")
                    + (f'<p class="note-p">{esc(hl["blind_spots"])}</p>'
                       if hl.get("blind_spots") else ""))
    concl = "".join(f"<li>{c}</li>" for c in hl.get("conclusions", []))  # HTML allowed
    concl_body = (f'<ul class="notes" style="list-style:disc;padding-left:1.25rem">{concl}</ul>'
                  if concl else "")

    caveats = list(hl.get("extra_caveats", []))
    caveats += ["Метрики ошибок и стоимость несопоставимы между инструментами"
                f" (без cost-данных: {', '.join(stats.get('cost_untracked_tools', [])) or '—'}).",
                "Wall-часы включают простои открытых сессий; плотность работы — по вызовам."]
    if synth_note:
        caveats.append(synth_note + ".")
    caveats_html = "".join(f"<li>{esc(c)}</li>" for c in caveats)

    stuck_section = section("stuck", "Затыки и паттерны", "retry: ≥2 команды подряд",
                            stuck_body + cls_body)
    owner_section = section("owner", "Что владелец постоянно поправлял",
                            f"стиринг: {steer_share} сообщений", owner_body)
    esc_section = section("escapes", "Побеги дефектов и выводы", "", esc_body + concl_body)

    visible = {"overview", "caveats"}
    if stuck_section:
        visible.add("stuck")
    if owner_section:
        visible.add("owner")
    if esc_section:
        visible.add("escapes")
    tabs = [(sid, label) for sid, label in [
        ("overview", "Общая картина"), ("stuck", "Затыки"),
        ("owner", "Поправки владельца"), ("escapes", "Побеги и выводы"),
        ("caveats", "Оговорки")] if sid in visible]
    tabs_html = "".join(f'<a class="view-tab" href="#{sid}">{esc(label)}</a>'
                        for sid, label in tabs)

    page = f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)} — итоги аудита ИИ-агентов</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Lora:wght@400;500;600&family=Poppins:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>{CSS}</style>
</head>
<body>
<header class="header">
  <div>
    <h1>{esc(title)}<span class="sub">{esc(hl.get("subtitle", ""))}</span></h1>
    <div class="instructions">{esc(hl.get("intro", "Как кодинг-агенты работали над репозиторием — по их локальным логам."))}</div>
  </div>
  <div class="meta">{esc(period)}<br>agentic-usage-analysis · только чтение</div>
</header>
<nav class="view-tabs">{tabs_html}</nav>
<main class="main">
{section("overview", "Общая картина", hl.get("repo", ""), tools_body)}
{stuck_section}
{owner_section}
{esc_section}
{section("caveats", "Оговорки", "", f'<ul class="notes" style="list-style:disc;padding-left:1.25rem">{caveats_html}</ul>')}
</main>
<div class="footer-meta">Полный разбор — report.md · выгрузки — data/*_sessions.jsonl · дампы содержат секреты, не публиковать без санитайза</div>
<script>{SCROLLSPY}</script>
</body></html>"""

    out_path = os.path.join(args.out, "report.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(page)
    print(f"report.html written: {out_path} ({os.path.getsize(out_path):,} bytes)".replace(",", " "))
    if not hl:
        print("note: no data/report_highlights.json — qualitative sections skipped;"
              " write it per the format in this script's docstring and rerun")


if __name__ == "__main__":
    main()
