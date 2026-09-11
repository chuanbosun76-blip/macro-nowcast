"""指标注册表：与原文“指标选取 / 自回归对照表”对应。"""

# source: 东方财富数据中心 reportName；field: 字段；jan_merge: 1–2 月合并发布
# role: nowcast = 原文“需实时预测”(√)；persist = 原文高相关、沿用上期(X)
# spring: 原文做春节调整；seasonal: 使用 (P,D,Q,12) 季节参数
INDICATORS = [
    {
        "id": "new_loans", "name": "金融机构新增人民币贷款当月值", "short": "新增人民币贷款", "unit": "亿元",
        "source": "RPT_ECONOMY_RMB_LOAN", "field": "RMB_LOAN", "role": "nowcast", "group": "流动性",
        "spring": False, "seasonal": True, "force_d": 0, "jan_merge": False, "fmt": "{:,.0f}", "release": "次月 10–15 日（央行金融统计数据）",
        "keywords": ["信贷", "贷款", "社融", "金融数据", "M2", "M1", "货币", "降准", "降息", "LPR", "票据", "流动性", "政府债"],
        "paper": {"persist": -0.10, "ar": 0.25, "ar2": 0.27, "title": 0.90, "chunk": 0.58, "title_ar": -0.04, "chunk_ar": -0.13},
    },
    {
        "id": "export_yoy", "name": "出口金额当月同比", "short": "出口同比", "unit": "%",
        "source": "RPT_ECONOMY_CUSTOMS", "field": "EXIT_BASE_SAME", "role": "nowcast", "group": "增长",
        "spring": False, "seasonal": False, "jan_merge": False, "fmt": "{:.1f}", "release": "次月 7–9 日（海关总署）",
        "keywords": ["出口", "外贸", "进出口", "关税", "海关", "外需", "贸易", "集装箱", "港口", "订单"],
        "paper": {"persist": 0.37, "ar": 0.43, "ar2": 0.43, "title": 0.72, "chunk": 0.48, "title_ar": 0.36, "chunk_ar": 0.43},
    },
    {
        "id": "trade_balance", "name": "贸易差额当月值", "short": "贸易差额", "unit": "亿美元",
        "source": "RPT_ECONOMY_CUSTOMS", "field": "TRADE_BAL_100M_USD", "role": "nowcast", "group": "增长",
        "spring": True, "seasonal": False, "jan_merge": False, "fmt": "{:,.1f}", "release": "次月 7–9 日（海关总署）",
        "keywords": ["顺差", "贸易差额", "进出口", "出口", "进口", "外贸", "关税", "海关", "贸易"],
        "paper": {"persist": 0.55, "ar": 0.65, "ar2": 0.64, "title": 0.76, "chunk": 0.37, "title_ar": 0.69, "chunk_ar": 0.38},
    },
    {
        "id": "cpi_mom", "name": "CPI环比", "short": "CPI环比", "unit": "%",
        "source": "RPT_ECONOMY_CPI", "field": "NATIONAL_SEQUENTIAL", "role": "nowcast", "group": "通胀",
        "spring": True, "seasonal": False, "force_d": 0, "jan_merge": False, "fmt": "{:.1f}", "release": "次月 9–10 日（国家统计局）",
        "keywords": ["CPI", "通胀", "物价", "猪价", "猪肉", "油价", "食品", "消费价格", "核心CPI", "通缩"],
        "paper": {"persist": 0.18, "ar": 0.57, "ar2": 0.57, "title": 0.23, "chunk": 0.38, "title_ar": 0.25, "chunk_ar": 0.45},
    },
    {
        "id": "ip_ytd", "name": "工业增加值规模以上累计同比", "short": "工业增加值累计同比", "unit": "%",
        "source": "RPT_ECONOMY_INDUS_GROW", "field": "BASE_ACCUMULATE", "role": "nowcast", "group": "增长",
        "spring": False, "seasonal": False, "jan_merge": True, "fmt": "{:.1f}", "release": "次月 15–17 日（国家统计局）",
        "keywords": ["工业", "生产", "PMI", "开工", "制造业", "工业增加值", "高炉", "发电", "景气"],
        "paper": {"persist": 0.72, "ar": 0.68, "ar2": 0.68, "title": 0.80, "chunk": 0.73, "title_ar": 0.51, "chunk_ar": 0.67},
    },
    {
        "id": "import_yoy", "name": "进口金额当月同比", "short": "进口同比", "unit": "%",
        "source": "RPT_ECONOMY_CUSTOMS", "field": "IMPORT_BASE_SAME", "role": "nowcast", "group": "增长",
        "spring": False, "seasonal": False, "jan_merge": False, "fmt": "{:.1f}", "release": "次月 7–9 日（海关总署）",
        "keywords": ["进口", "进出口", "外贸", "内需", "大宗", "海关", "原油", "铁矿", "贸易"],
        "paper": {"persist": 0.74, "ar": 0.76, "ar2": 0.76, "title": 0.65, "chunk": 0.59, "title_ar": 0.50, "chunk_ar": 0.54},
    },
    {
        "id": "retail_yoy", "name": "社会消费品零售总额当月同比", "short": "社零同比", "unit": "%",
        "source": "RPT_ECONOMY_TOTAL_RETAIL", "field": "RETAIL_TOTAL_SAME", "fallback": "RETAIL_ACCUMULATE_SAME", "role": "nowcast", "group": "增长",
        "spring": True, "seasonal": False, "jan_merge": True, "fmt": "{:.1f}", "release": "次月 15–17 日（国家统计局）",
        "keywords": ["消费", "社零", "零售", "以旧换新", "汽车", "餐饮", "家电", "内需", "服务消费"],
        "paper": {"persist": 0.75, "ar": 0.68, "ar2": 0.68, "title": 0.66, "chunk": 0.74, "title_ar": 0.48, "chunk_ar": 0.79},
    },
    # —— 原文高相关（≥0.8）指标：直接沿用上期 ——
    {
        "id": "cpi_yoy", "name": "CPI当月同比", "short": "CPI同比", "unit": "%",
        "source": "RPT_ECONOMY_CPI", "field": "NATIONAL_SAME", "role": "persist", "group": "通胀",
        "spring": False, "seasonal": False, "jan_merge": False, "fmt": "{:.1f}", "release": "次月 9–10 日（国家统计局）",
        "keywords": ["CPI", "通胀", "物价"], "paper": {"persist": 0.91, "ar": 0.90},
    },
    {
        "id": "ppi_yoy", "name": "PPI全部工业品当月同比", "short": "PPI同比", "unit": "%",
        "source": "RPT_ECONOMY_PPI", "field": "BASE_SAME", "role": "persist", "group": "通胀",
        "spring": False, "seasonal": False, "jan_merge": False, "fmt": "{:.1f}", "release": "次月 9–10 日（国家统计局）",
        "keywords": ["PPI", "工业品", "价格"], "paper": {"persist": 0.98, "ar": 0.99},
    },
    {
        "id": "m2_yoy", "name": "M2同比", "short": "M2同比", "unit": "%",
        "source": "RPT_ECONOMY_CURRENCY_SUPPLY", "field": "BASIC_CURRENCY_SAME", "role": "persist", "group": "流动性",
        "spring": False, "seasonal": False, "jan_merge": False, "fmt": "{:.1f}", "release": "次月 10–15 日（央行）",
        "keywords": ["M2", "货币"], "paper": {"persist": 0.96, "ar": 0.95},
    },
    # —— 参考指标（原文未入选实时预测：PMI 无发布滞后；仅展示、供问答与研判参考）——
    {
        "id": "pmi_mfg", "name": "制造业PMI", "short": "制造业PMI", "unit": "%",
        "source": "RPT_ECONOMY_PMI", "field": "MAKE_INDEX", "role": "ref", "group": "景气",
        "spring": False, "seasonal": False, "jan_merge": False, "fmt": "{:.1f}", "release": "当月月末（国家统计局，无滞后）",
        "keywords": ["PMI", "景气", "制造业"], "paper": None,
    },
    {
        "id": "pmi_nonmfg", "name": "非制造业PMI", "short": "非制造业PMI", "unit": "%",
        "source": "RPT_ECONOMY_PMI", "field": "NMAKE_INDEX", "role": "ref", "group": "景气",
        "spring": False, "seasonal": False, "jan_merge": False, "fmt": "{:.1f}", "release": "当月月末（国家统计局，无滞后）",
        "keywords": ["PMI", "服务业", "建筑业"], "paper": None,
    },
    {
        "id": "m1_yoy", "name": "M1同比", "short": "M1同比", "unit": "%",
        "source": "RPT_ECONOMY_CURRENCY_SUPPLY", "field": "CURRENCY_SAME", "role": "ref", "group": "流动性",
        "spring": False, "seasonal": False, "jan_merge": False, "fmt": "{:.1f}", "release": "次月 10–15 日（央行）",
        "keywords": ["M1", "货币"], "paper": None,
    },
]

BY_ID = {x["id"]: x for x in INDICATORS}

LLM_MODES = {
    "title": "仅当月研报标题",
    "chunk": "仅当月研报正文片段",
    "title_ar": "标题 + 自回归参考",
    "chunk_ar": "正文片段 + 自回归参考",
}

# 东方财富字段 → 快照字段映射（贸易差额由出口额-进口额计算，单位：亿美元）
SOURCE_FIELDS = {
    "RPT_ECONOMY_CPI": ["NATIONAL_SAME", "NATIONAL_SEQUENTIAL"],
    "RPT_ECONOMY_PPI": ["BASE_SAME"],
    "RPT_ECONOMY_TOTAL_RETAIL": ["RETAIL_TOTAL_SAME", "RETAIL_ACCUMULATE_SAME"],
    "RPT_ECONOMY_INDUS_GROW": ["BASE_SAME", "BASE_ACCUMULATE"],
    "RPT_ECONOMY_RMB_LOAN": ["RMB_LOAN"],
    "RPT_ECONOMY_CUSTOMS": ["EXIT_BASE_SAME", "IMPORT_BASE_SAME", "TRADE_BAL_100M_USD"],
    "RPT_ECONOMY_CURRENCY_SUPPLY": ["BASIC_CURRENCY_SAME", "CURRENCY_SAME"],
    "RPT_ECONOMY_PMI": ["MAKE_INDEX", "NMAKE_INDEX"],
}
