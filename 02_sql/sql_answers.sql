-- ============================================================================
-- Olist Text2SQL 项目 · Phase 2 手写 SQL 基线（10 个业务问题）
-- 数据库：olist_ecommerce（表名为短名：orders / order_items / order_payments ...）
-- 口径：成交额以 order_payments.payment_value（实付）为准。
-- 用法：在 MySQL 客户端（如 Workbench）选中 olist_ecommerce 库后逐条执行；
--       或运行 02_sql/sql_answers.py 自动执行并生成 baseline_results.json。
-- ============================================================================

-- Q1 总订单数 / 总成交额 / 客单价
-- 坑：order_payments 一个订单可能多行（分期），订单数必须 COUNT(DISTINCT order_id)
SELECT
  COUNT(DISTINCT order_id)                                AS total_orders,
  ROUND(SUM(payment_value), 2)                            AS gmv,
  ROUND(SUM(payment_value) / COUNT(DISTINCT order_id), 2) AS aov
FROM order_payments;

-- Q2 每月销售趋势
-- 坑：时间戳在 orders、金额在 order_payments，必须 JOIN
SELECT
  DATE_FORMAT(o.order_purchase_timestamp, '%Y-%m')        AS month,
  ROUND(SUM(p.payment_value), 2)                          AS monthly_gmv,
  COUNT(DISTINCT o.order_id)                              AS monthly_orders
FROM orders o
JOIN order_payments p ON o.order_id = p.order_id
GROUP BY month
ORDER BY month;

-- Q3 各品类销售额排名
-- 口径：销售额用 order_items.price（商品售价，不含运费，单表聚合无扇出）；
--       品类名用翻译表英文译名，翻译缺失时回退葡语原名
SELECT
  COALESCE(t.product_category_name_english, p.product_category_name) AS category,
  ROUND(SUM(oi.price), 2)                                 AS category_sales,
  COUNT(*)                                                AS items_sold
FROM order_items oi
JOIN products p ON oi.product_id = p.product_id
LEFT JOIN product_category_name_translation t
       ON p.product_category_name = t.product_category_name
GROUP BY category
ORDER BY category_sales DESC
LIMIT 10;

-- Q4 复购率
-- 坑：真实用户用 customer_unique_id（经 customers 表关联）；先子查询再算占比
SELECT
  COUNT(*)                                                AS total_customers,
  SUM(order_count >= 2)                                   AS repeat_customers,
  ROUND(SUM(order_count >= 2) / COUNT(*), 4)              AS repurchase_rate
FROM (
  SELECT c.customer_unique_id, COUNT(*) AS order_count
  FROM orders o
  JOIN customers c ON o.customer_id = c.customer_id
  GROUP BY c.customer_unique_id
) t;

-- Q5 各州订单分布 + 配送天数（orders + customers + order_payments 三表）
-- 坑：JOIN order_payments 会让订单行翻倍 → 先按"订单粒度"算配送天数再聚合
-- 口径：配送天数统一用 TIMESTAMPDIFF(DAY)（与 Q8 一致，满 24 小时算一天）
WITH per_order AS (
  SELECT
    o.order_id,
    c.customer_state,
    TIMESTAMPDIFF(DAY, o.order_purchase_timestamp, o.order_delivered_customer_date) AS delivery_days
  FROM orders o
  JOIN customers c ON o.customer_id = c.customer_id
),
order_gmv AS (
  SELECT order_id, SUM(payment_value) AS gmv
  FROM order_payments
  GROUP BY order_id
)
SELECT
  po.customer_state                                       AS state,
  COUNT(*)                                                AS orders,
  ROUND(SUM(g.gmv), 2)                                    AS gmv,
  ROUND(AVG(po.delivery_days), 1)                         AS avg_delivery_days
FROM per_order po
JOIN order_gmv g ON po.order_id = g.order_id
GROUP BY po.customer_state
ORDER BY orders DESC;

-- Q6 评分最高的产品 + 卖家（两条独立榜单）
-- 口径：题面问"产品和卖家分别是哪些" → 拆成产品榜与卖家榜各 Top10；
--       HAVING COUNT(*) >= 20 过滤样本量，避免"1 条 5 星"刷榜
WITH product_scores AS (
  SELECT
    oi.product_id,
    ROUND(AVG(r.review_score), 2)                           AS avg_score,
    COUNT(*)                                                AS review_count
  FROM order_items oi
  JOIN order_reviews r ON oi.order_id = r.order_id
  GROUP BY oi.product_id
  HAVING COUNT(*) >= 20
  ORDER BY avg_score DESC, review_count DESC
  LIMIT 10
),
seller_scores AS (
  SELECT
    oi.seller_id,
    ROUND(AVG(r.review_score), 2)                           AS avg_score,
    COUNT(*)                                                AS review_count
  FROM order_items oi
  JOIN order_reviews r ON oi.order_id = r.order_id
  GROUP BY oi.seller_id
  HAVING COUNT(*) >= 20
  ORDER BY avg_score DESC, review_count DESC
  LIMIT 10
)
SELECT 'product' AS entity_type, product_id AS entity_id, avg_score, review_count
FROM product_scores
UNION ALL
SELECT 'seller'  AS entity_type, seller_id  AS entity_id, avg_score, review_count
FROM seller_scores
ORDER BY entity_type, avg_score DESC, review_count DESC;

-- Q7 Top5 卖家月销售趋势（CTE 先取 Top5，再按月聚合 = 两个聚合层级）
WITH top5 AS (
  SELECT seller_id
  FROM order_items
  GROUP BY seller_id
  ORDER BY SUM(price) DESC
  LIMIT 5
)
SELECT
  oi.seller_id                                            AS seller_id,
  DATE_FORMAT(o.order_purchase_timestamp, '%Y-%m')        AS month,
  ROUND(SUM(oi.price), 2)                                 AS monthly_sales
FROM order_items oi
JOIN top5 t ON oi.seller_id = t.seller_id
JOIN orders o ON oi.order_id = o.order_id
GROUP BY oi.seller_id, month
ORDER BY oi.seller_id, month;

-- Q8 下单到签收平均时长（TIMESTAMPDIFF，按月趋势）
SELECT
  DATE_FORMAT(order_purchase_timestamp, '%Y-%m')          AS month,
  COUNT(*)                                                AS delivered_orders,
  ROUND(AVG(TIMESTAMPDIFF(DAY, order_purchase_timestamp, order_delivered_customer_date)), 1) AS avg_delivery_days
FROM orders
WHERE order_delivered_customer_date IS NOT NULL
GROUP BY month
ORDER BY month;

-- Q9 销售额环比下降的月份（LAG 取上一月）
WITH monthly AS (
  SELECT
    DATE_FORMAT(o.order_purchase_timestamp, '%Y-%m')      AS month,
    SUM(p.payment_value)                                  AS sales
  FROM orders o
  JOIN order_payments p ON o.order_id = p.order_id
  GROUP BY month
)
SELECT
  month,
  ROUND(sales, 2)                                         AS sales,
  ROUND(prev_sales, 2)                                    AS prev_sales,
  ROUND(sales - prev_sales, 2)                            AS delta
FROM (
  SELECT month, sales,
         LAG(sales) OVER (ORDER BY month) AS prev_sales
  FROM monthly
) t
WHERE sales < prev_sales
ORDER BY month;

-- Q10 高价值客户画像（CTE + NTILE 五分位，quintile=1 为最高消费组）
WITH spend AS (
  SELECT
    c.customer_unique_id,
    SUM(p.payment_value)                                  AS total_spend,
    COUNT(DISTINCT o.order_id)                            AS orders
  FROM orders o
  JOIN customers c       ON o.customer_id = c.customer_id
  JOIN order_payments p  ON o.order_id = p.order_id
  GROUP BY c.customer_unique_id
),
ranked AS (
  SELECT *, NTILE(5) OVER (ORDER BY total_spend DESC) AS quintile
  FROM spend
)
SELECT
  quintile,
  COUNT(*)                                                AS customers,
  ROUND(AVG(total_spend), 2)                              AS avg_spend,
  ROUND(AVG(orders), 2)                                   AS avg_orders
FROM ranked
GROUP BY quintile
ORDER BY quintile;
