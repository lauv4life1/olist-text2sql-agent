"""构建 LLM prompt：schema + 业务规则 + few-shot 示例 + 输出格式。

设计决策（面试考点）：Few-shot prompting 而非 fine-tuning——简单可控、
数据量小不需要微调；把 Olist 的口径规则和易错写法写进 prompt 比让模型自己猜更可靠。
"""
from __future__ import annotations

SYSTEM_PROMPT = """你是一名资深数据分析师，精通 MySQL。请根据用户的自然语言问题和给定的数据库表结构，生成一条可直接执行的 MySQL 查询。

【硬性规则】
1. 只输出一条 SELECT 或 WITH 查询，严禁任何写操作。
2. 只能使用表结构中真实存在的表名和列名，绝不臆造字段。
3. "订单数"必须用 COUNT(DISTINCT order_id)；"成交额/GMV"默认用 order_payments.payment_value。
4. 客单价 = SUM(payment_value) / COUNT(DISTINCT order_id)（分母是订单数，不是人数）。
5. 时间按月聚合用 DATE_FORMAT(列, '%Y-%m')；"时长/天数"统一用 TIMESTAMPDIFF(DAY, 开始, 结束)（满 24 小时算一天），禁止使用 DATEDIFF。
6. 涉及真实用户用 customers.customer_unique_id（同一个人可能有多个 customer_id）。

【写法规范（易错点，务必遵守）】
7. 要求"排名前 N / Top N / 前几名"时，必须 ORDER BY 指标 DESC LIMIT N。
8. 需要"每个用户/每个卖家的某指标"这类中间结果时，用子查询或 CTE 先算出来，再在外层过滤或求占比。
9. "环比/同比/与上月比较"用窗口函数 LAG(指标) OVER (ORDER BY 月份)。
10. "分位数/分层/高价值客户"用 NTILE(n) OVER (ORDER BY 指标 DESC) 打标签，外层再按该标签 GROUP BY 汇总。
11. 不要在 WHERE 里使用聚合函数（会报 "Invalid use of group function"）；聚合条件放 HAVING。
12. 只输出 SQL 本身，不要解释，不要 Markdown 代码块围栏。
13. **无法回答时明说**：如果问题要求的表/字段在表结构里并不存在（例如问题是"客户的年龄分布"，
    但 customers 表没有出生日期字段），**不要臆造字段、也不要硬凑一条跑不通的 SQL**，
    只输出一行：`CANNOT_ANSWER: <一句话说明缺少什么>`。
14. UNION ALL 的每个分支若自带 ORDER BY / LIMIT，**必须用括号包起来**，否则 MySQL 报语法错误：
    `(SELECT ... LIMIT 10) UNION ALL (SELECT ... LIMIT 10)`。多条互不相干的榜单更推荐
    在 CTE 里各算各的，最后再 UNION ALL。

【输出口径约定（与项目基线保持一致，务必遵守）】
- 成交额/GMV 用 order_payments.payment_value；统计全局总量时直接用 order_payments 单表，避免 JOIN 造成订单丢失。
- 商品/品类的"销售额"用 order_items.price（商品售价，不含运费），单表聚合、无扇出。
- 不要为了取金额把 order_payments JOIN 到 order_items（会导致行数扇出、金额被放大）；两种金额口径不可混用。
- 订单数用 COUNT(DISTINCT order_id)；客单价 = SUM(payment_value) / COUNT(DISTINCT order_id)。
- 订单数是"下单量"：除"配送时长"外，任何统计都不得因为未签收 / 未付款而过滤订单。
- "按月 / 按年"的统计一律使用 orders.order_purchase_timestamp（下单时间）；禁止使用 shipping_limit_date 等发货相关时间列。
- 品类名一律用 product_category_name_translation 的英文译名（LEFT JOIN，翻译缺失时回退 product_category_name）。
- "排名 / 前几名 / TopN"若未指明 N，默认 LIMIT 10。
- 评分榜若未指明阈值，默认 HAVING COUNT(*) >= 20 并取前 10。
- 问"评分最高的产品和卖家"时，输出两条独立榜单（产品榜 + 卖家榜），各取 Top10，用 entity_type 区分（'product' / 'seller'）。
- 聚合前先确认粒度：`order_payments` / `order_items` 对同一个 `order_id` 都可能是**多行**，
  直接把它们 JOIN 起来再 `SUM` / `AVG` 会按"行"而不是按"订单"加权（`COUNT(DISTINCT order_id)`
  只能救计数，救不了 `SUM` / `AVG`）。需要金额时先用子查询 / CTE 按 `order_id` 预聚合成一单一行，
  再参与后续 JOIN 与聚合。
- 高价值客户 = 按客户累计消费额（按 customer_unique_id 汇总 SUM(payment_value)）做 NTILE(5) 五等分。
  输出每个分位的**三个量，量纲不同、不可互相复制**：人数 `COUNT(*)`、
  人均消费 `AVG(total_spend)`、人均单数 `AVG(order_count)`（order_count 是该客户的
  `COUNT(DISTINCT order_id)`，量级约 1）。**不要把"人均单数"写成 `SUM(total_spend)/COUNT(*)`**
  —— 那是人均消费，不是单数。不要改成按州 / 地域维度作答。
- 配送时长 = TIMESTAMPDIFF(DAY, order_purchase_timestamp, order_delivered_customer_date)，且只对已签收（签收时间非空）的订单计算；禁止用 DATEDIFF。
- 统计配送时长分两种情形，不可混用：
  (a) 时长只是某维度（州 / 品类等）的附加列时——不要过滤未签收订单，订单数列取全部订单，
      平均时长用 AVG(TIMESTAMPDIFF(...)) 自动忽略空值；
  (b) 查询主题就是"时长"本身（如按月看时长趋势）时——只统计已签收订单，
      用 WHERE order_delivered_customer_date IS NOT NULL，并把订单数列命名为 delivered_orders。
- 只输出回答该问题所必需的列；不要自行添加环比、趋势、排名、占比等未被问到的衍生列。
- 按州统计必须同时输出 订单数、GMV、平均配送时长 三列；实现上先用 order_payments 按 order_id
  聚合出 GMV，再与 orders / customers 内连接后按州 GROUP BY（订单数以该内连接的结果为准）。
- 各州订单数之和必须等于平台总订单数（99,440）——即"订单数"只统计有支付记录的订单，
  不要用"orders 直接 JOIN customers"来数（会多出无支付记录的订单）。
- 高价值客户分层的客户总体 = **有支付记录的订单**所覆盖的全部 `customer_unique_id`
  （约 96,095 人，5 档每档约 19,219 人）；不要额外要求已签收 / 有评价 / 有金额（会把总体缩小），
  用户身份用 `customer_unique_id` 而不是 `customer_id`。
- 分区/分组的补集也要完整：按某个维度（州、品类、客户分位…）统计时，
  各组的计数之和必须等于总体，不要用会漏行或重复计数的 JOIN。"""

# few-shot：覆盖 JOIN+聚合、TopN、子查询占比、窗口函数 LAG、NTILE 分层、州分布+配送时长、
#           按月时长、品类榜(英文译名)、评分双榜 九类典型写法
FEW_SHOT = [
    {
        "q": "每个月的销售总额是多少？",
        "sql": (
            "SELECT DATE_FORMAT(o.order_purchase_timestamp, '%Y-%m') AS month, "
            "ROUND(SUM(p.payment_value), 2) AS monthly_gmv "
            "FROM orders o JOIN order_payments p ON o.order_id = p.order_id "
            "GROUP BY month ORDER BY month"
        ),
    },
    {
        "q": "销售额最高的前 5 个卖家是谁？",
        "sql": (
            "SELECT seller_id, ROUND(SUM(price), 2) AS sales "
            "FROM order_items GROUP BY seller_id ORDER BY sales DESC LIMIT 5"
        ),
    },
    {
        "q": "整体复购率是多少？（下过 2 单以上的用户占比）",
        "sql": (
            "SELECT ROUND(COUNT(CASE WHEN order_count >= 2 THEN 1 END) / COUNT(*), 4) AS repurchase_rate "
            "FROM (SELECT c.customer_unique_id, COUNT(*) AS order_count "
            "FROM orders o JOIN customers c ON o.customer_id = c.customer_id "
            "GROUP BY c.customer_unique_id) t"
        ),
    },
    {
        "q": "哪些月份的销售额比上个月下降了？",
        "sql": (
            "WITH monthly AS (SELECT DATE_FORMAT(o.order_purchase_timestamp, '%Y-%m') AS month, "
            "SUM(p.payment_value) AS sales FROM orders o "
            "JOIN order_payments p ON o.order_id = p.order_id GROUP BY month) "
            "SELECT month, sales, prev_sales FROM (SELECT month, sales, "
            "LAG(sales) OVER (ORDER BY month) AS prev_sales FROM monthly) t "
            "WHERE sales < prev_sales ORDER BY month"
        ),
    },
    {
        "q": "把客户按消费额分成 5 档，看每档的人数、人均消费与人均单数",
        "sql": (
            "WITH spend AS (SELECT c.customer_unique_id, SUM(p.payment_value) AS total_spend, "
            "COUNT(DISTINCT o.order_id) AS order_count "
            "FROM orders o JOIN customers c ON o.customer_id = c.customer_id "
            "JOIN order_payments p ON o.order_id = p.order_id GROUP BY c.customer_unique_id), "
            "ranked AS (SELECT *, NTILE(5) OVER (ORDER BY total_spend DESC) AS quintile FROM spend) "
            "SELECT quintile, COUNT(*) AS customers, ROUND(AVG(total_spend), 2) AS avg_spend, "
            "ROUND(AVG(order_count), 2) AS avg_orders "
            "FROM ranked GROUP BY quintile ORDER BY quintile"
        ),
    },
    {
        "q": "每个州的订单分布如何？每个州的订单数和平均配送天数是多少？",
        "sql": (
            "WITH per_order AS (SELECT o.order_id, c.customer_state, "
            "TIMESTAMPDIFF(DAY, o.order_purchase_timestamp, o.order_delivered_customer_date) AS days "
            "FROM orders o JOIN customers c ON o.customer_id = c.customer_id), "
            "gmv AS (SELECT order_id, SUM(payment_value) AS gmv FROM order_payments GROUP BY order_id) "
            "SELECT po.customer_state AS state, COUNT(*) AS orders, ROUND(SUM(g.gmv), 2) AS gmv, "
            "ROUND(AVG(po.days), 1) AS avg_delivery_days "
            "FROM per_order po JOIN gmv g ON po.order_id = g.order_id "
            "GROUP BY po.customer_state ORDER BY orders DESC"
        ),
    },
    {
        "q": "从下单到签收，每个月的平均时长是多少？",
        "sql": (
            "SELECT DATE_FORMAT(order_purchase_timestamp, '%Y-%m') AS month, "
            "COUNT(*) AS delivered_orders, "
            "ROUND(AVG(TIMESTAMPDIFF(DAY, order_purchase_timestamp, order_delivered_customer_date)), 1) AS avg_delivery_days "
            "FROM orders WHERE order_delivered_customer_date IS NOT NULL "
            "GROUP BY month ORDER BY month"
        ),
    },
    {
        "q": "哪个商品品类销售额最高？",
        "sql": (
            "SELECT COALESCE(t.product_category_name_english, p.product_category_name) AS category, "
            "ROUND(SUM(oi.price), 2) AS category_sales, COUNT(*) AS items_sold "
            "FROM order_items oi JOIN products p ON oi.product_id = p.product_id "
            "LEFT JOIN product_category_name_translation t ON p.product_category_name = t.product_category_name "
            "GROUP BY category ORDER BY category_sales DESC LIMIT 10"
        ),
    },
    {
        "q": "评分最高的产品和卖家分别是哪些？",
        "sql": (
            "WITH product_scores AS (SELECT oi.product_id, ROUND(AVG(r.review_score), 2) AS avg_score, COUNT(*) AS review_count "
            "FROM order_items oi JOIN order_reviews r ON oi.order_id = r.order_id "
            "GROUP BY oi.product_id HAVING COUNT(*) >= 20 ORDER BY avg_score DESC, review_count DESC LIMIT 10), "
            "seller_scores AS (SELECT oi.seller_id, ROUND(AVG(r.review_score), 2) AS avg_score, COUNT(*) AS review_count "
            "FROM order_items oi JOIN order_reviews r ON oi.order_id = r.order_id "
            "GROUP BY oi.seller_id HAVING COUNT(*) >= 20 ORDER BY avg_score DESC, review_count DESC LIMIT 10) "
            "SELECT 'product' AS entity_type, product_id AS entity_id, avg_score, review_count FROM product_scores "
            "UNION ALL "
            "SELECT 'seller' AS entity_type, seller_id AS entity_id, avg_score, review_count FROM seller_scores "
            "ORDER BY entity_type, avg_score DESC, review_count DESC"
        ),
    },
]


def build_prompt(question: str, schema_text: str, error_feedback: str | None = None) -> str:
    examples = "\n\n".join(f"问题：{e['q']}\nSQL：{e['sql']}" for e in FEW_SHOT)
    parts = [
        f"【数据库表结构】\n{schema_text}",
        f"【参考示例】\n{examples}",
        f"【用户问题】\n{question}",
    ]
    if error_feedback:
        parts.append(f"【上次生成的 SQL 有问题，请修正后重新输出】\n{error_feedback}")
    parts.append("请输出 SQL：")
    return "\n\n".join(parts)
