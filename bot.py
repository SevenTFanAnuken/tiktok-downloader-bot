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
TOKEN = os.getenv('7880620831:AAE-pjgq2FU0YNJ7sGakn0GHT9E0DvmQCvc')
bot = telebot.TeleBot(TOKEN)

# === GOOGLE SHEETS LOGGING (secure – no file needed) ===
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds_json = os.getenv('GOOGLE_CREDENTIALS')

if creds_json:
    try:
        creds = ServiceAccountCredentials.from_json_keyfile_dict(json.loads(creds_json), scope)
        gc = gspread.authorize(creds)
        sheet = gc.open("TikTok Bot Logs").sheet1   # ← CHANGE THIS TO YOUR EXACT SHEET NAME
        logging_enabled = True
        print("Google Sheets logging ENABLED")
    except Exception as e:
        print("Google Sheets failed to initialize:", e)
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
        print("Failed to write to sheet:", e)

# Temporary folder
if not os.path.exists('downloads'):
    os.makedirs('downloads')

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(message, "TikTok Downloader Bot\n\n"
                         "Send any TikTok link → I’ll download it (video/photo/sensitive) and log everything!")

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    url = message.text.strip()
    if "tiktok.com" not in url:
        bot.reply_to(message, "Please send a valid TikTok link!")
        return

    # Log immediately when link is received
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
            bot.edit_message_text("Downloading video (no watermark)...", message.chat.id, status_msg.message_id)
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

# === PHOTO DOWNLOADER (unchanged) ===
def download_tiktok_photo(url, base_path):
    # your existing function – keep it exactly as before
    # (copy-paste your current one here)
    pass  # ← replace with your real function

print("Bot started – full logging active!")
bot.infinity_polling()