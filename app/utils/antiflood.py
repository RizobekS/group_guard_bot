# app/utils/antiflood.py
from __future__ import annotations
from collections import deque
from dataclasses import dataclass
from time import monotonic
from typing import Deque, Dict, Tuple

@dataclass
class FloodState:
    # timestamps of last messages
    times: Deque[float]

class AntiFlood:
    """
    Sliding window:
      key = (chat_id, user_id)
      value = deque of monotonic timestamps
    """
    def __init__(self):
        self._data: Dict[Tuple[int, int], FloodState] = {}

    def hit(self, chat_id: int, user_id: int, window_sec: int, max_msgs: int) -> bool:
        """
        Returns True if user exceeded flood limit.
        """
        now = monotonic()
        key = (chat_id, user_id)
        st = self._data.get(key)
        if st is None:
            st = FloodState(times=deque())
            self._data[key] = st

        st.times.append(now)

        # clear old
        cutoff = now - float(window_sec)
        while st.times and st.times[0] < cutoff:
            st.times.popleft()

        return len(st.times) > max_msgs

    def cleanup_chat(self, chat_id: int):
        # optional
        for key in list(self._data.keys()):
            if key[0] == chat_id:
                self._data.pop(key, None)

    def clear_user(self, chat_id: int, user_id: int) -> None:
        self._data.pop((chat_id, user_id), None)
