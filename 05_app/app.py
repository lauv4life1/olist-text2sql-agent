"""Olist 电商数据分析 Agent —— 前端（Phase 5）。

**视觉取向：纸面铅印风（editorial / print）**

刻意不用"AI 感"的那套皮肤（深色底 + 紫蓝渐变 + 圆角发光卡片 + emoji 满屏），
而是走**纸质数据手记**的排印逻辑：

- 暖白纸面 + 墨色文字，唯一强调色是朱砂红；靛青只作图表次色；
- 报头 + 副题 + 双细分割线 + 章节编号（§ 01 / § 02），像刊物而不是面板；
- 标题衬线（Georgia / 宋体）、数字等宽、正文小字号高行距；
- 卡片改用**细线分区**而不是圆角阴影块；指标用排印式数字条而不是彩块；
- 不用 emoji，用文字标签与小型大写字母。

**中文**：图表由 `chart_renderer` 内部翻译，表格与指标条由 `labels.py` 翻译，
列名与州 / 品类等取值都会显示为中文。

运行：streamlit run 05_app/app.py
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "03_agent"))
sys.path.insert(0, str(ROOT / "04_visualization"))

from agent import ask  # noqa: E402
from chart_renderer import kpi_items, render  # noqa: E402
from chart_selector import classify  # noqa: E402
from labels import display_frame  # noqa: E402

INK = "#2B2620"
INK_SOFT = "#6B6257"
RULE = "#DED5C4"
ACCENT = "#A62B1F"
ACCENT_2 = "#1F4E4A"

# ---------------------------------------------------------------------------
# 样式
# ---------------------------------------------------------------------------
CSS = f"""
<style>
  /* ---- 去掉 Streamlit 自带的工具条 / 页脚 / 菜单 ---- */
  #MainMenu, footer, header[data-testid="stHeader"] {{display: none !important;}}
  [data-testid="stToolbar"], [data-testid="stDecoration"] {{display: none !important;}}
  [data-testid="stAppViewContainer"] {{background: #F7F3EA;}}
  .block-container {{padding: 1.6rem 2.2rem 3rem 2.2rem; max-width: 1180px;}}
  [data-testid="stSidebar"] {{background: #F2EDE1; border-right: 1px solid {RULE};}}
  [data-testid="stSidebar"] .block-container {{padding-top: 1.8rem;}}

  /* ---- 报头 ---- */
  .dj-masthead {{border-top: 3px solid {INK}; border-bottom: 1px solid {RULE};
                 padding: 12px 0 0 0; margin-bottom: 0;}}
  .dj-kicker {{display: flex; justify-content: space-between; align-items: baseline;
               font-size: 0.68rem; letter-spacing: 0.22em; color: {INK_SOFT};
               text-transform: uppercase; padding-bottom: 10px;}}
  .dj-title {{font-size: 2.5rem; line-height: 1.14; font-weight: 400; color: {INK};
              margin: 6px 0 8px 0; letter-spacing: 0.01em;}}
  .dj-title em {{font-style: normal; color: {ACCENT};}}
  .dj-deck {{font-size: 0.95rem; color: {INK_SOFT}; line-height: 1.85; max-width: 62ch;
             padding-bottom: 14px;}}
  .dj-double-rule {{border-top: 1px solid {RULE}; border-bottom: 1px solid {RULE};
                    height: 3px; margin: 0 0 22px 0;}}

  /* ---- 章节 ---- */
  .dj-section {{display: flex; align-items: baseline; gap: 12px; margin: 30px 0 6px 0;
                border-bottom: 1px solid {RULE}; padding-bottom: 7px;}}
  .dj-sec-no {{font-size: 0.7rem; letter-spacing: 0.2em; color: {ACCENT};
               border: 1px solid {ACCENT}; padding: 2px 7px; white-space: nowrap;}}
  .dj-sec-title {{font-size: 1.06rem; color: {INK}; letter-spacing: 0.04em;}}
  .dj-sec-note {{margin-left: auto; font-size: 0.74rem; color: {INK_SOFT};}}

  /* ---- 指标条（排印式，不用彩块卡片）---- */
  .dj-kpi-row {{display: flex; flex-wrap: wrap; gap: 0; border: 1px solid {RULE};
                background: #FFFDF8; margin: 6px 0 4px 0;}}
  .dj-kpi {{flex: 1 1 0; min-width: 150px; padding: 16px 20px 17px 20px;
            border-right: 1px solid {RULE};}}
  .dj-kpi:last-child {{border-right: none;}}
  .dj-kpi-label {{font-size: 0.7rem; letter-spacing: 0.16em; color: {INK_SOFT};
                  text-transform: uppercase; margin-bottom: 9px;}}
  .dj-kpi-value {{font-family: {('"Consolas", "SFMono-Regular", monospace')};
                  font-size: 1.62rem; color: {INK}; line-height: 1;}}

  /* ---- 结论 / 提示 ---- */
  .dj-quote {{border-left: 3px solid {ACCENT}; background: #FFFDF8; padding: 15px 20px;
              margin: 4px 0 2px 0; font-size: 1rem; line-height: 1.95; color: {INK};}}
  .dj-note {{font-size: 0.8rem; color: {INK_SOFT}; line-height: 1.8;}}
  .dj-badge {{display: inline-block; font-size: 0.72rem; letter-spacing: 0.1em;
              padding: 3px 9px; border: 1px solid; margin-right: 8px;}}
  .dj-badge-ok {{color: {ACCENT_2}; border-color: {ACCENT_2};}}
  .dj-badge-warn {{color: {ACCENT}; border-color: {ACCENT};}}
  .dj-badge-info {{color: {INK_SOFT}; border-color: {RULE};}}
  .dj-sql-caption {{font-size: 0.75rem; color: {INK_SOFT}; margin-bottom: 6px;}}

  /* ---- 控件 ---- */
  .stButton > button {{border-radius: 0; border: 1px solid {INK}; background: {INK};
      color: #F7F3EA; letter-spacing: 0.18em; font-size: 0.76rem; text-transform: uppercase;
      padding: 0.5rem 1.1rem; transition: none;}}
  .stButton > button:hover {{background: {ACCENT}; border-color: {ACCENT}; color: #FFFDF8;}}
  .stTextArea textarea {{border-radius: 0; border: 1px solid {RULE}; background: #FFFDF8;
      color: {INK}; font-size: 1rem; line-height: 1.8;}}
  .stTextArea textarea:focus {{border-color: {ACCENT}; box-shadow: none;}}
  [data-baseweb="select"] > div {{border-radius: 0; border-color: {RULE};
      background: #FFFDF8; font-size: 0.9rem;}}
  [data-testid="stExpander"] {{border-radius: 0; border: 1px solid {RULE};
      background: transparent;}}
  [data-testid="stExpander"] summary {{font-size: 0.85rem; color: {INK_SOFT};}}
  pre, code, kbd {{font-family: "Consolas", "SFMono-Regular", monospace !important;}}
  [data-testid="stCode"] {{border-radius: 0; border: 1px solid {RULE};
      border-left: 3px solid {ACCENT_2};}}
  [data-testid="stDataFrame"] {{border: 1px solid {RULE}; border-radius: 0;}}
  .stSpinner > div {{border-top-color: {ACCENT} !important;}}
  hr {{border-color: {RULE};}}
  .dj-foot {{margin-top: 34px; border-top: 1px solid {RULE}; padding-top: 12px;
             font-size: 0.72rem; color: {INK_SOFT}; line-height: 1.9;}}
</style>
"""


def _load_questions() -> list[dict]:
    spec = importlib.util.spec_from_file_location("questions", ROOT / "01_data" / "questions.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod.QUESTIONS


def section(no: str, title: str, note: str = "") -> None:
    st.markdown(
        f'<div class="dj-section"><span class="dj-sec-no">{no}</span>'
        f'<span class="dj-sec-title">{title}</span>'
        f'<span class="dj-sec-note">{note}</span></div>',
        unsafe_allow_html=True,
    )


def kpi_strip(items: list[tuple[str, str]]) -> None:
    cells = "".join(
        f'<div class="dj-kpi"><div class="dj-kpi-label">{label}</div>'
        f'<div class="dj-kpi-value">{value}</div></div>'
        for label, value in items
    )
    st.markdown(f'<div class="dj-kpi-row">{cells}</div>', unsafe_allow_html=True)


st.set_page_config(page_title="Olist 数据手记 · Text2SQL 分析 Agent", page_icon="▤",
                   layout="wide")
st.markdown(CSS, unsafe_allow_html=True)

if "history" not in st.session_state:
    st.session_state.history = []

questions = _load_questions()

# ---------------------------------------------------------------------------
# 报头
# ---------------------------------------------------------------------------
st.markdown(
    '<div class="dj-masthead">'
    '<div class="dj-kicker"><span>Olist · 数据手记 / Data Journal</span>'
    '<span>2016.09 — 2018.10　·　9 张表　·　99,440 笔订单</span></div>'
    '<div class="dj-title">把一句中文问句，<em>变成一份可信的数</em></div>'
    '<div class="dj-deck">输入业务问题 → 自动生成 SQL → 只读执行 → '
    '结果级口径守恒断言 → 图表与结论。<br>'
    '口径不是写在文档里的约定，而是执行后必须撞过去的断言。</div>'
    '</div><div class="dj-double-rule"></div>',
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# 侧栏
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown(
        f'<div class="dj-kicker" style="padding-bottom:6px;"><span>选题</span></div>',
        unsafe_allow_html=True,
    )
    pick = st.selectbox(
        "从 10 道业务问题里挑一个（或选「自定义」自己写）",
        ["（自定义）"] + [f"Q{q['id']:02d}　{q['title']}" for q in questions],
        label_visibility="collapsed",
    )
    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
    st.markdown(
        f'<div class="dj-note">'
        f'<b>本期看点</b><br>'
        f'· 口径登记表 C1–C23<br>'
        f'· 静态校验 4 层 + 断言 1 层<br>'
        f'· 攻击 SQL 28 条全拦<br>'
        f'· 对抗问题 18 个不崩<br>'
        f'· 本次已提问 {len(st.session_state.history)} 次'
        f'</div>',
        unsafe_allow_html=True,
    )

default_q = ""
if pick != "（自定义）":
    qid = int(pick.split("　")[0][1:])
    default_q = next(q["question"] for q in questions if q["id"] == qid)

section("§ 提问", "写下一个业务问题", note="中文即可，不必写 SQL")
question = st.text_area(
    "问题", value=default_q, height=86, label_visibility="collapsed",
    placeholder="例如：每个月的销售额走势如何？各州的平均配送时长差多少？",
)

col_a, _ = st.columns([1, 5])
with col_a:
    run = st.button("开始分析", type="primary", width="stretch")

# ---------------------------------------------------------------------------
# 执行
# ---------------------------------------------------------------------------
if run and not question.strip():
    st.markdown('<div class="dj-note">请先写下问题。</div>', unsafe_allow_html=True)
elif run:
    with st.spinner("正在生成并执行 SQL ..."):
        try:
            out = ask(question.strip())
        except Exception as exc:  # noqa: BLE001
            st.error(f"执行失败：{exc}")
            out = None
    if out:
        st.session_state.history.append(out)

        if out["status"] == "unanswerable":
            section("§ 回执", "这个问题，现有数据回答不了")
            st.markdown(
                f'<div class="dj-quote">{out.get("answer")}</div>',
                unsafe_allow_html=True,
            )
            st.markdown(
                f'<div class="dj-note" style="margin-top:10px;">'
                f'模型没有硬凑一条跑不通的 SQL。它按约定输出 '
                f'<code>CANNOT_ANSWER</code> 标记，链路就以「无法回答」收尾，'
                f'不占用重试预算。</div>',
                unsafe_allow_html=True,
            )
        elif out["status"] != "ok":
            section("§ 回执", "SQL 未通过校验")
            st.markdown(
                f'<div class="dj-quote"><span class="dj-badge dj-badge-warn">'
                f'{str(out.get("layer")).upper()}</span>{out.get("error")}</div>',
                unsafe_allow_html=True,
            )
            if out.get("sql"):
                st.code(out["sql"], language="sql", wrap_lines=True)
        else:
            attempts = out.get("attempts", 1)
            caliber_ok = out.get("caliber_ok", True)
            rows = out["result"]["rows"]

            # ---- § 01 生成的 SQL ----
            section("§ 01", "生成的 SQL",
                    note=f"temperature=0　·　生成重试 {attempts} 次")
            # 模型常把 SQL 写成一行，不换行会被横向裁掉 → 让它自动折行
            st.code(out["sql"], language="sql", wrap_lines=True)
            if out.get("warnings"):
                st.markdown(
                    f'<div class="dj-note">可能的未知标识符：'
                    f'{"、".join(out["warnings"])}</div>',
                    unsafe_allow_html=True,
                )

            # ---- § 02 口径校验 ----
            section("§ 02", "口径校验", note="结果级守恒断言（第 4 层）")
            if caliber_ok:
                st.markdown(
                    '<div class="dj-note">'
                    '<span class="dj-badge dj-badge-ok">口径通过</span>'
                    '结果满足守恒断言：全局总量 / 州维度守恒 / 分层总体 / 无扇出 / '
                    '行列不重复。这类断言不依赖人工基线 —— 各组之和必须等于总量，'
                    '数学上没得商量。</div>',
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    '<div class="dj-note">'
                    '<span class="dj-badge dj-badge-warn">口径未通过</span>'
                    f'重试 {attempts} 次后仍违反口径，<b>结果不建议直接采用</b>。</div>',
                    unsafe_allow_html=True,
                )
                with st.expander("查看违反了哪几处口径"):
                    for v in out.get("caliber_violations", []):
                        st.markdown(f"- {v}")

            # ---- § 03 业务结论 ----
            if out.get("conclusion"):
                section("§ 03", "业务结论")
                st.markdown(
                    f'<div class="dj-quote">{out["conclusion"]}</div>',
                    unsafe_allow_html=True,
                )

            # ---- § 04 图表 / 指标 ----
            spec = classify(out["result"])
            section("§ 04", "图表", note={
                "indicator": "单值结果 · 指标条",
                "line": "时间序列 · 折线",
                "bar": "分类比较 · 条形",
                "scatter": "两指标 · 散点",
            }.get(spec["type"], "按结果形状自动选图"))

            if spec["type"] == "indicator":
                items = kpi_items(out["result"])
                if items:
                    kpi_strip(items)
                else:
                    st.markdown('<div class="dj-note">该结果没有可显示的数值列。</div>',
                                unsafe_allow_html=True)
            else:
                fig = render(out["result"])
                if fig is not None:
                    st.plotly_chart(fig, width="stretch",
                                    config={"displayModeBar": False, "responsive": True})
                else:
                    st.markdown('<div class="dj-note">该结果形状不适合作图，见下方明细。</div>',
                                unsafe_allow_html=True)

            # ---- § 05 结果明细 ----
            section("§ 05", "结果明细",
                    note=f"{len(rows)} 行" + ("　·　已截断至 1000 行" if out["result"].get("truncated") else ""))
            df = display_frame(out["result"])

            cfg: dict[str, st.column_config.Column] = {}
            for c in df.columns:
                # 只给真正的数值列配格式；编号类 / 分类列保持原样（左对齐文本）
                if df[c].dtype.kind not in "if":
                    continue
                if "编号" in c or c in ("州", "商品品类", "榜单类型", "消费分层"):
                    continue
                try:
                    if "（元）" in c or "（天）" in c or "单数" in c:
                        cfg[c] = st.column_config.NumberColumn(format="%.2f")
                    elif "率" in c or "占比" in c:
                        cfg[c] = st.column_config.NumberColumn(format="%.4f")
                    else:
                        cfg[c] = st.column_config.NumberColumn(format="%d")
                except Exception:  # noqa: BLE001
                    continue
            st.dataframe(df, width="stretch", hide_index=True, column_config=cfg)

# ---------------------------------------------------------------------------
# 历史
# ---------------------------------------------------------------------------
if st.session_state.history:
    with st.expander(f"本次会话的提问记录（{len(st.session_state.history)} 条）"):
        for out in reversed(st.session_state.history):
            mark = {"ok": "已答复", "unanswerable": "无法回答"}.get(out["status"], "未通过")
            cal = out.get("caliber_ok")
            extra = "" if cal is None else ("　·　口径通过" if cal else "　·　口径存疑")
            st.markdown(
                f'<div class="dj-note" style="border-bottom:1px solid {RULE};'
                f'padding:7px 0;"><b>{out["question"]}</b>　'
                f'<span style="color:{INK_SOFT}">{mark}{extra}</span></div>',
                unsafe_allow_html=True,
            )

st.markdown(
    '<div class="dj-foot">'
    '口径守恒量：平台订单 99,440　·　实付总额 16,008,872.12　·　商品售价合计 13,591,643.70　·　'
    '高价值客户 96,095（5 档 × 19,219）<br>'
    '数据来源 Kaggle · Brazilian E-Commerce Public Dataset by Olist　|　'
    '完整口径登记表见 03_agent/CALIBER.md'
    '</div>',
    unsafe_allow_html=True,
)
