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

# === TOKEN (MUST be set in Railway Variables as "TOKEN") ===
TOKEN = os.getenv('TOKEN')
if not TOKEN:
    print("FATAL: TOKEN not found! Add it in Railway Variables")
    exit()
bot = telebot.TeleBot(TOKEN)

# === GOOGLE SHEETS LOGGING (WITH FULL DEBUG) ===
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds_json = os.getenv('GOOGLE_CREDENTIALS')

if not creds_json:
    print("ERROR: GOOGLE_CREDENTIALS variable is missing or empty!")
    logging_enabled = False
else:
    print("GOOGLE_CREDENTIALS found – length:", len(creds_json))
    try:
        creds_dict = json.loads(creds_json)
        print("JSON parsed successfully")
        print("Project ID:", creds_dict.get("project_id"))
        print("Client email:", creds_dict.get("client_email"))

        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        gc = gspread.authorize(creds)
        print("Authorized with Google successfully")

        # ←←←←← CHANGE THIS TO YOUR EXACT SHEET NAME (case-sensitive!) ←←←←←
        sheet = gc.open("TiktokData").sheet1   # ←←← CHANGE THIS LINE!
        
        print("Opened sheet successfully:", sheet.title)
        logging_enabled = True
        print("Google Sheets logging FULLY ENABLED")
    except Exception as e:
        print("Google Sheets setup FAILED:", str(e))
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
        print("Logged to Google Sheet:", row)
    except Exception as e:
        print("Failed to write to sheet:", str(e))

# Temporary folder
if not os.path.exists('downloads'):
    os.makedirs('downloads')

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(message, "TikTok Downloader Bot\n\n"
                         "Send any TikTok link → I’ll download it + log to Google Sheets!")

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    url = message.text.strip()
    if "tiktok.com" not in url:
        bot.reply_to(message, "Please send a valid TikTok link!")
        return

    log_usage(message.from_user, url, "Received")
    status_msg = bot.reply_to(message, "Processing...")

    try:
        unique_id = str(uuid.uuid4())
        temp_path = f"downloads/{unique_id}"

        if "/photo/" in url:
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
                bot.send_document(message.chat.id, z, caption="Your TikTok photos + music")
            os.remove(zip_path)
            log_usage(message.from_user, url, "Photo Sent")

        else:
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
                        bot.send_video(message.chat.id, video, caption="Your TikTok video (no watermark)!")
                    os.remove(path)
                    log_usage(message.from_user, url, "Video Sent")
                    break

        bot.delete_message(message.chat.id, status_msg.message_id)

    except Exception as e:
        bot.reply_to(message, f"Failed: {str(e)}")
        log_usage(message.from_user, url, f"Failed: {str(e)[:50]}")
        print("ERROR:", e)

# === PHOTO DOWNLOADER (keep your working version) ===
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

print("Bot started – waiting for links...")
bot.infinity_polling()