"""运行配置：优先读取环境变量，其次读取项目根目录 .env（不依赖 python-dotenv）。"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _load_dotenv():
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        os.environ.setdefault(k, v)


_load_dotenv()

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "").strip()
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
# deepseek-v4-pro：推理模型（对应原文 DeepSeek-R1 的角色）；deepseek-flash：快速版，适合大批量回测
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro").strip()
DEEPSEEK_MODELS = [m.strip() for m in os.environ.get("DEEPSEEK_MODELS", "deepseek-v4-pro,deepseek-flash").split(",") if m.strip()]
DEEPSEEK_TIMEOUT = float(os.environ.get("DEEPSEEK_TIMEOUT", "300"))
DEEPSEEK_MAX_TOKENS = int(os.environ.get("DEEPSEEK_MAX_TOKENS", "8000"))
LLM_CONCURRENCY = int(os.environ.get("LLM_CONCURRENCY", "4"))

# 公网部署时务必设置：运行 DeepSeek / 刷新数据等会产生费用的操作需要此口令
ACCESS_PASSWORD = os.environ.get("ACCESS_PASSWORD", "").strip()

DATA_DIR = Path(os.environ.get("DATA_DIR", str(ROOT / "var")))
DATA_DIR.mkdir(parents=True, exist_ok=True)

# 回测区间（原文：2014/1/1–2025/5/30；此处默认起点相同，终点为最新可得月份）
BACKTEST_START = os.environ.get("BACKTEST_START", "2014-01")
# 东方财富研报库宏观/策略报告约自 2017 年起可得，LLM 回测最早起点
LLM_EARLIEST = os.environ.get("LLM_EARLIEST", "2017-01")
# 预训练泄漏检验切分点（原文 DeepSeek-R1 预训练截至 2025 年 1 月）
LEAK_SPLIT = os.environ.get("LEAK_SPLIT", "2025-01")
# 数据自动刷新间隔（小时）
REFRESH_HOURS = float(os.environ.get("REFRESH_HOURS", "1"))  # 数据源轮询间隔：每小时检查一次东方财富是否有新数据
HTTP_TIMEOUT = float(os.environ.get("HTTP_TIMEOUT", "20"))
OFFLINE = os.environ.get("OFFLINE", "0") == "1"  # 测试用：不访问外网，只用内置快照
