# bot.py - FINAL VERSION (December 2025)
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
import time

# === TOKEN ===
TOKEN = os.getenv('TOKEN')
if not TOKEN:
    print("FATAL: TOKEN not found in Railway Variables!")
    exit()
bot = telebot.TeleBot(TOKEN)

# === GOOGLE SHEETS LOGGING (AUTO-CREATES HEADERS) ===
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds_json = os.getenv('GOOGLE_CREDENTIALS')

if creds_json:
    try:
        creds = ServiceAccountCredentials.from_json_keyfile_dict(json.loads(creds_json), scope)
        gc = gspread.authorize(creds)
        sh = gc.open("Sheet1")           # ← Change only if your sheet has a different name
        sheet = sh.sheet1

        # AUTO-CREATE HEADERS IF MISSING OR WRONG
        headers = ["Timestamp", "User ID", "Username", "First Name", "TikTok Link", "Type", "Status"]
        current_headers = sheet.row_values(1)
        if not current_headers or current_headers != headers:
            sheet.clear()
            sheet.append_row(headers)
            print("Google Sheet headers created automatically!")

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
        print("Logged to sheet:", row)
    except Exception as e:
        print("Sheet write failed:", e)

# Temporary folder
if not os.path.exists('downloads'):
    os.makedirs('downloads')

# ==================== COMMANDS ====================

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "Bot is waiting for the link\n\n"
                          "Just send any TikTok link — I'll download it for you!")

@bot.message_handler(commands=['help'])
def send_help(message):
    bot.reply_to(message,
        "Commands:\n"
        "/start - Welcome\n"
        "/help - This help\n"
        "/issue - Contact @mnchetra\n\n"
        "Just paste any TikTok link → I send video/photo with the link as caption!")

@bot.message_handler(commands=['issue'])
def send_issue(message):
    bot.reply_to(message, "Found a bug or need help?\nContact the developer: @mnchetra")

# ==================== MAIN HANDLER ====================

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    url = message.text.strip()
    if "tiktok.com" not in url:
        bot.reply_to(message, "Please send a valid TikTok link!")
        return

    log_usage(message.from_user, url, "Received")
    status_msg = bot.reply_to(message, "Downloading...")

    try:
        unique_id = str(uuid.uuid4())
        temp_path = f"downloads/{unique_id}"

        # === PHOTO POSTS ===
        if "/photo/" in url:
            bot.edit_message_text("Downloading photo(s)...", message.chat.id, status_msg.message_id)
            files = download_tiktok_photo_robust(url, temp_path)
            if not files:
                raise Exception("No photos found")

            zip_path = f"{temp_path}.zip"
            with zipfile.ZipFile(zip_path, 'w') as zf:
                for f in files:
                    zf.write(f, arcname=os.path.basename(f))
                    os.remove(f)

            with open(zip_path, 'rb') as z:
                bot.send_document(message.chat.id, z, caption=url)
            os.remove(zip_path)
            log_usage(message.from_user, url, "Photo Sent")

        # === VIDEO POSTS ===
        else:
            success = False
            for attempt in range(3):
                try:
                    bot.edit_message_text(f"Downloading video... (attempt {attempt+1}/3)", message.chat.id, status_msg.message_id)
                    ydl_opts = {
                        'outtmpl': f'{temp_path}.%(ext)s',
                        'format': 'best[height<=720]/best',
                        'merge_output_format': 'mp4',
                        'quiet': True,
                        'cookiefile': 'cookies.txt',
                        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                        'referer': 'https://www.tiktok.com/',
                        'sleep_interval': 2,
                        'extractor_retries': 3,
                    }
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        ydl.download([url])

                    for file in os.listdir('downloads'):
                        if file.startswith(unique_id):
                            path = os.path.join('downloads', file)
                            with open(path, 'rb') as video:
                                bot.send_video(message.chat.id, video, caption=url)
                            os.remove(path)
                            success = True
                            log_usage(message.from_user, url, "Video Sent")
                            break
                    if success:
                        break
                    time.sleep(3)
                except Exception as e:
                    if attempt == 2:
                        raise e

        bot.delete_message(message.chat.id, status_msg.message_id)

    except Exception as e:
        bot.reply_to(message, f"Download failed: {str(e)}\nTry again or use /issue")
        log_usage(message.from_user, url, "Failed")
        print("ERROR:", e)

# === BULLETPROOF PHOTO DOWNLOADER + API FALLBACK ===
def download_tiktok_photo_robust(url, base_path, max_retries=3):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
    }

    for attempt in range(max_retries):
        try:
            r = requests.get(url, headers=headers, timeout=20)
            r.raise_for_status()
            break
        except Exception as e:
            print(f"Photo request failed (attempt {attempt+1}): {e}")
            if attempt < max_retries - 1:
                time.sleep(3)
            else:
                return download_photo_api_fallback(url, base_path)

    soup = BeautifulSoup(r.text, 'html.parser')
    downloaded = []

    for script in soup.find_all('script'):
        if not script.string:
            continue
        txt = script.string

        # Extract images
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
                    img_path = f"{base_path}_photo_{len(downloaded)+1}.jpg"
                    with open(img_path, 'wb') as f:
                        f.write(img_data)
                    downloaded.append(img_path)
                except: pass
            pos = end

        # Extract music
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

    if downloaded:
        return downloaded

    # Final fallback
    return download_photo_api_fallback(url, base_path)

def download_photo_api_fallback(url, base_path):
    try:
        api = "https://tikwm.com/api/"
        resp = requests.get(api, params={'url': url, 'hd': 1}, timeout=15)
        data = resp.json()
        downloaded = []

        if data.get('code') == 0 and 'data' in data:
            images = data['data'].get('images', [])
            for i, img_url in enumerate(images):
                if img_url:
                    img_path = f"{base_path}_photo_{i+1}.jpg"
                    img_data = requests.get(img_url, timeout=15).content
                    with open(img_path, 'wb') as f:
                        f.write(img_data)
                    downloaded.append(img_path)

            music_url = data['data'].get('music')
            if music_url:
                music_path = f"{base_path}_music.mp3"
                music = requests.get(music_url, timeout=15).content
                with open(music_path, 'wb') as f:
                    f.write(music)
                downloaded.append(music_path)

        return downloaded
    except Exception as e:
        print("API fallback failed:", e)
        return []

print("TikTok Downloader Bot is LIVE! (Auto headers + bulletproof)")
bot.infinity_polling()
