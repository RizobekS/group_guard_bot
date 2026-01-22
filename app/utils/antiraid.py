# app/utils/antiraid.py
from __future__ import annotations
from collections import deque
from dataclasses import dataclass
from time import monotonic
from typing import Deque, Dict

@dataclass
class RaidState:
    joins: Deque[float]
    locked_until: float = 0.0

class AntiRaid:
    def __init__(self):
        self._chats: Dict[int, RaidState] = {}

    def hit(self, chat_id: int, join_count: int, window_sec: int, limit: int) -> bool:
        if limit <= 0:
            return False

        now = monotonic()
        st = self._chats.get(chat_id)
        if st is None:
            st = RaidState(joins=deque())
            self._chats[chat_id] = st

        # если уже закрыт, не дергаем повторно
        if st.locked_until and now < st.locked_until:
            return False

        for _ in range(max(1, join_count)):
            st.joins.append(now)

        cutoff = now - float(window_sec)
        while st.joins and st.joins[0] < cutoff:
            st.joins.popleft()

        return len(st.joins) >= limit

    def set_locked(self, chat_id: int, seconds: int):
        now = monotonic()
        st = self._chats.get(chat_id)
        if st is None:
            st = RaidState(joins=deque())
            self._chats[chat_id] = st
        st.locked_until = now + float(seconds)

    def clear(self, chat_id: int):
        self._chats.pop(chat_id, None)
