import os
import json
import logging
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

from groq import Groq
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
Help customers search products, check prices (₦ Naira), check orders, and answer questions.
If customer demands a human or has a payment dispute/double debit, call `escalate_to_human`.
Keep answers concise, helpful, and polite.
"""

def run_agent_turn(user_id: int, user_text: str, user_name: str):
    if user_id not in USER_SESSIONS:
        USER_SESSIONS[user_id] = {"history": [], "escalated": False, "assigned_to": None, "name": user_name}

    session = USER_SESSIONS[user_id]
    if session["escalated"]:
        return None, False, ""

    session["history"].append({"role": "user", "content": user_text})
    escalated_flag = False
    escalation_reason = ""

    while True:
        response = client.chat.completions.create(
            model="qwen/qwen3.8-27b",
            messages=[{"role": "system", "content": SYSTEM_PROMPT}] + session["history"],
            tools=TOOLS,
            tool_choice="auto",
            temperature=0.2,
            max_tokens=500
        )

        resp_msg = response.choices[0].message
        if resp_msg.tool_calls:
            session["history"].append(resp_msg)
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

                session["history"].append({
                    "role": "tool",
                    "tool_call_id": tool_id,
                    "name": fn_name,
                    "content": json.dumps(result)
                })
            continue
        else:
            bot_text = resp_msg.content
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

if __name__ == "__main__":
    print("🚀 Malltiple Multi-Agent Support Desk is starting...")
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("addagent", add_agent_cmd))
    app.add_handler(CommandHandler("claim", claim_cmd))
    app.add_handler(CommandHandler("reply", reply_cmd))
    app.add_handler(CommandHandler("resolve", resolve_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_customer_message))

    print("✅ System Online! Multi-Agent Dispatch & Admin Surveillance active.")
    app.run_polling()