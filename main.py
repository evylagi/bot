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

# Add Flask for health check server
try:
    from flask import Flask
    FLASK_AVAILABLE = True
except ImportError:
    FLASK_AVAILABLE = False
    print("Installing Flask for health checks...")
    os.system("pip install flask")

try:
    import uuid
    UUID_AVAILABLE = True
except ImportError:
    UUID_AVAILABLE = False

try:
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMember
    from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler
    from telegram.constants import ChatType
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False
    print("pip install python-telegram-bot")
    sys.exit(1)

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Configuration - Use environment variables for security
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8330163722:AAEv9Sj0EMT8cpRu9dtfsfVN7JSB0J9n_7A")
ADMIN_IDS = [int(id.strip()) for id in os.environ.get("ADMIN_IDS", "7716750398").split(",") if id.strip()]
DB_FILE = "musicgpt_bot.json"
DEBUG = os.environ.get("DEBUG", "False").lower() == "true"
MAX_RETRIES = 3
RETRY_DELAY = 5
REQUEST_TIMEOUT = 30
PORT = int(os.environ.get("PORT", 8080))  # Render provides PORT env variable

# Create required directories
os.makedirs("output", exist_ok=True)

try:
    import asyncio
except ImportError:
    import asyncio

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
        # Create backup before saving
        if os.path.exists(DB_FILE):
            try:
                with open(DB_FILE, 'r') as f:
                    old_data = json.load(f)
                with open(f"{DB_FILE}.backup", 'w') as f:
                    json.dump(old_data, f, indent=2, default=str)
            except:
                pass
        
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
        except Exception as e:
            logger.error(f"Create user error: {e}")
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
        except Exception as e:
            logger.error(f"Approve user error: {e}")
    
    @staticmethod
    def reject_user(user_id):
        try:
            data = load_db()
            for pending in data["pending_approvals"]:
                if pending["user_id"] == user_id and pending["status"] == "pending":
                    pending["status"] = "rejected"
            save_db(data)
        except Exception as e:
            logger.error(f"Reject user error: {e}")
    
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
        except Exception as e:
            logger.error(f"Request approval error: {e}")
    
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
        except Exception as e:
            logger.error(f"Add generation error: {e}")
    
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
        except Exception as e:
            logger.error(f"Update session error: {e}")
    
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
        except Exception as e:
            logger.error(f"Update last audio error: {e}")
    
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

class TempMailTM:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/ld+json, application/json",
            "Content-Type": "application/json"
        })
        self.token = None
        self.account_id = None
        self.email_address = None
        self.password = None
        self.provider = "mail.tm"

    def create_account(self) -> dict:
        try:
            domains_resp = self.session.get("https://api.mail.tm/domains", timeout=REQUEST_TIMEOUT)
            if domains_resp.status_code != 200:
                raise Exception(f"Failed to fetch domains: {domains_resp.status_code}")

            data = domains_resp.json()
            if isinstance(data, list):
                domains = data
            elif "hydra:member" in data:
                domains = data["hydra:member"]
            elif "member" in data:
                domains = data["member"]
            else:
                domains = [data] if isinstance(data, dict) else []

            if not domains:
                raise Exception("No domains available")

            domain = domains[0] if isinstance(domains[0], str) else domains[0].get("domain", "")
            username = ''.join(random.choices(string.ascii_lowercase + string.digits, k=12))
            self.email_address = f"{username}@{domain}"
            self.password = ''.join(random.choices(string.ascii_letters + string.digits + "!@#$%^&*", k=20))

            account_data = {"address": self.email_address, "password": self.password}
            resp = self.session.post("https://api.mail.tm/accounts", json=account_data, timeout=REQUEST_TIMEOUT)
            if resp.status_code not in [200, 201]:
                raise Exception(f"Account creation failed: {resp.status_code}")

            account = resp.json()
            self.account_id = account.get("id") or account.get("@id")

            token_resp = self.session.post("https://api.mail.tm/token", json=account_data, timeout=REQUEST_TIMEOUT)
            if token_resp.status_code != 200:
                raise Exception(f"Token request failed: {token_resp.status_code}")

            token_data = token_resp.json()
            self.token = token_data.get("token") if isinstance(token_data, dict) else str(token_data)
            self.session.headers["Authorization"] = f"Bearer {self.token}"

            return {"email": self.email_address, "password": self.password, "id": self.account_id, "provider": self.provider}
        except requests.Timeout:
            raise Exception("Connection timeout. Please try again.")
        except Exception as e:
            raise Exception(f"Account creation failed: {str(e)}")

    def get_messages(self, page: int = 1) -> list:
        if not self.token:
            return []
        try:
            resp = self.session.get(f"https://api.mail.tm/messages", params={"page": page}, timeout=REQUEST_TIMEOUT)
            if resp.status_code != 200:
                return []
            data = resp.json()
            if isinstance(data, list):
                return data
            return data.get("hydra:member", data.get("member", []))
        except:
            return []

    def get_message(self, message_id: str) -> Optional[dict]:
        if not self.token:
            return None
        try:
            resp = self.session.get(f"https://api.mail.tm/messages/{message_id}", timeout=REQUEST_TIMEOUT)
            if resp.status_code != 200:
                return None
            return resp.json()
        except:
            return None

    def wait_for_otp(self, timeout: int = 120, poll_interval: int = 3) -> Optional[str]:
        start_time = time.time()
        seen_ids = set()

        while time.time() - start_time < timeout:
            try:
                messages = self.get_messages()
                for msg in messages:
                    msg_id = msg.get("id") if isinstance(msg, dict) else None
                    if not msg_id or msg_id in seen_ids:
                        continue
                    seen_ids.add(msg_id)

                    full_msg = self.get_message(msg_id)
                    if not full_msg:
                        continue

                    try:
                        self.session.patch(f"https://api.mail.tm/messages/{msg_id}")
                    except:
                        pass

                    subject = full_msg.get("subject", "") if isinstance(full_msg, dict) else ""
                    text = full_msg.get("text", "") if isinstance(full_msg, dict) else ""
                    html_list = full_msg.get("html", []) if isinstance(full_msg, dict) else []
                    html = " ".join(html_list) if isinstance(html_list, list) else str(html_list)
                    content = f"{subject} {text} {html}"

                    codes = re.findall(r'\b(\d{4,8})\b', content)
                    for code in codes:
                        if len(code) == 6:
                            return code
            except:
                pass
            time.sleep(poll_interval)
        return None

    def cleanup(self):
        if self.account_id and self.token:
            try:
                self.session.delete(f"https://api.mail.tm/accounts/{self.account_id}")
            except:
                pass

class TempMailORG:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36",
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Origin": "https://temp-mail.org",
            "Referer": "https://temp-mail.org/",
            "sec-ch-ua": '"Not;A=Brand";v="8", "Chromium";v="150", "Google Chrome";v="150"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-site",
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
                raise Exception(f"Mailbox creation failed: {mailbox_resp.status_code}")

            data = mailbox_resp.json()
            self.token = data.get("token")
            self.email_address = data.get("mailbox")

            if not self.token or not self.email_address:
                raise Exception("No token or email received")

            self.session.headers["Authorization"] = f"Bearer {self.token}"

            return {"email": self.email_address, "token": self.token, "provider": self.provider}
        except requests.Timeout:
            raise Exception("Connection timeout. Please try again.")
        except Exception as e:
            raise Exception(f"Account creation failed: {str(e)}")

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

    def wait_for_otp(self, timeout: int = 120, poll_interval: int = 3) -> Optional[str]:
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
                    content = f"{subject} {body}"

                    codes = re.findall(r'\b(\d{4,8})\b', content)
                    for code in codes:
                        if len(code) == 6:
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
        self.device_id = self._gen_id()
        self.session_id = int(time.time() * 1000)
        self.anonymous_id = self._gen_id()

        self.session.cookies.set("anonymous_id", self.anonymous_id, domain=".musicgpt.com")

        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Content-Type": "application/json",
            "Origin": "https://musicgpt.com",
            "Referer": "https://musicgpt.com/",
            "sec-ch-ua": '"Not;A=Brand";v="8", "Chromium";v="150", "Google Chrome";v="150"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "Sec-Fetch-Site": "same-site",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
            "Connection": "keep-alive",
            "ngrok-skip-browser-warning": "yes"
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
                return {"error": "Invalid JSON response", "success": False}

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
        except requests.Timeout:
            return {"error": "Request timed out", "success": False}
        except Exception as e:
            return {"error": str(e), "success": False}

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
        retry_count = 0
        while time.time() - start_time < timeout:
            try:
                data = self.get_audio(audio_id)
                if data:
                    status = data.get("conversion_status", "")
                    if status == "SUCCESS":
                        return data
                    elif status == "FAILED":
                        return None
                retry_count = 0
            except:
                retry_count += 1
                if retry_count > 5:
                    logger.warning("Too many errors getting audio status")
                    retry_count = 0
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
        self.user_commands = {}
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
        """Check if message is from channel and if bot is mentioned"""
        
        # If private chat - always allowed
        if update.effective_chat.type == ChatType.PRIVATE:
            return True
        
        # If group/supergroup/channel - check for mention
        if update.effective_chat.type in [ChatType.GROUP, ChatType.SUPERGROUP, ChatType.CHANNEL]:
            # Check if bot is mentioned
            if not self.bot_username:
                self.bot_username = (await context.bot.get_me()).username
            
            # Check if message contains bot mention
            if update.message:
                text = update.message.text or update.message.caption or ""
                mention = f"@{self.bot_username}"
                
                # Check if mentioned
                if mention in text:
                    return True
                
                # Check if replying to bot
                if update.message.reply_to_message:
                    if update.message.reply_to_message.from_user.id == context.bot.id:
                        return True
            return False
        
        return False
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        # Check if this is a valid request
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
        
        keyboard = [
            [InlineKeyboardButton("📧 temp-mail.org", callback_data="login_org")],
            [InlineKeyboardButton("📧 mail.tm", callback_data="login_tm")],
            [InlineKeyboardButton("🔙 Back", callback_data="back")]
        ]
        
        await query.message.reply_text(
            "🔑 **Choose Login Provider**\n\n"
            "Select which temporary email service to use:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    
    async def login_provider_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.check_channel(update, context):
            return
        
        query = update.callback_query
        await query.answer()
        user_id = update.effective_user.id
        provider = query.data.replace("login_", "")
        
        status_msg = await query.message.reply_text(f"🔑 Creating email via {provider}...")
        
        try:
            if provider == "tm":
                self.temp_mail = TempMailTM()
            else:
                self.temp_mail = TempMailORG()
            
            email_data = self.temp_mail.create_account()
            
            await status_msg.edit_text(f"📧 Email created: `{email_data['email']}`\n\nRequesting OTP...")
            
            self.api = MusicGPTAPI()
            validation_token = self.api.send_otp(email_data["email"])
            
            if not validation_token:
                await status_msg.edit_text("❌ Failed to send OTP. Try again.")
                return
            
            await status_msg.edit_text(f"📧 Waiting for OTP...\n\nCheck your email: `{email_data['email']}`\n\n⏳ This may take up to 2 minutes...")
            
            otp = self.temp_mail.wait_for_otp(timeout=180)
            
            if not otp:
                await status_msg.edit_text("❌ OTP not received. Try again.")
                return
            
            await status_msg.edit_text(f"✅ OTP received: `{otp}`\n\nVerifying...")
            
            success = self.api.verify_otp(otp, validation_token)
            
            if not success:
                await status_msg.edit_text("❌ Verification failed.")
                return
            
            username = email_data["email"].split("@")[0]
            display_name = f"User_{user_id}"
            
            self.api.set_display_name(username, display_name)
            
            Database.update_session(
                user_id, 1, email_data["email"], display_name, 
                email_data.get("provider", provider), 
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
                f"Provider: `{email_data.get('provider', provider)}`\n\n"
                f"🎵 Click **'Generate Music'** to start creating!",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
            
        except Exception as e:
            await status_msg.edit_text(f"❌ Login error: {str(e)}\n\nPlease try again.")
            logger.error(f"Login error: {e}")
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
        # Check if bot is mentioned (for groups/channels)
        if not await self.check_channel(update, context):
            logger.info(f"Ignoring message from {update.effective_chat.type}: {update.effective_chat.id}")
            return
        
        user_id = update.effective_user.id
        text = update.message.text or ""
        
        # Check if awaiting prompt
        if context.user_data.get('awaiting_prompt'):
            context.user_data['awaiting_prompt'] = False
            await self.process_generation(update, context, text)
            return
        
        # Only respond if explicitly mentioned or in private
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
            
            os.makedirs("output", exist_ok=True)
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
            logger.error(f"Generate error: {e}")
            await status_msg.edit_text(f"❌ Error: {str(e)}\n\nPlease try again.")
    
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
            await query.message.reply_text(f"🔄 Fetching audio: `{audio_id[:12]}`...", parse_mode='Markdown')
            
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
                    
                    os.makedirs("output", exist_ok=True)
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
        # Check if bot is mentioned
        if not await self.check_channel(update, context):
            return
        
        query = update.callback_query
        data = query.data
        
        if data == "login":
            await self.login_callback(update, context)
        elif data == "login_org" or data == "login_tm":
            await self.login_provider_callback(update, context)
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
        logger.error(f"Update {update} caused error: {error}")
        
        # Ignore 409 Conflict errors (bot already running elsewhere)
        if "Conflict" in str(error) and "getUpdates" in str(error):
            logger.warning("Bot conflict detected - another instance is running. This is normal if you're testing.")
            return
        
        error_message = "❌ An error occurred. Please try again."
        
        if isinstance(error, requests.Timeout):
            error_message = "❌ Request timed out. Please try again."
        elif isinstance(error, ConnectionError):
            error_message = "❌ Connection error. Please check your internet."
        elif "Timed out" in str(error):
            error_message = "❌ Operation timed out. Please try again."
        
        if update and update.effective_message:
            try:
                keyboard = [[InlineKeyboardButton("🔄 Try Again", callback_data="back")]]
                await update.effective_message.reply_text(
                    error_message,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            except:
                pass

# Health check server for Render
def run_health_server():
    """Run a simple HTTP server for Render health checks"""
    try:
        from flask import Flask, jsonify
        
        health_app = Flask(__name__)
        
        @health_app.route('/')
        @health_app.route('/health')
        def health():
            return jsonify({
                "status": "healthy",
                "timestamp": datetime.now().isoformat(),
                "service": "MusicGPT Telegram Bot"
            }), 200
        
        @health_app.route('/ping')
        def ping():
            return "pong", 200
        
        # Run the health server
        health_app.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False)
    except Exception as e:
        logger.error(f"Health server error: {e}")

def main():
    if not TELEGRAM_AVAILABLE:
        print("Install: pip install python-telegram-bot")
        return
    
    # Start health check server in a separate thread
    health_thread = threading.Thread(target=run_health_server, daemon=True)
    health_thread.start()
    logger.info(f"Health check server started on port {PORT}")
    
    # Add a small delay to ensure cleanup of previous instances
    time.sleep(2)
    
    bot = MusicGPTBot()
    
    # Build application with connection pool settings
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
    print(f"🌐 Health check server running on port {PORT}")
    print("📋 Inline buttons only - no commands needed!")
    print("🎵 MusicGPT integration ready!")
    print("\n🔒 Channel Protection:")
    print("  ✅ Private chats: Always responds")
    print("  ✅ Groups: Only responds when mentioned @botname")
    print("  ✅ Channels: Only responds when mentioned @botname")
    print("  ❌ Auto-reply to channels: DISABLED")
    print("\nFlow:")
    print("  1. User clicks 'Request Access'")
    print("  2. Admin approves via button")
    print("  3. User clicks 'Login' -> chooses provider")
    print("  4. User clicks 'Generate Music' -> types prompt")
    print("  5. Bot generates and sends audio")
    
    try:
        # Use polling with specific settings to avoid conflicts
        app.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
            stop_signals=None  # Prevents issues with signal handling on Render
        )
    except KeyboardInterrupt:
        print("\n👋 Bot stopped.")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        print(f"❌ Fatal error: {e}")

if __name__ == "__main__":
    main()
