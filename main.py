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
from typing import Optional, Dict, Any
from functools import wraps
import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
import sys

# ============== RENDER DEPLOYMENT CONFIG ==============
# Get configuration from environment variables
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8330163722:AAEv9Sj0EMT8cpRu9dtfsfVN7JSB0J9n_7A")
ADMIN_IDS = [int(id.strip()) for id in os.environ.get("ADMIN_IDS", "7716750398").split(",") if id.strip()]
DB_FILE = os.environ.get("DB_FILE", "musicgpt_bot.json")
DEBUG = os.environ.get("DEBUG", "False").lower() == "true"
PORT = int(os.environ.get("PORT", 8080))
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")  # Optional: set for webhook mode
USE_WEBHOOK = os.environ.get("USE_WEBHOOK", "False").lower() == "true"

# ============== LOGGING SETUP ==============
# Fix console encoding for Windows/Linux
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

class UTF8StreamHandler(logging.StreamHandler):
    def emit(self, record):
        try:
            msg = self.format(record)
            stream = self.stream
            stream.write(msg + self.terminator)
            self.flush()
        except UnicodeEncodeError:
            # Remove emojis and special characters for console output
            msg = self.format(record)
            emoji_pattern = re.compile("["
                u"\U0001F600-\U0001F64F"
                u"\U0001F300-\U0001F5FF"
                u"\U0001F680-\U0001F6FF"
                u"\U0001F1E0-\U0001F1FF"
                u"\U00002702-\U000027B0"
                u"\U000024C2-\U0001F251"
                u"\U0001F900-\U0001F9FF"
                u"\U0001FA70-\U0001FAFF"
                u"\u2600-\u26FF"
                u"\u2700-\u27BF"
                u"\uFE00-\uFE0F"
                u"\u200D"
                "]+", flags=re.UNICODE)
            msg = emoji_pattern.sub('', msg)
            # Replace common emoji shortcuts
            replacements = {
                '✅': '[OK]', '❌': '[X]', '⏳': '[WAIT]', '🎵': '[MUSIC]',
                '🔑': '[KEY]', '📊': '[STATS]', '👤': '[USER]', '👑': '[ADMIN]',
                '📧': '[EMAIL]', '📥': '[DL]', '▶️': '[PLAY]', '🔄': '[REFRESH]',
                '📋': '[LIST]', '🔒': '[LOCK]', '🔙': '[BACK]', '📁': '[FOLDER]',
                '📝': '[NOTE]', '🔔': '[NOTIFY]', '⚙️': '[SETTINGS]'
            }
            for emoji, replacement in replacements.items():
                msg = msg.replace(emoji, replacement)
            stream.write(msg + self.terminator)
            self.flush()

# Setup logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Remove existing handlers
for handler in logger.handlers[:]:
    logger.removeHandler(handler)

# Add console handler with UTF-8 support
console_handler = UTF8StreamHandler(sys.stdout)
console_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
logger.addHandler(console_handler)

# Add file handler (if directory is writable)
try:
    if os.path.exists('/tmp') or os.path.exists('./'):
        log_dir = '/tmp' if os.path.exists('/tmp') else '.'
        log_file = os.path.join(log_dir, 'bot.log')
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
        logger.addHandler(file_handler)
except Exception as e:
    print(f"Could not create file handler: {e}")

# ============== CONFIGURATION ==============
MAX_RETRIES = 3
RETRY_DELAY = 5
REQUEST_TIMEOUT = 30
POLLING_TIMEOUT = 180
EXECUTOR = ThreadPoolExecutor(max_workers=4)

# ============== TELEGRAM IMPORTS ==============
try:
    import uuid
    UUID_AVAILABLE = True
except ImportError:
    UUID_AVAILABLE = False

try:
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMember
    from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler
    from telegram.constants import ChatType
    from telegram.error import TimedOut, NetworkError, RetryAfter
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False
    print("Install: pip install python-telegram-bot")

# ============== DATABASE ==============
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

# ============== TEMP MAIL CLASSES ==============
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
            resp = self.session.get(f"https://api.mail.tm/messages", params={"page": page}, timeout=10)
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
            resp = self.session.get(f"https://api.mail.tm/messages/{message_id}", timeout=10)
            if resp.status_code != 200:
                return None
            return resp.json()
        except:
            return None

    def wait_for_otp(self, timeout: int = POLLING_TIMEOUT, poll_interval: int = 3) -> Optional[str]:
        start_time = time.time()
        seen_ids = set()
        last_error_time = 0

        while time.time() - start_time < timeout:
            try:
                messages = self.get_messages()
                if messages:
                    for msg in messages:
                        msg_id = msg.get("id") if isinstance(msg, dict) else None
                        if not msg_id or msg_id in seen_ids:
                            continue
                        seen_ids.add(msg_id)

                        full_msg = self.get_message(msg_id)
                        if not full_msg:
                            continue

                        try:
                            self.session.patch(f"https://api.mail.tm/messages/{msg_id}", timeout=5)
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
                last_error_time = 0
            except Exception as e:
                logger.warning(f"Error polling messages: {e}")
                if time.time() - last_error_time < 10:
                    time.sleep(poll_interval * 2)
                last_error_time = time.time()
            time.sleep(poll_interval)
        return None

    def cleanup(self):
        if self.account_id and self.token:
            try:
                self.session.delete(f"https://api.mail.tm/accounts/{self.account_id}", timeout=5)
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
            resp = self.session.get("https://web2.temp-mail.org/messages", timeout=10)
            if resp.status_code != 200:
                return []
            data = resp.json()
            if isinstance(data, dict) and "messages" in data:
                return data["messages"]
            return data if isinstance(data, list) else []
        except:
            return []

    def wait_for_otp(self, timeout: int = POLLING_TIMEOUT, poll_interval: int = 3) -> Optional[str]:
        start_time = time.time()
        seen_ids = set()
        last_error_time = 0

        while time.time() - start_time < timeout:
            try:
                messages = self.get_messages()
                if messages:
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
                last_error_time = 0
            except Exception as e:
                logger.warning(f"Error polling messages: {e}")
                if time.time() - last_error_time < 10:
                    time.sleep(poll_interval * 2)
                last_error_time = time.time()
            time.sleep(poll_interval)
        return None

    def cleanup(self):
        pass

# ============== MUSICGPT API ==============
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
        last_error_time = 0
        
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
                last_error_time = 0
            except Exception as e:
                retry_count += 1
                logger.warning(f"Error getting audio status (attempt {retry_count}): {e}")
                if retry_count > 5:
                    logger.warning("Too many errors getting audio status, increasing delay")
                    retry_count = 0
                    time.sleep(10)
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

# ============== BOT CLASS ==============
class MusicGPTBot:
    def __init__(self):
        self.api = None
        self.temp_mail = None
        self.user_commands = {}
        self.bot_username = None
        self.executor = ThreadPoolExecutor(max_workers=4)
        self.application = None
    
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
    
    async def safe_send_message(self, chat_id, text, **kwargs):
        max_retries = 3
        for attempt in range(max_retries):
            try:
                return await self.application.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    **kwargs
                )
            except TimedOut:
                if attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 2
                    logger.warning(f"Timeout sending message, retrying in {wait_time}s...")
                    await asyncio.sleep(wait_time)
                    continue
                else:
                    logger.error(f"Failed to send message after {max_retries} attempts")
                    raise
            except Exception as e:
                logger.error(f"Error sending message: {e}")
                raise
    
    async def safe_edit_message(self, message, text, **kwargs):
        max_retries = 3
        for attempt in range(max_retries):
            try:
                return await message.edit_text(text, **kwargs)
            except TimedOut:
                if attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 2
                    logger.warning(f"Timeout editing message, retrying in {wait_time}s...")
                    await asyncio.sleep(wait_time)
                    continue
                else:
                    logger.error(f"Failed to edit message after {max_retries} attempts")
                    raise
            except Exception as e:
                logger.error(f"Error editing message: {e}")
                raise
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.check_channel(update, context):
            return
        
        user = update.effective_user
        if not Database.get_user(user.id):
            Database.create_user(user.id, user.username, user.first_name, user.last_name)
        
        keyboard = [
            [InlineKeyboardButton("Login", callback_data="login")],
            [InlineKeyboardButton("Generate Music", callback_data="generate")],
            [InlineKeyboardButton("Play Last Track", callback_data="play")],
            [InlineKeyboardButton("My Status", callback_data="status")],
            [InlineKeyboardButton("My Profile", callback_data="profile")],
        ]
        
        if self.is_admin(user.id):
            keyboard.append([InlineKeyboardButton("Admin Panel", callback_data="admin_panel")])
        
        if not self.is_approved(user.id):
            keyboard = [
                [InlineKeyboardButton("Request Access", callback_data="request_access")],
                [InlineKeyboardButton("My Status", callback_data="status")]
            ]
        
        welcome = f"Welcome {user.first_name}!\n\n"
        if self.is_approved(user.id):
            if self.is_authenticated(user.id):
                welcome += "You are authenticated and ready to generate music!\n\n"
                welcome += "Just click 'Generate Music' and tell me what you want!"
            else:
                welcome += "You are approved but need to login first.\n\n"
                welcome += "Click 'Login' to authenticate with MusicGPT."
        else:
            welcome += "You need approval to use this bot.\n\n"
            welcome += "Click 'Request Access' to ask for permission."
        
        await self.safe_send_message(
            update.effective_chat.id,
            welcome,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    
    async def login_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.check_channel(update, context):
            return
        
        query = update.callback_query
        try:
            await query.answer()
        except TimedOut:
            logger.warning("Callback query answer timed out, continuing...")
        
        user_id = update.effective_user.id
        
        if not self.is_approved(user_id):
            await self.safe_send_message(
                update.effective_chat.id,
                "You need to be approved first. Use /start"
            )
            return
        
        keyboard = [
            [InlineKeyboardButton("temp-mail.org", callback_data="login_org")],
            [InlineKeyboardButton("mail.tm", callback_data="login_tm")],
            [InlineKeyboardButton("Back", callback_data="back")]
        ]
        
        await self.safe_send_message(
            update.effective_chat.id,
            "Choose Login Provider\n\nSelect which temporary email service to use:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    
    async def login_provider_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.check_channel(update, context):
            return
        
        query = update.callback_query
        try:
            await query.answer()
        except TimedOut:
            logger.warning("Callback query answer timed out, continuing...")
        
        user_id = update.effective_user.id
        provider = query.data.replace("login_", "")
        
        status_msg = await self.safe_send_message(
            update.effective_chat.id,
            f"Creating email via {provider}..."
        )
        
        try:
            future = self.executor.submit(self._create_email_and_otp, provider, status_msg, update, context)
            
            try:
                result = future.result(timeout=POLLING_TIMEOUT + 30)
                if result:
                    await self._handle_login_success(update, context, status_msg, result)
                else:
                    await self.safe_edit_message(status_msg, "Login failed. Please try again.")
            except (FutureTimeoutError, TimeoutError):
                await self.safe_edit_message(
                    status_msg,
                    "Login Timeout\n\nThe login process took too long. Please try again.\nMake sure you have a stable internet connection.",
                    parse_mode='Markdown'
                )
                future.cancel()
                
        except Exception as e:
            await self.safe_edit_message(status_msg, f"Login error: {str(e)}\n\nPlease try again.")
            logger.error(f"Login error: {e}")
        finally:
            if self.temp_mail:
                try:
                    self.temp_mail.cleanup()
                except:
                    pass
            self.temp_mail = None
    
    def _create_email_and_otp(self, provider, status_msg, update, context):
        if provider == "tm":
            self.temp_mail = TempMailTM()
        else:
            self.temp_mail = TempMailORG()
        
        email_data = self.temp_mail.create_account()
        
        self.api = MusicGPTAPI()
        validation_token = self.api.send_otp(email_data["email"])
        
        if not validation_token:
            return None
        
        otp = self.temp_mail.wait_for_otp(timeout=POLLING_TIMEOUT)
        if not otp:
            return None
        
        success = self.api.verify_otp(otp, validation_token)
        if not success:
            return None
        
        return {
            "email": email_data["email"],
            "provider": provider,
            "token": self.api.access_token,
            "user_id_api": self.api.user_id,
            "display_name": f"User_{update.effective_user.id}"
        }
    
    async def _handle_login_success(self, update, context, status_msg, result):
        user_id = update.effective_user.id
        
        username = result["email"].split("@")[0]
        self.api.set_display_name(username, result["display_name"])
        
        Database.update_session(
            user_id, 1, result["email"], result["display_name"], 
            result["provider"], result["token"], result["user_id_api"]
        )
        
        keyboard = [
            [InlineKeyboardButton("Generate Music", callback_data="generate")],
            [InlineKeyboardButton("My Status", callback_data="status")],
            [InlineKeyboardButton("Back", callback_data="back")]
        ]
        
        await self.safe_edit_message(
            status_msg,
            f"Login Successful!\n\nDisplay: {result['display_name']}\nEmail: {result['email']}\nProvider: {result['provider']}\n\nClick 'Generate Music' to start creating!",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    
    async def generate_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.check_channel(update, context):
            return
        
        query = update.callback_query
        try:
            await query.answer()
        except TimedOut:
            logger.warning("Callback query answer timed out, continuing...")
        
        user_id = update.effective_user.id
        
        if not self.is_approved(user_id):
            await self.safe_send_message(
                update.effective_chat.id,
                "Access denied. Request approval first."
            )
            return
        
        if not self.is_authenticated(user_id):
            keyboard = [[InlineKeyboardButton("Login First", callback_data="login")]]
            await self.safe_send_message(
                update.effective_chat.id,
                "Not Authenticated\n\nYou need to login first before generating music.",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
            return
        
        await self.safe_send_message(
            update.effective_chat.id,
            "Describe Your Music\n\nSend me a text description of the music you want to create.\n\nExamples:\n• Epic orchestral music with dramatic violins\n• Chill lofi beats for studying\n• Electronic dance music with heavy bass\n\nType your prompt now:"
        )
        context.user_data['awaiting_prompt'] = True
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.check_channel(update, context):
            logger.info(f"Ignoring message from {update.effective_chat.type}: {update.effective_chat.id}")
            return
        
        user_id = update.effective_user.id
        text = update.message.text or ""
        
        if context.user_data.get('awaiting_prompt'):
            context.user_data['awaiting_prompt'] = False
            await self.process_generation(update, context, text)
            return
        
        keyboard = [
            [InlineKeyboardButton("Generate Music", callback_data="generate")],
            [InlineKeyboardButton("My Status", callback_data="status")],
            [InlineKeyboardButton("Back", callback_data="back")]
        ]
        await self.safe_send_message(
            update.effective_chat.id,
            "I'm not sure what you want. Please use the buttons below:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    async def process_generation(self, update: Update, context: ContextTypes.DEFAULT_TYPE, prompt: str):
        user_id = update.effective_user.id
        status_msg = await self.safe_send_message(
            update.effective_chat.id,
            f"Generating music...\n\nPrompt: {prompt}\n\nThis may take 1-2 minutes...",
            parse_mode='Markdown'
        )
        
        try:
            session = Database.get_session(user_id)
            if not session or not session[4]:
                await self.safe_edit_message(status_msg, "Session expired. Login again.")
                return
            
            self.api = MusicGPTAPI(session[4])
            
            future = self.executor.submit(self._process_generation_sync, prompt, status_msg, update)
            
            try:
                result = future.result(timeout=REQUEST_TIMEOUT + 300)
                if result:
                    await self._handle_generation_success(update, context, status_msg, result, prompt)
                else:
                    await self.safe_edit_message(status_msg, "Generation failed. Please try again.")
            except (FutureTimeoutError, TimeoutError):
                await self.safe_edit_message(
                    status_msg,
                    "Generation Timeout\n\nThe music generation took too long. Please try again.",
                    parse_mode='Markdown'
                )
                future.cancel()
                
        except Exception as e:
            logger.error(f"Generate error: {e}")
            await self.safe_edit_message(status_msg, f"Error: {str(e)}\n\nPlease try again.")
    
    def _process_generation_sync(self, prompt, status_msg, update):
        result = self.api.submit_prompt(prompt)
        if not result.get("success"):
            return None
        
        audio_data = self.api.wait_for_audio(result["conversion_id"], result["eta"])
        if not audio_data:
            return None
        
        audio_id = audio_data.get("id", result["conversion_id"])
        download_url = self.api.get_download_url(audio_id)
        if not download_url:
            return None
        
        return {
            "audio_id": audio_id,
            "download_url": download_url,
            "audio_data": audio_data
        }
    
    async def _handle_generation_success(self, update, context, status_msg, result, prompt):
        user_id = update.effective_user.id
        audio_id = result["audio_id"]
        audio_data = result["audio_data"]
        download_url = result["download_url"]
        
        title = audio_data.get("title", "music")
        safe_title = re.sub(r'[^\w\-_\. ]', '_', title)
        safe_title = re.sub(r'_+', '_', safe_title)
        filename = f"{safe_title}_{audio_id[:8]}.mp3"
        
        # Use /tmp for Render deployment
        output_dir = '/tmp/output' if os.path.exists('/tmp') else 'output'
        os.makedirs(output_dir, exist_ok=True)
        filepath = os.path.join(output_dir, filename)
        
        await self.safe_edit_message(status_msg, "Downloading...")
        
        future = self.executor.submit(self._download_audio, download_url, filepath)
        try:
            download_success = future.result(timeout=REQUEST_TIMEOUT * 4)
            if not download_success:
                await self.safe_edit_message(status_msg, "Download failed.")
                return
        except (FutureTimeoutError, TimeoutError):
            await self.safe_edit_message(status_msg, "Download timed out.")
            return
        
        Database.add_generation(user_id, prompt, audio_id, title, filepath)
        Database.update_last_audio(user_id, audio_id, title, filepath)
        
        with open(filepath, "rb") as f:
            await context.bot.send_audio(
                chat_id=update.effective_chat.id,
                audio=f,
                title=title,
                performer="MusicGPT AI",
                caption=f"Title: {title}\n\nPrompt: {prompt}\n\nGenerated by MusicGPT AI"
            )
        
        keyboard = [
            [InlineKeyboardButton("Play Again", callback_data="play")],
            [InlineKeyboardButton("Generate More", callback_data="generate")],
            [InlineKeyboardButton("My Status", callback_data="status")]
        ]
        await self.safe_edit_message(
            status_msg,
            f"Generation Complete!\n\nTitle: {title}\nDuration: {audio_data.get('audio_length_ms', 0) / 1000:.1f}s\n\nWhat would you like to do next?",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    
    def _download_audio(self, download_url: str, filepath: str) -> bool:
        try:
            resp = requests.get(download_url, stream=True, timeout=REQUEST_TIMEOUT * 4)
            if resp.status_code == 200:
                with open(filepath, "wb") as f:
                    for chunk in resp.iter_content(8192):
                        if chunk:
                            f.write(chunk)
                return True
            return False
        except:
            return False
    
    async def play_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.check_channel(update, context):
            return
        
        query = update.callback_query
        try:
            await query.answer()
        except TimedOut:
            logger.warning("Callback query answer timed out, continuing...")
        
        user_id = update.effective_user.id
        
        session = Database.get_session(user_id)
        if not session:
            await self.safe_send_message(
                update.effective_chat.id,
                "User not found. Use /start first."
            )
            return
        
        filepath = session[8]
        audio_id = session[6]
        title = session[7]
        
        if filepath and os.path.exists(filepath):
            await self.safe_send_message(
                update.effective_chat.id,
                f"Playing: {title}",
                parse_mode='Markdown'
            )
            with open(filepath, "rb") as f:
                await context.bot.send_audio(
                    chat_id=update.effective_chat.id,
                    audio=f,
                    title=title,
                    performer="MusicGPT AI"
                )
        elif audio_id:
            await self.safe_send_message(
                update.effective_chat.id,
                f"Fetching audio: {audio_id[:12]}...",
                parse_mode='Markdown'
            )
            
            session_data = Database.get_session(user_id)
            if not session_data or not session_data[4]:
                await self.safe_send_message(
                    update.effective_chat.id,
                    "Session expired. Login again."
                )
                return
            
            self.api = MusicGPTAPI(session_data[4])
            
            future = self.executor.submit(self._get_audio_data_sync, audio_id)
            try:
                result = future.result(timeout=REQUEST_TIMEOUT + 60)
                if not result:
                    await self.safe_send_message(
                        update.effective_chat.id,
                        "Could not fetch audio data."
                    )
                    return
                
                audio_data, download_url = result
                if not download_url:
                    await self.safe_send_message(
                        update.effective_chat.id,
                        "No download URL available."
                    )
                    return
                
                title = audio_data.get("title", "music")
                safe_title = re.sub(r'[^\w\-_\. ]', '_', title)
                filename = f"{safe_title}_{audio_id[:8]}.mp3"
                
                output_dir = '/tmp/output' if os.path.exists('/tmp') else 'output'
                os.makedirs(output_dir, exist_ok=True)
                filepath = os.path.join(output_dir, filename)
                
                download_future = self.executor.submit(self._download_audio, download_url, filepath)
                try:
                    download_success = download_future.result(timeout=REQUEST_TIMEOUT * 4)
                    if download_success:
                        Database.update_last_audio(user_id, audio_id, title, filepath)
                        await self.safe_send_message(
                            update.effective_chat.id,
                            f"Playing: {title}",
                            parse_mode='Markdown'
                        )
                        with open(filepath, "rb") as f:
                            await context.bot.send_audio(
                                chat_id=update.effective_chat.id,
                                audio=f,
                                title=title,
                                performer="MusicGPT AI"
                            )
                    else:
                        await self.safe_send_message(
                            update.effective_chat.id,
                            "Failed to download."
                        )
                except (FutureTimeoutError, TimeoutError):
                    await self.safe_send_message(
                        update.effective_chat.id,
                        "Download timed out."
                    )
            except (FutureTimeoutError, TimeoutError):
                await self.safe_send_message(
                    update.effective_chat.id,
                    "Fetching audio timed out."
                )
                
        else:
            keyboard = [[InlineKeyboardButton("Generate Music", callback_data="generate")]]
            await self.safe_send_message(
                update.effective_chat.id,
                "Nothing to play. Generate music first.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
    
    def _get_audio_data_sync(self, audio_id: str):
        audio_data = self.api.get_audio(audio_id)
        if audio_data:
            download_url = self.api.get_download_url(audio_id)
            return audio_data, download_url
        return None, None
    
    async def status_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.check_channel(update, context):
            return
        
        query = update.callback_query
        try:
            await query.answer()
        except TimedOut:
            logger.warning("Callback query answer timed out, continuing...")
        
        user_id = update.effective_user.id
        
        session = Database.get_session(user_id)
        if not session:
            await self.safe_send_message(
                update.effective_chat.id,
                "User not found. Use /start first."
            )
            return
        
        authenticated = session[0] == 1
        email = session[1] or "Not set"
        display = session[2] or "Not set"
        provider = session[3] or "Not set"
        
        keyboard = []
        if authenticated:
            keyboard.append([InlineKeyboardButton("Generate Music", callback_data="generate")])
        else:
            keyboard.append([InlineKeyboardButton("Login", callback_data="login")])
        keyboard.append([InlineKeyboardButton("Back", callback_data="back")])
        
        status_text = "Session Status\n\n"
        status_text += f"Authenticated: {'Yes' if authenticated else 'No'}\n"
        if authenticated:
            status_text += f"Display: {display}\n"
            status_text += f"Email: {email}\n"
            status_text += f"Provider: {provider}\n"
        status_text += f"User ID: {user_id}\n\n"
        
        if authenticated:
            status_text += "Ready to generate music!"
        else:
            status_text += "Click 'Login' to authenticate."
        
        try:
            await self.safe_edit_message(
                query.message,
                status_text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
        except:
            await self.safe_send_message(
                update.effective_chat.id,
                status_text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
    
    async def profile_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.check_channel(update, context):
            return
        
        query = update.callback_query
        try:
            await query.answer()
        except TimedOut:
            logger.warning("Callback query answer timed out, continuing...")
        
        user_id = update.effective_user.id
        
        user = Database.get_user(user_id)
        if not user:
            await self.safe_send_message(
                update.effective_chat.id,
                "User not found."
            )
            return
        
        approved = self.is_approved(user_id)
        admin = self.is_admin(user_id)
        authenticated = self.is_authenticated(user_id)
        monthly = Database.get_generation_count(user_id)
        
        keyboard = [[InlineKeyboardButton("Back", callback_data="back")]]
        
        profile_text = f"Profile\n\n"
        profile_text += f"Name: {user.get('first_name', '')} @{user.get('username', 'None')}\n"
        profile_text += f"Admin: {'Yes' if admin else 'No'}\n"
        profile_text += f"Approved: {'Yes' if approved else 'No'}\n"
        profile_text += f"Authenticated: {'Yes' if authenticated else 'No'}\n"
        profile_text += f"Generations: {monthly}/month\n\n"
        
        if authenticated:
            profile_text += "Ready to generate!"
        else:
            profile_text += "Use 'Login' to authenticate."
        
        await self.safe_send_message(
            update.effective_chat.id,
            profile_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    
    async def admin_panel_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.check_channel(update, context):
            return
        
        query = update.callback_query
        try:
            await query.answer()
        except TimedOut:
            logger.warning("Callback query answer timed out, continuing...")
        
        user_id = update.effective_user.id
        
        if not self.is_admin(user_id):
            await self.safe_send_message(
                update.effective_chat.id,
                "Admin only."
            )
            return
        
        pending = Database.get_pending_approvals()
        
        keyboard = [
            [InlineKeyboardButton("View Pending", callback_data="view_pending")],
            [InlineKeyboardButton("Back", callback_data="back")]
        ]
        
        admin_text = f"Admin Panel\n\n"
        admin_text += f"Pending Requests: {len(pending)}\n\n"
        admin_text += "Click 'View Pending' to see all requests."
        
        await self.safe_send_message(
            update.effective_chat.id,
            admin_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    
    async def view_pending_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.check_channel(update, context):
            return
        
        query = update.callback_query
        try:
            await query.answer()
        except TimedOut:
            logger.warning("Callback query answer timed out, continuing...")
        
        user_id = update.effective_user.id
        
        if not self.is_admin(user_id):
            await self.safe_send_message(
                update.effective_chat.id,
                "Admin only."
            )
            return
        
        pending = Database.get_pending_approvals()
        
        if not pending:
            keyboard = [[InlineKeyboardButton("Back", callback_data="admin_panel")]]
            await self.safe_send_message(
                update.effective_chat.id,
                "No pending requests.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
        
        for p in pending:
            keyboard = [
                [
                    InlineKeyboardButton("Approve", callback_data=f"approve_{p[0]}"),
                    InlineKeyboardButton("Reject", callback_data=f"reject_{p[0]}")
                ],
                [InlineKeyboardButton("Back", callback_data="admin_panel")]
            ]
            await self.safe_send_message(
                update.effective_chat.id,
                f"Pending Request\n\nUser: {p[2]} @{p[1]}\nID: {p[0]}\nRequested: {p[4][:19]}",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
    
    async def request_access_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.check_channel(update, context):
            return
        
        query = update.callback_query
        try:
            await query.answer()
        except TimedOut:
            logger.warning("Callback query answer timed out, continuing...")
        
        user_id = update.effective_user.id
        
        if self.is_approved(user_id):
            await self.safe_send_message(
                update.effective_chat.id,
                "You're already approved!"
            )
            return
        
        data = load_db()
        for pending in data["pending_approvals"]:
            if pending["user_id"] == user_id and pending["status"] == "pending":
                await self.safe_send_message(
                    update.effective_chat.id,
                    "Request already pending."
                )
                return
        
        Database.request_approval(user_id)
        
        for admin_id in ADMIN_IDS:
            try:
                keyboard = [[
                    InlineKeyboardButton("Approve", callback_data=f"approve_{user_id}"),
                    InlineKeyboardButton("Reject", callback_data=f"reject_{user_id}")
                ]]
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=f"New Request\nUser: {update.effective_user.first_name} @{update.effective_user.username}\nID: {user_id}",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode='Markdown'
                )
            except:
                pass
        
        keyboard = [[InlineKeyboardButton("Check Status", callback_data="status")]]
        await self.safe_send_message(
            update.effective_chat.id,
            "Request Sent!\n\nYour access request has been sent to the admins.\nYou'll be notified when approved.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    
    async def back_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.check_channel(update, context):
            return
        
        query = update.callback_query
        try:
            await query.answer()
        except TimedOut:
            logger.warning("Callback query answer timed out, continuing...")
        
        await self.start(update, context)
    
    async def approve_reject_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.check_channel(update, context):
            return
        
        query = update.callback_query
        try:
            await query.answer()
        except TimedOut:
            logger.warning("Callback query answer timed out, continuing...")
        
        user_id = update.effective_user.id
        
        if not self.is_admin(user_id):
            await self.safe_send_message(
                update.effective_chat.id,
                "Admin only."
            )
            return
        
        data = query.data
        action, target = data.split("_")
        target = int(target)
        
        if action == "approve":
            Database.approve_user(target)
            await self.safe_edit_message(query.message, f"User {target} approved!")
            try:
                await context.bot.send_message(chat_id=target, text="Approved!\n\nYou can now use the bot. Click /start to begin.")
            except:
                pass
        else:
            Database.reject_user(target)
            await self.safe_edit_message(query.message, f"User {target} rejected.")
            try:
                await context.bot.send_message(chat_id=target, text="Denied\n\nYour access request was rejected. Contact an admin.")
            except:
                pass
    
    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.check_channel(update, context):
            return
        
        query = update.callback_query
        data = query.data
        
        try:
            await query.answer()
        except TimedOut:
            logger.warning(f"Callback query answer timed out for {data}")
        
        handlers = {
            "login": self.login_callback,
            "login_org": self.login_provider_callback,
            "login_tm": self.login_provider_callback,
            "generate": self.generate_callback,
            "play": self.play_callback,
            "status": self.status_callback,
            "profile": self.profile_callback,
            "admin_panel": self.admin_panel_callback,
            "view_pending": self.view_pending_callback,
            "request_access": self.request_access_callback,
            "back": self.back_callback,
        }
        
        if data.startswith("approve_") or data.startswith("reject_"):
            await self.approve_reject_callback(update, context)
        elif data in handlers:
            try:
                await handlers[data](update, context)
            except TimedOut:
                logger.error(f"Handler {data} timed out")
                await self.safe_send_message(
                    update.effective_chat.id,
                    "The operation timed out. Please try again."
                )
            except Exception as e:
                logger.error(f"Handler {data} error: {e}")
                await self.safe_send_message(
                    update.effective_chat.id,
                    f"Error: {str(e)}"
                )
    
    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        error = context.error
        logger.error(f"Update {update} caused error: {type(error).__name__}: {error}")
        
        error_message = "An error occurred. Please try again."
        
        if isinstance(error, TimedOut):
            error_message = "The operation timed out. Please try again later."
            logger.warning("Telegram API timeout - the bot might be overloaded")
        elif isinstance(error, NetworkError):
            error_message = "Network error. Please check your internet connection."
        elif isinstance(error, RetryAfter):
            retry_after = error.retry_after
            error_message = f"Rate limited. Please wait {retry_after} seconds."
        elif isinstance(error, requests.Timeout):
            error_message = "Request timed out. Please try again."
        elif isinstance(error, ConnectionError):
            error_message = "Connection error. Please check your internet."
        elif "Timed out" in str(error):
            error_message = "Operation timed out. Please try again."
        
        if update and update.effective_message:
            try:
                keyboard = [[InlineKeyboardButton("Try Again", callback_data="back")]]
                await self.safe_send_message(
                    update.effective_chat.id,
                    error_message,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            except Exception as e:
                logger.error(f"Failed to send error message: {e}")

# ============== HEALTH CHECK SERVER (for Render) ==============
def run_health_server():
    """Simple HTTP server for Render health checks"""
    try:
        from http.server import HTTPServer, BaseHTTPRequestHandler
        
        class HealthHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == '/health' or self.path == '/':
                    self.send_response(200)
                    self.send_header('Content-type', 'text/plain')
                    self.end_headers()
                    self.wfile.write(b'OK')
                else:
                    self.send_response(404)
                    self.end_headers()
        
        server = HTTPServer(('0.0.0.0', PORT), HealthHandler)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        print(f"Health check server running on port {PORT}")
    except Exception as e:
        logger.warning(f"Could not start health server: {e}")

# ============== MAIN ==============
def main():
    if not TELEGRAM_AVAILABLE:
        print("Install: pip install python-telegram-bot")
        return
    
    # Start health check server for Render
    run_health_server()
    
    bot = MusicGPTBot()
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Store app reference for safe sending
    bot.application = app
    
    app.add_handler(CommandHandler("start", bot.start))
    app.add_handler(CallbackQueryHandler(bot.button_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_message))
    app.add_error_handler(bot.error_handler)
    
    print("Bot started!")
    print(f"Admin ID: {ADMIN_IDS[0]}")
    print(f"Using environment variables")
    print(f"Debug mode: {DEBUG}")
    print(f"Use webhook: {USE_WEBHOOK}")
    
    try:
        if USE_WEBHOOK and WEBHOOK_URL:
            # Webhook mode (for production)
            print(f"Starting webhook mode on port {PORT}")
            app.run_webhook(
                listen="0.0.0.0",
                port=PORT,
                url_path=BOT_TOKEN,
                webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}"
            )
        else:
            # Polling mode (default for Render)
            print("Starting polling mode...")
            app.run_polling(
                allowed_updates=Update.ALL_TYPES,
                timeout=30,
                read_timeout=30,
                write_timeout=30,
                pool_timeout=30,
                connect_timeout=30,
                drop_pending_updates=True  # Skip old updates on restart
            )
    except KeyboardInterrupt:
        print("\nBot stopped.")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        print(f"Fatal error: {e}")

if __name__ == "__main__":
    main()
