import os
import requests
from dotenv import load_dotenv

load_dotenv()

DEEPGRAM_KEY = os.getenv("DEEPGRAM_API_KEY")
ELEVENLABS_KEY = os.getenv("ELEVENLABS_API_KEY")

# Default ElevenLabs voice (Sarah - warm, clear, professional)
# You can change this to any Nigerian/African voice ID from your ElevenLabs Voice Library!
DEFAULT_VOICE_ID = "EXAVITQu4vr4xnSDxMaL"

def transcribe_audio_bytes(audio_bytes: bytes, mime_type: str = "audio/ogg") -> dict:
    """
    Sends raw audio bytes (like Telegram voice notes) to Deepgram Nova-2 for ultra-fast transcription.
    """
    if not DEEPGRAM_KEY:
        return {"success": False, "error": "DEEPGRAM_API_KEY missing"}

    endpoint = "https://api.deepgram.com/v1/listen?model=nova-2&smart_format=true&punctuate=true"
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
        return {"success": False, "error": f"Deepgram status {response.status_code}: {response.text}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

def text_to_speech_bytes(text: str, voice_id: str = DEFAULT_VOICE_ID) -> bytes:
    """
    Converts text to an MP3 audio buffer using ElevenLabs ultra-fast Flash v2.5 model.
    """
    if not ELEVENLABS_KEY:
        raise ValueError("ELEVENLABS_API_KEY is missing in .env")

    endpoint = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    headers = {
        "xi-api-key": ELEVENLABS_KEY,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg"
    }

    payload = {
        "text": text,
        "model_id": "eleven_flash_v2_5",  # Fastest model (latency ~150ms)
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.75
        }
    }

    response = requests.post(endpoint, headers=headers, json=payload, timeout=12)
    if response.status_code == 200:
        return response.content
    else:
        raise RuntimeError(f"ElevenLabs error {response.status_code}: {response.text}")
