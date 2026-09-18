import html
import asyncio
import logging
from fastapi import APIRouter, Form, Response
from app.core.config import settings
from app.core.database import SessionLocal
from app.models.audit import AuditLog
from app.services.customer_service import get_or_create_customer
from app.services.brain import execute_turn

router = APIRouter()
logger = logging.getLogger("whatsapp_webhook")

WHATSAPP_SESSIONS = {}

@router.post("/api/whatsapp-webhook")
async def handle_twilio_whatsapp(
    From: str = Form(...),
    Body: str = Form(""),
    ProfileName: str = Form("WhatsApp Customer")
):
    clean_phone = From.replace("whatsapp:", "").replace("+", "").strip()
    user_text = Body.strip()

    if not user_text:
        return Response(content="<Response></Response>", media_type="application/xml")

    db = SessionLocal()
    db.add(AuditLog(user_id=clean_phone, user_name=ProfileName, sender="WhatsApp Customer", message=user_text))
    db.commit()

    customer_profile = get_or_create_customer(telegram_id=f"wa_{clean_phone}", fallback_name=ProfileName)
    if not customer_profile.get("phone"):
        customer_profile["phone"] = clean_phone

    session = WHATSAPP_SESSIONS.setdefault(clean_phone, {"history": []})
    session["history"].append({"role": "user", "content": user_text})

    # CRITICAL FIX: Run in worker thread so FastAPI event loop never freezes!
    reply, was_escalated, reason = await asyncio.to_thread(
        execute_turn, clean_phone, customer_profile, session["history"]
    )

    if reply:
        session["history"].append({"role": "assistant", "content": reply})
        db.add(AuditLog(user_id=clean_phone, user_name=ProfileName, sender="Malltiple AI (WhatsApp)", message=reply))
        db.commit()

    if was_escalated:
        reply = "⏳ I have escalated your request to our customer care team. A human agent will follow up with you shortly."

    db.close()

    twiml_response = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Message>{html.escape(reply)}</Message>
</Response>"""

    return Response(content=twiml_response, media_type="application/xml")
