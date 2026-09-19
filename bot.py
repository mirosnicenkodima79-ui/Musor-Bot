import asyncio
import logging
import os
import json
import time
import subprocess
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart
from aiogram.types import (
    FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery,
    LabeledPrice, PreCheckoutQuery, Message
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiohttp import web

TOKEN = "8932719806:AAFXhInm6CH7b7RtrvGh8bzelU2XwGvrL7M"
ADMIN_ID = 8388465814
MUSOR_PATH = "MUSOR.MOV" if os.path.exists("MUSOR.MOV") else r"C:\Users\miros\Downloads\Screenshots\MUSOR.MOV"
PHOTO_PATH = "MUSOR DRIO.jpg" if os.path.exists("MUSOR DRIO.jpg") else r"C:\Users\miros\Downloads\Screenshots\MUSOR DRIO.jpg"

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher()

os.makedirs("downloads", exist_ok=True)
os.makedirs("output", exist_ok=True)

user_sessions = {}
user_cooldowns = {}
processing_lock = asyncio.Lock()
paid_users = {ADMIN_ID}
USERS_FILE = "users.json"

def load_users():
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except:
            return set()
    return set()

def save_users(users_set):
    try:
        with open(USERS_FILE, "w", encoding="utf-8") as f:
            json.dump(list(users_set), f)
    except:
        pass

known_users = load_users()

class BroadcastState(StatesGroup):
    waiting_for_message = State()

def process_video_pause(user_video_path, output_path, speed, user_id, no_watermark):
    res_d = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", user_video_path
    ], stdout=subprocess.PIPE, text=True, timeout=30)
    try:
        duration = float(res_d.stdout.strip())
    except ValueError:
        duration = 10.0

    if duration > 60.0:
        raise ValueError("TOO_LONG")

    res_ad_d = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", MUSOR_PATH
    ], stdout=subprocess.PIPE, text=True, timeout=30)
    try:
        orig_ad_duration = float(res_ad_d.stdout.strip())
    except ValueError:
        orig_ad_duration = 5.9

    ad_duration = orig_ad_duration / speed
    half = duration / 2.0

    audio_probe = subprocess.run([
        "ffprobe", "-v", "error", "-select_streams", "a",
        "-show_entries", "stream=index", "-of", "csv=p=0", user_video_path
    ], stdout=subprocess.PIPE, text=True, timeout=30)
    has_audio = bool(audio_probe.stdout.strip())

    wm = "" if no_watermark else r",drawtext=text='@videomusordropbot':x=(W-tw)/2:y=H-th-25:fontsize=28:fontcolor=white@0.7:box=1:boxcolor=black@0.3"

    h = f"{half:.3f}"
    dur = f"{duration:.3f}"
    ad = f"{ad_duration:.3f}"
    sp = f"{speed:.2f}".rstrip("0").rstrip(".")

    fc = (
        f"[0:v]split=3[vs1][vs2][vs3];"
        f"[vs1]trim=0:{h},setpts=PTS-STARTPTS{wm}[v1];"
        f"[vs2]trim={h}:{dur},setpts=PTS-STARTPTS{wm}[v2];"
        f"[vs3]trim=start={h},setpts=PTS-STARTPTS,select='eq(n,0)',loop=loop=-1:size=1,trim=duration={ad},setpts=PTS-STARTPTS,setsar=1[frz];"
        f"[1:v]scale='iw*0.55:ih*0.55',setsar=1[adw];"
        f"[frz][adw]overlay=x=(W-w)/2:y=(H-h)/2{wm}[v3];"
    )
    if has_audio:
        fc += (
            f"[0:a]asplit=2[as1][as2];"
            f"[as1]atrim=0:{h},asetpts=PTS-STARTPTS[a1];"
            f"[as2]atrim={h}:{dur},asetpts=PTS-STARTPTS[a2];"
            f"[1:a]atempo={sp}[ada];"
            f"[a1][ada][a2]concat=n=3:v=0:a=1[aout];"
        )
    fc += f"[v1][v3][v2]concat=n=3:v=1:a=0[vout]"

    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", user_video_path, "-i", MUSOR_PATH,
        "-filter_complex", fc,
        "-map", "[vout]"
    ]
    if has_audio:
        cmd += ["-map", "[aout]"]
    cmd += [
        "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency", "-threads", "0", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        "-y", output_path
    ]

    subprocess.run(cmd, check=True, timeout=120)

def process_video_overlay(user_video_path, output_path, speed, user_id, no_watermark):
    # Mode 2 is a single fast pass (~2-3 seconds!)
    res_d = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", user_video_path
    ], stdout=subprocess.PIPE, text=True, timeout=30)
    try:
        duration = float(res_d.stdout.strip())
    except ValueError:
        duration = 10.0

    if duration > 60.0:
        raise ValueError("TOO_LONG")

    res_ad_d = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", MUSOR_PATH
    ], stdout=subprocess.PIPE, text=True, timeout=30)
    try:
        orig_ad_duration = float(res_ad_d.stdout.strip())
    except ValueError:
        orig_ad_duration = 5.9

    ad_duration = orig_ad_duration / speed
    start_time = max(0.0, (duration - ad_duration) / 2)
    end_time = start_time + ad_duration

    audio_probe = subprocess.run([
        "ffprobe", "-v", "error", "-select_streams", "a",
        "-show_entries", "stream=index", "-of", "csv=p=0", user_video_path
    ], stdout=subprocess.PIPE, text=True, timeout=30)
    has_audio = bool(audio_probe.stdout.strip())

    wm = "" if no_watermark else r",drawtext=text='@videomusordropbot':x=(W-tw)/2:y=H-th-25:fontsize=28:fontcolor=white@0.7:box=1:boxcolor=black@0.3"
    if not has_audio:
        if speed == 1.0:
            filter_complex = (
                f"[1:v]scale='iw*0.55:ih*0.55',setsar=1[ad_v];"
                f"[0:v][ad_v]overlay=x=(W-w)/2:y=(H-h)/2:enable='between(t,{start_time},{end_time})'{wm}[outv]"
            )
        else:
            filter_complex = (
                f"[1:v]setpts=PTS/{speed},scale='iw*0.55:ih*0.55',setsar=1[ad_v];"
                f"[0:v][ad_v]overlay=x=(W-w)/2:y=(H-h)/2:enable='between(t,{start_time},{end_time})'{wm}[outv]"
            )
        subprocess.run([
            "ffmpeg", "-i", user_video_path, "-i", MUSOR_PATH,
            "-filter_complex", filter_complex,
            "-map", "[outv]",
            "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency", "-threads", "0", "-crf", "23",
            "-movflags", "+faststart",
            "-y", output_path
        ], check=True, timeout=120)
        return

    silence_path = os.path.abspath(f"downloads/silence_{user_id}.wav")

    try:
        subprocess.run([
            "ffmpeg", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
            "-t", str(start_time), "-y", silence_path
        ], check=True, timeout=30)

        if speed == 1.0:
            filter_complex = (
                f"[2:v]scale='iw*0.55:ih*0.55',setsar=1[ad_v];"
                f"[1:a][2:a]concat=n=2:v=0:a=1[timed_ad_audio];"
                f"[0:a]volume=enable='between(t,{start_time},{end_time})':volume=0[base_audio];"
                f"[base_audio][timed_ad_audio]amix=inputs=2:duration=first[outa];"
                f"[0:v][ad_v]overlay=x=(W-w)/2:y=(H-h)/2:enable='between(t,{start_time},{end_time})'{wm}[outv]"
            )
        else:
            filter_complex = (
                f"[2:v]setpts=PTS/{speed},scale='iw*0.55:ih*0.55',setsar=1[ad_v];"
                f"[2:a]atempo={speed}[ad_a];"
                f"[1:a][ad_a]concat=n=2:v=0:a=1[timed_ad_audio];"
                f"[0:a]volume=enable='between(t,{start_time},{end_time})':volume=0[base_audio];"
                f"[base_audio][timed_ad_audio]amix=inputs=2:duration=first[outa];"
                f"[0:v][ad_v]overlay=x=(W-w)/2:y=(H-h)/2:enable='between(t,{start_time},{end_time})'{wm}[outv]"
            )

        subprocess.run([
            "ffmpeg", "-i", user_video_path, "-i", silence_path, "-i", MUSOR_PATH,
            "-filter_complex", filter_complex,
            "-map", "[outv]", "-map", "[outa]",
            "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency", "-threads", "0", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            "-y", output_path
        ], check=True, timeout=120)
    finally:
        if os.path.exists(silence_path):
            try: os.remove(silence_path)
            except: pass

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    known_users.add(user_id)
    save_users(known_users)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="ℹ️ Сведение", callback_data="btn_info"),
         InlineKeyboardButton(text="⭐ Поддержать", callback_data="btn_donate")],
        [InlineKeyboardButton(text="❌ Убрать ватермарк (20 ⭐)", callback_data="btn_remove_wm")]
    ])
    if user_id == ADMIN_ID:
        keyboard.inline_keyboard.append([InlineKeyboardButton(text="👑 Админ-панель", callback_data="btn_admin")])

    caption = (
        "<i>👋 Привет!\n\n"
        "🎥 Отправь мне видео (<b>до 1 минуты</b>), и я помогу настроить рекламу строго по центру со звуком.\n\n"
        "Жду твое видео! 📥</i>"
    )
    if os.path.exists(PHOTO_PATH):
        photo = FSInputFile(PHOTO_PATH)
        await message.answer_photo(photo, caption=caption, reply_markup=keyboard, parse_mode="HTML")
    else:
        await message.answer(caption, reply_markup=keyboard, parse_mode="HTML")

@dp.callback_query(F.data == "btn_admin")
async def cb_admin_panel(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещен", show_alert=True)
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Сделать рассылку", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")]
    ])
    await callback.message.answer("<i>👑 <b>Панель администратора:</b></i>", reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "admin_stats")
async def cb_admin_stats(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    await callback.message.answer(f"<i>📊 Статистика бота:\n\n👥 Всего пользователей: <b>{len(known_users)}</b></i>", parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "admin_broadcast")
async def cb_admin_broadcast(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return
    await callback.message.answer("<i>📢 Отправь текст, фото или видео для рассылки всем пользователям:</i>", parse_mode="HTML")
    await state.set_state(BroadcastState.waiting_for_message)
    await callback.answer()

@dp.message(BroadcastState.waiting_for_message, F.from_user.id == ADMIN_ID)
async def process_broadcast(message: Message, state: FSMContext):
    await state.clear()
    status_msg = await message.answer("<i>⏳ Рассылка началась...</i>", parse_mode="HTML")
    
    success = 0
    fail = 0
    for uid in known_users:
        try:
            await message.send_copy(chat_id=uid)
            success += 1
            await asyncio.sleep(0.05)
        except:
            fail += 1

    await status_msg.edit_text(f"<i>✅ Рассылка завершена!\n\nОтправлено: <b>{success}</b>\nНе удалось: <b>{fail}</b></i>", parse_mode="HTML")

@dp.callback_query(F.data == "btn_info")
async def cb_info(callback: CallbackQuery):
    info_text = (
        "<i>ℹ️ <b>Сведение о проекте:</b>\n\n"
        "🛠 Разработчик этого бота: <b>@azookick</b>\n"
        "🤖 Бот предназначен для автоматической вставки рекламных баннеров в видео для TikTok / Shorts.</i>"
    )
    await callback.message.answer(info_text, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "btn_donate")
async def cb_donate(callback: CallbackQuery):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="15 ⭐", callback_data="donate_15"),
            InlineKeyboardButton(text="50 ⭐", callback_data="donate_50"),
            InlineKeyboardButton(text="100 ⭐", callback_data="donate_100"),
        ],
        [
            InlineKeyboardButton(text="250 ⭐", callback_data="donate_250"),
            InlineKeyboardButton(text="500 ⭐", callback_data="donate_500"),
        ]
    ])
    await callback.message.answer("<i>❤️ Выбери сумму поддержки проекта звездами (Telegram Stars):</i>", reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data.startswith("donate_"))
async def cb_donate_amount(callback: CallbackQuery):
    amount = int(callback.data.split("_")[1])
    prices = [LabeledPrice(label=f"Поддержка {amount} ⭐", amount=amount)]
    await bot.send_invoice(
        chat_id=callback.message.chat.id,
        title="Поддержать проект",
        description=f"Донат в размере {amount} Telegram Stars для развития бота.",
        payload=f"donate_{amount}",
        currency="XTR",
        prices=prices
    )
    await callback.answer()

@dp.callback_query(F.data == "btn_remove_wm")
async def cb_remove_wm(callback: CallbackQuery):
    user_id = callback.from_user.id
    if user_id in paid_users:
        await callback.message.answer("<i>✅ У тебя уже отключен ватермарк навсегда!</i>", parse_mode="HTML")
        await callback.answer()
        return

    prices = [LabeledPrice(label="Убрать ватермарк @videomusordropbot", amount=20)]
    await bot.send_invoice(
        chat_id=callback.message.chat.id,
        title="Убрать ватермарк",
        description="Отключение водяного знака навсегда для всех твоих видео.",
        payload="remove_watermark",
        currency="XTR",
        prices=prices
    )
    await callback.answer()

@dp.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery):
    await bot.answer_pre_checkout_query(query.id, ok=True)

@dp.message(F.successful_payment)
async def successful_payment(message: Message):
    payment = message.successful_payment
    payload = payment.invoice_payload
    user_id = message.from_user.id

    if payload == "remove_watermark":
        paid_users.add(user_id)
        await message.answer("<i>🎉 Успешно! Ватермарк навсегда отключен для твоего аккаунта.</i>", parse_mode="HTML")
    elif payload.startswith("donate_"):
        amount = payload.split("_")[1]
        await message.answer(f"<i>❤️ Огромное спасибо за поддержку в размере {amount} ⭐! Ты лучший!</i>", parse_mode="HTML")

@dp.message(F.video | F.animation | F.document)
async def handle_video(message: types.Message):
    user_id = message.from_user.id

    # Cooldown check (1 minute)
    now = time.time()
    if user_id != ADMIN_ID and user_id in user_cooldowns:
        elapsed = now - user_cooldowns[user_id]
        if elapsed < 60:
            remaining = int(60 - elapsed)
            await message.answer(f"<i>⏳ Пожалуйста, подожди еще <b>{remaining} сек.</b> перед отправкой следующего видео (КД 1 минута).</i>", parse_mode="HTML")
            return

    known_users.add(user_id)
    save_users(known_users)

    file_id = None
    if message.video:
        file_id = message.video.file_id
    elif message.animation:
        file_id = message.animation.file_id
    elif message.document:
        if message.document.mime_type and message.document.mime_type.startswith("video"):
            file_id = message.document.file_id

    if not file_id:
        await message.answer("<i>❌ Пожалуйста, отправь видеофайл!</i>", parse_mode="HTML")
        return

    status_msg = await message.answer("<i>📥 Скачиваю видео...</i>", parse_mode="HTML")
    input_file = os.path.abspath(f"downloads/input_{user_id}.mp4")

    try:
        file = await bot.get_file(file_id)
        await bot.download_file(file.file_path, destination=input_file)
        user_sessions[user_id] = {"file": input_file}

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="1.0x", callback_data="speed_1.0"),
                InlineKeyboardButton(text="1.1x", callback_data="speed_1.1"),
                InlineKeyboardButton(text="1.2x", callback_data="speed_1.2"),
            ],
            [
                InlineKeyboardButton(text="1.3x", callback_data="speed_1.3"),
                InlineKeyboardButton(text="1.4x", callback_data="speed_1.4"),
            ]
        ])

        await bot.edit_message_text(
            "<i>🎛 Видео скачано! Шаг 1/2: Выбери скорость рекламного баннера:</i>",
            chat_id=message.chat.id,
            message_id=status_msg.message_id,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    except Exception as e:
        await bot.edit_message_text(f"<i>❌ Ошибка: {e}</i>", chat_id=message.chat.id, message_id=status_msg.message_id, parse_mode="HTML")

@dp.callback_query(F.data.startswith("speed_"))
async def process_speed_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    speed_str = callback.data.split("_")[1]
    try:
        speed = float(speed_str)
    except ValueError:
        speed = 1.0

    if user_id not in user_sessions:
        await callback.message.answer("<i>❌ Время сессии истекло. Отправь видео заново.</i>", parse_mode="HTML")
        await callback.answer()
        return

    user_sessions[user_id]["speed"] = speed

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏸ С паузой (заморозка кадра + реклама)", callback_data="mode_pause")],
        [InlineKeyboardButton(text="▶️ Без паузы (наложение поверх)", callback_data="mode_overlay")]
    ])

    await callback.message.edit_text(
        f"<i>✅ Скорость {speed}x сохранена!\n\nШаг 2/2: Выбери режим вставки рекламы:</i>",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("mode_"))
async def process_mode_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    mode = callback.data.split("_")[1] # 'pause' or 'overlay'
    session = user_sessions.get(user_id)

    if not session or "file" not in session or "speed" not in session:
        await callback.message.answer("<i>❌ Время сессии истекло. Отправь видео заново.</i>", parse_mode="HTML")
        await callback.answer()
        return

    input_file = session["file"]
    speed = session["speed"]
    no_watermark = (user_id in paid_users or user_id == ADMIN_ID)

    await callback.message.edit_reply_markup(reply_markup=None)
    
    if processing_lock.locked():
        await callback.message.edit_text("<i>⏳ Сервер занят обработкой другого видео. Твое видео встало в очередь...</i>", parse_mode="HTML")

    async with processing_lock:
        if user_id != ADMIN_ID:
            user_cooldowns[user_id] = time.time()

        await callback.message.edit_text(f"<i>✂️ Обрабатываю видео (скорость {speed}x, режим {mode})...</i>", parse_mode="HTML")

        output_file = os.path.abspath(f"output/output_{user_id}.mp4")

        try:
            loop = asyncio.get_running_loop()
            if mode == "pause":
                await loop.run_in_executor(None, process_video_pause, input_file, output_file, speed, user_id, no_watermark)
            else:
                await loop.run_in_executor(None, process_video_overlay, input_file, output_file, speed, user_id, no_watermark)

            video_input = FSInputFile(output_file)
            await callback.message.answer_video(
                video_input,
                caption="<i>🎬 Твое готовое видео (@vip_musor):</i>",
                parse_mode="HTML"
            )
            await bot.delete_message(chat_id=callback.message.chat.id, message_id=callback.message.message_id)

        except ValueError as ve:
            if str(ve) == "TOO_LONG":
                await callback.message.answer("<i>⚠️ Видео слишком длинное. Максимальная длительность — 1 минута!</i>", parse_mode="HTML")
            else:
                await callback.message.answer(f"<i>❌ Ошибка: {ve}</i>", parse_make=False, parse_mode="HTML") # type: ignore
        except Exception as e:
            logging.error(f"Error: {e}")
            await callback.message.answer(f"<i>❌ Произошла ошибка при обработке: {e}</i>", parse_mode="HTML")
        finally:
            if input_file and os.path.exists(input_file):
                try: os.remove(input_file)
                except: pass
            if output_file and os.path.exists(output_file):
                try: os.remove(output_file)
                except: pass
            if user_id in user_sessions:
                del user_sessions[user_id]
            await callback.answer()

async def web_server(request):
    return web.Response(text="Bot is running 24/7!")

async def main():
    app = web.Application()
    app.router.add_get("/", web_server)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    logging.info(f"Starting web server on port {port} and bot polling...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
