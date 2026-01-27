# app/handlers/guard.py
import asyncio
import re
from datetime import datetime, date
from aiogram import Router, F
from aiogram.utils.markdown import hbold
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import Message, ChatPermissions, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.text_decorations import html_decoration as hd
from ..db import DB
from ..config import Config
from ..utils.access import can_manage_chat
from ..utils.access import can_manage_bot
from ..utils.moderation import has_link, has_arabic, looks_like_ads, is_channel_post, text_hash, mute_user
from ..utils.antiraid import AntiRaid
from ..utils.admin import is_admin

router = Router()

ALLOW_ALL = ChatPermissions(
    can_send_messages=True,
    can_send_media_messages=True,
    can_send_polls=True,
    can_send_other_messages=True,
    can_add_web_page_previews=True,
)

DENY_ALL = ChatPermissions(
    can_send_messages=False,
    can_send_media_messages=False,
    can_send_polls=False,
    can_send_other_messages=False,
    can_add_web_page_previews=False,
)

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

def _get_text(message: Message) -> str:
    return message.text or message.caption or ""

def _mention(user) -> str:
    if user.username:
        return f"@{user.username}"
    full = (user.full_name or "user").replace("<", "").replace(">", "")
    return f'<a href="tg://user?id={user.id}">{full}</a>'

async def _send_temp(message: Message, text: str, seconds: int = 10):
    warn = await message.answer(text, parse_mode="HTML", disable_web_page_preview=True)
    async def _del():
        await asyncio.sleep(seconds)
        try:
            await message.bot.delete_message(warn.chat.id, warn.message_id)
        except Exception:
            pass
    asyncio.create_task(_del())

def _append_force_text(s, txt: str) -> str:
    extra = (getattr(s, "force_text", "") or "").strip()
    if not extra:
        return txt
    # красивый quote, как вы уже делали
    return txt + "\n\n" + hd.quote(extra)

async def _handle_violation(
    message: Message,
    db: DB,
    config: Config,
    rule: str,
    warn_text: str,
    mute_text: str,
    mute_minutes: int,
    strike_window_sec: int = 3600,
    bot_msg_delete_sec: int = 10,
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
        await message.delete()
    except Exception:
        pass

    m = _mention(user)

    # текст предупреждения + textforce (если задан)
    warn_full = _append_force_text(s, f"{m} {warn_text}")
    mute_full = _append_force_text(s, f"{m} {mute_text} ({mute_minutes} daqiqa)")

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
    else:
        await _send_temp(
            message,
            _append_force_text(s, f"{m} {mute_text} (lekin cheklashga ruxsat yo‘q)"),
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

    s = await db.get_or_create_settings(chat_id)
    text = _get_text(message)

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
    if s.linked_channel:
        res = await _is_subscribed(message.bot, s.linked_channel, user.id)
        if res is False:
            # удаляем сообщение и даем инструкцию (тихо и без спама)
            try:
                await message.delete()
            except Exception:
                pass
            m = _mention(user)
            txt = f"🔒 {m} guruhda yozish uchun @{s.linked_channel} kanaliga obuna bo‘ling."
            txt = _append_force_text(s, txt)

            warn = await message.answer(
                txt,
                parse_mode="HTML",
                disable_web_page_preview=True
            )

            async def _delete_later(chat_id: int, msg_id: int):
                await asyncio.sleep(10)
                try:
                    await message.bot.delete_message(chat_id, msg_id)
                except Exception:
                    pass

            asyncio.create_task(_delete_later(warn.chat.id, warn.message_id))
            return
            # res is None -> не можем проверить, не блокируем (иначе заблочим всех из-за прав бота)

    # Force add
    if s.force_add_enabled:
        if not await db.is_force_priv(chat_id, user.id):
            added = await db.get_force_progress(chat_id, user.id)
            required = int(s.force_add_required)
            if added < required:
                try:
                    await message.delete()
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

                # Agar admin /textforce bilan custom matn bergan bo'lsa, pastiga qo'shib yuboramiz
                if s.force_text:
                    txt += hd.quote(s.force_text.strip())

                warn = await message.answer(
                    txt,
                    parse_mode="HTML",
                    reply_markup=kb,
                    disable_web_page_preview=True
                )

                # delete warning after N sec (sizda force_text_delete_sec bor)
                try:
                    sec = int(s.force_text_delete_sec or 10)
                except Exception:
                    sec = 10

                async def _delete_later():
                    await asyncio.sleep(sec)
                    try:
                        await message.bot.delete_message(warn.chat.id, warn.message_id)
                    except Exception:
                        pass

                asyncio.create_task(_delete_later())
                return

    # 1) Канал-посты
    if s.block_channel_posts and is_channel_post(message):
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
        # удаляем сразу
        try:
            await message.delete()
        except Exception:
            pass
        hits = await db.inc_ads_hits(chat_id, user.id, day=date.today(), inc=1)

        m = _mention(user)
        if hits <= s.ads_daily_limit:
            msg = _append_force_text(
                s,
                f"{m} reklama yubormang. Limit: {s.ads_daily_limit}/kun. Hozir: {hits}."
            )
            await _send_temp(message, msg, seconds=10)
            return

        # превысил лимит
        muted = await mute_user(message.bot, chat_id, user.id, minutes=300)
        if muted:
            await _send_temp(
                message,
                _append_force_text(s, f"{m} reklama limitidan oshdingiz, blok! (300 daqiqa)"),
                seconds=10
            )
        else:
            await _send_temp(
                message,
                _append_force_text(s, f"{m} reklama limitidan oshdingiz (lekin cheklashga ruxsat yo‘q)"),
                seconds=10
            )
        return

    if s.block_swear and text.strip():
        norm = _normalize_for_words(text)
        bad_words = await db.list_bad_words(chat_id, limit=200)
        for w in bad_words:
            if f" {w} " in norm:
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

    # 2) FORCE-ADD прогресс: считаем ВСЕГДА, если это РУЧНОЕ добавление
    # Telegram: при join по ссылке from_user обычно == сам вошедший -> это НЕ "я добавил людей"
    if s.force_add_enabled and message.from_user:
        inviter = message.from_user
        new_members = list(message.new_chat_members or [])

        # убираем бота и самого inviter (на случай странных кейсов)
        new_members = [m for m in new_members if not getattr(m, "is_bot", False) and m.id != inviter.id]

        # если inviter добавил кого-то вручную, то inviter != added_user (обычно так и бывает)
        # если люди зашли сами по ссылке, inviter == joiner -> new_members после фильтра станет пустым
        if new_members:
            try:
                await db.inc_force_progress(message.chat.id, inviter.id, len(new_members))
            except Exception as e:
                print(f"[force_add] cannot inc progress chat={message.chat.id} inviter={inviter.id}: {e}")

    # 3) ANTI-RAID (считает любых входящих, и ручных и по ссылке, потому что это "навалились люди")
    join_count = len(message.new_chat_members or [])
    window_hours = int(s.raid_window_min)
    close_hours = int(s.raid_close_min)
    window_sec = window_hours * 3600
    close_sec = close_hours * 3600

    triggered = antiraid.hit(
        chat_id=message.chat.id,
        join_count=join_count,
        window_sec=window_sec,
        limit=int(s.raid_limit),
    )
    if not triggered:
        return

    # Закрываем чат
    try:
        await message.bot.set_chat_permissions(message.chat.id, DENY_ALL)
        antiraid.set_locked(message.chat.id, close_sec)
        await message.answer(
            f"🚨 Anti-raid: chat yopildi.\n"
            f"Limit: {s.raid_limit} / oyna: {window_hours} soat / yopish: {close_hours} soat",
            disable_web_page_preview=True
        )
    except Exception:
        return

    # Через N часов открываем обратно
    async def _reopen():
        await asyncio.sleep(close_sec)
        try:
            await message.bot.set_chat_permissions(message.chat.id, ALLOW_ALL)
            await message.answer("✅ Anti-raid: chat qayta ochildi.")
        except Exception:
            pass

    asyncio.create_task(_reopen())

@router.message(F.chat.type.in_({"group", "supergroup"}), F.left_chat_member)
async def guard_leave(message: Message, db: DB, config: Config):
    s = await db.get_or_create_settings(message.chat.id)
    if s.hide_service_msgs:
        try:
            await message.delete()
        except Exception:
            pass


@router.message(F.chat.type.in_({"group", "supergroup"}))
async def guard_all(message: Message, db: DB, antiflood, config: Config):
    if message.new_chat_members or message.left_chat_member:
        return
    # фиксируем чат как активный даже без команд
    await db.touch_chat(message.chat.id, message.chat.title or "")
    await _process(message, db, antiflood, config)
