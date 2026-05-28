import logging
import json
import os
import re
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, 
    ContextTypes, MessageHandler, filters
)
from telegram import BotCommandScopeDefault, BotCommandScopeChat

# ============ CONFIGURATION ============
BOT_TOKEN = '8096001615:AAED1k-QJJx6Yuo2RXYLIB4hBsYTEZ7lbmw'
ADMIN_ID = 7354419969

# Directories
ACCOUNT_ITEMS_DIR = 'account_items'
DIGITAL_FILES_DIR = 'digital_files'
DATA_DIR = 'data'
QR_DIR = 'qr_codes'

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', 
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Create directories
for dir_path in [ACCOUNT_ITEMS_DIR, DIGITAL_FILES_DIR, DATA_DIR, QR_DIR]:
    Path(dir_path).mkdir(exist_ok=True)

# ============ HELPER FUNCTIONS ============
def get_user_display(user):
    if user.username:
        return f"@{user.username}"
    elif user.first_name:
        return user.first_name
    return f"User_{user.id}"

def make_2col_buttons(buttons):
    keyboard = []
    for i in range(0, len(buttons), 2):
        row = [buttons[i]]
        if i + 1 < len(buttons):
            row.append(buttons[i + 1])
        keyboard.append(row)
    return keyboard

# ============ STORAGE CLASS ============
class Storage:
    def __init__(self):
        self.data_folder = DATA_DIR
        self.account_items_file = os.path.join(self.data_folder, 'account_items.json')
        self.digital_files_file = os.path.join(self.data_folder, 'digital_files.json')
        self.orders_file = os.path.join(self.data_folder, 'orders.json')
        self.users_file = os.path.join(self.data_folder, 'users.json')
        self.pending_file = os.path.join(self.data_folder, 'pending.json')
        self.settings_file = os.path.join(self.data_folder, 'settings.json')
        self.announcements_file = os.path.join(self.data_folder, 'announcements.json')
        self.notifications_file = os.path.join(self.data_folder, 'notifications.json')
        self.admins_file = os.path.join(self.data_folder, 'admins.json')
        self.admin_logs_file = os.path.join(self.data_folder, 'admin_logs.json')
        self.load_data()

    def _load_json(self, filename, default):
        if os.path.exists(filename):
            try:
                with open(filename, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading {filename}: {e}")
        return default

    def _save_json(self, filename, data):
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            return True
        except Exception as e:
            logger.error(f"Error saving {filename}: {e}")
            return False

    def load_data(self):
        self.account_items = self._load_json(self.account_items_file, {})
        self.digital_files = self._load_json(self.digital_files_file, {})
        self.orders = self._load_json(self.orders_file, {})
        self.users = self._load_json(self.users_file, {})
        self.pending_payments = self._load_json(self.pending_file, {})
        self.settings = self._load_json(self.settings_file, {})
        self.announcements = self._load_json(self.announcements_file, [])
        self.notifications = self._load_json(self.notifications_file, {})
        self.admins = self._load_json(self.admins_file, [str(ADMIN_ID)])
        self.admin_logs = self._load_json(self.admin_logs_file, [])

    def save_all(self):
        self._save_json(self.account_items_file, self.account_items)
        self._save_json(self.digital_files_file, self.digital_files)
        self._save_json(self.orders_file, self.orders)
        self._save_json(self.users_file, self.users)
        self._save_json(self.pending_file, self.pending_payments)
        self._save_json(self.settings_file, self.settings)
        self._save_json(self.announcements_file, self.announcements)
        self._save_json(self.notifications_file, self.notifications)
        self._save_json(self.admins_file, self.admins)
        self._save_json(self.admin_logs_file, self.admin_logs)

    def is_admin(self, user_id):
        return str(user_id) in self.admins

    def is_master_admin(self, user_id):
        return str(user_id) == str(ADMIN_ID)

    def get_all_admins(self):
        return self.admins.copy()

    def add_admin(self, user_id, added_by, username=None):
        user_id_str = str(user_id)
        if user_id_str not in self.admins:
            self.admins.append(user_id_str)
            self.save_all()
            self.log_admin_action(added_by, 'ADD_ADMIN', f"Added admin {user_id}")
            return True
        return False

    def remove_admin(self, user_id, removed_by):
        user_id_str = str(user_id)
        if user_id_str in self.admins and user_id_str != str(ADMIN_ID):
            self.admins.remove(user_id_str)
            self.save_all()
            self.log_admin_action(removed_by, 'REMOVE_ADMIN', f"Removed admin {user_id}")
            return True
        return False

    def log_admin_action(self, admin_id, action, details):
        self.admin_logs.append({
            'admin_id': str(admin_id),
            'action': action,
            'details': details,
            'timestamp': str(datetime.now())
        })
        if len(self.admin_logs) > 500:
            self.admin_logs = self.admin_logs[-500:]
        self.save_all()

    def get_admin_logs(self, limit=50):
        return self.admin_logs[-limit:]

    def update_setting(self, key, value):
        self.settings[key] = value
        self.save_all()
        return True

    def get_setting(self, key):
        return self.settings.get(key, '⚠️ NOT SET')

    def is_setup_complete(self):
        required = ['gcash_number', 'payment_instructions', 'admin_contact', 'delivery_info']
        return all(self.settings.get(req) for req in required)

    def add_announcement(self, announcement):
        self.announcements.append({
            'id': str(int(datetime.now().timestamp())),
            'text': announcement,
            'date': str(datetime.now())
        })
        self.save_all()
        return True

    def get_announcements(self):
        return self.announcements[-5:]

    def clear_announcements(self):
        self.announcements = []
        self.save_all()
        return True

    def add_user_notification(self, user_id, notification_type, data):
        user_id_str = str(user_id)
        if user_id_str not in self.notifications:
            self.notifications[user_id_str] = []
        self.notifications[user_id_str].append({
            'type': notification_type,
            'data': data,
            'read': False,
            'date': str(datetime.now())
        })
        self.save_all()

    def get_user_notifications(self, user_id, unread_only=False):
        user_id_str = str(user_id)
        user_notifs = self.notifications.get(user_id_str, [])
        if unread_only:
            return [n for n in user_notifs if not n.get('read', False)]
        return user_notifs

    def mark_notification_read(self, user_id, notif_index):
        user_id_str = str(user_id)
        if user_id_str in self.notifications and len(self.notifications[user_id_str]) > notif_index:
            self.notifications[user_id_str][notif_index]['read'] = True
            self.save_all()
            return True
        return False

    def add_account_item(self, item):
        self.account_items[item['id']] = item
        self.save_all()
        return item['id']

    def get_account_item(self, item_id):
        return self.account_items.get(item_id)

    def get_account_items_by_game(self, game_type):
        return [item for item in self.account_items.values() if item.get('account_type', '').upper() == game_type.upper()]

    def get_all_account_items(self):
        return list(self.account_items.values())

    def update_account_item(self, item_id, updates):
        if item_id in self.account_items:
            self.account_items[item_id].update(updates)
            self.save_all()
            return True
        return False

    def delete_account_item(self, item_id):
        if item_id in self.account_items:
            img_path = self.account_items[item_id].get('image')
            if img_path and os.path.exists(img_path):
                try:
                    os.remove(img_path)
                except:
                    pass
            del self.account_items[item_id]
            self.save_all()
            return True
        return False

    def add_digital_file(self, file_item):
        self.digital_files[file_item['id']] = file_item
        self.save_all()
        return file_item['id']

    def get_digital_file(self, file_id):
        return self.digital_files.get(file_id)

    def get_all_digital_files(self):
        return list(self.digital_files.values())

    def update_digital_file(self, file_id, updates):
        if file_id in self.digital_files:
            self.digital_files[file_id].update(updates)
            self.save_all()
            return True
        return False

    def delete_digital_file(self, file_id):
        if file_id in self.digital_files:
            file_path = self.digital_files[file_id].get('file_path')
            if file_path and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except:
                    pass
            del self.digital_files[file_id]
            self.save_all()
            return True
        return False

    def add_order(self, order):
        self.orders[order['id']] = order
        self.save_all()
        return order['id']

    def update_order_status(self, order_id, status):
        if order_id in self.orders:
            self.orders[order_id]['status'] = status
            self.save_all()
            return True
        return False

    def update_order_delivery(self, order_id, delivery_details):
        if order_id in self.orders:
            self.orders[order_id]['delivery_details'] = delivery_details
            self.save_all()
            return True
        return False

    def get_user_orders(self, user_id):
        return [o for o in self.orders.values() if o['buyer_id'] == user_id]

    def add_pending_payment(self, payment_id, data):
        self.pending_payments[payment_id] = data
        self.save_all()
        return payment_id

    def get_pending_payment(self, payment_id):
        return self.pending_payments.get(payment_id)

    def remove_pending_payment(self, payment_id):
        if payment_id in self.pending_payments:
            del self.pending_payments[payment_id]
            self.save_all()
            return True
        return False

    def register_user(self, user_id, username, first_name=None):
        user_id_str = str(user_id)
        if user_id_str not in self.users:
            self.users[user_id_str] = {
                'username': username,
                'first_name': first_name,
                'joined': str(datetime.now())
            }
            self.save_all()
            return True
        return False

    def decrease_stock(self, item_id, item_type='account'):
        if item_type == 'account':
            item = self.get_account_item(item_id)
            if item:
                current_stock = item.get('stock', 1)
                if current_stock > 0:
                    new_stock = current_stock - 1
                    self.update_account_item(item_id, {'stock': new_stock})
                    if new_stock == 0:
                        self.update_account_item(item_id, {'status': 'out_of_stock'})
                    return new_stock
        else:
            item = self.get_digital_file(item_id)
            if item:
                current_stock = item.get('stock', 1)
                if current_stock > 0:
                    new_stock = current_stock - 1
                    self.update_digital_file(item_id, {'stock': new_stock})
                    if new_stock == 0:
                        self.update_digital_file(item_id, {'status': 'out_of_stock'})
                    return new_stock
        return 0

    def get_stock_status(self, item_id, item_type='account'):
        if item_type == 'account':
            item = self.get_account_item(item_id)
        else:
            item = self.get_digital_file(item_id)
        
        if not item:
            return "Out of Stock"
        
        stock = item.get('stock', 1)
        status = item.get('status', 'available')
        
        if status == 'out_of_stock' or stock <= 0:
            return "OUT OF STOCK"
        elif stock <= 5:
            return f"Only {stock} left!"
        else:
            return f"In stock ({stock} available)"

# Initialize storage
storage = Storage()

# ============ BOT HANDLERS ============
class BotHandlers:
    def __init__(self):
        self.admin_selling = {}
        self.awaiting_payment_screenshot = {}
        self.account_delivery_data = {}
        self.delivery_step = {}
        self.stock_notify = {}
        self.messages_to_delete = []

    def is_admin(self, user_id):
        return storage.is_admin(user_id)

    def is_master_admin(self, user_id):
        return storage.is_master_admin(user_id)

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = str(update.effective_user.id)
        username = update.effective_user.username
        first_name = update.effective_user.first_name
        storage.register_user(user_id, username, first_name)

        display_name = get_user_display(update.effective_user)

        if self.is_admin(user_id):
            if not storage.is_setup_complete():
                await update.message.reply_text(
                    f"👑 Welcome Admin {display_name}!\n\n"
                    f"⚠️ SETUP REQUIRED\n"
                    f"Please complete the bot setup first.\n\n"
                    f"Use /settings to configure the bot."
                )
            else:
                await update.message.reply_text(
                    f"👑 Welcome back Admin {display_name}!\n\n"
                    f"Use /menu to access admin panel or /help for commands."
                )
        else:
            if not storage.is_setup_complete():
                await update.message.reply_text(
                    f"🎉 Welcome {display_name}!\n\n"
                    f"⚠️ Shop is currently being set up by admin.\n"
                    f"Please check back later."
                )
            else:
                await update.message.reply_text(
                    f"🎉 Welcome {display_name}!\n\n"
                    f"Use /menu to browse items or /help for commands."
                )

    async def menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = str(update.effective_user.id)
        chat_id = update.effective_chat.id

        if update.callback_query:
            await update.callback_query.message.delete()
            send_func = update.callback_query.message.reply_text
        else:
            send_func = update.message.reply_text

        if self.is_admin(user_id):
            buttons = [
                InlineKeyboardButton("⚙️ Settings", callback_data='admin_settings'),
                InlineKeyboardButton("👥 Admin Management", callback_data='admin_management'),
                InlineKeyboardButton("➕ Add Account Item", callback_data='admin_add_account'),
                InlineKeyboardButton("📁 Add Files", callback_data='admin_add_file'),
                InlineKeyboardButton("💰 Approve Payments", callback_data='admin_pending'),
                InlineKeyboardButton("📦 Pending Delivery", callback_data='admin_pending_delivery'),
                InlineKeyboardButton("📊 All Orders", callback_data='admin_orders'),
                InlineKeyboardButton("👁️ View Shop", callback_data='view_shop'),
                InlineKeyboardButton("📢 Send Announcement", callback_data='admin_announcement'),
                InlineKeyboardButton("🎯 Send Promo", callback_data='admin_promo'),
                InlineKeyboardButton("📦 Stock Manager", callback_data='admin_stock_manager'),
                InlineKeyboardButton("◀️ Back", callback_data='menu'),
            ]
            keyboard = make_2col_buttons(buttons)
        else:
            unread_count = len(storage.get_user_notifications(user_id, unread_only=True))
            notif_button = f"🔔 Notifications ({unread_count})" if unread_count > 0 else "🔕 Notifications"

            buttons = [
                InlineKeyboardButton("🎮 Account Items", callback_data='account_items_menu'),
                InlineKeyboardButton("📁 Digital Files", callback_data='view_digital_files'),
                InlineKeyboardButton("📦 My Orders", callback_data='my_orders'),
                InlineKeyboardButton(notif_button, callback_data='view_notifications'),
                InlineKeyboardButton("🛒 Shop", callback_data='view_shop'),
            ]
            keyboard = make_2col_buttons(buttons)

        reply_markup = InlineKeyboardMarkup(keyboard)
        await send_func("📱 Main Menu:", reply_markup=reply_markup)

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if self.is_admin(user_id):
            help_text = """
👑 ADMIN COMMANDS

📦 PRODUCT MANAGEMENT:
/addaccount - Add new account item
/addfile - Add new digital file
/stock - Manage product stock

💰 ORDER MANAGEMENT:
/pending - View pending payments
/pendingdelivery - View orders to deliver
/orders - View all customer orders

📢 BROADCAST:
/announce - Send announcement
/promo - Send promo message

⚙️ SETTINGS:
/settings - Bot configuration

Use /menu for interactive menu
"""
        else:
            help_text = """
🛒 USER COMMANDS

/start - Start the bot
/menu - Open main menu
/shop - Browse all items
/buy <ID> - Purchase item
/orders - View your orders
/notifications - View notifications
/help - Show this help

💡 HOW TO BUY:
1. Browse items using /menu
2. Copy the item ID
3. Type /buy <item_id>
4. Send payment to GCash
5. Click "I HAVE PAID"
6. Send payment screenshot
7. Wait for admin approval
"""
        await update.message.reply_text(help_text)

    async def settings_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_admin(update.effective_user.id):
            await update.message.reply_text("❌ Unauthorized")
            return

        gcash_num = storage.get_setting('gcash_number')
        instructions = storage.get_setting('payment_instructions')
        admin_contact = storage.get_setting('admin_contact')
        delivery_info = storage.get_setting('delivery_info')

        text = f"""
⚙️ SETTINGS
━━━━━━━━━━━━━━━━━━━━

💳 GCash Number: {gcash_num}
📝 Payment Instructions: {instructions[:50] if instructions else 'Not set'}...
👤 Admin Contact: {admin_contact}
🚚 Delivery Info: {delivery_info[:50] if delivery_info else 'Not set'}...

━━━━━━━━━━━━━━━━━━━━
Use /menu to access full admin panel
"""

        await update.message.reply_text(text)

# ============ MAIN FUNCTION ============
async def main():
    """Start the bot"""
    # Create application
    application = Application.builder().token(BOT_TOKEN).build()

    # Create handlers instance
    handlers = BotHandlers()

    # Add command handlers
    application.add_handler(CommandHandler("start", handlers.start))
    application.add_handler(CommandHandler("menu", handlers.menu))
    application.add_handler(CommandHandler("help", handlers.help_command))
    application.add_handler(CommandHandler("settings", handlers.settings_command))

    # Add callback query handler
    application.add_handler(CallbackQueryHandler(handlers.handle_callback, pattern=None))

    # Add message handlers
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.handle_message))
    application.add_handler(MessageHandler(filters.PHOTO, handlers.handle_media))
    application.add_handler(MessageHandler(filters.Document.ALL, handlers.handle_media))

    # Set bot commands
    await set_bot_commands(application)

    # Start polling
    print("🤖 Bot is running...")
    print(f"👑 Admin ID: {ADMIN_ID}")
    print(f"👥 Admins: {storage.get_all_admins()}")
    
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    
    # Keep running
    await asyncio.Event().wait()

async def set_bot_commands(application: Application):
    """Set bot commands for different user types"""
    default_commands = [
        BotCommand("start", "Start the bot"),
        BotCommand("menu", "Show main menu"),
        BotCommand("shop", "Browse all items"),
        BotCommand("buy", "Purchase item by ID"),
        BotCommand("orders", "My orders"),
        BotCommand("notifications", "View notifications"),
        BotCommand("help", "Show help"),
    ]

    admin_commands = [
        BotCommand("addaccount", "Add account item"),
        BotCommand("addfile", "Add digital file"),
        BotCommand("pending", "View pending payments"),
        BotCommand("announce", "Send announcement"),
        BotCommand("promo", "Send promo"),
        BotCommand("stats", "View bot stats"),
        BotCommand("settings", "Bot settings"),
        BotCommand("stock", "Manage product stock"),
    ]

    await application.bot.set_my_commands(default_commands, scope=BotCommandScopeDefault())

    for admin_id in storage.get_all_admins():
        try:
            await application.bot.set_my_commands(
                default_commands + admin_commands,
                scope=BotCommandScopeChat(chat_id=int(admin_id))
            )
        except Exception as e:
            logger.error(f"Failed to set admin commands for {admin_id}: {e}")

# Add missing handler methods
BotHandlers.handle_callback = lambda self, update, context: None
BotHandlers.handle_message = lambda self, update, context: None  
BotHandlers.handle_media = lambda self, update, context: None

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot stopped")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        raise
