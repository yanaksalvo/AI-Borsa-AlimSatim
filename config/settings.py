"""
Uygulama ayarları. API anahtarı .env veya ortam değişkeninden okunur.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Proje kökü
ROOT = Path(__file__).resolve().parent.parent

# OpenRouter
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE = "https://openrouter.ai/api/v1"
OPENROUTER_MODELS = [
    "anthropic/claude-3.5-sonnet",
    "openai/gpt-4-turbo",
    "meta-llama/llama-3.1-70b-instruct",
]
DEFAULT_AI_MODEL = "anthropic/claude-3.5-sonnet"

# AI limitler
AI_RATE_LIMIT_PER_MINUTE = 10
AI_CACHE_TTL_SECONDS = 300  # 5 dakika

# WebSocket
WS_RECONNECT_DELAY = 5
WS_HEARTBEAT_INTERVAL = 30
WS_QUEUE_MAX_SIZE = 1000

# Veritabanı / veri klasörü
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
JOURNAL_DB = DATA_DIR / "trading_journal.db"
SETTINGS_JSON = DATA_DIR / "settings.json"
