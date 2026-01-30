import json
from datetime import date, datetime, timedelta

from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import select, delete, case
from .models import (
    Base,
    ChatSettings,
    UserDailyCounter,
    UserMessageLog,
    BotAdmin,
    BadWord,
    ForceAddProgress,
    ForceAddPriv,
    UserStrike,
    ChatBotAdmin,
    BotChat,
    SavedAd,
    BotUser,
)
class DB:
    def __init__(self, database_url: str):
        self.engine = create_async_engine(database_url, echo=False)
        self.Session = async_sessionmaker(self.engine, expire_on_commit=False, class_=AsyncSession)

    async def init_models(self):
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def touch_chat(self, chat_id: int, title: str = "") -> None:
        async with self.Session() as session:
            res = await session.execute(select(BotChat).where(BotChat.chat_id == chat_id))
            obj = res.scalar_one_or_none()
            now = datetime.utcnow()
            if not obj:
                obj = BotChat(chat_id=chat_id, title=(title or "")[:255], is_active=True, last_seen_at=now)
                session.add(obj)
            else:
                obj.title = (title or obj.title or "")[:255]
                obj.is_active = True
                obj.last_seen_at = now
            await session.commit()

    async def set_chat_active(self, chat_id: int, active: bool) -> None:
        async with self.Session() as session:
            res = await session.execute(select(BotChat).where(BotChat.chat_id == chat_id))
            obj = res.scalar_one_or_none()
            if not obj:
                obj = BotChat(chat_id=chat_id, title="", is_active=active, last_seen_at=datetime.utcnow())
                session.add(obj)
            else:
                obj.is_active = active
                obj.last_seen_at = datetime.utcnow()
            await session.commit()

    async def list_active_chats(self, limit: int = 5000) -> list[int]:
        async with self.Session() as session:
            res = await session.execute(
                select(BotChat.chat_id).where(BotChat.is_active == True).limit(limit))  # noqa: E712
            return [r[0] for r in res.all()]

    async def touch_user(self, user_id: int, username: str = "", full_name: str = "") -> None:
        async with self.Session() as session:
            res = await session.execute(select(BotUser).where(BotUser.user_id == user_id))
            obj = res.scalar_one_or_none()
            now = datetime.utcnow()
            if not obj:
                obj = BotUser(
                    user_id=user_id,
                    username=(username or "")[:64],
                    full_name=(full_name or "")[:255],
                    is_active=True,
                    last_seen_at=now,
                )
                session.add(obj)
            else:
                obj.username = (username or obj.username or "")[:64]
                obj.full_name = (full_name or obj.full_name or "")[:255]
                obj.is_active = True
                obj.last_seen_at = now
            await session.commit()

    async def set_user_active(self, user_id: int, active: bool) -> None:
        async with self.Session() as session:
            res = await session.execute(select(BotUser).where(BotUser.user_id == user_id))
            obj = res.scalar_one_or_none()
            if obj:
                obj.is_active = active
                obj.last_seen_at = datetime.utcnow()
                await session.commit()

    async def list_active_users(self, limit: int = 5000) -> list[int]:
        async with self.Session() as session:
            res = await session.execute(
                select(BotUser.user_id).where(BotUser.is_active == True).limit(limit)  # noqa: E712
            )
            return [r[0] for r in res.all()]


    async def save_ad(self, owner_id: int, title: str, text: str, photo_file_id: str,
                      buttons: list[tuple[str, str]]) -> int:
        buttons_json = json.dumps(buttons, ensure_ascii=False)
        async with self.Session() as session:
            obj = SavedAd(
                owner_id=owner_id,
                title=(title or "")[:120],
                text=text or "",
                photo_file_id=photo_file_id or "",
                buttons_json=buttons_json,
            )
            session.add(obj)
            await session.commit()
            return obj.id

    async def list_ads(self, owner_id: int, limit: int = 20) -> list[SavedAd]:
        async with self.Session() as session:
            res = await session.execute(
                select(SavedAd).where(SavedAd.owner_id == owner_id).order_by(SavedAd.id.desc()).limit(limit)
            )
            return list(res.scalars().all())

    async def get_ad(self, owner_id: int, ad_id: int) -> SavedAd | None:
        async with self.Session() as session:
            res = await session.execute(select(SavedAd).where(SavedAd.owner_id == owner_id, SavedAd.id == ad_id))
            return res.scalar_one_or_none()

    async def delete_ad(self, owner_id: int, ad_id: int) -> bool:
        async with self.Session() as session:
            res = await session.execute(select(SavedAd).where(SavedAd.owner_id == owner_id, SavedAd.id == ad_id))
            obj = res.scalar_one_or_none()
            if not obj:
                return False
            await session.delete(obj)
            await session.commit()
            return True

    async def get_or_create_settings(self, chat_id: int) -> ChatSettings:
        async with self.Session() as session:
            res = await session.execute(select(ChatSettings).where(ChatSettings.chat_id == chat_id))
            obj = res.scalar_one_or_none()
            if obj:
                return obj
            obj = ChatSettings(chat_id=chat_id)
            session.add(obj)
            await session.commit()
            return obj

    async def update_settings(self, chat_id: int, **fields) -> ChatSettings:
        async with self.Session() as session:
            res = await session.execute(select(ChatSettings).where(ChatSettings.chat_id == chat_id))
            obj = res.scalar_one()
            for k, v in fields.items():
                setattr(obj, k, v)
            await session.commit()
            return obj

    async def get_or_create_daily_counter(self, chat_id: int, user_id: int, day: date) -> UserDailyCounter:
        async with self.Session() as session:
            q = select(UserDailyCounter).where(
                UserDailyCounter.chat_id == chat_id,
                UserDailyCounter.user_id == user_id,
                UserDailyCounter.day == day,
            )
            res = await session.execute(q)
            obj = res.scalar_one_or_none()
            if obj:
                return obj
            obj = UserDailyCounter(chat_id=chat_id, user_id=user_id, day=day, ads_hits=0)
            session.add(obj)
            await session.commit()
            return obj

    async def inc_ads_hits(self, chat_id: int, user_id: int, day: date, inc: int = 1) -> int:
        async with self.Session() as session:
            q = select(UserDailyCounter).where(
                UserDailyCounter.chat_id == chat_id,
                UserDailyCounter.user_id == user_id,
                UserDailyCounter.day == day,
            )
            res = await session.execute(q)
            obj = res.scalar_one_or_none()
            if not obj:
                obj = UserDailyCounter(chat_id=chat_id, user_id=user_id, day=day, ads_hits=0)
                session.add(obj)

            obj.ads_hits += inc
            await session.commit()
            return obj.ads_hits

    # -------- antisame --------
    async def get_or_create_msglog(self, chat_id: int, user_id: int) -> UserMessageLog:
        async with self.Session() as session:
            q = select(UserMessageLog).where(
                UserMessageLog.chat_id == chat_id,
                UserMessageLog.user_id == user_id,
            )
            res = await session.execute(q)
            obj = res.scalar_one_or_none()
            if obj:
                return obj
            obj = UserMessageLog(chat_id=chat_id, user_id=user_id, last_hash="", last_at=datetime.utcnow())
            session.add(obj)
            await session.commit()
            return obj

    async def update_msglog(self, chat_id: int, user_id: int, last_hash: str, last_at: datetime) -> None:
        async with self.Session() as session:
            q = select(UserMessageLog).where(
                UserMessageLog.chat_id == chat_id,
                UserMessageLog.user_id == user_id,
            )
            res = await session.execute(q)
            obj = res.scalar_one_or_none()
            if not obj:
                obj = UserMessageLog(chat_id=chat_id, user_id=user_id, last_hash=last_hash, last_at=last_at)
                session.add(obj)
            else:
                obj.last_hash = last_hash
                obj.last_at = last_at
            await session.commit()

    async def is_bot_admin(self, user_id: int) -> bool:
        async with self.Session() as session:
            res = await session.execute(select(BotAdmin).where(BotAdmin.user_id == user_id))
            return res.scalar_one_or_none() is not None

    async def add_bot_admin(self, user_id: int) -> None:
        async with self.Session() as session:
            exists = await session.execute(select(BotAdmin).where(BotAdmin.user_id == user_id))
            if exists.scalar_one_or_none():
                return
            session.add(BotAdmin(user_id=user_id))
            await session.commit()

    async def remove_bot_admin(self, user_id: int) -> None:
        async with self.Session() as session:
            res = await session.execute(select(BotAdmin).where(BotAdmin.user_id == user_id))
            obj = res.scalar_one_or_none()
            if obj:
                await session.delete(obj)
                await session.commit()

    async def is_chat_bot_admin(self, chat_id: int, user_id: int) -> bool:
        async with self.Session() as session:
            res = await session.execute(
                select(ChatBotAdmin).where(
                    ChatBotAdmin.chat_id == chat_id,
                    ChatBotAdmin.user_id == user_id
                )
            )
            return res.scalar_one_or_none() is not None

    async def add_chat_bot_admin(self, chat_id: int, user_id: int) -> None:
        async with self.Session() as session:
            exists = await session.execute(
                select(ChatBotAdmin).where(
                    ChatBotAdmin.chat_id == chat_id,
                    ChatBotAdmin.user_id == user_id
                )
            )
            if exists.scalar_one_or_none():
                return
            session.add(ChatBotAdmin(chat_id=chat_id, user_id=user_id))
            await session.commit()

    async def remove_chat_bot_admin(self, chat_id: int, user_id: int) -> None:
        async with self.Session() as session:
            res = await session.execute(
                select(ChatBotAdmin).where(
                    ChatBotAdmin.chat_id == chat_id,
                    ChatBotAdmin.user_id == user_id
                )
            )
            obj = res.scalar_one_or_none()
            if obj:
                await session.delete(obj)
                await session.commit()

    async def add_bad_word(self, chat_id: int, word: str) -> bool:
        w = (word or "").strip().lower()
        if not w:
            return False

        async with self.Session() as session:
            res = await session.execute(
                select(BadWord).where(BadWord.chat_id == chat_id, BadWord.word == w)
            )
            if res.scalar_one_or_none():
                return False
            session.add(BadWord(chat_id=chat_id, word=w))
            await session.commit()
            return True

    async def remove_bad_word(self, chat_id: int, word: str) -> bool:
        w = (word or "").strip().lower()
        if not w:
            return False
        async with self.Session() as session:
            await session.execute(
                delete(BadWord).where(BadWord.chat_id == chat_id, BadWord.word == w)
            )
            await session.commit()
            return True

    async def list_bad_words(self, chat_id: int, limit: int = 200) -> list[str]:
        async with self.Session() as session:
            res = await session.execute(
                select(BadWord.word).where(BadWord.chat_id == chat_id).limit(limit)
            )
            return [r[0] for r in res.all()]

    # сколько добавил
    async def get_force_progress(self, chat_id: int, user_id: int) -> int:
        async with self.Session() as s:
            q = select(ForceAddProgress).where(
                ForceAddProgress.chat_id == chat_id,
                ForceAddProgress.user_id == user_id
            )
            r = await s.execute(q)
            obj = r.scalar_one_or_none()
            return obj.added_count if obj else 0

    async def inc_force_progress(self, chat_id: int, user_id: int, inc: int):
        async with self.Session() as s:
            q = select(ForceAddProgress).where(
                ForceAddProgress.chat_id == chat_id,
                ForceAddProgress.user_id == user_id
            )
            r = await s.execute(q)
            obj = r.scalar_one_or_none()
            if not obj:
                obj = ForceAddProgress(chat_id=chat_id, user_id=user_id, added_count=0)
                s.add(obj)
            obj.added_count += inc
            await s.commit()

    async def reset_force_user(self, chat_id: int, user_id: int):
        async with self.Session() as s:
            await s.execute(delete(ForceAddProgress).where(
                ForceAddProgress.chat_id == chat_id,
                ForceAddProgress.user_id == user_id
            ))
            await s.commit()

    # priv
    async def is_force_priv(self, chat_id: int, user_id: int) -> bool:
        async with self.Session() as s:
            q = select(ForceAddPriv).where(
                ForceAddPriv.chat_id == chat_id,
                ForceAddPriv.user_id == user_id
            )
            r = await s.execute(q)
            return r.scalar_one_or_none() is not None

    async def add_force_priv(self, chat_id: int, user_id: int):
        async with self.Session() as s:
            s.add(ForceAddPriv(chat_id=chat_id, user_id=user_id))
            await s.commit()

    async def remove_force_priv(self, chat_id: int, user_id: int):
        async with self.Session() as s:
            await s.execute(delete(ForceAddPriv).where(
                ForceAddPriv.chat_id == chat_id,
                ForceAddPriv.user_id == user_id
            ))
            await s.commit()

    async def clean_user_stats(self, chat_id: int, user_id: int) -> None:
        """
        Сбросить ВСЕ пользовательские счетчики (по этому чату):
        - реклама (daily counters)
        - anti-same log
        - force-add progress
        """
        async with self.Session() as s:
            await s.execute(delete(UserDailyCounter).where(
                UserDailyCounter.chat_id == chat_id,
                UserDailyCounter.user_id == user_id
            ))
            await s.execute(delete(UserMessageLog).where(
                UserMessageLog.chat_id == chat_id,
                UserMessageLog.user_id == user_id
            ))
            await s.execute(delete(ForceAddProgress).where(
                ForceAddProgress.chat_id == chat_id,
                ForceAddProgress.user_id == user_id
            ))
            await s.commit()

    async def deforce_chat(self, chat_id: int) -> None:
        """
        Полный сброс ForceAdd данных по чату:
        - прогресс
        - привилегированные
        (настройки force_add_enabled/required/text можно оставить как есть или сбросить отдельно)
        """
        async with self.Session() as s:
            await s.execute(delete(ForceAddProgress).where(ForceAddProgress.chat_id == chat_id))
            await s.execute(delete(ForceAddPriv).where(ForceAddPriv.chat_id == chat_id))
            await s.commit()

    async def hit_strike(self, chat_id: int, user_id: int, rule: str, window_sec: int) -> int:
        now = datetime.utcnow()
        cutoff = now - timedelta(seconds=window_sec)

        async with self.Session() as session:
            stmt = insert(UserStrike).values(
                chat_id=chat_id,
                user_id=user_id,
                rule=rule,
                count=1,
                last_at=now,
            ).on_conflict_do_update(
                index_elements=["chat_id", "user_id", "rule"],  # соответствует uq_user_strike
                set_={
                    # если страйк старый -> начинаем заново с 1
                    "count": case(
                        (UserStrike.last_at < cutoff, 1),
                        else_=(UserStrike.count + 1),
                    ),
                    "last_at": now,
                }
            )

            await session.execute(stmt)
            await session.commit()

            # вернуть актуальный count
            res = await session.execute(
                select(UserStrike.count).where(
                    UserStrike.chat_id == chat_id,
                    UserStrike.user_id == user_id,
                    UserStrike.rule == rule,
                )
            )
            return int(res.scalar_one())

    async def reset_strike(self, chat_id: int, user_id: int, rule: str) -> None:
        async with self.Session() as session:
            await session.execute(delete(UserStrike).where(
                UserStrike.chat_id == chat_id,
                UserStrike.user_id == user_id,
                UserStrike.rule == rule,
            ))
            await session.commit()