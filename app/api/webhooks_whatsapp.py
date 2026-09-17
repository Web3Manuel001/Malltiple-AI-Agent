import os
import json
import logging
import requests
from fastapi import APIRouter, Request, Response, BackgroundTasks
from app.core.config import settings
from app.core.database import SessionLocal
from app.models.audit import AuditLog
from app.services.customer_service import get_or_create_customer
from app.services.brain import execute_turn

router = APIRouter()
logger = logging.getLogger("whatsapp_webhook")

WHATSAPP_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "malltiple_secure_verify_2026")

WHATSAPP_SESSIONS = {}

def send_whatsapp_message(to_phone: str, message_text: str):
    """Sends a text message back to customer via Meta Cloud API."""
    if not WHATSAPP_TOKEN or not WHATSAPP_PHONE_NUMBER_ID:
        logger.error("WhatsApp credentials missing in .env")
        return

    url = f"https://graph.facebook.com/v20.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to_phone,
        "type": "text",
        "text": {"body": message_text}
    }
    try:
        requests.post(url, headers=headers, json=payload, timeout=10)
    except Exception as e:
        logger.error(f"Failed to send WhatsApp message: {e}")

async def process_incoming_whatsapp(from_phone: str, text: str, user_name: str):
    """Processes message through our central AI Brain."""
    db = SessionLocal()
    db.add(AuditLog(user_id=from_phone, user_name=user_name, sender="WhatsApp Customer", message=text))
    db.commit()

    # Automatically identify customer by their real WhatsApp phone number!
    customer_profile = get_or_create_customer(telegram_id=f"wa_{from_phone}", fallback_name=user_name)
    if not customer_profile.get("phone"):
        customer_profile["phone"] = from_phone

    session = WHATSAPP_SESSIONS.setdefault(from_phone, {"history": []})
    session["history"].append({"role": "user", "content": text})

    reply, was_escalated, reason = execute_turn(from_phone, customer_profile, session["history"])

    if reply:
        session["history"].append({"role": "assistant", "content": reply})
        send_whatsapp_message(from_phone, reply)
        db.add(AuditLog(user_id=from_phone, user_name=user_name, sender="Malltiple AI", message=reply))
        db.commit()

    if was_escalated:
        alert_msg = f"🚨 *WHATSAPP ESCALATION:*\n• Customer: {user_name} (+{from_phone})\n• Reason: {reason}"
        send_whatsapp_message(from_phone, "⏳ I have flagged your request for our customer care team. An agent will follow up with you shortly.")
        logger.info(alert_msg)

    db.close()

# 1. Verification Endpoint for Meta Webhook Setup
@router.get("/api/whatsapp-webhook")
async def verify_whatsapp_webhook(request: Request):
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode == "subscribe" and token == WHATSAPP_VERIFY_TOKEN:
        logger.info("✅ WhatsApp Webhook verified successfully!")
        return Response(content=challenge, media_type="text/plain")
    return Response(content="Verification token mismatch", status_code=403)

# 2. Incoming Messages Endpoint
@router.post("/api/whatsapp-webhook")
async def handle_whatsapp_incoming(request: Request, background_tasks: BackgroundTasks):
    try:
        body = await request.json()
        entry = body.get("entry", [])[0]
        changes = entry.get("changes", [])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [])

        if not messages:
            return {"status": "ignored_or_status_update"}

        msg = messages[0]
        from_phone = msg.get("from") # E.g. "2348012345678"
        user_name = value.get("contacts", [{}])[0].get("profile", {}).get("name", "WhatsApp Customer")

        if msg.get("type") == "text":
            text = msg.get("text", {}).get("body", "").strip()
            # Process in background so Meta gets instant 200 OK
            background_tasks.add_task(process_incoming_whatsapp, from_phone, text, user_name)

        return {"status": "processing"}
    except Exception as e:
        logger.error(f"Error handling WhatsApp webhook: {e}")
        return {"status": "error"}
