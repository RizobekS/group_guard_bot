# app/handlers/guard.py
import asyncio
import re
import time
from datetime import datetime, date
from aiogram import Router, F
from aiogram.utils.markdown import hbold
from aiogram.exceptions import TelegramRetryAfter, TelegramNetworkError
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import Message, ChatPermissions, InlineKeyboardMarkup, InlineKeyboardButton, ChatMemberUpdated
from aiogram.utils.text_decorations import html_decoration as hd
from ..db import DB
from ..config import Config
from ..utils.access import can_manage_chat
from ..utils.access import can_manage_bot
from ..utils.moderation import has_link, has_arabic, looks_like_ads, is_channel_post, text_hash, mute_user, mute_user_seconds, unmute_user
from ..utils.antiraid import AntiRaid
from ..utils.admin import is_admin

router = Router()

ALLOW_ALL = ChatPermissions(
    can_send_messages=True,
    can_send_media_messages=True,
    can_send_polls=True,
    can_send_other_messages=True,
    can_add_web_page_previews=True,
    can_invite_users=True,
)

DENY_ALL = ChatPermissions(
    can_send_messages=True,
    can_send_media_messages=True,
    can_send_polls=False,
    can_send_other_messages=False,
    can_add_web_page_previews=False,
    can_invite_users=False,
)

_last_touch: dict[int, float] = {}
_last_user_touch: dict[int, float] = {}
_media_cache: dict[tuple[int, str], dict] = {}
_album_warned: dict[tuple[int, int, str, str], float] = {}

async def safe_answer(message: Message, *args, **kwargs):
    for attempt in range(3):
        try:
            return await message.answer(*args, **kwargs)
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after)
        except TelegramNetworkError:
            await asyncio.sleep(1 + attempt)
        except Exception as e:
            print(f"[safe_answer] failed: {type(e).__name__}: {e}")
            return None
    return None

def _cleanup_album_warned(ttl_sec: int = 15):
    now = time.monotonic()
    for key in list(_album_warned.keys()):
        if now - float(_album_warned[key]) > ttl_sec:
            _album_warned.pop(key, None)

async def _is_subscribed(bot, channel_username: str, user_id: int) -> bool | None:
    """
    Returns:
      True  - subscribed
      False - not subscribed
      None  - can't check (bot not admin / no access / channel invalid)
    """
    try:
        member = await bot.get_chat_member(chat_id=f"@{channel_username}", user_id=user_id)
        # possible statuses: creator, administrator, member, restricted, left, kicked
        return member.status in ("creator", "administrator", "member")
    except (TelegramBadRequest, TelegramForbiddenError) as e:
        # например: bot не админ канала, канал приватный, username неверный
        print(f"[force_channel] cannot check @{channel_username} user={user_id}: {e}")
        return None


def _normalize_for_words(text: str) -> str:
    t = (text or "").lower()
    # заменим всё кроме букв/цифр пробелом, чтобы ловить "a@b#c" примерно
    t = re.sub(r"[^\w]+", " ", t, flags=re.UNICODE)
    t = re.sub(r"\s+", " ", t).strip()
    return f" {t} "

def _normalize_for_badwords(text: str) -> str:
    t = (text or "").lower()
    # унифицируем апострофы
    t = t.replace("’", "'").replace("ʻ", "'").replace("`", "'")
    # всё кроме букв/цифр/подчёрк/апострофа -> пробел
    t = re.sub(r"[^\w']+", " ", t, flags=re.UNICODE)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _get_text(message: Message) -> str:
    return message.text or message.caption or ""

def _origin_usernames(message: Message) -> list[str]:
    res: list[str] = []

    # 1) От имени чата/канала
    if message.sender_chat:
        u = (getattr(message.sender_chat, "username", "") or "").strip().lstrip("@").lower()
        if u:
            res.append(u)

    # 2) Старый forward_from_chat
    if message.forward_from_chat:
        u = (getattr(message.forward_from_chat, "username", "") or "").strip().lstrip("@").lower()
        if u:
            res.append(u)

    # 3) Новый forward_origin.chat
    fo = getattr(message, "forward_origin", None)
    if fo is not None:
        ch = getattr(fo, "chat", None)
        if ch is not None:
            u = (getattr(ch, "username", "") or "").strip().lstrip("@").lower()
            if u:
                res.append(u)

    return res


def _mention(user) -> str:
    if user.username:
        return f"@{user.username}"
    full = (user.full_name or "user").replace("<", "").replace(">", "")
    return f'<a href="tg://user?id={user.id}">{full}</a>'

async def _send_temp(message: Message, text: str, seconds: int = 10):
    warn = await safe_answer(message, text, parse_mode="HTML")
    if not warn:
        return
    async def _del():
        await asyncio.sleep(seconds)
        try:
            await message.bot.delete_message(warn.chat.id, warn.message_id)
        except Exception:
            pass
    asyncio.create_task(_del())

def _schedule_auto_unmute(bot, chat_id: int, user_id: int, seconds: int):
    if seconds <= 0:
        return

    async def _job():
        await asyncio.sleep(seconds + 1)
        try:
            await unmute_user(bot, chat_id, user_id)
        except Exception:
            pass

    asyncio.create_task(_job())


def _remember_media(message: Message):
    """
    Remember message ids for albums (media_group_id), so later we can delete whole album.
    """
    if not message.media_group_id:
        return
    key = (message.chat.id, str(message.media_group_id))
    entry = _media_cache.get(key)
    now = time.monotonic()
    if not entry:
        _media_cache[key] = {"ids": [message.message_id], "ts": now}
        return
    if message.message_id not in entry["ids"]:
        entry["ids"].append(message.message_id)
    entry["ts"] = now


def _cleanup_media_cache(ttl_sec: int = 60):
    """
    Best-effort cleanup to prevent memory leak.
    """
    now = time.monotonic()
    for key in list(_media_cache.keys()):
        if now - float(_media_cache[key].get("ts", 0)) > ttl_sec:
            _media_cache.pop(key, None)

async def _safe_delete(bot, chat_id: int, mid: int):
    for _ in range(3):
        try:
            await bot.delete_message(chat_id, mid)
            return True
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after)
        except Exception:
            return False
    return False

async def _delete_message_or_album(message: Message):
    """
    Deletes a single message or the whole album (media group) if present.
    """
    # clean old cached groups sometimes
    _cleanup_media_cache(ttl_sec=120)

    if message.media_group_id:
        key = (message.chat.id, str(message.media_group_id))
        await asyncio.sleep(0.8)
        entry = _media_cache.get(key)
        ids = []
        if entry and entry.get("ids"):
            ids = list(entry["ids"])
        # ensure current msg id included
        if message.message_id not in ids:
            ids.append(message.message_id)

        # try delete all ids
        for _pass in range(2):
            for mid in list(ids):
                ok = await _safe_delete(message.bot, message.chat.id, mid)
                if ok and mid in ids:
                    ids.remove(mid)
            if not ids:
                break
            await asyncio.sleep(0.4)
            entry = _media_cache.get(key) or {}
            more = entry.get("ids") or []
            for mid in more:
                if mid not in ids:
                    ids.append(mid)

        _media_cache.pop(key, None)
        return

    await _safe_delete(message.bot, message.chat.id, message.message_id)


# def _append_force_text(s, txt: str) -> str:
#     extra = (getattr(s, "force_text", "") or "").strip()
#     if not extra:
#         return txt
#     # красивый quote, как вы уже делали
#     return txt + "\n\n" + hd.quote(extra)

async def _handle_violation(
    message: Message,
    db: DB,
    config: Config,
    rule: str,
    warn_text: str,
    mute_text: str,
    mute_minutes: int,
    strike_window_sec: int = 3600,
    bot_msg_delete_sec: int = 60,
):
    chat_id = message.chat.id
    user = message.from_user
    if not user:
        return

    s = await db.get_or_create_settings(chat_id)

    # менеджер = владелец бота / global bot-admin / creator / chat bot-admin
    is_manager = await can_manage_chat(
        message.bot,
        chat_id,
        user.id,
        user.username,
        db,
        config
    )

    # удаляем нарушающее сообщение
    try:
        await _delete_message_or_album(message)
    except Exception:
        pass

    if message.media_group_id:
        _cleanup_album_warned(ttl_sec=20)
        k = (chat_id, user.id, str(message.media_group_id), rule)
        if k in _album_warned:
            # уже предупреждали за этот альбом -> просто молча выходим
            return
        _album_warned[k] = time.monotonic()

    m = _mention(user)

    # текст предупреждения + textforce (если задан)
    warn_full = f"{m} {warn_text}"
    mute_full = f"{m} {mute_text} ({mute_minutes} daqiqa)"

    # менеджеров не наказываем, только предупреждаем
    if is_manager:
        await _send_temp(message, warn_full, seconds=bot_msg_delete_sec)
        return

    count = await db.hit_strike(chat_id, user.id, rule=rule, window_sec=strike_window_sec)

    if count == 1:
        await _send_temp(message, warn_full, seconds=bot_msg_delete_sec)
        return

    muted = await mute_user(message.bot, chat_id, user.id, minutes=mute_minutes)
    if muted:
        await _send_temp(message, mute_full, seconds=bot_msg_delete_sec)
        _schedule_auto_unmute(message.bot, chat_id, user.id, mute_minutes * 60)
    else:
        await _send_temp(
            message,
            f"{m} {mute_text} (lekin cheklashga ruxsat yo‘q)",
            seconds=bot_msg_delete_sec
        )

    await db.reset_strike(chat_id, user.id, rule=rule)


async def _process(message: Message, db: DB, antiflood, config: Config):
    chat_id = message.chat.id
    user = message.from_user
    try:
        tg_admin = await is_admin(message.bot, chat_id, user.id)
    except Exception:
        tg_admin = False
    if not user:
        return

    # сохраним username/ФИО, чтобы команды могли работать по @username,
    # даже если сообщение уже удалено.
    now = time.monotonic()
    last_u = _last_user_touch.get(user.id, 0.0)
    if now - last_u >= 300.0:  # раз в 5 минут на юзера
        _last_user_touch[user.id] = now
        try:
            await db.touch_user(user.id, user.username or "", user.full_name or "")
        except Exception:
            pass

    s = await db.get_or_create_settings(chat_id)
    text = _get_text(message)
    _remember_media(message)

    origin_usernames = _origin_usernames(message)
    is_ignored_sender = False
    for u in origin_usernames:
        if await db.is_ignore_username(chat_id, u):
            is_ignored_sender = True
            break

    # Команды:
    # - менеджерам/админам пропускаем (чтобы /priv @user не улетал как "ссылка")
    # - обычным юзерам проверяем "хвост" после команды (чтобы не обходили рекламу/мат)
    if message.text and message.text.startswith("/"):
        is_manager = await can_manage_chat(
            message.bot, chat_id, user.id, user.username, db, config
        )
        if is_manager or tg_admin:
            return
        # обычный юзер: проверяем то, что после "/команда"
        parts = text.split(maxsplit=1)
        text = parts[1] if len(parts) > 1 else ""
        if not text.strip():
            return

    # Force add
    if s.force_add_enabled and not tg_admin:
        if not await db.is_force_priv(chat_id, user.id):
            added = await db.get_force_progress(chat_id, user.id)
            required = int(s.force_add_required)
            if added < required:

                if message.media_group_id:
                    _cleanup_album_warned(ttl_sec=30)
                    k = (chat_id, user.id, str(message.media_group_id), "force_add")
                    if k in _album_warned:
                        return
                    _album_warned[k] = time.monotonic()

                try:
                    await _delete_message_or_album(message)
                except Exception:
                    pass

                need = max(0, required - added)
                m = _mention(user)

                bot_username = (await message.bot.get_me()).username
                deep_link = f"https://t.me/{bot_username}?start=force_{chat_id}"

                kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="👥 Odam qo‘shdim", url=deep_link)]
                ])

                txt = (
                    f"Kechirasiz! {m} guruhda yozish uchun avval "
                    f"<b>{required}</b> ta odam qo‘shishingiz zarur!\n\n"
                    f"📊 Siz qo‘shganlar: <b>{added}</b> ta\n"
                    f"⏳ Yana kerak: <b>{need}</b> ta\n\n"
                )


                warn = await safe_answer(
                    message,
                    txt,
                    parse_mode="HTML",
                    reply_markup=kb,
                    disable_web_page_preview=True
                )
                if not warn:
                    return

                # delete warning after N sec (sizda force_text_delete_sec bor)
                try:
                    sec = int(s.force_text_delete_sec or 60)
                except Exception:
                    sec = 60

                await mute_user_seconds(message.bot, chat_id, user.id, sec)

                async def _auto_unmute():
                    await asyncio.sleep(sec + 1)
                    try:
                        await unmute_user(message.bot, chat_id, user.id)
                    except Exception:
                        pass

                asyncio.create_task(_auto_unmute())

                async def _delete_later():
                    await asyncio.sleep(sec)
                    try:
                        await message.bot.delete_message(warn.chat.id, warn.message_id)
                    except Exception:
                        pass

                asyncio.create_task(_delete_later())
                return

    # 0) Anti-flood
    if s.antiflood_enabled:
        exceeded = antiflood.hit(
            chat_id=chat_id,
            user_id=user.id,
            window_sec=s.flood_window_sec,
            max_msgs=s.flood_max_msgs,
        )
        if exceeded:
            await _handle_violation(
                message, db, config,
                rule="antiflood",
                warn_text="Belgilangan vaqt ichida keragidan ortiq habar yubormang aks xolda bloklanasiz.",
                mute_text="Belgilangan vaqt ichida keragidan ortiq habar yuborganingiz uchun 2 daqiqaga bloklandingiz.",
                mute_minutes=2
            )
            return

    # 0.5) Force kanal: если канал привязан и юзер не подписан — удаляем сообщение
    if s.linked_channel and not tg_admin and not is_ignored_sender:
        res = await _is_subscribed(message.bot, s.linked_channel, user.id)
        if res is False:
            # удаляем сообщение и даем инструкцию (тихо и без спама)
            try:
                await message.delete()
            except Exception:
                pass
            m = _mention(user)
            txt = f"🔒 {m} guruhda yozish uchun @{s.linked_channel} kanaliga obuna bo‘ling."

            warn = await safe_answer(
                message,
                txt,
                parse_mode="HTML",
                disable_web_page_preview=True
            )
            if not warn:
                return

            async def _delete_later(chat_id: int, msg_id: int):
                await asyncio.sleep(10)
                try:
                    await message.bot.delete_message(chat_id, msg_id)
                except Exception:
                    pass

            asyncio.create_task(_delete_later(warn.chat.id, warn.message_id))
            return
            # res is None -> не можем проверить, не блокируем (иначе заблочим всех из-за прав бота)

    # 1) Канал-посты
    if s.block_channel_posts and is_channel_post(message):
        if is_ignored_sender:
            return
        # ✅ Исключение: если это "прикреплённый" канал из /set @kanal, то его посты не удаляем.
        linked = (s.linked_channel or "").lstrip("@").lower().strip()
        if linked:
            # 1) пост от имени канала
            if message.sender_chat and getattr(message.sender_chat, "type", None) == "channel":
                ch_u = (getattr(message.sender_chat, "username", "") or "").lower()
                if ch_u and ch_u == linked:
                    return
            # 2) форвард из канала (новое/старое поле)
            if message.forward_from_chat and getattr(message.forward_from_chat, "type", None) == "channel":
                ch_u = (getattr(message.forward_from_chat, "username", "") or "").lower()
                if ch_u and ch_u == linked:
                    return
            fo = getattr(message, "forward_origin", None)
            if fo is not None:
                ch = getattr(fo, "chat", None)
                if ch is not None and getattr(ch, "type", None) == "channel":
                    ch_u = (getattr(ch, "username", "") or "").lower()
                    if ch_u and ch_u == linked:
                        return

        await _handle_violation(
            message, db, config,
            rule="channel",
            warn_text="kanal nomidan post yubormang. Yana takrorlansa blok bo‘ladi.",
            mute_text="kanal post yuborganingiz uchun bloklandingiz.",
            mute_minutes=60
        )
        return

    # 2) Anti-same
    if s.antisame_enabled and text.strip():
        h = text_hash(text)
        log = await db.get_or_create_msglog(chat_id, user.id)
        minutes = s.antisame_minutes
        delta = datetime.utcnow() - log.last_at
        if log.last_hash == h and delta.total_seconds() <= minutes * 60:
            await _handle_violation(
                message, db, config,
                rule="antisame",
                warn_text="bir xil xabarni qayta yubormang. Yana takrorlansa blok bo‘ladi.",
                mute_text="bir xil xabarni qayta yuborganingiz uchun bloklandingiz.",
                mute_minutes=120
            )
            return
        await db.update_msglog(chat_id, user.id, last_hash=h, last_at=datetime.utcnow())

    # 3) Ссылки
    if s.block_links and has_link(text):
        await _handle_violation(
            message, db, config,
            rule="links",
            warn_text="havola yubormang. Yana yuborsangiz bloklanasiz.",
            mute_text="siz havola yuborganingiz uchun bloklandingiz.",
            mute_minutes=30,
        )
        return

    # 4) Arab
    if s.block_arab and has_arabic(text):
        await _handle_violation(
            message, db, config,
            rule="arab",
            warn_text="arabcha matn yubormang. Yana takrorlansa blok bo‘ladi.",
            mute_text="arabcha matn yuborganingiz uchun bloklandingiz.",
            mute_minutes=60,
        )
        return

    # 5) Реклама
    if s.block_ads and looks_like_ads(text):
        try:
            await _delete_message_or_album(message)
        except Exception:
            pass

        # 2) если это альбом — предупреждаем/считаем лимит только один раз на весь альбом
        if message.media_group_id:
            _cleanup_album_warned(ttl_sec=30)  # чуть больше, чтобы точно хватило
            album_key = (chat_id, user.id, str(message.media_group_id), "ads")
            if album_key in _album_warned:
                return
            _album_warned[album_key] = time.monotonic()

        # 3) считаем лимит (один раз на событие)
        hits = await db.inc_ads_hits(chat_id, user.id, day=date.today(), inc=1)

        m = _mention(user)
        if hits <= s.ads_daily_limit:
            msg = f"{m} reklama yubormang. Limit: {s.ads_daily_limit}/kun. Hozir: {hits}."
            await _send_temp(message, msg, seconds=60)
            return

        # 4) превысил лимит -> mute + auto-unmute
        muted = await mute_user(message.bot, chat_id, user.id, minutes=300)
        if muted:
            await _send_temp(
                message,
                f"{m} reklama limitidan oshdingiz, blok! (300 daqiqa)",
                seconds=60
            )
            _schedule_auto_unmute(message.bot, chat_id, user.id, 300 * 60)
        else:
            await _send_temp(
                message,
                f"{m} reklama limitidan oshdingiz (lekin cheklashga ruxsat yo‘q)",
                seconds=60
            )
        return

    if s.block_swear and text.strip():
        norm = _normalize_for_badwords(text)
        padded = f" {norm} "
        tokens = set(norm.split())
        bad_words = await db.list_bad_words(chat_id, limit=200)
        for w in bad_words:
            bw = _normalize_for_badwords(w)

            if not bw:
                continue
            if bw in tokens:
                await _handle_violation(
                    message, db, config,
                    rule="swear",
                    warn_text="so‘kinish mumkin emas. Yana takrorlansa blok bo‘ladi.",
                    mute_text="so‘kinganingiz uchun bloklandingiz.",
                    mute_minutes=300,  # 5 soat
                )
                return
            if len(bw) >= 4 and bw in padded:
                await _handle_violation(
                    message, db, config,
                    rule="swear",
                    warn_text="so‘kinish mumkin emas. Yana takrorlansa blok bo‘ladi.",
                    mute_text="so‘kinganingiz uchun bloklandingiz.",
                    mute_minutes=300,  # 5 soat
                )
                return



@router.message(
    F.chat.type.in_({"group", "supergroup"}) &
    (
        F.new_chat_title |
        F.new_chat_photo |
        F.delete_chat_photo |
        F.group_chat_created |
        F.supergroup_chat_created |
        F.message_auto_delete_timer_changed |
        F.pinned_message |
        F.migrate_from_chat_id |
        F.migrate_to_chat_id
    )
)
async def guard_service_messages(message: Message, db: DB, config: Config):
    s = await db.get_or_create_settings(message.chat.id)
    if not s.hide_service_msgs:
        return
    try:
        await message.delete()
    except Exception:
        pass

async def _antiraid_trigger(
    bot,
    chat_id: int,
    s,
    antiraid: AntiRaid,
    message: Message | None = None,
    join_count: int = 1,
):
    window_hours = int(s.raid_window_min)
    close_hours = int(s.raid_close_min)
    window_sec = window_hours * 3600
    close_sec = close_hours * 3600

    triggered = antiraid.hit(
        chat_id=chat_id,
        join_count=join_count,
        window_sec=window_sec,
        limit=int(s.raid_limit),
    )
    if not triggered:
        return

    try:
        await bot.set_chat_permissions(chat_id, DENY_ALL)
        antiraid.set_locked(chat_id, close_sec)
    except Exception as e:
        print(f"[antiraid] set_chat_permissions failed chat={chat_id}: {type(e).__name__}: {e}")
        return

    text = (
        f"🚨 Anti-raid: chat yopildi.\n"
        f"Limit: {s.raid_limit} / oyna: {window_hours} soat / yopish: {close_hours} soat"
    )

    # Если у нас нет Message (chat_member update), шлём напрямую
    try:
        if message:
            sent = await safe_answer(message, text, disable_web_page_preview=True)
            if not sent:
                print(f"[antiraid] notify failed chat={chat_id} limit={s.raid_limit}")
        else:
            await bot.send_message(chat_id, text, disable_web_page_preview=True)
    except Exception as e:
        print(f"[antiraid] notify failed chat={chat_id}: {type(e).__name__}: {e}")

    async def _reopen():
        await asyncio.sleep(close_sec)
        try:
            await bot.set_chat_permissions(chat_id, ALLOW_ALL)
            try:
                if message:
                    sent2 = await safe_answer(message, "✅ Anti-raid: chat qayta ochildi.")
                    if not sent2:
                        print(f"[antiraid open] notify failed chat={chat_id}")
                else:
                    await bot.send_message(chat_id, "✅ Anti-raid: chat qayta ochildi.")
            except Exception:
                pass
        except Exception as e:
            print(f"[antiraid] reopen failed chat={chat_id}: {type(e).__name__}: {e}")

    asyncio.create_task(_reopen())


@router.message(F.chat.type.in_({"group", "supergroup"}), F.new_chat_members)
async def guard_join(message: Message, db: DB, antiraid, config: Config):
    await db.touch_chat(message.chat.id, message.chat.title or "")
    s = await db.get_or_create_settings(message.chat.id)

    # 1) hide service msg
    if s.hide_service_msgs:
        try:
            await message.delete()
        except Exception:
            pass

      # Anti-raid: используем единую функцию (не копипастим логику)
    join_count = len(message.new_chat_members or [])

    if int(s.raid_limit or 0) > 0 and join_count > 0:
        await _antiraid_trigger(
            message.bot,
            message.chat.id,
            s,
            antiraid,
            message = message,  # тут можно reply через safe_answer
            join_count = join_count,  # пачка входящих
        )

@router.message(F.chat.type.in_({"group", "supergroup"}), F.left_chat_member)
async def guard_leave(message: Message, db: DB, config: Config):
    s = await db.get_or_create_settings(message.chat.id)
    if s.hide_service_msgs:
        try:
            await message.delete()
        except Exception:
            pass

@router.chat_member(F.chat.type.in_({"group", "supergroup"}))
async def guard_chat_member(update: ChatMemberUpdated, db: DB, antiraid: AntiRaid):
    chat_id = update.chat.id
    s = await db.get_or_create_settings(chat_id)

    # --- Anti-raid via chat_member (works even if service join messages are missing) ---
    old_status = getattr(update.old_chat_member, "status", None)
    new_status = getattr(update.new_chat_member, "status", None)
    if old_status in ("left", "kicked") and new_status in ("member", "restricted", "administrator", "creator"):
        if int(s.raid_limit or 0) > 0:
            await _antiraid_trigger(update.bot, chat_id, s, antiraid, message=None, join_count=1)

    if not s.force_add_enabled:
        return

    inviter = update.from_user
    new_user = update.new_chat_member.user

    if not inviter or not new_user:
        return

    if inviter.id == new_user.id:
        return

    if getattr(new_user, "is_bot", False):
        return

    try:
        tg_admin = await is_admin(update.bot, chat_id, inviter.id)
    except Exception:
        tg_admin = False
    if tg_admin:
        return

    await db.inc_force_progress(chat_id, inviter.id, 1)

@router.message(F.chat.type.in_({"group", "supergroup"}))
async def guard_all(message: Message, db: DB, antiflood, config: Config):
    if message.new_chat_members or message.left_chat_member:
        return

    chat_id = message.chat.id
    now = time.monotonic()

    # трогаем чат в БД максимум раз в 30 сек
    last = _last_touch.get(chat_id, 0.0)
    if now - last >= 30.0:
        _last_touch[chat_id] = now
        try:
            await db.touch_chat(chat_id, message.chat.title or "")
        except Exception:
            pass

    await _process(message, db, antiflood, config)
