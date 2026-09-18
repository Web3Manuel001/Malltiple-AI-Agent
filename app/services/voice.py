import os
import re
import requests
from app.core.config import settings

def clean_text_for_speech(text: str) -> str:
    text = text.replace("&#8358;", " Naira ").replace("&amp;", " and ")
    text = re.sub(r'(?i)(?<![a-z])(?:[₦\u20a6]|NGN|N)\s*([0-9]+(?:,[0-9]+)*(?:\.[0-9]{1,2})?)', r'\1 Naira', text)
    text = text.replace('₦', ' Naira ').replace('\u20a6', ' Naira ')
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)
    text = re.sub(r'[*_~`#]', '', text)
    text = re.sub(r'[^\w\s,.\?!;:/\-]', '', text)
    return re.sub(r'\s+', ' ', text).strip()

def transcribe_audio_bytes(audio_bytes: bytes, mime_type: str = "audio/ogg") -> dict:
    if not settings.DEEPGRAM_API_KEY:
        return {"success": False, "error": "DEEPGRAM_API_KEY missing"}

    endpoint = "https://api.deepgram.com/v1/listen?model=nova-2&smart_format=true&punctuate=true&language=en&keywords=Malltiple:2"
    headers = {"Authorization": f"Token {settings.DEEPGRAM_API_KEY}", "Content-Type": mime_type}

    try:
        response = requests.post(endpoint, headers=headers, data=audio_bytes, timeout=8)
        if response.status_code == 200:
            data = response.json()
            transcript = data["results"]["channels"][0]["alternatives"][0]["transcript"]
            return {"success": True, "text": transcript.strip()}
        return {"success": False, "error": f"Deepgram status {response.status_code}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

def text_to_speech_bytes(text: str, voice: str = None) -> bytes:
    if not settings.YARNGPT_API_KEY:
        raise ValueError("YARNGPT_API_KEY is missing")

    selected_voice = voice or settings.YARNGPT_VOICE or "Idera"
    spoken_text = clean_text_for_speech(text)

    endpoint = "https://yarngpt.ai/api/v1/tts"
    headers = {
        "Authorization": f"Bearer {settings.YARNGPT_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "text": spoken_text,
        "voice": selected_voice,
        "response_format": "mp3"
    }

    # Strict 10s timeout so the voice call never hangs
    response = requests.post(endpoint, headers=headers, json=payload, timeout=10)
    if response.status_code == 200:
        return response.content
    else:
        raise RuntimeError(f"YarnGPT error {response.status_code}: {response.text}")
