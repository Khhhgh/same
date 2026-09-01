import os
import asyncio
import glob
import uuid

from telegram import Update
from telegram.request import HTTPXRequest
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)


# =========================================================
# SETTINGS
# =========================================================

BOT_TOKEN = "5183479640:AAE7L00aDWtZrJgGcbDR8EdgIbdX8KhtcpM"

# عدد عمليات التحميل المستقلة في نفس الوقت
MAX_DOWNLOADS = 20

# عدد عمليات إرسال الفيديو في نفس الوقت
MAX_SENDS = 20

# أجزاء التحميل المتزامنة لكل فيديو
CONCURRENT_FRAGMENTS = 16

DOWNLOAD_DIR = "downloads"

os.makedirs(
    DOWNLOAD_DIR,
    exist_ok=True
)


# =========================================================
# SEMAPHORES
# =========================================================

download_semaphore = asyncio.Semaphore(
    MAX_DOWNLOADS
)

send_semaphore = asyncio.Semaphore(
    MAX_SENDS
)


# =========================================================
# START
# =========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.message:
        return

    try:

        await update.message.reply_text(
            "أرسل رابط الفيديو."
        )

    except Exception as e:

        print(
            "START ERROR:",
            repr(e)
        )


# =========================================================
# UNIQUE JOB DIRECTORY
# =========================================================

def create_job_directory(
    user_id: int
):

    job_id = (
        str(user_id)
        + "_"
        + uuid.uuid4().hex
    )

    job_dir = os.path.join(
        DOWNLOAD_DIR,
        job_id
    )

    os.makedirs(
        job_dir,
        exist_ok=True
    )

    return job_dir


# =========================================================
# DOWNLOAD WITH YT-DLP
# =========================================================

async def download_video(
    url: str,
    job_dir: str
):

    output = os.path.join(
        job_dir,
        "%(id)s.%(ext)s"
    )

    attempt = 0

    while True:

        attempt += 1

        print(
            "=========================================="
        )

        print(
            "DOWNLOAD START"
        )

        print(
            "Attempt:",
            attempt
        )

        print(
            "URL:",
            url
        )

        print(
            "=========================================="
        )

        command = [

            "python3",

            "-m",

            "yt_dlp",

            # -----------------------------------------
            # منع Playlist
            # -----------------------------------------

            "--no-playlist",

            # -----------------------------------------
            # أفضل صيغة MP4
            # -----------------------------------------

            "-f",
            "best[ext=mp4]/best",

            # -----------------------------------------
            # اسم الملف
            # -----------------------------------------

            "-o",
            output,

            # -----------------------------------------
            # تحميل أجزاء متعددة
            # -----------------------------------------

            "--concurrent-fragments",
            str(CONCURRENT_FRAGMENTS),

            # -----------------------------------------
            # Buffer أكبر
            # -----------------------------------------

            "--buffer-size",
            "1M",

            # -----------------------------------------
            # الشبكة
            # -----------------------------------------

            "--socket-timeout",
            "15",

            # -----------------------------------------
            # إعادة المحاولة الداخلية
            # -----------------------------------------

            "--retries",
            "2",

            "--fragment-retries",
            "2",

            # -----------------------------------------
            # تقليل المخرجات
            # -----------------------------------------

            "--quiet",

            "--no-warnings",

            # -----------------------------------------
            # الرابط
            # -----------------------------------------

            url
        ]

        try:

            process = (
                await asyncio.create_subprocess_exec(

                    *command,

                    stdout=(
                        asyncio.subprocess.PIPE
                    ),

                    stderr=(
                        asyncio.subprocess.PIPE
                    )
                )
            )

            stdout, stderr = (
                await process.communicate()
            )

            # -----------------------------------------
            # البحث عن الملف
            # -----------------------------------------

            files = glob.glob(
                os.path.join(
                    job_dir,
                    "*"
                )
            )

            valid_files = [

                file

                for file in files

                if os.path.isfile(file)

                and os.path.getsize(file) > 0
            ]

            # -----------------------------------------
            # نجاح
            # -----------------------------------------

            if (
                process.returncode == 0
                and valid_files
            ):

                valid_files.sort(
                    key=os.path.getsize,
                    reverse=True
                )

                filename = valid_files[0]

                print(
                    "DOWNLOAD SUCCESS:"
                )

                print(
                    filename
                )

                return filename

            # -----------------------------------------
            # الخطأ
            # -----------------------------------------

            error = stderr.decode(
                "utf-8",
                errors="ignore"
            )

            if not error:

                error = stdout.decode(
                    "utf-8",
                    errors="ignore"
                )

            print(
                "YT-DLP ERROR:"
            )

            print(
                error[-2000:]
            )

        except Exception as e:

            print(
                "YT-DLP EXCEPTION:",
                repr(e)
            )

        # -----------------------------------------
        # تنظيف الملفات
        # -----------------------------------------

        try:

            for file in glob.glob(
                os.path.join(
                    job_dir,
                    "*"
                )
            ):

                if os.path.isfile(file):

                    try:

                        os.remove(file)

                    except Exception:

                        pass

        except Exception:

            pass

        # -----------------------------------------
        # إعادة المحاولة
        # -----------------------------------------

        print(
            "Retrying in 2 seconds..."
        )

        await asyncio.sleep(
            2
        )


# =========================================================
# SEND VIDEO
# =========================================================

async def send_video(
    update: Update,
    filename: str
):

    async with send_semaphore:

        print(
            "SEND START:"
        )

        print(
            filename
        )

        with open(
            filename,
            "rb"
        ) as video:

            await update.message.reply_video(

                video=video,

                supports_streaming=True,

                read_timeout=180,

                write_timeout=180,

                connect_timeout=30
            )

        print(
            "SEND COMPLETE:"
        )

        print(
            filename
        )


# =========================================================
# PROCESS ONE JOB
# =========================================================

async def process_job(
    update: Update,
    status,
    url: str
):

    job_dir = create_job_directory(
        update.effective_user.id
    )

    filename = None

    try:

        # =================================================
        # كل رابط يحصل على عملية مستقلة
        # =================================================

        async with download_semaphore:

            print(
                "JOB START:"
            )

            print(
                url
            )

            filename = await download_video(
                url,
                job_dir
            )

        if not filename:

            raise Exception(
                "لم يتم العثور على الفيديو."
            )

        if not os.path.exists(
            filename
        ):

            raise Exception(
                "ملف الفيديو غير موجود."
            )

        # =================================================
        # تحديث الحالة
        # =================================================

        try:

            await status.edit_text(
                "تم التحميل، جاري الإرسال..."
            )

        except Exception:

            pass

        # =================================================
        # إرسال مستقل
        # =================================================

        await send_video(
            update,
            filename
        )

        # =================================================
        # حذف الحالة
        # =================================================

        try:

            await status.delete()

        except Exception:

            pass

    except Exception as e:

        print(
            "JOB ERROR:"
        )

        print(
            repr(e)
        )

        try:

            await status.edit_text(
                "فشل التحميل:\n"
                + str(e)[:1500]
            )

        except Exception:

            pass

    finally:

        # =================================================
        # تنظيف ملفات المهمة
        # =================================================

        try:

            if os.path.exists(
                job_dir
            ):

                for file in glob.glob(
                    os.path.join(
                        job_dir,
                        "*"
                    )
                ):

                    try:

                        os.remove(
                            file
                        )

                    except Exception:

                        pass

                try:

                    os.rmdir(
                        job_dir
                    )

                except Exception:

                    pass

        except Exception:

            pass


# =========================================================
# RECEIVE URL
# =========================================================

async def download_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.message:
        return

    if not update.message.text:
        return

    url = update.message.text.strip()

    # -----------------------------------------
    # التحقق من الرابط
    # -----------------------------------------

    if not url.startswith(
        (
            "http://",
            "https://"
        )
    ):

        await update.message.reply_text(
            "أرسل رابط صحيح."
        )

        return

    # -----------------------------------------
    # الرد فورًا
    # -----------------------------------------

    try:

        status = await update.message.reply_text(
            "جاري معالجة الرابط..."
        )

    except Exception as e:

        print(
            "STATUS ERROR:",
            repr(e)
        )

        return

    # =================================================
    # كل رابط يصبح Task مستقل فورًا
    # =================================================

    asyncio.create_task(

        process_job(

            update,

            status,

            url
        )
    )


# =========================================================
# ERROR HANDLER
# =========================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE
):

    print(
        "TELEGRAM ERROR:"
    )

    print(
        repr(context.error)
    )


# =========================================================
# MAIN
# =========================================================

def main():

    if (
        BOT_TOKEN
        == "ضع_التوكن_الجديد_هنا"
    ):

        print(
            "ضع توكن البوت الجديد داخل BOT_TOKEN"
        )

        return

    # =====================================================
    # Telegram HTTP
    # =====================================================

    request = HTTPXRequest(

        connect_timeout=20,

        read_timeout=180,

        write_timeout=180,

        pool_timeout=180
    )

    # =====================================================
    # APPLICATION
    # =====================================================

    app = (

        Application.builder()

        .token(
            BOT_TOKEN
        )

        .request(
            request
        )

        .get_updates_request(
            request
        )

        # استقبال تحديثات كثيرة بدون انتظار
        .concurrent_updates(
            100
        )

        .build()
    )

    # =====================================================
    # HANDLERS
    # =====================================================

    app.add_handler(

        CommandHandler(
            "start",
            start
        )
    )

    app.add_handler(

        MessageHandler(

            filters.TEXT
            & ~filters.COMMAND,

            download_handler
        )
    )

    app.add_error_handler(
        error_handler
    )

    # =====================================================
    # START
    # =====================================================

    print(
        "=========================================="
    )

    print(
        "BOT STARTED"
    )

    print(
        "Download workers:",
        MAX_DOWNLOADS
    )

    print(
        "Send workers:",
        MAX_SENDS
    )

    print(
        "Concurrent fragments:",
        CONCURRENT_FRAGMENTS
    )

    print(
        "Independent tasks: ON"
    )

    print(
        "Automatic retry: ON"
    )

    print(
        "=========================================="
    )

    app.run_polling(

        drop_pending_updates=True,

        bootstrap_retries=5
    )


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    main()
