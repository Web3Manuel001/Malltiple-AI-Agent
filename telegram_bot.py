import os
import io
import json
import logging
import asyncio
from datetime import datetime
from aiohttp import web
from dotenv import load_dotenv

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, 
    CallbackQueryHandler, filters, ContextTypes
)

from groq import Groq
from woo_tools import (
    search_products, get_categories, track_order_live, 
    create_order_and_payment_link
)
from memory import (
    get_customer, save_or_update_customer, log_message,
    add_agent, is_authorized_agent, get_all_active_agents,
    record_ticket_claim, record_ticket_resolution, record_csat_rating,
    get_agent_dashboard_metrics
)
from supervisor import audit_human_agent_message
from voice_engine import transcribe_audio_bytes, text_to_speech_bytes

load_dotenv()
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

client = Groq(api_key=GROQ_API_KEY)
USER_SESSIONS = {}

# --- TOOLS DEFINITION ---
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_products",
            "description": "Search products in the catalog by 1-2 core keywords.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "Search keyword (e.g. 'oats', 'soya')"}},
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "track_order_live",
            "description": "Track order fulfillment status, items, and courier/dispatch notes using numeric Order ID.",
            "parameters": {
                "type": "object",
                "properties": {"order_id": {"type": "integer", "description": "WooCommerce numeric order ID"}},
                "required": ["order_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_order_and_payment_link",
            "description": "Place an order for a customer and generate a secure Paystack payment link.",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_name": {"type": "string", "description": "Customer full name"},
                    "phone": {"type": "string", "description": "Phone number"},
                    "delivery_address": {"type": "string", "description": "Street address"},
                    "city": {"type": "string", "description": "City/State (e.g. 'Lagos')"},
                    "line_items": {
                        "type": "array",
                        "description": "List of items with product_id and quantity",
                        "items": {
                            "type": "object",
                            "properties": {
                                "product_id": {"type": "integer"},
                                "quantity": {"type": "integer"}
                            },
                            "required": ["product_id", "quantity"]
                        }
                    }
                },
                "required": ["customer_name", "phone", "delivery_address", "city", "line_items"]
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
            "description": "Look up customer profile by phone or email.",
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
            "description": "Escalate conversation to a human support agent.",
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
You are the official customer assistant for Malltiple (malltiple.com.ng), a Nigerian online marketplace.
Help customers search products, place orders, check prices (in Naira), and track live delivery.

ORDERING & PAYMENTS:
- When a customer wants to buy, gather their Name, Phone, Delivery Address, City, and Items.
- Call `create_order_and_payment_link` to create the order and give them the payment URL.

TRACKING:
- When a customer asks about order status or location, call `track_order_live`.

CRITICAL RULES:
- Never write 'N' or '₦' before numbers. Always write the number followed by the word 'Naira' (e.g. '11,500 Naira').
- If customer demands a human or reports a dispute, call `escalate_to_human`.
- Keep answers concise and helpful.
"""

def run_agent_turn(user_id: int, user_text: str, user_name: str):
    if user_id not in USER_SESSIONS:
        USER_SESSIONS[user_id] = {"history": [], "escalated": False, "assigned_to": None, "name": user_name}

    session = USER_SESSIONS[user_id]
    if session["escalated"]:
        return None, False, ""

    if len(session["history"]) > 6:
        session["history"] = session["history"][-6:]

    session["history"].append({"role": "user", "content": user_text})
    messages_for_api = [{"role": "system", "content": SYSTEM_PROMPT}] + list(session["history"])
    escalated_flag = False
    escalation_reason = ""

    while True:
        try:
            response = client.chat.completions.create(
                model="qwen/qwen3.8-27b",
                messages=messages_for_api,
                tools=TOOLS,
                tool_choice="auto",
                temperature=0.2,
                max_tokens=400
            )
        except Exception as e:
            return "Sorry, I had a brief issue. Could you repeat that?", False, ""

        resp_msg = response.choices[0].message
        if resp_msg.tool_calls:
            messages_for_api.append({
                "role": "assistant",
                "content": resp_msg.content or "",
                "tool_calls": [
                    {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                    for tc in resp_msg.tool_calls
                ]
            })

            for call in resp_msg.tool_calls:
                fn_name = call.function.name
                args = json.loads(call.function.arguments)
                tool_id = call.id

                if fn_name == "search_products":
                    result = search_products(args.get("query", ""))
                elif fn_name == "track_order_live":
                    result = track_order_live(args.get("order_id", 0))
                elif fn_name == "create_order_and_payment_link":
                    result = create_order_and_payment_link(
                        customer_name=args.get("customer_name"),
                        phone=args.get("phone"),
                        delivery_address=args.get("delivery_address"),
                        city=args.get("city"),
                        line_items=args.get("line_items", [])
                    )
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

                messages_for_api.append({"role": "tool", "tool_call_id": tool_id, "name": fn_name, "content": json.dumps(result)})
            continue
        else:
            bot_text = resp_msg.content or ""
            session["history"].append({"role": "assistant", "content": bot_text})
            return bot_text, escalated_flag, escalation_reason

# --- TELEGRAM BOT COMMANDS ---

async def claim_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sender_id = str(update.effective_user.id)
    agent_check = is_authorized_agent(sender_id)
    is_admin = sender_id == str(ADMIN_CHAT_ID)

    if not agent_check["authorized"] and not is_admin:
        await update.message.reply_text("⛔ Unauthorized.")
        return

    agent_name = agent_check["name"] if agent_check["authorized"] else "Admin"
    if not context.args:
        await update.message.reply_text("Usage: `/claim <user_id>`", parse_mode="Markdown")
        return

    target_user_id = int(context.args[0])
    session = USER_SESSIONS.get(target_user_id)
    if not session:
        await update.message.reply_text("❌ No active session found.")
        return

    session["assigned_to"] = {"id": sender_id, "name": agent_name}
    session["escalated"] = True

    # Record Claim in DB to start duration timer
    record_ticket_claim(target_user_id, session.get("name", "Customer"), sender_id, agent_name)

    await update.message.reply_text(f"🎯 Claimed customer `{target_user_id}`. Use `/reply {target_user_id} <msg>`.", parse_mode="Markdown")

async def reply_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sender_id = str(update.effective_user.id)
    agent_check = is_authorized_agent(sender_id)
    is_admin = sender_id == str(ADMIN_CHAT_ID)

    if not agent_check["authorized"] and not is_admin:
        await update.message.reply_text("⛔ Unauthorized.")
        return

    agent_name = agent_check["name"] if agent_check["authorized"] else "Admin"
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Usage: `/reply <user_id> <message>`", parse_mode="Markdown")
        return

    target_user_id = int(args[0])
    reply_text = " ".join(args[1:])

    # AI Supervisor Audit
    audit = audit_human_agent_message(agent_name, reply_text)
    if audit.get("violation_detected"):
        warning = f"🚨 *SUPERVISOR BLOCKED MESSAGE!*\n• Reason: {audit.get('reason')}\nMessage not delivered."
        await update.message.reply_text(warning, parse_mode="Markdown")
        return

    try:
        await context.bot.send_message(chat_id=target_user_id, text=f"👨‍💼 *Malltiple Support ({agent_name}):*\n{reply_text}", parse_mode="Markdown")
        log_message(user_id=str(target_user_id), sender=f"Agent: {agent_name}", text=reply_text)
        await update.message.reply_text(f"✅ Delivered to `{target_user_id}`.", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Failed: {e}")

async def resolve_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Marks ticket resolved, records handling duration, and sends CSAT rating to customer."""
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
        assigned_id = session.get("assigned_to", {}).get("id", sender_id)
        session["assigned_to"] = None

        # 1. Record resolution and calculate duration
        res = record_ticket_resolution(str(target_user_id), assigned_id)
        duration_mins = res["duration_seconds"] // 60
        duration_secs = res["duration_seconds"] % 60
        agent_name = res["agent_name"]

        await update.message.reply_text(
            f"✅ Ticket resolved!\n⏱️ Duration: {duration_mins}m {duration_secs}s.\nCustomer rating prompt sent.",
            parse_mode="Markdown"
        )

        # 2. Send CSAT Rating prompt to customer
        ticket_id = res["ticket_id"] or 0
        keyboard = [
            [
                InlineKeyboardButton("⭐ 1", callback_data=f"rate:{ticket_id}:{assigned_id}:{agent_name}:1"),
                InlineKeyboardButton("⭐ 2", callback_data=f"rate:{ticket_id}:{assigned_id}:{agent_name}:2"),
                InlineKeyboardButton("⭐ 3", callback_data=f"rate:{ticket_id}:{assigned_id}:{agent_name}:3"),
                InlineKeyboardButton("⭐ 4", callback_data=f"rate:{ticket_id}:{assigned_id}:{agent_name}:4"),
                InlineKeyboardButton("⭐ 5", callback_data=f"rate:{ticket_id}:{assigned_id}:{agent_name}:5"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await context.bot.send_message(
            chat_id=target_user_id,
            text=f"🤝 Your issue has been resolved by *{agent_name}*.\n\nHow would you rate your support experience today?",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )

async def handle_rating_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processes customer CSAT rating button clicks."""
    query = update.callback_query
    await query.answer()

    data = query.data.split(":")
    if data[0] == "rate":
        ticket_id = int(data[1])
        agent_id = data[2]
        agent_name = data[3]
        rating = int(data[4])

        record_csat_rating(ticket_id, str(query.from_user.id), agent_id, agent_name, rating)
        await query.edit_message_text(f"❤️ Thank you for rating *{agent_name}* {rating} out of 5 stars! We appreciate your feedback.", parse_mode="Markdown")

async def handle_customer_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    user_name = user.full_name or user.username or "Customer"
    text = update.message.text
    if text.startswith("/"):
        return

    log_message(user_id=str(user_id), sender="Customer", text=text, user_name=user_name)

    session = USER_SESSIONS.get(user_id)
    if session and session.get("escalated"):
        assigned = session.get("assigned_to")
        if assigned:
            await context.bot.send_message(chat_id=assigned["id"], text=f"💬 *[Cust Update]* {user_name} (`{user_id}`):\n\"{text}\"", parse_mode="Markdown")
        else:
            await update.message.reply_text("⏳ An agent will respond shortly.")
        return

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    bot_reply, was_escalated, reason = run_agent_turn(user_id, text, user_name)

    if bot_reply:
        await update.message.reply_text(bot_reply)
        log_message(user_id=str(user_id), sender="Malltiple AI", text=bot_reply, user_name=user_name)

    if was_escalated:
        alert = f"🚨 *ESCALATION:*\n• Cust: {user_name} (`{user_id}`)\n• Reason: {reason}\n👉 Claim: `/claim {user_id}`"
        if ADMIN_CHAT_ID:
            await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=alert, parse_mode="Markdown")
        for agent in get_all_active_agents():
            if str(agent["id"]) != str(ADMIN_CHAT_ID):
                try:
                    await context.bot.send_message(chat_id=agent["id"], text=alert, parse_mode="Markdown")
                except Exception:
                    pass

async def handle_customer_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    user_name = user.full_name or "Customer"

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="record_voice")
    try:
        voice_file = await context.bot.get_file(update.message.voice.file_id)
        audio_bytes = bytes(await voice_file.download_as_bytearray())

        stt_res = transcribe_audio_bytes(audio_bytes)
        if not stt_res.get("success") or not stt_res.get("text"):
            await update.message.reply_text("🎙️ I couldn't hear that clearly. Please try again.")
            return

        text = stt_res["text"]
        bot_reply, was_escalated, reason = run_agent_turn(user_id, text, user_name)
        if bot_reply:
            try:
                tts_bytes = text_to_speech_bytes(bot_reply)
                v_io = io.BytesIO(tts_bytes)
                v_io.name = "reply.mp3"
                await update.message.reply_voice(voice=v_io, caption=bot_reply)
            except Exception:
                await update.message.reply_text(bot_reply)
    except Exception as e:
        print(f"Voice error: {e}")

# --- WEB CONTROL DASHBOARD ---

DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Malltiple AI - Agent Command Center</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-slate-900 text-slate-100 min-h-screen p-6">
    <div class="max-w-6xl mx-auto">
        <header class="flex justify-between items-center pb-6 border-b border-slate-700 mb-6">
            <div>
                <h1 class="text-2xl font-bold text-amber-400">🛍️ Malltiple AI Agent Control</h1>
                <p class="text-sm text-slate-400">Human Support & Performance Analytics</p>
            </div>
            <a href="/dashboard" class="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-sm font-semibold rounded-lg border border-slate-600">Refresh Data</a>
        </header>

        <!-- Metric Cards -->
        <div class="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
            <div class="bg-slate-800 p-5 rounded-xl border border-slate-700">
                <span class="text-slate-400 text-sm">Active Human Agents</span>
                <p class="text-3xl font-extrabold mt-1 text-emerald-400">{{TOTAL_AGENTS}}</p>
            </div>
            <div class="bg-slate-800 p-5 rounded-xl border border-slate-700">
                <span class="text-slate-400 text-sm">Tickets Resolved Today</span>
                <p class="text-3xl font-extrabold mt-1 text-blue-400">{{TOTAL_RESOLVED}}</p>
            </div>
            <div class="bg-slate-800 p-5 rounded-xl border border-slate-700">
                <span class="text-slate-400 text-sm">Average CSAT Rating</span>
                <p class="text-3xl font-extrabold mt-1 text-amber-400">⭐ {{AVG_CSAT}} / 5.0</p>
            </div>
        </div>

        <!-- Add Agent Form -->
        <div class="bg-slate-800 p-6 rounded-xl border border-slate-700 mb-8">
            <h2 class="text-lg font-semibold mb-4 text-slate-200">➕ Register New Human Support Agent</h2>
            <form method="POST" action="/api/add-agent" class="grid grid-cols-1 md:grid-cols-3 gap-4">
                <input type="text" name="name" placeholder="Agent Full Name (e.g. Sarah J.)" required class="bg-slate-900 border border-slate-700 rounded-lg px-4 py-2 text-sm text-white focus:outline-none focus:border-amber-400">
                <input type="text" name="telegram_id" placeholder="Telegram User ID (e.g. 987654321)" required class="bg-slate-900 border border-slate-700 rounded-lg px-4 py-2 text-sm text-white focus:outline-none focus:border-amber-400">
                <button type="submit" class="bg-amber-500 hover:bg-amber-600 text-slate-950 font-bold px-4 py-2 rounded-lg text-sm transition">Add Agent</button>
            </form>
        </div>

        <!-- Agent Performance Table -->
        <div class="bg-slate-800 rounded-xl border border-slate-700 overflow-hidden">
            <div class="p-4 border-b border-slate-700">
                <h2 class="text-lg font-semibold text-slate-200">📊 Agent Performance & Handling Time</h2>
            </div>
            <div class="overflow-x-auto">
                <table class="w-full text-left text-sm text-slate-300">
                    <thead class="bg-slate-900/50 text-slate-400 uppercase text-xs">
                        <tr>
                            <th class="p-4">Agent Name</th>
                            <th class="p-4">Telegram ID</th>
                            <th class="p-4">Tickets Resolved</th>
                            <th class="p-4">Avg Handling Time</th>
                            <th class="p-4">Customer Rating</th>
                        </tr>
                    </thead>
                    <tbody class="divide-y divide-slate-700">
                        {{AGENT_ROWS}}
                    </tbody>
                </table>
            </div>
        </div>
    </div>
</body>
</html>
"""

async def handle_dashboard(request):
    data = get_agent_dashboard_metrics()
    agents = data["agents"]

    total_agents = len(agents)
    total_resolved = sum(a["resolved"] for a in agents)
    avg_csat = round(sum(a["avg_rating"] for a in agents) / total_agents, 1) if total_agents > 0 else 5.0

    rows_html = ""
    for a in agents:
        mins = a["avg_time_seconds"] // 60
        secs = a["avg_time_seconds"] % 60
        time_str = f"{mins}m {secs}s" if a["resolved"] > 0 else "N/A"
        rating_str = f"⭐ {a['avg_rating']} ({a['ratings_count']} ratings)" if a["ratings_count"] > 0 else "No ratings yet"

        rows_html += f"""
        <tr class="hover:bg-slate-700/40">
            <td class="p-4 font-semibold text-white">{a['name']}</td>
            <td class="p-4 font-mono text-slate-400">{a['id']}</td>
            <td class="p-4">{a['resolved']}</td>
            <td class="p-4">{time_str}</td>
            <td class="p-4 text-amber-400">{rating_str}</td>
        </tr>
        """

    if not rows_html:
        rows_html = "<tr><td colspan='5' class='p-4 text-center text-slate-500'>No agents registered yet. Use the form above.</td></tr>"

    html = DASHBOARD_HTML.replace("{{TOTAL_AGENTS}}", str(total_agents))
    html = html.replace("{{TOTAL_RESOLVED}}", str(total_resolved))
    html = html.replace("{{AVG_CSAT}}", str(avg_csat))
    html = html.replace("{{AGENT_ROWS}}", rows_html)

    return web.Response(text=html, content_type="text/html")

async def handle_add_agent_form(request):
    data = await request.post()
    name = data.get("name")
    tg_id = data.get("telegram_id")
    if name and tg_id:
        add_agent(tg_id, name)
    raise web.HTTPFound("/dashboard")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Malltiple AI Service Healthy"))
    app.router.add_get("/health", lambda r: web.Response(text="OK"))
    app.router.add_get("/dashboard", handle_dashboard)
    app.router.add_post("/api/add-agent", handle_add_agent_form)

    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"🌐 Web Control Dashboard running at http://0.0.0.0:{port}/dashboard")

# --- MAIN LOOP ---

if __name__ == "__main__":
    print("🚀 Malltiple Multi-Agent & Commerce Engine Starting...")
    tg_app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    tg_app.add_handler(CommandHandler("claim", claim_cmd))
    tg_app.add_handler(CommandHandler("reply", reply_cmd))
    tg_app.add_handler(CommandHandler("resolve", resolve_cmd))
    tg_app.add_handler(CallbackQueryHandler(handle_rating_callback))
    tg_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_customer_message))
    tg_app.add_handler(MessageHandler(filters.VOICE, handle_customer_voice))

    async def main():
        await start_web_server()
        await tg_app.initialize()
        await tg_app.start()
        await tg_app.updater.start_polling()
        print("✅ System Online! Both Bot and Dashboard are live.")
        while True:
            await asyncio.sleep(3600)

    asyncio.run(main())
