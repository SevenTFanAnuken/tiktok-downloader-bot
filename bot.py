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
    print("FATAL: TOKEN not found! Add it in Railway Variables")
    exit()

bot = telebot.TeleBot(TOKEN)

# === GOOGLE SHEETS LOGGING ===
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds_json = os.getenv('GOOGLE_CREDENTIALS')
logging_enabled = False

if creds_json:
    try:
        creds_dict = json.loads(creds_json)
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        gc = gspread.authorize(creds)
        sheet = gc.open("TiktokData").sheet1  # ← Change sheet name if needed

        # Auto-create headers if missing
        headers = ["Timestamp", "User ID", "Username", "First Name", "TikTok Link", "Type", "Status"]
        current_headers = sheet.row_values(1)
        if not current_headers or current_headers != headers:
            sheet.clear()
            sheet.append_row(headers)
            print("Google Sheet headers created automatically!")

        logging_enabled = True
        print("Google Sheets logging ENABLED")
    except Exception as e:
        print("Google Sheets setup FAILED:", str(e))
else:
    print("No GOOGLE_CREDENTIALS → logging disabled")

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
        print("Sheet write error:", e)

# Temporary folder
os.makedirs('downloads', exist_ok=True)

# === DUPLICATE PREVENTION CACHE ===
sent_cache = {}  # {chat_id: {url: sent_message_id}}

# ====================== COMMANDS ======================

@bot.message_handler(commands=['start'])
def cmd_start(message):
    bot.reply_to(message, "Bot is waiting for the link\n"
                         "Just send me any TikTok video or photo link!")

@bot.message_handler(commands=['help'])
def cmd_help(message):
    help_text = (
        "TikTok Downloader Bot Commands:\n\n"
        "/start – Show welcome message\n"
        "/help  – Show this help\n"
        "/issue – Contact the developer if something is wrong\n\n"
        "Just paste any TikTok link and I’ll send it without watermark!"
    )
    bot.reply_to(message, help_text)

@bot.message_handler(commands=['issue'])
def cmd_issue(message):
    bot.reply_to(message, "For any issues or suggestions, please contact the developer: @mnchetra")

# ====================== MAIN HANDLER ======================

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    url = message.text.strip()

    if "tiktok.com" not in url:
        bot.reply_to(message, "Please send a valid TikTok link!")
        return

    chat_id = message.chat.id

    # Anti-duplicate check
    if chat_id in sent_cache and url in sent_cache[chat_id]:
        prev_msg_id = sent_cache[chat_id][url]
        bot.reply_to(message, "You already downloaded this one!", reply_to_message_id=prev_msg_id)
        log_usage(message.from_user, url, "Duplicate")
        return

    log_usage(message.from_user, url, "Received")
    status_msg = bot.reply_to(message, "Processing your link…")

    try:
        unique_id = str(uuid.uuid4())
        temp_path = f"downloads/{unique_id}"
        is_photo = "/photo/" in url

        sent_msg = None

        if is_photo:
            bot.edit_message_text("Downloading photo slideshow…", chat_id, status_msg.message_id)
            files = download_tiktok_photo(url, temp_path)

            if not files:
                raise Exception("No media found in slideshow")

            zip_path = f"{temp_path}.zip"
            with zipfile.ZipFile(zip_path, 'w') as zf:
                for f in files:
                    zf.write(f, arcname=os.path.basename(f))
                    os.remove(f)

            with open(zip_path, 'rb') as z:
                sent_msg = bot.send_document(
                    chat_id,
                    z,
                    caption=url,
                    reply_to_message_id=message.message_id
                )
            os.remove(zip_path)
            log_usage(message.from_user, url, "Photo Sent")

        else:  # Video
            bot.edit_message_text("Downloading video (no watermark)…", chat_id, status_msg.message_id)

            # Primary: yt-dlp (with cookies for sensitive content)
            success = False
            try:
                ydl_opts = {
                    'outtmpl': f'{temp_path}.%(ext)s',
                    'format': 'bestvideo[height<=720]+bestaudio/best[height<=720]/best',
                    'merge_output_format': 'mp4',
                    'quiet': True,
                    'cookiefile': 'cookies.txt',
                    'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36',
                    'referer': 'https://www.tiktok.com/',
                }
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([url])
                success = True
            except Exception as e:
                print("yt-dlp failed (possibly sensitive content):", e)

            if success:
                # Send video from yt-dlp
                for file in os.listdir('downloads'):
                    if file.startswith(unique_id):
                        path = os.path.join('downloads', file)
                        with open(path, 'rb') as video_file:
                            sent_msg = bot.send_video(
                                chat_id,
                                video_file,
                                caption=url,
                                reply_to_message_id=message.message_id
                            )
                        os.remove(path)
                        log_usage(message.from_user, url, "Video Sent (yt-dlp)")
                        break
                else:
                    raise Exception("Video file not found after yt-dlp download")
            else:
                # Fallback: tikwm.com API
                print("Trying tikwm.com API fallback for video...")
                files = download_video_api_fallback(url, temp_path)
                if not files or not files[0].endswith('.mp4'):
                    raise Exception("API fallback failed or no video found")

                video_path = files[0]
                with open(video_path, 'rb') as video_file:
                    sent_msg = bot.send_video(
                        chat_id,
                        video_file,
                        caption=url,
                        reply_to_message_id=message.message_id
                    )
                # Clean up all files from fallback
                for f in files:
                    if os.path.exists(f):
                        os.remove(f)
                log_usage(message.from_user, url, "Video Sent (API fallback)")

        # Cache the sent message for duplicates
        if sent_msg and chat_id not in sent_cache:
            sent_cache[chat_id] = {}
        if sent_msg:
            sent_cache[chat_id][url] = sent_msg.message_id

        bot.delete_message(chat_id, status_msg.message_id)

    except Exception as e:
        error_text = str(e)[:97] + "..." if len(str(e)) > 100 else str(e)
        bot.edit_message_text(f"Failed: {error_text}\nTry again or use /issue", chat_id, status_msg.message_id)
        log_usage(message.from_user, url, f"Error: {error_text}")
        print("ERROR:", e)

# ====================== PHOTO DOWNLOADER (Primary + Fallback) ======================

def download_tiktok_photo(url, base_path):
    files = download_tiktok_photo_scrape(url, base_path)
    if files:
        return files
    print("Primary scrape failed → trying tikwm.com API")
    return download_tiktok_photo_api(url, base_path)

def download_tiktok_photo_scrape(url, base_path):
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        r = requests.get(url, headers=headers, timeout=20)
        r.raise_for_status()
    except:
        return []

    soup = BeautifulSoup(r.text, 'html.parser')
    downloaded = []

    for script in soup.find_all('script'):
        if not script.string:
            continue
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
                if 'tiktokcdn.com' in music_url or music_url.endswith('.mp3'):
                    try:
                        music_data = requests.get(music_url, headers=headers, timeout=15).content
                        music_path = f"{base_path}_music.mp3"
                        with open(music_path, 'wb') as f:
                            f.write(music_data)
                        downloaded.append(music_path)
                    except: pass
    return downloaded

def download_tiktok_photo_api(url, base_path):
    try:
        resp = requests.get("https://tikwm.com/api/", params={'url': url, 'hd': 1}, timeout=20)
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
                music_data = requests.get(music_url, timeout=15).content
                with open(music_path, 'wb') as f:
                    f.write(music_data)
                downloaded.append(music_path)

        return downloaded
    except Exception as e:
        print("Photo API fallback failed:", e)
        return []

# ====================== VIDEO API FALLBACK ======================

def download_video_api_fallback(url, base_path):
    try:
        resp = requests.get("https://tikwm.com/api/", params={'url': url, 'hd': 1}, timeout=20)
        data = resp.json()
        downloaded = []

        if data.get('code') == 0 and 'data' in data:
            video_url = data['data'].get('play')  # No-watermark video
            if video_url:
                video_path = f"{base_path}_video.mp4"
                video_data = requests.get(video_url, timeout=30).content
                with open(video_path, 'wb') as f:
                    f.write(video_data)
                downloaded.append(video_path)

            music_url = data['data'].get('music')
            if music_url:
                music_path = f"{base_path}_music.mp3"
                music_data = requests.get(music_url, timeout=15).content
                with open(music_path, 'wb') as f:
                    f.write(music_data)
                downloaded.append(music_path)

        return downloaded
    except Exception as e:
        print("Video API fallback failed:", e)
        return []

# ====================== START BOT ======================

print("TikTok Downloader Bot is LIVE! (Robust video/photo + anti-spam)")
bot.infinity_polling(none_stop=True)