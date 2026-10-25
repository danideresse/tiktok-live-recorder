import asyncio
import json
import os
import re
import sys
import threading
import time
from pathlib import Path

# Add src directory to path
script_dir = Path(__file__).resolve().parent
if str(script_dir) not in sys.path:
    sys.path.insert(0, str(script_dir))

from telethon import Button, TelegramClient, events

from core.tiktok_api import TikTokAPI
from core.tiktok_recorder import TikTokRecorder
from utils.custom_exceptions import LiveNotFound, TikTokRecorderError, UserLiveError
from utils.enums import Mode, TikTokError
from utils.logger_manager import logger
from utils.recorder_config import RecorderConfig
from utils.utils import read_cookies, read_telegram_config

# Ensure dedicated recordings directory exists
RECORDINGS_DIR = Path("recordings")
RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)

RECENT_USERS_FILE = script_dir / "recent_users.json"

# Active recording/monitoring sessions: username -> dict
active_tasks = {}
active_tasks_lock = threading.Lock()

# Persistent bottom reply keyboard
MAIN_KEYBOARD = [
    [Button.text("🔴 Record User"), Button.text("⏹ Stop Recording")],
    [Button.text("📊 Status"), Button.text("📁 Recordings")],
]


def load_recent_users() -> list[str]:
    """Load list of recently recorded usernames."""
    if RECENT_USERS_FILE.exists():
        try:
            with open(RECENT_USERS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
        except Exception:
            pass
    # Defaults based on previous recordings
    return ["betiabebe493", "samri.1222"]


def save_recent_user(user: str):
    """Add user to recent users list and save."""
    users = load_recent_users()
    if user in users:
        users.remove(user)
    users.insert(0, user)
    users = users[:8]  # Keep up to 8 recent creators
    try:
        with open(RECENT_USERS_FILE, "w", encoding="utf-8") as f:
            json.dump(users, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save recent user: {e}")


def parse_tiktok_username(text: str) -> str:
    """Extract TikTok username from username, @username, or TikTok live URL."""
    text = text.strip()
    url_match = re.search(r"tiktok\.com/@([^/?&#]+)", text)
    if url_match:
        return url_match.group(1)
    if text.startswith("@"):
        return text[1:].strip()
    # Remove command prefix if any
    parts = text.split()
    first = parts[0]
    if first.startswith("/"):
        return parts[1] if len(parts) > 1 else ""
    return first


def format_duration(seconds: float) -> str:
    mins, secs = divmod(int(seconds), 60)
    hrs, mins = divmod(mins, 60)
    if hrs > 0:
        return f"{hrs}h {mins}m {secs}s"
    return f"{mins}m {secs}s"


async def main():
    tg_config = read_telegram_config()
    api_id = tg_config.get("api_id")
    api_hash = tg_config.get("api_hash")
    bot_token = tg_config.get("bot_token")

    if not api_id or not api_hash or not bot_token:
        print("\n" + "=" * 60)
        print(" [!] Missing Telegram configuration!")
        print(" Please ensure 'api_id', 'api_hash', and 'bot_token'")
        print(" are configured in 'src/telegram.json'.")
        print("=" * 60 + "\n")
        return

    client = TelegramClient(
        "tiktok_live_recorder_bot",
        api_id=int(api_id),
        api_hash=str(api_hash),
    )

    await client.start(bot_token=str(bot_token))
    bot_me = await client.get_me()
    logger.info(f"Telegram Bot started successfully as @{bot_me.username}!")
    print(f"\n[*] Telegram Bot is online! Search @{bot_me.username} on Telegram to start.\n")

    loop = asyncio.get_running_loop()

    async def send_file_to_chat(chat_id: int, file_path: str, user: str):
        """Asynchronously uploads the recorded file to the Telegram chat."""
        try:
            path = Path(file_path)
            if not path.exists():
                logger.error(f"File {file_path} not found for upload.")
                await client.send_message(
                    chat_id,
                    f"⚠️ Error: Recorded file for @{user} was not found.",
                    buttons=MAIN_KEYBOARD,
                )
                return

            file_size = path.stat().st_size
            file_size_mb = round(file_size / (1024 * 1024), 1)

            # Telegram Bot API max file size is 2000 MB (2 GB)
            if file_size > 2000 * 1024 * 1024:
                await client.send_message(
                    chat_id,
                    f"⚠️ <b>Video too large for Telegram upload!</b>\n\n"
                    f"The recorded live for @{user} is {file_size_mb} MB (exceeds Telegram's 2 GB limit).\n"
                    f"File is saved safely in the dedicated folder:\n<code>{path.resolve()}</code>",
                    parse_mode="html",
                    buttons=MAIN_KEYBOARD,
                )
                return

            notify_msg = await client.send_message(
                chat_id,
                f"📤 <b>Uploading recording of @{user} ({file_size_mb} MB)...</b>\n"
                f"Please wait, this depends on file size and internet connection.",
                parse_mode="html",
            )

            caption = (
                f"🎥 <b>TikTok Live Recording</b>\n"
                f"👤 <b>Creator:</b> @{user}\n"
                f"📦 <b>Size:</b> {file_size_mb} MB\n"
                f"📁 <b>Saved to:</b> <code>recordings/</code>"
            )

            last_edit_time = [0.0]

            def progress_callback(current, total):
                now = time.time()
                if now - last_edit_time[0] > 4.0:
                    last_edit_time[0] = now
                    pct = round((current / total) * 100)
                    mb_cur = round(current / (1024 * 1024), 1)
                    mb_tot = round(total / (1024 * 1024), 1)
                    asyncio.run_coroutine_threadsafe(
                        notify_msg.edit(
                            f"📤 <b>Uploading recording of @{user}...</b>\n"
                            f"Progress: <code>{pct}%</code> ({mb_cur}/{mb_tot} MB)",
                            parse_mode="html",
                        ),
                        loop,
                    )

            await client.send_file(
                entity=chat_id,
                file=str(path),
                caption=caption,
                parse_mode="html",
                progress_callback=progress_callback,
                supports_streaming=True,
            )

            await notify_msg.delete()
            await client.send_message(
                chat_id,
                f"✅ <b>Delivered!</b> Live recording of @{user} has been sent.\n"
                f"Saved to: <code>{path.name}</code> in <code>recordings/</code> folder.",
                parse_mode="html",
                buttons=MAIN_KEYBOARD,
            )
            logger.info(f"Video for @{user} successfully sent to chat {chat_id}.")

        except Exception as e:
            logger.error(f"Failed to upload video for @{user}: {e}", exc_info=True)
            await client.send_message(
                chat_id,
                f"❌ <b>Error delivering video for @{user}:</b> {e}",
                parse_mode="html",
                buttons=MAIN_KEYBOARD,
            )

    def run_recording_worker(
        user: str,
        chat_id: int,
        mode: Mode,
        interval: int = 5,
        room_id: str | None = None,
    ):
        """Worker thread executing TikTokRecorder."""
        stop_event = threading.Event()
        with active_tasks_lock:
            active_tasks[user] = {
                "mode": "automatic" if mode == Mode.AUTOMATIC else "manual",
                "chat_id": chat_id,
                "stop_event": stop_event,
                "start_time": time.time(),
            }

        def on_finish_callback(mp4_file: str):
            asyncio.run_coroutine_threadsafe(
                send_file_to_chat(chat_id, mp4_file, user),
                loop,
            )

        try:
            cookies = read_cookies()
            tg_cfg = read_telegram_config()
            config = RecorderConfig(
                mode=mode,
                user=user,
                room_id=room_id,
                output="recordings",
                bitrate=tg_cfg.get("bitrate"),
                automatic_interval=interval,
                cookies=cookies,
                stop_event=stop_event,
                on_finish=on_finish_callback,
            )
            recorder = TikTokRecorder(config)
            recorder.run()

        except (UserLiveError, LiveNotFound) as ex:
            if mode == Mode.MANUAL:
                asyncio.run_coroutine_threadsafe(
                    client.send_message(
                        chat_id,
                        f"⚠️ @{user} is not live at the moment.",
                        buttons=MAIN_KEYBOARD,
                    ),
                    loop,
                )
            else:
                logger.info(f"Auto-mode check for @{user}: {ex}")

        except Exception as ex:
            logger.error(f"Error in recording worker for @{user}: {ex}", exc_info=True)
            asyncio.run_coroutine_threadsafe(
                client.send_message(
                    chat_id,
                    f"❌ Error recording @{user}: {ex}",
                    buttons=MAIN_KEYBOARD,
                ),
                loop,
            )


        finally:
            with active_tasks_lock:
                if user in active_tasks:
                    del active_tasks[user]
            logger.info(f"Recording worker ended for @{user}.")

    def start_recording_flow(user: str, chat_id: int, status_msg=None):
        """Pre-checks live status and starts recording with one-tap stop button."""
        save_recent_user(user)

        def worker():
            try:
                cookies = read_cookies()
                api = TikTokAPI(proxy=None, cookies=cookies)
                room_id = api.get_room_id_from_user(user)

                if not room_id or not api.is_room_alive(room_id):
                    text = f"⚠️ <b>@{user} is not live right now.</b>"
                    if status_msg:
                        asyncio.run_coroutine_threadsafe(
                            status_msg.edit(text, parse_mode="html"),
                            loop,
                        )
                    else:
                        asyncio.run_coroutine_threadsafe(
                            client.send_message(chat_id, text, parse_mode="html", buttons=MAIN_KEYBOARD),
                            loop,
                        )
                    return

                # Send recording confirmation with an interactive Stop button
                stop_buttons = [
                    [Button.inline(f"⏹ Stop Recording @{user}", data=f"stop:{user}")],
                ]

                msg_text = (
                    f"🔴 <b>@{user} is LIVE! Recording started...</b>\n\n"
                    f"📁 Saving to: <code>recordings/</code> folder\n"
                    f"Tap the button below anytime to stop recording & receive the video!"
                )

                if status_msg:
                    asyncio.run_coroutine_threadsafe(
                        status_msg.edit(msg_text, parse_mode="html", buttons=stop_buttons),
                        loop,
                    )
                else:
                    asyncio.run_coroutine_threadsafe(
                        client.send_message(chat_id, msg_text, parse_mode="html", buttons=stop_buttons),
                        loop,
                    )

                thread = threading.Thread(
                    target=run_recording_worker,
                    args=(user, chat_id, Mode.MANUAL, 5, room_id),
                    daemon=True,
                )
                thread.start()

            except UserLiveError as e:
                logger.info(f"User live status for @{user}: {e}")
                err_text = f"⚠️ <b>@{user}</b>: {e}"
                if status_msg:
                    asyncio.run_coroutine_threadsafe(
                        status_msg.edit(err_text, parse_mode="html"),
                        loop,
                    )
                else:
                    asyncio.run_coroutine_threadsafe(
                        client.send_message(chat_id, err_text, parse_mode="html", buttons=MAIN_KEYBOARD),
                        loop,
                    )

            except Exception as e:
                logger.error(f"Pre-check error for @{user}: {e}", exc_info=True)
                err_text = f"❌ Error checking @{user}: {e}"
                if status_msg:
                    asyncio.run_coroutine_threadsafe(
                        status_msg.edit(err_text),
                        loop,
                    )
                else:
                    asyncio.run_coroutine_threadsafe(
                        client.send_message(chat_id, err_text, buttons=MAIN_KEYBOARD),
                        loop,
                    )

        threading.Thread(target=worker, daemon=True).start()

    def stop_recording_flow(user: str | None = None) -> tuple[bool, str]:
        """Stops active recording for user or all."""
        with active_tasks_lock:
            if not active_tasks:
                return False, "⚠️ No active recordings at the moment."

            if user:
                task = active_tasks.get(user)
                if not task:
                    return False, f"⚠️ No active recording found for @{user}."
                task["stop_event"].set()
                return True, f"🛑 <b>Stopping recording for @{user}...</b>\nFinalizing video and uploading to you shortly!"
            else:
                # Stop single task if only 1 exists
                if len(active_tasks) == 1:
                    target_user = list(active_tasks.keys())[0]
                    active_tasks[target_user]["stop_event"].set()
                    return True, f"🛑 <b>Stopping recording for @{target_user}...</b>\nFinalizing video and uploading to you shortly!"
                else:
                    return False, "multiple"

    # Callback Query Handler (for inline buttons)
    @client.on(events.CallbackQuery)
    async def callback_handler(event):
        data = event.data.decode("utf-8")

        if data.startswith("stop:"):
            target_user = data.split(":", 1)[1]
            success, msg = stop_recording_flow(target_user)
            await event.answer("Stopping recording...")
            await event.edit(msg, parse_mode="html")

        elif data.startswith("rec:"):
            target_user = data.split(":", 1)[1]
            await event.answer(f"Checking @{target_user}...")
            status_msg = await event.edit(f"🔍 <b>Checking @{target_user} live status...</b>", parse_mode="html")
            start_recording_flow(target_user, event.chat_id, status_msg)

        elif data == "clear_recent":
            try:
                if RECENT_USERS_FILE.exists():
                    RECENT_USERS_FILE.unlink()
            except Exception:
                pass
            await event.answer("Recent creators cleared!")
            await event.edit(
                "🗑 <b>Recent creators list has been cleared!</b>\n\n"
                "Send any TikTok username or link whenever you want to record.",
                parse_mode="html",
            )

        elif data.startswith("auto:"):
            target_user = data.split(":", 1)[1]
            await event.answer(f"Setting auto-monitor for @{target_user}...")
            save_recent_user(target_user)
            with active_tasks_lock:
                if target_user in active_tasks:
                    await event.edit(f"⚠️ @{target_user} is already being recorded or monitored!")
                    return

            stop_buttons = [[Button.inline(f"⏹ Stop Monitoring @{target_user}", data=f"stop:{target_user}")]]
            await event.edit(
                f"🔄 <b>Auto-monitoring activated for @{target_user}!</b>\n\n"
                f"• Checking every 5 minutes.\n"
                f"• Videos will be saved to <code>recordings/</code> and sent here.\n"
                f"• Tap below anytime to stop monitoring.",
                parse_mode="html",
                buttons=stop_buttons,
            )
            thread = threading.Thread(
                target=run_recording_worker,
                args=(target_user, event.chat_id, Mode.AUTOMATIC, 5),
                daemon=True,
            )
            thread.start()

    # /start and /help command
    @client.on(events.NewMessage(pattern=r"^/(start|help)$"))
    async def welcome_handler(event):
        sender = await event.get_sender()
        name = getattr(sender, "first_name", "there")
        recent = load_recent_users()

        inline_quick = []
        if recent:
            row = []
            for u in recent[:4]:
                row.append(Button.inline(f"▶️ @{u}", data=f"rec:{u}"))
                if len(row) == 2:
                    inline_quick.append(row)
                    row = []
            if row:
                inline_quick.append(row)

        text = (
            f"👋 Welcome <b>{name}</b>!\n\n"
            f"🎥 <b>TikTok Live Recorder Bot</b>\n\n"
            f"<b>Features:</b>\n"
            f"• <b>Multiple Recordings</b>: You can record multiple creators at the same time!\n"
            f"• <b>High Quality</b>: Automatically captures the highest live quality (1080p / 720p HD).\n"
            f"• <b>Dedicated Folder</b>: All videos saved in <code>recordings/</code>.\n\n"
            f"<b>How to use:</b>\n"
            f"1️⃣ Tap <b>🔴 Record User</b> or send any TikTok username.\n"
            f"2️⃣ When recording, tap the <b>⏹ Stop</b> button anytime.\n\n"
            f"👇 <i>Tap a creator below to start recording now:</i>"
        )
        await event.respond(text, parse_mode="html", buttons=inline_quick or None)
        if not inline_quick:
            await event.respond("Use the menu buttons below:", buttons=MAIN_KEYBOARD)

    # Bottom button: "🔴 Record User"
    @client.on(events.NewMessage(pattern=r"^(🔴 Record User|/record)$"))
    async def record_menu_handler(event):
        recent = load_recent_users()
        inline_buttons = []
        row = []
        for u in recent:
            row.append(Button.inline(f"🔴 @{u}", data=f"rec:{u}"))
            if len(row) == 2:
                inline_buttons.append(row)
                row = []
        if row:
            inline_buttons.append(row)

        if recent:
            inline_buttons.append([Button.inline("🗑 Clear Recent Creators", data="clear_recent")])

        msg = (
            "🎯 <b>Tap a creator to record, or type/paste any username:</b>"
            if inline_buttons
            else "🎯 <b>Type or paste any TikTok username to start recording:</b>"
        )
        await event.respond(msg, parse_mode="html", buttons=inline_buttons or MAIN_KEYBOARD)

    # /clear command
    @client.on(events.NewMessage(pattern=r"^/(clear|clear_recent)$"))
    async def clear_command_handler(event):
        try:
            if RECENT_USERS_FILE.exists():
                RECENT_USERS_FILE.unlink()
        except Exception:
            pass
        await event.respond("🗑 <b>Recent creators list has been cleared!</b>", parse_mode="html", buttons=MAIN_KEYBOARD)


    # Bottom button: "⏹ Stop Recording" or "stop"
    @client.on(events.NewMessage(pattern=r"^(⏹ Stop Recording|stop|/stop)$", func=lambda e: not e.raw_text.strip().startswith("/stop ")))
    async def stop_menu_handler(event):
        with active_tasks_lock:
            if not active_tasks:
                await event.respond("ℹ️ No active recordings to stop.", buttons=MAIN_KEYBOARD)
                return

            if len(active_tasks) == 1:
                target_user = list(active_tasks.keys())[0]
                active_tasks[target_user]["stop_event"].set()
                await event.respond(
                    f"🛑 <b>Stopping recording for @{target_user}...</b>\n"
                    f"Finalizing video and uploading to you shortly!",
                    parse_mode="html",
                    buttons=MAIN_KEYBOARD,
                )
            else:
                # Multiple tasks - show buttons for each
                buttons = []
                for u in active_tasks:
                    buttons.append([Button.inline(f"⏹ Stop @{u}", data=f"stop:{u}")])
                await event.respond("Select which recording to stop:", buttons=buttons)

    # Specific stop with username: "/stop <user>" or "stop <user>"
    @client.on(events.NewMessage(pattern=r"^(?:/stop|stop)\s+(.*)$"))
    async def stop_specific_handler(event):
        raw_user = event.pattern_match.group(1).strip()
        user = parse_tiktok_username(raw_user)
        success, msg = stop_recording_flow(user)
        await event.respond(msg, parse_mode="html", buttons=MAIN_KEYBOARD)

    # Bottom button: "📊 Status" or "status"
    @client.on(events.NewMessage(pattern=r"^(📊 Status|status|/status)$"))
    async def status_menu_handler(event):
        with active_tasks_lock:
            if not active_tasks:
                await event.respond("ℹ️ No active recordings or monitoring tasks right now.", buttons=MAIN_KEYBOARD)
                return

            msg = "📊 <b>Active Recording Tasks:</b>\n\n"
            now = time.time()
            buttons = []
            for u, data in active_tasks.items():
                dur = format_duration(now - data["start_time"])
                msg += f"• <b>@{u}</b>\n  Mode: <code>{data['mode']}</code> | Elapsed: <code>{dur}</code>\n\n"
                buttons.append([Button.inline(f"⏹ Stop @{u}", data=f"stop:{u}")])

            await event.respond(msg, parse_mode="html", buttons=buttons or MAIN_KEYBOARD)

    # Bottom button: "📁 Recordings"
    @client.on(events.NewMessage(pattern=r"^(📁 Recordings|recordings|/recordings)$"))
    async def recordings_menu_handler(event):
        files = list(RECORDINGS_DIR.glob("*.mp4"))
        if not files:
            await event.respond(
                "📁 <b>Recordings Folder is empty.</b>\nAll future recordings will be stored in <code>recordings/</code>.",
                parse_mode="html",
                buttons=MAIN_KEYBOARD,
            )
            return

        files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        msg = f"📁 <b>Saved Recordings ({len(files)} files in <code>recordings/</code>):</b>\n\n"
        for f in files[:10]:
            size_mb = round(f.stat().st_size / (1024 * 1024), 1)
            msg += f"• <code>{f.name}</code> ({size_mb} MB)\n"

        if len(files) > 10:
            msg += f"\n<i>...and {len(files) - 10} more files.</i>"

        await event.respond(msg, parse_mode="html", buttons=MAIN_KEYBOARD)

    # Direct username or link sent: "betiabebe493" or "@betiabebe493" or "tiktok.com/@..."
    @client.on(events.NewMessage)
    async def smart_text_handler(event):
        text = event.raw_text.strip()
        # Ignore already-handled commands and menu labels
        if text.startswith("/") or text in ["🔴 Record User", "⏹ Stop Recording", "📊 Status", "📁 Recordings", "stop", "status"]:
            return

        user = parse_tiktok_username(text)
        if not user or len(user) < 2 or " " in user:
            return

        with active_tasks_lock:
            if user in active_tasks:
                stop_btn = [[Button.inline(f"⏹ Stop Recording @{user}", data=f"stop:{user}")]]
                await event.respond(
                    f"⚠️ @{user} is already being recorded!\nTap below if you want to stop it:",
                    buttons=stop_btn,
                )
                return

        # Show instant 1-tap choice buttons
        action_buttons = [
            [
                Button.inline(f"🔴 Record @{user} Now", data=f"rec:{user}"),
                Button.inline(f"🔄 Auto Monitor", data=f"auto:{user}"),
            ]
        ]
        await event.respond(
            f"👤 <b>Creator: @{user}</b>\nTap an option below to start:",
            parse_mode="html",
            buttons=action_buttons,
        )

    await client.run_until_disconnected()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("\n[*] Bot stopped.")
