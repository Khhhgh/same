import os
import asyncio
import glob
import uuid
import json
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
CONCURRENT_FRAGMENTS = 16
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
    "welcome_message": "أهلاً بك في بوت التحميل الشامل! 🚀\nأرسل رابط من (يوتيوب، انستغرام، تيك توك، بينترست) للتحميل.",
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
            [InlineKeyboardButton("📊 لوحة التحكم والأداة", callback_data="admin_panel")]
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
             InlineKeyboardButton("📢 إرسال اذاعة", callback_data="adm_broadcast")],
            [InlineKeyboardButton("➕ إضافة قناة اشتراك", callback_data="adm_add_ch"),
             InlineKeyboardButton("🗑 حذف قناة اشتراك", callback_data="adm_del_ch")],
            [InlineKeyboardButton("✏️ تغيير رسالة الترحيب", callback_data="adm_set_welcome")],
            [InlineKeyboardButton("🔙 إغلاق اللوحة", callback_data="adm_close")]
        ]
        await query.message.edit_text("مرحباً بك في لوحة التحكم الإدارية:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "adm_stats" and user_id == ADMIN_ID:
        total_users = len(users_data["users"])
        banned_users = len(users_data["banned"])
        channels_count = len(settings_data["channels"])
        
        stats_text = (
            f"📊 **إحصائيات البوت:**\n\n"
            f"👤 عدد المستخدمين: `{total_users}`\n"
            f"🚫 المحظورين: `{banned_users}`\n"
            f"📢 قنوات الاشتراك الإجباري: `{channels_count}`"
        )
        keyboard = [[InlineKeyboardButton("رجوع", callback_data="admin_panel")]]
        await query.message.edit_text(stats_text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "adm_broadcast" and user_id == ADMIN_ID:
        context.user_data["waiting_for_broadcast"] = True
        await query.message.reply_text("أرسل الآن رسالة الإذاعة (نص، صورة، فيديو...) وسيتم إرسالها لجميع المستخدمين:")

    elif data == "adm_set_welcome" and user_id == ADMIN_ID:
        context.user_data["waiting_for_welcome"] = True
        await query.message.reply_text("أرسل النص الجديد لرسالة الترحيب:")

    elif data == "adm_add_ch" and user_id == ADMIN_ID:
        context.user_data["waiting_for_add_channel"] = True
        await query.message.reply_text("أرسل معرف القناة ورابطها بهذا الشكل (افصل بينهم بمسافة):\n`@ChannelUsername https://t.me/...`", parse_mode="Markdown")

    elif data == "adm_del_ch" and user_id == ADMIN_ID:
        channels = settings_data["channels"]
        if not channels:
            await query.answer("لا توجد قنوات مضافة حالياً!", show_alert=True)
            return
        keyboard = []
        for idx, ch in enumerate(channels):
            keyboard.append([InlineKeyboardButton(f"حذف: {ch['id']}", callback_data=f"del_ch_{idx}")])
        keyboard.append([InlineKeyboardButton("رجوع", callback_data="admin_panel")])
        await query.message.edit_text("اختر القناة المراد حذفها:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("del_ch_") and user_id == ADMIN_ID:
        idx = int(data.split("_")[2])
        if idx < len(settings_data["channels"]):
            removed = settings_data["channels"].pop(idx)
            save_json(SETTINGS_FILE, settings_data)
            await query.answer(f"تم حذف القناة {removed['id']} بنجاح!", show_alert=True)
        keyboard = [[InlineKeyboardButton("رجوع", callback_data="admin_panel")]]
        await query.message.edit_text("تم الحذف بنجاح.", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "adm_close":
        await query.message.delete()


# =========================================================
# ADMIN TEXT HANDLERS
# =========================================================
async def handle_admin_steps(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        return False

    if context.user_data.get("waiting_for_welcome"):
        new_welcome = update.message.text
        settings_data["welcome_message"] = new_welcome
        save_json(SETTINGS_FILE, settings_data)
        context.user_data["waiting_for_welcome"] = False
        await update.message.reply_text("✅ تم تحديث رسالة الترحيب بنجاح!")
        return True

    if context.user_data.get("waiting_for_add_channel"):
        parts = update.message.text.strip().split()
        if len(parts) >= 2:
            ch_id = parts[0]
            ch_url = parts[1]
            settings_data["channels"].append({"id": ch_id, "url": ch_url})
            save_json(SETTINGS_FILE, settings_data)
            context.user_data["waiting_for_add_channel"] = False
            await update.message.reply_text(f"✅ تم إضافة القناة {ch_id} بنجاح للاشتراك الإجباري!")
        else:
            await update.message.reply_text("خطأ في التنسيق. أرسل المعرف والرابط مفصولين بمسافة.")
        return True

    if context.user_data.get("waiting_for_broadcast"):
        context.user_data["waiting_for_broadcast"] = False
        users = users_data["users"]
        sent_count = 0
        await update.message.reply_text(f"🚀 جاري بدء الإذاعة إلى {len(users)} مستخدم...")
        
        for uid in users:
            try:
                await update.message.copy(chat_id=uid)
                sent_count += 1
                await asyncio.sleep(0.05)
            except Exception:
                pass
        
        await update.message.reply_text(f"✅ تمت الإذاعة بنجاح إلى `{sent_count}` مستخدم.")
        return True

    return False


# =========================================================
# JOB DIRECTORY & DOWNLOAD
# =========================================================
def create_job_directory(user_id: int):
    job_id = str(user_id) + "_" + uuid.uuid4().hex
    job_dir = os.path.join(DOWNLOAD_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)
    return job_dir

async def download_video(url: str, job_dir: str):
    output = os.path.join(job_dir, "%(id)s.%(ext)s")
    attempt = 0

    while True:
        attempt += 1
        command = [
            "python",
            "-m",
            "yt_dlp",
            "--no-playlist",
            "-f", "b / best",
            "-o", output,
            "--socket-timeout", "30",
            "--retries", "5",
            "--fragment-retries", "5",
            "--no-check-certificates",
            "--geo-bypass",
            "--quiet",
            "--no-warnings",
            url
        ]

        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()

            files = glob.glob(os.path.join(job_dir, "*"))
            valid_files = [
                file for file in files
                if os.path.isfile(file) and os.path.getsize(file) > 0
            ]

            if process.returncode == 0 and valid_files:
                valid_files.sort(key=os.path.getsize, reverse=True)
                return valid_files[0]

        except Exception as e:
            print("YT-DLP EXCEPTION:", repr(e))

        if attempt >= 3:
            return None
        await asyncio.sleep(2)

async def send_video(update: Update, filename: str):
    async with send_semaphore:
        with open(filename, "rb") as video:
            await update.message.reply_video(
                video=video,
                supports_streaming=True,
                read_timeout=180,
                write_timeout=180,
                connect_timeout=30
            )

async def process_job(update: Update, status, url: str):
    job_dir = create_job_directory(update.effective_user.id)
    filename = None

    try:
        async with download_semaphore:
            filename = await download_video(url, job_dir)

        if not filename or not os.path.exists(filename):
            raise Exception("لم يتم العثور على الفيديو أو فشل التحميل من هذا الرابط.")

        try:
            await status.edit_text("تم التحميل، جاري الإرسال...")
        except Exception:
            pass

        await send_video(update, filename)
        try:
            await status.delete()
        except Exception:
            pass

    except Exception as e:
        try:
            await status.edit_text("فشل التحميل:\n" + str(e)[:1500])
        except Exception:
            pass
    finally:
        try:
            if os.path.exists(job_dir):
                for file in glob.glob(os.path.join(job_dir, "*")):
                    try:
                        os.remove(file)
                    except Exception:
                        pass
                try:
                    os.rmdir(job_dir)
                except Exception:
                    pass
        except Exception:
            pass


# =========================================================
# MESSAGE HANDLER
# =========================================================
async def download_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    if await handle_admin_steps(update, context):
        return

    user_id = update.effective_user.id
    
    not_sub = await check_subscription(user_id, context)
    if not_sub:
        keyboard = []
        for ch in not_sub:
            keyboard.append([InlineKeyboardButton("اشترك في القناة 📢", url=ch["url"])])
        keyboard.append([InlineKeyboardButton("تحقق من الاشتراك ✅", callback_data="check_sub")])
        
        await update.message.reply_text(
            "عذراً، يجب عليك الاشتراك في القنوات الإجبارية أولاً لتتمكن من التحميل.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    url = update.message.text.strip()
    if not url.startswith(("http://", "https://")):
        await update.message.reply_text("أرسل رابط صحيح (يوتيوب، انستغرام، تيك توك، بينترست).")
        return

    try:
        status = await update.message.reply_text("جاري معالجة الرابط وتحميل الفيديو...")
    except Exception as e:
        return

    asyncio.create_task(process_job(update, status, url))

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    print("TELEGRAM ERROR:", repr(context.error))


# =========================================================
# MAIN
# =========================================================
def main():
    request = HTTPXRequest(connect_timeout=20, read_timeout=180, write_timeout=180, pool_timeout=180)
    app = Application.builder().token(BOT_TOKEN).request(request).get_updates_request(request).concurrent_updates(100).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(admin_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, download_handler))
    app.add_error_handler(error_handler)

    print("==========================================")
    print("BOT STARTED - ALL PLATFORMS SUPPORTED")
    print("==========================================")

    app.run_polling(drop_pending_updates=True, bootstrap_retries=5)

if __name__ == "__main__":
    main()
