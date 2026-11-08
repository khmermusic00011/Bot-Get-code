import telebot
import imaplib
import email
import re
import requests
import os
import json
import base64
import hashlib
import random
import string
from datetime import datetime, timedelta
from flask import Flask
from threading import Thread
from cryptography.fernet import Fernet

# ==============================================================================
# CONFIGURATION & ENVIRONMENT VARIABLES (RENDER)
# ==============================================================================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
BIN_URL = os.environ.get("BIN_URL", "")
API_KEY = os.environ.get("API_KEY", "")
HOTMAIL_API_URL = os.environ.get("HOTMAIL_API_URL", "https://mailgen.shop/api/inbox-read")

# GitHub Gist & POS Admin Settings
GITHUB_PAT = os.environ.get("GITHUB_PAT", "")  # GitHub Personal Access Token with 'gist' scope
GIST_ID = os.environ.get("GIST_ID", "adc1248a9481d7cdeb2db6c89598c138")
GIST_FILENAME = os.environ.get("GIST_FILENAME", "gistfile1.txt")
SECRET_SALT = os.environ.get("SECRET_SALT", "lshPOS@2026_SecureKey")

# Telegram Admin ID (Your personal Telegram User ID, check with /myid)
# If left empty, the first person to send /setadmin will become admin!
ADMIN_ID = os.environ.get("ADMIN_ID", "")

bot = telebot.TeleBot(BOT_TOKEN)

# ==============================================================================
# EMAIL EXTRACTOR CONFIG & SERVERS
# ==============================================================================
GUERRILLA_DOMAINS = [
    "guerrillamail.com", "guerrillamail.info", "guerrillamail.biz", 
    "guerrillamail.de", "guerrillamail.net", "guerrillamail.org", 
    "sharklasers.com", "grr.la", "pokemail.net", "spam4.me", "guerrillamailblock.com"
]

IMAP_SERVERS = {
    "yandex": "imap.yandex.com",
    "zoho": "imap.zoho.com",
    "mailfence": "imap.mailfence.com",
    "outlook": "outlook.office365.com",
    "hotmail": "outlook.office365.com"
}

# ==============================================================================
# FLASK WEB SERVER (KEEP-ALIVE FOR RENDER 24/7)
# ==============================================================================
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is awake and fully updated on Render (Email Extractor + LSH-POS Admin)!"

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_web_server)
    t.daemon = True
    t.start()

# ==============================================================================
# CRYPTOGRAPHIC HELPERS (SHA-256 HASH & AES-256 ENCRYPTION)
# ==============================================================================
def hash_license_key(key: str) -> str:
    """Computes SHA-256 salted hash of License Key."""
    data = f"{key.strip().upper()}:{SECRET_SALT}"
    return hashlib.sha256(data.encode()).hexdigest().lower()

def get_token_cipher():
    """Generates AES-256 Fernet cipher matching POS client."""
    cipher_key = base64.urlsafe_b64encode(hashlib.sha256(SECRET_SALT.encode() + b'_lsh_gist_token_2026').digest())
    return Fernet(cipher_key)

def encrypt_bot_token(plain_token: str) -> str:
    """Encrypts Reporter Bot Token with AES-256 for safe storage on Gist."""
    f = get_token_cipher()
    return f.encrypt(plain_token.strip().encode()).decode()

def generate_random_license_key() -> str:
    """Generates clean format: LSH-2026-XXXX-XXXX"""
    p1 = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
    p2 = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
    year = datetime.now().year
    return f"LSH-{year}-{p1}-{p2}"

def is_admin(user_id) -> bool:
    """Checks if message sender is authorized admin."""
    global ADMIN_ID
    if not ADMIN_ID:
        return True  # If not configured yet, allow access to run /setadmin
    return str(user_id) == str(ADMIN_ID)

# ==============================================================================
# GITHUB GIST API HELPERS
# ==============================================================================
def fetch_gist_data():
    """Fetches the latest JSON content from GitHub Gist via API."""
    url = f"https://api.github.com/gists/{GIST_ID}"
    headers = {"Accept": "application/vnd.github+json"}
    if GITHUB_PAT:
        headers["Authorization"] = f"Bearer {GITHUB_PAT}"
    
    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            files = r.json().get("files", {})
            for fname, finfo in files.items():
                if fname == GIST_FILENAME or "gistfile" in fname or fname.endswith(".txt"):
                    return json.loads(finfo.get("content", "{}")), fname
        return {}, GIST_FILENAME
    except Exception as e:
        print(f"Error fetching Gist: {e}")
        return {}, GIST_FILENAME

def save_gist_data(data_dict, target_filename=None):
    """Pushes updated JSON to GitHub Gist using Personal Access Token."""
    if not GITHUB_PAT:
        return False, "សូមកំណត់ GITHUB_PAT (Personal Access Token) ក្នុង Environment Variables របស់ Render ជាមុនសិន!"

    url = f"https://api.github.com/gists/{GIST_ID}"
    headers = {
        "Authorization": f"Bearer {GITHUB_PAT}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }
    filename = target_filename or GIST_FILENAME
    payload = {
        "files": {
            filename: {
                "content": json.dumps(data_dict, indent=2, ensure_ascii=False)
            }
        }
    }
    try:
        r = requests.patch(url, headers=headers, json=payload, timeout=12)
        if r.status_code == 200:
            return True, "ជោគជ័យ"
        return False, f"GitHub API Error: HTTP {r.status_code} ({r.text[:120]})"
    except Exception as e:
        return False, f"Exception: {e}"

# ==============================================================================
# EMAIL PARSING & IMAP UTILITIES (FROM YOUR ORIGINAL BOT)
# ==============================================================================
def load_email_accounts():
    try:
        headers = {"X-Master-Key": API_KEY}
        response = requests.get(BIN_URL, headers=headers, timeout=5)
        if response.status_code == 200:
            return response.json()["record"].get("emails", [])
    except Exception as e:
        print(f"Error fetching data: {e}")
    return []

def extract_code(email_body):
    if not email_body:
        return None
    pattern = r'(?i)(?:code|confirm|is|លេខ|verification|pin|otp).*?(\d{4,8})'
    match = re.search(pattern, email_body)
    if match:
        return match.group(1)
    match_simple = re.search(r'\b(\d{4,8})\b', email_body)
    if match_simple:
        return match_simple.group(1)
    return None

def fetch_guerrilla_mail(email_address):
    username = email_address.split("@")[0]
    base_url = "https://api.guerrillamail.com/ajax.php"
    session = requests.Session()
    try:
        r = session.get(f"{base_url}?f=set_email_user&email_user={username}&lang=en", timeout=10)
        sid_token = r.json().get("sid_token")
        r = session.get(f"{base_url}?f=get_email_list&offset=0&sid_token={sid_token}", timeout=10)
        emails = r.json().get("list", [])
        for mail in emails:
            if mail.get("mail_from") == "no-reply@guerrillamail.com":
                continue
            mail_id = mail.get("mail_id")
            r = session.get(f"{base_url}?f=fetch_email&email_id={mail_id}&sid_token={sid_token}", timeout=10)
            body = r.json().get("mail_body", "")
            code = extract_code(body)
            if code:
                return (code, "Guerrilla Mail Code Found")
        return None
    except Exception as e:
        print(f"Guerrilla Error: {e}")
        return None

def detect_email_provider(email_address):
    domain = email_address.lower().split("@")[1]
    if "yandex" in domain: return "yandex"
    elif "zoho" in domain: return "zoho"
    elif "mailfence" in domain: return "mailfence"
    elif "outlook" in domain: return "outlook"
    elif "hotmail" in domain: return "hotmail"
    return "yandex"

def fetch_latest_email(email_acc, alias_email):
    try:
        email_parts = email_acc.split("|")
        if len(email_parts) < 2: return None
        main_email = email_parts[0]
        provider = detect_email_provider(main_email)
        imap_server = IMAP_SERVERS.get(provider)
        if not imap_server: return None

        if provider in ["outlook", "hotmail"] and len(email_parts) == 4:
            password = email_parts[3]
        else:
            password = email_parts[1]

        mail = imaplib.IMAP4_SSL(imap_server)
        mail.login(main_email, password)

        if provider in ["outlook", "hotmail"]:
            folders = ["INBOX", "Junk"]
        elif provider == "yandex":
            folders = ["INBOX", "Social", "Spam"]
        elif provider == "zoho":
            folders = ["INBOX", "Spam"]
        else:
            folders = ["INBOX"]

        for folder in folders:
            result, _ = mail.select(folder)
            if result == "OK": break
        else:
            mail.logout()
            return None

        search_query = f'(OR (FROM "security@facebookmail.com") (FROM "registration@facebookmail.com") TO "{alias_email}")'
        result, data = mail.search(None, search_query)
        if result != "OK" or not data[0]:
            mail.logout()
            return None

        email_ids = data[0].split()
        latest_email_id = email_ids[-1]
        result, msg_data = mail.fetch(latest_email_id, "(RFC822)")
        mail.logout()

        for response_part in msg_data:
            if isinstance(response_part, tuple):
                msg = email.message_from_bytes(response_part[1])
                body = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == "text/plain":
                            body = part.get_payload(decode=True).decode(errors='ignore')
                else:
                    body = msg.get_payload(decode=True).decode(errors='ignore')
                return (extract_code(body), body)
    except Exception as e:
        print(f"IMAP Error ({alias_email}): {e}")
        return None

def fetch_outlook(email_addr, password=None, refresh_token=None, client_id=None):
    if password and refresh_token and client_id:
        email_data = f"{email_addr}|{password}|{refresh_token}|{client_id}"
    else:
        email_data = email_addr

    payload = {"emailData": email_data, "messageCount": 20}
    headers = {"Content-Type": "application/json"}
    try:
        response = requests.post(HOTMAIL_API_URL, json=payload, headers=headers, timeout=15)
        if response.status_code == 200:
            data = response.json()
            if data.get("success") is True or data.get("status") == "SUCCESS":
                for msg in data.get("messages", []):
                    code = extract_code(f"{msg.get('subject', '')} {msg.get('preview', '')}")
                    if code:
                        return code
                return None
            return None
        return None
    except Exception as e:
        print(f"Outlook Error: {e}")
        return None

# ==============================================================================
# TELEGRAM BOT COMMAND HANDLERS
# ==============================================================================
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    user_id = message.from_user.id
    if is_admin(user_id):
        text = (
            "👋 **សួស្តីម្ចាស់ប្រព័ន្ធ LSH-POS!**\n\n"
            "🤖 Bot នេះបានបញ្ចូលគ្នាទាំង **ការទាញយកកូដអ៊ីមែល** និង **ការគ្រប់គ្រង License LSH-POS**៖\n\n"
            "🛒 **ពាក្យបញ្ជាគ្រប់គ្រង LSH-POS (Admin Commands):**\n"
            "• `/newmart <ឈ្មោះហាង> <ចំនួនថ្ងៃ>` — បង្កើត Mart & License Key ថ្មី\n"
            "• `/marts` — មើលបញ្ជី Mart ទាំងអស់ និងថ្ងៃផុតកំណត់\n"
            "• `/extend <MART-ID> <ចំនួនថ្ងៃ>` — ពន្យារយៈពេលបន្ថែម\n"
            "• `/revoke <MART-ID>` — ផ្អាកដំណើរការ Mart នោះភ្លាមៗ\n"
            "• `/settoken <Bot-Token>` — Encrypt & Update Bot Token លើ Gist\n"
            "• `/myid` — មើល Telegram ID របស់អ្នក\n\n"
            "📧 សម្រាប់ទាញយកកូដអ៊ីមែល៖ អាចផ្ញើ `mail@outlook.com` ដូចធម្មតា។"
        )
    else:
        text = (
            "សួស្តី! ខ្ញុំគឺជា Bot សម្រាប់ទាញយកកូដ។\n"
            "អ្នកអាចផ្ញើ **ឈ្មោះអ៊ីមែលមួយ ឬច្រើន** មកកាន់ខ្ញុំក្នុងពេលតែមួយបាន។\n"
            "(ឧទាហរណ៍៖ `mail1@guerrillamail.com mail2@outlook.com`)"
        )
    bot.reply_to(message, text, parse_mode="Markdown")

@bot.message_handler(commands=['myid'])
def cmd_my_id(message):
    bot.reply_to(
        message, 
        f"🆔 **Telegram ID របស់អ្នកគឺ:** `{message.from_user.id}`\n\n"
        f"💡 បងអាចយកលេខនេះទៅដាក់ក្នុង Environment Variable `ADMIN_ID` លើ Render ដើម្បីការពារកុំឱ្យអ្នកដទៃបញ្ជាបាន!",
        parse_mode="Markdown"
    )

@bot.message_handler(commands=['setadmin'])
def cmd_set_admin(message):
    global ADMIN_ID
    if not ADMIN_ID:
        ADMIN_ID = str(message.from_user.id)
        bot.reply_to(message, f"✅ បានកំណត់ Admin ID ទៅកាន់: `{ADMIN_ID}` រួចរាល់!", parse_mode="Markdown")
    else:
        bot.reply_to(message, "⚠️ Admin ត្រូវបានកំណត់រួចហើយ!", parse_mode="Markdown")

# ------------------------------------------------------------------------------
# 1. ADD NEW MART & GENERATE HASHED LICENSE
# ------------------------------------------------------------------------------
@bot.message_handler(commands=['newmart'])
def cmd_new_mart(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "⛔ សុំទោស សិទ្ធិនេះសម្រាប់តែ Admin ប៉ុណ្ណោះ!")
        return

    # Syntax: /newmart <Mart Name> <Days>
    parts = message.text.split()
    if len(parts) < 3:
        bot.reply_to(
            message,
            "⚠️ **ទម្រង់មិនត្រឹមត្រូវ!**\n"
            "សូមប្រើ៖ `/newmart <ឈ្មោះហាង> <ចំនួនថ្ងៃ>`\n\n"
            "ឧទាហរណ៍៖\n"
            "`/newmart Smile-Mart 365`\n"
            "`/newmart Lucky-ToulKork 180`",
            parse_mode="Markdown"
        )
        return

    mart_name = " ".join(parts[1:-1])
    try:
        days = int(parts[-1])
    except ValueError:
        bot.reply_to(message, "❌ ចំនួនថ្ងៃត្រូវតែជាលេខ (ឧ. 365)!")
        return

    bot.reply_to(message, "⏳ កំពុងទាញយកទិន្នន័យពី Gist និងបង្កើត Key ថ្មី...")

    gist_data, fname = fetch_gist_data()
    if not gist_data:
        gist_data = {"system": {}, "marts": {}}
    if "marts" not in gist_data:
        gist_data["marts"] = {}

    # Determine Mart ID (e.g. MART-01, MART-02...)
    existing_marts = gist_data.get("marts", {})
    mart_id = f"MART-{len(existing_marts) + 1:02d}"

    # Generate License Key & SHA-256 Hash
    key = generate_random_license_key()
    key_hash = hash_license_key(key)
    expiry_date = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")

    # Add to Gist structure (store ONLY hash!)
    gist_data["marts"][mart_id] = {
        "key_hash": key_hash,
        "mart_name": mart_name,
        "expiry_date": expiry_date,
        "status": "active"
    }

    # Save to Gist via GitHub API
    success, msg = save_gist_data(gist_data, fname)
    if success:
        reply_msg = (
            f"🎉 **បង្កើត Mart ថ្មីជោគជ័យ!**\n"
            f"───────────────────\n"
            f"🏪 **ហាង៖** {mart_name} (`{mart_id}`)\n"
            f"⏳ **សុពលភាព៖** {days} ថ្ងៃ\n"
            f"📅 **ផុតកំណត់៖** {expiry_date}\n\n"
            f"🔑 **LICENSE KEY សម្រាប់អតិថិជន៖**\n"
            f"```{key}```\n"
            f"*(ចុចលើលេខកូដដើម្បី Copy ផ្ញើឱ្យអតិថិជន)*\n"
            f"───────────────────\n"
            f"🔒 *សុវត្ថិភាពខ្ពស់៖ នៅលើ Gist រក្សាទុកត្រឹមតែ SHA-256 Hash ប៉ុណ្ណោះ គ្មាននរណាអាចលួច Key នេះបានឡើយ!*"
        )
    else:
        reply_msg = f"❌ មិនអាច Update ចូល Gist បានទេ៖ {msg}"

    bot.reply_to(message, reply_msg, parse_mode="Markdown")

# ------------------------------------------------------------------------------
# 2. LIST ALL MARTS & STATUS
# ------------------------------------------------------------------------------
@bot.message_handler(commands=['marts'])
def cmd_list_marts(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "⛔ សុំទោស សិទ្ធិនេះសម្រាប់តែ Admin ប៉ុណ្ណោះ!")
        return

    bot.reply_to(message, "🔍 កំពុងពិនិត្យមើលបញ្ជី Mart លើ Gist...")
    gist_data, _ = fetch_gist_data()
    marts = gist_data.get("marts", {})

    if not marts:
        bot.reply_to(message, "📭 មិនទាន់មាន Mart ណាមួយត្រូវបានបង្កើតនៅឡើយទេ។")
        return

    now = datetime.now()
    lines = ["📊 **បញ្ជី MARTS ទាំងអស់ក្នុងប្រព័ន្ធ៖**\n"]
    for code, info in marts.items():
        name = info.get("mart_name", code)
        status = info.get("status", "active")
        exp_str = info.get("expiry_date", "")
        status_icon = "🟢" if status == "active" else "🔴"

        days_text = ""
        try:
            exp_date = datetime.strptime(exp_str, "%Y-%m-%d")
            diff = (exp_date - now).days
            days_text = f"({diff} ថ្ងៃនៅសល់)" if diff >= 0 else "(ផុតកំណត់)"
        except Exception:
            pass

        lines.append(f"{status_icon} **{code}** — {name}\n   📅 ផុតកំណត់: {exp_str} {days_text} | Status: `{status}`\n")

    lines.append("\n💡 ប្រើ `/revoke <ID>` ដើម្បីផ្អាក ឬ `/extend <ID> <ថ្ងៃ>` ដើម្បីបន្ថែមថ្ងៃ។")
    bot.reply_to(message, "\n".join(lines), parse_mode="Markdown")

# ------------------------------------------------------------------------------
# 3. REVOKE / SUSPEND MART
# ------------------------------------------------------------------------------
@bot.message_handler(commands=['revoke'])
def cmd_revoke_mart(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "⛔ សុំទោស សិទ្ធិនេះសម្រាប់តែ Admin ប៉ុណ្ណោះ!")
        return

    parts = message.text.split()
    if len(parts) < 2:
        bot.reply_to(message, "⚠️ សូមបញ្ជាក់ Mart ID! ឧ. `/revoke MART-01`", parse_mode="Markdown")
        return

    target_code = parts[1].strip().upper()
    gist_data, fname = fetch_gist_data()
    marts = gist_data.get("marts", {})

    if target_code not in marts:
        bot.reply_to(message, f"❌ រកមិនឃើញ `{target_code}` ក្នុងប្រព័ន្ធឡើយ!", parse_mode="Markdown")
        return

    marts[target_code]["status"] = "revoked"
    success, msg = save_gist_data(gist_data, fname)
    if success:
        bot.reply_to(message, f"🚫 **បានផ្អាកដំណើរការ (REVOKED) `{target_code}` ({marts[target_code].get('mart_name')}) ជោគជ័យ!**", parse_mode="Markdown")
    else:
        bot.reply_to(message, f"❌ បរាជ័យក្នុងការ Update: {msg}")

# ------------------------------------------------------------------------------
# 4. EXTEND LICENSE DAYS
# ------------------------------------------------------------------------------
@bot.message_handler(commands=['extend'])
def cmd_extend_mart(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "⛔ សុំទោស សិទ្ធិនេះសម្រាប់តែ Admin ប៉ុណ្ណោះ!")
        return

    parts = message.text.split()
    if len(parts) < 3:
        bot.reply_to(message, "⚠️ សូមប្រើទម្រង់៖ `/extend <MART-ID> <ចំនួនថ្ងៃបន្ថែម>`\nឧទាហរណ៍៖ `/extend MART-01 30`", parse_mode="Markdown")
        return

    target_code = parts[1].strip().upper()
    try:
        add_days = int(parts[2])
    except ValueError:
        bot.reply_to(message, "❌ ចំនួនថ្ងៃត្រូវតែជាលេខ!")
        return

    gist_data, fname = fetch_gist_data()
    marts = gist_data.get("marts", {})

    if target_code not in marts:
        bot.reply_to(message, f"❌ រកមិនឃើញ `{target_code}` ក្នុងប្រព័ន្ធឡើយ!", parse_mode="Markdown")
        return

    cur_exp = marts[target_code].get("expiry_date", "")
    try:
        base_date = datetime.strptime(cur_exp, "%Y-%m-%d")
        if base_date < datetime.now():
            base_date = datetime.now()
        new_exp = (base_date + timedelta(days=add_days)).strftime("%Y-%m-%d")
        marts[target_code]["expiry_date"] = new_exp
        marts[target_code]["status"] = "active"

        success, msg = save_gist_data(gist_data, fname)
        if success:
            bot.reply_to(message, f"✅ **បានពន្យារយៈពេល `{target_code}` +{add_days} ថ្ងៃជោគជ័យ!**\n📅 កាលបរិច្ឆេទផុតកំណត់ថ្មី: `{new_exp}`", parse_mode="Markdown")
        else:
            bot.reply_to(message, f"❌ បរាជ័យក្នុងការ Update: {msg}")
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")

# ------------------------------------------------------------------------------
# 5. ENCRYPT & SET TELEGRAM BOT TOKEN ON GIST
# ------------------------------------------------------------------------------
@bot.message_handler(commands=['settoken'])
def cmd_set_token(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "⛔ សុំទោស សិទ្ធិនេះសម្រាប់តែ Admin ប៉ុណ្ណោះ!")
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        bot.reply_to(message, "⚠️ សូមបញ្ជាក់ Bot Token! ឧ. `/settoken 9008183535:AAHJ...`", parse_mode="Markdown")
        return

    raw_token = parts[1].strip()
    try:
        enc_token = encrypt_bot_token(raw_token)
        gist_data, fname = fetch_gist_data()
        if "system" not in gist_data:
            gist_data["system"] = {}

        gist_data["system"]["report_bot_token_encrypted"] = enc_token
        # Clear any plaintext token
        if "report_bot_token" in gist_data["system"]:
            del gist_data["system"]["report_bot_token"]

        success, msg = save_gist_data(gist_data, fname)
        if success:
            bot.reply_to(
                message,
                f"🔐 **Bot Token ត្រូវបាន Encrypt (AES-256) និង Update លើ Gist រួចរាល់!**\n\n"
                f"🔒 *Ciphertext លើ Gist:*\n`{enc_token[:25]}...{enc_token[-15:]}`\n\n"
                f"✅ ម៉ាស៊ីន POS ទាំងអស់នឹងទាញយក និង Decrypt ដោយស្វ័យប្រវត្តិតាមរយៈ .pyd!",
                parse_mode="Markdown"
            )
        else:
            bot.reply_to(message, f"❌ មិនអាច Update Gist បានទេ៖ {msg}")
    except Exception as e:
        bot.reply_to(message, f"❌ Error ពេល Encrypt Token: {e}")

# ==============================================================================
# EXISTING EMAIL OTP EXTRACTOR HANDLER (PRESERVED 100%)
# ==============================================================================
@bot.message_handler(func=lambda message: True)
def get_code_from_mail(message):
    parts = message.text.strip().split('|')
    alias_email = parts[0].strip().lower()
    
    if "@" not in alias_email:
        bot.reply_to(message, "❌ សូមបញ្ចូលអ៊ីមែលឱ្យបានត្រឹមត្រូវ!")
        return

    bot.reply_to(message, f"🔍 កំពុងដំណើរការស្វែងរកសម្រាប់: {alias_email}...")

    # ២. ករណី Outlook/Hotmail (ទម្រង់ពេញ)
    if len(parts) >= 4:
        password = parts[1].strip()
        refresh_token = parts[2].strip()
        client_id = parts[3].strip()
        code = fetch_outlook(alias_email, password, refresh_token, client_id)
        if code:
            bot.reply_to(message, f"✅ កូដ Outlook របស់អ្នកគឺ: `{code}`", parse_mode="Markdown")
        else:
            bot.reply_to(message, "❌ រកមិនឃើញកូដទេ (សូមឆែកមើល Logs ក្នុង Render ដើម្បីដឹងពីបញ្ហា)")
        return
    
    # ៣. ករណី Guerrilla Mail
    domain = alias_email.split("@")[1]
    if domain in GUERRILLA_DOMAINS:
        res = fetch_guerrilla_mail(alias_email)
        if res:
            code, body = res
            bot.reply_to(message, f"✅ កូដ Guerrilla របស់អ្នកគឺ: `{code}`", parse_mode="Markdown")
        else:
            bot.reply_to(message, "❌ មិនមានកូដថ្មីៗក្នុង Guerrilla Mail នេះទេ")
        return

    # ៤. ករណី Yandex/Zoho/Mailfence - ឆែកក្នុង JSONbin
    email_accounts = load_email_accounts()
    if not email_accounts:
        bot.reply_to(message, "⚠️ មិនមាន Database សម្រាប់ឆែកទេ")
        return

    base_email = alias_email.split("+")[0]
    matched_accounts = [acc for acc in email_accounts if acc.split("|")[0].split("@")[0] == base_email]

    if not matched_accounts:
        bot.reply_to(message, "❌ រកមិនឃើញអ៊ីមែលនេះក្នុងប្រព័ន្ធទេ (សូមបញ្ចូលក្នុង JSONbin)")
        return

    found = False
    for acc in matched_accounts:
        res = fetch_latest_email(acc, alias_email)
        if res:
            code, body = res
            if code:
                bot.reply_to(message, f"✅ កូដរបស់អ្នកគឺ: `{code}`", parse_mode="Markdown")
                found = True
                break
    
    if not found:
        bot.reply_to(message, "❌ មិនមានកូដថ្មីៗទេ")

# ==============================================================================
# MAIN ENTRY POINT
# ==============================================================================
if __name__ == "__main__":
    print("Starting Web Server...")
    keep_alive()
    print("Starting Telegram Bot (Email Extractor + LSH-POS Admin)...")
    bot.infinity_polling(skip_pending=True)

