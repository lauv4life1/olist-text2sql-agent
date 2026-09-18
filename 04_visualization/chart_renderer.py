"""Plotly 渲染（Phase 4）。接收 sql_executor 的结果，输出 Plotly Figure。

**视觉：纸面铅印风（editorial / print）**，刻意避开"科技感 dashboard"那套
（深色底、霓虹渐变、圆角卡片、发光描边）：

- 暖白纸面底 + 墨色轴线，只有横向细参考线（像账本的行线），去掉竖网格与边框盒子；
- 双色主调：朱砂 `#A62B1F`（主）+ 靛青 `#1F4E4A`（次），其余为低饱和辅助色；
- 字体走衬线（Georgia + 宋体），数字用等宽，读起来像纸质报告而不是监控大屏；
- 分类名较长的柱状图**自动转成横向条形并排序** —— 中文品类名竖着排会挤成一团；
- 折线只给单序列加一层极淡的面积填充，多序列不加，避免图形过载。

**中文**：所有轴标题、图例、悬停、数据标签都走 `labels.py` 的对照表，
结果集里的州代码（`SP`）与品类英文名（`health_beauty`）也会翻成中文。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from chart_selector import classify  # noqa: E402
from labels import display_frame, zh_column, zh_value  # noqa: E402

# ---------------------------------------------------------------------------
# 主题常量（与 .streamlit/config.toml 保持一致，改一处要同步另一处）
# ---------------------------------------------------------------------------
INK = "#2B2620"          # 正文墨色
INK_SOFT = "#6B6257"     # 次级文字
PAPER = "#FFFDF8"        # 图表纸面
RULE = "#E4DCCD"         # 网格细线
AXIS = "#C4B9A6"         # 轴线
ACCENT = "#A62B1F"       # 朱砂（主色）
ACCENT_2 = "#1F4E4A"     # 靛青（次色）
PALETTE = [ACCENT, ACCENT_2, "#8A6A3B", "#4B5D7A", "#7A6A8C", "#5E7A4B", "#A8752B"]

FONT_SERIF = 'Georgia, "Songti SC", "STSong", SimSun, "Noto Serif SC", serif'
FONT_MONO = '"Consolas", "SFMono-Regular", "Courier New", monospace'

# 分类名超过这个长度就转横向条形（中文按字数算）
_H_BAR_LEN = 5
# 轴标签 / 图例名最大字符数（超长哈希 id 会撑爆画布，截断后完整值放 hover）
_LABEL_MAX = 16
_LEGEND_MAX = 14


def _short(s, n: int = _LABEL_MAX) -> str:
    s = str(s)
    return s if len(s) <= n else s[: n - 1] + "…"


def _disp_width(s: str) -> float:
    """估算显示宽度：一个汉字≈1 个字宽，ASCII≈0.55 个（用来算轴标签要占多少边距）。

    只数 `len(s)` 会低估中文标签（"第 1 档（高消费）"是 9 个字符但约 8.7 个字宽），
    左边距不够就把标签左半边裁掉 —— Q10 踩过。
    """
    return sum(1.0 if ord(ch) > 0x2E7F else 0.55 for ch in str(s))


def _second_metric(df, y: str, x: str = ""):
    """折线图的第二条数值列（用于右轴）。只认真正的数值列，且必须与主列 / x 列不同。"""
    import pandas as pd

    for c in df.columns:
        if c in (y, x):
            continue
        if pd.api.types.is_numeric_dtype(df[c]) and df[c].notna().any():
            return c
    return None


def _legend(fig):
    """多序列才画图例；统一成顶部横排、无边框、衬线小字。"""
    if len(fig.data) > 1:
        fig.update_layout(
            showlegend=True,
            legend=dict(
                orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
                bgcolor="rgba(0,0,0,0)", borderwidth=0,
                font=dict(family=FONT_SERIF, size=12, color=INK),
            ),
        )
    else:
        fig.update_layout(showlegend=False)


def _localize(result: dict, spec: dict) -> dict:
    """把 spec 里的列名换成中文，并返回已翻译的 DataFrame。"""
    df = display_frame(result)
    spec = dict(spec)
    for k in ("x", "y", "series", "label_col"):
        if spec.get(k):
            spec[k] = zh_column(spec[k])
    spec["value_cols"] = [zh_column(c) for c in spec.get("value_cols", [])]
    return spec, df


def _apply_theme(fig, *, title: str = ""):
    # 边距：各分支（横向条形的长标签 / 折线的旋转月份）会先算好自己的边距，
    # 这里**不能无条件覆盖** —— 否则那些自适应边距全是死代码（曾把 Q10 的中文标签裁掉）。
    m = fig.layout.margin
    if m is None or m.l is None:
        margin = dict(l=72, r=32, t=64 if title else 34, b=64)
    else:
        margin = dict(l=m.l, r=m.r if m.r is not None else 32,
                      t=m.t if m.t is not None else (64 if title else 34),
                      b=m.b if m.b is not None else 64)
    fig.update_layout(
        template="none",
        colorway=PALETTE,
        font=dict(family=FONT_SERIF, size=13, color=INK),
        paper_bgcolor=PAPER,
        plot_bgcolor=PAPER,
        bargap=0.42,
        margin=margin,
        height=430,
        hoverlabel=dict(
            bgcolor=INK, bordercolor=INK,
            font=dict(family=FONT_SERIF, size=12.5, color="#F8F5EE"),
        ),
        hovermode="closest",
    )
    if title:
        fig.update_layout(
            title=dict(
                text=title, x=0, xanchor="left", y=0.97, yanchor="top",
                font=dict(family=FONT_SERIF, size=15.5, color=INK),
            )
        )
    fig.update_xaxes(
        showgrid=False, zeroline=False, showline=True, linecolor=AXIS, linewidth=1,
        ticks="outside", ticklen=4, tickcolor=AXIS,
        tickfont=dict(family=FONT_SERIF, size=12, color=INK_SOFT),
        title_font=dict(family=FONT_SERIF, size=12.5, color=INK_SOFT),
    )
    fig.update_yaxes(
        showgrid=True, gridcolor=RULE, gridwidth=1, griddash="solid",
        zeroline=False, showline=False,
        tickfont=dict(family=FONT_MONO, size=11.5, color=INK),
        title_font=dict(family=FONT_SERIF, size=12.5, color=INK_SOFT),
    )
    return fig


def _bar(fig, spec, df):
    """柱状图：分类名长 → 横向条形（并按值升序，最大的在最上面）。"""
    x, y = spec["x"], spec["y"]
    labels = [str(v) for v in df[x].tolist()]
    long_labels = labels and max(len(s) for s in labels) > _H_BAR_LEN
    if long_labels:
        d = df.sort_values(y, ascending=True)
        fig = _new_bar(d, xvals=d[y], yvals=[_short(v) for v in d[x]],
                       full=[str(v) for v in d[x]], horizontal=True)
        fig.update_xaxes(title_text=y, showgrid=True, gridcolor=RULE,
                         tickfont=dict(family=FONT_MONO, size=11.5, color=INK))
        fig.update_yaxes(title_text="", showgrid=False, showline=True,
                         linecolor=AXIS, tickfont=dict(family=FONT_SERIF, size=12, color=INK))
        if len(d) <= 18:
            fig.update_traces(
                text=[f"{v:,.0f}" if abs(v) >= 100 else f"{v:,.2f}" for v in d[y]],
                textposition="outside", textfont=dict(family=FONT_MONO, size=11, color=INK_SOFT),
                cliponaxis=False,
            )
        # 左边距跟着标签实际显示宽度走，别让长 id / 中文标签被裁掉
        pad = 32 + 11.5 * max(_disp_width(_short(s)) for s in labels)
        fig.update_layout(margin=dict(l=int(min(pad, 210)), r=64, t=34, b=52))
    else:
        fig = _new_bar(df, xvals=df[x], yvals=df[y], horizontal=False)
        fig.update_xaxes(title_text=spec["x"])
        fig.update_yaxes(title_text=y)
        if len(df) <= 16:
            fig.update_traces(
                text=[f"{v:,.0f}" if abs(v) >= 100 else f"{v:,.2f}" for v in df[y]],
                textposition="outside", textfont=dict(family=FONT_MONO, size=11, color=INK_SOFT),
                cliponaxis=False,
            )
    return fig


def _new_bar(df, xvals, yvals, horizontal: bool, full=None):
    import plotly.graph_objects as go

    kw = dict(marker=dict(color=ACCENT, line=dict(width=0)))
    if full is not None:
        kw["customdata"] = list(full)
        kw["hovertemplate"] = "%{customdata}<br>%{x:,.2f}<extra></extra>"
    if horizontal:
        return go.Figure(go.Bar(x=list(xvals), y=list(yvals), orientation="h", **kw))
    return go.Figure(go.Bar(x=list(xvals), y=list(yvals), **kw))


def render(result: dict, localize: bool = True):
    """返回 plotly Figure；类型为 table / empty / indicator 时返回 None。

    `indicator` 交给前端渲染成 HTML 指标条（Plotly 的 indicator 卡片没有排印感）。
    """
    import plotly.graph_objects as go

    spec = classify(result)
    kind = spec["type"]
    if kind in ("empty", "table", "indicator"):
        return None

    df = display_frame(result)
    if df.empty:
        return None
    if localize:
        spec = dict(spec)
        for k in ("x", "y", "series"):
            if spec.get(k):
                spec[k] = zh_column(spec[k])

    if kind == "line":
        fig = go.Figure()
        if spec.get("series"):
            for i, (name, grp) in enumerate(df.groupby(spec["series"], sort=False)):
                fig.add_trace(go.Scatter(
                    x=list(grp[spec["x"]]), y=list(grp[spec["y"]]),
                    name=_short(name, _LEGEND_MAX), mode="lines+markers",
                    line=dict(width=1.8, color=PALETTE[i % len(PALETTE)]),
                    marker=dict(size=6, line=dict(width=1.6, color=PAPER)),
                    customdata=[str(name)] * len(grp),
                    hovertemplate="%{customdata}<br>%{x}　%{y:,.2f}<extra></extra>",
                ))
        else:
            fig.add_trace(go.Scatter(
                x=list(df[spec["x"]]), y=list(df[spec["y"]]),
                mode="lines+markers", name=spec["y"],
                line=dict(width=2.2, color=ACCENT),
                marker=dict(size=6.5, line=dict(width=1.6, color=PAPER)),
                fill="tozeroy", fillcolor="rgba(166,43,31,0.07)",
            ))
            # 时间序列常带两个指标（如"月销售额 + 月订单量"、"月签收量 + 平均配送天数"）。
            # 量纲差几个数量级，硬画在同一根轴上会把小量级那条压成直线，
            # 所以给第二条加**右轴**（点线 + 靛青 + 轴色同色，明确它读哪根轴）。
            y2 = _second_metric(df, spec["y"], spec["x"])
            if y2:
                fig.add_trace(go.Scatter(
                    x=list(df[spec["x"]]), y=list(df[y2]),
                    mode="lines+markers", name=y2, yaxis="y2",
                    line=dict(width=1.7, color=ACCENT_2, dash="dot"),
                    marker=dict(size=5.5, line=dict(width=1.4, color=PAPER)),
                ))
                fig.update_layout(
                    yaxis2=dict(overlaying="y", side="right", showgrid=False,
                                zeroline=False, showline=False, rangemode="tozero",
                                tickfont=dict(family=FONT_MONO, size=11.5, color=ACCENT_2),
                                title_font=dict(family=FONT_SERIF, size=12.5, color=ACCENT_2)),
                )
        fig.update_xaxes(title_text=spec["x"], tickangle=-45, nticks=11,
                         tickfont=dict(size=11), automargin=True)
        fig.update_yaxes(title_text=spec["y"])
        fig.update_layout(margin=dict(l=76, r=32, t=40, b=78))
        _legend(fig)
    elif kind == "bar":
        # 兜底闸门：x 有重复值时 Plotly 会把同名分组**累加**（Q6 曾把 4.9 的评分画成 49）。
        # 宁可不出图，也不出一张会骗人的图 —— 前端会提示"该结果形状不适合作图"。
        if spec["x"] in df.columns and df[spec["x"]].duplicated().any():
            return None
        fig = _bar(go.Figure(), spec, df)
    elif kind == "scatter":
        fig = go.Figure(go.Scatter(
            x=list(df[spec["x"]]), y=list(df[spec["y"]]), mode="markers",
            marker=dict(size=9, color=ACCENT, line=dict(width=1.6, color=PAPER)),
        ))
        fig.update_xaxes(title_text=spec["x"])
        fig.update_yaxes(title_text=spec["y"])
    else:
        return None

    return _apply_theme(fig)


def kpi_items(result: dict) -> list[tuple[str, str]]:
    """把单行结果拆成 [(中文标签, 显示值)]，供前端渲染指标条。"""
    rows = result.get("rows") or []
    if not rows:
        return []
    row = rows[0]
    out = []
    for c in (result.get("columns") or row.keys()):
        v = row.get(c)
        if isinstance(v, bool) or v is None:
            continue
        name = zh_column(c)
        if isinstance(v, float):
            if "率" in name or "占比" in name or "比率" in name:
                txt = f"{v * 100:.2f}%"
            elif abs(v) >= 1000:
                txt = f"{v:,.2f}"
            else:
                txt = f"{v:,.2f}"
        elif isinstance(v, int):
            txt = f"{v:,}"
        else:
            txt = str(v)
        out.append((name, txt))
    return out
