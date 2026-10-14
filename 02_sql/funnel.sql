-- ============================================================
-- 履约漏斗分析（教学版）
--
-- 【概念课】漏斗 = 用户一步步走流程，每步都流失一批人。
--   下单 → 支付 → 发货 → 送达 → 好评
-- 把每步剩余人数画出来上宽下窄，像漏斗。
-- 价值：定位"钱漏在哪一环"——哪步转化率最低，就该优先优化哪步。
--
-- 【技巧课】SUM(条件) 在 MySQL 里 = 满足条件的行数（真=1假=0）。
--   时间戳字段不为 NULL 就代表走到了那一步。
--   NULLIF(分母, 0) 防止除零报错——口径防御的小习惯。
--
-- 【严谨性】一个订单可能有多条评价，先按订单取最高分再统计，
--   避免 LEFT JOIN 造成扇出（正是第4层口径断言防的那类错误）。
-- ============================================================
SELECT
    COUNT(*)                                                     AS step1_placed,
    SUM(order_approved_at IS NOT NULL)                           AS step2_paid,
    SUM(order_delivered_carrier_date IS NOT NULL)                AS step3_shipped,
    SUM(order_delivered_customer_date IS NOT NULL)               AS step4_delivered,
    SUM(r.review_score >= 4)                                     AS step5_positive_review,
    ROUND(SUM(order_approved_at IS NOT NULL) / COUNT(*) * 100, 2)               AS paid_rate_pct,
    ROUND(SUM(order_delivered_carrier_date IS NOT NULL)
        / NULLIF(SUM(order_approved_at IS NOT NULL), 0) * 100, 2)              AS ship_rate_pct,
    ROUND(SUM(order_delivered_customer_date IS NOT NULL)
        / NULLIF(SUM(order_delivered_carrier_date IS NOT NULL), 0) * 100, 2)   AS deliver_rate_pct,
    ROUND(SUM(r.review_score >= 4)
        / NULLIF(SUM(order_delivered_customer_date IS NOT NULL), 0) * 100, 2)  AS positive_rate_pct
FROM orders o
LEFT JOIN (
    SELECT order_id, MAX(review_score) AS review_score
    FROM order_reviews
    GROUP BY order_id
) r ON o.order_id = r.order_id;
