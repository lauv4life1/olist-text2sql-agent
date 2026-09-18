"""Olist Text2SQL 项目 —— 10 个业务问题定义（由易到难）。

这是整个项目的"题面基准"：
- Phase 2 手写 SQL 基线（02_sql）以此为准，产出 ground truth；
- Phase 3 Text2SQL Agent（03_agent）用同样的 10 个自然语言问法测准确率。

字段说明：
    id       题目编号（1-10）
    title    简短标题
    question 面向用户的自然语言问法（Agent 的输入）
    skill    本题考查的核心 SQL 技能
"""

QUESTIONS = [
    {
        "id": 1,
        "title": "总订单数 / 总成交额 / 客单价",
        "question": "平台一共成交了多少订单？总成交额是多少？平均每单多少钱？",
        "skill": "COUNT(DISTINCT) / SUM / 除法",
    },
    {
        "id": 2,
        "title": "每月销售趋势",
        "question": "每个月的销售额走势怎么样？是在涨还是跌？",
        "skill": "DATE_FORMAT + GROUP BY + JOIN",
    },
    {
        "id": 3,
        "title": "各品类销售额排名",
        "question": "哪个商品品类最赚钱？给我排个名，前几名是哪些？",
        "skill": "JOIN + GROUP BY + ORDER BY + LIMIT",
    },
    {
        "id": 4,
        "title": "复购率",
        "question": "我们的客户忠诚吗？整体复购率是多少？",
        "skill": "子查询 + GROUP BY + 去重",
    },
    {
        "id": 5,
        "title": "各州订单分布 + 配送天数",
        "question": "订单在各州的分布如何？每个州的平均配送天数是多少？",
        "skill": "3 表 JOIN + 日期差 + 聚合",
    },
    {
        "id": 6,
        "title": "评分最高的产品 + 卖家",
        "question": "评分最高的产品和卖家分别是哪些？",
        "skill": "4 表 JOIN + AVG + HAVING",
    },
    {
        "id": 7,
        "title": "Top5 卖家月销售趋势",
        "question": "销售额最高的前 5 个卖家，他们每个月的销售趋势如何？",
        "skill": "CTE / ROW_NUMBER + 双聚合",
    },
    {
        "id": 8,
        "title": "下单到签收平均时长",
        "question": "从下单到客户签收，平均要多少天？各月趋势如何？",
        "skill": "TIMESTAMPDIFF + 聚合",
    },
    {
        "id": 9,
        "title": "销售额环比下降的月份",
        "question": "哪些月份的销售额比上个月下降了？",
        "skill": "LAG() 窗口函数 + 环比",
    },
    {
        "id": 10,
        "title": "高价值客户画像",
        "question": "我们的高价值客户有什么特征？该如何运营他们？",
        "skill": "CTE + NTILE 百分位分层",
    },
]
