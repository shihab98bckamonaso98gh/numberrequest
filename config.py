import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", 0))
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", 0))

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is not set")
if not ADMIN_CHAT_ID:
    raise ValueError("ADMIN_CHAT_ID is not set")
if not ADMIN_USER_ID:
    raise ValueError("ADMIN_USER_ID is not set")