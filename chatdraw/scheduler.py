"""アプリの中の予約（「10 分後に描いて」「毎晩描いて」）。

アプリが開いている間だけ、30 秒ごとに時刻を見て、来た予約の頼みをチャットに送り直す。予約の一覧は利用者ごとの設定（QSettings）に
残し、開き直しても消えない（閉じていた間に過ぎた一回きりの予約は、開いたときに 1 回だけ行う）。
OS の予約（タスク スケジューラ、cron）には登録しない。アプリの外で模型を動かすと、何が動いているのか利用者から見えないため。
"""
from __future__ import annotations

import json
import time
import uuid

from PySide6.QtCore import QObject, QSettings, QTimer, Signal

KEY = "chat_schedule"
TICK_MS = 30_000


class Scheduler(QObject):
    fire = Signal(str)   # 来た予約の頼み（チャットにそのまま送る文）

    def __init__(self, store: QSettings | None = None, parent=None, clock=time.time):
        super().__init__(parent)
        self.store = store or QSettings("CharacterDesigner", "chatdraw-settings")
        self.clock = clock
        self.timer = QTimer(self)
        self.timer.setInterval(TICK_MS)
        self.timer.timeout.connect(self.tick)
        self.timer.start()

    def jobs(self) -> list[dict]:
        try:
            v = json.loads(self.store.value(KEY, "[]") or "[]")
            return v if isinstance(v, list) else []
        except (TypeError, ValueError):
            return []

    def _save(self, jobs: list[dict]):
        self.store.setValue(KEY, json.dumps(jobs, ensure_ascii=False))

    def add(self, text: str, after_min: int | None = None, daily: tuple | None = None) -> dict:
        from chatdraw.chatplan import next_daily
        now = self.clock()
        at = next_daily(*daily, now=now) if daily else now + 60 * (after_min or 0)
        job = {"id": uuid.uuid4().hex[:8], "text": text, "at": at, "daily": list(daily) if daily else None}
        self._save(self.jobs() + [job])
        return job

    def remove(self, job_id: str) -> bool:
        jobs = self.jobs()
        left = [j for j in jobs if j.get("id") != job_id]
        self._save(left)
        return len(left) != len(jobs)

    def clear(self):
        self._save([])

    def tick(self):
        """来た予約を送る。毎日の物は次の日へ送り、一回きりの物は消す"""
        from chatdraw.chatplan import next_daily
        now = self.clock()
        keep, due = [], []
        for j in self.jobs():
            if float(j.get("at", 0)) <= now:
                due.append(j)
                if j.get("daily"):
                    keep.append(dict(j, at=next_daily(*j["daily"], now=now)))
            else:
                keep.append(j)
        if due:
            self._save(keep)
        for j in due:
            self.fire.emit(j["text"])
        return due

    def summary(self) -> str:
        jobs = self.jobs()
        if not jobs:
            return "予約はありません"
        lines = []
        for j in jobs:
            when = (f"毎日 {j['daily'][0]:02d}:{j['daily'][1]:02d}" if j.get("daily")
                    else time.strftime("%m/%d %H:%M", time.localtime(float(j["at"]))))
            lines.append(f"{when}  {j['text']}")
        return "\n".join(lines)
