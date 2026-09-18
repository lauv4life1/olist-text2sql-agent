"""生成离线样例图 `sample_charts.html`（纸面铅印风 + 全中文）。

用途：给 README / 简历附件做「后端可视化能力」的静态证据 —— 不启动 Streamlit
也能看到 chart_selector 自动选图 + chart_renderer 渲染 + labels 中文化的完整链路。

运行：
    python 04_visualization/make_sample_charts.py

数据源：`02_sql/baseline_results.json`（真实跑库产物，非手写假数据）。
"""
from __future__ import annotations

import html
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

from chart_renderer import PAPER  # noqa: E402
from chart_renderer import kpi_items, render  # noqa: E402
from chart_selector import classify  # noqa: E402

BASELINE = ROOT / "02_sql" / "baseline_results.json"
OUT = HERE / "sample_charts.html"

_KIND_ZH = {
    "indicator": "指标卡",
    "line": "折线",
    "bar": "柱状 / 条形",
    "scatter": "散点",
    "table": "表格",
    "empty": "空结果",
}


def _kpi_html(items: list[tuple[str, str]]) -> str:
    cells = "".join(
        f'<div class="kpi"><div class="kpi-l">{html.escape(lab)}</div>'
        f'<div class="kpi-v">{html.escape(val)}</div></div>'
        for lab, val in items
    )
    return f'<div class="kpi-row">{cells}</div>'


def main() -> int:
    data = json.loads(BASELINE.read_text(encoding="utf-8"))
    qs = [data[k] for k in sorted(data, key=lambda x: int(x))]
    plotly_js_done = False
    blocks: list[str] = []

    for q in qs:
        rows = q.get("rows") or []
        cols = list(rows[0].keys()) if rows else []
        result = {"columns": cols, "rows": rows}
        spec = classify(result)
        kind = spec["type"]
        title = q.get("title") or q.get("question") or ""
        qid = q.get("id")

        if kind == "indicator":
            body = _kpi_html(kpi_items(result))
        else:
            fig = render(result)
            if fig is None:
                body = '<p class="note">该结果以表格呈现，无图形。</p>'
            else:
                body = fig.to_html(
                    full_html=False,
                    include_plotlyjs=("cdn" if not plotly_js_done else False),
                    config={"displayModeBar": False, "responsive": True},
                )
                plotly_js_done = True

        blocks.append(
            f'<section class="q">'
            f'<div class="q-head"><span class="q-no">Q{qid}</span>'
            f'<h2>{html.escape(title)}</h2>'
            f'<span class="q-tag">{_KIND_ZH.get(kind, kind)}</span></div>'
            f'<p class="q-ask">{html.escape(q.get("question", ""))}</p>'
            f'{body}</section>'
        )

    doc = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Olist Text2SQL · 可视化样例（纸面铅印风）</title>
<style>
  :root {{
    --ink:#2B2620; --ink-soft:#6B6257; --paper:{PAPER}; --bg:#F7F3EA;
    --rule:#E4DCCD; --accent:#A62B1F;
    --serif: Georgia, "Songti SC", "STSong", "Noto Serif SC", SimSun, serif;
    --mono: "Consolas", "SFMono-Regular", "Courier New", monospace;
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; padding:48px 24px 80px; background:var(--bg); color:var(--ink);
         font-family:var(--serif); font-size:15px; line-height:1.75; }}
  .wrap {{ max-width:960px; margin:0 auto; }}
  .kicker {{ font-size:11.5px; letter-spacing:.22em; text-transform:uppercase;
             color:var(--ink-soft); margin:0 0 10px; }}
  h1 {{ font-size:30px; line-height:1.3; margin:0 0 6px; font-weight:600;
        border-top:3px solid var(--ink); padding-top:16px; }}
  h1 em {{ font-style:normal; color:var(--accent); }}
  .deck {{ color:var(--ink-soft); margin:0 0 10px; font-size:14.5px; }}
  .meta {{ font-family:var(--mono); font-size:12px; color:var(--ink-soft);
           border-bottom:1px solid var(--rule); padding-bottom:14px;
           display:flex; gap:20px; flex-wrap:wrap; }}
  .q {{ background:var(--paper); border:1px solid var(--rule); border-top:2px solid var(--ink);
        padding:22px 26px 12px; margin:26px 0 0; }}
  .q-head {{ display:flex; align-items:baseline; gap:10px; flex-wrap:wrap; }}
  .q-no {{ font-family:var(--mono); font-size:12px; color:var(--accent);
           border:1px solid var(--accent); padding:1px 7px; letter-spacing:.06em; }}
  .q-head h2 {{ font-size:17px; margin:0; font-weight:600; flex:1 1 auto; }}
  .q-tag {{ font-size:11.5px; letter-spacing:.14em; color:var(--ink-soft);
            border-bottom:1px solid var(--rule); }}
  .q-ask {{ color:var(--ink-soft); font-size:13.5px; margin:8px 0 14px;
            border-left:3px solid var(--rule); padding-left:10px; }}
  .kpi-row {{ display:flex; flex-wrap:wrap; gap:0; margin:6px 0 14px;
              border-top:1px solid var(--rule); border-bottom:1px solid var(--rule); }}
  .kpi {{ flex:1 1 160px; padding:14px 18px; border-right:1px solid var(--rule); }}
  .kpi:last-child {{ border-right:0; }}
  .kpi-l {{ font-size:12.5px; color:var(--ink-soft); margin-bottom:4px; }}
  .kpi-v {{ font-family:var(--mono); font-size:25px; color:var(--accent);
            letter-spacing:-.01em; }}
  .note {{ color:var(--ink-soft); font-size:13.5px; }}
  footer {{ margin-top:34px; border-top:1px solid var(--rule); padding-top:12px;
            font-family:var(--mono); font-size:11.5px; color:var(--ink-soft); }}
</style></head>
<body><div class="wrap">
<p class="kicker">Olist · 数据手记 / Data Journal</p>
<h1>后端可视化样例 · <em>纸面铅印风</em></h1>
<p class="deck">真实数据 → 自动选图 → 中文标签 → 排印式渲染。以下图形由
<code>chart_selector</code> + <code>chart_renderer</code> 直接产出，未手工调整。</p>
<div class="meta"><span>2016.09 — 2018.10</span><span>9 张表 · 99,440 笔订单</span>
<span>数据源 02_sql/baseline_results.json</span></div>
{"".join(blocks)}
<footer>生成脚本 04_visualization/make_sample_charts.py · 主题常量与
.streamlit/config.toml 同步 · 配色：朱砂 #A62B1F / 靛青 #1F4E4A</footer>
</div></body></html>
"""
    OUT.write_text(doc, encoding="utf-8")
    print(f"OK -> {OUT}  ({len(doc):,} chars, {len(qs)} questions)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
