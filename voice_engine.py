import os
import re
import urllib.parse
import requests
from dotenv import load_dotenv

load_dotenv()

DEEPGRAM_KEY = os.getenv("DEEPGRAM_API_KEY")
ELEVENLABS_KEY = os.getenv("ELEVENLABS_API_KEY")
VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "EXAVITQu4vr4xnSDxMaL")

def clean_text_for_speech(text: str) -> str:
    """
    Guarantees that prices like N3,000, N 3,500, ₦68,000 are converted 
    to '3,000 Naira' so ElevenLabs NEVER pronounces the letter 'N' or 'En'.
    """
    # 1. Clean HTML entities
    text = text.replace("&#8358;", " Naira ")
    text = text.replace("&amp;", " and ")

    # 2. Catch N3000, N 3,500, ₦68000, NGN 5000 and turn into '3,000 Naira'
    text = re.sub(r'(?i)(?<![a-z])(?:[₦\u20a6]|NGN|N)\s*([0-9]+(?:,[0-9]+)*(?:\.[0-9]{1,2})?)', r'\1 Naira', text)

    # 3. Clean any leftover symbols
    text = text.replace('₦', ' Naira ').replace('\u20a6', ' Naira ')

    # 4. Remove markdown links [Text](http...) -> Text
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)

    # 5. Remove markdown symbols (*, _, ~, #, `)
    text = re.sub(r'[*_~`#]', '', text)

    # 6. Remove emojis
    text = re.sub(r'[^\w\s,.\?!;:/\-]', '', text)

    # 7. Normalize spaces
    return re.sub(r'\s+', ' ', text).strip()

def transcribe_audio_bytes(audio_bytes: bytes, mime_type: str = "audio/ogg") -> dict:
    """Sends audio to Deepgram Nova-2 with Nigerian retail keywords."""
    if not DEEPGRAM_KEY:
        return {"success": False, "error": "DEEPGRAM_API_KEY missing"}

    context_prompt = urllib.parse.quote("Malltiple is a Nigerian online shopping marketplace in Lagos selling groceries, soya oil, oats, and electronics in Naira.")
    keywords = "keywords=Malltiple:4&keywords=Naira:3&keywords=Soya:3&keywords=Quaker:3&keywords=Pringles:3"

    endpoint = f"https://api.deepgram.com/v1/listen?model=nova-2&smart_format=true&punctuate=true&language=en&prompt={context_prompt}&{keywords}"
    headers = {"Authorization": f"Token {DEEPGRAM_KEY}", "Content-Type": mime_type}

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
    """Converts cleaned text to audio using ElevenLabs."""
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
