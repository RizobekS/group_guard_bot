from datetime import date, datetime

from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import BigInteger, Integer, Boolean, String, UniqueConstraint, Date, DateTime, Text


class Base(DeclarativeBase):
    pass


class BotAdmin(Base):
    __tablename__ = "bot_admins"
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    added_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ChatSettings(Base):
    __tablename__ = "chat_settings"

    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    # фильтры
    block_links: Mapped[bool] = mapped_column(Boolean, default=False)      # /ssilka
    block_ads: Mapped[bool] = mapped_column(Boolean, default=False)        # /reklama
    block_arab: Mapped[bool] = mapped_column(Boolean, default=False)       # /arab
    block_swear: Mapped[bool] = mapped_column(Boolean, default=False)      # /sokin
    block_channel_posts: Mapped[bool] = mapped_column(Boolean, default=False)  # /kanalpost
    hide_service_msgs: Mapped[bool] = mapped_column(Boolean, default=False)    # /xizmat

    # реклама лимит
    ads_daily_limit: Mapped[int] = mapped_column(Integer, default=20)

    # antiflood
    antiflood_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    flood_max_msgs: Mapped[int] = mapped_column(Integer, default=15)  # /setflood
    flood_window_sec: Mapped[int] = mapped_column(Integer, default=5)

    # antiraid
    raid_limit: Mapped[int] = mapped_column(Integer, default=200)     # /limit
    raid_window_min: Mapped[int] = mapped_column(Integer, default=1)  # /oyna
    raid_close_min: Mapped[int] = mapped_column(Integer, default=10)  # /yopish

    # force add / subscribe
    force_add_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    force_add_required: Mapped[int] = mapped_column(Integer, default=0)  # /add 10
    force_text: Mapped[str] = mapped_column(String(500), default="Guruhda yozish uchun odam qo‘shing.")
    force_text_delete_sec: Mapped[int] = mapped_column(Integer, default=30)  # /text_time
    force_text_repeat_sec: Mapped[int] = mapped_column(Integer, default=0)  # /text_repeat
    force_text_repeat_delete_sec: Mapped[int] = mapped_column(Integer, default=0)  # /text_repeat_time

    linked_channel: Mapped[str] = mapped_column(String(255), default="")  # /set -> @channelusername

    # antisame
    antisame_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    antisame_minutes: Mapped[int] = mapped_column(Integer, default=120)  # /settime


class UserDailyCounter(Base):
    """
    Счетчики на пользователя в чате по дням:
    - например, сколько раз пойман на рекламе сегодня
    """
    __tablename__ = "user_daily_counters"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    day: Mapped[date] = mapped_column(Date, index=True)

    ads_hits: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (
        UniqueConstraint("chat_id", "user_id", "day", name="uq_counter_chat_user_day"),
    )

class UserMessageLog(Base):
    """
    Для anti-same: последнее сообщение (хеш) и время.
    """
    __tablename__ = "user_message_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)

    last_hash: Mapped[str] = mapped_column(String(64), default="")
    last_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("chat_id", "user_id", name="uq_msglog_chat_user"),
    )

class BadWord(Base):
    __tablename__ = "bad_words"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    word: Mapped[str] = mapped_column(String(64), index=True)  # храним нормализованное

    __table_args__ = (
        UniqueConstraint("chat_id", "word", name="uq_badword_chat_word"),
    )


class ForceAddProgress(Base):
    __tablename__ = "force_add_progress"
    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    added_count: Mapped[int] = mapped_column(Integer, default=0)


class ForceAddPriv(Base):
    __tablename__ = "force_add_priv"
    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)


class UserStrike(Base):
    __tablename__ = "user_strikes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    rule: Mapped[str] = mapped_column(String(32), index=True)  # "links" | "arab" | "swear" | "ads" ...
    count: Mapped[int] = mapped_column(Integer, default=0)
    last_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("chat_id", "user_id", "rule", name="uq_user_strike"),
    )


class ChatBotAdmin(Base):
    """
    Har bir chat (guruh) bo‘yicha bot adminlar:
    chat egasi (creator) o‘z guruhida admin tayinlay oladi.
    """
    __tablename__ = "chat_bot_admins"

    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    added_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class BotChat(Base):
    __tablename__ = "bot_chats"

    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    title: Mapped[str] = mapped_column(String(255), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class BotUser(Base):
    __tablename__ = "bot_users"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), default="")
    full_name: Mapped[str] = mapped_column(String(255), default="")

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SavedAd(Base):
    __tablename__ = "saved_ads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, index=True)

    title: Mapped[str] = mapped_column(String(120), default="")
    text: Mapped[str] = mapped_column(Text, default="")
    photo_file_id: Mapped[str] = mapped_column(String(255), default="")
    buttons_json: Mapped[str] = mapped_column(Text, default="[]")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class IgnoreUsername(Base):
    __tablename__ = "ignore_usernames"
    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), primary_key=True)

