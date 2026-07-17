import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_API_ID = int(os.getenv("TELEGRAM_API_ID"))
TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH")
TELEGRAM_SESSION_STRING = os.getenv("TELEGRAM_SESSION_STRING")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
MANAGER_USERNAME = os.getenv("MANAGER_USERNAME", "tutor_zelimhan")
GOOGLE_SHEETS_CREDS = os.getenv("GOOGLE_SHEETS_CREDS", "google_creds.json")
ZADANIE_PATH = os.getenv("ZADANIE_PATH", "zadanie.jpg")
DB_PATH = os.getenv("DB_PATH", "candidates.db")
