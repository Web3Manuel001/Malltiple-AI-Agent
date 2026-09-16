import os
import re
import requests
from dotenv import load_dotenv

load_dotenv()

DEEPGRAM_KEY = os.getenv("DEEPGRAM_API_KEY")
ELEVENLABS_KEY = os.getenv("ELEVENLABS_API_KEY")

DEFAULT_VOICE_ID = "EXAVITQu4vr4xnSDxMaL"

def clean_text_for_speech(text: str) -> str:
    """
    Cleans markdown, emojis, links, and converts ₦ symbol to 'Naira' 
    so ElevenLabs pronounces it perfectly.
    """
    # 1. Convert ₦500 or ₦ 500 to '500 Naira'
    text = re.sub(r'₦\s*([0-9,]+(\.[0-9]{2})?)', r'\1 Naira', text)
    text = text.replace("₦", " Naira ")

    # 2. Convert markdown links [Text](http://...) to just 'Text'
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)

    # 3. Strip bold/italic markdown (*, _, ~)
    text = re.sub(r'[*_~`#]', '', text)

    # 4. Strip common emojis
    text = re.sub(r'[^\w\s,.\?!;:/\-₦]', '', text)

    # 5. Clean up extra spaces
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def transcribe_audio_bytes(audio_bytes: bytes, mime_type: str = "audio/ogg") -> dict:
    """
    Sends audio to Deepgram Nova-2 with Nigerian context priming and keyword boosting.
    """
    if not DEEPGRAM_KEY:
        return {"success": False, "error": "DEEPGRAM_API_KEY missing"}

    # Boost recognition for Malltiple terms & Nigerian context
    keywords = [
        "Malltiple:3",
        "Naira:3",
        "Soya:2",
        "Quaker:2",
        "Pringles:2",
        "Custard:2",
        "Lagos:2",
        "Abuja:2",
        "Paystack:2"
    ]
    keywords_param = "&".join([f"keywords={kw}" for kw in keywords])

    endpoint = (
        f"https://api.deepgram.com/v1/listen?"
        f"model=nova-2&smart_format=true&punctuate=true&{keywords_param}"
    )

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
    Converts sanitized text to an MP3 audio buffer using ElevenLabs Flash v2.5.
    """
    if not ELEVENLABS_KEY:
        raise ValueError("ELEVENLABS_API_KEY is missing in .env")

    # Clean the text so ElevenLabs speaks 'Naira' properly
    spoken_text = clean_text_for_speech(text)

    endpoint = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    headers = {
        "xi-api-key": ELEVENLABS_KEY,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg"
    }

    payload = {
        "text": spoken_text,
        "model_id": "eleven_flash_v2_5",
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