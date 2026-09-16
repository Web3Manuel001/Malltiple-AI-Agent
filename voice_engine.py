import os
import re
import urllib.parse
import requests
from dotenv import load_dotenv

load_dotenv()

DEEPGRAM_KEY = os.getenv("DEEPGRAM_API_KEY")
ELEVENLABS_KEY = os.getenv("ELEVENLABS_API_KEY")
DEFAULT_VOICE_ID = "EXAVITQu4vr4xnSDxMaL"

def clean_text_for_speech(text: str) -> str:
    """
    Catches all variations: N3000, N 3,500, ₦68,000, NGN 5000
    and converts them to '[Amount] Naira' so ElevenLabs never says 'En' or 'Naira sign'.
    """
    # 1. Clean HTML entities
    text = text.replace("&#8358;", " Naira ")
    text = text.replace("&amp;", " and ")

    # 2. Match N, ₦, or NGN followed by numbers (e.g. N3,500, N 3500, ₦68,000, NGN 5000)
    # Notice: (?<![A-Za-z]) ensures words like 'Need' or 'Nine' are NOT affected!
    currency_pattern = r'(?<![A-Za-z])(?:[₦\u20a6]|NGN|N)\s*([0-9]+(?:,[0-9]+)*(?:\.[0-9]{1,2})?)'
    text = re.sub(currency_pattern, r'\1 Naira', text, flags=re.IGNORECASE)

    # 3. Clean any leftover standalone currency symbols
    text = text.replace('₦', ' Naira ').replace('\u20a6', ' Naira ')

    # 4. Convert markdown links [Text](http...) to just Text
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)

    # 5. Remove markdown formatting (*, _, ~, #, `)
    text = re.sub(r'[*_~`#]', '', text)

    # 6. Remove emojis and unusual punctuation
    text = re.sub(r'[^\w\s,.\?!;:/\-]', '', text)

    # 7. Normalize spaces
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def transcribe_audio_bytes(audio_bytes: bytes, mime_type: str = "audio/ogg") -> dict:
    """
    Transcribes audio with Deepgram Nova-2 using contextual priming and Nigerian retail keywords.
    """
    if not DEEPGRAM_KEY:
        return {"success": False, "error": "DEEPGRAM_API_KEY missing"}

    # Context prompt teaches Deepgram what kind of speech to expect
    context_prompt = urllib.parse.quote("Malltiple is a Nigerian online e-commerce store in Lagos selling groceries, soya oil, oats, and electronics in Naira.")
    
    # Priority keywords
    keywords = [
        "Malltiple:4",
        "Naira:3",
        "Soya:3",
        "Quaker:3",
        "Pringles:3",
        "Custard:3",
        "Lagos:2",
        "Abuja:2"
    ]
    keywords_param = "&".join([f"keywords={kw}" for kw in keywords])

    endpoint = (
        f"https://api.deepgram.com/v1/listen?"
        f"model=nova-2&smart_format=true&punctuate=true&language=en&prompt={context_prompt}&{keywords_param}"
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

def text_to_speech_bytes(text: str, voice_id: str = None) -> bytes:
    """
    Converts text to natural human speech using an authentic Nigerian voice 
    and ElevenLabs Multilingual v2 engine.
    """
    if not ELEVENLABS_KEY:
        raise ValueError("ELEVENLABS_API_KEY is missing in .env")

    # Use Voice ID from .env, or fallback
    active_voice_id = voice_id or os.getenv("ELEVENLABS_VOICE_ID", DEFAULT_VOICE_ID)

    # Clean text to ensure smooth reading
    spoken_text = clean_text_for_speech(text)

    endpoint = f"https://api.elevenlabs.io/v1/text-to-speech/{active_voice_id}"
    headers = {
        "xi-api-key": ELEVENLABS_KEY,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg"
    }

    payload = {
        "text": spoken_text,
        # Multilingual v2 has maximum emotional range and native accent handling
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {
            "stability": 0.45,         # Lower stability = more human expression/inflection
            "similarity_boost": 0.85,  # Higher similarity = locks tightly onto the Nigerian accent
            "style": 0.20,             # Adds conversational warmth
            "use_speaker_boost": True
        }
    }

    response = requests.post(endpoint, headers=headers, json=payload, timeout=12)
    if response.status_code == 200:
        return response.content
    else:
        raise RuntimeError(f"ElevenLabs error {response.status_code}: {response.text}")