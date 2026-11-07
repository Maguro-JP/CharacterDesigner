"""描けるまで続ける。描き直し・検品・直しの回数に上限を置かない。

前は「12 回まで」「6 回まで」の上限で止め、崩れの残った絵を渡していた。止まるのは次の 2 つだけにする。
- 利用者が止めるボタンを押した
- 同じ崩れが変わらないまま、別の手（種、模型、強さ、範囲）を一周すべて試した（それ以上回しても同じ絵になる）
どちらで止まっても、一番良かった回の絵を使う。
"""
from __future__ import annotations

import itertools


class Persist:
    """hands は試す手の並び（1 回ごとに次の手へ回す）。go_on(崩れ) が False を返したら止める"""

    def __init__(self, hands=None, stopped=lambda: False):
        self.hands = list(hands or [None])
        self.stopped = stopped
        self.k = 0
        self.same = 0
        self.last = None
        self.best_n = None
        self.reason = ""

    def hand(self):
        return self.hands[self.k % len(self.hands)]

    def rounds(self):
        """0, 1, 2, … と回の番号を出し続ける（止めるのは go_on）"""
        return itertools.count()

    def go_on(self, bad) -> bool:
        bad = list(bad or [])
        if not bad:
            self.reason = "崩れが無くなった"
            return False
        if self.stopped():
            self.reason = "止めるボタンで止めた"
            return False
        sig = tuple(sorted(set(map(str, bad))))
        improved = self.best_n is None or len(bad) < self.best_n
        if improved:
            self.best_n = len(bad)
        self.same = self.same + 1 if (sig == self.last and not improved) else 0
        self.last = sig
        self.k += 1
        if self.same >= len(self.hands):
            self.reason = f"同じ崩れが、別の手を {len(self.hands)} 通り試しても変わらなかった"
            return False
        return True


def counter(limit):
    """limit が None なら上限なしの回の番号。数なら試験のための上限（本番では None）"""
    return itertools.count() if limit is None else range(limit)
