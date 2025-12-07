# bot.py
import telebot
import yt_dlp
import os
import uuid
import requests
from bs4 import BeautifulSoup
from urllib.parse import unquote
import zipfile

# === PUT YOUR TOKEN HERE OR USE ENVIRONMENT VARIABLE (Railway) ===
TOKEN = os.getenv('TOKEN', '7880620831:AAE-pjgq2FU0YNJ7sGakn0GHT9E0DvmQCvc')  # Remove hardcoded token for security!
bot = telebot.TeleBot(TOKEN)

# Temporary folder
if not os.path.exists('downloads'):
    os.makedirs('downloads')

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(message,
        "TikTok Downloader Bot (Video + Photo)\n\n"
        "Just send any TikTok link:\n"
        "• Video → gets MP4 (no watermark)\n"
        "• Photo/Slideshow → gets ZIP with images + music\n\n"
        "Example:\n"
        "https://www.tiktok.com/@username/video/123456789\n"
        "https://www.tiktok.com/@username/photo/123456789")

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    url = message.text.strip()
    if "tiktok.com" not in url:
        bot.reply_to(message, "Please send a valid TikTok link!")
        return

    status_msg = bot.reply_to(message, "Analyzing link...")

    try:
        unique_id = str(uuid.uuid4())
        temp_path = f"downloads/{unique_id}"

        # PHOTO / SLIDESHOW
        if "/photo/" in url:
            bot.edit_message_text("Downloading photo(s)...", message.chat.id, status_msg.message_id)
            files = download_tiktok_photo(url, temp_path)
            if not files:
                raise Exception("No images/music found")

            zip_path = f"{temp_path}.zip"
            with zipfile.ZipFile(zip_path, 'w') as zf:
                for f in files:
                    zf.write(f, arcname=os.path.basename(f))
                    os.remove(f)  # clean individual files

            with open(zip_path, 'rb') as zip_file:
                bot.send_document(message.chat.id, zip_file,
                                  caption="Here are your TikTok photos + music!")
            os.remove(zip_path)

        # VIDEO
        else:
            bot.edit_message_text("Downloading video (no watermark)...", message.chat.id, status_msg.message_id)
            ydl_opts = {
                'outtmpl': f'{temp_path}.%(ext)s',
                'format': 'bestvideo[height<=720]+bestaudio/best[height<=720]/best',  # Never fails
                'merge_output_format': 'mp4',
                'quiet': True,
                'no_warnings': True,
                # NEW: Cookie support for sensitive videos
                'cookiefile': 'cookies.txt',  # Path to your exported cookies file
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])

            # Find the downloaded file
            for file in os.listdir('downloads'):
                if file.startswith(unique_id):
                    file_path = os.path.join('downloads', file)
                    with open(file_path, 'rb') as video:
                        bot.send_video(message.chat.id, video,
                                       caption="Your TikTok video (no watermark)!")
                    os.remove(file_path)
                    break

        bot.delete_message(message.chat.id, status_msg.message_id)

    except Exception as e:
        bot.reply_to(message, f"Failed to download.\nError: {str(e)}\n\n💡 If sensitive content, ensure cookies.txt is set up!")
        print("ERROR:", e)

# ==================== PHOTO DOWNLOADER ====================
def download_tiktok_photo(url, base_path):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    try:
        r = requests.get(url, headers=headers, timeout=15)
        r.raise_for_status()
    except:
        return []

    soup = BeautifulSoup(r.text, 'html.parser')
    downloaded = []

    # Find image URLs (TikTok hides them in script tags)
    for script in soup.find_all('script'):
        if not script.string:
            continue
        txt = script.string
        pos = 0
        while True:
            pos = txt.find('https://', pos)
            if pos == -1:
                break
            end = txt.find('"', pos)
            if end == -1:
                break
            img_url = unquote(txt[pos:end])
            if ('p16-sign' in img_url or 'p26-sign' in img_url) and img_url.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
                try:
                    img_data = requests.get(img_url, headers=headers, timeout=15).content
                    img_path = f"{base_path}_{len(downloaded)}.jpg"
                    with open(img_path, 'wb') as f:
                        f.write(img_data)
                    downloaded.append(img_path)
                except:
                    pass
            pos = end

        # Music (optional)
        if 'playUrl' in txt or 'music' in txt.lower():
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
                    except:
                        pass

    return downloaded

# ==================== START BOT ====================
print("TikTok Downloader Bot is running...")
bot.infinity_polling()