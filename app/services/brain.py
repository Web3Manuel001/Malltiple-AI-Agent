import json
from groq import Groq
from app.config import settings
from app.services.woocommerce import search_products, get_categories, track_order_live, build_customer_cart

client = Groq(api_key=settings.GROQ_API_KEY)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_products",
            "description": "Search products in catalog by 1-2 core keywords.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "Search keyword"}},
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "build_customer_cart",
            "description": "Calculate total prices and generate the official Malltiple cart link for customer to pay on the website.",
            "parameters": {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
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
                "required": ["items"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "track_order_live",
            "description": "Track order status and dispatch updates using Order ID.",
            "parameters": {
                "type": "object",
                "properties": {"order_id": {"type": "integer"}},
                "required": ["order_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_categories",
            "description": "List all product departments available on Malltiple.",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "escalate_to_human",
            "description": "Escalate conversation to human staff for complaints or customer demand.",
            "parameters": {
                "type": "object",
                "properties": {"reason": {"type": "string"}},
                "required": ["reason"]
            }
        }
    }
]

SYSTEM_PROMPT = """
You are the official customer assistant for Malltiple (malltiple.com.ng), a Nigerian online marketplace.
Help customers search products, prepare carts, check prices in Naira, and track live orders.

SHOPPING & CART POLICY:
- Help customers find items using `search_products`.
- When they want to purchase, call `build_customer_cart` with product IDs and quantities.
- Give them the itemized total in Naira and the direct link to review their cart and pay securely on the website.

RULES:
- Never write 'N' or '₦' before numbers. Always write '11,500 Naira'.
- If customer demands a human or reports a dispute, call `escalate_to_human`.
- Keep answers concise and helpful.
"""

def execute_turn(history: list) -> tuple:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history[-6:]
    escalated = False
    reason = ""

    while True:
        try:
            res = client.chat.completions.create(
                model="qwen/qwen3.8-27b",
                messages=messages,
                tools=TOOLS,
                tool_choice="auto",
                temperature=0.2,
                max_tokens=400
            )
        except Exception:
            return "Sorry, I had a brief connection glitch. Could you repeat that?", False, ""

        msg = res.choices[0].message
        if msg.tool_calls:
            messages.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                    for tc in msg.tool_calls
                ]
            })

            for call in msg.tool_calls:
                fn = call.function.name
                args = json.loads(call.function.arguments)
                tool_id = call.id

                if fn == "search_products":
                    result = search_products(args.get("query", ""))
                elif fn == "build_customer_cart":
                    result = build_customer_cart(args.get("items", []))
                elif fn == "track_order_live":
                    result = track_order_live(args.get("order_id", 0))
                elif fn == "get_categories":
                    result = get_categories()
                elif fn == "escalate_to_human":
                    escalated = True
                    reason = args.get("reason", "Customer requested human support.")
                    result = {"status": "escalated", "message": "Support team notified."}
                else:
                    result = {"error": "Unknown tool"}

                messages.append({"role": "tool", "tool_call_id": tool_id, "name": fn, "content": json.dumps(result)})
            continue
        else:
            return msg.content or "", escalated, reason
