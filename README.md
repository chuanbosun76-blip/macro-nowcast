# 观数 · 宏观预测平台 v3

面向宏观 / 策略分析师的**指标实时预测（nowcasting）+ 依据生成 + 资产传导**工作台。

## 覆盖
- **中国 56 项**：增长（GDP 累计/当季估算/名义/二三产、工业增加值、社零 3 口径、固投 3 口径、消费者信心 3 项、企业景气）、通胀（CPI 4、PPI 2、CGPI 4、PPI−CPI）、外贸与外部（进出口同比/累计/金额、贸易差额、外储、黄金储备、FDI）、金融（新增贷款、贷款累计同比、存款、M0/M1/M2、M1−M2、准备金率、中债 2Y/10Y/期限利差）、财政（收入当月/累计、税收）、地产（70 城新房/二手同比、新房环比）、景气（制造业/非制造业 PMI）。
- **美国 24 项**：GDP、零售、耐用品、ISM 制造/非制造、消费者信心、CPI/核心 CPI/PPI、非农、失业率、贸易差额、联邦基金利率、美债 2Y/10Y/期限利差、新屋开工、成屋销售、成屋签约。
- **市场月度库**：A 股宽基（沪深300/上证/创业板/中证500/中证1000/科创50）、恒生、标普/纳指/道指、日经、美元指数、USDCNH、黄金、原油，中美 2Y/10Y/30Y 收益率，2005 年起。

## 五种预测方法
| 方法 | 公式 | 用途 |
|---|---|---|
| 沿用上期 | ŷ=y(t−1) | 随机游走基准 |
| SARIMAX | φ(L)Φ(Lˢ)(1−L)^d y = c+βx+θ(L)Θ(Lˢ)ε | 时序结构 + 春节外生变量，月度 s=12 / 季度 s=4 |
| 多因子岭回归 | β̂=(Z′Z+λI)⁻¹Z′(y−ȳ)，λ=1 | 横截面信息，输出每个因子贡献 β·z |
| 桥方程 | y_q=α+Σβ·z̄_q（季度至今均值） | GDPNow 思路，季度指标的月度追踪 |
| AI 研判 | 研报 + 数据 + 模型参考 → 结构化 JSON | 文本信息与政策拐点 |
| 组合 | w ∝ 1/RMSE²（Bates–Granger 1969） | 稳健性核对 |

## 依据引擎
每个指标自动生成**结论先行 + ≥5 条量化支撑**：基准与惯性、时序模型与季节性、因子贡献分解、领先信号扫描、基数与翘尾、历史相似期、桥方程追踪、组合与不确定性、跨频率含义；再给风险情景（±1.28σ/±1.96σ，σ 用 1.4826×MAD 稳健估计）与市场含义（预期差 z × 事件回归 β）。内嵌 GDPNow / 纽约联储 DFM / 克利夫兰联储 / MIDAS 组合 / 信达高频 / 中金论证结构 / IMF 年度口径七套方法论。

## 频率体系
月度 / 季度 / 年度三个口径：月度→季/年按 kind 聚合（同比与指数取期内均值、流量取期内合计、存量取期末值）；季度 GDP→月度用桥方程；当期追踪 = 已公布期实际值 + 待公布期模型预测 + 剩余期外推（季节漂移 / 同比比例 / 近 5 年同月均值），并显示已实现占比。

## 导出
Word / PPT / Excel / Markdown，零依赖 OOXML 写入（`office.py`，无 lxml/Pillow）。全库 Excel 含 6 张表：预测总览、月度数据、季度数据、年度数据、回测评分、市场月度库。

## 部署（Render）
1. 代码推到 GitHub 仓库 → Render New → Blueprint（或 Web Service，Docker）。
2. 环境变量：`DEEPSEEK_API_KEY`、`ANTHROPIC_API_KEY`（可选）、`ACCESS_PASSWORD`（可选，公网口令）、`DATA_DIR=/data`。
3. 免费版无磁盘时设 `DATA_DIR=/tmp/data`；重启后档案会清空，内置快照与 `ar_seed.json` 保证秒级冷启动。

本地运行：`pip install -r requirements.txt && python main.py` → http://localhost:8000

## 主要 API
`/api/status` `/api/meta` `/api/hierarchy` `/api/overview` `/api/board` `/api/table?freq=M|Q|A`
`/api/series/<id>` `/api/views/<id>` `/api/evidence/<id>` `/api/transmission/<id>` `/api/methodology`
`/api/search?q=` `/api/calendar` `/api/backtest` `/api/runs` `/api/sync`（POST，一键更新）
`/api/export`（POST，kind=docx|xlsx|pptx|md）`/api/ai/report`（POST）`/api/nowcast`（POST）`/api/ask`（POST）
