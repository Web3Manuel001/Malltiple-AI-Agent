import os
import re
import requests
from dotenv import load_dotenv

load_dotenv()

DEEPGRAM_KEY = os.getenv("DEEPGRAM_API_KEY")
ELEVENLABS_KEY = os.getenv("ELEVENLABS_API_KEY")
VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "EXAVITQu4vr4xnSDxMaL")

def clean_text_for_speech(text: str) -> str:
    """Cleans currency and markdown so ElevenLabs speaks prices naturally."""
    text = text.replace("&#8358;", " Naira ").replace("&amp;", " and ")

    # 1. Clean currency symbols: N3000, ₦68,000 -> 3,000 Naira
    text = re.sub(r'(?i)(?<![a-z])(?:[₦\u20a6]|NGN|N)\s*([0-9]+(?:,[0-9]+)*(?:\.[0-9]{1,2})?)', r'\1 Naira', text)
    text = text.replace('₦', ' Naira ').replace('\u20a6', ' Naira ')

    # 2. Clean markdown and emojis
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)
    text = re.sub(r'[*_~`#]', '', text)
    text = re.sub(r'[^\w\s,.\?!;:/\-]', '', text)
    return re.sub(r'\s+', ' ', text).strip()

def transcribe_audio_bytes(audio_bytes: bytes, mime_type: str = "audio/ogg") -> dict:
    """
    Clean, un-distorted Deepgram Nova-2 transcription.
    Only softly hints 'Malltiple' so it doesn't hallucinate or warp words.
    """
    if not DEEPGRAM_KEY:
        return {"success": False, "error": "DEEPGRAM_API_KEY missing"}

    # Clean, natural endpoint without heavy keyword warping
    endpoint = "https://api.deepgram.com/v1/listen?model=nova-2&smart_format=true&punctuate=true&language=en&keywords=Malltiple:2"
    headers = {
        "Authorization": f"Token {DEEPGRAM_KEY}",
        "Content-Type": mime_type
    }

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
    """Converts cleaned text to natural speech using ElevenLabs."""
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
        "model_id": "eleven_turbo_v2_5",
        "voice_settings": {
            "stability": 0.50,
            "similarity_boost": 0.75
        }
    }

    response = requests.post(endpoint, headers=headers, json=payload, timeout=12)
    if response.status_code == 200:
        return response.content
    else:
        raise RuntimeError(f"ElevenLabs error {response.status_code}: {response.text}")
