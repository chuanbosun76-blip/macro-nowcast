# 观数 · 宏观实时预测研究台（部署版）

复现中金《量化配置系列（18）》：沿用上期 → SARIMAX（春节外生变量）→ DeepSeek 读研报标题。
数据：东方财富数据中心 + 研报中心（每小时轮询，自动更新）；模型：DeepSeek API（服务端调用）。

部署：Render → New → Blueprint → 选择本仓库 → 填写 DEEPSEEK_API_KEY 与 ACCESS_PASSWORD。
本地运行：`pip install -r requirements.txt && python main.py`
