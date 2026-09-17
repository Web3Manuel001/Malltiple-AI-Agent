import os
import json
from groq import Groq
from dotenv import load_dotenv

load_dotenv()
client = Groq(api_key=os.getenv("GROQ_API_KEY"))

SUPERVISOR_PROMPT = """
You are the Chief Compliance & Anti-Fraud Security AI for Malltiple (malltiple.com.ng).
Your sole job is to audit human customer service agents' messages to detect fraud, scams, policy violations, or unethical behavior.

RED FLAG VIOLATIONS TO DETECT:
1. PERSONAL PAYMENT REDIRECTION (CRITICAL): Agent providing personal Nigerian bank account details (OPay, PalmPay, Kuda, GTB, etc.) instead of directing customer to official Malltiple checkout.
2. SENSITIVE CREDENTIAL THEFT (CRITICAL): Asking for OTP, password, Card PIN, CVV, or BVN.
3. OFF-PLATFORM REDIRECTION (HIGH): Asking customer to chat on agent's private WhatsApp or private phone.
4. UNPROFESSIONAL / ABUSIVE BEHAVIOR (MEDIUM): Insults, dismissive language, or rude behavior.

OUTPUT FORMAT:
Return strictly a JSON object with:
{
  "violation_detected": true/false,
  "risk_level": "NONE" | "MEDIUM" | "HIGH" | "CRITICAL",
  "reason": "Brief explanation of the violation",
  "evidence": "Quote the exact offending words",
  "action_required": "Immediate supervisor intervention / disciplinary action"
}
"""

def audit_human_agent_message(agent_name: str, message_text: str) -> dict:
    """
    Analyzes a message sent by a human staff member for fraud and compliance.
    """
    try:
        response = client.chat.completions.create(
            model="qwen/qwen3.8-27b",
            messages=[
                {"role": "system", "content": SUPERVISOR_PROMPT},
                {"role": "user", "content": f"Agent Name: {agent_name}\nMessage Sent to Customer: \"{message_text}\""}
            ],
            temperature=0.0,
            max_tokens=300
        )

        raw_output = response.choices[0].message.content.strip()
        
        # Clean potential markdown wrapping
        if raw_output.startswith("```json"):
            raw_output = raw_output[7:-3].strip()
        elif raw_output.startswith("```"):
            raw_output = raw_output[3:-3].strip()

        result = json.loads(raw_output)
        return result

    except Exception as e:
        return {
            "violation_detected": False,
            "error": f"Supervisor check failed: {str(e)}"
        }

# Quick test function
if __name__ == "__main__":
    print("Testing Anti-Fraud AI Supervisor...\n")
    
    # Test 1: Normal Agent Message
    test_1 = "Hello! You can complete your order using Paystack on our website."
    print("Test 1 (Clean Message):")
    print(audit_human_agent_message("Agent John", test_1))

    # Test 2: Rogue Agent Scam Attempt
    test_2 = "Website is having issues, just send the ₦15,000 to my OPay account 8012345678 and I will dispatch your shoes."
    print("\nTest 2 (Scam Attempt):")
    print(audit_human_agent_message("Agent Mark", test_2))
