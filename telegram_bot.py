import os
import json
import logging
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
import asyncio
from aiohttp import web
from groq import Groq
import io
from voice_engine import transcribe_audio_bytes, text_to_speech_bytes
from woo_tools import search_products, get_order_status, get_categories
from memory import (
    get_customer, save_or_update_customer, log_message, 
    add_agent, is_authorized_agent, get_all_active_agents
)
from supervisor import audit_human_agent_message

load_dotenv()
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

client = Groq(api_key=GROQ_API_KEY)

# Track sessions: {user_id: {"history": [...], "escalated": False, "assigned_to": None}}
USER_SESSIONS = {}

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_products",
            "description": "Search products in Malltiple catalog by name or keyword.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "Search term"}},
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_order_status",
            "description": "Look up fulfillment status and items using numeric Order ID.",
            "parameters": {
                "type": "object",
                "properties": {"order_id": {"type": "integer", "description": "Order ID"}},
                "required": ["order_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_categories",
            "description": "Get all product categories available on Malltiple.",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "lookup_customer",
            "description": "Look up customer by phone number or email address.",
            "parameters": {
                "type": "object",
                "properties": {"identifier": {"type": "string", "description": "Phone or Email"}},
                "required": ["identifier"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "escalate_to_human",
            "description": "Hand over the chat to a human agent for complex disputes or customer demand.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {"type": "string", "description": "Reason for escalation"},
                    "urgency": {"type": "string", "description": "Urgency level"}
                },
                "required": ["reason"]
            }
        }
    }
]

SYSTEM_PROMPT = """
You are the customer assistant for Malltiple (malltiple.com.ng), a Nigerian online marketplace.
Help customers search products, check prices, check orders, and answer questions.
If customer demands a human or has a payment dispute/double debit, call `escalate_to_human`.

CRITICAL SPEECH & CURRENCY RULE:
- NEVER EVER write the letter 'N' or the symbol '₦' before a price (NEVER write 'N3,500' or '₦3,500').
- ALWAYS write the number first followed by the word 'Naira' (e.g. '3,500 Naira', '68,000 Naira').
- Keep answers short and conversational.
"""

def run_agent_turn(user_id: int, user_text: str, user_name: str):
    if user_id not in USER_SESSIONS:
        USER_SESSIONS[user_id] = {"history": [], "escalated": False, "assigned_to": None, "name": user_name}

    session = USER_SESSIONS[user_id]
    if session["escalated"]:
        return None, False, ""

    # Keep only the last 6 messages to stay well within token limits
    if len(session["history"]) > 6:
        session["history"] = session["history"][-6:]

    session["history"].append({"role": "user", "content": user_text})
    escalated_flag = False
    escalation_reason = ""

    # Working copy of messages for this specific turn
    messages_for_api = [{"role": "system", "content": SYSTEM_PROMPT}] + list(session["history"])

    while True:
        try:
            response = client.chat.completions.create(
                model="qwen/qwen3.8-27b",
                messages=messages_for_api,
                tools=TOOLS,
                tool_choice="auto",
                temperature=0.2,
                max_tokens=300
            )
        except Exception as api_err:
            print(f"❌ Groq API Error: {api_err}")
            return "Sorry, I had a temporary glitch checking the store. Could you repeat that?", False, ""

        resp_msg = response.choices[0].message
        if resp_msg.tool_calls:
            # Append assistant message with tool calls
            messages_for_api.append({
                "role": "assistant",
                "content": resp_msg.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments}
                    }
                    for tc in resp_msg.tool_calls
                ]
            })

            for call in resp_msg.tool_calls:
                fn_name = call.function.name
                args = json.loads(call.function.arguments)
                tool_id = call.id

                if fn_name == "search_products":
                    result = search_products(args.get("query", ""))
                elif fn_name == "get_order_status":
                    result = get_order_status(args.get("order_id", 0))
                elif fn_name == "get_categories":
                    result = get_categories()
                elif fn_name == "lookup_customer":
                    result = get_customer(args.get("identifier", ""))
                elif fn_name == "escalate_to_human":
                    session["escalated"] = True
                    escalated_flag = True
                    escalation_reason = args.get("reason", "Customer requested human support.")
                    result = {"status": "escalated", "message": "Support agents notified."}
                else:
                    result = {"error": "Unknown tool"}

                messages_for_api.append({
                    "role": "tool",
                    "tool_call_id": tool_id,
                    "name": fn_name,
                    "content": json.dumps(result)
                })
            continue
        else:
            bot_text = resp_msg.content or ""
            # Save clean final assistant text into persistent session history
            session["history"].append({"role": "assistant", "content": bot_text})
            return bot_text, escalated_flag, escalation_reason
# --- COMMAND HANDLERS ---

async def add_agent_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command: /addagent <telegram_id> <name>"""
    sender_id = str(update.effective_user.id)
    if sender_id != str(ADMIN_CHAT_ID):
        await update.message.reply_text("⛔ Only the Master Admin can register agents.")
        return

    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Usage: `/addagent <telegram_id> <agent_name>`", parse_mode="Markdown")
        return

    agent_id = args[0]
    agent_name = " ".join(args[1:])
    msg = add_agent(agent_id, agent_name)
    await update.message.reply_text(f"✅ {msg}")

async def claim_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Agent command: /claim <user_id>"""
    sender_id = str(update.effective_user.id)
    agent_check = is_authorized_agent(sender_id)
    is_admin = sender_id == str(ADMIN_CHAT_ID)

    if not agent_check["authorized"] and not is_admin:
        await update.message.reply_text("⛔ You are not an authorized agent.")
        return

    agent_name = agent_check["name"] if agent_check["authorized"] else "Master Admin"

    if not context.args:
        await update.message.reply_text("Usage: `/claim <user_id>`", parse_mode="Markdown")
        return

    target_user_id = int(context.args[0])
    session = USER_SESSIONS.get(target_user_id)

    if not session:
        await update.message.reply_text("❌ No active session found for that user.")
        return

    session["assigned_to"] = {"id": sender_id, "name": agent_name}
    session["escalated"] = True

    # Inform the agent
    await update.message.reply_text(
        f"🎯 You have claimed customer `{target_user_id}`.\nUse `/reply {target_user_id} <message>` to chat.",
        parse_mode="Markdown"
    )

    # Inform Master Admin
    if sender_id != str(ADMIN_CHAT_ID) and ADMIN_CHAT_ID:
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=f"📌 Agent *{agent_name}* claimed customer `{target_user_id}`.",
            parse_mode="Markdown"
        )

async def reply_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Agent command: /reply <user_id> <message>"""
    sender_id = str(update.effective_user.id)
    agent_check = is_authorized_agent(sender_id)
    is_admin = sender_id == str(ADMIN_CHAT_ID)

    if not agent_check["authorized"] and not is_admin:
        await update.message.reply_text("⛔ Unauthorized.")
        return

    agent_name = agent_check["name"] if agent_check["authorized"] else "Master Admin"
    args = context.args

    if len(args) < 2:
        await update.message.reply_text("Usage: `/reply <user_id> <message>`", parse_mode="Markdown")
        return

    target_user_id = int(args[0])
    reply_text = " ".join(args[1:])

    # 1. RUN SUPERVISOR FRAUD AUDIT ON HUMAN AGENT
    audit = audit_human_agent_message(agent_name, reply_text)
    if audit.get("violation_detected"):
        warning = (
            f"🚨 *SUPERVISOR BLOCKED MESSAGE!* (Agent: {agent_name})\n"
            f"• Risk: {audit.get('risk_level')}\n"
            f"• Reason: {audit.get('reason')}\n"
            f"Message was NOT sent to the customer."
        )
        await update.message.reply_text(warning, parse_mode="Markdown")
        if ADMIN_CHAT_ID and sender_id != str(ADMIN_CHAT_ID):
            await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=f"⚠️ *AGENT COMPLIANCE ALERT:*\n{warning}", parse_mode="Markdown")
        return

    # 2. Deliver message to Customer
    try:
        await context.bot.send_message(
            chat_id=target_user_id,
            text=f"👨‍💼 *Malltiple Support ({agent_name}):*\n{reply_text}",
            parse_mode="Markdown"
        )
        log_message(user_id=str(target_user_id), sender=f"Agent: {agent_name}", text=reply_text)
        await update.message.reply_text(f"✅ Delivered to `{target_user_id}`.", parse_mode="Markdown")

        # 3. Mirror to Master Admin so Admin always sees everything
        if ADMIN_CHAT_ID and sender_id != str(ADMIN_CHAT_ID):
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=f"👁️ *[MIRROR]* Agent *{agent_name}* ➔ Cust `{target_user_id}`:\n\"{reply_text}\"",
                parse_mode="Markdown"
            )
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to deliver: {e}")

async def resolve_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Return customer conversation back to AI: /resolve <user_id>"""
    sender_id = str(update.effective_user.id)
    if not is_authorized_agent(sender_id)["authorized"] and sender_id != str(ADMIN_CHAT_ID):
        await update.message.reply_text("⛔ Unauthorized.")
        return

    if not context.args:
        await update.message.reply_text("Usage: `/resolve <user_id>`", parse_mode="Markdown")
        return

    target_user_id = int(context.args[0])
    session = USER_SESSIONS.get(target_user_id)
    if session:
        session["escalated"] = False
        session["assigned_to"] = None
        await update.message.reply_text(f"✅ Ticket for `{target_user_id}` marked resolved. AI is active again.", parse_mode="Markdown")
        await context.bot.send_message(
            chat_id=target_user_id,
            text="🤝 Your inquiry has been marked as resolved by our team. Our AI assistant is here if you need anything else!"
        )

async def handle_customer_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles incoming audio voice notes from customers."""
    user = update.effective_user
    user_id = user.id
    user_name = user.full_name or user.username or "Customer"

    # Show 'recording voice' indicator on Telegram
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="record_voice")

    try:
        # 1. Download voice note bytes directly into memory
        voice_file = await context.bot.get_file(update.message.voice.file_id)
        audio_bytearray = await voice_file.download_as_bytearray()
        audio_bytes = bytes(audio_bytearray)

        # 2. Transcribe with Deepgram Nova-2
        stt_result = transcribe_audio_bytes(audio_bytes)
        if not stt_result.get("success") or not stt_result.get("text"):
            await update.message.reply_text("🎙️ I couldn't hear that clearly. Could you please speak closer to the mic or type it?")
            return

        transcribed_text = stt_result["text"]
        print(f"\n🎤 [Voice Transcribed] {user_name}: \"{transcribed_text}\"")

        # 3. Mirror transcription to Admin
        if ADMIN_CHAT_ID and str(user_id) != str(ADMIN_CHAT_ID):
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=f"🎙️ *[VOICE INCOMING]* From: {user_name} (`{user_id}`)\nTranscript: \"_{transcribed_text}_\"",
                parse_mode="Markdown"
            )

        # 4. Log customer message
        log_message(user_id=str(user_id), sender="Customer (Voice)", text=transcribed_text, user_name=user_name)

        # 5. Check if session is assigned to an agent
        session = USER_SESSIONS.get(user_id)
        if session and session.get("escalated"):
            assigned = session.get("assigned_to")
            if assigned:
                await context.bot.send_message(
                    chat_id=assigned["id"],
                    text=f"🎙️ *[VOICE UPDATE]* From customer {user_name} (`{user_id}`):\n\"{transcribed_text}\"",
                    parse_mode="Markdown"
                )
            else:
                await update.message.reply_text("⏳ A customer care agent has been notified and will reply shortly.")
            return

        # 6. Run AI Brain
        bot_reply, was_escalated, reason = run_agent_turn(user_id, transcribed_text, user_name)

        if bot_reply:
            log_message(user_id=str(user_id), sender="Malltiple AI", text=bot_reply, user_name=user_name)

            # 7. Convert AI reply to Voice with ElevenLabs
            try:
                tts_bytes = text_to_speech_bytes(bot_reply)
                voice_io = io.BytesIO(tts_bytes)
                voice_io.name = "reply.mp3"

                # Reply with Voice Note AND text caption
                await update.message.reply_voice(voice=voice_io, caption=bot_reply)
            except Exception as tts_err:
                print(f"TTS Fallback error: {tts_err}")
                # If TTS fails or quota is low, fallback gracefully to text
                await update.message.reply_text(bot_reply)

            if ADMIN_CHAT_ID and str(user_id) != str(ADMIN_CHAT_ID):
                await context.bot.send_message(
                    chat_id=ADMIN_CHAT_ID,
                    text=f"🤖 *[AI VOICE REPLY]* To: {user_name} (`{user_id}`)\n{bot_reply}"
                )

        # Handle escalation if triggered by voice
        if was_escalated:
            alert = (
                f"🚨 *URGENT ESCALATION VIA VOICE!*\n\n"
                f"• Customer: {user_name} (`{user_id}`)\n"
                f"• Reason: {reason}\n\n"
                f"👉 Claim with: `/claim {user_id}`"
            )
            if ADMIN_CHAT_ID:
                await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=alert, parse_mode="Markdown")
            for agent in get_all_active_agents():
                if str(agent["id"]) != str(ADMIN_CHAT_ID):
                    try:
                        await context.bot.send_message(chat_id=agent["id"], text=alert, parse_mode="Markdown")
                    except Exception:
                        pass

    except Exception as e:
        print(f"Voice handling error: {e}")
        await update.message.reply_text("⚠️ An error occurred processing your voice note. Please try again.")

# --- CUSTOMER MESSAGE HANDLER ---

async def handle_customer_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    user_name = user.full_name or user.username or "Customer"
    text = update.message.text

    if text.startswith("/"):
        return

    log_message(user_id=str(user_id), sender="Customer", text=text, user_name=user_name)

    # Mirror customer message to Master Admin
    if ADMIN_CHAT_ID and str(user_id) != str(ADMIN_CHAT_ID):
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=f"💬 *[INCOMING]* From: {user_name} (`{user_id}`)\nMessage: {text}",
            parse_mode="Markdown"
        )

    # Check if session is assigned to an agent
    session = USER_SESSIONS.get(user_id)
    if session and session.get("escalated"):
        assigned = session.get("assigned_to")
        if assigned:
            # Forward customer's new message directly to their assigned agent
            await context.bot.send_message(
                chat_id=assigned["id"],
                text=f"💬 *[UPDATE]* From your customer {user_name} (`{user_id}`):\n\"{text}\"",
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text("⏳ A customer care agent has been notified and will take over shortly.")
        return

    # Process AI
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    bot_reply, was_escalated, reason = run_agent_turn(user_id, text, user_name)

    if bot_reply:
        await update.message.reply_text(bot_reply)
        log_message(user_id=str(user_id), sender="Malltiple AI", text=bot_reply, user_name=user_name)

        if ADMIN_CHAT_ID and str(user_id) != str(ADMIN_CHAT_ID):
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=f"🤖 *[AI REPLY]* To: {user_name} (`{user_id}`)\n{bot_reply}"
            )

    # If Escalated, broadcast to all agents and Admin
    if was_escalated:
        escalation_broadcast = (
            f"🚨 *URGENT ESCALATION REQUIRED!*\n\n"
            f"• Customer: {user_name} (`{user_id}`)\n"
            f"• Reason: {reason}\n\n"
            f"👉 *To claim this customer, type:*\n"
            f"`/claim {user_id}`"
        )
        # 1. Alert Admin
        if ADMIN_CHAT_ID:
            await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=escalation_broadcast, parse_mode="Markdown")

        # 2. Broadcast to all active team agents
        for agent in get_all_active_agents():
            if str(agent["id"]) != str(ADMIN_CHAT_ID):
                try:
                    await context.bot.send_message(chat_id=agent["id"], text=escalation_broadcast, parse_mode="Markdown")
                except Exception:
                    pass

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome to Malltiple Assistant! I can help you search products, check prices, and track orders. What are you looking for today?"
    )

async def health_check(request):
    return web.Response(text="Malltiple Bot is running healthy!")

async def start_health_server():
    app = web.Application()
    app.router.add_get("/", health_check)
    app.router.add_get("/health", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"🌐 Health check web server running on port {port}")

if __name__ == "__main__":
    print("🚀 Malltiple Multi-Agent Support Desk is starting...")
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("addagent", add_agent_cmd))
    app.add_handler(CommandHandler("claim", claim_cmd))
    app.add_handler(CommandHandler("reply", reply_cmd))
    app.add_handler(CommandHandler("resolve", resolve_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_customer_message))
    app.add_handler(CommandHandler("resolve", resolve_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_customer_message))
    app.add_handler(MessageHandler(filters.VOICE, handle_customer_voice))

    # Run both the web health server and the telegram polling
    async def main():
        await start_health_server()
        await app.initialize()
        await app.start()
        await app.updater.start_polling()
        print("✅ System Online! Listening for messages...")
        # Keep running forever
        while True:
            await asyncio.sleep(3600)

    asyncio.run(main())