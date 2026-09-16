import os
import json
from groq import Groq
from dotenv import load_dotenv
from woo_tools import search_products, get_order_status, get_categories
from memory import get_customer, save_or_update_customer

load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_products",
            "description": "Search for products in the Malltiple catalog by name or keyword.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search term (e.g., 'oats', 'oil')"}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_order_status",
            "description": "Look up fulfillment status, items, and total using numeric Order ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "integer", "description": "WooCommerce numeric order ID"}
                },
                "required": ["order_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_categories",
            "description": "Get all active product categories and departments available on Malltiple.",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "lookup_customer",
            "description": "Look up an existing customer using either their PHONE NUMBER or EMAIL ADDRESS.",
            "parameters": {
                "type": "object",
                "properties": {
                    "identifier": {
                        "type": "string", 
                        "description": "Customer's phone number OR email address (e.g., '08012345678' or 'customer@gmail.com')"
                    }
                },
                "required": ["identifier"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "save_customer_profile",
            "description": "Save or update a customer's name, email, phone number, city, or order info.",
            "parameters": {
                "type": "object",
                "properties": {
                    "phone": {"type": "string", "description": "Customer phone number"},
                    "email": {"type": "string", "description": "Customer email address"},
                    "name": {"type": "string", "description": "Customer name"},
                    "city": {"type": "string", "description": "Delivery city/state"},
                    "last_order_id": {"type": "integer", "description": "Recent order ID"}
                }
            }
        }
    },

    {
        "type": "function",
        "function": {
            "name": "escalate_to_human",
            "description": "Transfer the conversation to a human customer care representative. Call this immediately when the customer demands a human, expresses deep frustration, or has a complex dispute/refund issue.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": "Detailed summary of why escalation is needed"
                    },
                    "urgency": {
                        "type": "string",
                        "enum": ["low", "medium", "high", "critical"],
                        "description": "Urgency level"
                    }
                },
                "required": ["reason"]
            }
        }
    }
]

SYSTEM_PROMPT = """
You are the official AI customer assistant for Malltiple (malltiple.com.ng), a Nigerian online marketplace.

STORE SCOPE:
Malltiple offers Electronics, Bags & Fashion, Car Accessories, Groceries, Healthcare, Baby & Pregnancy, Household Needs, and more.

CUSTOMER RECOGNITION (CRITICAL):
- Whenever a customer provides a PHONE NUMBER or EMAIL ADDRESS, ALWAYS call `lookup_customer` FIRST.
- The `lookup_customer` tool checks both memory and live store order history.
- If `lookup_customer` returns `found: True`:
  - Greet them warmly by their real name (e.g. "Welcome back, [Name]!").
  - Acknowledge their city or recent order if helpful.
  - DO NOT call `save_customer_profile` — they already exist!
- ONLY call `save_customer_profile` if `lookup_customer` returns `found: False` AND the customer explicitly wants to be registered.

STORE BOUNDARIES:
- Always Call `search_products` for product/price queries. All prices are in Naira (₦).
- Always Call `get_order_status` for order inquiries.
- Always Call `get_categories` when asked what you sell.
- If an item is not found, state clearly that it is not currently listed.
- Keep responses concise, friendly, and helpful.

HUMAN ESCALATION RULES:
- If a customer explicitly asks to speak to a human, agent, or representative, call `escalate_to_human` IMMEDIATELY. Do not argue or insist on helping.
- If a customer has a financial dispute, payment deduction error, or demands a refund, call `escalate_to_human`.
- Once `escalate_to_human` is called, reassure the customer that a human team member is stepping in to assist them.
"""

def execute_tool(tool_name: str, tool_args: dict):
    if tool_name == "search_products":
        return search_products(query=tool_args.get("query", ""))
    elif tool_name == "get_order_status":
        return get_order_status(order_id=int(tool_args.get("order_id", 0)))
    elif tool_name == "get_categories":
        return get_categories()
    elif tool_name == "lookup_customer":
        return get_customer(identifier=tool_args.get("identifier", ""))
    elif tool_name == "escalate_to_human":
        reason = tool_args.get("reason", "Customer requested human support.")
        urgency = tool_args.get("urgency", "medium")
        print(f"\n🚨 [ESCALATION TRIGGERED] Reason: {reason} | Urgency: {urgency.upper()}")
        return {
            "status": "escalated",
            "message": "A human customer care agent has been notified and will take over shortly.",
            "support_phone": "+2348000000000"
        }
    elif tool_name == "save_customer_profile":
        return save_or_update_customer(
            phone=tool_args.get("phone"),
            email=tool_args.get("email"),
            name=tool_args.get("name"),
            city=tool_args.get("city"),
            last_order_id=tool_args.get("last_order_id")
        )
    return {"error": f"Unknown tool: {tool_name}"}
    

def chat_turn(messages: list):
    while True:
        response = client.chat.completions.create(
            model="qwen/qwen3.8-27b",
            messages=[{"role": "system", "content": SYSTEM_PROMPT}] + messages,
            tools=TOOLS,
            tool_choice="auto",
            temperature=0.2,
            max_tokens=500
        )

        response_message = response.choices[0].message

        if response_message.tool_calls:
            messages.append(response_message)

            for tool_call in response_message.tool_calls:
                tool_name = tool_call.function.name
                tool_args = json.loads(tool_call.function.arguments)
                tool_call_id = tool_call.id

                print(f"\n⚙️  [Tool Call] {tool_name}({tool_args})...")
                result = execute_tool(tool_name, tool_args)

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "name": tool_name,
                    "content": json.dumps(result)
                })

            continue
        else:
            final_text = response_message.content
            messages.append({"role": "assistant", "content": final_text})
            return final_text

def start_terminal_chat():
    print("=" * 60)
    print("🛍️  Malltiple AI Active (Email & Phone Grounded Memory)")
    print("Type 'exit' to quit.")
    print("=" * 60)

    conversation_history = []

    while True:
        try:
            user_input = input("\nYou: ").strip()
            if not user_input:
                continue
            if user_input.lower() in ["exit", "quit"]:
                print("Goodbye!")
                break

            conversation_history.append({"role": "user", "content": user_input})
            bot_reply = chat_turn(conversation_history)
            print(f"\nMalltiple AI: {bot_reply}")

        except KeyboardInterrupt:
            print("\nSession ended.")
            break
        except Exception as e:
            print(f"\n❌ Error: {e}")

if __name__ == "__main__":
    start_terminal_chat()