import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    STORE_URL: str = os.getenv("WOO_STORE_URL", "https://malltiple.com.ng")
    CONSUMER_KEY: str = os.getenv("WOO_CONSUMER_KEY", "")
    CONSUMER_SECRET: str = os.getenv("WOO_CONSUMER_SECRET", "")
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    ADMIN_CHAT_ID: str = os.getenv("ADMIN_CHAT_ID", "")
    DEEPGRAM_API_KEY: str = os.getenv("DEEPGRAM_API_KEY", "")
    YARNGPT_API_KEY: str = os.getenv("YARNGPT_API_KEY", "")
    YARNGPT_VOICE: str = os.getenv("YARNGPT_VOICE", "Idera")
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./malltiple.db")

settings = Settings()
