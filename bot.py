# bot.py
import telebot
import yt_dlp
import os
import uuid
import requests
from bs4 import BeautifulSoup
from urllib.parse import unquote
import zipfile

TOKEN = os.getenv('TOKEN', '7880620831:AAE-pjgq2FU0YNJ7sGakn0GHT9E0DvmQCvc')  # ← REMOVE YOUR REAL TOKEN HERE BEFORE PUSHING!
bot = telebot.TeleBot(TOKEN)

if not os.path.exists('downloads'):
    os.makedirs('downloads')

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(message,
        "TikTok Downloader Bot\n\n"
        "Send any TikTok link (video or photo) → I’ll send it back without watermark!\n"
        "Sensitive / age-restricted videos also work now")

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    url = message.text.strip()
    if "tiktok.com" not in url:
        bot.reply_to(message, "Please send a valid TikTok link!")
        return

    status_msg = bot.reply_to(message, "Analyzing...")

    try:
        unique_id = str(uuid.uuid4())
        temp_path = f"downloads/{unique_id}"

        # PHOTO
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

        # VIDEO (← THIS IS THE ONLY PART THAT CHANGED)
        else:
            bot.edit_message_text("Downloading video (no watermark)...", message.chat.id, status_msg.message_id)
            ydl_opts = {
                'outtmpl': f'{temp_path}.%(ext)s',
                'format': 'bestvideo[height<=720]+bestaudio/best[height<=720]/best',
                'merge_output_format': 'mp4',
                'quiet': True,
                'no_warnings': True,
                # ←←← THESE TWO LINES ARE NEW AND CRITICAL ←←←
                'cookiefile': 'cookies.txt',           # ← loads your cookies
                'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])

            for file in os.listdir('downloads'):
                if file.startswith(unique_id):
                    path = os.path.join('downloads', file)
                    with open(path, 'rb') as video:
                        bot.send_video(message.chat.id, video, caption="Your TikTok video (no watermark)!")
                    os.remove(path)
                    break

        bot.delete_message(message.chat.id, status_msg.message_id)

    except Exception as e:
        bot.reply_to(message, f"Failed: {str(e)}")
        print("ERROR:", e)

# (photo function stays exactly the same — no changes needed)
def download_tiktok_photo(url, base_path):
    # ... (your existing function – copy-paste it unchanged)
    # I’ll skip pasting it here to save space – keep yours
    pass  # ← just keep your original function here

print("Bot started – sensitive videos now work!")
bot.infinity_polling()