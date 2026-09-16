import os
import re
import requests
from dotenv import load_dotenv

load_dotenv()

DEEPGRAM_KEY = os.getenv("DEEPGRAM_API_KEY")
YARNGPT_KEY = os.getenv("YARNGPT_API_KEY")
DEFAULT_VOICE = os.getenv("YARNGPT_VOICE", "Idera")

def clean_text_for_speech(text: str) -> str:
    """Light cleanup: removes markdown, links, and emojis."""
    text = text.replace("&#8358;", " Naira ").replace("&amp;", " and ")

    # Ensure ₦ is spelled as Naira
    text = text.replace("₦", " Naira ")

    # Remove markdown links [Text](http...) -> Text
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)

    # Remove formatting and emojis
    text = re.sub(r'[*_~`#]', '', text)
    text = re.sub(r'[^\w\s,.\?!;:/\-]', '', text)
    return re.sub(r'\s+', ' ', text).strip()

def transcribe_audio_bytes(audio_bytes: bytes, mime_type: str = "audio/ogg") -> dict:
    """
    Optimized Deepgram Nova-2 with numerals parsing and clean acoustics.
    """
    if not DEEPGRAM_KEY:
        return {"success": False, "error": "DEEPGRAM_API_KEY missing"}

    # numerals=true ensures order numbers and prices are parsed as digits
    endpoint = (
        "https://api.deepgram.com/v1/listen?"
        "model=nova-2&smart_format=true&punctuate=true&numerals=true&language=en"
        "&keywords=Malltiple:3&keywords=Naira:2&keywords=Soya:2&keywords=Quaker:2"
    )

    headers = {
        "Authorization": f"Token {DEEPGRAM_KEY}",
        "Content-Type": mime_type
    }

    try:
        response = requests.post(endpoint, headers=headers, data=audio_bytes, timeout=12)
        if response.status_code == 200:
            data = response.json()
            transcript = data["results"]["channels"][0]["alternatives"][0]["transcript"]
            return {"success": True, "text": transcript.strip()}
        return {"success": False, "error": f"Deepgram status {response.status_code}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

def text_to_speech_bytes(text: str, voice: str = None) -> bytes:
    """
    Converts text to authentic Nigerian speech using YarnGPT.
    """
    if not YARNGPT_KEY:
        raise ValueError("YARNGPT_API_KEY is missing in .env")

    selected_voice = voice or DEFAULT_VOICE
    spoken_text = clean_text_for_speech(text)

    endpoint = "https://yarngpt.ai/api/v1/tts"
    headers = {
        "Authorization": f"Bearer {YARNGPT_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "text": spoken_text,
        "voice": selected_voice,
        "response_format": "mp3"
    }

    response = requests.post(endpoint, headers=headers, json=payload, timeout=20)
    if response.status_code == 200:
        return response.content
    else:
        raise RuntimeError(f"YarnGPT error {response.status_code}: {response.text}")
