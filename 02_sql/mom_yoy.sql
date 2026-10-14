-- ============================================================
-- 环比 / 同比 分析模板（教学版）
--
-- 【概念课】
-- 环比(MoM)：跟上一个周期比。本月 vs 上月 —— 看"短期变化"。
-- 同比(YoY)：跟去年同期比。今年8月 vs 去年8月 —— 排除季节性，看"真实增长"。
-- 为什么要分两个？因为有季节性。月饼9月暴增10月暴跌，
--   环比-50%别慌（中秋过了），同比-20%才是真问题（今年不如去年卖得好）。
--   一句话：环比看短期波动，同比看真实趋势。
--
-- 【口径】与项目既有口径一致（见 sql_answers.sql 第29行注释）：
--   销售额 = SUM(order_items.price)（商品售价，不含运费）
--   排除已取消订单 order_status <> 'canceled'
--
-- 【窗口函数 LAG 课】
--   LAG(列) OVER (ORDER BY 排序列) = 取"上一行"的值。
--   环比的本质就是：本月GMV ÷ 上月GMV - 1，而上月GMV用 LAG 一行取到。
-- ============================================================

-- ---------- 查询1：月度GMV + 环比 ----------
WITH monthly AS (
    SELECT
        DATE_FORMAT(o.order_purchase_timestamp, '%Y-%m') AS month,
        ROUND(SUM(oi.price), 2)                          AS gmv
    FROM orders o
    JOIN order_items oi ON o.order_id = oi.order_id
    WHERE o.order_status <> 'canceled'
    GROUP BY month
)
SELECT
    month,
    gmv,
    LAG(gmv) OVER (ORDER BY month)                          AS last_month_gmv,
    ROUND((gmv / LAG(gmv) OVER (ORDER BY month) - 1) * 100, 2) AS mom_pct
FROM monthly
ORDER BY month;

-- ---------- 查询2：月度GMV + 同比 ----------
-- 同比用"自连接"：把 monthly 表连自己一次，
-- 连接条件 = a的月份 恰好等于 b的月份加12个月。
WITH monthly AS (
    SELECT
        DATE_FORMAT(o.order_purchase_timestamp, '%Y-%m') AS month,
        ROUND(SUM(oi.price), 2)                          AS gmv
    FROM orders o
    JOIN order_items oi ON o.order_id = oi.order_id
    WHERE o.order_status <> 'canceled'
    GROUP BY month
)
SELECT
    a.month,
    a.gmv,
    b.gmv                                       AS gmv_last_year,
    ROUND((a.gmv / b.gmv - 1) * 100, 2)         AS yoy_pct
FROM monthly a
JOIN monthly b
  ON a.month = DATE_FORMAT(
         DATE_ADD(STR_TO_DATE(CONCAT(b.month, '-01'), '%Y-%m-%d'),
                  INTERVAL 12 MONTH), '%Y-%m')
ORDER BY a.month;
