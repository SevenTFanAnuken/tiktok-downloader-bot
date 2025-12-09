# bot.py
import telebot
import yt_dlp
import os
import uuid
import requests
from bs4 import BeautifulSoup
from urllib.parse import unquote
import zipfile
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import json

# === TOKEN ===
TOKEN = os.getenv('TOKEN')
if not TOKEN:
    print("FATAL: TOKEN not found!")
    exit()
bot = telebot.TeleBot(TOKEN)

# === GOOGLE SHEETS LOGGING ===
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds_json = os.getenv('GOOGLE_CREDENTIALS')

if creds_json:
    try:
        creds = ServiceAccountCredentials.from_json_keyfile_dict(json.loads(creds_json), scope)
        gc = gspread.authorize(creds)
        sheet = gc.open("TiktokData").sheet1  # Your sheet name
        logging_enabled = True
        print("Google Sheets logging ENABLED")
    except Exception as e:
        print("Google Sheets failed:", e)
        logging_enabled = False
else:
    print("No GOOGLE_CREDENTIALS → logging disabled")
    logging_enabled = False

def log_usage(user, url, status="Success"):
    if not logging_enabled:
        return
    try:
        row = [
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            user.id,
            user.username or "None",
            user.first_name or "",
            url,
            "Video" if "/video/" in url else "Photo",
            status
        ]
        sheet.append_row(row)
    except Exception as e:
        print("Sheet write failed:", e)

# Temporary folder
if not os.path.exists('downloads'):
    os.makedirs('downloads')

# ==================== COMMANDS ====================

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "Bot is waiting for the link\n\n"
                          "Just send any TikTok link and I will download it for you!")

@bot.message_handler(commands=['help'])
def send_help(message):
    help_text = (
        "Available Commands:\n\n"
        "/start - Show welcome message\n"
        "/help  - Show this help\n"
        "/issue - Contact the developer\n\n"
        "Just paste any TikTok link (video or photo) and I’ll send it back without watermark!"
    )
    bot.reply_to(message, help_text)

@bot.message_handler(commands=['issue'])
def send_issue(message):
    bot.reply_to(message, "Found a bug or have a suggestion?\n"
                          "Contact the developer: @mnchetra")

# ==================== MAIN HANDLER ====================

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    url = message.text.strip()
    
    if "tiktok.com" not in url:
        bot.reply_to(message, "Please send a valid TikTok link!")
        return

    # Log when link received
    log_usage(message.from_user, url, "Received")
    status_msg = bot.reply_to(message, "Downloading...")

    try:
        unique_id = str(uuid.uuid4())
        temp_path = f"downloads/{unique_id}"

        if "/photo/" in url:
            # === PHOTO DOWNLOAD ===
            bot.edit_message_text("Downloading photo(s)...", message.chat.id, status_msg.message_id)
            files = download_tiktok_photo(url, temp_path)
            if not files:
                raise Exception("No media found")

            zip_path = f"{temp_path}.zip"
            with zipfile.ZipFile(zip_path, 'w') as zf:
                for f in files:
                    zf.write(f, arcname=os.path.basename(f))
                    os.remove(f)

            with open(zip_path, 'rb') as z:
                # Caption = the original link
                bot.send_document(message.chat.id, z, caption=url)
            os.remove(zip_path)
            log_usage(message.from_user, url, "Photo Sent")

        else:
            # === VIDEO DOWNLOAD ===
            bot.edit_message_text("Downloading video...", message.chat.id, status_msg.message_id)
            ydl_opts = {
                'outtmpl': f'{temp_path}.%(ext)s',
                'format': 'bestvideo[height<=720]+bestaudio/best[height<=720]/best',
                'merge_output_format': 'mp4',
                'quiet': True,
                'cookiefile': 'cookies.txt',
                'user_agent': 'Mozilla/5.0',
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])

            for file in os.listdir('downloads'):
                if file.startswith(unique_id):
                    path = os.path.join('downloads', file)
                    with open(path, 'rb') as video:
                        # Caption = the original TikTok link
                        bot.send_video(message.chat.id, video, caption=url)
                    os.remove(path)
                    log_usage(message.from_user, url, "Video Sent")
                    break

        bot.delete_message(message.chat.id, status_msg.message_id)

    except Exception as e:
        bot.reply_to(message, f"Download failed: {str(e)}")
        log_usage(message.from_user, url, f"Failed")
        print("ERROR:", e)

# === PHOTO DOWNLOADER FUNCTION ===
def download_tiktok_photo(url, base_path):
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        r = requests.get(url, headers=headers, timeout=15)
        r.raise_for_status()
    except:
        return []
    soup = BeautifulSoup(r.text, 'html.parser')
    downloaded = []
    for script in soup.find_all('script'):
        if not script.string: continue
        txt = script.string
        pos = 0
        while True:
            pos = txt.find('https://', pos)
            if pos == -1: break
            end = txt.find('"', pos)
            if end == -1: break
            img_url = unquote(txt[pos:end])
            if ('p16-sign' in img_url or 'p26-sign' in img_url) and img_url.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
                try:
                    img_data = requests.get(img_url, headers=headers, timeout=15).content
                    img_path = f"{base_path}_{len(downloaded)}.jpg"
                    with open(img_path, 'wb') as f:
                        f.write(img_data)
                    downloaded.append(img_path)
                except: pass
            pos = end
        if 'playUrl' in txt:
            pos = txt.find('"playUrl":"')
            if pos != -1:
                pos += 11
                end = txt.find('"', pos)
                music_url = unquote(txt[pos:end])
                if 'tiktokcdn.com' in music_url:
                    try:
                        music_data = requests.get(music_url, headers=headers, timeout=15).content
                        music_path = f"{base_path}_music.mp3"
                        with open(music_path, 'wb') as f:
                            f.write(music_data)
                        downloaded.append(music_path)
                    except: pass
    return downloaded

print("Bot started – waiting for TikTok links...")
bot.infinity_polling()