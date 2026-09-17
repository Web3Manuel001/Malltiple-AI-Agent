import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.core.config import settings
from app.core.database import engine, Base
from app.api.dashboard import router as dashboard_router
from app.api.webhooks_telegram import router as telegram_router, tg_app
from app.api.webhooks_whatsapp import router as whatsapp_router

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)

# Create all tables on boot
Base.metadata.create_all(bind=engine)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize Telegram Bot & Set Webhook
    await tg_app.initialize()
    await tg_app.start()

    webhook_url = f"{settings.BASE_URL}/api/telegram-webhook"
    print(f"🔗 Registering Telegram Webhook to: {webhook_url}")
    await tg_app.bot.set_webhook(url=webhook_url)

    print("🚀 Malltiple Enterprise Engine Online!")
    yield

    # Shutdown: Cleanly remove webhook
    print("🛑 Shutting down Telegram Webhook...")
    await tg_app.stop()
    await tg_app.shutdown()

app = FastAPI(title="Malltiple Enterprise AI Engine", lifespan=lifespan)

@app.get("/health")
def health_check():
    return {"status": "healthy", "service": "Malltiple Modular Engine"}

# Mount Domain Routers
app.include_router(dashboard_router) #Dashboard router is included for handling dashboard-related endpoints
app.include_router(telegram_router) #Telegram router is included for handling Telegram webhooks and interactions
app.include_router(whatsapp_router) #Whatsapp router is included for handling WhatsApp webhooks and interactions