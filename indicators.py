"""指标注册表 v3（中国 + 美国，分层分类）。
字段：
  id, name, short, country(CN/US), l1(一级分类), l2(二级分类), unit, freq(M/Q), role(nowcast=实时预测 / persist=沿用上期 / ref=参考)
  kind: yoy | mom | level | flow | index | rate  —— 决定季度/年度聚合方式（yoy/mom/index/rate→均值，flow→求和，level→均值，stock→期末）
  agg: 可显式覆盖聚合方式 mean | sum | last
  source:
    {"em": (表, 字段)}                     东方财富数据中心月度表
    {"em_house": 字段}                    70 城房价（按城市取均值）
    {"em_us": EMG代码}                    东方财富·全球宏观（美国）
    {"em_step": (表, 字段, 日期字段)}       事件型（准备金率）→ 月度前值填充
    {"em_accum_yoy": (表, 累计字段)}       由累计值计算累计同比（未剔除基数修订）
    {"gdp": 模式}                         由 GDP 累计表推算（q_yoy 当季同比估算 / nominal_yoy 名义同比估算 / 分产业）
    {"derived": [id_a, op, id_b]}         派生指标（剪刀差等）
    {"yield": 市场键}                      国债收益率月均（markets 模块）
    {"fred": 序列, "transform": ...}       FRED 备源（服务器可达时）
  release: 发布规律（用于估算公布日）；keywords: 研报召回；theory: 驱动因素；
  spring: 春节外生变量；seasonal: 12 期季节项；jan_merge: 1–2 月合并发布；force_d: 差分阶数
  paper: 中金论文回测参考值（仅展示）
"""

CN = [
    # ================= 增长 =================
    # —— 总量（季度）——
    dict(id="gdp_yoy", name="GDP累计同比（实际）", short="GDP累计同比", l1="增长", l2="总量", unit="%", freq="Q", role="ref", kind="yoy",
         source={"em": ("RPT_ECONOMY_GDP", "SUM_SAME")}, release="季后 15–20 日（国家统计局）",
         keywords=["GDP", "经济增长", "增速"], theory="工业生产、服务业、投资与消费的季度合成；官方口径为年初至今累计同比"),
    dict(id="gdp_q_yoy", name="GDP当季同比（估算）", short="GDP当季同比", l1="增长", l2="总量", unit="%", freq="Q", role="nowcast", kind="yoy",
         source={"gdp": "q_yoy"}, release="季后 15–20 日（国家统计局）",
         keywords=["GDP", "经济增长", "增速", "季度", "开门红"], theory="由累计同比与上年同期名义权重推算的单季增速；月度追踪用工业增加值、社零、出口、固投、PMI 桥方程（信达/中金月度 GDP 方法）"),
    dict(id="gdp_nominal_yoy", name="名义GDP当季同比（估算）", short="名义GDP同比", l1="增长", l2="总量", unit="%", freq="Q", role="persist", kind="yoy",
         source={"gdp": "nominal_yoy"}, release="季后 15–20 日（国家统计局）", keywords=["名义GDP", "GDP平减", "价格"], theory="实际增速 + 平减指数；决定企业营收与财政收入弹性"),
    dict(id="gdp_ind2_yoy", name="第二产业累计同比", short="二产累计同比", l1="增长", l2="总量", unit="%", freq="Q", role="ref", kind="yoy",
         source={"em": ("RPT_ECONOMY_GDP", "SECOND_SAME")}, release="季后 15–20 日（国家统计局）", keywords=["第二产业", "工业", "建筑业"], theory="工业 + 建筑业"),
    dict(id="gdp_ind3_yoy", name="第三产业累计同比", short="三产累计同比", l1="增长", l2="总量", unit="%", freq="Q", role="ref", kind="yoy",
         source={"em": ("RPT_ECONOMY_GDP", "THIRD_SAME")}, release="季后 15–20 日（国家统计局）", keywords=["第三产业", "服务业"], theory="服务业生产指数"),
    # —— 生产 ——
    dict(id="ip_yoy", name="工业增加值当月同比", short="工业增加值同比", l1="增长", l2="生产", unit="%", freq="M", role="nowcast", kind="yoy", jan_merge=True,
         source={"em": ("RPT_ECONOMY_INDUS_GROW", "BASE_SAME"), "fallback": "BASE_ACCUMULATE"}, release="次月 15–17 日（国家统计局）",
         keywords=["工业", "生产", "PMI", "开工", "制造业", "工业增加值", "发电", "景气"], theory="PMI 生产指数、出口交货、高炉/开工率、工作日与基数"),
    dict(id="ip_ytd", name="工业增加值累计同比", short="工业增加值累计", l1="增长", l2="生产", unit="%", freq="M", role="nowcast", kind="yoy", jan_merge=True,
         source={"em": ("RPT_ECONOMY_INDUS_GROW", "BASE_ACCUMULATE")}, release="次月 15–17 日（国家统计局）",
         keywords=["工业", "生产", "PMI", "开工", "制造业", "工业增加值"], theory="累计口径平滑，主要由当月同比与年内累计基数决定",
         paper={"persist": 0.72, "ar": 0.68, "title": 0.80, "chunk": 0.73}),
    dict(id="boom_index", name="企业景气指数", short="企业景气", l1="增长", l2="生产", unit="", freq="Q", role="ref", kind="index",
         source={"em": ("RPT_ECONOMY_BOOM_INDEX", "BOOM_INDEX")}, release="季后（国家统计局）", keywords=["景气", "企业信心"], theory="企业家对宏观经济的信心"),
    dict(id="faith_index", name="企业家信心指数", short="企业家信心", l1="增长", l2="生产", unit="", freq="Q", role="ref", kind="index",
         source={"em": ("RPT_ECONOMY_BOOM_INDEX", "FAITH_INDEX")}, release="季后（国家统计局）", keywords=["企业家信心", "景气"], theory="领先制造业投资约 4 个季度（信达）"),
    # —— 消费 ——
    dict(id="retail_yoy", name="社会消费品零售总额当月同比", short="社零同比", l1="增长", l2="消费", unit="%", freq="M", role="nowcast", kind="yoy", jan_merge=True, spring=True,
         source={"em": ("RPT_ECONOMY_TOTAL_RETAIL", "RETAIL_TOTAL_SAME"), "fallback": "RETAIL_ACCUMULATE_SAME"}, release="次月 15–17 日（国家统计局）",
         keywords=["消费", "社零", "零售", "以旧换新", "汽车", "餐饮", "家电", "内需", "服务消费"], theory="汽车/家电以旧换新政策、节假日错位、地产链消费、居民收入预期；乘用车零售、油价、纺织价格为高频代理（信达消费指数）",
         paper={"persist": 0.75, "ar": 0.68, "title": 0.66, "chunk": 0.74}),
    dict(id="retail_ytd", name="社零累计同比", short="社零累计", l1="增长", l2="消费", unit="%", freq="M", role="persist", kind="yoy", jan_merge=True,
         source={"em": ("RPT_ECONOMY_TOTAL_RETAIL", "RETAIL_ACCUMULATE_SAME")}, release="次月 15–17 日（国家统计局）", keywords=["消费", "社零"], theory="累计口径，随当月同比缓慢变化"),
    dict(id="retail_level", name="社零总额当月值", short="社零总额", l1="增长", l2="消费", unit="亿元", freq="M", role="ref", kind="flow", jan_merge=True,
         source={"em": ("RPT_ECONOMY_TOTAL_RETAIL", "RETAIL_TOTAL")}, release="次月 15–17 日（国家统计局）", keywords=["社零", "消费"], theory="名义消费规模"),
    dict(id="consumer_conf", name="消费者信心指数", short="消费者信心", l1="增长", l2="消费", unit="", freq="M", role="persist", kind="index",
         source={"em": ("RPT_ECONOMY_FAITH_INDEX", "CONSUMERS_FAITH_INDEX")}, release="次月下旬（国家统计局）", keywords=["消费者信心", "消费意愿", "就业预期"], theory="收入预期、就业预期、地产财富效应"),
    dict(id="consumer_expect", name="消费者预期指数", short="消费者预期", l1="增长", l2="消费", unit="", freq="M", role="ref", kind="index",
         source={"em": ("RPT_ECONOMY_FAITH_INDEX", "CONSUMERS_EXPECT_INDEX")}, release="次月下旬（国家统计局）", keywords=["消费者预期", "消费者信心"], theory="对未来 6 个月的预期，领先满意度"),
    dict(id="consumer_satis", name="消费者满意指数", short="消费者满意", l1="增长", l2="消费", unit="", freq="M", role="ref", kind="index",
         source={"em": ("RPT_ECONOMY_FAITH_INDEX", "CONSUMERS_ASTIS_INDEX")}, release="次月下旬（国家统计局）", keywords=["消费者满意", "消费者信心"], theory="当前状况评价"),
    # —— 投资 ——
    dict(id="fai_ytd_yoy", name="固定资产投资累计同比（按未修订基数计算）", short="固投累计同比", l1="增长", l2="投资", unit="%", freq="M", role="nowcast", kind="yoy", jan_merge=True,
         source={"em_accum_yoy": ("RPT_ECONOMY_ASSET_INVEST", "BASE_ACCUMULATE")}, release="次月 15–17 日（国家统计局）",
         keywords=["固定资产投资", "基建", "制造业投资", "房地产投资", "专项债", "投资"], theory="基建（财政资金领先 1 个月）、制造业（利润与出口交货值领先 12 个月）、地产（销售领先 1 季度）三分法（信达）；注意：官方累计同比按修订后基数计算，与本口径可有数个百分点差异"),
    dict(id="fai_month", name="固定资产投资当月值", short="固投当月值", l1="增长", l2="投资", unit="亿元", freq="M", role="ref", kind="flow", jan_merge=True,
         source={"em": ("RPT_ECONOMY_ASSET_INVEST", "BASE")}, release="次月 15–17 日（国家统计局）", keywords=["固定资产投资"], theory="名义投资规模，季末月集中"),
    dict(id="fai_month_yoy", name="固定资产投资当月同比（按未修订基数计算）", short="固投当月同比", l1="增长", l2="投资", unit="%", freq="M", role="persist", kind="yoy", jan_merge=True,
         source={"em": ("RPT_ECONOMY_ASSET_INVEST", "BASE_SAME")}, release="次月 15–17 日（国家统计局）", keywords=["固定资产投资", "基建", "投资"], theory="当月口径波动大于累计口径"),
    # ================= 通胀 =================
    dict(id="cpi_yoy", name="CPI当月同比", short="CPI同比", l1="通胀", l2="消费价格", unit="%", freq="M", role="persist", kind="yoy",
         source={"em": ("RPT_ECONOMY_CPI", "NATIONAL_SAME")}, release="次月 9–10 日（国家统计局）",
         keywords=["CPI", "通胀", "物价", "猪价", "食品价格", "核心CPI"], theory="食品（猪肉、鲜菜）价格、能源价格、服务价格与基数效应（翘尾 + 新涨价）",
         paper={"persist": 0.91, "ar": 0.90}),
    dict(id="cpi_mom", name="CPI环比", short="CPI环比", l1="通胀", l2="消费价格", unit="%", freq="M", role="nowcast", kind="mom", spring=True, force_d=0,
         source={"em": ("RPT_ECONOMY_CPI", "NATIONAL_SEQUENTIAL")}, release="次月 9–10 日（国家统计局）",
         keywords=["CPI", "通胀", "物价", "猪价", "猪肉", "油价", "食品", "消费价格", "核心CPI", "通缩"],
         theory="季节性（春节、暑期）、猪价与鲜菜价格当月变动、成品油调价、服务价格；克利夫兰联储做法：核心用 12 个月均值持续性 + 能源用高频油价", paper={"persist": 0.18, "ar": 0.57, "title": 0.23, "chunk": 0.38}),
    dict(id="cpi_city_yoy", name="城市CPI同比", short="城市CPI", l1="通胀", l2="消费价格", unit="%", freq="M", role="ref", kind="yoy",
         source={"em": ("RPT_ECONOMY_CPI", "CITY_SAME")}, release="次月 9–10 日（国家统计局）", keywords=["CPI", "城市"], theory="服务权重更高"),
    dict(id="cpi_rural_yoy", name="农村CPI同比", short="农村CPI", l1="通胀", l2="消费价格", unit="%", freq="M", role="ref", kind="yoy",
         source={"em": ("RPT_ECONOMY_CPI", "RURAL_SAME")}, release="次月 9–10 日（国家统计局）", keywords=["CPI", "农村"], theory="食品权重更高"),
    dict(id="ppi_yoy", name="PPI当月同比", short="PPI同比", l1="通胀", l2="工业价格", unit="%", freq="M", role="persist", kind="yoy",
         source={"em": ("RPT_ECONOMY_PPI", "BASE_SAME")}, release="次月 9–10 日（国家统计局）",
         keywords=["PPI", "工业品价格", "大宗商品", "反内卷", "产能"], theory="国际油价、黑色/有色金属价格、产能利用率、翘尾因素；PPI 同比 ≈ 工业企业利润的价格因子（利润 = 量 × 价 × 利润率）", paper={"persist": 0.98, "ar": 0.99}),
    dict(id="ppi_ytd", name="PPI累计同比", short="PPI累计", l1="通胀", l2="工业价格", unit="%", freq="M", role="ref", kind="yoy",
         source={"em": ("RPT_ECONOMY_PPI", "BASE_ACCUMULATE"), "offset": -100}, release="次月 9–10 日（国家统计局）", keywords=["PPI"],
         theory="累计口径（原始表为“上年同期=100”的累计指数，此处减 100 转为累计同比）"),
    dict(id="cgpi_yoy", name="企业商品价格指数（CGPI）同比", short="CGPI同比", l1="通胀", l2="上游价格", unit="%", freq="M", role="persist", kind="yoy",
         source={"em": ("RPT_ECONOMY_GOODS_INDEX", "BASE_SAME")}, release="次月中旬（人民银行）", keywords=["企业商品价格", "大宗商品", "CGPI", "上游价格"], theory="央行编制的批发环节价格，覆盖农产品、矿产品、煤油电，领先 PPI"),
    dict(id="cgpi_farm_yoy", name="CGPI农产品同比", short="CGPI农产品", l1="通胀", l2="上游价格", unit="%", freq="M", role="ref", kind="yoy",
         source={"em": ("RPT_ECONOMY_GOODS_INDEX", "FARM_BASE_SAME")}, release="次月中旬（人民银行）", keywords=["农产品价格", "猪价", "粮价"], theory="食品 CPI 的上游"),
    dict(id="cgpi_mineral_yoy", name="CGPI矿产品同比", short="CGPI矿产品", l1="通胀", l2="上游价格", unit="%", freq="M", role="ref", kind="yoy",
         source={"em": ("RPT_ECONOMY_GOODS_INDEX", "MINERAL_BASE_SAME")}, release="次月中旬（人民银行）", keywords=["矿产品价格", "铁矿", "有色", "黑色"], theory="PPI 生产资料的上游"),
    dict(id="cgpi_energy_yoy", name="CGPI煤油电同比", short="CGPI煤油电", l1="通胀", l2="上游价格", unit="%", freq="M", role="ref", kind="yoy",
         source={"em": ("RPT_ECONOMY_GOODS_INDEX", "ENERGY_BASE_SAME")}, release="次月中旬（人民银行）", keywords=["能源价格", "油价", "煤价", "电价"], theory="能源分项"),
    dict(id="ppi_cpi_gap", name="PPI−CPI剪刀差", short="PPI−CPI", l1="通胀", l2="价格结构", unit="pct", freq="M", role="ref", kind="yoy",
         source={"derived": ["ppi_yoy", "-", "cpi_yoy"]}, release="随 CPI/PPI 发布", keywords=["剪刀差", "PPI", "CPI", "利润分配"], theory="上游与下游价格差 → 中下游企业利润率；剪刀差扩大压缩中游利润"),
    # ================= 外贸与外部 =================
    dict(id="export_yoy", name="出口金额当月同比（美元）", short="出口同比", l1="外贸与外部", l2="进出口", unit="%", freq="M", role="nowcast", kind="yoy",
         source={"em": ("RPT_ECONOMY_CUSTOMS", "EXIT_BASE_SAME")}, release="次月 7–9 日（海关总署）",
         keywords=["出口", "外贸", "进出口", "关税", "海关", "外需", "贸易", "集装箱", "港口", "订单"], theory="外需（美欧 PMI，按出口份额加权）、关税与抢出口、汇率、基数、港口吞吐与集运价格（BDI/SCFI）；PPI 领先出口价格 1 季度（信达）",
         paper={"persist": 0.37, "ar": 0.43, "title": 0.72, "chunk": 0.48}),
    dict(id="import_yoy", name="进口金额当月同比（美元）", short="进口同比", l1="外贸与外部", l2="进出口", unit="%", freq="M", role="nowcast", kind="yoy",
         source={"em": ("RPT_ECONOMY_CUSTOMS", "IMPORT_BASE_SAME")}, release="次月 7–9 日（海关总署）",
         keywords=["进口", "进出口", "外贸", "内需", "大宗", "海关", "原油", "铁矿", "贸易"], theory="内需与大宗商品价格、加工贸易联动、基数",
         paper={"persist": 0.74, "ar": 0.76, "title": 0.65, "chunk": 0.59}),
    dict(id="export_ytd_yoy", name="出口累计同比", short="出口累计", l1="外贸与外部", l2="进出口", unit="%", freq="M", role="ref", kind="yoy",
         source={"em": ("RPT_ECONOMY_CUSTOMS", "EXIT_ACCUMULATE_SAME")}, release="次月 7–9 日（海关总署）", keywords=["出口"], theory="累计口径"),
    dict(id="export_level", name="出口金额当月值", short="出口金额", l1="外贸与外部", l2="进出口", unit="亿美元", freq="M", role="ref", kind="flow",
         source={"em": ("RPT_ECONOMY_CUSTOMS", "EXIT_BASE"), "scale": 1e-5}, release="次月 7–9 日（海关总署）", keywords=["出口"], theory="美元计价规模"),
    dict(id="import_level", name="进口金额当月值", short="进口金额", l1="外贸与外部", l2="进出口", unit="亿美元", freq="M", role="ref", kind="flow",
         source={"em": ("RPT_ECONOMY_CUSTOMS", "IMPORT_BASE"), "scale": 1e-5}, release="次月 7–9 日（海关总署）", keywords=["进口"], theory="美元计价规模"),
    dict(id="trade_balance", name="贸易差额当月值", short="贸易差额", l1="外贸与外部", l2="进出口", unit="亿美元", freq="M", role="nowcast", kind="flow", spring=True,
         source={"em": ("RPT_ECONOMY_CUSTOMS", "TRADE_BAL_100M_USD")}, release="次月 7–9 日（海关总署）",
         keywords=["顺差", "贸易差额", "进出口", "出口", "进口", "外贸", "关税", "海关", "贸易"], theory="出口与进口的差，受季节性（春节前后进口回落）影响明显",
         paper={"persist": 0.55, "ar": 0.65, "title": 0.76, "chunk": 0.37}),
    dict(id="fx_reserves", name="外汇储备", short="外汇储备", l1="外贸与外部", l2="储备", unit="亿美元", freq="M", role="persist", kind="stock",
         source={"em": ("RPT_ECONOMY_GOLD_CURRENCY", "FOREX")}, release="次月 7 日（外汇管理局）",
         keywords=["外汇储备", "汇率", "资本流动"], theory="估值效应（美元指数、美债价格）与跨境资金流动"),
    dict(id="gold_reserves", name="黄金储备（美元估值）", short="黄金储备", l1="外贸与外部", l2="储备", unit="亿美元", freq="M", role="ref", kind="stock",
         source={"em": ("RPT_ECONOMY_GOLD_CURRENCY", "GOLD_RESERVES")}, release="次月 7 日（外汇管理局）", keywords=["黄金储备", "央行购金"], theory="央行储备多元化"),
    dict(id="fdi_annual", name="实际使用外资金额（年度）", short="FDI年度", l1="外贸与外部", l2="资本流动", unit="亿美元", freq="A", role="ref", kind="flow",
         source={"em": ("RPT_ECONOMY_FDI_NEW", "ACTUAL_FOREIGN")}, release="次年 1 月（商务部）", keywords=["外资", "FDI", "外商投资"], theory="外资流入，年度口径"),
    # ================= 金融 =================
    dict(id="new_loans", name="金融机构新增人民币贷款", short="新增人民币贷款", l1="金融", l2="信贷", unit="亿元", freq="M", role="nowcast", kind="flow", seasonal=True, force_d=0,
         source={"em": ("RPT_ECONOMY_RMB_LOAN", "RMB_LOAN")}, release="次月 10–15 日（央行）",
         keywords=["信贷", "贷款", "社融", "金融数据", "M2", "M1", "货币", "降准", "降息", "LPR", "票据", "流动性", "政府债"],
         theory="季节性投放节奏（1 月开门红、季末冲量，'3.5/2.5/2/2' 季度分布）、票据融资、政策指导、企业与居民融资需求", paper={"persist": -0.10, "ar": 0.25, "title": 0.90, "chunk": 0.58}),
    dict(id="loans_ytd_yoy", name="人民币贷款累计同比", short="贷款累计同比", l1="金融", l2="信贷", unit="%", freq="M", role="persist", kind="yoy",
         source={"em": ("RPT_ECONOMY_RMB_LOAN", "LOAN_ACCUMULATE_SAME")}, release="次月 10–15 日（央行）", keywords=["信贷", "贷款"], theory="累计投放相对去年同期"),
    dict(id="new_deposits", name="本外币新增存款", short="新增存款", l1="金融", l2="信贷", unit="亿元", freq="M", role="ref", kind="flow",
         source={"em": ("RPT_ECONOMY_FOREX_DEPOSIT", "BASE")}, release="次月 10–15 日（央行）", keywords=["存款", "居民存款", "超额储蓄"], theory="居民与企业存款变动，季节性强"),
    dict(id="m2_yoy", name="M2同比", short="M2同比", l1="金融", l2="货币", unit="%", freq="M", role="persist", kind="yoy",
         source={"em": ("RPT_ECONOMY_CURRENCY_SUPPLY", "BASIC_CURRENCY_SAME")}, release="次月 10–15 日（央行）",
         keywords=["M2", "货币"], theory="信贷派生、财政投放、基数", paper={"persist": 0.96, "ar": 0.95}),
    dict(id="m1_yoy", name="M1同比", short="M1同比", l1="金融", l2="货币", unit="%", freq="M", role="persist", kind="yoy",
         source={"em": ("RPT_ECONOMY_CURRENCY_SUPPLY", "CURRENCY_SAME")}, release="次月 10–15 日（央行）",
         keywords=["M1", "货币", "活期"], theory="企业活期存款、地产销售回款、口径调整；与股市同步性高"),
    dict(id="m0_yoy", name="M0同比", short="M0同比", l1="金融", l2="货币", unit="%", freq="M", role="ref", kind="yoy",
         source={"em": ("RPT_ECONOMY_CURRENCY_SUPPLY", "FREE_CASH_SAME")}, release="次月 10–15 日（央行）", keywords=["M0", "现金"], theory="现金需求，春节前后季节性强"),
    dict(id="m1_m2_gap", name="M1−M2剪刀差", short="M1−M2", l1="金融", l2="货币", unit="pct", freq="M", role="ref", kind="yoy",
         source={"derived": ["m1_yoy", "-", "m2_yoy"]}, release="随货币数据发布", keywords=["剪刀差", "M1", "M2", "资金活化"], theory="剪刀差收窄/转正 → 存款活期化、经济活性改善，历史上领先 PPI 与股市"),
    dict(id="rrr", name="存款准备金率（大型机构）", short="存款准备金率", l1="金融", l2="政策", unit="%", freq="M", role="ref", kind="rate",
         source={"em_step": ("RPT_ECONOMY_DEPOSIT_RESERVE", "INTEREST_RATE_BA", "TRADE_DATE_NEW")}, release="不定期（央行公告）", keywords=["降准", "存款准备金率", "流动性", "央行"], theory="数量型政策工具，每降 0.5 个百分点释放约 1 万亿元长期资金"),
    dict(id="cn10y", name="中债10年期国债收益率（月均）", short="中债10Y", l1="金融", l2="利率", unit="%", freq="M", role="ref", kind="rate",
         source={"yield": "cn10y"}, release="每日（中债登）", keywords=["国债收益率", "债市", "利率", "降息"], theory="政策利率预期 + 期限溢价；名义增速的定价锚"),
    dict(id="cn2y", name="中债2年期国债收益率（月均）", short="中债2Y", l1="金融", l2="利率", unit="%", freq="M", role="ref", kind="rate",
         source={"yield": "cn2y"}, release="每日（中债登）", keywords=["国债收益率", "短端利率", "资金面"], theory="资金面与政策利率预期"),
    dict(id="cn_term_spread", name="中债10Y−2Y期限利差", short="中债期限利差", l1="金融", l2="利率", unit="pct", freq="M", role="ref", kind="rate",
         source={"derived": ["cn10y", "-", "cn2y"]}, release="每日", keywords=["期限利差", "曲线", "债市"], theory="曲线陡峭化 = 增长/通胀预期改善或宽松预期；平坦化相反"),
    # ================= 财政 =================
    dict(id="fiscal_rev_yoy", name="公共财政收入当月同比", short="财政收入同比", l1="财政", l2="收入", unit="%", freq="M", role="ref", kind="yoy", jan_merge=True,
         source={"em": ("RPT_ECONOMY_INCOME", "BASE_SAME")}, release="次月中下旬（财政部）",
         keywords=["财政", "税收", "财政收入"], theory="税收与土地出让、经济名义增速"),
    dict(id="fiscal_rev_ytd_yoy", name="公共财政收入累计同比", short="财政收入累计", l1="财政", l2="收入", unit="%", freq="M", role="ref", kind="yoy", jan_merge=True,
         source={"em": ("RPT_ECONOMY_INCOME", "ACCUMULATE_SAME")}, release="次月中下旬（财政部）", keywords=["财政收入"], theory="累计口径"),
    dict(id="tax_ytd_yoy", name="全国税收收入累计同比", short="税收累计同比", l1="财政", l2="收入", unit="%", freq="Q", role="ref", kind="yoy",
         source={"em": ("RPT_ECONOMY_TAX", "TAX_INCOME_SAME")}, release="季后（税务总局）", keywords=["税收", "增值税", "财政"], theory="名义 GDP 与 PPI 的函数"),
    # ================= 地产 =================
    dict(id="house_price_70", name="70城新建商品住宅价格同比（均值）", short="70城新房同比", l1="地产", l2="房价", unit="%", freq="M", role="nowcast", kind="yoy",
         source={"em_house": "FIRST_COMHOUSE_SAME"}, release="次月 15–17 日（国家统计局）",
         keywords=["房价", "地产", "楼市", "商品房", "销售", "房地产"], theory="销售景气、库存去化、政策（限购/房贷利率）、基数"),
    dict(id="house_price_70_second", name="70城二手住宅价格同比（均值）", short="70城二手同比", l1="地产", l2="房价", unit="%", freq="M", role="persist", kind="yoy",
         source={"em_house": "SECOND_HOUSE_SAME"}, release="次月 15–17 日（国家统计局）", keywords=["二手房", "房价", "地产"], theory="二手房价更能反映市场化定价，领先新房"),
    dict(id="house_price_70_mom", name="70城新建商品住宅价格环比（均值）", short="70城新房环比", l1="地产", l2="房价", unit="%", freq="M", role="ref", kind="mom",
         source={"em_house": "FIRST_COMHOUSE_SEQUENTIAL"}, release="次月 15–17 日（国家统计局）", keywords=["房价环比", "止跌回稳"], theory="环比止跌是拐点信号"),
    # ================= 景气 =================
    dict(id="pmi_mfg", name="制造业PMI", short="制造业PMI", l1="景气", l2="PMI", unit="", freq="M", role="persist", kind="index",
         source={"em": ("RPT_ECONOMY_PMI", "MAKE_INDEX")}, release="当月月末（国家统计局，无滞后）", keywords=["PMI", "景气", "制造业"], theory="新订单、生产、库存分项；50 为荣枯线"),
    dict(id="pmi_nonmfg", name="非制造业PMI", short="非制造业PMI", l1="景气", l2="PMI", unit="", freq="M", role="persist", kind="index",
         source={"em": ("RPT_ECONOMY_PMI", "NMAKE_INDEX")}, release="当月月末（国家统计局，无滞后）", keywords=["PMI", "服务业", "建筑业"], theory="建筑业与服务业景气"),
]

US = [
    # ================= 增长 =================
    dict(id="us_gdp_qoq", name="美国实际GDP环比折年率", short="美GDP", l1="增长", l2="总量", unit="%", freq="Q", role="nowcast", kind="yoy",
         source={"fred": "A191RL1Q225SBEA", "transform": "level", "em_us": "EMG00159633"}, release="季后首月末（BEA，初值）",
         keywords=["美国GDP", "美国经济", "衰退", "GDPNow"], theory="消费、投资、净出口与库存的季度合成；亚特兰大联储 GDPNow 用 13 个分项桥方程 + 动态因子模型逐日更新"),
    dict(id="us_retail_mom", name="美国零售销售环比", short="美零售环比", l1="增长", l2="消费", unit="%", freq="M", role="nowcast", kind="mom",
         source={"fred": "RSAFS", "transform": "mom", "em_us": "EMG00003721"}, release="次月中旬（Census）",
         keywords=["美国零售", "美国消费", "消费者", "信用卡"], theory="汽车销售、汽油价格（名义值）、信用卡消费高频数据、天气与假日"),
    dict(id="us_core_retail_mom", name="美国核心零售销售环比", short="美核心零售", l1="增长", l2="消费", unit="%", freq="M", role="persist", kind="mom",
         source={"em_us": "EMG00003722"}, release="次月中旬（Census）", keywords=["核心零售", "美国消费"], theory="剔除汽车后的消费动能"),
    dict(id="us_umcsent", name="密歇根消费者信心（初值）", short="密歇根信心", l1="增长", l2="消费", unit="", freq="M", role="ref", kind="index",
         source={"fred": "UMCSENT", "transform": "level", "em_us": "EMG00002846"}, release="当月中旬初值/月末终值", keywords=["消费者信心", "密歇根", "通胀预期"], theory="汽油价格、股市、通胀预期、政治周期"),
    dict(id="us_conf_board", name="咨商会消费者信心指数", short="咨商会信心", l1="增长", l2="消费", unit="", freq="M", role="ref", kind="index",
         source={"em_us": "EMG00002847"}, release="当月最后一个周二（Conference Board）", keywords=["消费者信心", "咨商会", "就业预期"], theory="就业市场感受、股市、汽油价格；与密歇根指数互补"),
    dict(id="us_durable_mom", name="美国耐用品订单环比", short="耐用品订单", l1="增长", l2="投资", unit="%", freq="M", role="nowcast", kind="mom",
         source={"fred": "DGORDER", "transform": "mom", "em_us": "EMG00342254"}, release="次月下旬（Census）", keywords=["耐用品", "订单", "波音", "资本开支"], theory="飞机订单（波音）主导波动，核心资本品反映投资"),
    dict(id="us_core_durable_mom", name="美国核心耐用品订单环比（除运输）", short="核心耐用品", l1="增长", l2="投资", unit="%", freq="M", role="persist", kind="mom",
         source={"em_us": "EMG01421900"}, release="次月下旬（Census）", keywords=["核心耐用品", "资本开支", "设备投资"], theory="企业资本开支周期"),
    dict(id="us_ism_mfg", name="美国ISM制造业PMI", short="ISM制造业", l1="增长", l2="生产景气", unit="", freq="M", role="nowcast", kind="index",
         source={"em_us": "EMG00002790"}, release="次月第一个工作日（ISM）",
         keywords=["ISM", "美国制造业", "PMI", "美国经济", "关税", "新订单"], theory="新订单-库存差、地区联储制造业调查（Empire/Philly）、Markit PMI、关税与补库周期"),
    dict(id="us_ism_nonmfg", name="美国ISM非制造业PMI", short="ISM非制造业", l1="增长", l2="生产景气", unit="", freq="M", role="persist", kind="index",
         source={"em_us": "EMG00002791"}, release="次月第三个工作日（ISM）", keywords=["ISM", "服务业", "PMI", "美国经济"], theory="服务消费、就业分项与新订单"),
    dict(id="us_indpro_yoy", name="美国工业产出同比", short="美工业产出", l1="增长", l2="生产景气", unit="%", freq="M", role="persist", kind="yoy",
         source={"fred": "INDPRO", "transform": "yoy"}, release="次月中旬（美联储）", keywords=["美国制造业", "ISM", "工业产出"], theory="ISM 生产分项、汽车产量、公用事业（天气）"),
    dict(id="us_tcu", name="美国产能利用率", short="产能利用率", l1="增长", l2="生产景气", unit="%", freq="M", role="persist", kind="rate",
         source={"fred": "TCU", "transform": "level"}, release="次月中旬（美联储）", keywords=["产能利用率", "美国制造业"], theory="与工业产出同源"),
    # ================= 通胀 =================
    dict(id="us_cpi_yoy", name="美国CPI同比", short="美CPI同比", l1="通胀", l2="消费价格", unit="%", freq="M", role="nowcast", kind="yoy",
         source={"fred": "CPIAUCSL", "transform": "yoy", "em_us": "EMG00000733"}, release="次月 10–15 日（BLS）",
         keywords=["美国CPI", "美国通胀", "美联储", "通胀", "油价", "关税", "美国"], theory="能源与食品价格、住房租金（滞后）、核心商品（关税传导）、基数效应；克利夫兰联储 nowcast：核心 = 过去 12 个月均值持续性，汽油 = 当前油价与汽油价格"),
    dict(id="us_cpi_mom", name="美国CPI环比", short="美CPI环比", l1="通胀", l2="消费价格", unit="%", freq="M", role="nowcast", kind="mom",
         source={"fred": "CPIAUCSL", "transform": "mom", "em_us": "EMG00000770"}, release="次月 10–15 日（BLS）",
         keywords=["美国CPI", "美国通胀", "美联储", "通胀", "油价", "关税"], theory="汽油价格当月变动、住房 OER、二手车、机票等波动分项"),
    dict(id="us_core_cpi_yoy", name="美国核心CPI同比", short="美核心CPI", l1="通胀", l2="消费价格", unit="%", freq="M", role="nowcast", kind="yoy",
         source={"fred": "CPILFESL", "transform": "yoy", "em_us": "EMG00000746"}, release="次月 10–15 日（BLS）",
         keywords=["核心CPI", "美国通胀", "美联储", "住房", "关税"], theory="住房租金、核心服务（工资驱动）、核心商品（关税、供应链）"),
    dict(id="us_pce_yoy", name="美国PCE物价同比", short="美PCE", l1="通胀", l2="消费价格", unit="%", freq="M", role="persist", kind="yoy",
         source={"fred": "PCEPI", "transform": "yoy"}, release="次月底（BEA）", keywords=["PCE", "美联储", "通胀"], theory="与 CPI 高度相关，权重不同（医疗更高、住房更低）"),
    dict(id="us_core_pce_yoy", name="美国核心PCE同比", short="美核心PCE", l1="通胀", l2="消费价格", unit="%", freq="M", role="persist", kind="yoy",
         source={"fred": "PCEPILFE", "transform": "yoy"}, release="次月底（BEA）", keywords=["核心PCE", "美联储", "通胀"], theory="美联储目标口径，可由 CPI/PPI 分项推算"),
    dict(id="us_ppi_mom", name="美国PPI环比", short="美PPI环比", l1="通胀", l2="工业价格", unit="%", freq="M", role="persist", kind="mom",
         source={"em_us": "EMG00177897"}, release="次月中旬（BLS）", keywords=["PPI", "美国通胀", "生产者价格", "关税"], theory="能源与食品批发价、贸易服务利润率、关税向上游传导"),
    dict(id="us_core_ppi_yoy", name="美国核心PPI同比", short="美核心PPI", l1="通胀", l2="工业价格", unit="%", freq="M", role="persist", kind="yoy",
         source={"em_us": "EMG00177799"}, release="次月中旬（BLS）", keywords=["核心PPI", "PPI", "美国通胀"], theory="剔除食品能源后的上游价格，领先核心商品 CPI"),
    dict(id="us_ppi_yoy", name="美国PPI同比", short="美PPI", l1="通胀", l2="工业价格", unit="%", freq="M", role="persist", kind="yoy",
         source={"fred": "PPIFIS", "transform": "yoy"}, release="次月中旬（BLS）", keywords=["PPI", "美国通胀"], theory="能源、贸易服务利润率、关税"),
    # ================= 就业 =================
    dict(id="us_nfp", name="美国非农新增就业", short="非农新增", l1="就业", l2="就业", unit="千人", freq="M", role="nowcast", kind="flow",
         source={"fred": "PAYEMS", "transform": "diff", "em_us": "EMG00152118"}, release="次月第一个周五（BLS）",
         keywords=["非农", "美国就业", "失业率", "美联储", "劳动力市场", "裁员"], theory="ADP/初请失业金、JOLTS 职位空缺、企业调查、政府就业、移民与罢工等一次性因素"),
    dict(id="us_unrate", name="美国失业率", short="美失业率", l1="就业", l2="就业", unit="%", freq="M", role="nowcast", kind="rate",
         source={"fred": "UNRATE", "transform": "level", "em_us": "EMG00001039"}, release="次月第一个周五（BLS）",
         keywords=["失业率", "非农", "美国就业", "劳动力"], theory="劳动参与率、持续申领失业金人数、家庭调查噪声；萨姆规则：3 个月均值较 12 个月低点上升 0.5pct 为衰退信号"),
    dict(id="us_wage_yoy", name="美国时薪同比", short="美时薪", l1="就业", l2="工资", unit="%", freq="M", role="persist", kind="yoy",
         source={"fred": "AHETPI", "transform": "yoy"}, release="次月第一个周五（BLS）", keywords=["工资", "薪资", "非农"], theory="劳动力供需、最低工资调整、构成效应"),
    dict(id="us_claims", name="美国初请失业金（月均，千人）", short="初请失业金", l1="就业", l2="就业", unit="千人", freq="M", role="ref", kind="level",
         source={"fred": "ICSA", "transform": "level", "agg": "mean", "scale": 0.001}, release="每周四（劳工部）", keywords=["初请", "失业金", "裁员"], theory="裁员节奏的高频先行指标"),
    dict(id="us_jolts", name="美国职位空缺（JOLTS，千人）", short="职位空缺", l1="就业", l2="就业", unit="千人", freq="M", role="persist", kind="level",
         source={"fred": "JTSJOL", "transform": "level"}, release="隔月初（BLS）", keywords=["职位空缺", "JOLTS", "美国就业"], theory="劳动力需求，领先非农"),
    # ================= 外贸与外部 =================
    dict(id="us_trade_balance", name="美国商品和服务贸易差额", short="美贸易差额", l1="外贸与外部", l2="进出口", unit="亿美元", freq="M", role="persist", kind="flow",
         source={"fred": "BOPGSTB", "transform": "level", "scale": 0.01, "em_us": "EMG00000700", "em_scale": 0.01}, release="隔月初（Census/BEA）", keywords=["美国贸易", "逆差", "关税", "进口"], theory="关税前抢进口、美元、能源出口"),
    # ================= 金融 =================
    dict(id="us_fedfunds", name="联邦基金利率（目标上限）", short="联邦基金利率", l1="金融", l2="政策", unit="%", freq="M", role="ref", kind="rate",
         source={"fred": "FEDFUNDS", "transform": "level", "em_us": "EMG00342250"}, release="FOMC 会议后（美联储）", keywords=["美联储", "降息", "加息", "FOMC", "利率"], theory="FOMC 决议与点阵图、通胀与就业双目标"),
    dict(id="us10y", name="美国10年期国债收益率（月均）", short="美债10Y", l1="金融", l2="利率", unit="%", freq="M", role="ref", kind="rate",
         source={"yield": "us10y"}, release="每日", keywords=["美债", "收益率", "美联储", "期限溢价"], theory="政策利率预期、期限溢价、财政赤字与发债"),
    dict(id="us2y", name="美国2年期国债收益率（月均）", short="美债2Y", l1="金融", l2="利率", unit="%", freq="M", role="ref", kind="rate",
         source={"yield": "us2y"}, release="每日", keywords=["美债", "2年期", "加息预期", "降息预期"], theory="未来两年政策利率路径的市场定价"),
    dict(id="us_term_spread", name="美债10Y−2Y期限利差", short="美债期限利差", l1="金融", l2="利率", unit="pct", freq="M", role="ref", kind="rate",
         source={"derived": ["us10y", "-", "us2y"]}, release="每日", keywords=["利差", "倒挂", "衰退", "美债"], theory="倒挂是衰退领先指标（平均领先 12–18 个月）"),
    # ================= 地产 =================
    dict(id="us_houst", name="美国新屋开工（千套，折年）", short="新屋开工", l1="地产", l2="供给", unit="千套", freq="M", role="nowcast", kind="level",
         source={"fred": "HOUST", "transform": "level", "em_us": "EMG00003224"}, release="次月中旬（Census）", keywords=["美国地产", "新屋开工", "房贷利率", "住房"], theory="房贷利率、建筑许可（领先）、天气、建筑商信心 NAHB"),
    dict(id="us_permit", name="美国建筑许可（千套，折年）", short="建筑许可", l1="地产", l2="供给", unit="千套", freq="M", role="persist", kind="level",
         source={"fred": "PERMIT", "transform": "level"}, release="次月中旬（Census）", keywords=["建筑许可", "美国地产", "住房"], theory="领先新屋开工 1–2 个月"),
    dict(id="us_existing_sales", name="美国成屋销售（万套，折年）", short="成屋销售", l1="地产", l2="销售", unit="万套", freq="M", role="persist", kind="level",
         source={"em_us": "EMG00003078"}, release="次月下旬（NAR）", keywords=["成屋销售", "美国地产", "房贷利率", "住房"], theory="房贷利率、待售库存、房价可负担性；领先指标为未决房屋销售"),
    dict(id="us_pending_home", name="美国未决房屋销售环比", short="未决房屋销售", l1="地产", l2="销售", unit="%", freq="M", role="persist", kind="mom",
         source={"em_us": "EMG00342249"}, release="次月下旬（NAR）", keywords=["未决房屋", "成屋", "美国地产", "房贷利率"], theory="签约领先成屋销售 1–2 个月，对房贷利率敏感"),
]

INDICATORS = CN + US
for _i in CN:
    _i["country"] = "CN"
for _i in US:
    _i["country"] = "US"
for _i in INDICATORS:
    _i.setdefault("spring", False); _i.setdefault("seasonal", False); _i.setdefault("jan_merge", False)
    _i.setdefault("paper", None); _i.setdefault("force_d", None); _i.setdefault("kind", "level")
    _i.setdefault("agg", {"yoy": "mean", "mom": "mean", "index": "mean", "rate": "mean", "level": "mean", "flow": "sum", "stock": "last"}[_i["kind"]])
    _i["group"] = _i["l1"]  # 兼容旧字段

BY_ID = {x["id"]: x for x in INDICATORS}
L1_ORDER = ["增长", "通胀", "就业", "外贸与外部", "金融", "财政", "地产", "景气"]
L2_ORDER = {"增长": ["总量", "生产", "生产景气", "消费", "投资"], "通胀": ["消费价格", "工业价格", "上游价格", "价格结构"], "就业": ["就业", "工资"],
            "外贸与外部": ["进出口", "储备", "资本流动"], "金融": ["货币", "信贷", "政策", "利率"], "财政": ["收入"], "地产": ["房价", "供给", "销售"], "景气": ["PMI"]}
GROUPS_ORDER = L1_ORDER


def hierarchy(country=None):
    """[{l1, groups:[{l2, ids:[...]}]}]，按固定顺序。"""
    out = []
    for l1 in L1_ORDER:
        l2s = {}
        for i in INDICATORS:
            if i["l1"] != l1 or (country and i["country"] != country):
                continue
            l2s.setdefault(i["l2"], []).append(i["id"])
        if not l2s:
            continue
        order = L2_ORDER.get(l1, [])
        keys = [k for k in order if k in l2s] + [k for k in l2s if k not in order]
        out.append({"l1": l1, "groups": [{"l2": k, "ids": l2s[k]} for k in keys]})
    return out


LLM_MODES = {
    "title": "研报标题 + 数据研判（推荐）",
    "chunk": "研报正文片段 + 数据研判",
    "title_ar": "研报标题 + 自回归参考",
    "data": "仅数据研判（不读研报）",
}

# 东方财富表 → 快照字段（datasource 按此抓取）
EM_FIELDS = {
    "RPT_ECONOMY_CPI": ["NATIONAL_SAME", "NATIONAL_SEQUENTIAL", "CITY_SAME", "RURAL_SAME"],
    "RPT_ECONOMY_PPI": ["BASE_SAME", "BASE_ACCUMULATE"],
    "RPT_ECONOMY_TOTAL_RETAIL": ["RETAIL_TOTAL", "RETAIL_TOTAL_SAME", "RETAIL_ACCUMULATE_SAME"],
    "RPT_ECONOMY_INDUS_GROW": ["BASE_SAME", "BASE_ACCUMULATE"],
    "RPT_ECONOMY_RMB_LOAN": ["RMB_LOAN", "LOAN_ACCUMULATE_SAME"],
    "RPT_ECONOMY_CUSTOMS": ["EXIT_BASE", "IMPORT_BASE", "EXIT_BASE_SAME", "IMPORT_BASE_SAME", "EXIT_ACCUMULATE_SAME", "TRADE_BAL_100M_USD"],
    "RPT_ECONOMY_CURRENCY_SUPPLY": ["BASIC_CURRENCY_SAME", "CURRENCY_SAME", "FREE_CASH_SAME"],
    "RPT_ECONOMY_PMI": ["MAKE_INDEX", "NMAKE_INDEX"],
    "RPT_ECONOMY_GDP": ["SUM_SAME", "FIRST_SAME", "SECOND_SAME", "THIRD_SAME", "DOMESTICL_PRODUCT_BASE"],
    "RPT_ECONOMY_GOLD_CURRENCY": ["FOREX", "GOLD_RESERVES"],
    "RPT_ECONOMY_INCOME": ["BASE_SAME", "ACCUMULATE_SAME"],
    "RPT_ECONOMY_BOOM_INDEX": ["BOOM_INDEX", "FAITH_INDEX"],
    "RPT_ECONOMY_ASSET_INVEST": ["BASE", "BASE_SAME", "BASE_ACCUMULATE"],
    "RPT_ECONOMY_GOODS_INDEX": ["BASE_SAME", "FARM_BASE_SAME", "MINERAL_BASE_SAME", "ENERGY_BASE_SAME"],
    "RPT_ECONOMY_FAITH_INDEX": ["CONSUMERS_FAITH_INDEX", "CONSUMERS_EXPECT_INDEX", "CONSUMERS_ASTIS_INDEX"],
    "RPT_ECONOMY_FOREX_DEPOSIT": ["BASE"],
    "RPT_ECONOMY_TAX": ["TAX_INCOME_SAME"],
    "RPT_ECONOMY_FDI_NEW": ["ACTUAL_FOREIGN"],
}
# 事件型表（单独抓取）
EM_STEP_TABLES = {"RPT_ECONOMY_DEPOSIT_RESERVE": ("INTEREST_RATE_BA", "TRADE_DATE_NEW")}
# 70 城房价字段
EM_HOUSE_FIELDS = ["FIRST_COMHOUSE_SAME", "SECOND_HOUSE_SAME", "FIRST_COMHOUSE_SEQUENTIAL"]
