import telebot
import imaplib
import email
import re
import requests
import os
from flask import Flask
from threading import Thread

# ទាញយកកូដសម្ងាត់ពី Environment Variables របស់ Render
BOT_TOKEN = ""
BIN_URL = ""
API_KEY = ""
HOTMAIL_API_URL = os.environ.get("HOTMAIL_API_URL", "https://mailgen.shop/api/inbox-read")

bot = telebot.TeleBot(BOT_TOKEN)

# បញ្ជី Domain របស់ Guerrilla Mail
GUERRILLA_DOMAINS = [
    "guerrillamail.com", "guerrillamail.info", "guerrillamail.biz", 
    "guerrillamail.de", "guerrillamail.net", "guerrillamail.org", 
    "sharklasers.com", "grr.la", "pokemail.net", "spam4.me", "guerrillamailblock.com"
]

# បន្ថែម Server របស់ Microsoft (Outlook/Hotmail)
IMAP_SERVERS = {
    "yandex": "imap.yandex.com",
    "zoho": "imap.zoho.com",
    "mailfence": "imap.mailfence.com",
    "outlook": "outlook.office365.com",
    "hotmail": "outlook.office365.com"
}

# --- ផ្នែក Flask Web Server (សម្រាប់ឱ្យប្រព័ន្ធដើរ ២៤ម៉ោងលើ Render) ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is awake and fully updated on Render!"

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_web_server)
    t.start()

# --- ទាញយកទិន្នន័យគណនីពី JSONbin ---
def load_email_accounts():
    try:
        headers = {"X-Master-Key": API_KEY}
        response = requests.get(BIN_URL, headers=headers, timeout=5)
        if response.status_code == 200:
            return response.json()["record"].get("emails", [])
    except Exception as e:
        print(f"Error fetching data: {e}")
    return []

# --- មុខងារស្វែងរកកូដទូទៅ (ចាប់យកលេខពី ៤ ទៅ ៨ ខ្ទង់) ---
def extract_code(email_body):
    if not email_body:
        return None
    # ស្វែងរកលេខ ៤ ដល់ ៨ ខ្ទង់ ដែលស្ថិតនៅជិតពាក្យ code, confirm, is, លេខ, verification...
    pattern = r'(?i)(?:code|confirm|is|លេខ|verification|pin|otp).*?(\d{4,8})'
    match = re.search(pattern, email_body)
    
    if match:
        return match.group(1)
        
    # បើរកមិនឃើញលេខជិតពាក្យទាំងនោះទេ សឹមត្រឡប់មករកលេខ ៤ ដល់ ៨ ខ្ទង់ធម្មតា
    match_simple = re.search(r'\b(\d{4,8})\b', email_body)
    if match_simple:
        return match_simple.group(1)
        
    return None

# --- មុខងារ៖ ទាញយកពី Guerrilla Mail ផ្ទាល់ ---
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

# --- មុខងារ៖ ទាញយកពី IMAP ធម្មតា (Yandex, Zoho, Mailfence, Outlook, Hotmail) ---
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

        # បើសិនជា Outlook/Hotmail ហើយមាន App Password (ធាតុទី៤) ត្រូវយកមកប្រើ
        if provider in ["outlook", "hotmail"] and len(email_parts) == 4:
            password = email_parts[3]  # apppassword
        else:
            password = email_parts[1]  # pass ធម្មតាសម្រាប់ provider ផ្សេងទៀត

        mail = imaplib.IMAP4_SSL(imap_server)
        mail.login(main_email, password)

        # កំណត់ Folder ទៅតាមប្រភេទ Provider (Microsoft ប្រើ INBOX ឬ Junk)
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

        # ស្វែងរកអ៊ីមែលពី Facebook (អាចកែប្រែបាន)
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
        
# --- មុខងារ៖ ទាញយកពី Outlook/Hotmail (ប្រើប្រាស់ Inbox Read API ថ្មី) ---
def fetch_outlook(email_addr, password=None, refresh_token=None, client_id=None):
    if password and refresh_token and client_id:
        email_data = f"{email_addr}|{password}|{refresh_token}|{client_id}"
    else:
        email_data = email_addr

    print(f"[DEBUG] កំពុងស្នើសុំទាញយកសារពី Outlook/Hotmail API ({HOTMAIL_API_URL})...")
    payload = {
        "emailData": email_data,
        "messageCount": 20
    }
    headers = {
        "Content-Type": "application/json"
    }

    try:
        response = requests.post(HOTMAIL_API_URL, json=payload, headers=headers, timeout=15)
        if response.status_code == 200:
            data = response.json()
            if data.get("success") is True or data.get("status") == "SUCCESS":
                messages = data.get("messages", [])
                for msg in messages:
                    subject = msg.get("subject", "")
                    preview = msg.get("preview", "")
                    # ស្វែងរកកូដក្នុង subject ឬ preview
                    code = extract_code(f"{subject} {preview}")
                    if code:
                        print(f"[DEBUG] ទាញយកកូដបានជោគជ័យ: {code}")
                        return code
                print("[DEBUG] ចូលបានជោគជ័យ តែមិនទាន់មានកូដក្នុងសារទេ")
                return None
            else:
                print(f"[DEBUG] API ត្រឡប់ Error: {data.get('error')}")
                return None
        else:
            print(f"[DEBUG] API Response Error Code ({response.status_code}): {response.text}")
            return None
    except Exception as e:
        print(f"[ERROR] Error ពេលហៅ Outlook/Hotmail API: {e}")
        return None

        
# --- Telegram Bot Commands (ប្រព័ន្ធទទួលសារ) ---
@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "សួស្តី! ខ្ញុំគឺជា Bot សម្រាប់ទាញយកកូដ។\nអ្នកអាចផ្ញើ **ឈ្មោះអ៊ីមែលមួយ ឬច្រើន** មកកាន់ខ្ញុំក្នុងពេលតែមួយបាន។\n(ឧទាហរណ៍៖ `mail1@guerrillamail.com mail2@outlook.com`)", parse_mode="Markdown")

@bot.message_handler(func=lambda message: True)
def get_code_from_mail(message):
    # ១. បំបែកសារដែលអ្នកប្រើប្រាស់ផ្ញើមកតាមសញ្ញា |
    parts = message.text.strip().split('|')
    alias_email = parts[0].strip().lower()
    
    # បើមិនមែនជាទម្រង់អ៊ីមែលទេ
    if "@" not in alias_email:
        bot.reply_to(message, "❌ សូមបញ្ចូលអ៊ីមែលឱ្យបានត្រឹមត្រូវ!")
        return

    bot.reply_to(message, f"🔍 កំពុងដំណើរការស្វែងរកសម្រាប់: {alias_email}...")

    # ២. ករណី Outlook/Hotmail (ទម្រង់ពេញ)
    if len(parts) >= 4:
        password = parts[1].strip()
        refresh_token = parts[2].strip()  # នេះគឺជា Refresh Token
        client_id = parts[3].strip()      # នេះជា Client ID
        
        # បញ្ជូនទិន្នន័យទាំងអស់ទៅកាន់ fetch_outlook
        code = fetch_outlook(alias_email, password, refresh_token, client_id)
        
        if code:
            bot.reply_to(message, f"✅ កូដ Outlook របស់អ្នកគឺ: `{code}`", parse_mode="Markdown")
        else:
            bot.reply_to(message, "❌ រកមិនឃើញកូដទេ (សូមឆែកមើល Logs ក្នុង Render ដើម្បីដឹងពីបញ្ហា)")
        return
    
    # ៣. ករណី Guerrilla Mail (ទម្រង់: mail)
    domain = alias_email.split("@")[1]
    if domain in GUERRILLA_DOMAINS:
        res = fetch_guerrilla_mail(alias_email)
        if res:
            code, body = res
            bot.reply_to(message, f"✅ កូដ Guerrilla របស់អ្នកគឺ: `{code}`", parse_mode="Markdown")
        else:
            bot.reply_to(message, "❌ មិនមានកូដថ្មីៗក្នុង Guerrilla Mail នេះទេ")
        return

    # ៤. ករណី Yandex/Zoho/Mailfence (ទម្រង់: mail) - ឆែកក្នុង JSONbin
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

if __name__ == "__main__":
    print("Starting Web Server...")
    keep_alive()
    print("Starting Telegram Bot...")
    bot.infinity_polling(skip_pending=True)
