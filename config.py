import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))
DATABASE_PATH = os.getenv("DATABASE_PATH", "karaoke.db")

ROLE_NONE = 0
ROLE_ADMIN = 1
ROLE_KJ = 2
ROLE_VIP = 3
ROLE_USER = 4
ROLE_NO_TABLE = 5

ADMIN_COMMISSION = 0.05

DEFAULT_CURRENCY = "MDL"

MAX_GROUP_SIZE = 4
MAX_ACTIVE_SONGS_PER_USER = 2
