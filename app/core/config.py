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
    WHATSAPP_ACCESS_TOKEN: str = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
    WHATSAPP_PHONE_NUMBER_ID: str = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
    WHATSAPP_VERIFY_TOKEN: str = os.getenv("WHATSAPP_VERIFY_TOKEN", "malltiple_secure_verify_2026")

    # Render automatically sets RENDER_EXTERNAL_URL (e.g. https://malltiple-ai-agent.onrender.com)
    BASE_URL: str = os.getenv("RENDER_EXTERNAL_URL", "https://malltiple-ai-agent.onrender.com")

    # Executive switch for direct checkout
    ALLOW_DIRECT_CHECKOUT: bool = os.getenv("ALLOW_DIRECT_CHECKOUT", "false").lower() == "true"

settings = Settings()
