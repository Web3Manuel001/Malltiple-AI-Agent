import os
import re
import urllib.parse
import requests
from dotenv import load_dotenv

load_dotenv()

DEEPGRAM_KEY = os.getenv("DEEPGRAM_API_KEY")
ELEVENLABS_KEY = os.getenv("ELEVENLABS_API_KEY")
VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "EXAVITQu4vr4xnSDxMaL")

def number_to_words(val: int) -> str:
    """Converts a number like 8500 into 'eight thousand five hundred'."""
    units = ["", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]
    teens = ["ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
    tens = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]

    if val == 0:
        return "zero"

    def two_digits(n):
        if n < 10:
            return units[n]
        elif 10 <= n < 20:
            return teens[n - 10]
        else:
            return tens[n // 10] + ("-" + units[n % 10] if n % 10 != 0 else "")

    def three_digits(n):
        res = ""
        if n >= 100:
            res += units[n // 100] + " hundred"
            n %= 100
            if n > 0:
                res += " and "
        if n > 0:
            res += two_digits(n)
        return res

    temp = val
    parts = []
    if temp >= 1000000:
        parts.append(three_digits(temp // 1000000) + " million")
        temp %= 1000000
    if temp >= 1000:
        parts.append(three_digits(temp // 1000) + " thousand")
        temp %= 1000
    if temp > 0:
        parts.append(three_digits(temp))

    return " ".join(parts).strip()

def _price_words_replacer(match):
    num_str = match.group(1).replace(",", "")
    try:
        val = int(float(num_str))
        words = number_to_words(val)
        return f"{words} Naira"
    except Exception:
        return match.group(0)

def clean_text_for_speech(text: str) -> str:
    """
    Cleans text and expands numbers to spoken words so 8,500 is read as
    'eight thousand five hundred Naira' (never 'eighty-five hundred').
    """
    text = text.replace("&#8358;", " Naira ").replace("&amp;", " and ")

    # 1. Normalize currency symbols: N3000, ₦68,000 -> 3000 Naira
    text = re.sub(r'(?i)(?<![a-z])(?:[₦\u20a6]|NGN|N)\s*([0-9]+(?:,[0-9]+)*(?:\.[0-9]{1,2})?)', r'\1 Naira', text)
    text = text.replace('₦', ' Naira ').replace('\u20a6', ' Naira ')

    # 2. Expand prices like '8,500 Naira' to 'eight thousand five hundred Naira'
    text = re.sub(r'([0-9]+(?:,[0-9]+)*(?:\.[0-9]{1,2})?)\s*Naira', _price_words_replacer, text, flags=re.IGNORECASE)

    # 3. Clean markdown and symbols
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)
    text = re.sub(r'[*_~`#]', '', text)
    text = re.sub(r'[^\w\s,.\?!;:/\-]', '', text)
    return re.sub(r'\s+', ' ', text).strip()

def transcribe_audio_bytes(audio_bytes: bytes, mime_type: str = "audio/ogg") -> dict:
    """Sends audio to Deepgram Nova-2 with Nigerian retail keywords."""
    if not DEEPGRAM_KEY:
        return {"success": False, "error": "DEEPGRAM_API_KEY missing"}

    context = (
        "Malltiple Nigerian online shopping marketplace in Lagos and Abuja. "
        "Customer inquiries about groceries, prices, soya oil, quaker oats, custard, "
        "pringles, biscuits, delivery, and orders in Naira."
    )
    context_prompt = urllib.parse.quote(context)

    boosted_keywords = [
        "Malltiple:5", "Naira:4", "Soya:4", "Quaker:4", "Oats:4", "Pringles:4",
        "Custard:3", "Lagos:3", "Abuja:3", "Indomie:3", "Paystack:3", "keg:3",
        "pouch:3", "carton:3", "dispatch:3", "delivery:3", "how much:3"
    ]
    keywords_param = "&".join([f"keywords={kw}" for kw in boosted_keywords])

    endpoint = (
        f"https://api.deepgram.com/v1/listen?"
        f"model=nova-2&smart_format=true&punctuate=true&language=en&"
        f"prompt={context_prompt}&{keywords_param}"
    )

    headers = {"Authorization": f"Token {DEEPGRAM_KEY}", "Content-Type": "audio/ogg"}

    try:
        response = requests.post(endpoint, headers=headers, data=audio_bytes, timeout=10)
        if response.status_code == 200:
            data = response.json()
            transcript = data["results"]["channels"][0]["alternatives"][0]["transcript"]
            return {"success": True, "text": transcript.strip()}
        return {"success": False, "error": f"Deepgram status {response.status_code}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

def text_to_speech_bytes(text: str, voice_id: str = None) -> bytes:
    """Converts cleaned text to natural human speech using ElevenLabs."""
    if not ELEVENLABS_KEY:
        raise ValueError("ELEVENLABS_API_KEY is missing in .env")

    active_voice = voice_id or VOICE_ID
    spoken_text = clean_text_for_speech(text)

    endpoint = f"https://api.elevenlabs.io/v1/text-to-speech/{active_voice}"
    headers = {
        "xi-api-key": ELEVENLABS_KEY,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg"
    }

    payload = {
        "text": spoken_text,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {
            "stability": 0.45,
            "similarity_boost": 0.85,
            "style": 0.20
        }
    }

    response = requests.post(endpoint, headers=headers, json=payload, timeout=12)
    if response.status_code == 200:
        return response.content
    else:
        raise RuntimeError(f"ElevenLabs error {response.status_code}: {response.text}")
