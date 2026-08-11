import os
import sys
import logging
import requests
import tempfile
import signal
import json
from datetime import datetime
from flask import Flask, request, jsonify, send_file
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from config import (
    TELEGRAM_TOKEN, FISH_API_KEY, BOT_NAME, DEV_NAME, DEV_ALIAS,
    MAX_CHARS, PORT, VOICES_FILE, MAX_VOICES, DEFAULT_VOICES, EMOTIONS, LANGUAGES,
    ENABLE_API, VALID_API_KEYS, REQUEST_COUNTS
)

flask_app = Flask(__name__)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def validate_api_key():
    if not ENABLE_API:
        return True
    
    api_key = request.headers.get('X-API-Key') or request.headers.get('Authorization', '').replace('Bearer ', '')
    
    if not api_key or api_key not in VALID_API_KEYS:
        return False
    
    key_info = VALID_API_KEYS[api_key]
    if key_info.get('status') != 'active':
        return False
    
    rate_limit = key_info.get('rate_limit', 50)
    daily_limit = key_info.get('daily_limit', 1000)
    
    if api_key not in REQUEST_COUNTS:
        REQUEST_COUNTS[api_key] = {
            'minute': 0,
            'day': 0,
            'minute_reset': datetime.now(),
            'day_reset': datetime.now()
        }
    
    now = datetime.now()
    counter = REQUEST_COUNTS[api_key]
    
    if (now - counter['minute_reset']).seconds >= 60:
        counter['minute'] = 0
        counter['minute_reset'] = now
    
    if (now - counter['day_reset']).days >= 1:
        counter['day'] = 0
        counter['day_reset'] = now
    
    if counter['minute'] >= rate_limit or counter['day'] >= daily_limit:
        return False
    
    counter['minute'] += 1
    counter['day'] += 1
    
    return True

def require_api_key(f):
    def decorated_function(*args, **kwargs):
        if not validate_api_key():
            return jsonify({
                "success": False,
                "error": "Invalid or rate-limited API key",
                "code": "AUTH_REQUIRED"
            }), 401
        return f(*args, **kwargs)
    decorated_function.__name__ = f.__name__
    return decorated_function

def is_emotions_enabled(api_key):
    """Check if emotions are enabled for this API key"""
    if api_key in VALID_API_KEYS:
        return VALID_API_KEYS[api_key].get('emotions_enabled', False)
    return False

@flask_app.route('/')
def health_check():
    return "Bot is running!", 200

@flask_app.route('/health')
def health():
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "version": "3.0",
        "total_voices": len(VOICE_ARTISTS) if 'VOICE_ARTISTS' in globals() else 0,
        "supported_languages": len(LANGUAGES),
        "api_keys": len(VALID_API_KEYS),
        "emotions_enabled": False
    }, 200

@flask_app.route('/api/voices', methods=['GET'])
@require_api_key
def api_get_voices():
    try:
        page = int(request.args.get('page', 1))
        limit = min(int(request.args.get('limit', 10)), 50)
        search = request.args.get('search', '')
        
        voices_list = []
        for key, voice in VOICE_ARTISTS.items():
            voices_list.append({
                "id": key,
                "name": voice['name'],
                "reference_id": voice['reference_id'],
                "emoji": voice['emoji'],
                "description": voice['description'],
                "is_default": key in DEFAULT_VOICES
            })
        
        if search:
            search_lower = search.lower()
            voices_list = [
                v for v in voices_list 
                if search_lower in v['name'].lower() or search_lower in v['description'].lower()
            ]
        
        total = len(voices_list)
        total_pages = (total + limit - 1) // limit
        start = (page - 1) * limit
        end = min(start + limit, total)
        
        return jsonify({
            "success": True,
            "data": {
                "total": total,
                "page": page,
                "limit": limit,
                "total_pages": total_pages,
                "voices": voices_list[start:end],
                "emotions_enabled": False
            }
        }), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@flask_app.route('/api/voice/<voice_id>', methods=['GET'])
@require_api_key
def api_get_voice(voice_id):
    try:
        if voice_id not in VOICE_ARTISTS:
            return jsonify({"success": False, "error": "Voice not found", "code": "VOICE_NOT_FOUND"}), 404
        
        voice = VOICE_ARTISTS[voice_id]
        return jsonify({
            "success": True,
            "data": {
                "id": voice_id,
                "name": voice['name'],
                "reference_id": voice['reference_id'],
                "emoji": voice['emoji'],
                "description": voice['description'],
                "is_default": voice_id in DEFAULT_VOICES,
                "emotions_enabled": False
            }
        }), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@flask_app.route('/api/tts', methods=['POST'])
@require_api_key
def api_generate_tts():
    try:
        data = request.get_json()
        api_key = request.headers.get('X-API-Key') or request.headers.get('Authorization', '').replace('Bearer ', '')
        
        if not data or 'text' not in data:
            return jsonify({"success": False, "error": "Missing 'text'", "code": "INVALID_TEXT"}), 400
        
        text = data['text']
        if len(text) > MAX_CHARS:
            return jsonify({"success": False, "error": f"Text exceeds {MAX_CHARS}", "code": "TEXT_TOO_LONG"}), 400
        
        voice_id = data.get('voice_id', 'studio_pro')
        if voice_id not in VOICE_ARTISTS:
            return jsonify({"success": False, "error": "Voice not found", "code": "VOICE_NOT_FOUND"}), 404
        
        language = data.get('language', 'en')
        if language not in LANGUAGES:
            return jsonify({"success": False, "error": "Language not supported", "code": "LANGUAGE_NOT_SUPPORTED"}), 400
        
        # Check if emotions are enabled for this API key
        if is_emotions_enabled(api_key):
            emotion = data.get('emotion', 'neutral')
            if emotion in EMOTIONS:
                text = f"{EMOTIONS[emotion]} {text}"
        else:
            # Emotions are disabled - remove any emotion tags from text
            for emotion_tag in EMOTIONS.values():
                text = text.replace(emotion_tag, '')
            text = text.strip()
        
        voice = VOICE_ARTISTS[voice_id]
        audio_file = generate_voice(text, voice['reference_id'])
        
        if audio_file and os.path.exists(audio_file):
            return send_file(
                audio_file,
                as_attachment=True,
                download_name=f"speech_{datetime.now().timestamp()}.mp3",
                mimetype="audio/mpeg"
            )
        else:
            return jsonify({"success": False, "error": "Failed to generate audio", "code": "AUDIO_GENERATION_FAILED"}), 500
            
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@flask_app.route('/api/tts/advanced', methods=['POST'])
@require_api_key
def api_generate_tts_advanced():
    try:
        data = request.get_json()
        api_key = request.headers.get('X-API-Key') or request.headers.get('Authorization', '').replace('Bearer ', '')
        
        if not data or 'text' not in data or 'voice_reference_id' not in data:
            return jsonify({"success": False, "error": "Missing parameters", "code": "INVALID_PARAMS"}), 400
        
        text = data['text']
        voice_reference_id = data['voice_reference_id']
        
        if len(text) > MAX_CHARS:
            return jsonify({"success": False, "error": f"Text exceeds {MAX_CHARS}", "code": "TEXT_TOO_LONG"}), 400
        
        # Check if emotions are enabled for this API key
        if not is_emotions_enabled(api_key):
            # Emotions are disabled - remove any emotion tags from text
            for emotion_tag in EMOTIONS.values():
                text = text.replace(emotion_tag, '')
            text = text.strip()
        
        audio_file = generate_voice(text, voice_reference_id)
        
        if audio_file and os.path.exists(audio_file):
            return jsonify({
                "success": True,
                "data": {
                    "audio_url": f"https://bot-production-aba4.up.railway.app/api/audio/{os.path.basename(audio_file)}",
                    "format": "mp3",
                    "size_bytes": os.path.getsize(audio_file),
                    "emotions_enabled": False
                }
            }), 200
        else:
            return jsonify({"success": False, "error": "Failed to generate audio", "code": "AUDIO_GENERATION_FAILED"}), 500
            
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@flask_app.route('/api/languages', methods=['GET'])
@require_api_key
def api_get_languages():
    try:
        return jsonify({
            "success": True,
            "data": {
                "total": len(LANGUAGES),
                "languages": LANGUAGES
            }
        }), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@flask_app.route('/api/emotions', methods=['GET'])
@require_api_key
def api_get_emotions():
    try:
        api_key = request.headers.get('X-API-Key') or request.headers.get('Authorization', '').replace('Bearer ', '')
        
        if is_emotions_enabled(api_key):
            emotion_list = {
                "happy": "[happy] - Cheerful, joyful tone",
                "sad": "[sad] - Melancholic, emotional tone",
                "angry": "[angry] - Intense, firm tone",
                "excited": "[excited] - Energetic, enthusiastic",
                "calm": "[calm] - Relaxed, soothing tone",
                "laughing": "[laughing] - Laughing while speaking",
                "whispering": "[whispering] - Soft, whispered voice",
                "serious": "[serious] - Professional, serious tone",
                "friendly": "[friendly] - Warm, inviting tone",
                "neutral": "[neutral] - Balanced, natural tone"
            }
            return jsonify({
                "success": True,
                "data": {
                    "emotions": emotion_list,
                    "emotions_enabled": True
                }
            }), 200
        else:
            return jsonify({
                "success": True,
                "data": {
                    "emotions": {},
                    "emotions_enabled": False,
                    "message": "Emotions are disabled for this API key"
                }
            }), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@flask_app.route('/api/sample', methods=['POST'])
@require_api_key
def api_generate_sample():
    try:
        data = request.get_json() or {}
        api_key = request.headers.get('X-API-Key') or request.headers.get('Authorization', '').replace('Bearer ', '')
        
        voice_id = data.get('voice_id', 'studio_pro')
        language = data.get('language', 'en')
        
        if voice_id not in VOICE_ARTISTS:
            return jsonify({"success": False, "error": "Voice not found", "code": "VOICE_NOT_FOUND"}), 404
        
        voice = VOICE_ARTISTS[voice_id]
        sample_texts = {
            "en": f"Hello! Welcome to {BOT_NAME}! This is the {voice['name']} voice.",
            "zh": f"你好！欢迎来到 {BOT_NAME}！这是{voice['name']}的声音。",
            "ja": f"こんにちは！{BOT_NAME}へようこそ！これは{voice['name']}の声です。",
            "es": f"¡Hola! ¡Bienvenido a {BOT_NAME}! Esta es la voz de {voice['name']}.",
        }
        sample_text = sample_texts.get(language, sample_texts["en"])
        
        # Remove any emotion tags if emotions are disabled
        if not is_emotions_enabled(api_key):
            for emotion_tag in EMOTIONS.values():
                sample_text = sample_text.replace(emotion_tag, '')
            sample_text = sample_text.strip()
        
        audio_file = generate_voice(sample_text, voice['reference_id'])
        
        if audio_file and os.path.exists(audio_file):
            return send_file(
                audio_file,
                as_attachment=True,
                download_name=f"sample_{datetime.now().timestamp()}.mp3",
                mimetype="audio/mpeg"
            )
        else:
            return jsonify({"success": False, "error": "Failed to generate sample", "code": "SAMPLE_GENERATION_FAILED"}), 500
            
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

def load_voices_from_json():
    try:
        voice_artists = dict(DEFAULT_VOICES)
        logger.info(f"✅ Loaded {len(DEFAULT_VOICES)} default voices")
        
        if os.path.exists(VOICES_FILE):
            logger.info(f"📂 Loading voices from {VOICES_FILE}...")
            
            with open(VOICES_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
                if 'models' in data:
                    voices_data = data.get('models', [])
                elif 'voices' in data:
                    voices_data = data.get('voices', [])
                else:
                    voices_data = data.get('items', [])
                
                if not voices_data:
                    logger.warning(f"⚠️ No voices found in {VOICES_FILE}")
                    return voice_artists
                
                logger.info(f"📊 Found {len(voices_data)} voices in JSON file")
                
                json_count = 0
                for i, voice in enumerate(voices_data[:MAX_VOICES]):
                    voice_id = voice.get('_id') or voice.get('id') or voice.get('reference_id')
                    if not voice_id:
                        continue
                    
                    title = voice.get('title') or voice.get('name') or f'Voice {i+1}'
                    language = voice.get('language', 'Unknown')
                    gender = voice.get('gender', 'Unknown')
                    description = voice.get('description', f'{gender} voice in {language}')
                    
                    if any(v.get('reference_id') == voice_id for v in voice_artists.values()):
                        continue
                    
                    emoji = "🎙️"
                    if gender.lower() in ['male', 'm']:
                        emoji = "👨"
                    elif gender.lower() in ['female', 'f']:
                        emoji = "👩"
                    
                    key = f"json_voice_{i+1}"
                    voice_artists[key] = {
                        "name": title[:30],
                        "reference_id": voice_id,
                        "emoji": emoji,
                        "description": f"{gender} · {language} · {description[:50]}",
                        "full_data": voice,
                        "is_default": False
                    }
                    json_count += 1
                
                logger.info(f"✅ Added {json_count} voices from JSON")
                logger.info(f"🎤 Total voices: {len(voice_artists)}")
                return voice_artists
        else:
            logger.warning(f"⚠️ {VOICES_FILE} not found. Using default voices only.")
            return voice_artists
            
    except Exception as e:
        logger.error(f"❌ Error loading voices: {e}")
        return DEFAULT_VOICES

VOICE_ARTISTS = load_voices_from_json()

def generate_voice(text, reference_id):
    try:
        response = requests.post(
            "https://api.fish.audio/v1/tts",
            headers={
                "Authorization": f"Bearer {FISH_API_KEY}",
                "Content-Type": "application/json",
                "model": "s2.1-pro-free",
            },
            json={
                "text": text,
                "reference_id": reference_id,
                "format": "mp3",
            },
            timeout=60
        )
        if response.status_code == 200:
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
            temp_file.write(response.content)
            temp_file.close()
            return temp_file.name
        else:
            logger.error(f"API Error: {response.status_code}")
            return None
    except Exception as e:
        logger.error(f"Error: {e}")
        return None

class VoiceBot:
    def __init__(self):
        self.user_voices = {}
        self.user_languages = {}
        self.start_time = datetime.now()
        self.voice_pages = {}
        self.lang_pages = {}
        self.search_pages = {}
        self.search_results = {}

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        welcome_text = f"""
🎙️ *Welcome to {BOT_NAME}*

🌍 Supports 83 languages!
🎤 {len(VOICE_ARTISTS)} premium voice artists

*How to use:*
1. Set your language with /language
2. Choose your voice with /voice or /search
3. Send text to convert to voice!

*Commands:*
/language - Set your language
/voice - Browse all voices
/search [name] - Search for voices
/sample - Hear a demo
/voices - List all available voices

---
✨ *Developer:* {DEV_NAME}
        """
        await update.message.reply_text(welcome_text, parse_mode='Markdown')

    async def voices_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        voices_text = f"🎤 *Available Voices ({len(VOICE_ARTISTS)} total)*\n\n"
        
        default_count = 0
        json_count = 0
        
        for key, voice in VOICE_ARTISTS.items():
            if key in DEFAULT_VOICES:
                default_count += 1
                voices_text += f"⭐ {voice['emoji']} *{voice['name']}* (Default)\n"
                voices_text += f"   {voice['description']}\n\n"
        
        for key, voice in VOICE_ARTISTS.items():
            if key not in DEFAULT_VOICES:
                if json_count < 20:
                    voices_text += f"   {voice['emoji']} {voice['name']}\n"
                json_count += 1
        
        if json_count > 20:
            voices_text += f"\n... and {json_count - 20} more voices from library\n"
        
        voices_text += f"\n⭐ = Default Voice ({default_count} always available)"
        voices_text += f"\n📌 Use /voice to browse all voices with pagination"
        await update.message.reply_text(voices_text, parse_mode='Markdown')

    async def show_search_page(self, update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: str, page: int, query: str):
        if user_id in self.search_results and self.search_results[user_id] and self.search_results[user_id].get('query') == query:
            results = self.search_results[user_id]['results']
        else:
            results = []
            query_lower = query.lower()
            
            for key, voice in VOICE_ARTISTS.items():
                name = voice['name'].lower()
                desc = voice['description'].lower()
                if query_lower in name or query_lower in desc:
                    is_default = key in DEFAULT_VOICES
                    results.append((key, voice, is_default))
            
            results.sort(key=lambda x: (not x[2], x[1]['name'].lower()))
            
            self.search_results[user_id] = {
                'query': query,
                'results': results
            }
        
        if not results:
            if update.callback_query:
                await update.callback_query.edit_message_text(
                    f"❌ No voices found for '{query}'\n\nTry different keywords!",
                    parse_mode='Markdown'
                )
            else:
                await update.message.reply_text(
                    f"❌ No voices found for '{query}'\n\nTry different keywords!",
                    parse_mode='Markdown'
                )
            return
        
        items_per_page = 5
        total_pages = (len(results) + items_per_page - 1) // items_per_page
        
        if page < 0:
            page = 0
        elif page >= total_pages:
            page = total_pages - 1
        
        self.search_pages[user_id] = page
        start_idx = page * items_per_page
        end_idx = min(start_idx + items_per_page, len(results))
        
        keyboard = []
        for key, voice, is_default in results[start_idx:end_idx]:
            label = f"{'⭐ ' if is_default else ''}{voice['emoji']} {voice['name']}"
            keyboard.append([InlineKeyboardButton(
                label,
                callback_data=f"search_select_{key}"
            )])
        
        nav_row = []
        if page > 0:
            nav_row.append(InlineKeyboardButton("◀️ Previous", callback_data="search_page_prev"))
        if page < total_pages - 1:
            nav_row.append(InlineKeyboardButton("Next ▶️", callback_data="search_page_next"))
        if nav_row:
            keyboard.append(nav_row)
        
        keyboard.append([InlineKeyboardButton("🎤 Back to All Voices", callback_data="search_back_to_voice")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        text = f"🔍 *Search Results for \"{query}\"*\n\n"
        text += f"Found {len(results)} voices:\n"
        text += f"Page {page + 1}/{total_pages}\n\n"
        
        for key, voice, is_default in results[start_idx:end_idx]:
            text += f"{'⭐ ' if is_default else ''}{voice['emoji']} *{voice['name']}*"
            if is_default:
                text += " *(Default)*"
            text += f"\n   {voice['description']}\n"
            text += f"   📌 Click to select\n\n"
        
        if update.callback_query:
            await update.callback_query.edit_message_text(
                text,
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
        else:
            await update.message.reply_text(
                text,
                parse_mode='Markdown',
                reply_markup=reply_markup
            )

    async def search_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = str(update.effective_user.id)
        query = ' '.join(context.args) if context.args else ''
        
        if not query:
            await update.message.reply_text(
                "🔍 *How to search for voices:*\n\n"
                "Type: `/search narrator`\n"
                "Type: `/search female`\n"
                "Type: `/search spanish`\n"
                "Type: `/search dave`\n\n"
                "⭐ Default voices are shown first!\n"
                "Try searching for voice names, languages, or descriptions!\n"
                "You can also browse all voices with `/voice`",
                parse_mode='Markdown'
            )
            return
        
        self.search_results[user_id] = None
        await self.show_search_page(update, context, user_id, 0, query)

    async def show_voice_page(self, update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: str, page: int):
        voice_keys = list(VOICE_ARTISTS.keys())
        if not voice_keys:
            await update.message.reply_text("❌ No voices available.")
            return
            
        current_voice = self.user_voices.get(user_id, next(iter(DEFAULT_VOICES.keys())) if DEFAULT_VOICES else voice_keys[0])
        items_per_page = 10
        total_pages = (len(voice_keys) + items_per_page - 1) // items_per_page
        
        if page < 0:
            page = 0
        elif page >= total_pages:
            page = total_pages - 1
        
        self.voice_pages[user_id] = page
        start_idx = page * items_per_page
        end_idx = min(start_idx + items_per_page, len(voice_keys))
        
        keyboard = []
        for key in voice_keys[start_idx:end_idx]:
            voice = VOICE_ARTISTS[key]
            is_current = " ✅" if key == current_voice else ""
            is_default = " ⭐" if key in DEFAULT_VOICES else ""
            keyboard.append([InlineKeyboardButton(
                f"{voice['emoji']} {voice['name']}{is_default}{is_current}",
                callback_data=f"voice_{key}"
            )])
        
        nav_row = []
        if page > 0:
            nav_row.append(InlineKeyboardButton("◀️ Previous", callback_data="voice_page_prev"))
        if page < total_pages - 1:
            nav_row.append(InlineKeyboardButton("Next ▶️", callback_data="voice_page_next"))
        if nav_row:
            keyboard.append(nav_row)
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        current = VOICE_ARTISTS.get(current_voice, list(VOICE_ARTISTS.values())[0] if VOICE_ARTISTS else {"name": "Unknown", "description": ""})
        
        default_count = len(DEFAULT_VOICES)
        
        text = f"🎤 *Select Voice Artist*\n\n"
        text += f"Current: {current['name']}\n"
        text += f"{current['description']}\n"
        text += f"⭐ = Default Voice ({default_count} available)\n"
        text += f"Page {page + 1}/{total_pages}"
        
        if update.callback_query:
            await update.callback_query.edit_message_text(
                text,
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
        else:
            await update.message.reply_text(
                text,
                parse_mode='Markdown',
                reply_markup=reply_markup
            )

    async def show_language_page(self, update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: str, page: int):
        current_lang = self.user_languages.get(user_id, "en")
        lang_codes = sorted(LANGUAGES.keys())
        items_per_page = 20
        total_pages = (len(lang_codes) + items_per_page - 1) // items_per_page
        
        if page < 0:
            page = 0
        elif page >= total_pages:
            page = total_pages - 1
        
        self.lang_pages[user_id] = page
        start_idx = page * items_per_page
        end_idx = min(start_idx + items_per_page, len(lang_codes))
        
        keyboard = []
        for code in lang_codes[start_idx:end_idx]:
            if code in LANGUAGES:
                is_current = " ✅" if code == current_lang else ""
                keyboard.append([InlineKeyboardButton(
                    f"{LANGUAGES[code]}{is_current}",
                    callback_data=f"lang_{code}"
                )])
        
        nav_row = []
        if page > 0:
            nav_row.append(InlineKeyboardButton("◀️ Previous", callback_data="lang_page_prev"))
        if page < total_pages - 1:
            nav_row.append(InlineKeyboardButton("Next ▶️", callback_data="lang_page_next"))
        if nav_row:
            keyboard.append(nav_row)
        
        keyboard.append([InlineKeyboardButton("📚 View All Languages", callback_data="view_all_langs")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        current_display = LANGUAGES.get(current_lang, "English")
        
        text = f"🌍 *Select Your Language*\n\nCurrent: {current_display}\nPage {page + 1}/{total_pages}"
        
        if update.callback_query:
            await update.callback_query.edit_message_text(
                text,
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
        else:
            await update.message.reply_text(
                text,
                parse_mode='Markdown',
                reply_markup=reply_markup
            )

    async def language_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = str(update.effective_user.id)
        page = self.lang_pages.get(user_id, 0)
        await self.show_language_page(update, context, user_id, page)

    async def voice_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = str(update.effective_user.id)
        page = self.voice_pages.get(user_id, 0)
        await self.show_voice_page(update, context, user_id, page)

    async def sample_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = str(update.effective_user.id)
        voice_keys = list(VOICE_ARTISTS.keys())
        voice_key = self.user_voices.get(user_id, next(iter(DEFAULT_VOICES.keys())) if DEFAULT_VOICES else voice_keys[0] if voice_keys else "studio_pro")
        voice = VOICE_ARTISTS.get(voice_key, list(VOICE_ARTISTS.values())[0] if VOICE_ARTISTS else {"name": "Studio Pro", "reference_id": "95496a7632a14321891943545846c31c"})
        lang = self.user_languages.get(user_id, "en")
        lang_name = LANGUAGES.get(lang, "English")
        await update.message.reply_text(f"🎵 Generating sample in {lang_name} with {voice['emoji']} {voice['name']}...")
        sample_texts = {
            "en": f"Hello! Welcome to {BOT_NAME}! This is the {voice['name']} voice.",
            "zh": f"你好！欢迎来到 {BOT_NAME}！这是{voice['name']}的声音。",
            "ja": f"こんにちは！{BOT_NAME}へようこそ！これは{voice['name']}の声です。",
            "es": f"¡Hola! ¡Bienvenido a {BOT_NAME}! Esta es la voz de {voice['name']}.",
        }
        sample_text = sample_texts.get(lang, sample_texts["en"])
        audio_file = generate_voice(sample_text, voice['reference_id'])
        if audio_file and os.path.exists(audio_file):
            with open(audio_file, 'rb') as audio:
                await update.message.reply_voice(
                    voice=audio,
                    caption=f"🎧 *Sample in {lang_name}*\n{voice['emoji']} {voice['name']}\n✨ {DEV_NAME}",
                    parse_mode='Markdown'
                )
            os.unlink(audio_file)
        else:
            await update.message.reply_text("❌ Failed. Please try again.")

    async def about_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        uptime = datetime.now() - self.start_time
        hours = uptime.seconds // 3600
        minutes = (uptime.seconds % 3600) // 60
        default_count = len(DEFAULT_VOICES)
        total_count = len(VOICE_ARTISTS)
        about_text = f"""
ℹ️ *About {BOT_NAME}*

*Version:* 3.0
*Developer:* {DEV_NAME}
*Languages:* 83 supported
*Voice Artists:* {total_count} total
*Default Voices:* {default_count} always available
*Max Characters:* {MAX_CHARS}
*Uptime:* {hours}h {minutes}m

*Features:*
• 83 languages
• {total_count} premium voice artists
• Studio quality audio

Made with ❤️ by {DEV_NAME}
        """
        await update.message.reply_text(about_text, parse_mode='Markdown')

    async def handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = str(update.effective_user.id)
        text = update.message.text
        if len(text) > MAX_CHARS:
            await update.message.reply_text(f"⚠️ Text exceeds {MAX_CHARS} characters.")
            return
        voice_keys = list(VOICE_ARTISTS.keys())
        voice_key = self.user_voices.get(user_id, next(iter(DEFAULT_VOICES.keys())) if DEFAULT_VOICES else voice_keys[0] if voice_keys else "studio_pro")
        voice = VOICE_ARTISTS.get(voice_key, list(VOICE_ARTISTS.values())[0] if VOICE_ARTISTS else {"name": "Studio Pro", "reference_id": "95496a7632a14321891943545846c31c"})
        lang = self.user_languages.get(user_id, "en")
        lang_name = LANGUAGES.get(lang, "English")
        
        # Remove emotion tags from text for API users
        for emotion_tag in EMOTIONS.values():
            text = text.replace(emotion_tag, '')
        text = text.strip()
        
        processing = await update.message.reply_text(
            f"🎵 Converting to voice ({voice['emoji']} {voice['name']})\n🌍 Language: {lang_name}"
        )
        audio_file = generate_voice(text, voice['reference_id'])
        if audio_file and os.path.exists(audio_file):
            with open(audio_file, 'rb') as audio:
                caption = f"🎧 *{voice['emoji']} {voice['name']}*\n🌍 {lang_name} · 📝 {len(text)} chars\n✨ {DEV_NAME}"
                await update.message.reply_voice(
                    voice=audio,
                    caption=caption,
                    parse_mode='Markdown'
                )
            os.unlink(audio_file)
            await processing.delete()
        else:
            await processing.edit_text("❌ Failed to generate voice. Please try again.")

    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        user_id = str(update.effective_user.id)
        data = query.data

        if data.startswith("search_select_"):
            voice_key = data.replace("search_select_", "")
            if voice_key in VOICE_ARTISTS:
                self.user_voices[user_id] = voice_key
                voice = VOICE_ARTISTS[voice_key]
                is_default = "⭐ Default Voice! " if voice_key in DEFAULT_VOICES else ""
                await query.edit_message_text(
                    f"✅ Voice changed to: {voice['emoji']} *{voice['name']}*\n{is_default}{voice['description']}\n\nSend any text to hear this voice!",
                    parse_mode='Markdown'
                )
            else:
                await query.edit_message_text(
                    f"❌ Voice not found. Please try again.",
                    parse_mode='Markdown'
                )

        elif data == "search_page_next":
            current_page = self.search_pages.get(user_id, 0)
            new_page = current_page + 1
            if user_id in self.search_results and self.search_results[user_id]:
                query_text = self.search_results[user_id]['query']
                await self.show_search_page(update, context, user_id, new_page, query_text)
            else:
                await query.edit_message_text(
                    "❌ Search results expired. Please search again with /search",
                    parse_mode='Markdown'
                )

        elif data == "search_page_prev":
            current_page = self.search_pages.get(user_id, 0)
            new_page = max(0, current_page - 1)
            if user_id in self.search_results and self.search_results[user_id]:
                query_text = self.search_results[user_id]['query']
                await self.show_search_page(update, context, user_id, new_page, query_text)
            else:
                await query.edit_message_text(
                    "❌ Search results expired. Please search again with /search",
                    parse_mode='Markdown'
                )

        elif data == "search_back_to_voice":
            page = self.voice_pages.get(user_id, 0)
            await self.show_voice_page(update, context, user_id, page)

        elif data.startswith("voice_") and not data.startswith("voice_page_"):
            voice_key = data[6:]
            
            if voice_key in VOICE_ARTISTS:
                self.user_voices[user_id] = voice_key
                voice = VOICE_ARTISTS[voice_key]
                is_default = "⭐ Default Voice! " if voice_key in DEFAULT_VOICES else ""
                await query.edit_message_text(
                    f"✅ Voice changed to: {voice['emoji']} *{voice['name']}*\n{is_default}{voice['description']}\n\nSend any text to hear this voice!",
                    parse_mode='Markdown'
                )
            else:
                found = False
                for key, voice in VOICE_ARTISTS.items():
                    if voice_key == key or voice_key in key or key in voice_key:
                        self.user_voices[user_id] = key
                        is_default = "⭐ Default Voice! " if key in DEFAULT_VOICES else ""
                        await query.edit_message_text(
                            f"✅ Voice changed to: {voice['emoji']} *{voice['name']}*\n{is_default}{voice['description']}\n\nSend any text to hear this voice!",
                            parse_mode='Markdown'
                        )
                        found = True
                        break
                
                if not found:
                    await query.edit_message_text(
                        f"❌ Voice not found. Please try again.",
                        parse_mode='Markdown'
                    )

        elif data == "voice_page_next":
            current_page = self.voice_pages.get(user_id, 0)
            new_page = current_page + 1
            await self.show_voice_page(update, context, user_id, new_page)

        elif data == "voice_page_prev":
            current_page = self.voice_pages.get(user_id, 0)
            new_page = max(0, current_page - 1)
            await self.show_voice_page(update, context, user_id, new_page)

        elif data.startswith("lang_") and not data.startswith("lang_page_"):
            lang_code = data.replace("lang_", "")
            if lang_code in LANGUAGES:
                self.user_languages[user_id] = lang_code
                lang_name = LANGUAGES[lang_code]
                await query.edit_message_text(
                    f"✅ Language set to: {lang_name}\n\nYour text will now be processed in {lang_name}.\nSend a message or try /sample to hear it!",
                    parse_mode='Markdown'
                )

        elif data == "lang_page_next":
            current_page = self.lang_pages.get(user_id, 0)
            new_page = current_page + 1
            await self.show_language_page(update, context, user_id, new_page)

        elif data == "lang_page_prev":
            current_page = self.lang_pages.get(user_id, 0)
            new_page = max(0, current_page - 1)
            await self.show_language_page(update, context, user_id, new_page)

        elif data == "view_all_langs":
            all_langs = "🌍 *All 83 Languages*\n\n"
            for code, name in sorted(LANGUAGES.items()):
                all_langs += f"{name}\n"
            all_langs += "\nUse /language to select your preferred language."
            await query.edit_message_text(all_langs, parse_mode='Markdown')

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        default_count = len(DEFAULT_VOICES)
        await update.message.reply_text(
            f"📋 *Commands*\n\n"
            f"/start - Welcome message\n"
            f"/help - This guide\n"
            f"/language - Set your language (83 options)\n"
            f"/voice - Browse all voices ({len(VOICE_ARTISTS)} total)\n"
            f"/search [name] - Search for voices (⭐ defaults first)\n"
            f"/voices - List all available voices\n"
            f"/sample - Hear a demo in your language\n"
            f"/about - Bot info\n\n"
            f"*How to use:*\n"
            f"1. Set your language with /language\n"
            f"2. Choose your voice with /voice or /search\n"
            f"3. Send text to convert to voice!\n\n"
            f"⭐ = Default Voice ({default_count} always available)\n\n"
            f"✨ *Developer:* {DEV_NAME}",
            parse_mode='Markdown'
        )

    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        logger.error(f"Error: {context.error}")
        if update:
            if update.effective_message:
                await update.effective_message.reply_text("⚠️ Service unavailable. Please try again.")
            elif update.callback_query:
                await update.callback_query.edit_message_text("⚠️ Service unavailable. Please try again.")

def run_bot():
    bot = VoiceBot()
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", bot.start_command))
    app.add_handler(CommandHandler("help", bot.help_command))
    app.add_handler(CommandHandler("language", bot.language_command))
    app.add_handler(CommandHandler("voice", bot.voice_command))
    app.add_handler(CommandHandler("search", bot.search_command))
    app.add_handler(CommandHandler("voices", bot.voices_command))
    app.add_handler(CommandHandler("sample", bot.sample_command))
    app.add_handler(CommandHandler("about", bot.about_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_text))
    app.add_handler(CallbackQueryHandler(bot.button_callback))
    app.add_error_handler(bot.error_handler)

    webhook_url = os.environ.get("WEBHOOK_URL")

    logger.info(f"🎙️ {BOT_NAME} by {DEV_NAME} is running...")
    logger.info(f"🌍 {len(LANGUAGES)} languages supported")
    logger.info(f"🎤 {len(VOICE_ARTISTS)} voice artists available ({len(DEFAULT_VOICES)} defaults)")
    logger.info(f"🔒 Emotions disabled for API")
    if ENABLE_API:
        logger.info(f"🔑 API enabled with {len(VALID_API_KEYS)} key(s)")
        logger.info(f"🌐 API endpoints available at /api/*")

    if webhook_url:
        logger.info(f"🌐 Starting webhook on port {PORT}")
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            webhook_url=webhook_url,
            drop_pending_updates=True
        )
    else:
        logger.info("📡 Starting in polling mode...")
        app.run_polling(allowed_updates=Update.ALL_TYPES)

def main():
    from werkzeug.serving import run_simple

    def signal_handler(sig, frame):
        logger.info("🛑 Shutting down...")
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    import threading
    flask_thread = threading.Thread(target=lambda: run_simple(
        "0.0.0.0", PORT, flask_app, use_reloader=False, use_debugger=False
    ))
    flask_thread.daemon = True
    flask_thread.start()

    logger.info(f"🌐 Health check available at https://bot-production-aba4.up.railway.app/")
    logger.info(f"🌐 API available at https://bot-production-aba4.up.railway.app/api/")

    run_bot()

if __name__ == "__main__":
    main()
