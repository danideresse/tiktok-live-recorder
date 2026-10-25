import asyncio
from pathlib import Path

from telethon import TelegramClient

from utils.logger_manager import logger
from utils.utils import read_telegram_config


FREE_USER_MAX_FILE_SIZE = 2 * 1024 * 1024 * 1024
PREMIUM_USER_MAX_FILE_SIZE = 4 * 1024 * 1024 * 1024


class Telegram:
    def __init__(self):
        config = read_telegram_config()

        self.api_id = config.get("api_id")
        self.api_hash = config.get("api_hash")
        self.chat_id = config.get("chat_id", "me")
        self.bot_token = config.get("bot_token") or None

        session_name = (
            "tiktok_live_recorder_bot"
            if self.bot_token
            else "tiktok_live_recorder_session"
        )
        self.client = TelegramClient(
            session_name,
            api_id=self.api_id,
            api_hash=self.api_hash,
        )

    def upload(self, file_path: str, chat_id=None):
        """
        Upload a file to the user's Saved Messages or specified chat via Telethon.
        """
        target_chat = chat_id or self.chat_id
        if isinstance(target_chat, str) and (
            target_chat.isdigit()
            or (target_chat.startswith("-") and target_chat[1:].isdigit())
        ):
            target_chat = int(target_chat)

        async def _upload():
            try:
                await self.client.connect()

                if not await self.client.is_user_authorized():
                    if self.bot_token:
                        await self.client.start(bot_token=self.bot_token)
                    else:
                        await self.client.start()

                me = await self.client.get_me()
                is_premium = getattr(me, "premium", False)
                max_size = (
                    PREMIUM_USER_MAX_FILE_SIZE
                    if is_premium
                    else FREE_USER_MAX_FILE_SIZE
                )

                file_size = Path(file_path).stat().st_size
                logger.info(
                    f"File to upload: {Path(file_path).name} "
                    f"({round(file_size / (1024 * 1024))} MB)"
                )

                if file_size > max_size:
                    logger.warning(
                        "The file is too large to be uploaded "
                        "with this type of account."
                    )
                    return

                logger.info(
                    "Uploading video on Telegram... "
                    "This may take a while depending on file size."
                )

                await self.client.send_file(
                    entity=target_chat,
                    file=file_path,
                    caption=(
                        "🎥 <b>Video recorded via "
                        '<a href="https://github.com/Michele0303/'
                        'tiktok-live-recorder">'
                        "TikTok Live Recorder</a></b>"
                    ),
                    parse_mode="html",
                    force_document=True,
                )

                logger.info("File successfully uploaded to Telegram.\n")

            except Exception as e:
                logger.error(f"Error during Telegram upload: {e}\n", exc_info=True)

            finally:
                await self.client.disconnect()

        asyncio.run(_upload())
