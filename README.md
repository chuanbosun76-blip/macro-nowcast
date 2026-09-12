# 观数 · 宏观预测平台 v2

中国（国家统计局 / 海关 / 央行口径，经东方财富数据中心）22 项 + 美国（FRED）23 项宏观指标，10 年+ 历史，每小时自动更新。
对每个待测指标同时给出 沿用上期 / SARIMAX（春节外生变量）/ AI 研判（DeepSeek 或 Claude：读研报 + 数据 + 统计模型，输出数值、区间、驱动因素、传导机制、证据、风险）三种预测并按回测择优；所有预测可追溯到具体研报（直达链接）与 Prompt。

## 部署（Render）
1. 代码推到 GitHub 仓库 → Render New → Blueprint（或 Web Service，Docker）。
2. 环境变量：`DEEPSEEK_API_KEY`、`ANTHROPIC_API_KEY`（可选，接 Claude）、`ACCESS_PASSWORD`（可选，公网口令）、`DATA_DIR=/data`（挂 1GB 磁盘后档案持久保存）。
3. 可选：`IFIND_REFRESH_TOKEN` + `IFIND_EDB_MAP`（iFinD EDB 覆盖中国数据）、`FRED_API_KEY`（不填走公共 CSV 接口）。

本地运行：`pip install -r requirements.txt && python main.py` → http://localhost:8000
