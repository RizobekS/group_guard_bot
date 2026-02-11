# app/utils/text_repeater.py
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Dict, Optional

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest

from ..db import DB


@dataclass
class _TaskInfo:
    task: asyncio.Task


class TextRepeater:
    """
    Per-chat background sender:
      - sends ChatSettings.force_text every force_text_repeat_sec
      - deletes sent message after force_text_delete_sec
    """

    def __init__(self, bot: Bot, db: DB):
        self.bot = bot
        self.db = db
        self._tasks: Dict[int, _TaskInfo] = {}

    async def restore_from_db(self) -> None:
        """
        On startup: schedule tasks for chats where repeat is enabled.
        """
        # we don't have a dedicated query method, so:
        # take active chats and check settings
        chat_ids = await self.db.list_active_chats(limit=5000)
        for chat_id in chat_ids:
            s = await self.db.get_or_create_settings(chat_id)
            if getattr(s, "force_text_repeat_sec", 0) and (s.force_text or "").strip():
                self.start(chat_id)

    def start(self, chat_id: int) -> None:
        """
        Start or restart repeater task for a chat.
        """
        self.stop(chat_id)
        self._tasks[chat_id] = _TaskInfo(task=asyncio.create_task(self._runner(chat_id)))

    def stop(self, chat_id: int) -> None:
        """
        Stop repeater task for a chat.
        """
        info = self._tasks.pop(chat_id, None)
        if info and not info.task.done():
            info.task.cancel()

    async def _delete_later(self, chat_id: int, message_id: int, delay: int) -> None:
        try:
            await asyncio.sleep(max(0, int(delay)))
            await self.bot.delete_message(chat_id, message_id)
        except Exception:
            pass

    async def _runner(self, chat_id: int) -> None:
        """
        Loop: read settings each cycle, so changes apply without restart.
        """
        try:
            while True:
                s = await self.db.get_or_create_settings(chat_id)

                repeat_sec = int(getattr(s, "force_text_repeat_sec", 0) or 0)
                text_value = (s.force_text or "").strip()

                # stop conditions
                if repeat_sec <= 0 or not text_value:
                    return

                # send
                try:
                    msg = await self.bot.send_message(chat_id, text_value)
                    delete_sec = int(getattr(s, "force_text_repeat_delete_sec", 0) or 0)
                    if delete_sec > 0:
                        asyncio.create_task(self._delete_later(chat_id, msg.message_id, delete_sec))
                except TelegramBadRequest:
                    # chat not found / no rights / etc
                    pass
                except Exception:
                    pass

                await asyncio.sleep(repeat_sec)
        except asyncio.CancelledError:
            return
