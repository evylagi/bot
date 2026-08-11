import os

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8107617495:AAEjCpxJ0qVmG1m7C5rzAU_maM2t9IlnUJs")
FISH_API_KEY = os.environ.get("FISH_API_KEY", "")

BOT_NAME = "VoiceStudio Pro"
DEV_NAME = "J 🧃"
DEV_ALIAS = "Jews"
MAX_CHARS = 5000
PORT = int(os.environ.get("PORT", 8080))

VOICES_FILE = "all_voices.json"
MAX_VOICES = 999

ENABLE_API = os.environ.get("ENABLE_API", "true").lower() == "true"

VALID_API_KEYS = {
    "holdenhiscock_sk_api_e8f7d3c1a9b5f6d2": {
        "owner": "HoldenHisCock",
        "type": "user",
        "status": "active",
        "rate_limit": 50,
        "daily_limit": 1000
    }
}

REQUEST_COUNTS = {}

DEFAULT_VOICES = {
    "J The Devs🤪": {
        "name": "J the Devs🤪",
        "reference_id": "95496a7632a14321891943545846c31c",
        "emoji": "🎙️",
        "description": "Professional studio quality voice"
    },
    "dave": {
        "name": "Dave",
        "reference_id": "08bc8442f20945b4a7bce5bde11f2505",
        "emoji": "👨",
        "description": "Clear, serious, informative male voice"
    },
    "deep_dave": {
        "name": "Deep Dave",
        "reference_id": "5d992f2f63074d31a99413fdb157a565",
        "emoji": "🧘",
        "description": "Deep, meditative, calm male voice"
    },
    "calm": {
        "name": "Calm Voice",
        "reference_id": "b347db033a6549378b48d00acb0d06cd",
        "emoji": "🌊",
        "description": "Soft, gentle, soothing voice"
    },
    "dave_deep_media": {
        "name": "Dave - Male Deep Voice",
        "reference_id": "0dd3903013144408b29b7e74ca9e8614",
        "emoji": "👨",
        "description": "Male · English · Deep voice for Media and AI"
    },
    "ramsey_dave": {
        "name": "ramsey dave",
        "reference_id": "0eb1c3a354fc4c0aad24570fdb437746",
        "emoji": "👨",
        "description": "Male · English · Confident, authoritative, educational"
    }
}

EMOTIONS = {
    "happy": "[happy]",
    "sad": "[sad]",
    "angry": "[angry]",
    "excited": "[excited]",
    "calm": "[calm]",
    "laughing": "[laughing]",
    "whispering": "[whispering]",
    "serious": "[serious]",
    "friendly": "[friendly]",
    "neutral": "[neutral]"
}

LANGUAGES = {
    "af": "🇿🇦 Afrikaans", "am": "🇪🇹 Amharic", "ar": "🇸🇦 Arabic",
    "as": "🇮🇳 Assamese", "az": "🇦🇿 Azerbaijani", "be": "🇧🇾 Belarusian",
    "bg": "🇧🇬 Bulgarian", "bn": "🇧🇩 Bengali", "bodo": "🇮🇳 Bodo",
    "bs": "🇧🇦 Bosnian", "ca": "🇪🇸 Catalan", "cs": "🇨🇿 Czech",
    "cy": "🇬🇧 Welsh", "da": "🇩🇰 Danish", "de": "🇩🇪 German",
    "doi": "🇮🇳 Dogri", "el": "🇬🇷 Greek", "en": "🇬🇧 English",
    "es": "🇪🇸 Spanish", "et": "🇪🇪 Estonian", "eu": "🇪🇸 Basque",
    "fa": "🇮🇷 Persian", "fi": "🇫🇮 Finnish", "fil": "🇵🇭 Filipino",
    "fr": "🇫🇷 French", "ga": "🇮🇪 Irish", "gl": "🇪🇸 Galician",
    "gu": "🇮🇳 Gujarati", "he": "🇮🇱 Hebrew", "hi": "🇮🇳 Hindi",
    "hr": "🇭🇷 Croatian", "hu": "🇭🇺 Hungarian", "hy": "🇦🇲 Armenian",
    "id": "🇮🇩 Indonesian", "is": "🇮🇸 Icelandic", "it": "🇮🇹 Italian",
    "ja": "🇯🇵 Japanese", "ka": "🇬🇪 Georgian", "kk": "🇰🇿 Kazakh",
    "km": "🇰🇭 Khmer", "kn": "🇮🇳 Kannada", "ko": "🇰🇷 Korean",
    "kok": "🇮🇳 Konkani", "ks": "🇮🇳 Kashmiri", "lo": "🇱🇦 Lao",
    "lt": "🇱🇹 Lithuanian", "lv": "🇱🇻 Latvian", "mai": "🇮🇳 Maithili",
    "mk": "🇲🇰 Macedonian", "ml": "🇮🇳 Malayalam", "mn": "🇲🇳 Mongolian",
    "mni": "🇮🇳 Manipuri", "mr": "🇮🇳 Marathi", "ms": "🇲🇾 Malay",
    "my": "🇲🇲 Burmese", "nb": "🇳🇴 Norwegian", "ne": "🇳🇵 Nepali",
    "nl": "🇳🇱 Dutch", "or": "🇮🇳 Odia", "pa": "🇮🇳 Punjabi",
    "pl": "🇵🇱 Polish", "ps": "🇦🇫 Pashto", "pt": "🇵🇹 Portuguese",
    "ro": "🇷🇴 Romanian", "ru": "🇷🇺 Russian", "sat": "🇮🇳 Santali",
    "sd": "🇵🇰 Sindhi", "si": "🇱🇰 Sinhala", "sk": "🇸🇰 Slovak",
    "sl": "🇸🇮 Slovenian", "sq": "🇦🇱 Albanian", "sr": "🇷🇸 Serbian",
    "sv": "🇸🇪 Swedish", "sw": "🇹🇿 Swahili", "ta": "🇮🇳 Tamil",
    "te": "🇮🇳 Telugu", "tg": "🇹🇯 Tajik", "th": "🇹🇭 Thai",
    "tk": "🇹🇲 Turkmen", "tr": "🇹🇷 Turkish", "uk": "🇺🇦 Ukrainian",
    "ur": "🇵🇰 Urdu", "uz": "🇺🇿 Uzbek", "vi": "🇻🇳 Vietnamese",
    "xh": "🇿🇦 Xhosa", "zh": "🇨🇳 Chinese", "zu": "🇿🇦 Zulu"
}
