import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN=os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS = [
    int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x
]
# Super adminlar (hech qachon o'chirilmaydi; .env dan). Oddiy adminlar DB da (admins jadvali).
SUPER_ADMIN_IDS = ADMIN_IDS

DB_PATH = os.path.join(os.path.dirname(__file__), "reklama.db")
LOG_PATH = os.path.join(os.path.dirname(__file__), "logs", "bot.log")
