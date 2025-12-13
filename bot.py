# bot.py - All-in-One TikTok + Instagram Downloader Bot
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
        sheet = gc.open("TiktokData").sheet1  # You can rename sheet to "SocialMediaData" if you want

        headers = ["Timestamp", "User ID", "Username", "First Name", "Link", "Platform", "Type", "Status"]
        current_headers = sheet.row_values(1)
        if not current_headers or current_headers != headers:
            sheet.clear()
            sheet.append_row(headers)
            print("Google Sheet headers updated!")

        logging_enabled = True
        print("Google Sheets logging ENABLED")
    except Exception as e:
        print("Google Sheets setup FAILED:", str(e))
else:
    print("No GOOGLE_CREDENTIALS → logging disabled")

def log_usage(user, url, platform="TikTok", media_type="Video", status="Success"):
    if not logging_enabled:
        return
    try:
        row = [
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            user.id,
            user.username or "None",
            user.first_name or "",
            url,
            platform,
            media_type,
            status
        ]
        sheet.append_row(row)
    except Exception as e:
        print("Sheet write error:", e)

# Temporary folder
os.makedirs('downloads', exist_ok=True)

# Duplicate cache: {chat_id: {url: sent_message_id}}
sent_cache = {}

# ====================== COMMANDS ======================

@bot.message_handler(commands=['start'])
def cmd_start(message):
    bot.reply_to(message, 
        "🔥 All-in-One Downloader Bot 🔥\n\n"
        "Send me any link from:\n"
        "• TikTok (videos & photo slideshows)\n"
        "• Instagram (Reels, Posts, Stories)\n\n"
        "I’ll send it back without watermark! 😎")

@bot.message_handler(commands=['help'])
def cmd_help(message):
    help_text = (
        "Supported Platforms:\n\n"
        "✅ TikTok – Videos & Photo Slideshows\n"
        "✅ Instagram – Reels, Posts, IGTV, Stories\n\n"
        "Commands:\n"
        "/start – Welcome message\n"
        "/help  – This help\n"
        "/issue – Contact developer\n\n"
        "Just paste a link and wait!"
    )
    bot.reply_to(message, help_text)

@bot.message_handler(commands=['issue'])
def cmd_issue(message):
    bot.reply_to(message, "For issues or suggestions, contact the developer: @mnchetra")

# ====================== MAIN HANDLER ======================

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    url = message.text.strip()

    if "tiktok.com" not in url and "instagram.com" not in url:
        bot.reply_to(message, "❌ Please send a valid TikTok or Instagram link!")
        return

    platform = "TikTok" if "tiktok.com" in url else "Instagram"

    chat_id = message.chat.id

    # Anti-duplicate
    if chat_id in sent_cache and url in sent_cache[chat_id]:
        prev_msg_id = sent_cache[chat_id][url]
        bot.reply_to(message, "You already downloaded this one! 👇", reply_to_message_id=prev_msg_id)
        log_usage(message.from_user, url, platform, "Video/Photo", "Duplicate")
        return

    log_usage(message.from_user, url, platform, "Unknown", "Received")
    status_msg = bot.reply_to(message, "⬇️ Downloading your content... Please wait.")

    try:
        unique_id = str(uuid.uuid4())
        temp_path = f"downloads/{unique_id}"

        # Special case: TikTok Photo Slideshow
        if "tiktok.com" in url and "/photo/" in url:
            bot.edit_message_text("📸 Downloading photo slideshow...", chat_id, status_msg.message_id)
            files = download_tiktok_photo(url, temp_path)

            if not files:
                raise Exception("No photos found")

            zip_path = f"{temp_path}.zip"
            with zipfile.ZipFile(zip_path, 'w') as zf:
                for f in files:
                    zf.write(f, arcname=os.path.basename(f))
                    os.remove(f)

            with open(zip_path, 'rb') as z:
                sent_msg = bot.send_document(chat_id, z, caption=url, reply_to_message_id=message.message_id)
            os.remove(zip_path)
            log_usage(message.from_user, url, "TikTok", "Photo", "Sent")
        else:
            # Universal video downloader for TikTok + Instagram
            bot.edit_message_text("🎞️ Downloading video (no watermark)...", chat_id, status_msg.message_id)

            ydl_opts = {
                'outtmpl': f'{temp_path}.%(ext)s',
                'format': 'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
                'merge_output_format': 'mp4',
                'quiet': True,
                'cookiefile': 'cookies.txt',  # Optional: helps with private/sensitive content
                'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36',
                'referer': 'https://www.instagram.com/' if 'instagram' in url else 'https://www.tiktok.com/',
            }

            # Try primary yt-dlp
            success = False
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([url])
                success = True
            except Exception as e:
                print(f"yt-dlp failed for {url}: {e}")

            if success:
                # Find and send downloaded file
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
                        media_type = "Video"
                        log_usage(message.from_user, url, platform, media_type, "Sent (yt-dlp)")
                        break
                else:
                    raise Exception("File not found after download")
            else:
                # Fallback to tikwm.com API (works great for TikTok, limited for Instagram)
                if "tiktok.com" in url:
                    print("Trying tikwm API fallback...")
                    files = download_video_api_fallback(url, temp_path)
                    if files and files[0].endswith('.mp4'):
                        with open(files[0], 'rb') as video_file:
                            sent_msg = bot.send_video(chat_id, video_file, caption=url, reply_to_message_id=message.message_id)
                        for f in files:
                            if os.path.exists(f): os.remove(f)
                        log_usage(message.from_user, url, "TikTok", "Video", "Sent (API)")
                    else:
                        raise Exception("Both yt-dlp and API failed")
                else:
                    raise Exception("Instagram download failed (try public links or fresh cookies)")

        # Cache for anti-spam
        if chat_id not in sent_cache:
            sent_cache[chat_id] = {}
        sent_cache[chat_id][url] = sent_msg.message_id

        bot.delete_message(chat_id, status_msg.message_id)

    except Exception as e:
        error_text = str(e)[:97] + "..." if len(str(e)) > 100 else str(e)
        bot.edit_message_text(f"❌ Failed: {error_text}\nTry again or /issue", chat_id, status_msg.message_id)
        log_usage(message.from_user, url, platform, "Error", f"Failed: {error_text}")
        print("ERROR:", e)

# ====================== TIKTOK PHOTO DOWNLOADER (Scrape + API Fallback) ======================
# (Same as before – keeping it for photo slideshows)
def download_tiktok_photo(url, base_path):
    files = download_tiktok_photo_scrape(url, base_path)
    if files:
        return files
    print("Photo scrape failed → trying API")
    return download_tiktok_photo_api(url, base_path)

def download_tiktok_photo_scrape(url, base_path):
    # ... (same as previous version – omitted for brevity, but include it)
    # You can copy from your previous code
    return []  # placeholder

def download_tiktok_photo_api(url, base_path):
    # ... (same API version)
    return []  # placeholder

def download_video_api_fallback(url, base_path):
    # ... (same as previous)
    return []  # placeholder

# ====================== START BOT ======================

print("All-in-One TikTok + Instagram Downloader Bot is LIVE!")
bot.infinity_polling(none_stop=True)