# CTE 速成 —— 拿本项目自己的 SQL 讲

> 写这份文档的原因：项目基线 SQL 里有 5 道题用了 `WITH ... AS (...)`（Q5 / Q6 / Q7 / Q9 / Q10），
> 生成的 SQL 里也常有 4~6 道用。如果只会在面试里"照着念"，被追问一句就崩。
> 所以这里只讲**本项目里真实出现过的那几种形状**，不铺开讲语法大全。
>
> 环境：本机 MySQL **8.0.38**，CTE 支持完整（MySQL 5.7 及以前**不支持** CTE，这点要知道）。
>
> **如果你的焦虑是"我本身不会 CTE，但项目里用了，怎么解释" → 直接看 §1.5。**
> 那一节回答的是"补掉它，还是解释它"这个选择题，含三种答复话术与各自代价。

---

## 0. 先破除恐惧：这个形状你在项目里已经见过

你项目里的 **Q4** 是这么写的：

```sql
SELECT
  COUNT(*)                                   AS total_customers,
  SUM(order_count >= 2)                      AS repeat_customers,
  ROUND(SUM(order_count >= 2) / COUNT(*), 4) AS repurchase_rate
FROM (
  SELECT c.customer_unique_id, COUNT(*) AS order_count     -- ← 这一坨
  FROM orders o
  JOIN customers c ON o.customer_id = c.customer_id
  GROUP BY c.customer_unique_id
) t;
```

括号里那坨就是**派生表（derived table）**：一个临时结果集，被外层当成"表"来查。

**CTE 就是把这一坨搬到最前面、给它起个名字而已**。Q4 用 CTE 重写：

```sql
WITH order_counts AS (                       -- ← 名字叫 order_counts
  SELECT c.customer_unique_id, COUNT(*) AS order_count
  FROM orders o
  JOIN customers c ON o.customer_id = c.customer_id
  GROUP BY c.customer_unique_id
)
SELECT
  COUNT(*)                                   AS total_customers,
  SUM(order_count >= 2)                      AS repeat_customers,
  ROUND(SUM(order_count >= 2) / COUNT(*), 4) AS repurchase_rate
FROM order_counts;                           -- ← 像查表一样用它
```

**结果一模一样，一行数据都不差。** 所以很多时候问题不是"不会写 CTE"，
而是"不知道这个写法就叫 CTE" —— **但认出来只是第一步，能自己写出来才算会**
（验收标准见 `03_agent/RESUME_DEFENSE.md` 第〇节的自测）。

### 一句话定义

> **CTE（Common Table Expression，公共表表达式）= 给子查询起个名字，写在 SQL 最前面，
> 后面可以像表一样引用它，而且可以引用多次。**

别名：MySQL 文档叫 CTE，PostgreSQL 一样，Hive/Spark 叫 CTE，也有人叫它"命名子查询"。

---

## 0.5 先把"派生表"这个词搞清楚

上面 Q4 里 `FROM ( ... ) t` 那个东西，正式名字叫 **派生表（derived table）**。

### 0.5.1 先分清：派生表 ≠ 子查询（是子查询的一种）

**子查询是"大类"，派生表是"子类"。** 凡写在括号里、嵌在另一条 SQL 内部的 `SELECT`，都叫**子查询**；
但只有写在 **`FROM` 后面**的那一种，才叫**派生表**。

| 位置 | 名字 | 返回形状 | 本项目实际情况（实测统计） |
|---|---|---|---|
| `FROM ( ... ) t` | **派生表** derived table | 一张表（多行多列） | 基线 **2 处**（Q4、Q9）；模型生成的 SQL 里 2~3 处 |
| `WHERE x IN ( ... )` | WHERE 子查询 | 一列（多行） | **基线 0 处**；只在模型生成的 SQL 里出现过 2 处 |
| `SELECT ( ... )` | 标量子查询 | **只能 1 行 1 列**（多行会报 `1242`） | 基线 0 处，项目里没用 |
| `WITH x AS ( ... )` | CTE（命名子查询） | 一张表，但要**先声明** | 基线 5 处（Q5/Q6/Q7/Q9/Q10） |

**一句话判据 = 出现在哪里（位置）＋ 返回什么形状，两者缺一不可：**

- 位置在 `FROM` → **派生表**
- 位置在 `WHERE` / `SELECT` → **不叫派生表**，就叫"WHERE 子查询"或"标量子查询"

> 复现命令（本项目实测）：
> ```bash
> grep -Ei "FROM\s*\(\s*SELECT" 02_sql/sql_answers.sql        # 基线派生表 2 处
> grep -Ei "(IN|=)\s*\(\s*SELECT" 02_sql/sql_answers.sql      # 基线 WHERE 子查询 0 处
> ```

### 0.5.2 那 CTE 算不算子查询？（面试爱抠的字眼）

**标准里 CTE 和子查询是并列的两个概念** —— CTE 有名字、写在最前面、可以引用多次，
这些都不是普通子查询的性质。所以严格说：**CTE 不是"派生表那类子查询"，它是另一个东西。**

但在 **MySQL 内部执行计划**里它俩物化成同一个东西（都是 `<derived2>`），
所以工程上讨论"派生表和 CTE 的关系"时可以说**等价** ——
**这两个结论不矛盾，注意别混在一句话里讲。**

安全答法："**派生表是子查询的一种；CTE 严格说是并列概念，但在 MySQL 里和派生表物化成同一个东西。**"

### 0.5.3 面试高概率追问：相关子查询

| | 非相关子查询 | 相关子查询（correlated） |
|---|---|---|
| 特征 | 子查询**能独立跑** | 子查询**引用了外层的列** |
| 例子 | `WHERE id IN (SELECT id FROM t2)` | `WHERE EXISTS (SELECT 1 FROM t2 WHERE t2.k = t1.k)` |
| 执行方式 | 先算一次子查询，再拿结果去比 | **外层每来一行就得跑一次** |
| 性能 | 好 | 差，是常见的慢查询来源 |

**为什么本项目没有它**（这本身是个能答的点）：10 条问题都能用"先聚合再 JOIN"直接表达
（比如 Q5 先把 `order_payments` 按 `order_id` 压成一行，再 JOIN 回订单），
不需要"逐行去探测另一张表"，所以没用到相关子查询 —— **不是不会，是没必要**。

### 定义

> **派生表 = 写在 `FROM` 后面的子查询。它从别的表"派生"出一个临时结果集，
> 外层查询把它当成一张表来查，所以必须给它起个别名。**

"派生"是"衍生/推算出来"的意思 —— 它不是真实存在的表，是查询过程中算出来的。

### 硬规则：不给别名，MySQL 直接报错

这条规则很多人不知道，但很值得记住。试一下：

```sql
SELECT COUNT(*) FROM (SELECT order_id FROM orders LIMIT 5);
```

MySQL 会回你：

```
ERROR 1248 (42000): Every derived table must have its own alias
```

（"每个派生表都必须有自己的别名"）

加上别名就好了：

```sql
SELECT COUNT(*) AS n FROM (SELECT order_id FROM orders LIMIT 5) AS t;   -- ✅
```

**为什么必须起名？** 因为外层 `SELECT` 要靠这个名字来引用子查询里的列
（比如 `t.order_id`），也避免和外层其他表同名冲突。

### 你项目里的派生表

基线 10 题里有 2 处：

| 题 | 位置 | 它在这里解决什么 |
|---|---|---|
| **Q4** | `FROM ( SELECT c.customer_unique_id, COUNT(*) AS order_count ... ) t` | 先把"每个客户下几单"算出来，外层才能统计"下过 ≥2 单的人占多少" —— **两段聚合** |
| **Q9** | `FROM ( SELECT month, sales, LAG(sales) OVER (...) AS prev_sales FROM monthly ) t` | `LAG()` 是窗口函数，必须在月度聚合**之后**才能用 —— **又是两段** |

（另外 9 处出现在模型生成的 SQL 里 —— 说明模型也常用派生表写法。）

### CTE 和派生表：同一个东西，两种写法

**这是最值得记住的一点：它们在 MySQL 内部是同一个东西。**

用 `EXPLAIN` 看一条 CTE 查询，MySQL 显示的执行计划是：

```
WITH x AS (SELECT order_id FROM orders LIMIT 5)
SELECT COUNT(*) FROM x
```

```
select_type = PRIMARY    table = <derived2>     ← CTE 变成了"派生表"
select_type = DERIVED    table = orders
```

**CTE 被 MySQL 翻译成了派生表**（`table=<derived2>` 就是这个意思）。
所以从执行层面讲，**"CTE" 和 "派生表" 是同一个概念的两种书写形式**：

| | 派生表 | CTE |
|---|---|---|
| 名字写在哪 | 跟在 `FROM ( ... )` **后面** | 写在 SQL **最前面**（`WITH`） |
| 顺序 | 先写主查询，中间插一坨子查询 | 先声明所有中间结果，再写主查询 |
| 必须起名 | **是**（否则 ERROR 1248） | **是** |
| 能否被引用多次 | 不行，要引用几次就写几遍 | **可以**，写名字就行 |
| 可读性 | 嵌套深了要配对括号 | 从上往下读 |
| 名字在 MySQL 内部 | `<derived2>` | `<derived2>`（**同一个东西**） |
| MySQL 版本 | 一直都有 | **8.0 才有** |

### 那到底该用哪个？

简单判断：

| 情况 | 用哪个 |
|---|---|
| 只有一层中间结果，且只引用一次 | **派生表**就够（少写一个 `WITH`，更紧凑） |
| 中间结果要**引用两次以上** | **CTE**（派生表得抄两遍） |
| 有**两层以上**嵌套 | **CTE**（派生表括号会套到看不清） |
| 想**单独跑中间结果**来调试 | **CTE**（`WITH x AS (...) SELECT * FROM x;` 直接看中间数据） |
| 目标环境是 MySQL 5.7 | **只能派生表**（5.7 不支持 CTE） |

> 一句话记法：**派生表是"匿名子查询"，CTE 是"提前命名的子查询"。名字放前面就是 CTE，放后面就是派生表。**

---

## 1. 本项目里 CTE 的三种形状（就这三种，没有别的）

### 形状一：先预聚合，再 JOIN —— Q5（防 JOIN 扇出）

```sql
WITH per_order AS (                    -- 第 1 段：订单粒度的明细
  SELECT o.order_id, c.customer_state,
         TIMESTAMPDIFF(DAY, o.order_purchase_timestamp,
                       o.order_delivered_customer_date) AS delivery_days
  FROM orders o JOIN customers c ON o.customer_id = c.customer_id
),
order_gmv AS (                         -- 第 2 段：把支付的多个分期压成一个订单一个金额
  SELECT order_id, SUM(payment_value) AS gmv
  FROM order_payments
  GROUP BY order_id
)
SELECT po.customer_state AS state, COUNT(*) AS orders,
       ROUND(SUM(g.gmv), 2) AS gmv,
       ROUND(AVG(po.delivery_days), 1) AS avg_delivery_days    -- ← AVG 不吃扇出
FROM per_order po
JOIN order_gmv g ON po.order_id = g.order_id
GROUP BY po.customer_state
ORDER BY orders DESC;
```

**为什么要写 CTE？** 因为 `order_payments` 一个订单有多行（分期付款）。
如果直接把 `orders JOIN customers JOIN order_payments` 再 `GROUP BY state`，
每个订单会按支付行数翻倍，`COUNT(*)` 和 `AVG(配送天数)` 全部被加权算错 —— 这就是
口径登记表里的 **C21「禁止扇出」**。

**这一段是面试必讲的**：CTE 在这里不是"为了好看"，是**口径正确性的前提**。

---

### 形状二：先取 TopN，再展开算 —— Q7（两段聚合）

```sql
WITH top5 AS (                          -- 第 1 段：先定出哪 5 个卖家
  SELECT seller_id
  FROM order_items
  GROUP BY seller_id
  ORDER BY SUM(price) DESC
  LIMIT 5
)
SELECT oi.seller_id AS seller_id,
       DATE_FORMAT(o.order_purchase_timestamp, '%Y-%m') AS month,
       ROUND(SUM(oi.price), 2) AS monthly_sales
FROM order_items oi
JOIN top5 t    ON oi.seller_id = t.seller_id
JOIN orders o  ON oi.order_id = o.order_id
GROUP BY oi.seller_id, month            -- 第 2 段聚合
ORDER BY oi.seller_id, month;
```

**为什么不写成一句？** 因为这里有**两个聚合层级**：
先按卖家汇总算出总销售额排名（取前 5），再按"卖家 × 月份"重新汇总。
SQL 不允许在同一个 `GROUP BY` 里同时按两个粒度聚合 —— 必须分层，CTE 就是分层的手段。

> 顺带一个面试考点：这个查询带 `LIMIT 5`，结果**不是全集的切片**。
> 所以口径断言里的守恒式（各组之和 = 平台总量）会主动跳过它 —— 这就是 **C23 作用域闸门**。

---

### 形状三：CTE 引用 CTE（链式加工）—— Q10

```sql
WITH spend AS (                         -- 第 1 层：每个客户总共花了多少、下了几单
  SELECT c.customer_unique_id,
         SUM(p.payment_value)         AS total_spend,
         COUNT(DISTINCT o.order_id)   AS orders
  FROM orders o
  JOIN customers c      ON o.customer_id = c.customer_id
  JOIN order_payments p ON o.order_id = p.order_id
  GROUP BY c.customer_unique_id
),
ranked AS (                             -- 第 2 层：拿上一层的结果打五分位标签
  SELECT *, NTILE(5) OVER (ORDER BY total_spend DESC) AS quintile
  FROM spend                            -- ← CTE 引用前面的 CTE
)
SELECT quintile, COUNT(*) AS customers,               -- 第 3 层：按档汇总
       ROUND(AVG(total_spend), 2) AS avg_spend,
       ROUND(AVG(orders), 2)      AS avg_orders
FROM ranked
GROUP BY quintile
ORDER BY quintile;
```

**为什么要分两层？** 窗口函数 `NTILE()` 是在 `GROUP BY` **之后**才生效的。
必须先有"每人一行"的结果集，才能对它排名分档 —— 不能在同一个查询块里
既 `GROUP BY customer_unique_id` 又对聚合结果跑窗口函数（要嵌套）。

---

## 1.5 我不会 CTE，可项目里就有 CTE —— 补掉，还是解释掉？

先把责任说清楚：**基线 SQL 不是照着"你现在会什么"写的，是写的时候选了 CTE 这种写法。**
所以这个暴露面是先天的，不是你造成的。现在真正要做的是一道选择题。

### 第一步：把暴露面数准（已实测）

| 题 | CTE 个数 | 在这里解决什么 | 行数 |
|---|---:|---|---:|
| **Q5** | 2 | 预聚合再 JOIN —— 防 `order_payments` 扇出 | 24 |
| **Q6** | 2 | 产品榜 + 卖家榜两条独立榜 | 32 |
| **Q7** | 1 | 先取 TopN，再展开算 | 16 |
| **Q9** | 1 | 预聚合后套 `LAG()` | 20 |
| **Q10** | 2 | CTE 引用 CTE（链式分层） | 22 |
| **Q1 / Q2 / Q3 / Q4 / Q8** | **0** | **完全不用 CTE** | 47 |

**结论：10 题里 5 题压根不用 CTE；用了的那 5 题只有 3 种形状、合计 8 个 CTE 定义。**
不是"满地都是 CTE"，是"**3 个形状，每个 8 行左右**"。

### 第二步：分清你是"不会读"还是"不会写"（代价差 10 倍）

这两个是完全不同的问题，别混在一起焦虑：

| | 具体表现 | 什么时候暴露 | 概率 |
|---|---|---|---|
| **不会读** | 面试官指着 Q5 问"这里为什么分两层"，答不上来 | **任何追问都会崩** | **高（>50%）** |
| **不会写** | 能讲清为什么，但闭卷默写写不出来 | 只有"你现场写一段"才暴露 | **低（约 20%）** |

**怎么判断自己是哪种**：Q4 用的是派生表（`FROM (SELECT ...) t`）。
**如果你能读懂 Q4，那你就已经能读 CTE** —— 因为 MySQL 内部它俩物化成同一个 `<derived2>`
（§0.5.2 有 `EXPLAIN` 证据）。
**所以大概率你只是"不会闭卷手写"，而不是"看不懂"。**

### 第三步：三条路，选一条

| 方案 | 被问到时怎么答 | 成本 | 风险 |
|---|---|---|---|
| **A. 补会**（推荐） | 不用答 —— 已经不存在这个问题 | 3~4 小时（§5 的 3 道练习） | 无 |
| **B. 主动披露 + 划清边界** | 见下方话术 | 0 | 低，但纯语法题仍会失分 |
| **C. 编个理由**（如"我们团队规范要求用 CTE"） | ❌ 不要 | 0 | **高 —— 一问"哪个团队"就崩** |

**B 方案的话术（如果今天就要面试）：**

> "这个项目的 SQL 是我和 AI 结对写的，CTE 的写法是它给的。
> 我能读懂、也能解释每一处**为什么**要这么写 —— 比如 Q5 分两层，是因为
> `order_payments` 一个订单有多行，直接 JOIN 会把订单数放大；
> Q10 分两层，是因为 `NTILE()` 必须在'每人一行'的结果上才能开窗。
> 但闭卷手写 CTE 我还不熟，这几天正在按项目里的 3 种形状补。"

**B 能不能守住，取决于你能不能说出那个"为什么"。** 好消息：那个"为什么"是**口径层**的，
一句 CTE 术语都不含 —— 就是 §1 里那三种形状，用业务语言讲清就够。

**C 为什么是死路**：编一个不存在的团队规范，等于把"能力缺口"升级成"履历不实"。
前者可以解释，后者一票否决。

### 不建议的做法：把基线里的 CTE 全改回派生表

技术上可行，但**没意义**：

1. 模型生成的 SQL 里本来就有 CTE（4~6 道），改不完；
2. 为迁就"不会"而放弃更好的写法是本末倒置 —— 嵌套两层以上时派生表括号会套到看不清；
3. 面试官反而会问"为什么不用 CTE"，**你就多了一个要解释的问题**。

**正解不是隐藏，是补上 —— 而且比你想象的便宜：3 个形状、各 8 行、3~4 小时。**

### 最低验收（闭卷，不看文档）

- [ ] 默写出 Q5 的 `WITH per_order AS (...), order_gmv AS (...) SELECT ...`
- [ ] 说清 `WITH x AS (...)` 与 `FROM (...) x` 的三点区别（名字写在哪 / 能否引用多次 / 嵌套可读性）
- [ ] 把 Q4 的派生表改写成 CTE，用 `02_sql/sql_answers.py` 跑出**完全相同**的结果
- [ ] 说清 CTE 的收益是**可读性与可验证性，不是性能**（§3 坑 2 有 `EXPLAIN` 证据）

#### 附：Q4 两种写法已实测跑过（结果逐值相同）

在 `olist_ecommerce` 上真跑了一遍，两版输出完全一致：

| 写法 | total_customers | repeat_customers | repurchase_rate |
|---|---:|---:|---:|
| 派生表 `FROM (...) t` | 96,096 | 2,997 | 0.0312 |
| CTE `WITH order_counts AS (...)` | 96,096 | 2,997 | 0.0312 |

同一份 `EXPLAIN` 也把"CTE 就是派生表"这件事钉死了（这是**项目真实查询**的计划，不是玩具例子）：

```
EXPLAIN WITH order_counts AS (...) SELECT ... FROM order_counts;
  select_type = PRIMARY    table = <derived2>    rows = 100,960
  select_type = DERIVED    table = c             rows = 96,187
  select_type = DERIVED    table = o             rows = 1
```

**`table = <derived2>` 就是 MySQL 给那个 CTE 起的内部名字** —— 它压根没把 CTE 当成新概念。
**面试讲到这里就很有说服力：不是"我觉得它俩等价"，是执行计划里就这么写的。**

---

## 2. 语法：只需要记这 3 条

```sql
WITH 名字1 AS ( 查询1 ),        -- ① 只有第一个 CTE 前面写 WITH，后面用逗号
     名字2 AS ( 查询2 ),        -- ② 最后一个 CTE 后面**不要**逗号
     名字3 AS ( 查询3 )
SELECT ... FROM 名字1 JOIN 名字3 ...   -- ③ CTE 直接当表名用
```

对照记忆：

| 你要做的事 | 写法 |
|---|---|
| 定义一个 CTE | `WITH 名字 AS ( SELECT ... )` |
| 定义第二个 | 前面的 `)` 后加逗号 `, 名字2 AS (...)` |
| 主查询 | 最后一个 `)` 之后直接跟 `SELECT`（**没有逗号**） |
| 引用 | 和表名一样用：`FROM 名字`、`JOIN 名字 ON ...` |
| 一个 CTE 用多次 | 直接写两次名字即可（子查询得抄两遍） |

**作用域**：CTE 只在**这一条 SQL 语句**内有效。语句执行完就没了 —— 它不是视图，也不落盘。

> 小知识：`WITH ... SELECT` 前面还能再套 `INSERT` / `UPDATE` / `DELETE`，例如
> `INSERT INTO t WITH x AS (...) SELECT * FROM x;`。本项目只读，用不到，但面试可能问。

---

## 3. 三个必须知道的坑（面试加分项）

### 坑 1：MySQL 5.7 及以前不支持 CTE

CTE 是 **MySQL 8.0** 才有的语法（PostgreSQL 8.4+、SQL Server 2005+、Oracle 11g+ 也都支持）。
**MySQL 5.7 上写 `WITH` 直接语法报错。** 老版本只能用派生表：

```sql
-- MySQL 5.7 写法（等价的派生表版本）
SELECT ... FROM ( SELECT ... ) AS spend ...;
```

本机是 8.0.38，所以没问题。但面试官如果问"你在 MySQL 5.7 上会怎么写"，
答案就是"退回派生表，逻辑不变"。

### 坑 2：CTE ≠ 缓存，被引用多次可能被物化

很多人以为"CTE 只算一次、结果复用，所以比子查询快"。**不一定。**

MySQL 8.0 对 CTE 有两种处理策略：

| 策略 | 什么时候用 | 含义 |
|---|---|---|
| **Merge（合并）** | CTE 简单、被引用一次 | 直接把 CTE 的定义揉进外层，等价于子查询，**没有额外开销** |
| **Materialize（物化）** | CTE 被引用 ≥2 次，或含 `LIMIT`、聚合、窗口函数等 | 先把结果存进临时表，再反复读 |

- 被引用**一次**的 CTE：大致等于子查询，不会更慢，主要是赢在可读性。
- 被引用**两次以上**的 CTE：MySQL 倾向于物化 → 可能生成临时表，
  大表上有真实成本（`EXPLAIN` 的 `select_type` 会显示 `MATERIALIZED`）。
- 想强制控制，MySQL 支持 `/*+ MERGE() */` / `/*+ NO_MERGE() */` 这类 optimizer hint。

**面试怎么答**："CTE 主要是**可读性和可维护性**的收益；性能上不能假定它被缓存，
被引用多次时 MySQL 8 会物化成临时表，这种情况我会先看 `EXPLAIN` 确认，必要时改成临时表或调整写法。"

### 坑 3：递归 CTE 要写 `WITH RECURSIVE`

普通 CTE 不需要 `RECURSIVE`，但如果 CTE **自己引用自己**（组织架构树、路径展开这类），
必须显式加：

```sql
WITH RECURSIVE org AS (
  SELECT id, name, 1 AS lvl FROM employees WHERE manager_id IS NULL   -- 锚点（起点）
  UNION ALL
  SELECT e.id, e.name, o.lvl + 1
  FROM employees e JOIN org o ON e.manager_id = o.id                  -- 递归引用自己
)
SELECT * FROM org;
```

**本项目没有层级结构数据，所以没用递归 CTE** —— 但这是个高频面试题，知道就行。

### 附带一个小坑：CTE 里的 `ORDER BY`

Q6 和 Q7 在 CTE 里写了 `ORDER BY ... LIMIT 10/5`。这是**合法的**，因为
`ORDER BY` 配合 `LIMIT` 时"取哪几行"有确定含义（取 TopN）。

但如果 CTE 里**只有 `ORDER BY` 没有 `LIMIT`**，行的顺序是不保证被保留的 ——
外层查询可能拿到的顺序和你想的不一样。**排序要么放在主查询，要么配 `LIMIT` 用。**

---

## 4. 面试话术（可以直接背）

### Q：你为什么用 CTE，不直接用子查询？

> "分两种情况。**单层**的过滤我直接用子查询，比如 Q4 算复购率。
> 但有几道题**必须在 SQL 里表达两个聚合层级** ——
> 比如 Q5，口径要求先按订单粒度算配送天数和订单金额、再按州聚合，
> 因为 `order_payments` 一个订单有多行，直接 JOIN 会让订单数翻倍、`AVG` 被加权算错（我们口径表里的 C21）；
> 再比如 Q7，要先算出哪 5 个卖家，再按卖家 × 月份重新聚合。
>
> 这种两段计算用嵌套子查询写，括号会套到三层，读的人得在心里配对括号。
> 写成 CTE 就是从上往下一段一段读，**而且中间结果可以单独跑出来验证** ——
> 我在做口径治理时，就是靠把 `per_order` 这个 CTE 单独跑一遍，
> 才定位到各州订单数之和比平台总数多 1 单的问题。
> 所以对我来说 CTE 的价值主要是**让口径可验证**，不只是好看。"

（这段话把 CTE、JOIN 扇出、口径治理三件事串起来了，是加分答法。）

### Q：CTE 和视图、临时表、子查询有什么区别？

| | 生命周期 | 能否多次引用 | 是否落盘 | 主要用途 |
|---|---|---|---|---|
| **子查询** | 单条语句内 | 要引用几次就抄几遍 | 否 | 一次性的中间过滤 |
| **CTE（`WITH`）** | 单条语句内 | 可以，写名字就行 | MySQL 可能物化成临时表 | 把一条复杂 SQL 拆成可读的多段 |
| **视图（`VIEW`）** | 永久存定义 | 跨语句 | 只存定义，不存数据 | 多人复用的稳定口径 |
| **临时表（`CREATE TEMPORARY TABLE`）** | 会话内 | 跨语句 | 落盘/内存，要显式建和删 | 跨多条 SQL 的中间结果 |

一句话记法：**子查询是匿名的、CTE 是命名的；视图是永久的、CTE 是临时的。**

### Q：CTE 会不会影响性能？

> "不能一概而论。MySQL 8 里，引用一次的简单 CTE 会被 merge 进外层，基本等价于子查询；
> 引用多次或者带 `LIMIT` / 窗口函数的，倾向物化成临时表，大表上有真实成本。
> 我的做法是先 `EXPLAIN` 确认有没有 `MATERIALIZED`，再决定要不要改写。
> 这个项目数据量只有 10 万行级，CTE 的可读性收益远大于性能成本 ——
> 但如果换成亿级表，我会重新评估。"

---

## 4.5 追问树：面试官会怎么一层层往下追

CTE 这个点，面试官不会只问一句。下面是他**最可能走的 6 层递进** ——
每层标了「答什么」和「万一答不上来怎么收」。

> **核心判断：第 1~5 层全是"口径与设计"语言，不要求你会写；只有第 6 层要求手写。
> 而第 6 层恰恰是所有层里最容易补的（因为 CTE 的语法只有 3 个记号，见 §4.6）。**

| 层 | 面试官问 | 标准答案的核心（一句话） | 答不上来的兜底 |
|---|---|---|---|
| **1** | "你这项目里哪儿用了 CTE？" | 10 题里 **5 题**用（Q5/Q6/Q7/Q9/Q10），只有 **3 种形状**、共 8 个定义 —— 全是"口径要求分两步算"的地方 | "集中在 5 道需要两段聚合的题上，Q1/Q2/Q3/Q4/Q8 都没用。" |
| **2** | "为什么要分两段？" | `order_payments` 对同一订单是**多行**，直接 JOIN 会把订单数和金额**扇出放大**（口径表 **C21**），所以先按 `order_id` 压成一行，再往上聚合 | ⚠️ 这层答不上来 = **口径层失守，必须会**（见 §1 形状一） |
| **3** | "那用子查询 / 派生表不行吗？" | 行，逻辑等价。但三个具体代价：① 要引用两次得**抄两遍**；② 嵌套两层括号就要**配对**；③ **中间结果不能单独跑出来验证** —— 我就是靠单独跑 `per_order`，才定位到"各州订单数之和比平台总数多 1 单" | "可以用派生表，我也写过（Q4/Q9 就是）。这里选 CTE 主要是为了**能单独验证中间结果**。" |
| **4** | "CTE 和派生表什么关系？" | 同一个东西两种写法；MySQL 内部把 CTE 物化成派生表（`EXPLAIN` 里 `table=<derived2>`） | §0.5.2 有可背的安全答法 |
| **5** | "CTE 有性能问题吗？" | 引用一次的简单 CTE 会被 **merge** 进外层，基本等价子查询；引用多次或带 `LIMIT`/窗口函数的倾向**物化成临时表**，大表上有真实成本 | "我会先 `EXPLAIN` 看有没有物化再决定；这个项目 10 万行级，可读性收益大于成本。" |
| **6** | **"你现场写一段 CTE 看看。"** | ← **唯一的真风险**，见 §4.6 | 见 §4.6 的兜底话术 |

**注意第 3 层的排序**：最容易打动面试官的是"中间结果能单独跑出来验证"这一条，
因为它把 CTE 从"语法糖"变成了**口径治理的工具** —— 而且你有真实故事（`99,441 vs 99,440`）。

---

## 4.6 被要求当场手写：三步机械改写 + 8 行骨架

### 先建立一个正确认知：写 CTE 不需要学新语法

CTE 不是"另一套写法"，它是**把你已经会写的子查询整段搬走、起个名字**。
所以现场手写的本质不是"创作"，而是**搬运 + 包壳**。

**整个 CTE 的语法只有 3 个记号：**

```
WITH   名字  AS  (
 ↑      ↑         ↑
关键字  你起的    固定的两个符号
       别名
```

其余 90% 全是你早就会写的 `SELECT ... FROM ... JOIN ... GROUP BY ... WHERE ...`。

### 三步机械改写（照这个顺序做，不会卡）

| 步 | 动作 |
|---|---|
| **1. 先写你会的** | 把两段 `SELECT` 各自独立写出来（**不带 CTE**，就是两条普通查询）。做完这步，任务已完成 90% |
| **2. 包壳** | 最前面加 `WITH 别名1 AS (`，把第一段粘进去；两个 CTE 之间写 `),`；最后一段后面写 `)` |
| **3. 换引用** | 主查询里原来的子查询位置，换成 `别名1` / `别名2` |

### 8 行骨架（记结构，不记内容）

```sql
WITH per_order AS (                       -- ① 关键字 + 别名 + 开括号
  SELECT order_id, customer_state,        -- ② 你原本就会写的那段 SELECT，原样搬进来
         TIMESTAMPDIFF(DAY, ...) AS delivery_days
  FROM orders o JOIN customers c ON ...
),                                        -- ③ 逗号在"括号外面"，只加在两个 CTE 之间
order_gmv AS (                            -- ④ 第二个 CTE（只有一个就删掉这 3 行）
  SELECT order_id, SUM(payment_value) AS gmv
  FROM order_payments GROUP BY order_id
)                                         -- ⑤ 最后一个 CTE 后面**不加逗号**
SELECT                                    -- ⑥ 主查询正常写，只是 FROM 换成别名
  po.customer_state, COUNT(*)
FROM per_order po JOIN order_gmv g ON po.order_id = g.order_id
GROUP BY po.customer_state;
```

**现场只检查这三个标点，就不会崩：**

1. **`WITH` 只写一次** —— 后面每个 CTE 直接写 `别名 AS (`。
2. **`),` 的逗号在括号外面**，且**只在 CTE 之间**。
3. **最后一个 CTE 后的 `)` 后面不写逗号**，直接接主查询。

### 不同熟练度的现场应对

| 你能做到 | 现场怎么表现 |
|---|---|
| **能默写** | 直接写，**边写边讲解**："这里先按订单粒度压成一行，是为了防 `order_payments` 扇出" —— **讲解比代码本身值分** |
| **记得骨架、忘了细节** | 先把两段普通 `SELECT` 写出来，再说"把上面这段提到前面命名就是 CTE"，然后照骨架包壳 |
| **完全写不出** | 用下面的兜底话术 |

**兜底话术（把"不会写"降级成"不熟这个写法"）：**

> "闭卷手写 CTE 我还没练熟，但我可以口述结构，也能写出等价的派生表写法。
> 外层先按订单粒度聚合出 `per_order` —— 这一步是为了防 `order_payments` 的扇出；
> 再按州聚合。CTE 只是把第一段提到前面起了个名字，用派生表写就是这样："
> （然后把两段 `SELECT` 写出来，就是练习 2 那种形式）

**为什么这条兜底能救命**：它把问题从"**你不会 CTE**"降级成"**你不熟这一种语法糖**" ——
同一件事的派生表写法你能写出来，面试官看到的是"**这题他会算，只是不熟 CTE 这个写法**"。
这跟"算不出来"是完全不同的评价。

> 兜底能不能说出口，取决于你是不是真能写出派生表版 —— **这就是 §5 练习 2 存在的唯一目的。**

---

## 5. 动手练习（做完这 3 题就稳了）

> **三道题的答案都在下面，而且都已经在真实库上跑通。**
> 方法是三遍：**照着抄一遍 → 关掉答案默写 → 试着变形**。只读不写等于没练。

### 练习 1：把 Q4 改成 CTE

**答案**：见 §0（派生表版与 CTE 版并列写在那里）。

**达标判据**：两版跑出来数字一个都不变 —— 已实测：都是 `96,096 / 2,997 / 0.0312`（见 §1.5 附录）。

### 练习 2：把 Q6 的两段改成不带 CTE 的写法

**这题的目的不是"学会"，而是让你能说出第 3 层追问的兜底话术**（§4.6）。

**答案（实测跑通，20 行，与 CTE 版一致）：**

```sql
SELECT * FROM (                            -- ← 派生表版：把 CTE 整段塞进 FROM
  SELECT 'product' AS entity_type, oi.product_id AS entity_id,
         ROUND(AVG(r.review_score), 2) AS avg_score, COUNT(*) AS review_count
  FROM order_items oi
  JOIN order_reviews r ON oi.order_id = r.order_id
  GROUP BY oi.product_id
  HAVING COUNT(*) >= 20
  ORDER BY avg_score DESC, review_count DESC
  LIMIT 10
) product_scores
UNION ALL
SELECT * FROM (                            -- ← 第二个榜单又要抄一遍
  SELECT 'seller' AS entity_type, oi.seller_id AS entity_id,
         ROUND(AVG(r.review_score), 2) AS avg_score, COUNT(*) AS review_count
  FROM order_items oi
  JOIN order_reviews r ON oi.order_id = r.order_id
  GROUP BY oi.seller_id
  HAVING COUNT(*) >= 20
  ORDER BY avg_score DESC, review_count DESC
  LIMIT 10
) seller_scores
ORDER BY entity_type, avg_score DESC, review_count DESC;
```

**实测结果**：20 行（产品榜 10 + 卖家榜 10），榜首产品 `4.96`（24 条评价）、
榜尾卖家 `4.78`（27 条评价）—— **与 CTE 版逐值一致**。

**改完你应该能说出"可读性差在哪"（这就是答案）**：

1. 两个大括号**并排**，看不出它们是"同一件事的两个副本"，得逐字对比才发现只差 `product_id / seller_id`；
2. 想改一处逻辑（比如把 `HAVING 20` 改成 `30`）**要改两遍**，改漏一处就一边对一边错；
3. 外层那个 `SELECT *` 是"被迫"的 —— 因为列名在里层定义，外层没法显式指定字段。

> **能自己讲出这 3 条，第 3 层追问（"用子查询不行吗"）就稳了** —— 因为你不是凭感觉说 CTE 好，
> 而是能举出具体代价。

### 练习 3（进阶）：给 Q5 加一个"各州退款率"

**答案（实测跑通，27 个州，且 C19 守恒未破）：**

```sql
WITH per_order AS (
  SELECT
    o.order_id,
    c.customer_state,
    o.order_status,                                        -- ← 新增这一列
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
  po.customer_state                                        AS state,
  COUNT(*)                                                 AS orders,
  SUM(po.order_status = 'canceled')                        AS canceled_orders,   -- ← 布尔求和，不是 COUNT
  ROUND(SUM(po.order_status = 'canceled') / COUNT(*), 4)   AS cancel_rate,
  ROUND(SUM(g.gmv), 2)                                     AS gmv,
  ROUND(AVG(po.delivery_days), 1)                          AS avg_delivery_days
FROM per_order po
JOIN order_gmv g ON po.order_id = g.order_id
GROUP BY po.customer_state
ORDER BY orders DESC;
```

**实测结果**（可以直接拿去对照）：

| state | orders | canceled_orders | cancel_rate | gmv | avg_delivery_days |
|---|---:|---:|---:|---:|---:|
| SP | 41,745 | 327 | 0.0078 | 5,998,226.96 | 8.3 |
| RJ | 12,852 | 86 | 0.0067 | — | — |
| MG | 11,635 | 64 | 0.0055 | — | — |
| RS | 5,466 | 25 | 0.0046 | — | — |

**关键验证点**：加了新列之后，**各州订单数之和仍然 = 99,440**（C19 守恒量没被破坏）。
说明这次改动**只增加了输出列，没有改变任何过滤或粒度** —— 这正是 §3 讲的"改完要回归验证"。

> **口径提醒（面试可讲的一个坑）**：这里的"退款率"分母是**有支付记录的订单**
> （因为 `order_gmv` 是内连接，只保留有支付的订单），所以它严格说是
> "**已付款订单里的取消率**"，不是"所有下单里的取消率"。
> 能主动指出这一点，说明你知道口径会影响结论 —— 这是加分项，不是减分项。

### 改完怎么验证

```bash
# 1) 重新生成基线 + 看是否仍跑得通
python 02_sql/sql_answers.py

# 2) 确认口径五处仍然一致（基线 SQL / prompt / few-shot / 评估指标 / 第 4 层断言）
python 03_agent/caliber_check.py

# 3) 全套回归测试（67 项）
python -m unittest discover -s 03_agent/tests -t 03_agent/tests
```

> ⚠️ 注意：练习 3 改的是**基线 SQL**。如果真要合进项目，按 §口径五步走流程
> （登记表 → 基线 → 重跑 → prompt/few-shot/CORE_COLS → 重跑评估）。
> 只是练手的话，**改完记得还原**。

### 自评表（勾完这三行，CTE 就不再是你的风险项）

- [ ] 练习 1：能**闭卷**把 Q4 写成 CTE，数字不变
- [ ] 练习 2：能**闭卷**写出派生表版 Q6，并说出可读性差的 3 个具体原因
- [ ] 练习 3：能在 Q5 上加一段新逻辑，并**主动想到要回归验证守恒量**
- [ ] 口头：能按 §4.5 的追问树，从第 1 层一路答到第 4 层不卡壳

---

## 6. 一页速查

```sql
-- 单个 CTE
WITH x AS ( SELECT ... )
SELECT * FROM x;

-- 多个 CTE（逗号分隔，只有第一个写 WITH）
WITH x AS ( SELECT ... ),
     y AS ( SELECT ... FROM x )        -- 可以引用前面的 CTE
SELECT * FROM x JOIN y ON ...;

-- 等价关系
WITH x AS (Q) SELECT ... FROM x        ≡   SELECT ... FROM (Q) AS x
--    ↑ 名字写前面 = CTE（MySQL 8+）        ↑ 名字写后面 = 派生表（一直都有）
--  派生表**必须**有别名，否则 ERROR 1248: Every derived table must have its own alias

-- CTE 被引用多次时可以反复用名字；派生表要引用几次就抄几遍
WITH RECURSIVE r AS (锚点 UNION ALL 递归) SELECT * FROM r;   -- 自引用必须加 RECURSIVE

-- 检查执行计划：CTE 在 MySQL 内部也会变成派生表
EXPLAIN WITH x AS (...) SELECT ... ;   -- table 列会显示 <derived2>
```

**本项目 CTE 索引**

| 题 | CTE 名字 | 形状 | 为什么必须分层 |
|---|---|---|---|
| Q5 | `per_order` + `order_gmv` | 预聚合再 JOIN | 防 `order_payments` JOIN 扇出（C21） |
| Q6 | `product_scores` + `seller_scores` | 两个独立榜单 | 产品榜与卖家榜各自 Top10，再 `UNION ALL` |
| Q7 | `top5` | 先 TopN 再展开 | 两个聚合层级（卖家总量排名 → 卖家×月份） |
| Q9 | `monthly` | 预聚合后套窗口函数 | `LAG()` 要在月度聚合之后才能用 |
| Q10 | `spend` → `ranked` | 链式（CTE 引用 CTE） | `NTILE()` 要等"每人一行"的结果出来 |

---

*文档位置：`02_sql/CTE_GUIDE.md`。配套的面试话术总表见 `03_agent/INTERVIEW_NOTES.md`。*
