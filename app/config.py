from dataclasses import dataclass
import os
from dotenv import load_dotenv

load_dotenv()

@dataclass(frozen=True)
class Config:
    bot_token: str
    database_url: str
    video_url: str
    owner_username: str

def load_config() -> Config:
    token = os.getenv("BOT_TOKEN", "").strip()
    db_url = os.getenv("DATABASE_URL", "").strip()
    video_url = os.getenv("VIDEO_GUIDE_URL", "").strip()
    owner_username = os.getenv("OWNER_USERNAME", "").lstrip("@").lower()

    if not token:
        raise RuntimeError("BOT_TOKEN is empty in .env")

    if not owner_username:
        raise RuntimeError("OWNER_USERNAME is empty")

    return Config(
        bot_token=token,
        database_url=db_url,
        video_url=video_url,
        owner_username=owner_username,
    )
