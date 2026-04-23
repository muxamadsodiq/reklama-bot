import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS = [
    int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x
]
# Root super adminlar (.env dan, o'chirilmaydi).
ROOT_SUPER_ADMIN_IDS = set(ADMIN_IDS)
# Aktiv super adminlar to'plami (root + DB'dan yuklanadi startup'da).
# Barcha joylarda `uid in SUPER_ADMIN_IDS` ishlatilgani uchun MUTABLE set.
SUPER_ADMIN_IDS = set(ROOT_SUPER_ADMIN_IDS)

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()

DB_PATH = os.path.join(os.path.dirname(__file__), "reklama.db")
LOG_PATH = os.path.join(os.path.dirname(__file__), "logs", "bot.log")
