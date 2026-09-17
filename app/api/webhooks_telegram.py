import io
import json
from datetime import datetime
from fastapi import APIRouter, Request, BackgroundTasks
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, 
    CallbackQueryHandler, filters, ContextTypes
)

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.agent import Agent
from app.models.ticket import TicketSession, CSATRating
from app.models.audit import AuditLog
from app.services.brain import execute_turn
from app.services.supervisor import audit_human_agent_message
from app.services.voice import transcribe_audio_bytes, text_to_speech_bytes

router = APIRouter()
tg_app = ApplicationBuilder().token(settings.TELEGRAM_BOT_TOKEN).build()
USER_SESSIONS = {}

# --- COMMANDS ---
async def claim_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sender_id = str(update.effective_user.id)
    db = SessionLocal()
    agent = db.query(Agent).filter(Agent.telegram_id == sender_id, Agent.is_active == True).first()
    is_admin = sender_id == str(settings.ADMIN_CHAT_ID)

    if not agent and not is_admin:
        db.close()
        await update.message.reply_text("⛔ Unauthorized.")
        return

    agent_name = agent.name if agent else "Admin"
    if not context.args:
        db.close()
        await update.message.reply_text("Usage: `/claim <user_id>`", parse_mode="Markdown")
        return

    target_id = int(context.args[0])
    session = USER_SESSIONS.get(target_id)
    if not session:
        db.close()
        await update.message.reply_text("❌ No active session found.")
        return

    session["assigned_to"] = {"id": sender_id, "name": agent_name}
    session["escalated"] = True

    ticket = TicketSession(customer_id=str(target_id), customer_name=session.get("name", "Customer"), assigned_agent_id=sender_id, assigned_agent_name=agent_name, status="claimed", claimed_at=datetime.utcnow())
    db.add(ticket)
    db.commit()
    db.close()

    await update.message.reply_text(f"🎯 Claimed customer `{target_id}`. Use `/reply {target_id} <msg>`.", parse_mode="Markdown")

async def reply_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sender_id = str(update.effective_user.id)
    db = SessionLocal()
    agent = db.query(Agent).filter(Agent.telegram_id == sender_id, Agent.is_active == True).first()
    is_admin = sender_id == str(settings.ADMIN_CHAT_ID)

    if not agent and not is_admin:
        db.close()
        await update.message.reply_text("⛔ Unauthorized.")
        return

    agent_name = agent.name if agent else "Admin"
    if len(context.args) < 2:
        db.close()
        await update.message.reply_text("Usage: `/reply <user_id> <message>`", parse_mode="Markdown")
        return

    target_id = int(context.args[0])
    reply_text = " ".join(context.args[1:])

    audit = audit_human_agent_message(agent_name, reply_text)
    if audit.get("violation_detected"):
        db.close()
        await update.message.reply_text(f"🚨 *SUPERVISOR BLOCKED MESSAGE!*\n• Reason: {audit.get('reason')}\nMessage not delivered.", parse_mode="Markdown")
        return

    try:
        await context.bot.send_message(chat_id=target_id, text=f"👨‍💼 *Malltiple Support ({agent_name}):*\n{reply_text}", parse_mode="Markdown")
        db.add(AuditLog(user_id=str(target_id), sender=f"Agent: {agent_name}", message=reply_text))
        db.commit()
        await update.message.reply_text(f"✅ Delivered to `{target_id}`.", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Failed: {e}")
    finally:
        db.close()

async def resolve_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sender_id = str(update.effective_user.id)
    db = SessionLocal()
    agent = db.query(Agent).filter(Agent.telegram_id == sender_id, Agent.is_active == True).first()
    is_admin = sender_id == str(settings.ADMIN_CHAT_ID)

    if not agent and not is_admin:
        db.close()
        await update.message.reply_text("⛔ Unauthorized.")
        return

    if not context.args:
        db.close()
        await update.message.reply_text("Usage: `/resolve <user_id>`", parse_mode="Markdown")
        return

    target_id = int(context.args[0])
    session = USER_SESSIONS.get(target_id)
    if session:
        session["escalated"] = False
        session["assigned_to"] = None

        ticket = db.query(TicketSession).filter(TicketSession.customer_id == str(target_id), TicketSession.status == "claimed").order_by(TicketSession.ticket_id.desc()).first()
        duration = 0
        agent_name = agent.name if agent else "Admin"
        ticket_id = 0

        if ticket:
            now = datetime.utcnow()
            duration = int((now - ticket.claimed_at).total_seconds())
            ticket.status = "resolved"
            ticket.resolved_at = now
            ticket.duration_seconds = duration
            ticket_id = ticket.ticket_id

            if agent:
                agent.total_time_seconds += duration
                agent.tickets_resolved += 1
            db.commit()

        db.close()
        mins = duration // 60
        secs = duration % 60
        await update.message.reply_text(f"✅ Ticket resolved!\n⏱️ Duration: {mins}m {secs}s.\nCustomer rating prompt sent.", parse_mode="Markdown")

        keyboard = [[
            InlineKeyboardButton("⭐ 1", callback_data=f"rate:{ticket_id}:{sender_id}:{agent_name}:1"),
            InlineKeyboardButton("⭐ 2", callback_data=f"rate:{ticket_id}:{sender_id}:{agent_name}:2"),
            InlineKeyboardButton("⭐ 3", callback_data=f"rate:{ticket_id}:{sender_id}:{agent_name}:3"),
            InlineKeyboardButton("⭐ 4", callback_data=f"rate:{ticket_id}:{sender_id}:{agent_name}:4"),
            InlineKeyboardButton("⭐ 5", callback_data=f"rate:{ticket_id}:{sender_id}:{agent_name}:5"),
        ]]
        await context.bot.send_message(
            chat_id=target_id,
            text=f"🤝 Your issue has been resolved by *{agent_name}*.\n\nHow would you rate your support experience today?",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    else:
        db.close()

async def rating_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data.split(":")
    if data[0] == "rate":
        db = SessionLocal()
        db.add(CSATRating(ticket_id=int(data[1]), customer_id=str(query.from_user.id), agent_id=data[2], agent_name=data[3], rating=int(data[4])))
        db.commit()
        db.close()
        await query.edit_message_text(f"❤️ Thank you for rating *{data[3]}* {data[4]} out of 5 stars! We appreciate your feedback.", parse_mode="Markdown")

async def customer_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    text = update.message.text
    if text.startswith("/"): return

    db = SessionLocal()
    db.add(AuditLog(user_id=str(user_id), user_name=user.full_name or "Customer", sender="Customer", message=text))
    db.commit()

    session = USER_SESSIONS.setdefault(user_id, {"history": [], "escalated": False, "assigned_to": None, "name": user.full_name or "Customer"})
    if session.get("escalated"):
        assigned = session.get("assigned_to")
        if assigned:
            await context.bot.send_message(chat_id=assigned["id"], text=f"💬 *[Cust Update]* {user.full_name} (`{user_id}`):\n\"{text}\"", parse_mode="Markdown")
        else:
            await update.message.reply_text("⏳ An agent will respond shortly.")
        db.close()
        return

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    session["history"].append({"role": "user", "content": text})
    reply, was_escalated, reason = execute_turn(str(user_id), session["history"])

    if reply:
        session["history"].append({"role": "assistant", "content": reply})
        await update.message.reply_text(reply)
        db.add(AuditLog(user_id=str(user_id), user_name=user.full_name or "Customer", sender="Malltiple AI", message=reply))
        db.commit()

    if was_escalated:
        session["escalated"] = True
        alert = f"🚨 *ESCALATION:*\n• Cust: {user.full_name} (`{user_id}`)\n• Reason: {reason}\n👉 Claim: `/claim {user_id}`"
        if settings.ADMIN_CHAT_ID:
            await context.bot.send_message(chat_id=settings.ADMIN_CHAT_ID, text=alert, parse_mode="Markdown")
        agents = db.query(Agent).filter(Agent.is_active == True).all()
        for a in agents:
            if str(a.telegram_id) != str(settings.ADMIN_CHAT_ID):
                try: await context.bot.send_message(chat_id=a.telegram_id, text=alert, parse_mode="Markdown")
                except: pass

    db.close()

async def customer_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="record_voice")
    try:
        v_file = await context.bot.get_file(update.message.voice.file_id)
        audio = bytes(await v_file.download_as_bytearray())
        stt = transcribe_audio_bytes(audio)
        if not stt.get("success") or not stt.get("text"):
            await update.message.reply_text("🎙️ I couldn't hear that clearly. Please try again.")
            return

        text = stt["text"]
        session = USER_SESSIONS.setdefault(user_id, {"history": [], "escalated": False, "assigned_to": None, "name": user.full_name or "Customer"})
        session["history"].append({"role": "user", "content": text})
        reply, was_esc, reason = execute_turn(str(user_id), session["history"])
        if reply:
            session["history"].append({"role": "assistant", "content": reply})
            try:
                tts = text_to_speech_bytes(reply)
                v_io = io.BytesIO(tts)
                v_io.name = "reply.mp3"
                await update.message.reply_voice(voice=v_io, caption=reply)
            except:
                await update.message.reply_text(reply)
    except Exception as e:
        print(f"Voice error: {e}")

# Register Handlers
tg_app.add_handler(CommandHandler("claim", claim_cmd))
tg_app.add_handler(CommandHandler("reply", reply_cmd))
tg_app.add_handler(CommandHandler("resolve", resolve_cmd))
tg_app.add_handler(CallbackQueryHandler(rating_callback))
tg_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, customer_msg))
tg_app.add_handler(MessageHandler(filters.VOICE, customer_voice))

# --- THE TELEGRAM WEBHOOK ENDPOINT ---
@router.post("/api/telegram-webhook")
async def telegram_webhook_handler(request: Request, background_tasks: BackgroundTasks):
    """
    Receives Telegram updates via HTTP POST. Zero polling loop, zero 409 conflicts.
    """
    req_dict = await request.json()
    update = Update.de_json(data=req_dict, bot=tg_app.bot)
    background_tasks.add_task(tg_app.process_update, update)
    return {"ok": True}
