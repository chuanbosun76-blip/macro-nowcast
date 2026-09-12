"""指标注册表（中国 + 美国）。
字段：id, name, short, country(CN/US), group, unit, freq(M/Q), role(nowcast=实时预测 / persist=沿用上期 / ref=参考展示),
      source: {"em": (表名, 字段)} 东方财富数据中心 或 {"fred": 序列, "transform": ...}
      transform: level | yoy | mom | diff | qoq_ann（FRED 序列已是增速时用 level）
      jan_merge: 1–2 月合并发布（剔除 1 月）；spring: 春节外生变量；seasonal: 12 期季节项；force_d: 差分阶
      keywords: 研报召回关键词；release: 发布规律；theory: 该指标的主要驱动因素（供 AI 研判使用）
"""

CN = [
    # —— 通胀 ——
    dict(id="cpi_yoy", name="CPI当月同比", short="CPI同比", group="通胀", unit="%", freq="M", role="persist",
         source={"em": ("RPT_ECONOMY_CPI", "NATIONAL_SAME")}, release="次月 9–10 日（国家统计局）",
         keywords=["CPI", "通胀", "物价", "猪价", "食品价格", "核心CPI"], theory="食品（猪肉、鲜菜）价格、能源价格、服务价格与基数效应",
         paper={"persist": 0.91, "ar": 0.90}),
    dict(id="cpi_mom", name="CPI环比", short="CPI环比", group="通胀", unit="%", freq="M", role="nowcast", spring=True, force_d=0,
         source={"em": ("RPT_ECONOMY_CPI", "NATIONAL_SEQUENTIAL")}, release="次月 9–10 日（国家统计局）",
         keywords=["CPI", "通胀", "物价", "猪价", "猪肉", "油价", "食品", "消费价格", "核心CPI", "通缩"],
         theory="季节性（春节、暑期）、猪价与鲜菜价格当月变动、成品油调价、服务价格", paper={"persist": 0.18, "ar": 0.57, "title": 0.23, "chunk": 0.38}),
    dict(id="ppi_yoy", name="PPI当月同比", short="PPI同比", group="通胀", unit="%", freq="M", role="persist",
         source={"em": ("RPT_ECONOMY_PPI", "BASE_SAME")}, release="次月 9–10 日（国家统计局）",
         keywords=["PPI", "工业品价格", "大宗商品", "反内卷", "产能"], theory="国际油价、黑色/有色金属价格、产能利用率、翘尾因素", paper={"persist": 0.98, "ar": 0.99}),
    # —— 增长 ——
    dict(id="gdp_yoy", name="GDP当季同比", short="GDP同比", group="增长", unit="%", freq="Q", role="ref",
         source={"em": ("RPT_ECONOMY_GDP", "SUM_SAME")}, release="季后 15–20 日（国家统计局）",
         keywords=["GDP", "经济增长", "增速"], theory="工业生产、服务业、投资与消费的季度合成"),
    dict(id="ip_yoy", name="工业增加值当月同比", short="工业增加值同比", group="增长", unit="%", freq="M", role="nowcast", jan_merge=True,
         source={"em": ("RPT_ECONOMY_INDUS_GROW", "BASE_SAME"), "fallback": "BASE_ACCUMULATE"}, release="次月 15–17 日（国家统计局）",
         keywords=["工业", "生产", "PMI", "开工", "制造业", "工业增加值", "发电", "景气"], theory="PMI 生产指数、出口交货、高炉/开工率、工作日与基数"),
    dict(id="ip_ytd", name="工业增加值累计同比", short="工业增加值累计", group="增长", unit="%", freq="M", role="nowcast", jan_merge=True,
         source={"em": ("RPT_ECONOMY_INDUS_GROW", "BASE_ACCUMULATE")}, release="次月 15–17 日（国家统计局）",
         keywords=["工业", "生产", "PMI", "开工", "制造业", "工业增加值"], theory="累计口径平滑，主要由当月同比与年内累计基数决定",
         paper={"persist": 0.72, "ar": 0.68, "title": 0.80, "chunk": 0.73}),
    dict(id="retail_yoy", name="社会消费品零售总额当月同比", short="社零同比", group="增长", unit="%", freq="M", role="nowcast", jan_merge=True, spring=True,
         source={"em": ("RPT_ECONOMY_TOTAL_RETAIL", "RETAIL_TOTAL_SAME"), "fallback": "RETAIL_ACCUMULATE_SAME"}, release="次月 15–17 日（国家统计局）",
         keywords=["消费", "社零", "零售", "以旧换新", "汽车", "餐饮", "家电", "内需", "服务消费"], theory="汽车/家电以旧换新政策、节假日错位、地产链消费、居民收入预期",
         paper={"persist": 0.75, "ar": 0.68, "title": 0.66, "chunk": 0.74}),
    dict(id="retail_ytd", name="社零累计同比", short="社零累计", group="增长", unit="%", freq="M", role="persist", jan_merge=True,
         source={"em": ("RPT_ECONOMY_TOTAL_RETAIL", "RETAIL_ACCUMULATE_SAME")}, release="次月 15–17 日（国家统计局）",
         keywords=["消费", "社零"], theory="累计口径，随当月同比缓慢变化"),
    dict(id="fiscal_rev_yoy", name="公共财政收入当月同比", short="财政收入同比", group="增长", unit="%", freq="M", role="ref", jan_merge=True,
         source={"em": ("RPT_ECONOMY_INCOME", "BASE_SAME")}, release="次月中下旬（财政部）",
         keywords=["财政", "税收", "财政收入"], theory="税收与土地出让、经济名义增速"),
    dict(id="boom_index", name="企业景气指数", short="企业景气", group="增长", unit="", freq="Q", role="ref",
         source={"em": ("RPT_ECONOMY_BOOM_INDEX", "BOOM_INDEX")}, release="季后（国家统计局）", keywords=["景气", "企业信心"], theory="企业家对宏观经济的信心"),
    # —— 外贸 ——
    dict(id="export_yoy", name="出口金额当月同比", short="出口同比", group="外贸", unit="%", freq="M", role="nowcast",
         source={"em": ("RPT_ECONOMY_CUSTOMS", "EXIT_BASE_SAME")}, release="次月 7–9 日（海关总署）",
         keywords=["出口", "外贸", "进出口", "关税", "海关", "外需", "贸易", "集装箱", "港口", "订单"], theory="外需（美欧 PMI）、关税与抢出口、汇率、基数、港口吞吐与集运价格",
         paper={"persist": 0.37, "ar": 0.43, "title": 0.72, "chunk": 0.48}),
    dict(id="import_yoy", name="进口金额当月同比", short="进口同比", group="外贸", unit="%", freq="M", role="nowcast",
         source={"em": ("RPT_ECONOMY_CUSTOMS", "IMPORT_BASE_SAME")}, release="次月 7–9 日（海关总署）",
         keywords=["进口", "进出口", "外贸", "内需", "大宗", "海关", "原油", "铁矿", "贸易"], theory="内需与大宗商品价格、加工贸易联动、基数",
         paper={"persist": 0.74, "ar": 0.76, "title": 0.65, "chunk": 0.59}),
    dict(id="trade_balance", name="贸易差额当月值", short="贸易差额", group="外贸", unit="亿美元", freq="M", role="nowcast", spring=True,
         source={"em": ("RPT_ECONOMY_CUSTOMS", "TRADE_BAL_100M_USD")}, release="次月 7–9 日（海关总署）",
         keywords=["顺差", "贸易差额", "进出口", "出口", "进口", "外贸", "关税", "海关", "贸易"], theory="出口与进口的差，受季节性（春节前后进口回落）影响明显",
         paper={"persist": 0.55, "ar": 0.65, "title": 0.76, "chunk": 0.37}),
    dict(id="fx_reserves", name="外汇储备", short="外汇储备", group="外贸", unit="亿美元", freq="M", role="persist",
         source={"em": ("RPT_ECONOMY_GOLD_CURRENCY", "FOREX")}, release="次月 7 日（外汇管理局）",
         keywords=["外汇储备", "汇率", "资本流动"], theory="估值效应（美元指数、美债价格）与跨境资金流动"),
    # —— 货币信贷 ——
    dict(id="new_loans", name="金融机构新增人民币贷款", short="新增人民币贷款", group="货币信贷", unit="亿元", freq="M", role="nowcast", seasonal=True, force_d=0,
         source={"em": ("RPT_ECONOMY_RMB_LOAN", "RMB_LOAN")}, release="次月 10–15 日（央行）",
         keywords=["信贷", "贷款", "社融", "金融数据", "M2", "M1", "货币", "降准", "降息", "LPR", "票据", "流动性", "政府债"],
         theory="季节性投放节奏（1 月、季末冲量）、票据融资、政策指导、企业与居民融资需求", paper={"persist": -0.10, "ar": 0.25, "title": 0.90, "chunk": 0.58}),
    dict(id="loans_ytd_yoy", name="人民币贷款累计同比", short="贷款累计同比", group="货币信贷", unit="%", freq="M", role="persist",
         source={"em": ("RPT_ECONOMY_RMB_LOAN", "LOAN_ACCUMULATE_SAME")}, release="次月 10–15 日（央行）", keywords=["信贷", "贷款"], theory="累计投放相对去年同期"),
    dict(id="m2_yoy", name="M2同比", short="M2同比", group="货币信贷", unit="%", freq="M", role="persist",
         source={"em": ("RPT_ECONOMY_CURRENCY_SUPPLY", "BASIC_CURRENCY_SAME")}, release="次月 10–15 日（央行）",
         keywords=["M2", "货币"], theory="信贷派生、财政投放、基数", paper={"persist": 0.96, "ar": 0.95}),
    dict(id="m1_yoy", name="M1同比", short="M1同比", group="货币信贷", unit="%", freq="M", role="persist",
         source={"em": ("RPT_ECONOMY_CURRENCY_SUPPLY", "CURRENCY_SAME")}, release="次月 10–15 日（央行）",
         keywords=["M1", "货币", "活期"], theory="企业活期存款、地产销售回款、口径调整"),
    dict(id="m0_yoy", name="M0同比", short="M0同比", group="货币信贷", unit="%", freq="M", role="ref",
         source={"em": ("RPT_ECONOMY_CURRENCY_SUPPLY", "FREE_CASH_SAME")}, release="次月 10–15 日（央行）", keywords=["M0", "现金"], theory="现金需求，春节前后季节性强"),
    # —— 景气 ——
    dict(id="pmi_mfg", name="制造业PMI", short="制造业PMI", group="景气", unit="", freq="M", role="ref",
         source={"em": ("RPT_ECONOMY_PMI", "MAKE_INDEX")}, release="当月月末（国家统计局，无滞后）", keywords=["PMI", "景气", "制造业"], theory="新订单、生产、库存分项"),
    dict(id="pmi_nonmfg", name="非制造业PMI", short="非制造业PMI", group="景气", unit="", freq="M", role="ref",
         source={"em": ("RPT_ECONOMY_PMI", "NMAKE_INDEX")}, release="当月月末（国家统计局，无滞后）", keywords=["PMI", "服务业", "建筑业"], theory="建筑业与服务业景气"),
    # —— 地产 ——
    dict(id="house_price_70", name="70城新建商品住宅价格同比（均值）", short="70城房价同比", group="地产", unit="%", freq="M", role="nowcast",
         source={"em_house": "FIRST_COMHOUSE_SAME"}, release="次月 15–17 日（国家统计局）",
         keywords=["房价", "地产", "楼市", "商品房", "销售", "房地产"], theory="销售景气、库存去化、政策（限购/房贷利率）、基数"),
]

US = [
    # —— 通胀 ——
    dict(id="us_cpi_yoy", name="美国CPI同比", short="美CPI同比", group="通胀", unit="%", freq="M", role="nowcast",
         source={"fred": "CPIAUCSL", "transform": "yoy", "em_us": "EMG00000733"}, release="次月 10–15 日（BLS）",
         keywords=["美国CPI", "美国通胀", "美联储", "通胀", "油价", "关税", "美国"], theory="能源与食品价格、住房租金（滞后）、核心商品（关税传导）、基数效应"),
    dict(id="us_cpi_mom", name="美国CPI环比", short="美CPI环比", group="通胀", unit="%", freq="M", role="nowcast",
         source={"fred": "CPIAUCSL", "transform": "mom", "em_us": "EMG00000770"}, release="次月 10–15 日（BLS）",
         keywords=["美国CPI", "美国通胀", "美联储", "通胀", "油价", "关税"], theory="汽油价格当月变动、住房 OER、二手车、机票等波动分项"),
    dict(id="us_core_cpi_yoy", name="美国核心CPI同比", short="美核心CPI", group="通胀", unit="%", freq="M", role="nowcast",
         source={"fred": "CPILFESL", "transform": "yoy", "em_us": "EMG00000746"}, release="次月 10–15 日（BLS）",
         keywords=["核心CPI", "美国通胀", "美联储", "住房", "关税"], theory="住房租金、核心服务（工资驱动）、核心商品（关税、供应链）"),
    dict(id="us_pce_yoy", name="美国PCE物价同比", short="美PCE", group="通胀", unit="%", freq="M", role="persist",
         source={"fred": "PCEPI", "transform": "yoy"}, release="次月底（BEA）", keywords=["PCE", "美联储", "通胀"], theory="与 CPI 高度相关，权重不同（医疗更高、住房更低）"),
    dict(id="us_core_pce_yoy", name="美国核心PCE同比", short="美核心PCE", group="通胀", unit="%", freq="M", role="persist",
         source={"fred": "PCEPILFE", "transform": "yoy"}, release="次月底（BEA）", keywords=["核心PCE", "美联储", "通胀"], theory="美联储目标口径，可由 CPI/PPI 分项推算"),
    dict(id="us_ppi_yoy", name="美国PPI同比", short="美PPI", group="通胀", unit="%", freq="M", role="persist",
         source={"fred": "PPIFIS", "transform": "yoy"}, release="次月中旬（BLS）", keywords=["PPI", "美国通胀"], theory="能源、贸易服务利润率、关税"),
    # —— 就业 ——
    dict(id="us_nfp", name="美国非农新增就业", short="非农新增", group="就业", unit="千人", freq="M", role="nowcast",
         source={"fred": "PAYEMS", "transform": "diff", "em_us": "EMG00152118"}, release="次月第一个周五（BLS）",
         keywords=["非农", "美国就业", "失业率", "美联储", "劳动力市场", "裁员"], theory="ADP/初请失业金、JOLTS 职位空缺、企业调查、政府就业、移民与罢工等一次性因素"),
    dict(id="us_unrate", name="美国失业率", short="美失业率", group="就业", unit="%", freq="M", role="nowcast",
         source={"fred": "UNRATE", "transform": "level", "em_us": "EMG00001039"}, release="次月第一个周五（BLS）",
         keywords=["失业率", "非农", "美国就业", "劳动力"], theory="劳动参与率、持续申领失业金人数、家庭调查噪声"),
    dict(id="us_wage_yoy", name="美国时薪同比", short="美时薪", group="就业", unit="%", freq="M", role="persist",
         source={"fred": "AHETPI", "transform": "yoy"}, release="次月第一个周五（BLS）", keywords=["工资", "薪资", "非农"], theory="劳动力供需、最低工资调整、构成效应"),
    dict(id="us_claims", name="美国初请失业金（月均，千人）", short="初请失业金", group="就业", unit="千人", freq="M", role="ref",
         source={"fred": "ICSA", "transform": "level", "agg": "mean", "scale": 0.001}, release="每周四（劳工部）", keywords=["初请", "失业金", "裁员"], theory="裁员节奏的高频先行指标"),
    dict(id="us_jolts", name="美国职位空缺（JOLTS，千人）", short="职位空缺", group="就业", unit="千人", freq="M", role="persist",
         source={"fred": "JTSJOL", "transform": "level"}, release="隔月初（BLS）", keywords=["职位空缺", "JOLTS", "美国就业"], theory="劳动力需求，领先非农"),
    # —— 增长 ——
    dict(id="us_gdp_qoq", name="美国实际GDP环比折年", short="美GDP", group="增长", unit="%", freq="Q", role="ref",
         source={"fred": "A191RL1Q225SBEA", "transform": "level", "em_us": "EMG00159633"}, release="季后首月末（BEA，初值）", keywords=["美国GDP", "美国经济", "衰退"], theory="消费、投资、净出口与库存的季度合成；GDPNow 类高频拆分"),
    dict(id="us_retail_mom", name="美国零售销售环比", short="美零售环比", group="增长", unit="%", freq="M", role="nowcast",
         source={"fred": "RSAFS", "transform": "mom", "em_us": "EMG00003721"}, release="次月中旬（Census）",
         keywords=["美国零售", "美国消费", "消费者", "信用卡"], theory="汽车销售、汽油价格（名义值）、信用卡消费高频数据、天气与假日"),
    dict(id="us_indpro_yoy", name="美国工业产出同比", short="美工业产出", group="增长", unit="%", freq="M", role="persist",
         source={"fred": "INDPRO", "transform": "yoy"}, release="次月中旬（美联储）", keywords=["美国制造业", "ISM", "工业产出"], theory="ISM 生产分项、汽车产量、公用事业（天气）"),
    dict(id="us_tcu", name="美国产能利用率", short="产能利用率", group="增长", unit="%", freq="M", role="persist",
         source={"fred": "TCU", "transform": "level"}, release="次月中旬（美联储）", keywords=["产能利用率", "美国制造业"], theory="与工业产出同源"),
    dict(id="us_durable_mom", name="美国耐用品订单环比", short="耐用品订单", group="增长", unit="%", freq="M", role="nowcast",
         source={"fred": "DGORDER", "transform": "mom", "em_us": "EMG00342254"}, release="次月下旬（Census）", keywords=["耐用品", "订单", "波音", "资本开支"], theory="飞机订单（波音）主导波动，核心资本品反映投资"),
    dict(id="us_umcsent", name="密歇根消费者信心", short="密歇根信心", group="增长", unit="", freq="M", role="ref",
         source={"fred": "UMCSENT", "transform": "level", "em_us": "EMG00002846"}, release="当月中旬初值/月末终值", keywords=["消费者信心", "密歇根", "通胀预期"], theory="汽油价格、股市、通胀预期、政治周期"),
    dict(id="us_ppi_mom", name="美国PPI环比", short="美PPI环比", group="通胀", unit="%", freq="M", role="persist",
         source={"em_us": "EMG00177897"}, release="次月中旬（BLS）", keywords=["PPI", "美国通胀", "生产者价格", "关税"],
         theory="能源与食品批发价、贸易服务利润率、关税向上游传导"),
    dict(id="us_core_ppi_yoy", name="美国核心PPI同比", short="美核心PPI", group="通胀", unit="%", freq="M", role="persist",
         source={"em_us": "EMG00177799"}, release="次月中旬（BLS）", keywords=["核心PPI", "PPI", "美国通胀"], theory="剔除食品能源后的上游价格，领先核心商品 CPI"),
    dict(id="us_conf_board", name="咨商会消费者信心指数", short="咨商会信心", group="增长", unit="", freq="M", role="ref",
         source={"em_us": "EMG00002847"}, release="当月最后一个周二（Conference Board）", keywords=["消费者信心", "咨商会", "就业预期"],
         theory="就业市场感受、股市、汽油价格；与密歇根指数互补"),
    dict(id="us_existing_sales", name="美国成屋销售（万套，折年）", short="成屋销售", group="地产", unit="万套", freq="M", role="persist",
         source={"em_us": "EMG00003078"}, release="次月下旬（NAR）", keywords=["成屋销售", "美国地产", "房贷利率", "住房"],
         theory="房贷利率、待售库存、房价可负担性；领先指标为未决房屋销售"),
    dict(id="us_pending_home", name="美国未决房屋销售环比", short="未决房屋销售", group="地产", unit="%", freq="M", role="persist",
         source={"em_us": "EMG00342249"}, release="次月下旬（NAR）", keywords=["未决房屋", "成屋", "美国地产", "房贷利率"],
         theory="签约领先成屋销售 1–2 个月，对房贷利率敏感"),
    dict(id="us_ism_mfg", name="美国ISM制造业PMI", short="ISM制造业", group="增长", unit="", freq="M", role="nowcast",
         source={"em_us": "EMG00002790"}, release="次月第一个工作日（ISM）",
         keywords=["ISM", "美国制造业", "PMI", "美国经济", "关税", "新订单"], theory="新订单-库存差、地区联储制造业调查（Empire/Philly）、Markit PMI、关税与补库周期"),
    dict(id="us_ism_nonmfg", name="美国ISM非制造业PMI", short="ISM非制造业", group="增长", unit="", freq="M", role="persist",
         source={"em_us": "EMG00002791"}, release="次月第三个工作日（ISM）",
         keywords=["ISM", "服务业", "PMI", "美国经济"], theory="服务消费、就业分项与新订单；与制造业 PMI 相关性有限"),
    # —— 地产 ——
    dict(id="us_houst", name="美国新屋开工（千套，折年）", short="新屋开工", group="地产", unit="千套", freq="M", role="nowcast",
         source={"fred": "HOUST", "transform": "level", "em_us": "EMG00003224"}, release="次月中旬（Census）", keywords=["美国地产", "新屋开工", "房贷利率", "住房"], theory="房贷利率、建筑许可（领先）、天气、建筑商信心 NAHB"),
    dict(id="us_permit", name="美国建筑许可（千套，折年）", short="建筑许可", group="地产", unit="千套", freq="M", role="persist",
         source={"fred": "PERMIT", "transform": "level"}, release="次月中旬（Census）", keywords=["建筑许可", "美国地产", "住房"], theory="领先新屋开工 1–2 个月"),
    # —— 货币利率 ——
    dict(id="us_fedfunds", name="联邦基金利率（目标上限）", short="联邦基金利率", group="货币利率", unit="%", freq="M", role="ref",
         source={"fred": "FEDFUNDS", "transform": "level", "em_us": "EMG00342250"}, release="每日（美联储）", keywords=["美联储", "降息", "加息", "FOMC", "利率"], theory="FOMC 决议与点阵图、通胀与就业双目标"),
    dict(id="us_gs10", name="美国10年期国债收益率（月均）", short="美债10Y", group="货币利率", unit="%", freq="M", role="ref",
         source={"fred": "GS10", "transform": "level"}, release="每日", keywords=["美债", "收益率", "美联储", "期限溢价"], theory="政策利率预期、期限溢价、财政赤字与发债"),
    dict(id="us_t10y2y", name="美债10Y-2Y利差（月均）", short="10Y-2Y利差", group="货币利率", unit="%", freq="M", role="ref",
         source={"fred": "T10Y2YM", "transform": "level"}, release="每日", keywords=["利差", "倒挂", "衰退", "美债"], theory="衰退预期与政策路径"),
    dict(id="us_trade_balance", name="美国商品和服务贸易差额", short="美贸易差额", group="外贸", unit="亿美元", freq="M", role="persist",
         source={"fred": "BOPGSTB", "transform": "level", "scale": 0.01, "em_us": "EMG00000700", "em_scale": 0.01}, release="隔月初（Census/BEA）", keywords=["美国贸易", "逆差", "关税", "进口"], theory="关税前抢进口、美元、能源出口"),
]

INDICATORS = CN + US
for _i in CN:
    _i["country"] = "CN"
for _i in US:
    _i["country"] = "US"
for _i in INDICATORS:
    _i.setdefault("spring", False); _i.setdefault("seasonal", False); _i.setdefault("jan_merge", False)
    _i.setdefault("paper", None); _i.setdefault("force_d", None)

BY_ID = {x["id"]: x for x in INDICATORS}
GROUPS_ORDER = ["增长", "通胀", "就业", "外贸", "货币信贷", "货币利率", "地产", "景气"]

LLM_MODES = {
    "title": "研报标题 + 数据研判（推荐）",
    "chunk": "研报正文片段 + 数据研判",
    "title_ar": "研报标题 + 自回归参考",
    "data": "仅数据研判（不读研报）",
}

# 东方财富表 → 快照字段
EM_FIELDS = {
    "RPT_ECONOMY_CPI": ["NATIONAL_SAME", "NATIONAL_SEQUENTIAL"],
    "RPT_ECONOMY_PPI": ["BASE_SAME"],
    "RPT_ECONOMY_TOTAL_RETAIL": ["RETAIL_TOTAL_SAME", "RETAIL_ACCUMULATE_SAME"],
    "RPT_ECONOMY_INDUS_GROW": ["BASE_SAME", "BASE_ACCUMULATE"],
    "RPT_ECONOMY_RMB_LOAN": ["RMB_LOAN", "LOAN_ACCUMULATE_SAME"],
    "RPT_ECONOMY_CUSTOMS": ["EXIT_BASE_SAME", "IMPORT_BASE_SAME", "TRADE_BAL_100M_USD"],
    "RPT_ECONOMY_CURRENCY_SUPPLY": ["BASIC_CURRENCY_SAME", "CURRENCY_SAME", "FREE_CASH_SAME"],
    "RPT_ECONOMY_PMI": ["MAKE_INDEX", "NMAKE_INDEX"],
    "RPT_ECONOMY_GDP": ["SUM_SAME"],
    "RPT_ECONOMY_GOLD_CURRENCY": ["FOREX"],
    "RPT_ECONOMY_INCOME": ["BASE_SAME"],
    "RPT_ECONOMY_BOOM_INDEX": ["BOOM_INDEX"],
}
