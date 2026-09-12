"""运行配置：环境变量优先，其次项目根目录 .env。"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _load_dotenv():
    p = ROOT / ".env"
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()

# ---- 大模型 ----
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "").strip()
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
DEEPSEEK_MODELS = [m.strip() for m in os.environ.get("DEEPSEEK_MODELS", "deepseek-v4-pro,deepseek-flash").split(",") if m.strip()]
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
ANTHROPIC_BASE_URL = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com").rstrip("/")
ANTHROPIC_MODELS = [m.strip() for m in os.environ.get("ANTHROPIC_MODELS", "").split(",") if m.strip()]  # 留空则自动发现
DEFAULT_MODEL = os.environ.get("DEEPSEEK_MODEL", os.environ.get("DEFAULT_MODEL", "deepseek-v4-pro")).strip()
LLM_TIMEOUT = float(os.environ.get("LLM_TIMEOUT", "300"))
LLM_MAX_TOKENS = int(os.environ.get("LLM_MAX_TOKENS", "8000"))
LLM_CONCURRENCY = int(os.environ.get("LLM_CONCURRENCY", "4"))
AUTO_PREDICT = os.environ.get("AUTO_PREDICT", "1") == "1"   # 新数据到达后自动对待测指标运行 AI 预测

# ---- 访问控制 ----
ACCESS_PASSWORD = os.environ.get("ACCESS_PASSWORD", "").strip()

# ---- 数据 ----
DATA_DIR = Path(os.environ.get("DATA_DIR", str(ROOT / "var")))
DATA_DIR.mkdir(parents=True, exist_ok=True)
FRED_API_KEY = os.environ.get("FRED_API_KEY", "").strip()   # 可选；不填走 fredgraph.csv 公共接口
BACKTEST_START = os.environ.get("BACKTEST_START", "2014-01")
LLM_EARLIEST = os.environ.get("LLM_EARLIEST", "2017-01")
LEAK_SPLIT = os.environ.get("LEAK_SPLIT", "2025-01")
REFRESH_HOURS = float(os.environ.get("REFRESH_HOURS", "1"))
HTTP_TIMEOUT = float(os.environ.get("HTTP_TIMEOUT", "25"))
OFFLINE = os.environ.get("OFFLINE", "0") == "1"
