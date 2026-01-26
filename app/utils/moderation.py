# app/utils/moderation.py
import re
import hashlib
from datetime import datetime, timedelta
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import ChatPermissions, Message

URL_RE = re.compile(
    r"(?i)("
    r"https?://[^\s]+"          # любые http/https ссылки
    r"|www\.[^\s]+"             # www.*
    r"|t\.me/[^\s]+"            # t.me/*
    r"|telegram\.me/[^\s]+"     # telegram.me/*
    r"|telegra\.ph/[^\s]+"      # telegra.ph/*
    r"|@[\w\d_]{4,}"             # @username (как ссылка)
    r")"
)

# арабский Unicode диапазон (базово)
ARABIC_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]")

MUTE_PERMS = ChatPermissions(
    can_send_messages=False,
    can_send_media_messages=False,
    can_send_polls=False,
    can_send_other_messages=False,
    can_add_web_page_previews=False,
)

UNMUTE_PERMS = ChatPermissions(
    can_send_messages=True,
    can_send_media_messages=True,
    can_send_polls=True,
    can_send_other_messages=True,
    can_add_web_page_previews=True,
)

def normalize_text(text: str) -> str:
    t = (text or "").strip().lower()
    t = re.sub(r"\s+", " ", t)
    # убрать повторяющиеся символы типа "круууууто"
    t = re.sub(r"(.)\1{3,}", r"\1\1", t)
    return t

def text_hash(text: str) -> str:
    norm = normalize_text(text)
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()

def has_link(text: str) -> bool:
    return bool(URL_RE.search(text or ""))

def has_arabic(text: str) -> bool:
    return bool(ARABIC_RE.search(text or ""))

# супер простая эвристика рекламы (потом улучшим)
ADS_KEYWORDS = {
    "reklama", "реклама", "obuna", "подпиш", "подписывай", "скидк", "акция", "kanal", "канал",
    "pul", "деньги", "доход", "zarabot", "работа", "ish", "telegram", "tg", "rek"
}

def looks_like_ads(text: str) -> bool:
    norm = normalize_text(text)
    if has_link(norm):
        return True
    return any(k in norm for k in ADS_KEYWORDS)

async def mute_user(bot, chat_id: int, user_id: int, minutes: int) -> bool:
    until = datetime.utcnow() + timedelta(minutes=minutes)
    until_ts = int(until.timestamp())  # <-- ВАЖНО: int, а не datetime
    try:
        await bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=MUTE_PERMS,
            until_date=until_ts
        )
        return True
    except TelegramBadRequest as e:
        print(f"[mute_user] cannot restrict user {user_id} in chat {chat_id}: {e}")
        return False

async def unmute_user(bot, chat_id: int, user_id: int) -> bool:
    try:
        await bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=UNMUTE_PERMS,
        )
        return True
    except TelegramBadRequest as e:
        print(f"[unmute_user] cannot unrestrict user {user_id} in chat {chat_id}: {e}")
        return False

def is_channel_post(message: Message) -> bool:
    # sender_chat появляется у постов от имени канала/чата
    if message.sender_chat is not None:
        return True
    # переслано из канала
    if message.forward_from_chat is not None and message.forward_from_chat.type == "channel":
        return True
    return False
