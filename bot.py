import os
import asyncio
import glob
import uuid
import json
import urllib.request
import urllib.parse
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.request import HTTPXRequest
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# =========================================================
# SETTINGS & DATABASE
# =========================================================

BOT_TOKEN = "5183479640:AAE7L00aDWtZrJgGcbDR8EdgIbdX8KhtcpM"
ADMIN_ID = 1310488710

USERS_FILE = "users.json"
SETTINGS_FILE = "settings.json"

MAX_DOWNLOADS = 20
MAX_SENDS = 20
DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

def load_json(filename, default):
    if os.path.exists(filename):
        try:
            with open(filename, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return default

def save_json(filename, data):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

users_data = load_json(USERS_FILE, {"users": [], "banned": []})
settings_data = load_json(SETTINGS_FILE, {
    "welcome_message": "أهلاً بك في البوت المُحدث بنجاح! 🚀\nأرسل رابط (يوتيوب، انستغرام، تيك توك، بينترست) أو أرسل مقطع صوتي لمعرفة الأغنية.",
    "channels": []
})

def add_user(user_id):
    if user_id not in users_data["users"] and user_id not in users_data["banned"]:
        users_data["users"].append(user_id)
        save_json(USERS_FILE, users_data)

download_semaphore = asyncio.Semaphore(MAX_DOWNLOADS)
send_semaphore = asyncio.Semaphore(MAX_SENDS)


# =========================================================
# SUBSCRIPTION CHECK
# =========================================================
async def check_subscription(user_id, context: ContextTypes.DEFAULT_TYPE):
    channels = settings_data.get("channels", [])
    if not channels:
        return []
    
    not_subscribed = []
    for ch in channels:
        ch_id = ch["id"]
        try:
            member = await context.bot.get_chat_member(chat_id=ch_id, user_id=user_id)
            if member.status in ["left", "kicked"]:
                not_subscribed.append(ch)
        except Exception:
            pass
    return not_subscribed


# =========================================================
# START & WELCOME
# =========================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    user_id = update.effective_user.id
    add_user(user_id)

    not_sub = await check_subscription(user_id, context)
    if not_sub:
        keyboard = []
        for ch in not_sub:
            keyboard.append([InlineKeyboardButton("اشترك في القناة 📢", url=ch["url"])])
        keyboard.append([InlineKeyboardButton("تحقق من الاشتراك ✅", callback_data="check_sub")])
        
        await update.message.reply_text(
            "عذراً، يجب عليك الاشتراك في قنوات البوت أولاً لتتمكن من استخدامه.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    welcome_text = settings_data.get("welcome_message", "أهلاً بك في البوت!")
    
    reply_markup = None
    if user_id == ADMIN_ID:
        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("📊 لوحة التحكم والإدارة", callback_data="admin_panel")]
        ])

    await update.message.reply_text(welcome_text, reply_markup=reply_markup)


# =========================================================
# ADMIN PANEL & CALLBACKS
# =========================================================
async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    if data == "check_sub":
        not_sub = await check_subscription(user_id, context)
        if not_sub:
            await query.answer("لم تقم بالاشتراك في جميع القنوات بعد!", show_alert=True)
        else:
            await query.message.delete()
            await query.message.reply_text("شكراً لاشتراكك! يمكنك إرسال الرابط الآن 🚀")

    elif data == "admin_panel" and user_id == ADMIN_ID:
        keyboard = [
            [InlineKeyboardButton("📊 الإحصائيات", callback_data="adm_stats"),
             InlineKeyboardButton("📢 إذاعة", callback_data="adm_broadcast")],
            [InlineKeyboardButton("➕ إضافة قناة", callback_data="adm_add_ch"),
             InlineKeyboardButton("🗑 حذف قناة", callback_data="adm_del_ch")],
            [InlineKeyboardButton("✏️ تغيير الترحيب", callback_data="adm_set_welcome")],
            [InlineKeyboardButton("🔙 إغلاق", callback_data="adm_close")]
        ]
        await query.message.edit_text("لوحة التحكم:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "adm_stats" and user_id == ADMIN_ID:
        total_users = len(users_data["users"])
        banned_users = len(users_data["banned"])
        channels_count = len(settings_data["channels"])
        stats_text = f"📊 المستخدمين: `{total_users}`\n🚫 المحظورين: `{banned_users}`\n📢 القنوات: `{channels_count}`"
        keyboard = [[InlineKeyboardButton("رجوع", callback_data="admin_panel")]]
        await query.message.edit_text(stats_text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "adm_broadcast" and user_id == ADMIN_ID:
        context.user_data["waiting_for_broadcast"] = True
        await query.message.reply_text("أرسل رسالة الإذاعة الآن:")

    elif data == "adm_set_welcome" and user_id == ADMIN_ID:
        context.user_data["waiting_for_welcome"] = True
        await query.message.reply_text("أرسل نص الترحيب الجديد:")

    elif data == "adm_add_ch" and user_id == ADMIN_ID:
        context.user_data["waiting_for_add_channel"] = True
        await query.message.reply_text("أرسل المعرف والرابط مفصولين بمسافة:\n`@ChannelUsername https://t.me/...`", parse_mode="Markdown")

    elif data == "adm_del_ch" and user_id == ADMIN_ID:
        channels = settings_data["channels"]
        if not channels:
            await query.answer("لا توجد قنوات!", show_alert=True)
            return
        keyboard = [[InlineKeyboardButton(f"حذف: {ch['id']}", callback_data=f"del_ch_{idx}")] for idx, ch in enumerate(channels)]
        keyboard.append([InlineKeyboardButton("رجوع", callback_data="admin_panel")])
        await query.message.edit_text("اختر القناة للحذف:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("del_ch_") and user_id == ADMIN_ID:
        idx = int(data.split("_")[2])
        if idx < len(settings_data["channels"]):
            removed = settings_data["channels"].pop(idx)
            save_json(SETTINGS_FILE, settings_data)
            await query.answer(f"تم حذف {removed['id']}", show_alert=True)
        keyboard = [[InlineKeyboardButton("رجوع", callback_data="admin_panel")]]
        await query.message.edit_text("تم الحذف.", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "adm_close":
        await query.message.delete()

    elif data.startswith("dl_"):
        parts = data.split("_")
        mode = parts[1] # video or audio
        url = urllib.parse.unquote("_".join(parts[2:]))
        
        await query.message.edit_text("⏳ جاري التحميل والمعالجة...")
        await process_download_task(query.message, url, mode)


# =========================================================
# ADMIN TEXT STEPS
# =========================================================
async def handle_admin_steps(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        return False

    if context.user_data.get("waiting_for_welcome"):
        settings_data["welcome_message"] = update.message.text
        save_json(SETTINGS_FILE, settings_data)
        context.user_data["waiting_for_welcome"] = False
        await update.message.reply_text("✅ تم التحديث!")
        return True

    if context.user_data.get("waiting_for_add_channel"):
        parts = update.message.text.strip().split()
        if len(parts) >= 2:
            settings_data["channels"].append({"id": parts[0], "url": parts[1]})
            save_json(SETTINGS_FILE, settings_data)
            context.user_data["waiting_for_add_channel"] = False
            await update.message.reply_text("✅ تم إضافة القناة!")
        else:
            await update.message.reply_text("خطأ في التنسيق.")
        return True

    if context.user_data.get("waiting_for_broadcast"):
        context.user_data["waiting_for_broadcast"] = False
        sent = 0
        for uid in users_data["users"]:
            try:
                await update.message.copy(chat_id=uid)
                sent += 1
                await asyncio.sleep(0.04)
            except:
                pass
        await update.message.reply_text(f"✅ تمت الإذاعة إلى `{sent}` مستخدم.")
        return True

    return False


# =========================================================
# DOWNLOAD CORE (YT-DLP) WITH TIKTOK & YOUTUBE FIX
# =========================================================
def create_job_directory(user_id: int):
    job_id = str(user_id) + "_" + uuid.uuid4().hex
    job_dir = os.path.join(DOWNLOAD_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)
    return job_dir

async def download_media(url: str, job_dir: str, mode: str = "video"):
    output = os.path.join(job_dir, "%(id)s.%(ext)s")
    
    base_command = [
        "python", "-m", "yt_dlp",
        "--no-playlist",
        "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "-o", output,
        "--no-check-certificates", "--geo-bypass", "--no-warnings"
    ]
    
    if "youtube.com" in url or "youtu.be" in url:
        base_command.extend(["--extractor-args", "youtube:player_client=android"])
    
    if mode == "audio":
        command = base_command + [
            "-x", "--audio-format", "mp3", "--audio-quality", "0",
            url
        ]
    else:
        command = base_command + [
            "-f", "best/bestvideo+bestaudio",
            "--merge-output-format", "mp4",
            url
        ]

    try:
        process = await asyncio.create_subprocess_exec(
            *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            print("YT-DLP ERROR:", stderr.decode("utf-8", errors="ignore"))

        files = glob.glob(os.path.join(job_dir, "*"))
        valid_files = [f for f in files if os.path.isfile(f) and os.path.getsize(f) > 0]

        if process.returncode == 0 and valid_files:
            valid_files.sort(key=os.path.getsize, reverse=True)
            return valid_files[0]
    except Exception as e:
        print("DOWNLOAD EXCEPTION:", repr(e))
    return None

async def process_download_task(message, url: str, mode: str):
    job_dir = create_job_directory(message.chat.id)
    try:
        async with download_semaphore:
            filename = await download_media(url, job_dir, mode)

        if not filename or not os.path.exists(filename):
            await message.edit_text("❌ عذراً، فشل التحميل من هذا الرابط.")
            return

        await message.edit_text("📤 جاري إرسال الملف...")
        async with send_semaphore:
            with open(filename, "rb") as f:
                if mode == "audio":
                    await message.reply_audio(audio=f)
                else:
                    await message.reply_video(video=f, supports_streaming=True)
        await message.delete()
    except Exception as e:
        try:
            await message.edit_text(f"❌ حدث خطأ: {str(e)[:100]}", parse_mode="Markdown")
        except:
            pass
    finally:
        if os.path.exists(job_dir):
            for f in glob.glob(os.path.join(job_dir, "*")):
                try: os.remove(f)
                except: pass
            try: os.rmdir(job_dir)
            except: pass


# =========================================================
# MUSIC RECOGNITION (AudD Free API)
# =========================================================
async def recognize_song(file_path: str):
    try:
        with open(file_path, "rb") as f:
            audio_data = f.read()
        
        data = {
            'api_token': 'test',
            'return': 'apple_music,spotify',
        }
        files = {
            'file': audio_data,
        }
        
        loop = asyncio.get_running_loop()
        def req():
            import requests
            return requests.post('https://api.audd.io/', data=data, files=files, timeout=15)
        
        response = await loop.run_in_executor(None, req)
        result = response.json()
        
        if result.get("status") == "success" and result.get("result"):
            res = result["result"]
            title = res.get("title", "غير معروف")
            artist = res.get("artist", "غير معروف")
            album = res.get("album", "غير معروف")
            spotify_url = res.get("spotify", {}).get("external_urls", {}).get("spotify", "")
            
            text = f"🎵 **تم العثور على الأغنية بنجاح!**\n\n" \
                   f"📌 **اسم الأغنية:** `{title}`\n" \
                   f"🎤 **المطرب/الفنان:** `{artist}`\n" \
                   f"💿 **الألبوم:** `{album}`"
            if spotify_url:
                text += f"\n🔗 [استمع على سبوتيفاي]({spotify_url})"
            return text
    except Exception as e:
        print("RECOGNITION ERROR:", repr(e))
    return None


# =========================================================
# MESSAGE HANDLERS
# =========================================================
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    if await handle_admin_steps(update, context):
        return

    user_id = update.effective_user.id
    
    not_sub = await check_subscription(user_id, context)
    if not_sub:
        keyboard = [[InlineKeyboardButton("اشترك في القناة 📢", url=ch["url"])] for ch in not_sub]
        keyboard.append([InlineKeyboardButton("تحقق من الاشتراك ✅", callback_data="check_sub")])
        await update.message.reply_text("عذراً، اشترك في القنوات أولاً.", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if update.message.text and update.message.text.strip().startswith(("http://", "https://")):
        url = update.message.text.strip()
        
        if "youtube.com" in url or "youtu.be" in url:
            encoded_url = urllib.parse.quote(url, safe="")
            keyboard = [
                [
                    InlineKeyboardButton("🎬 تحميل فيديو", callback_data=f"dl_video_{encoded_url}"),
                    InlineKeyboardButton("🎵 تحميل صوت MP3", callback_data=f"dl_audio_{encoded_url}")
                ]
            ]
            await update.message.reply_text("اختر طريقة التحميل المطلوبة ليوتيوب:", reply_markup=InlineKeyboardMarkup(keyboard))
            return
        
        status = await update.message.reply_text("⏳ جاري التحميل والمعالجة...")
        asyncio.create_task(process_download_task(status, url, "video"))
        return

    audio_file = update.message.audio or update.message.voice or update.message.video or update.message.document
    if audio_file:
        status = await update.message.reply_text("🎧 جاري الاستماع للتعرف على الأغنية...")
        job_dir = create_job_directory(user_id)
        try:
            file_obj = await context.bot.get_file(audio_file.file_id)
            input_path = os.path.join(job_dir, "input_media")
            await file_obj.download_to_drive(input_path)
            
            song_info = await recognize_song(input_path)
            if song_info:
                await status.edit_text(song_info, parse_mode="Markdown")
            else:
                await status.edit_text("❌ لم يتم التعرف على الأغنية، تأكد من وضوح المقطع الصوتي.")
        except Exception as e:
            await status.edit_text("❌ حدث خطأ أثناء تحليل الملف الصوتي.")
        finally:
            if os.path.exists(job_dir):
                for f in glob.glob(os.path.join(job_dir, "*")):
                    try: os.remove(f)
                    except: pass
                try: os.rmdir(job_dir)
                except: pass
        return

    if update.message.text:
        await update.message.reply_text("أرسل رابط صحيح (يوتيوب، انستغرام، تيك توك، بينترست) أو أرسل مقطعاً صوتياً للبحث عن الأغنية.")


# =========================================================
# MAIN
# =========================================================
def main():
    request = HTTPXRequest(connect_timeout=20, read_timeout=180, write_timeout=180, pool_timeout=180)
    app = Application.builder().token(BOT_TOKEN).request(request).get_updates_request(request).concurrent_updates(100).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(admin_callback))
    app.add_handler(MessageHandler(filters.TEXT | filters.AUDIO | filters.VOICE | filters.VIDEO | filters.DOCUMENT, message_handler))

    print("==========================================")
    print("BOT STARTED WITH UPDATED TIKTOK SUPPORT")
    print("==========================================")

    app.run_polling(drop_pending_updates=True, bootstrap_retries=5)

if __name__ == "__main__":
    main()
