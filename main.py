#!/usr/bin/env python3
import requests
import time
import random
import string
import re
import os
import json
import logging
from datetime import datetime, timedelta
from typing import Optional
from functools import wraps
import sys
import threading

try:
    from flask import Flask, jsonify
except ImportError:
    os.system("pip install flask")
    from flask import Flask, jsonify

try:
    import uuid
    UUID_AVAILABLE = True
except ImportError:
    UUID_AVAILABLE = False

try:
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
    from telegram.constants import ChatType
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False
    print("pip install python-telegram-bot")
    sys.exit(1)

# Configure logging - minimal
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Configuration
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8330163722:AAEv9Sj0EMT8cpRu9dtfsfVN7JSB0J9n_7A")
ADMIN_IDS = [int(id.strip()) for id in os.environ.get("ADMIN_IDS", "7716750398").split(",") if id.strip()]
DB_FILE = "musicgpt_bot.json"
REQUEST_TIMEOUT = 30
PORT = int(os.environ.get("PORT", 8080))

os.makedirs("output", exist_ok=True)

def load_db():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, 'r') as f:
                return json.load(f)
        except:
            return {"users": {}, "pending_approvals": [], "generations": []}
    return {"users": {}, "pending_approvals": [], "generations": []}

def save_db(data):
    try:
        with open(DB_FILE, 'w') as f:
            json.dump(data, f, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to save database: {e}")

class Database:
    @staticmethod
    def get_user(user_id):
        try:
            data = load_db()
            return data["users"].get(str(user_id))
        except:
            return None
    
    @staticmethod
    def create_user(user_id, username, first_name, last_name):
        try:
            data = load_db()
            user_id_str = str(user_id)
            if user_id_str in data["users"]:
                return False
            is_admin = 1 if user_id in ADMIN_IDS else 0
            approved = 1 if user_id in ADMIN_IDS else 0
            data["users"][user_id_str] = {
                "user_id": user_id,
                "username": username,
                "first_name": first_name,
                "last_name": last_name,
                "registered_date": datetime.now().isoformat(),
                "approved": approved,
                "is_admin": is_admin,
                "authenticated": 0,
                "current_email": "",
                "current_display": "",
                "current_provider": "",
                "access_token": "",
                "musicgpt_user_id": "",
                "last_audio_id": "",
                "last_title": "",
                "last_filepath": ""
            }
            save_db(data)
            return True
        except:
            return False
    
    @staticmethod
    def approve_user(user_id):
        try:
            data = load_db()
            user_id_str = str(user_id)
            if user_id_str in data["users"]:
                data["users"][user_id_str]["approved"] = 1
                for pending in data["pending_approvals"]:
                    if pending["user_id"] == user_id and pending["status"] == "pending":
                        pending["status"] = "approved"
                save_db(data)
        except:
            pass
    
    @staticmethod
    def reject_user(user_id):
        try:
            data = load_db()
            for pending in data["pending_approvals"]:
                if pending["user_id"] == user_id and pending["status"] == "pending":
                    pending["status"] = "rejected"
            save_db(data)
        except:
            pass
    
    @staticmethod
    def request_approval(user_id):
        try:
            data = load_db()
            data["pending_approvals"].append({
                "user_id": user_id,
                "requested_at": datetime.now().isoformat(),
                "status": "pending"
            })
            save_db(data)
        except:
            pass
    
    @staticmethod
    def get_pending_approvals():
        try:
            data = load_db()
            pending = []
            for p in data["pending_approvals"]:
                if p["status"] == "pending":
                    user = data["users"].get(str(p["user_id"]))
                    if user:
                        pending.append((p["user_id"], user.get("username", ""), user.get("first_name", ""), user.get("last_name", ""), p["requested_at"]))
            return pending
        except:
            return []
    
    @staticmethod
    def get_generation_count(user_id):
        try:
            data = load_db()
            count = 0
            for gen in data["generations"]:
                if gen["user_id"] == user_id:
                    gen_date = datetime.fromisoformat(gen["created_at"])
                    if (datetime.now() - gen_date).days <= 30:
                        count += 1
            return count
        except:
            return 0
    
    @staticmethod
    def add_generation(user_id, prompt, audio_id, title, file_path):
        try:
            data = load_db()
            data["generations"].append({
                "user_id": user_id,
                "prompt": prompt,
                "audio_id": audio_id,
                "title": title,
                "file_path": file_path,
                "created_at": datetime.now().isoformat()
            })
            save_db(data)
        except:
            pass
    
    @staticmethod
    def update_session(user_id, authenticated, email, display, provider, token, user_id_api):
        try:
            data = load_db()
            user_id_str = str(user_id)
            if user_id_str in data["users"]:
                data["users"][user_id_str]["authenticated"] = authenticated
                data["users"][user_id_str]["current_email"] = email
                data["users"][user_id_str]["current_display"] = display
                data["users"][user_id_str]["current_provider"] = provider
                data["users"][user_id_str]["access_token"] = token
                data["users"][user_id_str]["musicgpt_user_id"] = user_id_api
                save_db(data)
        except:
            pass
    
    @staticmethod
    def update_last_audio(user_id, audio_id, title, filepath):
        try:
            data = load_db()
            user_id_str = str(user_id)
            if user_id_str in data["users"]:
                data["users"][user_id_str]["last_audio_id"] = audio_id
                data["users"][user_id_str]["last_title"] = title
                data["users"][user_id_str]["last_filepath"] = filepath
                save_db(data)
        except:
            pass
    
    @staticmethod
    def get_session(user_id):
        try:
            data = load_db()
            user = data["users"].get(str(user_id))
            if user:
                return (
                    user.get("authenticated", 0),
                    user.get("current_email", ""),
                    user.get("current_display", ""),
                    user.get("current_provider", ""),
                    user.get("access_token", ""),
                    user.get("musicgpt_user_id", ""),
                    user.get("last_audio_id", ""),
                    user.get("last_title", ""),
                    user.get("last_filepath", "")
                )
            return None
        except:
            return None

class TempMailORG:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36",
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Origin": "https://temp-mail.org",
            "Referer": "https://temp-mail.org/",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache"
        })
        self.token = None
        self.email_address = None
        self.provider = "temp-mail.org"

    def create_account(self) -> dict:
        try:
            mailbox_resp = self.session.post(
                "https://web2.temp-mail.org/mailbox",
                headers={"Content-Length": "0", "Content-Type": "application/json"},
                timeout=REQUEST_TIMEOUT
            )

            if mailbox_resp.status_code not in [200, 201]:
                raise Exception("Failed to create mailbox")

            data = mailbox_resp.json()
            self.token = data.get("token")
            self.email_address = data.get("mailbox")

            if not self.token or not self.email_address:
                raise Exception("No token or email received")

            self.session.headers["Authorization"] = f"Bearer {self.token}"

            return {"email": self.email_address, "token": self.token, "provider": self.provider}
        except:
            raise Exception("Could not create temporary email")

    def get_messages(self) -> list:
        if not self.token:
            return []
        try:
            resp = self.session.get("https://web2.temp-mail.org/messages", timeout=REQUEST_TIMEOUT)
            if resp.status_code != 200:
                return []
            data = resp.json()
            if isinstance(data, dict) and "messages" in data:
                return data["messages"]
            return data if isinstance(data, list) else []
        except:
            return []

    def wait_for_otp(self, timeout: int = 180, poll_interval: int = 5) -> Optional[str]:
        start_time = time.time()
        seen_ids = set()

        while time.time() - start_time < timeout:
            try:
                messages = self.get_messages()
                for msg in messages:
                    msg_id = msg.get("_id") or msg.get("id", "")
                    if msg_id in seen_ids:
                        continue
                    seen_ids.add(msg_id)

                    subject = msg.get("subject", "")
                    body = msg.get("bodyPreview", "")
                    html = msg.get("bodyHtml", "")
                    content = f"{subject} {body} {html}".lower()
                    
                    # Look for 6-digit OTP
                    codes = re.findall(r'\b(\d{6})\b', content)
                    if codes:
                        return codes[0]
                    
                    # Look for code patterns
                    if "code" in content or "otp" in content:
                        codes = re.findall(r'\b(\d{4,8})\b', content)
                        for code in codes:
                            if len(code) >= 4 and code.isdigit():
                                return code
            except:
                pass
            time.sleep(poll_interval)
        return None

    def cleanup(self):
        pass

class MusicGPTAPI:
    BASE_URL = "https://api.prod.musicgpt.com"

    def __init__(self, token=None):
        self.session = requests.Session()
        self.access_token = token
        self.user_id = None
        self.email = None
        self.anonymous_id = self._gen_id()

        self.session.cookies.set("anonymous_id", self.anonymous_id, domain=".musicgpt.com")

        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Content-Type": "application/json",
            "Origin": "https://musicgpt.com",
            "Referer": "https://musicgpt.com/"
        })
        
        if token:
            self.session.headers["Authorization"] = f"Bearer {token}"

    def _gen_id(self) -> str:
        if UUID_AVAILABLE:
            return str(uuid.uuid4())
        return f"{random.getrandbits(32):08x}-{random.getrandbits(16):04x}-4{random.getrandbits(12):03x}-{random.randint(8,11):x}{random.getrandbits(12):03x}-{random.getrandbits(48):012x}"

    def send_otp(self, email: str) -> Optional[str]:
        try:
            payload = {"email": email, "language": "en_US"}
            resp = self.session.post(f"{self.BASE_URL}/authentication/login/email", json=payload, timeout=REQUEST_TIMEOUT)
            if resp.status_code != 200:
                return None
            data = resp.json()
            if isinstance(data, dict):
                inner = data.get("data", data)
                token = inner.get("validation_token")
                if token:
                    return token
                token = data.get("validation_token")
                if token:
                    return token
            return None
        except:
            return None

    def verify_otp(self, otp: str, validation_token: str) -> bool:
        try:
            payload = {"otp": otp, "validation_token": validation_token}
            resp = self.session.post(f"{self.BASE_URL}/authentication/login/verify-otp", json=payload, timeout=REQUEST_TIMEOUT)
            if resp.status_code != 200:
                return False
            data = resp.json()
            if isinstance(data, dict):
                inner = data.get("data", data)
                self.access_token = inner.get("access_token")
                self.user_id = inner.get("user_id")
                self.email = inner.get("email")
            else:
                return False
            if self.access_token:
                self.session.headers["Authorization"] = f"Bearer {self.access_token}"
                return True
            return False
        except:
            return False

    def set_display_name(self, username: str, display_name: str) -> bool:
        try:
            resp = self.session.post(
                f"{self.BASE_URL}/users/front/set-initial-names",
                json={"display_name": display_name, "username": username},
                timeout=REQUEST_TIMEOUT
            )
            return resp.status_code == 200
        except:
            return False

    def submit_prompt(self, prompt: str) -> dict:
        try:
            prompt_id = self._gen_id()
            conversion_id_1 = self._gen_id()
            conversion_id_2 = self._gen_id()

            payload = {
                "prompt": prompt,
                "prompt_id": prompt_id,
                "conversion_id_1": conversion_id_1,
                "conversion_id_2": conversion_id_2
            }

            resp = self.session.post(f"{self.BASE_URL}/prompt/front/submit", json=payload, timeout=REQUEST_TIMEOUT)

            if resp.status_code not in [200, 201]:
                return {"error": f"HTTP {resp.status_code}", "success": False}

            try:
                data = resp.json()
            except:
                return {"error": "Invalid response", "success": False}

            if isinstance(data, dict):
                inner = data.get("data", data)
                eta = inner.get("eta", 90)
                success = data.get("success", True)
                if not success:
                    return {"error": data.get("message", "Unknown"), "success": False}
            else:
                eta = 90

            return {
                "prompt_id": prompt_id,
                "conversion_id": conversion_id_2,
                "eta": eta,
                "success": True
            }
        except:
            return {"error": "Failed to submit prompt", "success": False}

    def get_audio(self, audio_id: str) -> Optional[dict]:
        try:
            resp = self.session.get(f"{self.BASE_URL}/audio/front/get-by-id/{audio_id}", timeout=REQUEST_TIMEOUT)
            if resp.status_code != 200:
                return None
            data = resp.json()
            return data.get("data", data) if isinstance(data, dict) else None
        except:
            return None

    def wait_for_audio(self, audio_id: str, eta: int, timeout_extra: int = 300) -> Optional[dict]:
        timeout = eta + timeout_extra
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                data = self.get_audio(audio_id)
                if data:
                    status = data.get("conversion_status", "")
                    if status == "SUCCESS":
                        return data
                    elif status == "FAILED":
                        return None
            except:
                pass
            time.sleep(3)
        return None

    def get_download_url(self, audio_id: str) -> Optional[str]:
        try:
            resp = self.session.get(f"{self.BASE_URL}/download/front/v3/{audio_id}/FULL_SONG", timeout=REQUEST_TIMEOUT)
            if resp.status_code != 200:
                return None
            data = resp.json()
            if isinstance(data, dict):
                inner = data.get("data", data)
                return inner.get("download_url")
            return None
        except:
            return None

class MusicGPTBot:
    def __init__(self):
        self.api = None
        self.temp_mail = None
        self.bot_username = None
    
    def is_approved(self, user_id):
        user = Database.get_user(user_id)
        return user.get("approved", 0) == 1 if user else False
    
    def is_admin(self, user_id):
        if user_id in ADMIN_IDS:
            return True
        user = Database.get_user(user_id)
        return user.get("is_admin", 0) == 1 if user else False
    
    def is_authenticated(self, user_id):
        session = Database.get_session(user_id)
        return session[0] == 1 if session else False
    
    async def check_channel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_chat.type == ChatType.PRIVATE:
            return True
        
        if update.effective_chat.type in [ChatType.GROUP, ChatType.SUPERGROUP, ChatType.CHANNEL]:
            if not self.bot_username:
                self.bot_username = (await context.bot.get_me()).username
            
            if update.message:
                text = update.message.text or update.message.caption or ""
                mention = f"@{self.bot_username}"
                
                if mention in text:
                    return True
                
                if update.message.reply_to_message:
                    if update.message.reply_to_message.from_user.id == context.bot.id:
                        return True
            return False
        
        return False
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.check_channel(update, context):
            return
        
        user = update.effective_user
        if not Database.get_user(user.id):
            Database.create_user(user.id, user.username, user.first_name, user.last_name)
        
        keyboard = [
            [InlineKeyboardButton("🔑 Login", callback_data="login")],
            [InlineKeyboardButton("🎵 Generate Music", callback_data="generate")],
            [InlineKeyboardButton("▶️ Play Last Track", callback_data="play")],
            [InlineKeyboardButton("📊 My Status", callback_data="status")],
            [InlineKeyboardButton("👤 My Profile", callback_data="profile")],
        ]
        
        if self.is_admin(user.id):
            keyboard.append([InlineKeyboardButton("👑 Admin Panel", callback_data="admin_panel")])
        
        if not self.is_approved(user.id):
            keyboard = [
                [InlineKeyboardButton("🔑 Request Access", callback_data="request_access")],
                [InlineKeyboardButton("📊 My Status", callback_data="status")]
            ]
        
        welcome = f"🎵 **Welcome {user.first_name}!**\n\n"
        if self.is_approved(user.id):
            if self.is_authenticated(user.id):
                welcome += "✅ You are **authenticated** and ready to generate music!\n\n"
                welcome += "Just click **'Generate Music'** and tell me what you want!"
            else:
                welcome += "🔑 You are **approved** but need to login first.\n\n"
                welcome += "Click **'Login'** to authenticate with MusicGPT."
        else:
            welcome += "⏳ You need **approval** to use this bot.\n\n"
            welcome += "Click **'Request Access'** to ask for permission."
        
        await update.message.reply_text(welcome, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    
    async def login_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.check_channel(update, context):
            return
        
        query = update.callback_query
        await query.answer()
        user_id = update.effective_user.id
        
        if not self.is_approved(user_id):
            await query.message.reply_text("❌ You need to be approved first. Use /start")
            return
        
        status_msg = await query.message.reply_text("🔑 Creating temporary email...")
        
        try:
            # Auto-login with temp-mail.org
            self.temp_mail = TempMailORG()
            email_data = self.temp_mail.create_account()
            
            await status_msg.edit_text(f"📧 Email created: `{email_data['email']}`\n\nRequesting OTP...")
            
            self.api = MusicGPTAPI()
            validation_token = self.api.send_otp(email_data["email"])
            
            if not validation_token:
                await status_msg.edit_text("❌ Failed to send OTP. Please try again.")
                return
            
            await status_msg.edit_text(f"📧 Waiting for OTP...\n\nCheck your email: `{email_data['email']}`\n\n⏳ This may take up to 2 minutes...")
            
            otp = self.temp_mail.wait_for_otp(timeout=180)
            
            if not otp:
                await status_msg.edit_text("❌ OTP not received. Please try again.")
                return
            
            await status_msg.edit_text(f"✅ OTP received! Verifying...")
            
            success = self.api.verify_otp(otp, validation_token)
            
            if not success:
                await status_msg.edit_text("❌ Verification failed. Please try again.")
                return
            
            username = email_data["email"].split("@")[0]
            display_name = f"User_{user_id}"
            
            self.api.set_display_name(username, display_name)
            
            Database.update_session(
                user_id, 1, email_data["email"], display_name, 
                "temp-mail.org", 
                self.api.access_token, self.api.user_id
            )
            
            keyboard = [
                [InlineKeyboardButton("🎵 Generate Music", callback_data="generate")],
                [InlineKeyboardButton("📊 My Status", callback_data="status")],
                [InlineKeyboardButton("🔙 Back", callback_data="back")]
            ]
            
            await status_msg.edit_text(
                f"✅ **Login Successful!**\n\n"
                f"Display: `{display_name}`\n"
                f"Email: `{email_data['email']}`\n"
                f"Provider: `temp-mail.org`\n\n"
                f"🎵 Click **'Generate Music'** to start creating!",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
            
        except Exception as e:
            await status_msg.edit_text(f"❌ Login error: {str(e)}\n\nPlease try again.")
        finally:
            if self.temp_mail:
                try:
                    self.temp_mail.cleanup()
                except:
                    pass
            self.temp_mail = None
    
    async def generate_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.check_channel(update, context):
            return
        
        query = update.callback_query
        await query.answer()
        user_id = update.effective_user.id
        
        if not self.is_approved(user_id):
            await query.message.reply_text("❌ Access denied. Request approval first.")
            return
        
        if not self.is_authenticated(user_id):
            keyboard = [[InlineKeyboardButton("🔑 Login First", callback_data="login")]]
            await query.message.reply_text(
                "❌ **Not Authenticated**\n\n"
                "You need to login first before generating music.",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
            return
        
        await query.message.reply_text(
            "🎵 **Describe Your Music**\n\n"
            "Send me a text description of the music you want to create.\n\n"
            "Examples:\n"
            "• `Epic orchestral music with dramatic violins`\n"
            "• `Chill lofi beats for studying`\n"
            "• `Electronic dance music with heavy bass`\n\n"
            "✏️ Type your prompt now:"
        )
        context.user_data['awaiting_prompt'] = True
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.check_channel(update, context):
            return
        
        user_id = update.effective_user.id
        text = update.message.text or ""
        
        if context.user_data.get('awaiting_prompt'):
            context.user_data['awaiting_prompt'] = False
            await self.process_generation(update, context, text)
            return
        
        keyboard = [
            [InlineKeyboardButton("🎵 Generate Music", callback_data="generate")],
            [InlineKeyboardButton("📊 My Status", callback_data="status")],
            [InlineKeyboardButton("🔙 Back", callback_data="back")]
        ]
        await update.message.reply_text(
            "I'm not sure what you want. Please use the buttons below:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    async def process_generation(self, update: Update, context: ContextTypes.DEFAULT_TYPE, prompt: str):
        user_id = update.effective_user.id
        status_msg = await update.message.reply_text(f"🎵 Generating music...\n\nPrompt: `{prompt}`\n\n⏳ This may take 1-2 minutes...", parse_mode='Markdown')
        
        try:
            session = Database.get_session(user_id)
            if not session or not session[4]:
                await status_msg.edit_text("❌ Session expired. Login again.")
                return
            
            self.api = MusicGPTAPI(session[4])
            
            result = self.api.submit_prompt(prompt)
            if not result.get("success"):
                await status_msg.edit_text(f"❌ Failed: {result.get('error', 'Unknown error')}")
                return
            
            await status_msg.edit_text(f"🎵 Generating...\n\nPrompt: `{prompt}`\n\n⏳ ETA: {result['eta']} seconds", parse_mode='Markdown')
            
            audio_data = self.api.wait_for_audio(result["conversion_id"], result["eta"])
            if not audio_data:
                await status_msg.edit_text("❌ Generation failed. Please try again.")
                return
            
            audio_id = audio_data.get("id", result["conversion_id"])
            download_url = self.api.get_download_url(audio_id)
            if not download_url:
                await status_msg.edit_text("❌ Failed to get download URL.")
                return
            
            title = audio_data.get("title", "music")
            safe_title = re.sub(r'[^\w\-_\. ]', '_', title)
            safe_title = re.sub(r'_+', '_', safe_title)
            filename = f"{safe_title}_{audio_id[:8]}.mp3"
            
            filepath = os.path.join("output", filename)
            
            await status_msg.edit_text(f"📥 Downloading...")
            
            resp = requests.get(download_url, stream=True, timeout=REQUEST_TIMEOUT * 4)
            if resp.status_code == 200:
                with open(filepath, "wb") as f:
                    for chunk in resp.iter_content(8192):
                        if chunk:
                            f.write(chunk)
                
                Database.add_generation(user_id, prompt, audio_id, title, filepath)
                Database.update_last_audio(user_id, audio_id, title, filepath)
                
                with open(filepath, "rb") as f:
                    await context.bot.send_audio(
                        chat_id=update.effective_chat.id,
                        audio=f,
                        title=title,
                        performer="MusicGPT AI",
                        caption=f"🎵 **{title}**\n\nPrompt: `{prompt}`\n\n✨ Generated by MusicGPT AI"
                    )
                
                keyboard = [
                    [InlineKeyboardButton("▶️ Play Again", callback_data="play")],
                    [InlineKeyboardButton("🎵 Generate More", callback_data="generate")],
                    [InlineKeyboardButton("📊 My Status", callback_data="status")]
                ]
                await status_msg.edit_text(
                    "✅ **Generation Complete!**\n\n"
                    f"Title: `{title}`\n"
                    f"Duration: {audio_data.get('audio_length_ms', 0) / 1000:.1f}s\n\n"
                    "What would you like to do next?",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode='Markdown'
                )
            else:
                await status_msg.edit_text("❌ Download failed.")
                
        except Exception as e:
            await status_msg.edit_text(f"❌ Failed to generate music. Please try again.")
    
    async def play_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.check_channel(update, context):
            return
        
        query = update.callback_query
        await query.answer()
        user_id = update.effective_user.id
        
        session = Database.get_session(user_id)
        if not session:
            await query.message.reply_text("❌ User not found. Use /start first.")
            return
        
        filepath = session[8]
        audio_id = session[6]
        title = session[7]
        
        if filepath and os.path.exists(filepath):
            await query.message.reply_text(f"▶️ Playing: `{title}`", parse_mode='Markdown')
            with open(filepath, "rb") as f:
                await context.bot.send_audio(
                    chat_id=update.effective_chat.id,
                    audio=f,
                    title=title,
                    performer="MusicGPT AI"
                )
        elif audio_id:
            await query.message.reply_text(f"🔄 Fetching audio...", parse_mode='Markdown')
            
            session_data = Database.get_session(user_id)
            if not session_data or not session_data[4]:
                await query.message.reply_text("❌ Session expired. Login again.")
                return
            
            self.api = MusicGPTAPI(session_data[4])
            audio_data = self.api.get_audio(audio_id)
            
            if audio_data:
                download_url = self.api.get_download_url(audio_id)
                if download_url:
                    title = audio_data.get("title", "music")
                    safe_title = re.sub(r'[^\w\-_\. ]', '_', title)
                    filename = f"{safe_title}_{audio_id[:8]}.mp3"
                    
                    filepath = os.path.join("output", filename)
                    
                    resp = requests.get(download_url, stream=True, timeout=REQUEST_TIMEOUT * 4)
                    if resp.status_code == 200:
                        with open(filepath, "wb") as f:
                            for chunk in resp.iter_content(8192):
                                if chunk:
                                    f.write(chunk)
                        
                        Database.update_last_audio(user_id, audio_id, title, filepath)
                        
                        await query.message.reply_text(f"▶️ Playing: `{title}`", parse_mode='Markdown')
                        with open(filepath, "rb") as f:
                            await context.bot.send_audio(
                                chat_id=update.effective_chat.id,
                                audio=f,
                                title=title,
                                performer="MusicGPT AI"
                            )
                    else:
                        await query.message.reply_text("❌ Failed to download.")
                else:
                    await query.message.reply_text("❌ No download URL available.")
            else:
                await query.message.reply_text("❌ Could not fetch audio data.")
        else:
            keyboard = [[InlineKeyboardButton("🎵 Generate Music", callback_data="generate")]]
            await query.message.reply_text(
                "❌ Nothing to play. Generate music first.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
    
    async def status_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.check_channel(update, context):
            return
        
        query = update.callback_query
        await query.answer()
        user_id = update.effective_user.id
        
        session = Database.get_session(user_id)
        if not session:
            await query.message.reply_text("❌ User not found. Use /start first.")
            return
        
        authenticated = session[0] == 1
        email = session[1] or "Not set"
        display = session[2] or "Not set"
        provider = session[3] or "Not set"
        
        keyboard = []
        if authenticated:
            keyboard.append([InlineKeyboardButton("🎵 Generate Music", callback_data="generate")])
        else:
            keyboard.append([InlineKeyboardButton("🔑 Login", callback_data="login")])
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="back")])
        
        status_text = f"📊 **Session Status**\n\n"
        status_text += f"✅ Authenticated: {'Yes' if authenticated else 'No'}\n"
        if authenticated:
            status_text += f"Display: `{display}`\n"
            status_text += f"Email: `{email}`\n"
            status_text += f"Provider: `{provider}`\n"
        status_text += f"User ID: `{user_id}`\n\n"
        
        if authenticated:
            status_text += "🎵 Ready to generate music!"
        else:
            status_text += "🔑 Click 'Login' to authenticate."
        
        await query.message.reply_text(
            status_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    
    async def profile_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.check_channel(update, context):
            return
        
        query = update.callback_query
        await query.answer()
        user_id = update.effective_user.id
        
        user = Database.get_user(user_id)
        if not user:
            await query.message.reply_text("❌ User not found.")
            return
        
        approved = self.is_approved(user_id)
        admin = self.is_admin(user_id)
        authenticated = self.is_authenticated(user_id)
        monthly = Database.get_generation_count(user_id)
        
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="back")]]
        
        profile_text = f"👤 **Profile**\n\n"
        profile_text += f"Name: {user.get('first_name', '')} @{user.get('username', 'None')}\n"
        profile_text += f"Admin: {'✅' if admin else '❌'}\n"
        profile_text += f"Approved: {'✅' if approved else '❌'}\n"
        profile_text += f"Authenticated: {'✅' if authenticated else '❌'}\n"
        profile_text += f"Generations: {monthly}/month\n\n"
        
        if authenticated:
            profile_text += "🎵 Ready to generate!"
        else:
            profile_text += "🔑 Use 'Login' to authenticate."
        
        await query.message.reply_text(
            profile_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    
    async def admin_panel_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.check_channel(update, context):
            return
        
        query = update.callback_query
        await query.answer()
        user_id = update.effective_user.id
        
        if not self.is_admin(user_id):
            await query.message.reply_text("❌ Admin only.")
            return
        
        pending = Database.get_pending_approvals()
        
        keyboard = [
            [InlineKeyboardButton("📋 View Pending", callback_data="view_pending")],
            [InlineKeyboardButton("🔙 Back", callback_data="back")]
        ]
        
        admin_text = f"👑 **Admin Panel**\n\n"
        admin_text += f"Pending Requests: {len(pending)}\n\n"
        admin_text += "Click 'View Pending' to see all requests."
        
        await query.message.reply_text(
            admin_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    
    async def view_pending_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.check_channel(update, context):
            return
        
        query = update.callback_query
        await query.answer()
        user_id = update.effective_user.id
        
        if not self.is_admin(user_id):
            await query.message.reply_text("❌ Admin only.")
            return
        
        pending = Database.get_pending_approvals()
        
        if not pending:
            keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="admin_panel")]]
            await query.message.reply_text(
                "📋 No pending requests.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
        
        for p in pending:
            keyboard = [
                [
                    InlineKeyboardButton("✅ Approve", callback_data=f"approve_{p[0]}"),
                    InlineKeyboardButton("❌ Reject", callback_data=f"reject_{p[0]}")
                ],
                [InlineKeyboardButton("🔙 Back", callback_data="admin_panel")]
            ]
            await query.message.reply_text(
                f"**Pending Request**\n\n"
                f"User: {p[2]} @{p[1]}\n"
                f"ID: `{p[0]}`\n"
                f"Requested: {p[4][:19]}",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
    
    async def request_access_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.check_channel(update, context):
            return
        
        query = update.callback_query
        await query.answer()
        user_id = update.effective_user.id
        
        if self.is_approved(user_id):
            await query.message.reply_text("✅ You're already approved!")
            return
        
        data = load_db()
        for pending in data["pending_approvals"]:
            if pending["user_id"] == user_id and pending["status"] == "pending":
                await query.message.reply_text("⏳ Request already pending.")
                return
        
        Database.request_approval(user_id)
        
        for admin_id in ADMIN_IDS:
            try:
                keyboard = [[
                    InlineKeyboardButton("✅ Approve", callback_data=f"approve_{user_id}"),
                    InlineKeyboardButton("❌ Reject", callback_data=f"reject_{user_id}")
                ]]
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=f"🔔 New Request\nUser: {update.effective_user.first_name} @{update.effective_user.username}\nID: `{user_id}`",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode='Markdown'
                )
            except:
                pass
        
        keyboard = [[InlineKeyboardButton("📊 Check Status", callback_data="status")]]
        await query.message.reply_text(
            "✅ **Request Sent!**\n\n"
            "Your access request has been sent to the admins.\n"
            "You'll be notified when approved.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    
    async def back_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.check_channel(update, context):
            return
        
        query = update.callback_query
        await query.answer()
        await self.start(update, context)
    
    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.check_channel(update, context):
            return
        
        query = update.callback_query
        data = query.data
        
        if data == "login":
            await self.login_callback(update, context)
        elif data == "generate":
            await self.generate_callback(update, context)
        elif data == "play":
            await self.play_callback(update, context)
        elif data == "status":
            await self.status_callback(update, context)
        elif data == "profile":
            await self.profile_callback(update, context)
        elif data == "admin_panel":
            await self.admin_panel_callback(update, context)
        elif data == "view_pending":
            await self.view_pending_callback(update, context)
        elif data == "request_access":
            await self.request_access_callback(update, context)
        elif data == "back":
            await self.back_callback(update, context)
        elif data.startswith("approve_") or data.startswith("reject_"):
            await self.approve_reject_callback(update, context)
    
    async def approve_reject_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.check_channel(update, context):
            return
        
        query = update.callback_query
        user_id = update.effective_user.id
        
        if not self.is_admin(user_id):
            await query.message.reply_text("❌ Admin only.")
            return
        
        data = query.data
        action, target = data.split("_")
        target = int(target)
        
        if action == "approve":
            Database.approve_user(target)
            await query.message.edit_text(f"✅ User `{target}` approved!")
            try:
                await context.bot.send_message(chat_id=target, text="🎉 **Approved!**\n\nYou can now use the bot. Click /start to begin.")
            except:
                pass
        else:
            Database.reject_user(target)
            await query.message.edit_text(f"❌ User `{target}` rejected.")
            try:
                await context.bot.send_message(chat_id=target, text="❌ **Denied**\n\nYour access request was rejected. Contact an admin.")
            except:
                pass
    
    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        error = context.error
        
        # Only log real errors (not conflicts)
        if "Conflict" in str(error) and "getUpdates" in str(error):
            return
        
        logger.error(f"Update {update} caused error: {error}")
        
        if update and update.effective_message:
            try:
                keyboard = [[InlineKeyboardButton("🔄 Try Again", callback_data="back")]]
                await update.effective_message.reply_text(
                    "❌ An error occurred. Please try again.",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            except:
                pass

# Health check server
def run_health_server():
    try:
        health_app = Flask(__name__)
        
        @health_app.route('/')
        @health_app.route('/health')
        def health():
            return jsonify({"status": "healthy", "timestamp": datetime.now().isoformat()}), 200
        
        health_app.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False)
    except:
        pass

def main():
    if not TELEGRAM_AVAILABLE:
        print("Install: pip install python-telegram-bot")
        return
    
    # Start health server
    health_thread = threading.Thread(target=run_health_server, daemon=True)
    health_thread.start()
    
    time.sleep(2)
    
    bot = MusicGPTBot()
    
    app = Application.builder()\
        .token(BOT_TOKEN)\
        .connect_timeout(30.0)\
        .read_timeout(30.0)\
        .build()
    
    app.add_handler(CommandHandler("start", bot.start))
    app.add_handler(CallbackQueryHandler(bot.button_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_message))
    app.add_error_handler(bot.error_handler)
    
    print("✅ Bot started!")
    print(f"👑 Admin ID: {ADMIN_IDS[0] if ADMIN_IDS else 'Not set'}")
    print("🎵 MusicGPT integration ready!")
    
    try:
        app.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
            stop_signals=None
        )
    except KeyboardInterrupt:
        print("\n👋 Bot stopped.")
    except Exception as e:
        print(f"❌ Fatal error: {e}")

if __name__ == "__main__":
    main()
