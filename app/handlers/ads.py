from __future__ import annotations

import json
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest

from ..config import Config
from ..db import DB
from ..utils.access import is_owner

router = Router()


class AdStates(StatesGroup):
    text = State()
    photo = State()
    buttons = State()
    target = State()
    confirm = State()


# ----------------- Keyboards -----------------

def _ad_menu_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="🆕 Yangi reklama", callback_data="ad:menu:new")
    kb.button(text="📂 Saqlangan reklamalar", callback_data="ad:menu:saved")
    kb.button(text="❌ Bekor qilish", callback_data="ad:cancel")
    kb.adjust(1)
    return kb.as_markup()


def _target_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="👤 Faqat menga", callback_data="ad:target:me")
    kb.button(text="👤 Barcha foydalanuvchilarga", callback_data="ad:target:users")
    kb.button(text="👥 Barcha guruhlarga", callback_data="ad:target:groups")
    kb.button(text="👤+👥 Foydalanuvchilar + guruhlar", callback_data="ad:target:users_groups")
    kb.button(text="❌ Bekor qilish", callback_data="ad:cancel")
    kb.adjust(1)
    return kb.as_markup()


def _confirm_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Yuborish", callback_data="ad:send")
    kb.button(text="❌ Bekor qilish", callback_data="ad:cancel")
    kb.adjust(2)
    return kb.as_markup()


def _save_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="💾 Saqlash", callback_data="ad:save")
    kb.button(text="⏭ Saqlamaslik", callback_data="ad:nosave")
    kb.adjust(2)
    return kb.as_markup()


def _ads_list_kb(ads):
    kb = InlineKeyboardBuilder()
    for a in ads:
        title = a.title or f"Reklama #{a.id}"
        kb.button(text=f"📄 {title[:35]}", callback_data=f"ad:open:{a.id}")
    kb.button(text="⬅️ Orqaga", callback_data="ad:back")
    kb.adjust(1)
    return kb.as_markup()


def _ad_manage_kb(ad_id: int):
    kb = InlineKeyboardBuilder()
    kb.button(text="📤 Yuborish", callback_data=f"ad:send_saved:{ad_id}")
    kb.button(text="🗑 O‘chirish", callback_data=f"ad:del:{ad_id}")
    kb.button(text="⬅️ Orqaga", callback_data="ad:menu:saved")
    kb.adjust(1)
    return kb.as_markup()


def _buttons_kb(buttons: list[tuple[str, str]]):
    if not buttons:
        return None
    kb = InlineKeyboardBuilder()
    for t, u in buttons:
        kb.button(text=t, url=u)
    kb.adjust(1)
    return kb.as_markup()


# ----------------- Parsers -----------------

def _parse_buttons(text: str) -> list[tuple[str, str]]:
    """
    Har qatorda: "Tugma nomi | https://link"
    """
    out: list[tuple[str, str]] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or "|" not in line:
            continue
        t, u = [p.strip() for p in line.split("|", 1)]
        if not t or not u:
            continue
        if not (u.startswith("http://") or u.startswith("https://") or u.startswith("tg://") or u.startswith("https://t.me/")):
            continue
        out.append((t[:64], u))
    return out[:10]


# ----------------- Handlers -----------------

@router.message(Command("ad"))
async def cmd_ad(message: Message, db: DB, state: FSMContext, config: Config):
    if message.chat.type != "private":
        return
    if not await is_owner(message, config):
        return

    await state.clear()
    await message.answer("📢 Reklama bo‘limi. Tanlang:", reply_markup=_ad_menu_kb())


@router.callback_query(F.data == "ad:menu:new")
async def ad_menu_new(query: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(AdStates.text)
    await query.message.answer(
        "📝 Reklama matnini yuboring.\n\n"
        "Keyin rasm so‘rayman. Rasm bo‘lmasa /skip yozing."
    )
    await query.answer()


@router.callback_query(F.data == "ad:menu:saved")
async def ad_menu_saved(query: CallbackQuery, db: DB):
    ads = await db.list_ads(query.from_user.id, limit=20)
    if not ads:
        await query.message.answer("📭 Saqlangan reklama yo‘q.")
        await query.answer()
        return
    await query.message.answer("📂 Saqlangan reklamalar:", reply_markup=_ads_list_kb(ads))
    await query.answer()


@router.callback_query(F.data == "ad:back")
async def ad_back(query: CallbackQuery):
    await query.message.answer("📢 Reklama bo‘limi. Tanlang:", reply_markup=_ad_menu_kb())
    await query.answer()


@router.callback_query(F.data.startswith("ad:open:"))
async def ad_open(query: CallbackQuery, db: DB):
    ad_id = int(query.data.split(":")[-1])
    ad = await db.get_ad(query.from_user.id, ad_id)
    if not ad:
        await query.message.answer("❌ Reklama topilmadi.")
        await query.answer()
        return

    preview = f"📄 <b>{ad.title or f'Reklama #{ad.id}'}</b>\n\n"
    txt = ad.text or ""
    preview += (txt[:900] + "…") if len(txt) > 900 else txt

    await query.message.answer(preview, reply_markup=_ad_manage_kb(ad_id), parse_mode="HTML")
    await query.answer()


@router.callback_query(F.data.startswith("ad:del:"))
async def ad_delete(query: CallbackQuery, db: DB):
    ad_id = int(query.data.split(":")[-1])
    ok = await db.delete_ad(query.from_user.id, ad_id)

    await query.message.answer("🗑 Reklama o‘chirildi." if ok else "❌ Reklama topilmadi.")
    # обновим список
    ads = await db.list_ads(query.from_user.id, limit=20)
    if ads:
        await query.message.answer("📂 Yangilangan ro‘yxat:", reply_markup=_ads_list_kb(ads))
    else:
        await query.message.answer("📭 Saqlangan reklama qolmadi.")
    await query.answer()


@router.callback_query(F.data.startswith("ad:send_saved:"))
async def ad_send_saved(query: CallbackQuery, db: DB, state: FSMContext):
    ad_id = int(query.data.split(":")[-1])
    ad = await db.get_ad(query.from_user.id, ad_id)
    if not ad:
        await query.message.answer("❌ Reklama topilmadi.")
        await query.answer()
        return

    buttons = json.loads(ad.buttons_json or "[]")

    await state.clear()
    await state.update_data(
        text=ad.text or "",
        photo_file_id=ad.photo_file_id or "",
        buttons=buttons,
        from_saved=True,
        saved_ad_id=ad.id,
    )
    await state.set_state(AdStates.target)
    await query.message.answer("📍 Qayerga yuboramiz?", reply_markup=_target_kb())
    await query.answer()


@router.message(AdStates.text)
async def ad_text(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("Matn yuboring (oddiy text).")
        return
    await state.update_data(text=message.text)
    await state.set_state(AdStates.photo)
    await message.answer("🖼 Rasm yuboring (photo). Rasm bo‘lmasa /skip.")


@router.message(AdStates.photo, Command("skip"))
async def ad_skip_photo(message: Message, state: FSMContext):
    await state.update_data(photo_file_id="")
    await state.set_state(AdStates.buttons)
    await message.answer(
        "🔘 Tugmalar (ixtiyoriy):\n\n"
        "Har qatorda:  Nomi | https://link\n"
        "Masalan:\n"
        "Do‘kon | https://example.com\n"
        "Telegram | https://t.me/kanal\n\n"
        "Tugma kerak bo‘lmasa /done yozing."
    )


@router.message(AdStates.photo)
async def ad_photo(message: Message, state: FSMContext):
    if not message.photo:
        await message.answer("Photo yuboring yoki /skip.")
        return
    file_id = message.photo[-1].file_id
    await state.update_data(photo_file_id=file_id)
    await state.set_state(AdStates.buttons)
    await message.answer(
        "🔘 Tugmalar (ixtiyoriy):\n\n"
        "Har qatorda:  Nomi | https://link\n"
        "Tugmalar tugasa /done."
    )


@router.message(AdStates.buttons, Command("done"))
async def ad_buttons_done(message: Message, state: FSMContext):
    await state.update_data(buttons=[])
    await state.set_state(AdStates.target)
    await message.answer("📍 Qayerga yuboramiz?", reply_markup=_target_kb())


@router.message(AdStates.buttons)
async def ad_buttons(message: Message, state: FSMContext):
    raw = message.text or ""
    buttons = _parse_buttons(raw)
    await state.update_data(buttons=buttons)
    await state.set_state(AdStates.target)
    await message.answer("📍 Qayerga yuboramiz?", reply_markup=_target_kb())


@router.callback_query(F.data.startswith("ad:target:"))
async def ad_target(query: CallbackQuery, state: FSMContext):
    target = query.data.split(":")[-1]
    await state.update_data(target=target)

    data = await state.get_data()
    text = data.get("text", "")
    photo_id = data.get("photo_file_id", "")
    buttons = data.get("buttons", [])
    kb = _buttons_kb(buttons)

    # preview
    if photo_id:
        await query.message.answer_photo(photo_id, caption=text, reply_markup=kb)
    else:
        await query.message.answer(text, reply_markup=kb, disable_web_page_preview=True)

    await query.message.answer("Tasdiqlaysizmi?", reply_markup=_confirm_kb())
    await state.set_state(AdStates.confirm)
    await query.answer()


@router.callback_query(F.data == "ad:cancel")
async def ad_cancel(query: CallbackQuery, state: FSMContext):
    await state.clear()
    await query.message.answer("❌ Bekor qilindi.")
    await query.answer()


@router.callback_query(F.data == "ad:send")
async def ad_send(query: CallbackQuery, db: DB, state: FSMContext):
    data = await state.get_data()
    target = data.get("target", "me")
    text = data.get("text", "")
    photo_id = data.get("photo_file_id", "")
    buttons = data.get("buttons", [])
    from_saved = bool(data.get("from_saved", False))

    kb = _buttons_kb(buttons)
    sent = 0
    failed = 0

    async def _send_to_chat(chat_id: int):
        nonlocal sent, failed
        try:
            if photo_id:
                await query.bot.send_photo(chat_id, photo_id, caption=text, reply_markup=kb)
            else:
                await query.bot.send_message(chat_id, text, reply_markup=kb, disable_web_page_preview=True)
            sent += 1
        except TelegramForbiddenError:
            failed += 1
            # важно: отличаем user/chat
            # если это группа — выключаем чат
            if chat_id < 0:
                await db.set_chat_active(chat_id, False)
            else:
                await db.set_user_active(chat_id, False)
        except TelegramBadRequest:
            failed += 1
        except Exception:
            failed += 1

    # 1) owner (me)
    if target == "me":
        await _send_to_chat(query.from_user.id)

    # 2) users
    if target == "users":
        user_ids = await db.list_active_users()
        for uid in user_ids:
            await _send_to_chat(uid)

    # 3) groups
    if target == "groups":
        chat_ids = await db.list_active_chats()
        for cid in chat_ids:
            await _send_to_chat(cid)

    # 4) users + groups
    if target == "users_groups":
        user_ids = await db.list_active_users()
        for uid in user_ids:
            await _send_to_chat(uid)
        chat_ids = await db.list_active_chats()
        for cid in chat_ids:
            await _send_to_chat(cid)

    await query.message.answer(f"✅ Yuborildi: {sent}\n❌ Xatolik: {failed}")

    # если реклама новая — предложим сохранить
    if not from_saved:
        await query.message.answer("💾 Reklamani saqlaysizmi?", reply_markup=_save_kb())
    else:
        await state.clear()

    await query.answer()


@router.callback_query(F.data == "ad:save")
async def ad_save(query: CallbackQuery, db: DB, state: FSMContext):
    data = await state.get_data()
    text = data.get("text", "")
    photo_id = data.get("photo_file_id", "")
    buttons = data.get("buttons", [])

    title = (text.strip().splitlines()[0] if text.strip() else "Reklama")[:80]
    ad_id = await db.save_ad(query.from_user.id, title, text, photo_id, buttons)

    await query.message.answer(f"✅ Saqlandi. ID: {ad_id}")
    await state.clear()
    await query.answer()


@router.callback_query(F.data == "ad:nosave")
async def ad_nosave(query: CallbackQuery, state: FSMContext):
    await query.message.answer("✅ Saqlanmadi.")
    await state.clear()
    await query.answer()
