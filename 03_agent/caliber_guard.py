"""第 4 层校验：结果级「口径断言」(caliber guard) —— 校验反馈的结构化回灌。

为什么必须放在**执行之后**（面试考点）：
- 前三层（安全 / 语法 / schema）只能看 SQL 文本，只能判断「能不能跑」；
- 有一类错误 SQL 语法完全合法、EXPLAIN 通过、也能跑出结果，
  但数字是错的 —— 行数扇出、分母口径错、总体被过度过滤、粒度错。
  这些只有**拿到结果集**才能判。
- 所以第 4 层不改 SQL，而是"用结果反推口径"，把错误定位到**具体某一列、某一类口径**，
  生成一段结构化反馈回灌给 LLM 触发**定向重写**。这就是"校验反馈结构化回灌"。

设计决策：
- **与题号解耦**：断言只依赖结果列的「形状」（有州列？有分位列？单行总量？）和 SQL 文本，
  不依赖"这是第几题"。新增题目只要形状命中就自动被保护。
- **守恒量写死在文件顶部**，是 `CALIBER.md` 唯一真源的**代码镜像**；
  `caliber_check.py` 会校验两者不漂移。
- 断言失败 → 返回可读的修正提示；LLM 拿到的不是"你错了"，而是"哪一列、错在哪、怎么改"。

与 CALIBER.md 的对应：C1 全局总量、C14 高价值客户总体、C19 州订单数守恒、C20 州分布三列、
C21 时长不可扇出、C22 分层结果不得有互为副本的指标列。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# 口径守恒量（CALIBER.md 的代码镜像，改动必须同步登记表）
# ---------------------------------------------------------------------------
TOTAL_ORDERS = 99_440            # C1 / C19：只统计有支付记录(order_payments)的订单
TOTAL_GMV = 16_008_872.12        # C1：SUM(order_payments.payment_value)（实付口径）
TOTAL_ITEM_PRICE = 13_591_643.70  # C15：SUM(order_items.price)（商品售价口径，不含运费）
HIGH_VALUE_CUSTOMERS = 96_095    # C14：有支付记录订单覆盖的 customer_unique_id
QUINTILE_SIZE = 19_219           # C14：96,095 / 5，每档人数

_STATE_COLS = {"state", "customer_state", "shipping_state", "cust_state"}
_LAYER_COLS = ("quintile", "percentile", "segment", "bucket", "tier", "decile", "quantile")


@dataclass(frozen=True)
class Violation:
    """一条口径违规。caliber 是登记表编号，message 是给 LLM 的定向修正提示。"""

    caliber: str
    message: str

    def __str__(self) -> str:
        return f"[{self.caliber}] {self.message}"


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------
def _pick(cols, includes, excludes=()):
    """按列名子串挑出第一列：命中任一 include 且不含任何 exclude。"""
    for c in cols:
        lc = str(c).lower()
        if any(n in lc for n in includes) and not any(x in lc for x in excludes):
            return c
    return None


def _state_col(cols):
    for c in cols:
        if str(c).lower() in _STATE_COLS:
            return c
    return None


def _int(v):
    try:
        return int(round(float(v)))
    except (TypeError, ValueError):
        return None


def _float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _layered_shape(cols, sql):
    """结果是否为"分层"形状（有分位列，或 SQL 用了 NTILE）。C14 / C22 共用。"""
    low = re.sub(r"\s+", " ", (sql or "").lower())
    return (
        "ntile" in low
        or any(str(c).lower() in _LAYER_COLS for c in cols)
        or any(_pick(cols, (k,)) for k in _LAYER_COLS)
    )


# TopN / 排名类问法（含中文数字："前五"、"前十" 的"十"不是 \d，必须显式列出）
_TOPN_Q = re.compile(
    r"(前\s*[\d一二三四五六七八九十百千]+|top\s*\d+|排行|排名|最好的|最高的|最多的|最大的)",
    re.I,
)
# 问题里问到的指标（决定 C20 要求哪几列）
_MONEY_Q = re.compile(r"(金额|成交|销售额|销量额|营收|客单价|消费|gmv|收入|总额|赚)", re.I)
_DAYS_Q = re.compile(r"(时长|配送|送达|物流|发货|天数|几天|多少天|时效)", re.I)
# 问的是"整体画像 / 分布"→ 按项目约定要求三列齐全（Q5 原型）
_PROFILE_Q = re.compile(r"(分布|画像|概览|整体|全面|综合|情况)", re.I)


def _is_truncated_scope(question: str, sql: str, truncated: bool = False) -> bool:
    """结果是否只是总体的一部分（TopN / LIMIT 截断 / 窗口排名取前几 / 命中行数上限）。

    **守恒式的前提是"分组覆盖全集"。** 一旦外层做了 LIMIT、按排名取前 N，
    或者结果集**被 1000 行上限截断**，各组之和必然小于平台总量 ——
    这是**问题本身要求的部分视图**，不是口径错误。

    为什么必须加这道闸门（高压测试实测，两个真实误报）：
    1. 问"各州客单价排名前十的州"：正确 SQL（外层 LIMIT 10）被 C19 判成
       "订单数之和 = 3497 ≠ 99440"，又被 C20 判成"缺少平均配送时长"；
    2. 问"每个州每个品类每个卖家的销售额"：结果按州×品类×卖家分组有数万行，
       **被 1000 行上限截断**，C19 拿前 1000 行求和（316,688）去比全平台总额。
    两次都会把**完全正确**的答案反复回灌改错、最终标成 caliber_ok=false。
    误报比漏报更伤：漏报只是少抓一个错，误报会让正确结果被改坏。
    """
    if truncated:
        return True
    low = re.sub(r"\s+", " ", (sql or "").lower())
    if re.search(r"\blimit\b", low):
        return True
    if re.search(r"\b(?:rank|dense_rank|row_number|ntile)\s*\(", low) and _TOPN_Q.search(
        question or ""
    ):
        return True
    return False


def _money_reference(sql: str):
    """判断 SQL 里的"钱"是哪套口径，返回 (守恒值, 口径名, 口径编号)。

    项目里有两套金额口径，**不可混用**（prompt 已列，但模型仍会混）：
    - `order_payments.payment_value` → 实付总额 = 16,008,872.12（C1/C19）
    - `order_items.price`            → 商品售价总额 = 13,591,643.70（C15，不含运费）
    拿 GMV 常量去校验一个 price 口径的列，是断言自身的错误（高压测试实测误报）。
    """
    low = re.sub(r"\s+", " ", (sql or "").lower())
    if "payment_value" in low:
        return TOTAL_GMV, "总成交额(GMV)", "C19"
    if re.search(r"\bprice\b", low):
        return TOTAL_ITEM_PRICE, "商品售价总额", "C15"
    # 看不出口径时回退到**项目默认的金额口径**（实付 GMV），
    # 而不是"不查了" —— 默认比放行更符合 C1 的立意。
    return TOTAL_GMV, "总成交额(GMV)", "C19"


def _numeric_vector(rows, col):
    """取某列的数值向量；只要有一行取不到数就返回 None（说明不是纯数值列）。"""
    out = []
    for r in rows:
        if not isinstance(r, dict):
            return None
        v = _float(r.get(col))
        if v is None:
            return None
        out.append(round(v, 4))
    return out


# ---------------------------------------------------------------------------
# 断言 1：C1 —— 单行"全局总量"必须守恒
# ---------------------------------------------------------------------------
def check_global_totals(question, cols, rows, sql, truncated=False):
    """结果只有一行且含 total_orders / gmv 时，校验平台总量。

    命中场景：Q1（总订单 / GMV / 客单价）。
    典型错误：用 `orders` 单表数订单（99,441），或用 order_items.price 求和当 GMV。
    """
    if len(rows) != 1 or not isinstance(rows[0], dict):
        return []
    if _is_truncated_scope(question, sql, truncated):
        return []
    r0 = rows[0]
    out = []

    oc = _pick(cols, ("total_orders", "total_order"))
    if oc:
        n = _int(r0.get(oc))
        if n is not None and n != TOTAL_ORDERS:
            out.append(Violation("C1", (
                f"平台总订单数 = {n}，应为 {TOTAL_ORDERS}。"
                "订单数只统计「有支付记录」的订单：用 COUNT(DISTINCT order_id) 数 order_payments，"
                "不要直接数 orders（orders 表有 99,441 行，含 1 条无支付记录的订单），"
                "也不要用 JOIN 后的行数当订单数。"
            )))

    gc = _pick(cols, ("gmv", "total_payment", "total_amount", "total_revenue", "total_sales", "price"))
    if gc:
        target, label, cal = _money_reference(sql)
        g = _float(r0.get(gc))
        if target is not None and g is not None and abs(g - target) > 0.01:
            if cal == "C15":
                out.append(Violation("C15", (
                    f"商品售价总额 = {g}，应为 {TOTAL_ITEM_PRICE}。"
                    "商品/品类的『销售额』口径 = SUM(order_items.price)（商品售价，不含运费），"
                    "单表聚合、不要 JOIN 出扇出；它与实付总额 GMV 是两套口径，不可混用。"
                )))
            else:
                out.append(Violation("C1", (
                    f"总成交额 = {g}，应为 {TOTAL_GMV}。"
                    "GMV 口径 = SUM(order_payments.payment_value)；"
                    "不要用 order_items.price（那是商品售价，不含运费、是另一个口径），"
                    "也不要把 order_payments JOIN 到别的表后求和（会扇出放大金额）。"
                )))
    return out


# ---------------------------------------------------------------------------
# 断言 2：C19 —— 按州统计时，各州订单数 / GMV 之和 = 平台总量（两条守恒式）
# ---------------------------------------------------------------------------
def check_state_order_conservation(question, cols, rows, sql, truncated=False):
    """结果含"州"列时，各州订单数之和 = 99,440；金额之和 = 对应口径的平台总额。

    命中场景：Q5。这是本项目最经典的口径漂移 ——
    基线 41,745 vs 模型 41,746，差 1 单，就是分母总体选错。
    两条守恒式各抓一类错误：
    - 订单数偏大 → 用了 orders JOIN customers（含无支付记录的订单）；
    - 金额偏大 → 把 order_payments 与别的表 JOIN 后求和（行数扇出、金额放大）。

    **前提是"分组覆盖全集"**：SQL 带 LIMIT / 排名取前 N / 结果被 1000 行截断时，
    守恒式不成立，直接跳过（见 `_is_truncated_scope` 里的两次真实误报）。
    金额侧的参照值按 SQL 实际用的口径选（payment_value → C19，price → C15）。
    """
    if not _state_col(cols):
        return []
    if _is_truncated_scope(question, sql, truncated):
        return []
    out: list[Violation] = []

    oc = _pick(cols, ("order",), excludes=("value", "gmv", "amount", "rate", "day", "avg", "pct", "per"))
    if oc:
        vals = [v for v in (_int(r.get(oc)) for r in rows if isinstance(r, dict)) if v is not None]
        if sum(vals) != TOTAL_ORDERS:  # 空结果之和为 0，同样判违规
            total = sum(vals)
            if not vals:
                hint = ("结果集为空。按州统计不可能没有行，通常是 JOIN 的关联键写错"
                        "（例如用 customer_unique_id 去 JOIN orders.customer_id），请检查关联条件。")
            elif total > TOTAL_ORDERS:
                hint = ("订单数之和偏大，最常见的两种原因：① 用 orders 直接 JOIN customers 数订单，"
                        "多算了无支付记录的订单；② 在州粒度外层又 JOIN 回一对多的明细表（order_items 等），"
                        "把订单行扇出成了多行。正确写法：先用子查询/CTE 从 order_payments 按 order_id "
                        "聚合成一单一行，再与 orders / customers 内连接后按州 GROUP BY。")
            else:
                hint = ("订单数之和偏小，通常是把总体缩小了（例如按已签收 / 有评价过滤，"
                        "或漏掉了部分有支付记录的订单）。订单数口径 = 有支付记录订单的全集。")
            out.append(Violation("C19", (
                f"按州统计的订单数之和 = {total}，应为平台总订单数 {TOTAL_ORDERS}"
                f"（相差 {total - TOTAL_ORDERS:+d}）。{hint}"
            )))

    gc = _pick(cols, ("gmv", "amount", "revenue", "payment", "sales", "value", "price"),
               excludes=("avg", "per", "rate"))
    if gc:
        target, label, cal = _money_reference(sql)
        if target is not None:
            vals = [v for v in (_float(r.get(gc)) for r in rows if isinstance(r, dict)) if v is not None]
            if abs(sum(vals) - target) > 1.0:
                total = round(sum(vals), 2)
                if cal == "C15":
                    hint = (
                        "商品售价口径 = SUM(order_items.price)，必须**单表聚合**"
                        "（order_items 对同一订单是多行，JOIN 出去会扇出放大）。"
                        "注意它与实付口径 GMV（payment_value）是两套口径，不可混用、也不可相加。"
                    )
                else:
                    hint = (
                        "金额被放大的典型原因是把 order_payments 与 order_items 等『一单多行』的表 "
                        "JOIN 后求和（行数扇出）。正确写法：先把 order_payments 按 order_id "
                        "聚合成一单一行，再去 JOIN。"
                    )
                out.append(Violation(cal, (
                    f"按州统计的{label}之和 = {total}，应为 {target}"
                    f"（相差 {round(total - target, 2):+}）。{hint}"
                )))
    return out


# ---------------------------------------------------------------------------
# 断言 3：C20 —— 按州统计必须同时输出 订单数 / GMV / 平均配送时长
# ---------------------------------------------------------------------------
def check_state_output_columns(question, cols, rows, sql, truncated=False):
    """按州统计时，校验**问题真正问到的那几列**是否齐全。

    口径 C20 的原型是 Q5「各州订单分布 + 平均配送天数」，要求三列齐全。
    但如果把它当成"只要出现州列就必须三列"，就会和 prompt 的另一条硬规则
    「只输出回答该问题所必需的列，不要自行添加未被问到的衍生列」直接冲突 ——
    问"每个州有多少订单"时反而会被逼着补上 GMV 和配送时长（E2E 实测确实发生了）。

    所以判定改为**问题驱动**，二段式：
    1. 问的是"分布 / 画像 / 概览" → 按项目约定要求三列齐全（Q5 原型，行为不变）；
    2. 问到了具体指标（时长 / 金额） → 只要求它问到的那几列；
       **什么指标都没问到 → 不追加要求**（不能凭空判断"必须有什么列"，
       否则又会退回"逼模型加列"的老毛病）。

    TopN 场景一律跳过：问"各州客单价排名前十"时问题本身只要州 + 客单价。
    """
    if not _state_col(cols):
        return []
    if _is_truncated_scope(question, sql, truncated):
        return []
    money = _pick(cols, ("gmv", "amount", "revenue", "payment", "sales", "value", "spend", "price"))
    days = _pick(cols, ("day", "delivery", "duration", "timediff"))

    q = question or ""
    want_money = bool(_MONEY_Q.search(q))
    want_days = bool(_DAYS_Q.search(q))
    if _PROFILE_Q.search(q):
        want_money = want_days = True  # Q5 原型：问"分布"就要求三列齐全

    missing = []
    if want_money and not money:
        missing.append("GMV/成交额")
    if want_days and not days:
        missing.append("平均配送时长(天)")
    if not missing:
        return []
    return [Violation("C20", (
        f"按州统计必须输出问题问到的指标列，当前缺少：{'、'.join(missing)}。"
        "配送时长用 TIMESTAMPDIFF(DAY, order_purchase_timestamp, order_delivered_customer_date)，"
        "且不要因为未签收而过滤订单（AVG 会自动忽略空值）。"
    ))]


# ---------------------------------------------------------------------------
# 断言 4：C14 —— 高价值客户分层的总体守恒
# ---------------------------------------------------------------------------
def check_highvalue_population(question, cols, rows, sql, truncated=False):
    """结果含分位列（或 SQL 用了 NTILE）时，各档人数之和必须等于 96,095。

    命中场景：Q10。典型错误：把客户总体过滤成"已签收 / 有评价"的子集
    （分档人数变成 18,672 / 21,145 这种），或用 customer_id 而非 customer_unique_id。
    """
    low = re.sub(r"\s+", " ", (sql or "").lower())
    if not _layered_shape(cols, sql):
        return []

    cc = _pick(cols, ("customer",), excludes=(
        "unique", "id", "state", "city", "spend", "value", "avg", "amount", "per"))
    if not cc:
        return []

    vals = [_int(r.get(cc)) for r in rows if isinstance(r, dict)]
    vals = [v for v in vals if v is not None]
    total = sum(vals)

    if not vals:
        return [Violation("C14", (
            "高价值客户分层返回了 **0 行**，但 NTILE(5) 必须恰好输出 5 个分位。"
            "最常见的原因是分层后 JOIN 的关联键写错 —— 例如拿 `customer_unique_id` 去 JOIN "
            "`orders.customer_id`，两者不是同一套编码，JOIN 结果为空。"
            "正确做法：CTE 里按 `customer_unique_id` 汇总成『一客户一行』，"
            "外层只对该 CTE 按 quintile 做 GROUP BY，不要再 JOIN 订单明细表。"
        ))]

    if total == HIGH_VALUE_CUSTOMERS and len(vals) == 5:
        return []

    if total > HIGH_VALUE_CUSTOMERS:
        cause = (
            f"人数**偏大**（多了 {total - HIGH_VALUE_CUSTOMERS}），说明『人数』列被放大了 —— "
            "你很可能在分层之外又 JOIN 回了一对多的明细表（orders / order_items / order_payments，"
            "一个客户对应多行），使 COUNT(*) 数成了『行数』而不是『人数』。"
            "正确做法：分层只基于『一客户一行』的 CTE，外层直接对它的 quintile 分组计数，"
            "不要在分位外层再 JOIN 明细表。"
        )
    elif total < HIGH_VALUE_CUSTOMERS:
        cause = (
            f"人数**偏小**（少了 {HIGH_VALUE_CUSTOMERS - total}），说明客户总体被过度过滤 —— "
            "不要额外要求已签收 / 有评价 / 有金额，也不要漏掉在 orders 里有订单但在别处取不到的客户；"
            "用户身份用 customer_unique_id，不是 customer_id。"
        )
    else:
        cause = "分位个数不等于 5：NTILE(5) 必须恰好产生 5 个分位。"

    detail = "、".join(f"第{i + 1}档 {v}" for i, v in enumerate(vals))
    return [Violation("C14", (
        f"高价值客户各分档人数之和 = {total}（{len(vals)} 档：{detail}），"
        f"应为 {HIGH_VALUE_CUSTOMERS}，恰好分 5 档、每档 {QUINTILE_SIZE} 人。{cause}"
        "分层用 NTILE(5) OVER (ORDER BY 累计消费额 DESC)，外层按分位 GROUP BY 汇总。"
    ))]


# ---------------------------------------------------------------------------
# 断言 5：C21 —— 配送时长不得被"一单多付"扇出加权
# ---------------------------------------------------------------------------
def check_duration_fanout(question, cols, rows, sql, truncated=False):
    """SQL 把「一单多行」的表 JOIN 进来，又要对 TIMESTAMPDIFF 求 AVG，
    且没有任何一层按 order_id 预聚合 —— 时长会被多行放大。命中 DeepSeek Q5 的错误。

    只在真的出现 `JOIN order_payments / order_items` 时判（子查询 IN / EXISTS 不扇出行）；
    出现 `GROUP BY ... order_id` 视为已做订单粒度预聚合，放行。
    """
    low = re.sub(r"\s+", " ", (sql or "").lower())
    joined = re.search(r"\bjoin\s+(?:`?\w+`?\.)?`?order_(?:payments|items)\b", low)
    if not joined:
        return []
    if "timestampdiff" not in low or not re.search(r"\bavg\s*\(", low):
        return []
    order_grain = bool(re.search(r"group\s+by\s+(?:[\w]*\.)?`?order_id\b", low))
    if order_grain:
        return []
    return [Violation("C16", (
        "SQL 直接 JOIN 了 order_payments / order_items（对同一订单是多行），"
        "并在该粒度上求 AVG(TIMESTAMPDIFF(...))，但没有任何一层按 order_id 预聚合。"
        "JOIN 后行数被扇出，平均配送时长会按『订单行数』而不是『订单数』加权（同一单被重复计入）。"
        "正确写法：先用 CTE 按 order_id 把金额类表聚合成一单一行，"
        "再在**订单粒度**上求 AVG(TIMESTAMPDIFF(...))；"
        "或改用 `JOIN (SELECT order_id, SUM(...) FROM ... GROUP BY order_id)`。"
        "COUNT(DISTINCT order_id) 只能修正计数，救不了被扇出的 AVG / SUM。"
    ))]


# ---------------------------------------------------------------------------
# 断言 6：C22 —— 分层结果里不得出现"互为副本"的数值列
# ---------------------------------------------------------------------------
def check_layered_duplicate_metrics(question, cols, rows, sql, truncated=False):
    """分层结果中，两列取值完全相同 ⇒ 至少一列算错了。

    命中场景：Q10。两个 GLM 都把"人均单数"写成 `ROUND(SUM(total_spend) / COUNT(*), 2)`，
    于是它和"人均消费"取值一一相同 —— 因为那其实就是人均消费（客单价），不是单数。
    人均单数的量级是 ~1，人均消费是 ~40~450，量纲差两个数量级，不可能相等。
    """
    if not _layered_shape(cols, sql):
        return []
    vectors: dict[tuple, list[str]] = {}
    for c in cols:
        vec = _numeric_vector(rows, c)
        if vec and len(vec) >= 2:
            vectors.setdefault(tuple(vec), []).append(c)
    dups = [(v, names) for v, names in vectors.items() if len(names) > 1]
    if not dups:
        return []
    vec, names = dups[0]
    sample = "、".join(f"{x}" for x in vec[:5])
    return [Violation("C22", (
        f"结果里 `{names[0]}` 与 `{names[1]}` 的取值完全一样（{sample}…）——"
        "两个不同的指标不可能逐行相等，其中至少一列算错了。"
        "高价值客户分层要输出三个量：**人数**（COUNT(*)）、**人均消费**（AVG(total_spend)）、"
        "**人均单数**（每个客户的订单数，用 COUNT(DISTINCT order_id) 按客户统计后再取平均）。"
        "人均单数量级在 1 左右，绝不可能等于人均消费。"
        "正确做法：在分层前的 CTE 里同时算出 total_spend 与 order_count（COUNT(DISTINCT order_id)），"
        "外层分别 ROUND(AVG(total_spend),2) AS avg_spend、ROUND(AVG(order_count),2) AS avg_orders。"
    ))]


# ---------------------------------------------------------------------------
# 统一入口
# ---------------------------------------------------------------------------
_CHECKS = (
    check_global_totals,
    check_state_order_conservation,
    check_state_output_columns,
    check_highvalue_population,
    check_layered_duplicate_metrics,
    check_duration_fanout,
)


def check(question: str, sql: str, result: dict) -> list[Violation]:
    """对执行结果跑全部口径断言，返回违规列表（空列表 = 通过）。

    断言只依赖结果形状与 SQL 文本，与题号解耦；单条断言内部报错不影响其它断言。
    **空结果不豁免** —— "分层查询返回 0 行"本身就是典型的口径错误（关联键写错），
    所以这里只在拿不到列信息时才退出。

    注意：**守恒式类断言（C1/C19）在 TopN / LIMIT 场景下会主动跳过**（见
    `_is_truncated_scope`）—— 前提不成立时宁可不判，也不要误报把正确答案改坏。
    """
    result = result or {}
    rows = result.get("rows") or []
    cols = result.get("columns") or (
        list(rows[0].keys()) if rows and isinstance(rows[0], dict) else []
    )
    if not cols:
        return []
    out: list[Violation] = []
    truncated = bool(result.get("truncated"))
    for fn in _CHECKS:
        try:
            out.extend(fn(question, cols, rows, sql, truncated))
        except Exception:  # noqa: BLE001  断言自身异常不该拖垮主链路
            continue
    return out


def format_feedback(sql: str, violations: list[Violation]) -> str:
    """把违规列表拼成给 LLM 的结构化修正提示（回灌进 prompt 的 error_feedback）。"""
    lines = [
        "上一次生成的 SQL 能正常执行，但**结果违反了以下数据口径**，请针对性修正后重新输出 SQL：",
    ]
    for i, v in enumerate(violations, 1):
        lines.append(f"{i}. [{v.caliber}] {v.message}")
    lines.append("只修正上述问题，不要改动问题里其它已经正确的口径。")
    return "\n".join(lines)
