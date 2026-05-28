import logging
import json
import os
from datetime import datetime
from pathlib import Path
import asyncio
import re

# Try to import from new version (v20+)
try:
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
    from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
    from telegram import BotCommand, BotCommandScopeDefault, BotCommandScopeChat
    USE_V20 = True
except ImportError:
    # Fallback for older version (v13-v19)
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
    from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, MessageHandler, Filters
    from telegram.ext import CallbackContext
    from telegram import BotCommand, BotCommandScopeDefault, BotCommandScopeChat
    USE_V20 = False
    
    # Create compatibility aliases
    class ContextTypes:
        DEFAULT_TYPE = CallbackContext
    
    class filters:
        TEXT = Filters.text
        PHOTO = Filters.photo
        DOCUMENT = Filters.document
        COMMAND = Filters.command
        ALL = Filters.all

# CONFIGURATION
BOT_TOKEN = '8096001615:AAED1k-QJJx6Yuo2RXYLIB4hBsYTEZ7lbmw'
ADMIN_ID = 7354419969

# Directories
ACCOUNT_ITEMS_DIR = 'account_items'
DIGITAL_FILES_DIR = 'digital_files'
DATA_DIR = 'data'
QR_DIR = 'qr_codes'

# SETUP
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

Path(ACCOUNT_ITEMS_DIR).mkdir(exist_ok=True)
Path(DIGITAL_FILES_DIR).mkdir(exist_ok=True)
Path(DATA_DIR).mkdir(exist_ok=True)
Path(QR_DIR).mkdir(exist_ok=True)

def get_user_display(user):
    if user.username:
        return f"@{user.username}"
    elif user.first_name:
        return user.first_name
    else:
        return f"User_{user.id}"

def make_2col_buttons(buttons):
    keyboard = []
    for i in range(0, len(buttons), 2):
        row = [buttons[i]]
        if i + 1 < len(buttons):
            row.append(buttons[i + 1])
        keyboard.append(row)
    return keyboard

def escape_markdown(text):
    """Escape special characters for Markdown"""
    if not text:
        return ""
    special_chars = r'[_*`[\]()~>#+\-=|{}.!]'
    return re.sub(special_chars, lambda m: '\\' + m.group(0), str(text))

# DATA STORAGE
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

    def _load_json(self, filename, default):
        if os.path.exists(filename):
            try:
                with open(filename, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading {filename}: {e}")
                return default
        return default

    def _save_json(self, filename, data):
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            return True
        except Exception as e:
            logger.error(f"Error saving {filename}: {e}")
            return False

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
            self.log_admin_action(added_by, 'ADD_ADMIN', f"Added admin {user_id} ({username or 'Unknown'})")
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
        for req in required:
            if not self.settings.get(req):
                return False
        return True

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

storage = Storage()


# BOT HANDLERS
class BotHandlers:
    def __init__(self):
        self.admin_selling = {}
        self.editing_item = {}
        self.messages_to_delete = []
        self.account_delivery_data = {}
        self.delivery_step = {}
        self.awaiting_payment_screenshot = {}
        self.stock_notify = {}

    def is_admin(self, user_id):
        return storage.is_admin(user_id)

    def is_master_admin(self, user_id):
        return storage.is_master_admin(user_id)

    async def delete_message(self, update, context, message_to_delete=None):
        try:
            if message_to_delete:
                await message_to_delete.delete()
            elif update.callback_query and update.callback_query.message:
                await update.callback_query.message.delete()
            elif update.message:
                await update.message.delete()
        except:
            pass

    async def delete_previous_messages(self, context, chat_id):
        for msg_id in self.messages_to_delete:
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
            except:
                pass
        self.messages_to_delete = []

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = str(update.effective_user.id)
        username = update.effective_user.username
        first_name = update.effective_user.first_name
        storage.register_user(user_id, username, first_name)
        await self.delete_message(update, context)

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
        if update.callback_query:
            await update.callback_query.message.delete()
            chat_id = update.callback_query.message.chat_id
        else:
            chat_id = update.message.chat_id

        user_id = str(update.effective_user.id)

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
            ]
            keyboard = make_2col_buttons(buttons)
        else:
            if not storage.is_setup_complete():
                if update.callback_query:
                    await update.callback_query.message.reply_text("⚠️ Shop is currently being set up. Please check back later.")
                else:
                    await update.message.reply_text("⚠️ Shop is currently being set up. Please check back later.")
                return

            unread_count = len(storage.get_user_notifications(user_id, unread_only=True))
            notif_button = f"🔔 Notifications ({unread_count})" if unread_count > 0 else "🔕 Notifications"

            buttons = [
                InlineKeyboardButton("🎮 Account Items", callback_data='account_items_menu'),
                InlineKeyboardButton("📁 Digital Files", callback_data='view_digital_files'),
                InlineKeyboardButton("📦 My Orders", callback_data='my_orders'),
                InlineKeyboardButton(notif_button, callback_data='view_notifications'),
            ]
            keyboard = make_2col_buttons(buttons)

        reply_markup = InlineKeyboardMarkup(keyboard)

        if update.callback_query:
            await update.callback_query.message.reply_text("📱 Main Menu:", reply_markup=reply_markup)
        else:
            await update.message.reply_text("📱 Main Menu:", reply_markup=reply_markup)

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id

        if self.is_admin(user_id):
            is_master = self.is_master_admin(user_id)

            help_text = """
👑 ADMIN COMMANDS
━━━━━━━━━━━━━━━━━━━━

📦 PRODUCT MANAGEMENT:
/addaccount - Add new account item
/addfile - Add new digital file
/stock - Manage product stock

💰 ORDER MANAGEMENT:
/pending - View pending payments
/pendingdelivery - View orders to deliver
/orders - View all customer orders

📢 BROADCAST:
/announce - Send announcement to all users
/promo - Send promo message to all users

⚙️ SETTINGS:
/settings - Bot configuration settings
"""
            if is_master:
                help_text += """
🔐 ADMIN ONLY:
/addadmin - Add new admin
/removeadmin - Remove admin
/adminlogs - View admin action logs
"""
            help_text += """
📊 STATISTICS:
/stats - View bot statistics

💡 Use /menu for interactive menu
"""
        else:
            help_text = """
🛒 USER COMMANDS
━━━━━━━━━━━━━━━━━━━━

📱 BASIC COMMANDS:
/start - Start the bot
/menu - Open main menu
/help - Show this help

🛍️ SHOPPING:
/shop - Browse all items
/buy <ID> - Purchase item by ID
/accounts - Browse game accounts
/files - Browse digital files

📦 ORDERS:
/orders - View your order history
/notifications - View notifications

💡 HOW TO BUY:
1. Browse items using /shop or /menu
2. Copy the item ID
3. Type /buy <item_id>
4. Send payment to GCash number
5. Click "I HAVE PAID" button
6. Send your GCash payment screenshot
7. Wait for admin approval
8. Receive your item via bot

📞 Contact admin for support
"""
        await update.message.reply_text(help_text)

    async def view_shop(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.callback_query:
            await update.callback_query.message.delete()
            chat_func = update.callback_query.message.reply_text
        else:
            chat_func = update.message.reply_text
        
        accounts = storage.get_all_account_items()
        files = storage.get_all_digital_files()
        
        in_stock_accounts = [a for a in accounts if a.get('status', 'available') != 'out_of_stock' and a.get('stock', 1) > 0]
        in_stock_files = [f for f in files if f.get('status', 'available') != 'out_of_stock' and f.get('stock', 1) > 0]
        
        if not in_stock_accounts and not in_stock_files:
            buttons = [[InlineKeyboardButton("◀️ Back to Menu", callback_data='menu')]]
            await chat_func("📭 No items in shop", reply_markup=InlineKeyboardMarkup(buttons))
            return
        
        shop_text = "🛒 SHOP ITEMS\n━━━━━━━━━━━━━━━━━━━━\n\n"
        
        if in_stock_accounts:
            shop_text += "🎮 ACCOUNT ITEMS\n"
            for i, item in enumerate(in_stock_accounts, 1):
                stock_status = storage.get_stock_status(item['id'], 'account')
                shop_text += f"\n{i}. 📌 {item['name']}\n"
                shop_text += f"   └ 🎮 {item.get('account_type', 'N/A')} | 💰 ₱{item['price']:,.2f}\n"
                shop_text += f"   └ 📦 {stock_status}\n"
                shop_text += f"   └ 🆔 {item['id']}\n"
            shop_text += "\n"
        
        if in_stock_files:
            shop_text += "📁 DIGITAL FILES\n"
            for i, item in enumerate(in_stock_files, 1):
                stock_status = storage.get_stock_status(item['id'], 'file')
                shop_text += f"\n{i}. 📌 {item['name']}\n"
                shop_text += f"   └ 💰 ₱{item['price']:,.2f}\n"
                shop_text += f"   └ 📦 {stock_status}\n"
                shop_text += f"   └ 🆔 {item['id']}\n"
            shop_text += "\n"
        
        shop_text += "━━━━━━━━━━━━━━━━━━━━\n"
        shop_text += "💡 Use /buy <ID> to purchase an item\n"
        
        buttons = [
            [InlineKeyboardButton("🎮 Browse Accounts", callback_data='account_items_menu')],
            [InlineKeyboardButton("📁 Browse Files", callback_data='view_digital_files')],
            [InlineKeyboardButton("◀️ Back to Menu", callback_data='menu')]
        ]
        
        await chat_func(shop_text, reply_markup=InlineKeyboardMarkup(buttons))

    async def buy_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args:
            await update.message.reply_text(
                "❌ Please provide an item ID.\n"
                "Usage: /buy <item_id>\n\n"
                "Find item IDs using /shop command."
            )
            return
        
        item_id = context.args[0]
        
        account_item = storage.get_account_item(item_id)
        if account_item:
            if account_item.get('status') == 'out_of_stock' or account_item.get('stock', 1) <= 0:
                await update.message.reply_text(
                    f"❌ {account_item['name']} is OUT OF STOCK!\n\n"
                    f"Please check other available items using /shop"
                )
                return
            
            if not storage.is_setup_complete():
                await update.message.reply_text("⚠️ Shop is currently being set up. Please check back later.")
                return
            
            order_id = str(int(datetime.now().timestamp()))
            context.user_data['purchase'] = {
                'item_id': item_id, 'order_id': order_id, 'amount': account_item['price'],
                'item_name': account_item['name'], 'item_type': 'account'
            }
            
            gcash_num = storage.get_setting('gcash_number')
            instructions = storage.get_setting('payment_instructions')
            admin_contact = storage.get_setting('admin_contact')
            stock_status = storage.get_stock_status(item_id, 'account')
            
            msg = f"""
💵 GCASH PAYMENT
━━━━━━━━━━━━━━━━━━━━

🎮 Item: {account_item['name']}
💰 Amount: ₱{account_item['price']:,.2f}
📦 Stock Status: {stock_status}

📌 GCash Number: {gcash_num}
🔑 Reference: ACC-{order_id}

📝 Instructions:
{instructions}

✅ After payment, click the button below.

👤 Contact: {admin_contact}
"""
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ I HAVE PAID", callback_data='confirm_payment')],
                [InlineKeyboardButton("◀️ Cancel", callback_data='menu')]
            ])
            
            qr_path = storage.get_setting('qr_code_path')
            if qr_path and os.path.exists(qr_path):
                with open(qr_path, 'rb') as qr:
                    await update.message.reply_photo(qr, caption=msg, reply_markup=keyboard)
            else:
                await update.message.reply_text(msg, reply_markup=keyboard)
            return
        
        file_item = storage.get_digital_file(item_id)
        if file_item:
            if file_item.get('status') == 'out_of_stock' or file_item.get('stock', 1) <= 0:
                await update.message.reply_text(
                    f"❌ {file_item['name']} is OUT OF STOCK!\n\n"
                    f"Please check other available items using /shop"
                )
                return
            
            if not storage.is_setup_complete():
                await update.message.reply_text("⚠️ Shop is currently being set up. Please check back later.")
                return
            
            order_id = str(int(datetime.now().timestamp()))
            context.user_data['purchase'] = {
                'item_id': item_id, 'order_id': order_id, 'amount': file_item['price'],
                'item_name': file_item['name'], 'item_type': 'file',
                'file_path': file_item.get('file_path', ''), 'file_name': file_item.get('file_name', '')
            }
            
            gcash_num = storage.get_setting('gcash_number')
            instructions = storage.get_setting('payment_instructions')
            admin_contact = storage.get_setting('admin_contact')
            stock_status = storage.get_stock_status(item_id, 'file')
            
            msg = f"""
💵 GCASH PAYMENT
━━━━━━━━━━━━━━━━━━━━

📁 File: {file_item['name']}
💰 Amount: ₱{file_item['price']:,.2f}
📦 Stock Status: {stock_status}

📌 GCash Number: {gcash_num}
🔑 Reference: FILE-{order_id}

📝 Instructions:
{instructions}

✅ After payment, click the button below.

👤 Contact: {admin_contact}
"""
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ I HAVE PAID", callback_data='confirm_payment')],
                [InlineKeyboardButton("◀️ Cancel", callback_data='menu')]
            ])
            
            qr_path = storage.get_setting('qr_code_path')
            if qr_path and os.path.exists(qr_path):
                with open(qr_path, 'rb') as qr:
                    await update.message.reply_photo(qr, caption=msg, reply_markup=keyboard)
            else:
                await update.message.reply_text(msg, reply_markup=keyboard)
            return
        
        await update.message.reply_text(f"❌ Item with ID {item_id} not found.\n\nUse /shop to see available items.")

    # ============ ADMIN MANAGEMENT ============
    async def admin_management(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_admin(update.effective_user.id):
            if update.callback_query:
                await update.callback_query.message.reply_text("❌ Unauthorized")
            else:
                await update.message.reply_text("❌ Unauthorized")
            return

        if update.callback_query:
            await update.callback_query.message.delete()
            chat_id = update.callback_query.message.chat_id
            send_func = update.callback_query.message.reply_text
        else:
            await update.message.delete()
            chat_id = update.message.chat_id
            send_func = update.message.reply_text
            
        user_id = update.effective_user.id
        is_master = self.is_master_admin(user_id)

        admins = storage.get_all_admins()
        admin_list = "👥 CURRENT ADMINS:\n"
        for admin in admins:
            is_master_mark = " 👑 " if admin == str(ADMIN_ID) else ""
            admin_list += f"\n• {admin}{is_master_mark}"

        buttons = []
        if is_master:
            buttons.append(InlineKeyboardButton("➕ Add Admin", callback_data='admin_add_admin'))
            buttons.append(InlineKeyboardButton("❌ Remove Admin", callback_data='admin_remove_admin'))
            buttons.append(InlineKeyboardButton("📜 Admin Logs", callback_data='admin_view_logs'))
        buttons.append(InlineKeyboardButton("◀️ Back to Menu", callback_data='menu'))

        keyboard = make_2col_buttons(buttons)
        reply_markup = InlineKeyboardMarkup(keyboard)

        text = f"{admin_list}\n\n━━━━━━━━━━━━━━━━━━━━\n👑 Admin can add/remove other admins.\nAll admins can manage items and orders."

        await send_func(text, reply_markup=reply_markup)

    async def admin_add_admin_prompt(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_master_admin(update.effective_user.id):
            await update.callback_query.message.reply_text("❌ Only Admin can add admins!")
            return

        await update.callback_query.message.delete()
        context.user_data['awaiting_admin_id'] = True

        buttons = [[InlineKeyboardButton("◀️ Cancel", callback_data='admin_management')]]
        await update.callback_query.message.reply_text(
            "➕ ADD ADMIN\n\n"
            "Send the Telegram User ID of the new admin.\n\n"
            "How to get User ID:\n"
            "1. Ask the user to message @userinfobot\n"
            "2. They will get their ID\n\n"
            "Or send their username (e.g., @username)\n\n"
            "Type /cancel to cancel.",
            reply_markup=InlineKeyboardMarkup(buttons)
        )

    async def admin_remove_admin_prompt(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_master_admin(update.effective_user.id):
            await update.callback_query.message.reply_text("❌ Only Admin can remove admins!")
            return

        await update.callback_query.message.delete()

        admins = storage.get_all_admins()
        admin_list = "❌ REMOVE ADMIN\n\nCurrent admins:\n"
        for admin in admins:
            if admin != str(ADMIN_ID):
                admin_list += f"\n• {admin}"

        if len(admins) <= 1:
            admin_list += "\n\n⚠️ No other admins to remove."

        admin_list += "\n\nSend the User ID of the admin to remove.\n\nType /cancel to cancel."

        context.user_data['awaiting_remove_admin'] = True

        buttons = [[InlineKeyboardButton("◀️ Cancel", callback_data='admin_management')]]
        await update.callback_query.message.reply_text(admin_list, reply_markup=InlineKeyboardMarkup(buttons))

    async def admin_view_logs(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_master_admin(update.effective_user.id):
            await update.callback_query.message.reply_text("❌ Only Admin can view logs!")
            return

        await update.callback_query.message.delete()

        logs = storage.get_admin_logs(30)
        if not logs:
            buttons = [[InlineKeyboardButton("◀️ Back", callback_data='admin_management')]]
            await update.callback_query.message.reply_text("📜 No admin logs yet.", reply_markup=InlineKeyboardMarkup(buttons))
            return

        log_text = "📜 ADMIN ACTION LOGS (last 30)\n━━━━━━━━━━━━━━━━━━━━\n\n"
        for log in reversed(logs):
            log_text += f"🕐 {log['timestamp'][:16]}\n"
            log_text += f"👤 Admin: {log['admin_id'][:10]}...\n"
            log_text += f"📌 {log['action']}: {log['details']}\n"
            log_text += "━━━━━━━━━━━━━━━━━━━━\n"

        buttons = [[InlineKeyboardButton("◀️ Back", callback_data='admin_management')]]

        if len(log_text) > 4000:
            log_text = log_text[:4000] + "\n...(truncated)"

        await update.callback_query.message.reply_text(log_text, reply_markup=InlineKeyboardMarkup(buttons))

    # ============ SETTINGS ============
    async def admin_settings(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_admin(update.effective_user.id):
            if update.callback_query:
                await update.callback_query.message.reply_text("❌ Unauthorized")
            else:
                await update.message.reply_text("❌ Unauthorized")
            return

        if update.callback_query:
            await update.callback_query.message.delete()
            send_func = update.callback_query.message.reply_text
        else:
            await update.message.delete()
            send_func = update.message.reply_text

        gcash_num = storage.get_setting('gcash_number')
        instructions = storage.get_setting('payment_instructions')
        admin_contact = storage.get_setting('admin_contact')
        delivery_info = storage.get_setting('delivery_info')
        has_qr = "✅ Yes" if storage.get_setting('qr_code_path') and os.path.exists(storage.get_setting('qr_code_path')) else "❌ No"
        notify_products = storage.get_setting('notify_new_products')
        notify_orders = storage.get_setting('notify_order_updates')

        notify_products_text = "✅ ON" if notify_products else "❌ OFF" if notify_products is not None else "⚠️ NOT SET"
        notify_orders_text = "✅ ON" if notify_orders else "❌ OFF" if notify_orders is not None else "⚠️ NOT SET"

        instr_preview = str(instructions)[:100] + "..." if len(str(instructions)) > 100 else str(instructions)
        delivery_preview = str(delivery_info)[:100] + "..." if len(str(delivery_info)) > 100 else str(delivery_info)

        text = f"""
⚙️ SETTINGS
━━━━━━━━━━━━━━━━━━━━

💳 GCash Number: {gcash_num}
📱 QR Code: {has_qr}

📝 Payment Instructions:
{instr_preview}

👤 Admin Contact: {admin_contact}

🚚 Delivery Info:
{delivery_preview}

🆕 New Product Alerts: {notify_products_text}
📦 Order Update Alerts: {notify_orders_text}

━━━━━━━━━━━━━━━━━━━━
Select option to edit:
"""

        buttons = [
            InlineKeyboardButton("💳 Set GCash Number", callback_data='set_gcash'),
            InlineKeyboardButton("📱 Upload QR Code", callback_data='set_qr'),
            InlineKeyboardButton("📝 Set Payment Instructions", callback_data='set_instructions'),
            InlineKeyboardButton("👤 Set Admin Contact", callback_data='set_admin_contact'),
            InlineKeyboardButton("🚚 Set Delivery Info", callback_data='set_delivery'),
            InlineKeyboardButton("👁️ View QR Code", callback_data='view_qr'),
            InlineKeyboardButton("🗑️ Clear Announcements", callback_data='clear_announcements'),
            InlineKeyboardButton("🆕 Toggle New Product Alerts", callback_data='toggle_notify_products'),
            InlineKeyboardButton("📦 Toggle Order Updates", callback_data='toggle_notify_orders'),
            InlineKeyboardButton("✏️ Edit Items", callback_data='admin_edit_items'),
            InlineKeyboardButton("🗑️ Remove Item", callback_data='admin_remove'),
            InlineKeyboardButton("📦 Stock Manager", callback_data='admin_stock_manager'),
            InlineKeyboardButton("◀️ Back to Menu", callback_data='menu'),
        ]
        keyboard = make_2col_buttons(buttons)

        await send_func(text, reply_markup=InlineKeyboardMarkup(keyboard))

    async def set_gcash_number(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_admin(update.effective_user.id):
            await update.callback_query.message.reply_text("❌ Unauthorized")
            return

        await update.callback_query.message.delete()
        context.user_data['setting'] = 'gcash_number'
        buttons = [[InlineKeyboardButton("◀️ Cancel", callback_data='admin_settings')]]
        await update.callback_query.message.reply_text(
            "💳 Send the GCash number:\n\nType /cancel to cancel.",
            reply_markup=InlineKeyboardMarkup(buttons)
        )

    async def set_qr_code(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_admin(update.effective_user.id):
            await update.callback_query.message.reply_text("❌ Unauthorized")
            return

        await update.callback_query.message.delete()
        context.user_data['setting'] = 'qr_code'
        buttons = [[InlineKeyboardButton("◀️ Cancel", callback_data='admin_settings')]]
        await update.callback_query.message.reply_text(
            "📱 Send the QR code image:\n\nType /cancel to cancel.",
            reply_markup=InlineKeyboardMarkup(buttons)
        )

    async def set_payment_instructions(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_admin(update.effective_user.id):
            await update.callback_query.message.reply_text("❌ Unauthorized")
            return

        await update.callback_query.message.delete()
        context.user_data['setting'] = 'instructions'
        buttons = [[InlineKeyboardButton("◀️ Cancel", callback_data='admin_settings')]]
        await update.callback_query.message.reply_text(
            "📝 Send the payment instructions:\n\nType /cancel to cancel.",
            reply_markup=InlineKeyboardMarkup(buttons)
        )

    async def set_admin_contact(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_admin(update.effective_user.id):
            await update.callback_query.message.reply_text("❌ Unauthorized")
            return

        await update.callback_query.message.delete()
        context.user_data['setting'] = 'admin_contact'
        buttons = [[InlineKeyboardButton("◀️ Cancel", callback_data='admin_settings')]]
        await update.callback_query.message.reply_text(
            "👤 Send admin contact (e.g., @username):\n\nType /cancel to cancel.",
            reply_markup=InlineKeyboardMarkup(buttons)
        )

    async def set_delivery_info(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_admin(update.effective_user.id):
            await update.callback_query.message.reply_text("❌ Unauthorized")
            return

        await update.callback_query.message.delete()
        context.user_data['setting'] = 'delivery'
        buttons = [[InlineKeyboardButton("◀️ Cancel", callback_data='admin_settings')]]
        await update.callback_query.message.reply_text(
            "🚚 Send delivery information:\n\nType /cancel to cancel.",
            reply_markup=InlineKeyboardMarkup(buttons)
        )

    async def view_qr(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_admin(update.effective_user.id):
            await update.callback_query.message.reply_text("❌ Unauthorized")
            return

        await update.callback_query.message.delete()

        qr_path = storage.get_setting('qr_code_path')
        if qr_path and os.path.exists(qr_path):
            with open(qr_path, 'rb') as qr:
                buttons = [[InlineKeyboardButton("◀️ Back to Settings", callback_data='admin_settings')]]
                await update.callback_query.message.reply_photo(
                    qr,
                    caption="📱 Current GCash QR Code",
                    reply_markup=InlineKeyboardMarkup(buttons)
                )
        else:
            buttons = [[InlineKeyboardButton("◀️ Back to Settings", callback_data='admin_settings')]]
            await update.callback_query.message.reply_text(
                "❌ No QR code uploaded yet.",
                reply_markup=InlineKeyboardMarkup(buttons)
            )

    async def toggle_notify_products(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_admin(update.effective_user.id):
            await update.callback_query.message.reply_text("❌ Unauthorized")
            return

        current = storage.get_setting('notify_new_products')
        new_value = not current if current is not None else True
        storage.update_setting('notify_new_products', new_value)
        status = "ON" if new_value else "OFF"

        buttons = [[InlineKeyboardButton("◀️ Back to Settings", callback_data='admin_settings')]]
        await update.callback_query.message.reply_text(
            f"✅ New product alerts turned {status}",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        storage.log_admin_action(update.effective_user.id, 'TOGGLE_NOTIFY_PRODUCTS', f"Turned {status}")

    async def toggle_notify_orders(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_admin(update.effective_user.id):
            await update.callback_query.message.reply_text("❌ Unauthorized")
            return

        current = storage.get_setting('notify_order_updates')
        new_value = not current if current is not None else True
        storage.update_setting('notify_order_updates', new_value)
        status = "ON" if new_value else "OFF"

        buttons = [[InlineKeyboardButton("◀️ Back to Settings", callback_data='admin_settings')]]
        await update.callback_query.message.reply_text(
            f"✅ Order update alerts turned {status}",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        storage.log_admin_action(update.effective_user.id, 'TOGGLE_NOTIFY_ORDERS', f"Turned {status}")

    async def clear_announcements(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_admin(update.effective_user.id):
            await update.callback_query.message.reply_text("❌ Unauthorized")
            return

        storage.clear_announcements()
        buttons = [[InlineKeyboardButton("◀️ Back to Settings", callback_data='admin_settings')]]
        await update.callback_query.message.reply_text(
            "🗑️ All announcements cleared!",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        storage.log_admin_action(update.effective_user.id, 'CLEAR_ANNOUNCEMENTS', "Cleared all announcements")

    async def handle_setting_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        setting = context.user_data.get('setting')
        if not setting:
            return

        text = update.message.text
        await self.delete_message(update, context)

        if setting == 'gcash_number':
            storage.update_setting('gcash_number', text.strip())
            await update.message.reply_text(f"✅ GCash number set to: {text}")
            storage.log_admin_action(update.effective_user.id, 'SET_GCASH', f"Set to {text}")
        elif setting == 'instructions':
            storage.update_setting('payment_instructions', text.strip())
            await update.message.reply_text("✅ Payment instructions saved!")
            storage.log_admin_action(update.effective_user.id, 'SET_INSTRUCTIONS', "Updated payment instructions")
        elif setting == 'admin_contact':
            storage.update_setting('admin_contact', text.strip())
            await update.message.reply_text(f"✅ Admin contact set to: {text}")
            storage.log_admin_action(update.effective_user.id, 'SET_ADMIN_CONTACT', f"Set to {text}")
        elif setting == 'delivery':
            storage.update_setting('delivery_info', text.strip())
            await update.message.reply_text("✅ Delivery information saved!")
            storage.log_admin_action(update.effective_user.id, 'SET_DELIVERY_INFO', "Updated delivery info")

        context.user_data.pop('setting', None)
        await self.settings_command(update, context)

    async def handle_setting_qr(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        setting = context.user_data.get('setting')
        if setting != 'qr_code':
            return

        await self.delete_message(update, context)

        try:
            photo = await update.message.photo[-1].get_file()
            timestamp = int(datetime.now().timestamp())
            path = f"{QR_DIR}/gcash_qr_{timestamp}.jpg"
            await photo.download_to_drive(path)

            old_qr = storage.get_setting('qr_code_path')
            if old_qr and os.path.exists(old_qr):
                try:
                    os.remove(old_qr)
                except:
                    pass

            storage.update_setting('qr_code_path', path)
            await update.message.reply_text("✅ QR code uploaded successfully!")
            storage.log_admin_action(update.effective_user.id, 'UPLOAD_QR', "Uploaded new QR code")
        except Exception as e:
            logger.error(f"QR upload error: {e}")
            await update.message.reply_text("❌ Error uploading QR code. Try again.")

        context.user_data.pop('setting', None)
        await self.settings_command(update, context)

    # ============ ADD ITEMS ============
    async def admin_add_account(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_admin(update.effective_user.id):
            await update.callback_query.message.reply_text("❌ Unauthorized")
            return

        await update.callback_query.message.delete()
        user_id = update.effective_user.id
        self.admin_selling[user_id] = {'step': 'name', 'type': 'account'}
        self.messages_to_delete = []

        buttons = [[InlineKeyboardButton("◀️ Cancel", callback_data='menu')]]
        sent_msg = await update.callback_query.message.reply_text(
            "➕ Add Account Item\n\n📝 Step 1/8: Send item name:\n\nType /cancel to cancel.",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        self.messages_to_delete.append(sent_msg.message_id)

    async def admin_add_file(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_admin(update.effective_user.id):
            await update.callback_query.message.reply_text("❌ Unauthorized")
            return

        await update.callback_query.message.delete()
        user_id = update.effective_user.id
        self.admin_selling[user_id] = {'step': 'name', 'type': 'file'}
        self.messages_to_delete = []

        buttons = [[InlineKeyboardButton("◀️ Cancel", callback_data='menu')]]
        sent_msg = await update.callback_query.message.reply_text(
            "📁 Add Files\n\n📝 Step 1/5: Send file name:\n\nType /cancel to cancel.",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        self.messages_to_delete.append(sent_msg.message_id)

    async def handle_admin_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if user_id not in self.admin_selling:
            return

        step = self.admin_selling[user_id]['step']
        text = update.message.text

        if text and text.lower() == '/cancel':
            del self.admin_selling[user_id]
            await self.delete_previous_messages(context, update.effective_chat.id)
            await update.message.reply_text("❌ Cancelled.")
            await self.menu(update, context)
            return

        self.messages_to_delete.append(update.message.message_id)

        if step == 'name':
            self.admin_selling[user_id]['name'] = text.strip()
            self.admin_selling[user_id]['step'] = 'desc'
            sent_msg = await update.message.reply_text(f"✅ Name: {text}\n\n📝 Step 2/8: Send description:\n\nType /cancel to cancel.")
            self.messages_to_delete.append(sent_msg.message_id)

        elif step == 'desc':
            self.admin_selling[user_id]['desc'] = text.strip()
            self.admin_selling[user_id]['step'] = 'price'
            sent_msg = await update.message.reply_text("✅ Description saved!\n\n💰 Step 3/8: Send price (PHP):\n\nType /cancel to cancel.")
            self.messages_to_delete.append(sent_msg.message_id)

        elif step == 'price':
            try:
                price = float(text.replace('₱', '').replace(',', '').strip())
                if price <= 0: raise ValueError

                self.admin_selling[user_id]['price'] = price

                if self.admin_selling[user_id]['type'] == 'account':
                    self.admin_selling[user_id]['step'] = 'stock'
                    sent_msg = await update.message.reply_text(f"✅ Price: ₱{price:,.2f}\n\n📦 Step 4/8: Send stock quantity:\n\nType /cancel to cancel.")
                    self.messages_to_delete.append(sent_msg.message_id)
                else:
                    self.admin_selling[user_id]['step'] = 'stock'
                    sent_msg = await update.message.reply_text(f"✅ Price: ₱{price:,.2f}\n\n📦 Step 4/5: Send stock quantity:\n\nType /cancel to cancel.")
                    self.messages_to_delete.append(sent_msg.message_id)
            except:
                sent_msg = await update.message.reply_text("❌ Invalid price. Try again:\n\nType /cancel to cancel.")
                self.messages_to_delete.append(sent_msg.message_id)

        elif step == 'stock':
            try:
                stock = int(text.strip())
                if stock < 0: raise ValueError
                
                self.admin_selling[user_id]['stock'] = stock
                
                if self.admin_selling[user_id]['type'] == 'account':
                    self.admin_selling[user_id]['step'] = 'game_type'
                    sent_msg = await update.message.reply_text(f"✅ Stock set to: {stock}\n\n🎮 Step 5/8: Game type (CODM or ML):\n\nType /cancel to cancel.")
                    self.messages_to_delete.append(sent_msg.message_id)
                else:
                    self.admin_selling[user_id]['step'] = 'file'
                    sent_msg = await update.message.reply_text(f"✅ Stock set to: {stock}\n\n📎 Step 5/5: Send the file:\n\nType /cancel to cancel.")
                    self.messages_to_delete.append(sent_msg.message_id)
            except:
                sent_msg = await update.message.reply_text("❌ Invalid stock quantity. Send a number:\n\nType /cancel to cancel.")
                self.messages_to_delete.append(sent_msg.message_id)

        elif step == 'game_type':
            game = text.strip().upper()
            if game not in ['CODM', 'ML']:
                sent_msg = await update.message.reply_text("❌ Invalid. Choose CODM or ML:\n\nType /cancel to cancel.")
                self.messages_to_delete.append(sent_msg.message_id)
                return
            self.admin_selling[user_id]['account_type'] = game
            self.admin_selling[user_id]['step'] = 'rank'
            sent_msg = await update.message.reply_text(f"✅ Game: {game}\n\n⭐ Step 6/8: Account rank:\n\nType /cancel to cancel.")
            self.messages_to_delete.append(sent_msg.message_id)

        elif step == 'rank':
            self.admin_selling[user_id]['rank'] = text.strip()
            self.admin_selling[user_id]['step'] = 'server'
            sent_msg = await update.message.reply_text(f"✅ Rank: {text}\n\n🌍 Step 7/8: Server:\n\nType /cancel to cancel.")
            self.messages_to_delete.append(sent_msg.message_id)

        elif step == 'server':
            self.admin_selling[user_id]['server'] = text.strip()
            self.admin_selling[user_id]['step'] = 'photo'
            sent_msg = await update.message.reply_text(f"✅ Server: {text}\n\n📸 Step 8/8: Send photo (or /clean to skip):\n\nType /cancel to cancel.")
            self.messages_to_delete.append(sent_msg.message_id)

    async def handle_admin_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if user_id not in self.admin_selling or self.admin_selling[user_id].get('step') != 'photo':
            return

        self.messages_to_delete.append(update.message.message_id)

        try:
            photo = await update.message.photo[-1].get_file()
            timestamp = int(datetime.now().timestamp())
            path = f"{ACCOUNT_ITEMS_DIR}/account_{timestamp}.jpg"
            await photo.download_to_drive(path)
            self.admin_selling[user_id]['media'] = path
            await self.admin_confirm(update, context)
        except:
            sent_msg = await update.message.reply_text("❌ Error. Try again or /clean to skip")
            self.messages_to_delete.append(sent_msg.message_id)

    async def handle_admin_file(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id

        if user_id not in self.admin_selling or self.admin_selling[user_id].get('step') != 'file':
            return

        self.messages_to_delete.append(update.message.message_id)

        try:
            if not update.message.document:
                sent_msg = await update.message.reply_text("❌ Please send a document file (PDF, ZIP, DOC, etc.)\n\nType /cancel to cancel.")
                self.messages_to_delete.append(sent_msg.message_id)
                return

            file = update.message.document
            file_name = file.file_name
            file_obj = await file.get_file()

            file_extension = file_name.split('.')[-1].upper() if '.' in file_name else 'UNKNOWN'
            file_format = file_extension

            file_size_bytes = file.file_size
            if file_size_bytes < 1024:
                file_size = f"{file_size_bytes} B"
            elif file_size_bytes < 1024 * 1024:
                file_size = f"{file_size_bytes / 1024:.2f} KB"
            elif file_size_bytes < 1024 * 1024 * 1024:
                file_size = f"{file_size_bytes / (1024 * 1024):.2f} MB"
            else:
                file_size = f"{file_size_bytes / (1024 * 1024 * 1024):.2f} GB"

            timestamp = int(datetime.now().timestamp())
            safe_filename = f"file_{timestamp}_{file_name.replace('/', '_').replace(' ', '_')}"
            path = f"{DIGITAL_FILES_DIR}/{safe_filename}"
            await file_obj.download_to_drive(path)

            self.admin_selling[user_id]['media'] = path
            self.admin_selling[user_id]['file_name'] = file_name
            self.admin_selling[user_id]['format'] = file_format
            self.admin_selling[user_id]['size'] = file_size

            sent_msg = await update.message.reply_text(f"✅ File uploaded!\n📁 {file_name}\n📄 Format: {file_format}\n📦 Size: {file_size}\n\n📋 Proceeding to confirmation...")
            self.messages_to_delete.append(sent_msg.message_id)
            await self.admin_confirm(update, context)

        except Exception as e:
            logger.error(f"File upload error: {e}")
            sent_msg = await update.message.reply_text("❌ Error uploading file. Please try again.")
            self.messages_to_delete.append(sent_msg.message_id)

    async def admin_clean_skip(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if user_id in self.admin_selling and self.admin_selling[user_id].get('step') == 'photo':
            await self.delete_previous_messages(context, update.effective_chat.id)
            self.admin_selling[user_id]['media'] = None
            await self.admin_confirm(update, context)
        else:
            await self.delete_previous_messages(context, update.effective_chat.id)
            sent_msg = await update.message.reply_text("🧹 Cleaned up messages!")
            await self.delete_message(update, context, sent_msg)

    async def admin_confirm(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        data = self.admin_selling[user_id]
        stock = data.get('stock', 1)
        stock_warning = "⚠️ LOW STOCK!" if stock <= 5 else "✅ Normal stock"
        
        if data['type'] == 'account':
            msg = f"""
📋 CONFIRM ACCOUNT ITEM
-------------------
📌 Name: {data['name']}
💰 Price: ₱{data['price']:,.2f}
📦 Stock: {stock} ({stock_warning})
🎮 Game: {data.get('account_type', 'N/A')}
⭐ Rank: {data.get('rank', 'N/A')}
🌍 Server: {data.get('server', 'N/A')}

📝 Description:
{data['desc']}

✅ List this item?
"""
        else:
            msg = f"""
📋 CONFIRM FILE
-------------------
📌 Name: {data['name']}
💰 Price: ₱{data['price']:,.2f}
📦 Stock: {stock} ({stock_warning})
📄 Format: {data.get('format', 'Auto-detected')}
📦 Size: {data.get('size', 'Auto-detected')}

📝 Description:
{data['desc']}

✅ List this item?
"""

        buttons = [
            InlineKeyboardButton("✅ Yes", callback_data='admin_confirm_yes'),
            InlineKeyboardButton("❌ No", callback_data='admin_confirm_no'),
        ]
        keyboard = [buttons]

        if data.get('media') and data['type'] == 'account':
            try:
                with open(data['media'], 'rb') as photo:
                    sent_msg = await update.message.reply_photo(photo, caption=msg, reply_markup=InlineKeyboardMarkup(keyboard))
                    self.messages_to_delete.append(sent_msg.message_id)
            except:
                sent_msg = await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))
                self.messages_to_delete.append(sent_msg.message_id)
        else:
            sent_msg = await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))
            self.messages_to_delete.append(sent_msg.message_id)

    async def admin_confirm_yes(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if user_id not in self.admin_selling:
            await update.callback_query.message.reply_text("❌ No pending item")
            return

        await self.delete_previous_messages(context, update.effective_chat.id)

        data = self.admin_selling[user_id]
        stock = data.get('stock', 1)

        if data['type'] == 'account':
            item = {
                'id': str(int(datetime.now().timestamp())),
                'name': data['name'],
                'description': data['desc'],
                'price': data['price'],
                'stock': stock,
                'account_type': data.get('account_type', 'Game Account'),
                'rank': data.get('rank', 'N/A'),
                'server': data.get('server', 'N/A'),
                'image': data.get('media', ''),
                'created_at': str(datetime.now()),
                'status': 'available' if stock > 0 else 'out_of_stock'
            }
            storage.add_account_item(item)
            stock_msg = f"📦 Stock: {stock} ({'LOW STOCK!' if stock <= 5 else 'In Stock'})"
            msg = f"✅ Account item added!\n📌 {item['name']}\n💰 ₱{item['price']:,.2f}\n{stock_msg}"
            storage.log_admin_action(update.effective_user.id, 'ADD_ACCOUNT_ITEM', f"Added {item['name']} - ₱{item['price']} - Stock: {stock}")
        else:
            file_path = data.get('media', '')
            if not file_path or not os.path.exists(file_path):
                await update.callback_query.message.reply_text("❌ File not found! Please upload the file first.")
                return

            item = {
                'id': str(int(datetime.now().timestamp())),
                'name': data['name'],
                'description': data['desc'],
                'price': data['price'],
                'stock': stock,
                'format': data.get('format', 'Document'),
                'size': data.get('size', 'N/A'),
                'file_path': file_path,
                'file_name': data.get('file_name', 'file'),
                'created_at': str(datetime.now()),
                'status': 'available' if stock > 0 else 'out_of_stock'
            }
            storage.add_digital_file(item)
            stock_msg = f"📦 Stock: {stock} ({'LOW STOCK!' if stock <= 5 else 'In Stock'})"
            msg = f"✅ File added!\n📁 {item['name']}\n💰 ₱{item['price']:,.2f}\n{stock_msg}\n📄 Format: {item['format']}\n📦 Size: {item['size']}"
            storage.log_admin_action(update.effective_user.id, 'ADD_FILE_ITEM', f"Added {item['name']} - ₱{item['price']} - Stock: {stock}")

        del self.admin_selling[user_id]

        if storage.get_setting('notify_new_products'):
            product_type = "Account Item" if data['type'] == 'account' else "File"
            product_name = data['name']
            product_price = data['price']
            stock_info = f"\n📦 Stock: {stock} available" if stock > 0 else "\n⚠️ OUT OF STOCK"

            for uid, user_data in storage.users.items():
                if not storage.is_admin(uid):
                    try:
                        await context.bot.send_message(
                            chat_id=int(uid),
                            text=f"🆕 [ NEW PRODUCT ]{stock_info}\n\n{product_type}: {product_name}\n💰 Price: ₱{product_price:,.2f}\n\n🛒 Check the shop to buy!"
                        )
                        storage.add_user_notification(uid, 'new_product', {'title': '🆕 New Product Available!', 'message': f"{product_name} - ₱{product_price:,.2f} (Stock: {stock})"})
                    except:
                        pass

        buttons = [[InlineKeyboardButton("◀️ Back to Menu", callback_data='menu')]]
        await update.callback_query.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(buttons))

    async def admin_confirm_no(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if user_id in self.admin_selling:
            del self.admin_selling[user_id]

        await self.delete_previous_messages(context, update.effective_chat.id)
        await update.callback_query.message.reply_text("❌ Cancelled")
        await self.menu(update, context)

    # ============ VIEW ITEMS ============
    async def view_codm_items(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.callback_query.message.delete()
        items = storage.get_account_items_by_game('CODM')
        
        in_stock_items = [i for i in items if i.get('status', 'available') != 'out_of_stock' and i.get('stock', 1) > 0]
        out_of_stock_items = [i for i in items if i.get('status', 'available') == 'out_of_stock' or i.get('stock', 1) <= 0]

        if not in_stock_items and not out_of_stock_items:
            buttons = [[InlineKeyboardButton("◀️ Back to Games", callback_data='account_items_menu')]]
            await update.callback_query.message.reply_text("📭 No CODM accounts available.", reply_markup=InlineKeyboardMarkup(buttons))
            return

        for item in in_stock_items:
            stock_status = storage.get_stock_status(item['id'], 'account')
            stock_warning = " ⚠️ ONLY A FEW LEFT!" if item.get('stock', 1) <= 5 else ""
            
            text = f"""
🎮 CODM ACCOUNT{stock_warning}
-----------
📌 Name: {item['name']}
💰 Price: ₱{item['price']:,.2f}
📦 {stock_status}
⭐ Rank: {item.get('rank', 'N/A')}
🌍 Server: {item.get('server', 'N/A')}

📝 Description:
{item['description']}

🆔 ID: {item['id']}
"""
            keyboard = [[InlineKeyboardButton("🛒 Buy Now", callback_data=f'buy_account_{item["id"]}')]]

            if item.get('image') and os.path.exists(item['image']):
                try:
                    with open(item['image'], 'rb') as photo:
                        await update.callback_query.message.reply_photo(photo, caption=text, reply_markup=InlineKeyboardMarkup(keyboard))
                except:
                    await update.callback_query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
            else:
                await update.callback_query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

        for item in out_of_stock_items:
            text = f"""
🎮 CODM ACCOUNT
-----------
📌 Name: {item['name']}
💰 Price: ₱{item['price']:,.2f}
📦 OUT OF STOCK
⭐ Rank: {item.get('rank', 'N/A')}
🌍 Server: {item.get('server', 'N/A')}

❌ This item is currently unavailable.
"""
            keyboard = [[InlineKeyboardButton("🔔 Notify when in stock", callback_data=f'notify_stock_{item["id"]}')]]
            await update.callback_query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

        buttons = [[InlineKeyboardButton("◀️ Back to Games", callback_data='account_items_menu')]]
        await update.callback_query.message.reply_text("⬅️ Back", reply_markup=InlineKeyboardMarkup(buttons))

    async def view_ml_items(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.callback_query.message.delete()
        items = storage.get_account_items_by_game('ML')
        
        in_stock_items = [i for i in items if i.get('status', 'available') != 'out_of_stock' and i.get('stock', 1) > 0]
        out_of_stock_items = [i for i in items if i.get('status', 'available') == 'out_of_stock' or i.get('stock', 1) <= 0]

        if not in_stock_items and not out_of_stock_items:
            buttons = [[InlineKeyboardButton("◀️ Back to Games", callback_data='account_items_menu')]]
            await update.callback_query.message.reply_text("📭 No ML accounts available.", reply_markup=InlineKeyboardMarkup(buttons))
            return

        for item in in_stock_items:
            stock_status = storage.get_stock_status(item['id'], 'account')
            stock_warning = " ⚠️ ONLY A FEW LEFT!" if item.get('stock', 1) <= 5 else ""
            
            text = f"""
⚔️ ML ACCOUNT{stock_warning}
----------
📌 Name: {item['name']}
💰 Price: ₱{item['price']:,.2f}
📦 {stock_status}
⭐ Rank: {item.get('rank', 'N/A')}
🌍 Server: {item.get('server', 'N/A')}

📝 Description:
{item['description']}

🆔 ID: {item['id']}
"""
            keyboard = [[InlineKeyboardButton("🛒 Buy Now", callback_data=f'buy_account_{item["id"]}')]]

            if item.get('image') and os.path.exists(item['image']):
                try:
                    with open(item['image'], 'rb') as photo:
                        await update.callback_query.message.reply_photo(photo, caption=text, reply_markup=InlineKeyboardMarkup(keyboard))
                except:
                    await update.callback_query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
            else:
                await update.callback_query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

        for item in out_of_stock_items:
            text = f"""
⚔️ ML ACCOUNT
----------
📌 Name: {item['name']}
💰 Price: ₱{item['price']:,.2f}
📦 OUT OF STOCK
⭐ Rank: {item.get('rank', 'N/A')}
🌍 Server: {item.get('server', 'N/A')}

❌ This item is currently unavailable.
"""
            keyboard = [[InlineKeyboardButton("🔔 Notify when in stock", callback_data=f'notify_stock_{item["id"]}')]]
            await update.callback_query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

        buttons = [[InlineKeyboardButton("◀️ Back to Games", callback_data='account_items_menu')]]
        await update.callback_query.message.reply_text("⬅️ Back", reply_markup=InlineKeyboardMarkup(buttons))

    async def view_digital_files(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.callback_query.message.delete()
        files = storage.get_all_digital_files()
        
        in_stock_files = [f for f in files if f.get('status', 'available') != 'out_of_stock' and f.get('stock', 1) > 0]
        out_of_stock_files = [f for f in files if f.get('status', 'available') == 'out_of_stock' or f.get('stock', 1) <= 0]

        if not in_stock_files and not out_of_stock_files:
            buttons = [[InlineKeyboardButton("◀️ Back to Menu", callback_data='menu')]]
            await update.callback_query.message.reply_text("📭 No digital files available.", reply_markup=InlineKeyboardMarkup(buttons))
            return

        for file in in_stock_files:
            stock_status = storage.get_stock_status(file['id'], 'file')
            stock_warning = " ⚠️ ONLY A FEW LEFT!" if file.get('stock', 1) <= 5 else ""
            
            text = f"""
📁 DIGITAL FILE{stock_warning}
------------
📌 Name: {file['name']}
💰 Price: ₱{file['price']:,.2f}
📦 {stock_status}
📄 Format: {file.get('format', 'N/A')}
📦 Size: {file.get('size', 'N/A')}

📝 Description:
{file['description']}

🆔 ID: {file['id']}
"""
            keyboard = [[InlineKeyboardButton("🛒 Buy Now", callback_data=f'buy_file_{file["id"]}')]]
            await update.callback_query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

        for file in out_of_stock_files:
            text = f"""
📁 DIGITAL FILE
------------
📌 Name: {file['name']}
💰 Price: ₱{file['price']:,.2f}
📦 OUT OF STOCK
📄 Format: {file.get('format', 'N/A')}
📦 Size: {file.get('size', 'N/A')}

❌ This file is currently unavailable.
"""
            keyboard = [[InlineKeyboardButton("🔔 Notify when in stock", callback_data=f'notify_stock_{file["id"]}')]]
            await update.callback_query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

        buttons = [[InlineKeyboardButton("◀️ Back to Menu", callback_data='menu')]]
        await update.callback_query.message.reply_text("⬅️ Back", reply_markup=InlineKeyboardMarkup(buttons))

    # ============ STOCK MANAGEMENT ============
    async def admin_stock_manager(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_admin(update.effective_user.id):
            await update.callback_query.message.reply_text("❌ Unauthorized")
            return

        await update.callback_query.message.delete()
        
        accounts = storage.get_all_account_items()
        files = storage.get_all_digital_files()
        
        if not accounts and not files:
            buttons = [[InlineKeyboardButton("◀️ Back to Menu", callback_data='menu')]]
            await update.callback_query.message.reply_text("📭 No items", reply_markup=InlineKeyboardMarkup(buttons))
            return
        
        text = "📦 STOCK MANAGER\n━━━━━━━━━━━━━━━━━━━━\n\nSelect an item to update stock:\n\n"
        
        buttons = []
        
        for item in accounts:
            stock = item.get('stock', 1)
            status_emoji = "🟢" if stock > 5 else "🟡" if stock > 0 else "🔴"
            buttons.append(InlineKeyboardButton(f"{status_emoji} Account: {item['name'][:20]} ({stock})", callback_data=f'stock_account_{item["id"]}'))
        
        for item in files:
            stock = item.get('stock', 1)
            status_emoji = "🟢" if stock > 5 else "🟡" if stock > 0 else "🔴"
            buttons.append(InlineKeyboardButton(f"{status_emoji} File: {item['name'][:20]} ({stock})", callback_data=f'stock_file_{item["id"]}'))
        
        buttons.append(InlineKeyboardButton("◀️ Back to Menu", callback_data='menu'))
        keyboard = make_2col_buttons(buttons)
        
        await update.callback_query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    async def stock_item_prompt(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        parts = update.callback_query.data.split('_')
        item_type = parts[1]
        item_id = '_'.join(parts[2:])
        
        if item_type == 'account':
            item = storage.get_account_item(item_id)
        else:
            item = storage.get_digital_file(item_id)
        
        if not item:
            await update.callback_query.message.reply_text("❌ Item not found")
            return
        
        context.user_data['stock_item'] = {'id': item_id, 'type': item_type}
        
        current_stock = item.get('stock', 1)
        
        text = f"""
📦 UPDATE STOCK
━━━━━━━━━━━━━━━━━━━━
📌 Item: {item['name']}
💰 Price: ₱{item['price']:,.2f}
📊 Current Stock: {current_stock}

━━━━━━━━━━━━━━━━━━━━
Send the NEW STOCK QUANTITY (number):

• Type 0 to mark as out of stock
• Type a positive number for stock count
• Type /cancel to cancel

Example: 10 or 0 or 5
"""

        buttons = [[InlineKeyboardButton("◀️ Cancel", callback_data='admin_stock_manager')]]
        await update.callback_query.message.delete()
        await update.callback_query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons))

    async def process_stock_update(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        stock_data = context.user_data.get('stock_item')
        if not stock_data:
            return
        
        text = update.message.text.strip()
        
        if text.lower() == '/cancel':
            context.user_data.pop('stock_item', None)
            await update.message.reply_text("❌ Cancelled.")
            await self.menu(update, context)
            return
        
        try:
            new_stock = int(text)
            if new_stock < 0:
                await update.message.reply_text("❌ Stock cannot be negative. Send a valid number.")
                return
        except ValueError:
            await update.message.reply_text("❌ Invalid input. Send a number (e.g., 10, 0, 5)")
            return
        
        item_id = stock_data['id']
        item_type = stock_data['type']
        
        if item_type == 'account':
            storage.update_account_item(item_id, {'stock': new_stock})
            if new_stock <= 0:
                storage.update_account_item(item_id, {'status': 'out_of_stock'})
            else:
                storage.update_account_item(item_id, {'status': 'available'})
            item = storage.get_account_item(item_id)
        else:
            storage.update_digital_file(item_id, {'stock': new_stock})
            if new_stock <= 0:
                storage.update_digital_file(item_id, {'status': 'out_of_stock'})
            else:
                storage.update_digital_file(item_id, {'status': 'available'})
            item = storage.get_digital_file(item_id)
        
        context.user_data.pop('stock_item', None)
        
        status_text = "OUT OF STOCK" if new_stock <= 0 else f"IN STOCK ({new_stock} left)"
        
        await update.message.reply_text(
            f"✅ Stock updated!\n\n"
            f"📌 Item: {item['name']}\n"
            f"📊 New Stock: {new_stock}\n"
            f"📌 Status: {status_text}"
        )
        storage.log_admin_action(update.effective_user.id, 'UPDATE_STOCK', f"{item['name']} - New stock: {new_stock}")
        
        await self.menu(update, context)

    async def notify_stock_request(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        item_id = update.callback_query.data.split('_')[2]
        
        item = storage.get_account_item(item_id)
        if not item:
            item = storage.get_digital_file(item_id)
        
        if not item:
            await update.callback_query.message.reply_text("❌ Item not found")
            return
        
        user_id = str(update.effective_user.id)
        if item_id not in self.stock_notify:
            self.stock_notify[item_id] = []
        if user_id not in self.stock_notify[item_id]:
            self.stock_notify[item_id].append(user_id)
        
        await update.callback_query.message.reply_text(
            f"🔔 You will be notified when {item['name']} is back in stock!"
        )

    # ============ ORDERS ============
    async def my_orders(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.callback_query.message.delete()
        orders = storage.get_user_orders(str(update.effective_user.id))

        if not orders:
            buttons = [[InlineKeyboardButton("◀️ Back to Menu", callback_data='menu')]]
            await update.callback_query.message.reply_text("📭 No orders yet", reply_markup=InlineKeyboardMarkup(buttons))
            return

        text = "📦 YOUR ORDERS\n-----------\n"
        for order in orders[-10:]:
            text += f"\n🆔 Order: {order['id'][:8]}\n📌 Item: {order['item_name']}\n📁 Type: {order['item_type'].upper()}\n💰 Amount: ₱{order['amount']:,.2f}\n📊 Status: {order['status']}\n📅 Date: {order['date'][:10]}\n-----------\n"

        buttons = [[InlineKeyboardButton("◀️ Back to Menu", callback_data='menu')]]
        await update.callback_query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons))

    async def admin_pending(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_admin(update.effective_user.id):
            await update.callback_query.message.reply_text("❌ Unauthorized")
            return

        await update.callback_query.message.delete()

        if not storage.pending_payments:
            buttons = [[InlineKeyboardButton("◀️ Back to Menu", callback_data='menu')]]
            await update.callback_query.message.reply_text("📭 No pending payments", reply_markup=InlineKeyboardMarkup(buttons))
            return

        for payment_id, data in storage.pending_payments.items():
            buyer_display = data.get('buyer_name', f"User_{data['buyer_id']}")
            text = f"🆔 Order: {data['order_id']}\n👤 Buyer: {buyer_display}\n📌 Item: {data['item_name']}\n📁 Type: {data['item_type'].upper()}\n💰 Amount: ₱{data['amount']:,.2f}"
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Approve & Deliver", callback_data=f'approve_delivery_{payment_id}')],
                [InlineKeyboardButton("◀️ Back to Menu", callback_data='menu')]
            ])
            await update.callback_query.message.reply_text(text, reply_markup=keyboard)

    async def admin_pending_delivery(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_admin(update.effective_user.id):
            await update.callback_query.message.reply_text("❌ Unauthorized")
            return

        await update.callback_query.message.delete()

        pending_orders = []
        for order in storage.orders.values():
            if order.get('status') == '⏳ Payment Received - Waiting for Approval':
                pending_orders.append(order)

        if not pending_orders:
            buttons = [[InlineKeyboardButton("◀️ Back to Menu", callback_data='menu')]]
            await update.callback_query.message.reply_text("📭 No pending approvals.", reply_markup=InlineKeyboardMarkup(buttons))
            return

        text = "📦 PENDING APPROVALS\n-----------------\n\n"
        for order in pending_orders:
            text += f"🆔 Order: {order['id']}\n👤 Buyer: {order['buyer_name']}\n📌 Item: {order['item_name']}\n📁 Type: {order['item_type'].upper()}\n💰 Amount: ₱{order['amount']:,.2f}\n-----------------\n"

        buttons = []
        for order in pending_orders:
            for pid, pend in storage.pending_payments.items():
                if pend.get('order_id') == order['id']:
                    buttons.append(InlineKeyboardButton(f"✅ Approve: {order['id'][:8]} - {order['item_name'][:20]}", callback_data=f'approve_delivery_{pid}'))
                    break
        buttons.append(InlineKeyboardButton("◀️ Back to Menu", callback_data='menu'))

        keyboard = make_2col_buttons(buttons)
        await update.callback_query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    async def admin_orders(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_admin(update.effective_user.id):
            await update.callback_query.message.reply_text("❌ Unauthorized")
            return

        await update.callback_query.message.delete()

        if not storage.orders:
            buttons = [[InlineKeyboardButton("◀️ Back to Menu", callback_data='menu')]]
            await update.callback_query.message.reply_text("📭 No orders", reply_markup=InlineKeyboardMarkup(buttons))
            return

        text = "📊 ALL ORDERS\n----------\n"
        for order in list(storage.orders.values())[-20:]:
            buyer_display = order.get('buyer_name', f"User_{order['buyer_id']}")
            text += f"\n🆔 Order: {order['id'][:8]}\n👤 Buyer: {buyer_display}\n📌 Item: {order['item_name']}\n📁 Type: {order['item_type'].upper()}\n💰 Amount: ₱{order['amount']:,.2f}\n📊 Status: {order['status']}\n📅 Date: {order['date'][:10]}\n----------\n"

        buttons = [[InlineKeyboardButton("◀️ Back to Menu", callback_data='menu')]]
        await update.callback_query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons))

    # ============ NOTIFICATIONS ============
    async def view_notifications(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.callback_query.message.delete()
        user_id = str(update.effective_user.id)

        notifications = storage.get_user_notifications(user_id)

        if not notifications:
            buttons = [[InlineKeyboardButton("◀️ Back to Menu", callback_data='menu')]]
            await update.callback_query.message.reply_text("📭 No notifications.", reply_markup=InlineKeyboardMarkup(buttons))
            return

        text = "🔔 YOUR NOTIFICATIONS\n------------------\n"
        for i, notif in enumerate(notifications[-10:]):
            read_mark = "✅" if notif.get('read', False) else "🟢"
            text += f"\n{read_mark} [{notif['type'].upper()}]\n{notif['data'].get('title', 'Update')}\n{notif['data'].get('message', '')[:100]}\n"

        buttons = [
            InlineKeyboardButton("✓ Mark as Read", callback_data='mark_notifications_read'),
            InlineKeyboardButton("◀️ Back to Menu", callback_data='menu')
        ]
        keyboard = [buttons]

        await update.callback_query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    async def mark_notifications_read(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = str(update.effective_user.id)

        notifications = storage.get_user_notifications(user_id)
        for i in range(len(notifications)):
            storage.mark_notification_read(user_id, i)

        buttons = [[InlineKeyboardButton("◀️ Back to Notifications", callback_data='view_notifications')]]
        await update.callback_query.message.reply_text("✅ All notifications marked as read.", reply_markup=InlineKeyboardMarkup(buttons))

    # ============ BROADCAST ============
    async def admin_announcement(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_admin(update.effective_user.id):
            await update.callback_query.message.reply_text("❌ Unauthorized")
            return

        await update.callback_query.message.delete()
        context.user_data['announcement_mode'] = True

        buttons = [[InlineKeyboardButton("◀️ Cancel", callback_data='menu')]]
        await update.callback_query.message.reply_text(
            "📢 Send the announcement message to broadcast to all users:\n\nType /cancel to cancel.",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        storage.log_admin_action(update.effective_user.id, 'START_ANNOUNCEMENT', "Started announcement broadcast")

    async def admin_promo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_admin(update.effective_user.id):
            await update.callback_query.message.reply_text("❌ Unauthorized")
            return

        await update.callback_query.message.delete()
        context.user_data['promo_mode'] = True

        buttons = [[InlineKeyboardButton("◀️ Cancel", callback_data='menu')]]
        await update.callback_query.message.reply_text(
            "🎯 Send the promo message to broadcast to all users:\n\nType /cancel to cancel.",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        storage.log_admin_action(update.effective_user.id, 'START_PROMO', "Started promo broadcast")

    async def process_announcement(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.user_data.get('announcement_mode'):
            return

        announcement_text = update.message.text
        await self.delete_message(update, context)

        storage.add_announcement(announcement_text)

        sent_count = 0
        for user_id, user_data in storage.users.items():
            try:
                await context.bot.send_message(
                    chat_id=int(user_id),
                    text=f"📢 [ ANNOUNCEMENT ]\n\n{announcement_text}\n\n- Admin"
                )
                storage.add_user_notification(user_id, 'announcement', {'title': '📢 New Announcement', 'message': announcement_text})
                sent_count += 1
            except:
                pass

        await update.message.reply_text(f"✅ Announcement sent to {sent_count} users and saved to database.")
        storage.log_admin_action(update.effective_user.id, 'SEND_ANNOUNCEMENT', f"Sent to {sent_count} users")
        context.user_data.pop('announcement_mode', None)
        await self.menu(update, context)

    async def process_promo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.user_data.get('promo_mode'):
            return

        promo_text = update.message.text
        await self.delete_message(update, context)

        sent_count = 0
        for user_id, user_data in storage.users.items():
            try:
                await context.bot.send_message(
                    chat_id=int(user_id),
                    text=f"🎯 [ PROMO / DEAL ]\n\n{promo_text}\n\n- Admin"
                )
                storage.add_user_notification(user_id, 'promo', {'title': '🎯 New Promo!', 'message': promo_text})
                sent_count += 1
            except:
                pass

        await update.message.reply_text(f"✅ Promo sent to {sent_count} users.")
        storage.log_admin_action(update.effective_user.id, 'SEND_PROMO', f"Sent promo to {sent_count} users")
        context.user_data.pop('promo_mode', None)
        await self.menu(update, context)

    # ============ EDIT ITEMS ============
    async def admin_edit_items(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_admin(update.effective_user.id):
            await update.callback_query.message.reply_text("❌ Unauthorized")
            return

        await update.callback_query.message.delete()

        accounts = storage.get_all_account_items()
        files = storage.get_all_digital_files()

        if not accounts and not files:
            buttons = [[InlineKeyboardButton("◀️ Back to Settings", callback_data='admin_settings')]]
            await update.callback_query.message.reply_text("📭 No items to edit", reply_markup=InlineKeyboardMarkup(buttons))
            return

        buttons = []
        for item in accounts:
            stock = item.get('stock', 1)
            stock_indicator = "🟢" if stock > 5 else "🟡" if stock > 0 else "🔴"
            buttons.append(InlineKeyboardButton(f"{stock_indicator} Edit Account: {item['name'][:20]}", callback_data=f'edit_account_{item["id"]}'))
        for item in files:
            stock = item.get('stock', 1)
            stock_indicator = "🟢" if stock > 5 else "🟡" if stock > 0 else "🔴"
            buttons.append(InlineKeyboardButton(f"{stock_indicator} Edit File: {item['name'][:20]}", callback_data=f'edit_file_{item["id"]}'))
        buttons.append(InlineKeyboardButton("◀️ Back to Settings", callback_data='admin_settings'))

        keyboard = make_2col_buttons(buttons)
        await update.callback_query.message.reply_text("✏️ Select item to edit:", reply_markup=InlineKeyboardMarkup(keyboard))

    async def edit_account_item(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.callback_query.message.delete()
        item_id = update.callback_query.data.split('_')[2]
        item = storage.get_account_item(item_id)

        if not item:
            await update.callback_query.message.reply_text("❌ Item not found")
            return

        context.user_data['editing'] = {'id': item_id, 'type': 'account'}
        stock = item.get('stock', 1)
        stock_warning = "⚠️ LOW STOCK!" if stock <= 5 else "✅ Normal"

        text = f"""
✏️ EDITING: {item['name']}
----------------------
📌 Name: {item['name']}
💰 Price: ₱{item['price']:,.2f}
📦 Stock: {stock} ({stock_warning})
🎮 Game: {item.get('account_type', 'N/A')}
⭐ Rank: {item.get('rank', 'N/A')}
🌍 Server: {item.get('server', 'N/A')}

What would you like to edit?
"""

        buttons = [
            InlineKeyboardButton("📌 Name", callback_data='edit_field_name'),
            InlineKeyboardButton("💰 Price", callback_data='edit_field_price'),
            InlineKeyboardButton("📦 Stock", callback_data='edit_field_stock'),
            InlineKeyboardButton("🎮 Game Type", callback_data='edit_field_game'),
            InlineKeyboardButton("⭐ Rank", callback_data='edit_field_rank'),
            InlineKeyboardButton("🌍 Server", callback_data='edit_field_server'),
            InlineKeyboardButton("📝 Description", callback_data='edit_field_desc'),
            InlineKeyboardButton("📸 Change Photo", callback_data='edit_field_photo'),
            InlineKeyboardButton("❌ Cancel", callback_data='admin_edit_items'),
        ]
        keyboard = make_2col_buttons(buttons)

        await update.callback_query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    async def edit_file_item(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.callback_query.message.delete()
        file_id = update.callback_query.data.split('_')[2]
        file = storage.get_digital_file(file_id)

        if not file:
            await update.callback_query.message.reply_text("❌ File not found")
            return

        context.user_data['editing'] = {'id': file_id, 'type': 'file'}
        stock = file.get('stock', 1)
        stock_warning = "⚠️ LOW STOCK!" if stock <= 5 else "✅ Normal"

        text = f"""
✏️ EDITING: {file['name']}
---------------------
📌 Name: {file['name']}
💰 Price: ₱{file['price']:,.2f}
📦 Stock: {stock} ({stock_warning})
📄 Format: {file.get('format', 'N/A')}
📦 Size: {file.get('size', 'N/A')}

What would you like to edit?
"""

        buttons = [
            InlineKeyboardButton("📌 Name", callback_data='edit_field_name'),
            InlineKeyboardButton("💰 Price", callback_data='edit_field_price'),
            InlineKeyboardButton("📦 Stock", callback_data='edit_field_stock'),
            InlineKeyboardButton("📄 Format", callback_data='edit_field_format'),
            InlineKeyboardButton("📦 Size", callback_data='edit_field_size'),
            InlineKeyboardButton("📝 Description", callback_data='edit_field_desc'),
            InlineKeyboardButton("📁 Change File", callback_data='edit_field_file'),
            InlineKeyboardButton("❌ Cancel", callback_data='admin_edit_items'),
        ]
        keyboard = make_2col_buttons(buttons)

        await update.callback_query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    async def handle_edit_field(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        field = update.callback_query.data.split('_')[2]
        context.user_data['edit_field'] = field

        field_names = {
            'name': "📌 Send new name:\n\nType /cancel to cancel.",
            'price': "💰 Send new price (PHP):\n\nType /cancel to cancel.",
            'stock': "📦 Send new stock quantity (number):\n\nType /cancel to cancel.",
            'game': "🎮 Send new game type (CODM or ML):\n\nType /cancel to cancel.",
            'rank': "⭐ Send new rank:\n\nType /cancel to cancel.",
            'server': "🌍 Send new server:\n\nType /cancel to cancel.",
            'desc': "📝 Send new description:\n\nType /cancel to cancel.",
            'format': "📄 Send new format:\n\nType /cancel to cancel.",
            'size': "📦 Send new size:\n\nType /cancel to cancel.",
            'photo': "📸 Send new photo:\n\nType /cancel to cancel.",
            'file': "📁 Send new file:\n\nType /cancel to cancel."
        }

        buttons = [[InlineKeyboardButton("◀️ Cancel", callback_data='admin_edit_items')]]
        await update.callback_query.message.reply_text(field_names.get(field, "Send new value:"), reply_markup=InlineKeyboardMarkup(buttons))

    async def process_edit_value(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        editing = context.user_data.get('editing')
        field = context.user_data.get('edit_field')

        if not editing or not field:
            return

        text = update.message.text
        await self.delete_message(update, context)

        if text and text.lower() == '/cancel':
            context.user_data.pop('edit_field', None)
            await update.message.reply_text("❌ Cancelled.")
            await self.admin_edit_items(update, context)
            return

        updates = {}
        old_stock = None

        if field == 'name':
            updates['name'] = text.strip()
        elif field == 'price':
            try:
                price = float(text.replace('₱', '').replace(',', '').strip())
                updates['price'] = price
            except:
                await update.message.reply_text("❌ Invalid price. Cancelled.")
                context.user_data.pop('edit_field', None)
                return
        elif field == 'stock':
            try:
                new_stock = int(text.strip())
                if new_stock < 0:
                    await update.message.reply_text("❌ Stock cannot be negative.")
                    return
                
                if editing['type'] == 'account':
                    old_item = storage.get_account_item(editing['id'])
                else:
                    old_item = storage.get_digital_file(editing['id'])
                old_stock = old_item.get('stock', 1) if old_item else 1
                
                updates['stock'] = new_stock
                updates['status'] = 'available' if new_stock > 0 else 'out_of_stock'
                
            except:
                await update.message.reply_text("❌ Invalid stock quantity. Send a number.")
                return
        elif field == 'game':
            game = text.strip().upper()
            if game not in ['CODM', 'ML']:
                await update.message.reply_text("❌ Invalid. Use CODM or ML")
                return
            updates['account_type'] = game
        elif field == 'rank':
            updates['rank'] = text.strip()
        elif field == 'server':
            updates['server'] = text.strip()
        elif field == 'desc':
            updates['description'] = text.strip()
        elif field == 'format':
            updates['format'] = text.strip()
        elif field == 'size':
            updates['size'] = text.strip()

        if editing['type'] == 'account':
            storage.update_account_item(editing['id'], updates)
        else:
            storage.update_digital_file(editing['id'], updates)

        await update.message.reply_text(f"✅ {field} updated successfully!")
        
        context.user_data.pop('edit_field', None)
        await self.admin_edit_items(update, context)

    async def handle_edit_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        editing = context.user_data.get('editing')
        field = context.user_data.get('edit_field')

        if not editing or field != 'photo':
            return

        await self.delete_message(update, context)

        try:
            photo = await update.message.photo[-1].get_file()
            timestamp = int(datetime.now().timestamp())
            path = f"{ACCOUNT_ITEMS_DIR}/account_{timestamp}.jpg"
            await photo.download_to_drive(path)

            old_item = storage.get_account_item(editing['id'])
            if old_item and old_item.get('image') and os.path.exists(old_item['image']):
                try:
                    os.remove(old_item['image'])
                except:
                    pass

            storage.update_account_item(editing['id'], {'image': path})
            await update.message.reply_text("✅ Photo updated successfully!")
        except:
            await update.message.reply_text("❌ Error uploading photo. Try again.")

        context.user_data.pop('edit_field', None)
        await self.admin_edit_items(update, context)

    async def handle_edit_file_upload(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        editing = context.user_data.get('editing')
        field = context.user_data.get('edit_field')

        if not editing or field != 'file':
            return

        await self.delete_message(update, context)

        try:
            if not update.message.document:
                await update.message.reply_text("❌ Please send a document file.")
                return

            file = update.message.document
            file_name = file.file_name
            file_obj = await file.get_file()

            file_extension = file_name.split('.')[-1].upper() if '.' in file_name else 'UNKNOWN'
            file_format = file_extension

            file_size_bytes = file.file_size
            if file_size_bytes < 1024:
                file_size = f"{file_size_bytes} B"
            elif file_size_bytes < 1024 * 1024:
                file_size = f"{file_size_bytes / 1024:.2f} KB"
            elif file_size_bytes < 1024 * 1024 * 1024:
                file_size = f"{file_size_bytes / (1024 * 1024):.2f} MB"
            else:
                file_size = f"{file_size_bytes / (1024 * 1024 * 1024):.2f} GB"

            timestamp = int(datetime.now().timestamp())
            path = f"{DIGITAL_FILES_DIR}/file_{timestamp}_{file_name.replace('/', '_')}"
            await file_obj.download_to_drive(path)

            updates = {
                'file_path': path,
                'file_name': file_name,
                'format': file_format,
                'size': file_size
            }

            old_item = storage.get_digital_file(editing['id'])
            if old_item and old_item.get('file_path') and os.path.exists(old_item['file_path']):
                try:
                    os.remove(old_item['file_path'])
                except:
                    pass

            storage.update_digital_file(editing['id'], updates)
            await update.message.reply_text(f"✅ File updated!\n📄 Format: {file_format}\n📦 Size: {file_size}")
        except:
            await update.message.reply_text("❌ Error uploading file. Try again.")

        context.user_data.pop('edit_field', None)
        await self.admin_edit_items(update, context)

    # ============ REMOVE ITEMS ============
    async def admin_remove(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_admin(update.effective_user.id):
            await update.callback_query.message.reply_text("❌ Unauthorized")
            return

        await update.callback_query.message.delete()
        accounts = storage.get_all_account_items()
        files = storage.get_all_digital_files()

        if not accounts and not files:
            buttons = [[InlineKeyboardButton("◀️ Back to Settings", callback_data='admin_settings')]]
            await update.callback_query.message.reply_text("📭 No items to remove", reply_markup=InlineKeyboardMarkup(buttons))
            return

        buttons = []
        for item in accounts:
            stock = item.get('stock', 1)
            stock_indicator = "🟢" if stock > 5 else "🟡" if stock > 0 else "🔴"
            buttons.append(InlineKeyboardButton(f"{stock_indicator} Account: {item['name'][:20]}", callback_data=f'remove_account_{item["id"]}'))
        for item in files:
            stock = item.get('stock', 1)
            stock_indicator = "🟢" if stock > 5 else "🟡" if stock > 0 else "🔴"
            buttons.append(InlineKeyboardButton(f"{stock_indicator} File: {item['name'][:20]}", callback_data=f'remove_file_{item["id"]}'))
        buttons.append(InlineKeyboardButton("◀️ Back to Settings", callback_data='admin_settings'))

        keyboard = make_2col_buttons(buttons)
        await update.callback_query.message.reply_text("🗑️ Select item to remove:", reply_markup=InlineKeyboardMarkup(keyboard))

    async def remove_account(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        item_id = update.callback_query.data.split('_')[2]
        if storage.delete_account_item(item_id):
            buttons = [[InlineKeyboardButton("◀️ Back to Remove Menu", callback_data='admin_remove')]]
            await update.callback_query.message.reply_text("✅ Item removed", reply_markup=InlineKeyboardMarkup(buttons))
            storage.log_admin_action(update.effective_user.id, 'REMOVE_ACCOUNT_ITEM', f"Removed item {item_id}")
        else:
            await update.callback_query.message.reply_text("❌ Not found")

    async def remove_file(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        file_id = update.callback_query.data.split('_')[2]
        if storage.delete_digital_file(file_id):
            buttons = [[InlineKeyboardButton("◀️ Back to Remove Menu", callback_data='admin_remove')]]
            await update.callback_query.message.reply_text("✅ File removed", reply_markup=InlineKeyboardMarkup(buttons))
            storage.log_admin_action(update.effective_user.id, 'REMOVE_FILE_ITEM', f"Removed file {file_id}")
        else:
            await update.callback_query.message.reply_text("❌ Not found")

    # ============ BUY ACTIONS ============
    async def buy_account_item(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.callback_query.message.delete()
        item_id = update.callback_query.data.split('_')[2]
        item = storage.get_account_item(item_id)

        if not item:
            await update.callback_query.message.reply_text("❌ Item not found")
            return
        
        if item.get('status') == 'out_of_stock' or item.get('stock', 1) <= 0:
            await update.callback_query.message.reply_text(f"❌ {item['name']} is OUT OF STOCK!")
            return

        order_id = str(int(datetime.now().timestamp()))
        context.user_data['purchase'] = {
            'item_id': item_id, 'order_id': order_id, 'amount': item['price'],
            'item_name': item['name'], 'item_type': 'account'
        }

        gcash_num = storage.get_setting('gcash_number')
        instructions = storage.get_setting('payment_instructions')
        admin_contact = storage.get_setting('admin_contact')
        stock_status = storage.get_stock_status(item_id, 'account')

        msg = f"""
💵 GCASH PAYMENT
-------------
🎮 Item: {item['name']}
💰 Amount: ₱{item['price']:,.2f}
📦 {stock_status}

📌 GCash Number: {gcash_num}
🔑 Reference: ACC-{order_id}

📝 Instructions:
{instructions}

✅ After payment, click I HAVE PAID below.

👤 Contact: {admin_contact}
"""

        qr_path = storage.get_setting('qr_code_path')
        keyboard = [[InlineKeyboardButton("✅ I HAVE PAID", callback_data='confirm_payment'), InlineKeyboardButton("◀️ Cancel", callback_data='menu')]]

        if qr_path and os.path.exists(qr_path):
            with open(qr_path, 'rb') as qr:
                await update.callback_query.message.reply_photo(qr, caption=msg, reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await update.callback_query.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))

    async def buy_digital_file(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.callback_query.message.delete()
        file_id = update.callback_query.data.split('_')[2]
        file = storage.get_digital_file(file_id)

        if not file:
            await update.callback_query.message.reply_text("❌ File not found")
            return
        
        if file.get('status') == 'out_of_stock' or file.get('stock', 1) <= 0:
            await update.callback_query.message.reply_text(f"❌ {file['name']} is OUT OF STOCK!")
            return

        order_id = str(int(datetime.now().timestamp()))
        context.user_data['purchase'] = {
            'item_id': file_id, 'order_id': order_id, 'amount': file['price'],
            'item_name': file['name'], 'item_type': 'file',
            'file_path': file.get('file_path', ''), 'file_name': file.get('file_name', '')
        }

        gcash_num = storage.get_setting('gcash_number')
        instructions = storage.get_setting('payment_instructions')
        admin_contact = storage.get_setting('admin_contact')
        stock_status = storage.get_stock_status(file_id, 'file')

        msg = f"""
💵 GCASH PAYMENT
-------------
📁 File: {file['name']}
💰 Amount: ₱{file['price']:,.2f}
📦 {stock_status}

📌 GCash Number: {gcash_num}
🔑 Reference: FILE-{order_id}

📝 Instructions:
{instructions}

✅ After payment, click I HAVE PAID below.

👤 Contact: {admin_contact}
"""

        keyboard = [[InlineKeyboardButton("✅ I HAVE PAID", callback_data='confirm_payment'), InlineKeyboardButton("◀️ Cancel", callback_data='menu')]]

        qr_path = storage.get_setting('qr_code_path')
        if qr_path and os.path.exists(qr_path):
            with open(qr_path, 'rb') as qr:
                await update.callback_query.message.reply_photo(qr, caption=msg, reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await update.callback_query.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))

    # ============ PAYMENT CONFIRMATION ============
    async def confirm_payment(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.callback_query.message.delete()
        purchase = context.user_data.get('purchase')

        if not purchase:
            await update.callback_query.message.reply_text("❌ No pending purchase")
            return

        user_id = update.effective_user.id
        self.awaiting_payment_screenshot[user_id] = purchase

        buttons = [[InlineKeyboardButton("❌ Cancel", callback_data='cancel_payment_screenshot')]]
        await update.callback_query.message.reply_text(
            "📸 Please send your GCash payment screenshot.\n\n"
            "⚠️ Make sure the screenshot clearly shows:\n"
            "• Transaction amount\n"
            "• Reference number\n"
            "• Date & time\n\n"
            "📤 Send the image now:",
            reply_markup=InlineKeyboardMarkup(buttons)
        )

    async def handle_payment_screenshot(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        purchase = self.awaiting_payment_screenshot.get(user_id)

        if not purchase:
            return

        if not update.message.photo:
            await update.message.reply_text(
                "❌ Please send an image/photo, not a file.\n\n"
                "📤 Send your GCash screenshot as a photo:"
            )
            return

        # Check stock again
        if purchase['item_type'] == 'account':
            item = storage.get_account_item(purchase['item_id'])
            if not item or item.get('stock', 1) <= 0:
                await update.message.reply_text(
                    f"❌ Sorry, {purchase['item_name']} is now OUT OF STOCK!\n\n"
                    f"Your payment has not been processed. Please choose another item."
                )
                del self.awaiting_payment_screenshot[user_id]
                context.user_data.clear()
                return
        else:
            item = storage.get_digital_file(purchase['item_id'])
            if not item or item.get('stock', 1) <= 0:
                await update.message.reply_text(
                    f"❌ Sorry, {purchase['item_name']} is now OUT OF STOCK!\n\n"
                    f"Your payment has not been processed. Please choose another item."
                )
                del self.awaiting_payment_screenshot[user_id]
                context.user_data.clear()
                return

        payment_id = f"PAY_{purchase['order_id']}_{int(datetime.now().timestamp())}"

        buyer_name = update.effective_user.username
        if not buyer_name:
            buyer_name = update.effective_user.first_name or f"User_{user_id}"

        account_item = storage.get_account_item(purchase['item_id']) if purchase['item_type'] == 'account' else None

        order = {
            'id': purchase['order_id'],
            'buyer_id': str(user_id),
            'buyer_name': buyer_name,
            'buyer_username': update.effective_user.username,
            'buyer_first_name': update.effective_user.first_name,
            'item_name': purchase['item_name'],
            'item_type': purchase['item_type'],
            'amount': purchase['amount'],
            'status': '⏳ Payment Received - Waiting for Approval',
            'date': str(datetime.now()),
            'payment_id': payment_id
        }
        storage.add_order(order)

        pending_data = {
            'order_id': purchase['order_id'],
            'payment_id': payment_id,
            'buyer_id': str(user_id),
            'buyer_name': buyer_name,
            'buyer_username': update.effective_user.username,
            'buyer_first_name': update.effective_user.first_name,
            'item_id': purchase['item_id'],
            'item_name': purchase['item_name'],
            'item_type': purchase['item_type'],
            'amount': purchase['amount'],
            'account_type': account_item.get('account_type', 'Game Account') if account_item else 'N/A',
            'rank': account_item.get('rank', 'N/A') if account_item else 'N/A',
            'server': account_item.get('server', 'N/A') if account_item else 'N/A',
            'file_path': purchase.get('file_path', ''),
            'file_name': purchase.get('file_name', '')
        }
        storage.add_pending_payment(payment_id, pending_data)

        remaining_stock = storage.decrease_stock(purchase['item_id'], purchase['item_type'])
        
        photo_file_id = update.message.photo[-1].file_id

        buyer_display = f"@{update.effective_user.username}" if update.effective_user.username else (update.effective_user.first_name or f"User_{user_id}")
        gcash_num = storage.get_setting('gcash_number')
        ref_prefix = 'ACC-' if purchase['item_type'] == 'account' else 'FILE-'

        stock_warning = f"\n⚠️ Stock remaining: {remaining_stock} left!" if remaining_stock <= 5 else ""

        admin_caption = (
            f"🔔 NEW PAYMENT - NEEDS APPROVAL{stock_warning}\n"
            f"---------------------------\n"
            f"📦 Order: {purchase['order_id']}\n"
            f"👤 Buyer: {buyer_display}\n"
            f"📌 Item: {purchase['item_name']}\n"
            f"📁 Type: {purchase['item_type'].upper()}\n"
            f"💰 Amount: ₱{purchase['amount']:,.2f}\n\n"
            f"✅ Check GCash: {gcash_num}\n"
            f"🔑 Reference: {ref_prefix}{purchase['order_id']}\n\n"
            f"📸 Payment screenshot attached.\n"
            f"📝 Click APPROVE to deliver."
        )

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ APPROVE & DELIVER", callback_data=f'approve_delivery_{payment_id}')]
        ])

        for admin_id in storage.get_all_admins():
            try:
                await context.bot.send_photo(
                    chat_id=int(admin_id),
                    photo=photo_file_id,
                    caption=admin_caption,
                    reply_markup=keyboard
                )
            except Exception as e:
                logger.error(f"Failed to send screenshot to admin {admin_id}: {e}")

        del self.awaiting_payment_screenshot[user_id]
        context.user_data.clear()

        stock_message = f"\n\n📦 Stock remaining: {remaining_stock} copies left!" if remaining_stock > 0 else "\n\n⚠️ This item is now OUT OF STOCK!"
        
        buttons = [[InlineKeyboardButton("◀️ Back to Menu", callback_data='menu')]]
        await update.message.reply_text(
            f"✅ Payment screenshot received!\n"
            f"📦 Order ID: {purchase['order_id']}\n\n"
            f"⏳ Our admin is reviewing your payment.{stock_message}\n"
            f"You will be notified once approved. Thank you!"
        )

    async def cancel_payment_screenshot(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if user_id in self.awaiting_payment_screenshot:
            del self.awaiting_payment_screenshot[user_id]
        context.user_data.clear()
        await update.callback_query.message.delete()
        await self.menu(update, context)

    async def approve_delivery(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_admin(update.effective_user.id):
            await update.callback_query.message.reply_text("❌ Unauthorized")
            return

        payment_id = '_'.join(update.callback_query.data.split('_')[2:])
        pending = storage.get_pending_payment(payment_id)

        if not pending:
            await update.callback_query.message.reply_text("❌ Payment not found.")
            return

        await update.callback_query.message.delete()

        if pending['item_type'] == 'file':
            file_path = pending.get('file_path', '')
            file_name = pending.get('file_name', 'file')

            if file_path and os.path.exists(file_path):
                try:
                    with open(file_path, 'rb') as f:
                        await context.bot.send_document(
                            chat_id=int(pending['buyer_id']),
                            document=f,
                            caption=f"✅ PAYMENT APPROVED!\n\n📁 Your purchased file: {pending['item_name']}\n\nThank you for your purchase!"
                        )

                    file_item = storage.get_digital_file(pending['item_id'])
                    if file_item and file_item.get('stock', 1) <= 0:
                        storage.delete_digital_file(pending['item_id'])

                    storage.update_order_status(pending['order_id'], '✅ Completed - File Sent')
                    storage.remove_pending_payment(payment_id)

                    if storage.get_setting('notify_order_updates'):
                        await context.bot.send_message(
                            chat_id=int(pending['buyer_id']),
                            text=f"📦 [ ORDER UPDATE ]\n\nYour order #{pending['order_id']} for {pending['item_name']} has been approved and delivered!"
                        )
                        storage.add_user_notification(pending['buyer_id'], 'order_update', {'title': '📦 Order Approved', 'message': f"Order #{pending['order_id']} - {pending['item_name']} has been delivered."})

                    buttons = [[InlineKeyboardButton("◀️ Back to Menu", callback_data='menu')]]
                    await update.callback_query.message.reply_text(
                        f"✅ File sent to buyer!\n\n"
                        f"📦 Order: {pending['order_id']}\n"
                        f"👤 Buyer: {pending['buyer_name']}\n"
                        f"📌 Item: {pending['item_name']}",
                        reply_markup=InlineKeyboardMarkup(buttons)
                    )
                    storage.log_admin_action(update.effective_user.id, 'APPROVE_FILE_ORDER', f"Order {pending['order_id']} - {pending['item_name']}")
                except Exception as e:
                    logger.error(f"Error sending file: {e}")
                    await update.callback_query.message.reply_text(f"❌ Error sending file: {str(e)[:100]}")
                    return
            else:
                await update.callback_query.message.reply_text("❌ File not found on server.")
                return

        else:
            admin_id = update.effective_user.id

            self.account_delivery_data[admin_id] = {
                'payment_id': payment_id,
                'pending': pending,
                'details': {},
                'message_ids': []
            }
            self.delivery_step[admin_id] = 1

            account_type = pending.get('account_type', 'ACCOUNT').upper()

            msg = await update.callback_query.message.reply_text(
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📝 ENTER ACCOUNT DETAILS\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"🎮 Game: {account_type}\n"
                f"👤 Buyer: {pending['buyer_name']}\n"
                f"📦 Item: {pending['item_name']}\n"
                f"💰 Amount: ₱{pending['amount']:,.2f}\n\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"📝 Step 1/8: Send Username:"
            )
            self.account_delivery_data[admin_id]['message_ids'].append(msg.message_id)

            cancel_buttons = [[InlineKeyboardButton("❌ CANCEL", callback_data=f'delivery_cancel_{admin_id}'), InlineKeyboardButton("◀️ Back", callback_data='admin_pending')]]
            cancel_msg = await update.callback_query.message.reply_text("⬇️ Type username below or click cancel:", reply_markup=InlineKeyboardMarkup(cancel_buttons))
            self.account_delivery_data[admin_id]['message_ids'].append(cancel_msg.message_id)

    async def send_step_prompt(self, update: Update, context: ContextTypes.DEFAULT_TYPE, admin_id: int, step: int, prompt: str, skip_button: bool = False):
        data = self.account_delivery_data[admin_id]
        self.delivery_step[admin_id] = step

        response_text = f"📝 Step {step}/8: {prompt}"

        buttons = []
        if skip_button:
            buttons.append([InlineKeyboardButton("⏭️ SKIP", callback_data=f'delivery_skip_{admin_id}_{step}')])
        buttons.append([InlineKeyboardButton("❌ CANCEL", callback_data=f'delivery_cancel_{admin_id}')])
        buttons.append([InlineKeyboardButton("◀️ Back", callback_data='admin_pending')])

        msg = await update.message.reply_text(response_text, reply_markup=InlineKeyboardMarkup(buttons))
        data['message_ids'].append(msg.message_id)

    async def process_account_delivery_step(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        admin_id = update.effective_user.id

        if admin_id not in self.delivery_step:
            return

        step = self.delivery_step[admin_id]
        data = self.account_delivery_data[admin_id]
        text = update.message.text.strip() if update.message.text else None

        await self.delete_message(update, context)

        for msg_id in data.get('message_ids', []):
            try:
                await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=msg_id)
            except:
                pass
        data['message_ids'] = []

        if text and text.lower() == '/cancel':
            del self.delivery_step[admin_id]
            del self.account_delivery_data[admin_id]
            await update.message.reply_text("❌ Delivery cancelled.")
            await self.menu(update, context)
            return

        if step == 1:
            data['details']['username'] = text if text else "Not provided"
            await self.send_step_prompt(update, context, admin_id, 2, "Send Password:")
        elif step == 2:
            data['details']['password'] = text if text else "Not provided"
            await self.send_step_prompt(update, context, admin_id, 3, "Send UID/ID:", skip_button=True)
        elif step == 3:
            data['details']['uid'] = text if text and text.lower() != 'skip' else "Not provided"
            await self.send_step_prompt(update, context, admin_id, 4, "Send Server:", skip_button=True)
        elif step == 4:
            data['details']['server'] = text if text and text.lower() != 'skip' else "Not provided"
            await self.send_step_prompt(update, context, admin_id, 5, "Send Rank:", skip_button=True)
        elif step == 5:
            data['details']['rank'] = text if text and text.lower() != 'skip' else "Not provided"
            await self.send_step_prompt(update, context, admin_id, 6, "Send Email (if linked):", skip_button=True)
        elif step == 6:
            data['details']['email'] = text if text and text.lower() != 'skip' else "Not provided"
            await self.send_step_prompt(update, context, admin_id, 7, "Send 2FA Code (if any):", skip_button=True)
        elif step == 7:
            data['details']['twofa'] = text if text and text.lower() != 'skip' else "Not provided"
            await self.send_step_prompt(update, context, admin_id, 8, "Send Other Info (optional):", skip_button=True)
        elif step == 8:
            data['details']['other'] = text if text and text.lower() != 'skip' else "None"

            account_type = data['pending'].get('account_type', 'ACCOUNT').upper()
            details = data['details']

            summary = f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📋 REVIEW ACCOUNT DETAILS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🎮 Game: {account_type}
👤 Buyer: {data['pending']['buyer_name']}
📦 Item: {data['pending']['item_name']}
💰 Amount: ₱{data['pending']['amount']:,.2f}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🎮 Username: {details.get('username', 'N/A')}
🔑 Password: {details.get('password', 'N/A')}
🆔 UID/ID: {details.get('uid', 'N/A')}
🌍 Server: {details.get('server', 'N/A')}
⭐ Rank: {details.get('rank', 'N/A')}
📧 Email: {details.get('email', 'N/A')}
🔐 2FA Code: {details.get('twofa', 'N/A')}
📱 Other Info: {details.get('other', 'N/A')}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

✅ Is this correct?

Click CONFIRM to deliver to buyer.
"""

            buttons = [
                [InlineKeyboardButton("✅ CONFIRM & DELIVER", callback_data=f'delivery_confirm_{admin_id}')],
                [InlineKeyboardButton("❌ CANCEL", callback_data=f'delivery_cancel_{admin_id}')],
                [InlineKeyboardButton("◀️ Back to Pending", callback_data='admin_pending')]
            ]

            msg = await update.message.reply_text(summary, reply_markup=InlineKeyboardMarkup(buttons))
            data['message_ids'] = [msg.message_id]

    async def handle_delivery_skip(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()

        data_parts = query.data.split('_')
        admin_id = int(data_parts[2])
        step = int(data_parts[3])

        if admin_id not in self.delivery_step:
            await query.message.reply_text("❌ Session expired.")
            return

        await query.message.delete()

        class FakeUpdate:
            effective_user = update.effective_user
            effective_chat = update.effective_chat
            message = type('obj', (object,), {'text': 'skip', 'message_id': 0, 'reply_text': query.message.reply_text})()

        await self.process_account_delivery_step(FakeUpdate(), context)

    async def handle_delivery_confirm(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        admin_id = int(update.callback_query.data.split('_')[2])

        if admin_id not in self.account_delivery_data:
            await update.callback_query.message.reply_text("❌ No pending delivery.")
            return

        await update.callback_query.message.delete()

        data = self.account_delivery_data[admin_id]
        pending = data['pending']
        details = data['details']

        account_type = pending.get('account_type', 'ACCOUNT').upper()

        delivery_message = f"""
✅ PAYMENT APPROVED & DELIVERED!
----------------------------
📦 Order ID: {pending['order_id']}
📌 Item: {pending['item_name']}
💰 Amount: ₱{pending['amount']:,.2f}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【 {account_type} ACCOUNT DETAILS 】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🎮 Username: {details.get('username', 'N/A')}
🔑 Password: {details.get('password', 'N/A')}
🆔 UID/ID: {details.get('uid', 'N/A')}
🌍 Server: {details.get('server', 'N/A')}
⭐ Rank: {details.get('rank', 'N/A')}
📧 Email: {details.get('email', 'N/A')}
🔐 2FA Code: {details.get('twofa', 'N/A')}
📱 Other Info: {details.get('other', 'N/A')}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Thank you for your purchase!

👤 Contact admin: {storage.get_setting('admin_contact')}
"""

        try:
            await context.bot.send_message(
                chat_id=int(pending['buyer_id']),
                text=delivery_message
            )

            account_item = storage.get_account_item(pending['item_id'])
            if account_item and account_item.get('stock', 1) <= 0:
                storage.delete_account_item(pending['item_id'])

            storage.update_order_status(pending['order_id'], '✅ Completed - Delivered')
            storage.update_order_delivery(pending['order_id'], delivery_message)
            storage.remove_pending_payment(data['payment_id'])

            if storage.get_setting('notify_order_updates'):
                await context.bot.send_message(
                    chat_id=int(pending['buyer_id']),
                    text=f"📦 [ ORDER UPDATE ]\n\nYour order #{pending['order_id']} for {pending['item_name']} has been approved and delivered!"
                )
                storage.add_user_notification(pending['buyer_id'], 'order_update', {'title': '📦 Order Delivered', 'message': f"Order #{pending['order_id']} - {pending['item_name']} has been delivered."})

            storage.log_admin_action(admin_id, 'APPROVE_ACCOUNT_ORDER', f"Order {pending['order_id']} - {pending['item_name']}")

            buttons = [[InlineKeyboardButton("◀️ Back to Menu", callback_data='menu')]]
            await update.callback_query.message.reply_text(
                f"✅ Account details sent to buyer!\n\n"
                f"📦 Order: {pending['order_id']}\n"
                f"👤 Buyer: {pending['buyer_name']}\n"
                f"📌 Item: {pending['item_name']}",
                reply_markup=InlineKeyboardMarkup(buttons)
            )

        except Exception as e:
            logger.error(f"Error sending delivery: {e}")
            await update.callback_query.message.reply_text(f"❌ Error sending to buyer: {str(e)[:100]}")

        del self.delivery_step[admin_id]
        del self.account_delivery_data[admin_id]

    async def handle_delivery_cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()

        admin_id = int(query.data.split('_')[2])

        await query.message.delete()

        if admin_id in self.account_delivery_data:
            for msg_id in self.account_delivery_data[admin_id].get('message_ids', []):
                try:
                    await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=msg_id)
                except:
                    pass
            del self.account_delivery_data[admin_id]
        if admin_id in self.delivery_step:
            del self.delivery_step[admin_id]

        await query.message.reply_text("❌ Delivery cancelled.")
        await self.menu(update, context)

    # ============ MENU ITEMS ============
    async def account_items_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.callback_query.message.delete()

        buttons = [
            InlineKeyboardButton("🎮 Call of Duty Mobile (CODM)", callback_data='view_codm_items'),
            InlineKeyboardButton("⚔️ Mobile Legends (ML)", callback_data='view_ml_items'),
            InlineKeyboardButton("◀️ Back to Menu", callback_data='menu'),
        ]
        keyboard = make_2col_buttons(buttons)

        await update.callback_query.message.reply_text("🎮 Select Game:", reply_markup=InlineKeyboardMarkup(keyboard))

    # ============ TEXT COMMAND HANDLERS ============
    async def shop_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.view_shop(update, context)

    async def accounts_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.delete()
        buttons = [
            InlineKeyboardButton("🎮 Call of Duty Mobile (CODM)", callback_data='view_codm_items'),
            InlineKeyboardButton("⚔️ Mobile Legends (ML)", callback_data='view_ml_items'),
            InlineKeyboardButton("◀️ Back to Menu", callback_data='menu'),
        ]
        keyboard = make_2col_buttons(buttons)
        await update.message.reply_text("🎮 Select Game:", reply_markup=InlineKeyboardMarkup(keyboard))

    async def files_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        files = storage.get_all_digital_files()
        
        in_stock_files = [f for f in files if f.get('status', 'available') != 'out_of_stock' and f.get('stock', 1) > 0]
        out_of_stock_files = [f for f in files if f.get('status', 'available') == 'out_of_stock' or f.get('stock', 1) <= 0]

        if not in_stock_files and not out_of_stock_files:
            buttons = [[InlineKeyboardButton("◀️ Back to Menu", callback_data='menu')]]
            await update.message.reply_text("📭 No digital files available.", reply_markup=InlineKeyboardMarkup(buttons))
            return

        for file in in_stock_files:
            stock_status = storage.get_stock_status(file['id'], 'file')
            stock_warning = " ⚠️ ONLY A FEW LEFT!" if file.get('stock', 1) <= 5 else ""
            
            text = f"""
📁 DIGITAL FILE{stock_warning}
------------
📌 Name: {file['name']}
💰 Price: ₱{file['price']:,.2f}
📦 {stock_status}
📄 Format: {file.get('format', 'N/A')}
📦 Size: {file.get('size', 'N/A')}

📝 Description:
{file['description']}

🆔 ID: {file['id']}
"""
            keyboard = [[InlineKeyboardButton("🛒 Buy Now", callback_data=f'buy_file_{file["id"]}')]]
            await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

        for file in out_of_stock_files:
            text = f"""
📁 DIGITAL FILE
------------
📌 Name: {file['name']}
💰 Price: ₱{file['price']:,.2f}
📦 OUT OF STOCK
📄 Format: {file.get('format', 'N/A')}
📦 Size: {file.get('size', 'N/A')}

❌ This file is currently unavailable.
"""
            keyboard = [[InlineKeyboardButton("🔔 Notify when in stock", callback_data=f'notify_stock_{file["id"]}')]]
            await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

        buttons = [[InlineKeyboardButton("◀️ Back to Menu", callback_data='menu')]]
        await update.message.reply_text("⬅️ Back", reply_markup=InlineKeyboardMarkup(buttons))

    async def notifications_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = str(update.effective_user.id)
        notifications = storage.get_user_notifications(user_id)

        if not notifications:
            buttons = [[InlineKeyboardButton("◀️ Back to Menu", callback_data='menu')]]
            await update.message.reply_text("📭 No notifications.", reply_markup=InlineKeyboardMarkup(buttons))
            return

        text = "🔔 YOUR NOTIFICATIONS\n------------------\n"
        for i, notif in enumerate(notifications[-10:]):
            read_mark = "✅" if notif.get('read', False) else "🟢"
            text += f"\n{read_mark} [{notif['type'].upper()}]\n{notif['data'].get('title', 'Update')}\n{notif['data'].get('message', '')[:100]}\n"

        buttons = [
            InlineKeyboardButton("✓ Mark as Read", callback_data='mark_notifications_read'),
            InlineKeyboardButton("◀️ Back to Menu", callback_data='menu')
        ]
        keyboard = [buttons]

        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    async def orders_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        orders = storage.get_user_orders(str(update.effective_user.id))

        if not orders:
            buttons = [[InlineKeyboardButton("◀️ Back to Menu", callback_data='menu')]]
            await update.message.reply_text("📭 No orders yet", reply_markup=InlineKeyboardMarkup(buttons))
            return

        text = "📦 YOUR ORDERS\n-----------\n"
        for order in orders[-10:]:
            text += f"\n🆔 Order: {order['id'][:8]}\n📌 Item: {order['item_name']}\n📁 Type: {order['item_type'].upper()}\n💰 Amount: ₱{order['amount']:,.2f}\n📊 Status: {order['status']}\n📅 Date: {order['date'][:10]}\n-----------\n"

        buttons = [[InlineKeyboardButton("◀️ Back to Menu", callback_data='menu')]]
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons))

    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_admin(update.effective_user.id):
            await update.message.reply_text("❌ Unauthorized. Admin only command.")
            return

        total_users = len(storage.users)
        total_orders = len(storage.orders)
        total_accounts = len(storage.get_all_account_items())
        total_files = len(storage.get_all_digital_files())
        
        total_account_stock = sum(item.get('stock', 1) for item in storage.get_all_account_items())
        total_file_stock = sum(item.get('stock', 1) for item in storage.get_all_digital_files())
        
        pending_orders = len([o for o in storage.orders.values() if o.get('status') == '⏳ Payment Received - Waiting for Approval'])
        completed_orders = len([o for o in storage.orders.values() if o.get('status', '').startswith('✅')])

        stats_text = f"""
📊 BOT STATISTICS
━━━━━━━━━━━━━━━━━━━━

👥 Users:
• Total Users: {total_users}

🛍️ Products:
• Account Items: {total_accounts} (Total Stock: {total_account_stock})
• Digital Files: {total_files} (Total Stock: {total_file_stock})
• Total Products: {total_accounts + total_files}

📦 Orders:
• Total Orders: {total_orders}
• Pending Approval: {pending_orders}
• Completed: {completed_orders}

👑 Admins:
• Total Admins: {len(storage.get_all_admins())}
"""
        await update.message.reply_text(stats_text)

    async def settings_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_admin(update.effective_user.id):
            await update.message.reply_text("❌ Unauthorized. Admin only command.")
            return

        await self.admin_settings(update, context)

    async def pending_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_admin(update.effective_user.id):
            await update.message.reply_text("❌ Unauthorized. Admin only command.")
            return

        if not storage.pending_payments:
            buttons = [[InlineKeyboardButton("◀️ Back to Menu", callback_data='menu')]]
            await update.message.reply_text("📭 No pending payments", reply_markup=InlineKeyboardMarkup(buttons))
            return

        for payment_id, data in storage.pending_payments.items():
            buyer_display = data.get('buyer_name', f"User_{data['buyer_id']}")
            text = f"🆔 Order: {data['order_id']}\n👤 Buyer: {buyer_display}\n📌 Item: {data['item_name']}\n📁 Type: {data['item_type'].upper()}\n💰 Amount: ₱{data['amount']:,.2f}"
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Approve & Deliver", callback_data=f'approve_delivery_{payment_id}')],
                [InlineKeyboardButton("◀️ Back to Menu", callback_data='menu')]
            ])
            await update.message.reply_text(text, reply_markup=keyboard)

    async def addaccount_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_admin(update.effective_user.id):
            await update.message.reply_text("❌ Unauthorized. Admin only command.")
            return

        await update.message.delete()
        user_id = update.effective_user.id
        self.admin_selling[user_id] = {'step': 'name', 'type': 'account'}
        self.messages_to_delete = []

        buttons = [[InlineKeyboardButton("◀️ Cancel", callback_data='menu')]]
        sent_msg = await update.message.reply_text(
            "➕ Add Account Item\n\n📝 Step 1/8: Send item name:\n\nType /cancel to cancel.",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        self.messages_to_delete.append(sent_msg.message_id)

    async def addfile_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_admin(update.effective_user.id):
            await update.message.reply_text("❌ Unauthorized. Admin only command.")
            return

        await update.message.delete()
        user_id = update.effective_user.id
        self.admin_selling[user_id] = {'step': 'name', 'type': 'file'}
        self.messages_to_delete = []

        buttons = [[InlineKeyboardButton("◀️ Cancel", callback_data='menu')]]
        sent_msg = await update.message.reply_text(
            "📁 Add Files\n\n📝 Step 1/5: Send file name:\n\nType /cancel to cancel.",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        self.messages_to_delete.append(sent_msg.message_id)

    async def announce_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_admin(update.effective_user.id):
            await update.message.reply_text("❌ Unauthorized. Admin only command.")
            return

        await update.message.delete()
        context.user_data['announcement_mode'] = True

        buttons = [[InlineKeyboardButton("◀️ Cancel", callback_data='menu')]]
        await update.message.reply_text(
            "📢 Send the announcement message to broadcast to all users:\n\nType /cancel to cancel.",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        storage.log_admin_action(update.effective_user.id, 'START_ANNOUNCEMENT', "Started announcement broadcast")

    async def promo_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_admin(update.effective_user.id):
            await update.message.reply_text("❌ Unauthorized. Admin only command.")
            return

        await update.message.delete()
        context.user_data['promo_mode'] = True

        buttons = [[InlineKeyboardButton("◀️ Cancel", callback_data='menu')]]
        await update.message.reply_text(
            "🎯 Send the promo message to broadcast to all users:\n\nType /cancel to cancel.",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        storage.log_admin_action(update.effective_user.id, 'START_PROMO', "Started promo broadcast")

    async def addadmin_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_master_admin(update.effective_user.id):
            await update.message.reply_text("❌ Only Admin can add admins!")
            return

        await update.message.delete()
        context.user_data['awaiting_admin_id'] = True

        buttons = [[InlineKeyboardButton("◀️ Cancel", callback_data='admin_management')]]
        await update.message.reply_text(
            "➕ ADD ADMIN\n\n"
            "Send the Telegram User ID of the new admin.\n\n"
            "How to get User ID:\n"
            "1. Ask the user to message @userinfobot\n"
            "2. They will get their ID\n\n"
            "Or send their username (e.g., @username)\n\n"
            "Type /cancel to cancel.",
            reply_markup=InlineKeyboardMarkup(buttons)
        )

    async def removeadmin_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_master_admin(update.effective_user.id):
            await update.message.reply_text("❌ Only Admin can remove admins!")
            return

        await update.message.delete()

        admins = storage.get_all_admins()
        admin_list = "❌ REMOVE ADMIN\n\nCurrent admins:\n"
        for admin in admins:
            if admin != str(ADMIN_ID):
                admin_list += f"\n• {admin}"

        if len(admins) <= 1:
            admin_list += "\n\n⚠️ No other admins to remove."

        admin_list += "\n\nSend the User ID of the admin to remove.\n\nType /cancel to cancel."

        context.user_data['awaiting_remove_admin'] = True

        buttons = [[InlineKeyboardButton("◀️ Cancel", callback_data='admin_management')]]
        await update.message.reply_text(admin_list, reply_markup=InlineKeyboardMarkup(buttons))

    async def adminlogs_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_master_admin(update.effective_user.id):
            await update.message.reply_text("❌ Only Admin can view logs!")
            return

        logs = storage.get_admin_logs(30)
        if not logs:
            buttons = [[InlineKeyboardButton("◀️ Back", callback_data='admin_management')]]
            await update.message.reply_text("📜 No admin logs yet.", reply_markup=InlineKeyboardMarkup(buttons))
            return

        log_text = "📜 ADMIN ACTION LOGS (last 30)\n━━━━━━━━━━━━━━━━━━━━\n\n"
        for log in reversed(logs):
            log_text += f"🕐 {log['timestamp'][:16]}\n"
            log_text += f"👤 Admin: {log['admin_id'][:10]}...\n"
            log_text += f"📌 {log['action']}: {log['details']}\n"
            log_text += "━━━━━━━━━━━━━━━━━━━━\n"

        buttons = [[InlineKeyboardButton("◀️ Back", callback_data='admin_management')]]

        if len(log_text) > 4000:
            log_text = log_text[:4000] + "\n...(truncated)"

        await update.message.reply_text(log_text, reply_markup=InlineKeyboardMarkup(buttons))

    async def stock_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_admin(update.effective_user.id):
            await update.message.reply_text("❌ Unauthorized. Admin only command.")
            return

        accounts = storage.get_all_account_items()
        files = storage.get_all_digital_files()
        
        if not accounts and not files:
            buttons = [[InlineKeyboardButton("◀️ Back to Menu", callback_data='menu')]]
            await update.message.reply_text("📭 No items", reply_markup=InlineKeyboardMarkup(buttons))
            return
        
        text = "📦 STOCK MANAGER\n━━━━━━━━━━━━━━━━━━━━\n\nSelect an item to update stock:\n\n"
        
        buttons = []
        
        for item in accounts:
            stock = item.get('stock', 1)
            status_emoji = "🟢" if stock > 5 else "🟡" if stock > 0 else "🔴"
            buttons.append(InlineKeyboardButton(f"{status_emoji} Account: {item['name'][:20]} ({stock})", callback_data=f'stock_account_{item["id"]}'))
        
        for item in files:
            stock = item.get('stock', 1)
            status_emoji = "🟢" if stock > 5 else "🟡" if stock > 0 else "🔴"
            buttons.append(InlineKeyboardButton(f"{status_emoji} File: {item['name'][:20]} ({stock})", callback_data=f'stock_file_{item["id"]}'))
        
        buttons.append(InlineKeyboardButton("◀️ Back to Menu", callback_data='menu'))
        keyboard = make_2col_buttons(buttons)
        
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    # ============ PROCESS FUNCTIONS ============
    async def process_add_admin(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.user_data.get('awaiting_admin_id'):
            return

        await self.delete_message(update, context)
        user_input = update.message.text.strip()

        if user_input.lower() == '/cancel':
            context.user_data.pop('awaiting_admin_id', None)
            await update.message.reply_text("❌ Cancelled.")
            await self.menu(update, context)
            return

        new_admin_id = None
        new_admin_username = None

        if user_input.startswith('@'):
            username = user_input[1:]
            for uid, udata in storage.users.items():
                if udata.get('username') == username:
                    new_admin_id = uid
                    new_admin_username = username
                    break
            if not new_admin_id:
                await update.message.reply_text(f"❌ User {user_input} not found in database. They need to /start the bot first.")
                return
        else:
            try:
                new_admin_id = str(int(user_input))
            except:
                await update.message.reply_text("❌ Invalid ID. Send a numeric User ID or username starting with @")
                return

        if new_admin_id == str(ADMIN_ID):
            await update.message.reply_text("❌ Admin is already an admin!")
            context.user_data.pop('awaiting_admin_id', None)
            return

        if storage.add_admin(new_admin_id, update.effective_user.id, new_admin_username):
            await update.message.reply_text(f"✅ Admin {new_admin_id} added successfully!")

            try:
                await context.bot.send_message(
                    chat_id=int(new_admin_id),
                    text="🎉 Congratulations!\n\nYou have been promoted to Admin of the Shop Bot!\n\nUse /menu to access admin features."
                )
            except:
                pass
        else:
            await update.message.reply_text(f"❌ User {new_admin_id} is already an admin.")

        context.user_data.pop('awaiting_admin_id', None)
        await self.admin_management(update, context)

    async def process_remove_admin(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.user_data.get('awaiting_remove_admin'):
            return

        await self.delete_message(update, context)
        user_input = update.message.text.strip()

        if user_input.lower() == '/cancel':
            context.user_data.pop('awaiting_remove_admin', None)
            await update.message.reply_text("❌ Cancelled.")
            await self.menu(update, context)
            return

        try:
            admin_id = str(int(user_input))
        except:
            await update.message.reply_text("❌ Invalid ID. Send a numeric User ID.")
            return

        if admin_id == str(ADMIN_ID):
            await update.message.reply_text("❌ Cannot remove Admin!")
            context.user_data.pop('awaiting_remove_admin', None)
            return

        if storage.remove_admin(admin_id, update.effective_user.id):
            await update.message.reply_text(f"✅ Admin {admin_id} removed successfully!")

            try:
                await context.bot.send_message(
                    chat_id=int(admin_id),
                    text="⚠️ You have been removed as Admin of the Shop Bot. You now have regular user access."
                )
            except:
                pass
        else:
            await update.message.reply_text(f"❌ Admin {admin_id} not found or cannot be removed.")

        context.user_data.pop('awaiting_remove_admin', None)
        await self.admin_management(update, context)

    # ============ CALLBACK HANDLER ============
    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            query = update.callback_query
            await query.answer()
            action = query.data

            if action == 'menu':
                await self.menu(update, context)
            elif action == 'admin_management':
                await self.admin_management(update, context)
            elif action == 'admin_add_admin':
                await self.admin_add_admin_prompt(update, context)
            elif action == 'admin_remove_admin':
                await self.admin_remove_admin_prompt(update, context)
            elif action == 'admin_view_logs':
                await self.admin_view_logs(update, context)
            elif action == 'view_notifications':
                await self.view_notifications(update, context)
            elif action == 'mark_notifications_read':
                await self.mark_notifications_read(update, context)
            elif action == 'admin_settings':
                await self.admin_settings(update, context)
            elif action == 'toggle_notify_products':
                await self.toggle_notify_products(update, context)
            elif action == 'toggle_notify_orders':
                await self.toggle_notify_orders(update, context)
            elif action == 'set_gcash':
                await self.set_gcash_number(update, context)
            elif action == 'set_qr':
                await self.set_qr_code(update, context)
            elif action == 'set_instructions':
                await self.set_payment_instructions(update, context)
            elif action == 'set_admin_contact':
                await self.set_admin_contact(update, context)
            elif action == 'set_delivery':
                await self.set_delivery_info(update, context)
            elif action == 'view_qr':
                await self.view_qr(update, context)
            elif action == 'clear_announcements':
                await self.clear_announcements(update, context)
            elif action == 'admin_edit_items':
                await self.admin_edit_items(update, context)
            elif action.startswith('edit_account_'):
                await self.edit_account_item(update, context)
            elif action.startswith('edit_file_'):
                await self.edit_file_item(update, context)
            elif action.startswith('edit_field_'):
                await self.handle_edit_field(update, context)
            elif action == 'account_items_menu':
                await self.account_items_menu(update, context)
            elif action == 'view_codm_items':
                await self.view_codm_items(update, context)
            elif action == 'view_ml_items':
                await self.view_ml_items(update, context)
            elif action == 'view_digital_files':
                await self.view_digital_files(update, context)
            elif action == 'my_orders':
                await self.my_orders(update, context)
            elif action == 'admin_add_account':
                await self.admin_add_account(update, context)
            elif action == 'admin_add_file':
                await self.admin_add_file(update, context)
            elif action == 'admin_pending':
                await self.admin_pending(update, context)
            elif action == 'admin_pending_delivery':
                await self.admin_pending_delivery(update, context)
            elif action == 'admin_orders':
                await self.admin_orders(update, context)
            elif action == 'admin_remove':
                await self.admin_remove(update, context)
            elif action == 'view_shop':
                await self.view_shop(update, context)
            elif action == 'admin_confirm_yes':
                await self.admin_confirm_yes(update, context)
            elif action == 'admin_confirm_no':
                await self.admin_confirm_no(update, context)
            elif action.startswith('remove_account_'):
                await self.remove_account(update, context)
            elif action.startswith('remove_file_'):
                await self.remove_file(update, context)
            elif action.startswith('buy_account_'):
                await self.buy_account_item(update, context)
            elif action.startswith('buy_file_'):
                await self.buy_digital_file(update, context)
            elif action == 'confirm_payment':
                await self.confirm_payment(update, context)
            elif action == 'cancel_payment_screenshot':
                await self.cancel_payment_screenshot(update, context)
            elif action.startswith('approve_delivery_'):
                await self.approve_delivery(update, context)
            elif action.startswith('delivery_confirm_'):
                await self.handle_delivery_confirm(update, context)
            elif action.startswith('delivery_cancel_'):
                await self.handle_delivery_cancel(update, context)
            elif action.startswith('delivery_skip_'):
                await self.handle_delivery_skip(update, context)
            elif action == 'admin_announcement':
                await self.admin_announcement(update, context)
            elif action == 'admin_promo':
                await self.admin_promo(update, context)
            elif action == 'admin_stock_manager':
                await self.admin_stock_manager(update, context)
            elif action.startswith('stock_account_') or action.startswith('stock_file_'):
                await self.stock_item_prompt(update, context)
            elif action.startswith('notify_stock_'):
                await self.notify_stock_request(update, context)
        except Exception as e:
            logger.error(f"Callback error: {e}")

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id

        if user_id in self.delivery_step:
            await self.process_account_delivery_step(update, context)
            return

        if context.user_data.get('awaiting_admin_id'):
            await self.process_add_admin(update, context)
        elif context.user_data.get('awaiting_remove_admin'):
            await self.process_remove_admin(update, context)
        elif context.user_data.get('announcement_mode'):
            await self.process_announcement(update, context)
        elif context.user_data.get('promo_mode'):
            await self.process_promo(update, context)
        elif context.user_data.get('setting'):
            await self.handle_setting_input(update, context)
        elif context.user_data.get('edit_field'):
            await self.process_edit_value(update, context)
        elif user_id in self.admin_selling:
            await self.handle_admin_input(update, context)
        elif context.user_data.get('stock_item'):
            await self.process_stock_update(update, context)

    async def handle_media(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id

        if user_id in self.awaiting_payment_screenshot:
            await self.handle_payment_screenshot(update, context)
            return

        if context.user_data.get('setting') == 'qr_code':
            await self.handle_setting_qr(update, context)
        elif context.user_data.get('edit_field') == 'photo':
            await self.handle_edit_photo(update, context)
        elif context.user_data.get('edit_field') == 'file':
            await self.handle_edit_file_upload(update, context)
        elif user_id in self.admin_selling:
            if self.admin_selling[user_id].get('step') == 'photo':
                await self.handle_admin_photo(update, context)
            elif self.admin_selling[user_id].get('step') == 'file':
                await self.handle_admin_file(update, context)


# ============ SET BOT COMMANDS ============
# ============ SET BOT COMMANDS ============
if USE_V20:
    async def set_bot_commands(application: Application):
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
            BotCommand("addadmin", "Add new admin (master only)"),
            BotCommand("removeadmin", "Remove admin (master only)"),
            BotCommand("adminlogs", "View admin logs (master only)"),
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
                logger.info(f"✅ Admin commands set for {admin_id}")
            except Exception as e:
                logger.error(f"Failed to set admin commands for {admin_id}: {e}")

        logger.info("✅ Bot menu commands set with scoped permissions!")
else:
    async def set_bot_commands_compat(updater):
        """Compatibility function for setting bot commands in older versions"""
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
            BotCommand("addadmin", "Add new admin (master only)"),
            BotCommand("removeadmin", "Remove admin (master only)"),
            BotCommand("adminlogs", "View admin logs (master only)"),
            BotCommand("addaccount", "Add account item"),
            BotCommand("addfile", "Add digital file"),
            BotCommand("pending", "View pending payments"),
            BotCommand("announce", "Send announcement"),
            BotCommand("promo", "Send promo"),
            BotCommand("stats", "View bot stats"),
            BotCommand("settings", "Bot settings"),
            BotCommand("stock", "Manage product stock"),
        ]
        
        await updater.bot.set_my_commands(default_commands, scope=BotCommandScopeDefault())
        
        for admin_id in storage.get_all_admins():
            try:
                await updater.bot.set_my_commands(
                    default_commands + admin_commands,
                    scope=BotCommandScopeChat(chat_id=int(admin_id))
                )
                logger.info(f"✅ Admin commands set for {admin_id}")
            except Exception as e:
                logger.error(f"Failed to set admin commands for {admin_id}: {e}")
        
        logger.info("✅ Bot menu commands set with scoped permissions!")

# ============ MAIN ============
def main():
    handlers = BotHandlers()

    if USE_V20:
        # New version (v20+)
        app = Application.builder().token(BOT_TOKEN).connect_timeout(60.0).read_timeout(60.0).build()
        
        # Basic command handlers
        app.add_handler(CommandHandler("start", handlers.start))
        app.add_handler(CommandHandler("menu", handlers.menu))
        app.add_handler(CommandHandler("help", handlers.help_command))
        app.add_handler(CommandHandler("clean", handlers.admin_clean_skip))
        app.add_handler(CommandHandler("shop", handlers.shop_command))
        app.add_handler(CommandHandler("buy", handlers.buy_command))
        app.add_handler(CommandHandler("accounts", handlers.accounts_command))
        app.add_handler(CommandHandler("files", handlers.files_command))
        app.add_handler(CommandHandler("orders", handlers.orders_command))
        app.add_handler(CommandHandler("notifications", handlers.notifications_command))
        
        # Admin commands
        app.add_handler(CommandHandler("stats", handlers.stats_command))
        app.add_handler(CommandHandler("settings", handlers.settings_command))
        app.add_handler(CommandHandler("pending", handlers.pending_command))
        app.add_handler(CommandHandler("addaccount", handlers.addaccount_command))
        app.add_handler(CommandHandler("addfile", handlers.addfile_command))
        app.add_handler(CommandHandler("announce", handlers.announce_command))
        app.add_handler(CommandHandler("promo", handlers.promo_command))
        app.add_handler(CommandHandler("stock", handlers.stock_command))
        app.add_handler(CommandHandler("addadmin", handlers.addadmin_command))
        app.add_handler(CommandHandler("removeadmin", handlers.removeadmin_command))
        app.add_handler(CommandHandler("adminlogs", handlers.adminlogs_command))
        
        # Callback and message handlers
        app.add_handler(CallbackQueryHandler(handlers.handle_callback))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.handle_message))
        app.add_handler(MessageHandler(filters.PHOTO, handlers.handle_media))
        app.add_handler(MessageHandler(filters.Document.ALL, handlers.handle_media))
        
        async def post_init(application: Application):
            await set_bot_commands(application)
        
        app.post_init = post_init
        
        print("🤖 Bot Running")
        print(f"👑 Admin ID: {ADMIN_ID}")
        print(f"👥 Admins: {storage.get_all_admins()}")
        print("✅ /shop command shows all items with stock status")
        print("✅ /buy <ID> command for quick purchase")
        print("✅ Stock tracking with 'Only X left' warning")
        print("✅ /stock command to manage product quantities")
        print("✅ Payment screenshot required before admin approval")
        print("✅ Screenshot forwarded to all admins with Approve button")
        
        app.run_polling(allowed_updates=Update.ALL_TYPES)
    
    else:
        # Old version (v13-v19)
        from telegram.ext import Updater, Filters
        from telegram.ext import CallbackContext
        
        updater = Updater(BOT_TOKEN)
        dispatcher = updater.dispatcher
        
        # Basic command handlers
        dispatcher.add_handler(CommandHandler("start", handlers.start))
        dispatcher.add_handler(CommandHandler("menu", handlers.menu))
        dispatcher.add_handler(CommandHandler("help", handlers.help_command))
        dispatcher.add_handler(CommandHandler("clean", handlers.admin_clean_skip))
        dispatcher.add_handler(CommandHandler("shop", handlers.shop_command))
        dispatcher.add_handler(CommandHandler("buy", handlers.buy_command))
        dispatcher.add_handler(CommandHandler("accounts", handlers.accounts_command))
        dispatcher.add_handler(CommandHandler("files", handlers.files_command))
        dispatcher.add_handler(CommandHandler("orders", handlers.orders_command))
        dispatcher.add_handler(CommandHandler("notifications", handlers.notifications_command))
        
        # Admin commands
        dispatcher.add_handler(CommandHandler("stats", handlers.stats_command))
        dispatcher.add_handler(CommandHandler("settings", handlers.settings_command))
        dispatcher.add_handler(CommandHandler("pending", handlers.pending_command))
        dispatcher.add_handler(CommandHandler("addaccount", handlers.addaccount_command))
        dispatcher.add_handler(CommandHandler("addfile", handlers.addfile_command))
        dispatcher.add_handler(CommandHandler("announce", handlers.announce_command))
        dispatcher.add_handler(CommandHandler("promo", handlers.promo_command))
        dispatcher.add_handler(CommandHandler("stock", handlers.stock_command))
        dispatcher.add_handler(CommandHandler("addadmin", handlers.addadmin_command))
        dispatcher.add_handler(CommandHandler("removeadmin", handlers.removeadmin_command))
        dispatcher.add_handler(CommandHandler("adminlogs", handlers.adminlogs_command))
        
        # Callback and message handlers
        dispatcher.add_handler(CallbackQueryHandler(handlers.handle_callback))
        dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handlers.handle_message))
        dispatcher.add_handler(MessageHandler(Filters.photo, handlers.handle_media))
        dispatcher.add_handler(MessageHandler(Filters.document, handlers.handle_media))
        
        # Set commands
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(set_bot_commands_compat(updater))
        
        print("🤖 Bot Running")
        print(f"👑 Admin ID: {ADMIN_ID}")
        print(f"👥 Admins: {storage.get_all_admins()}")
        print("✅ Bot is running in compatibility mode (older version)")
        
        updater.start_polling()
        updater.idle()


if __name__ == '__main__':
    main()
