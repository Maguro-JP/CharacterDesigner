"""描けるまで続ける。描き直し・検品・直しの回数に上限を置かない。

前は「12 回まで」「6 回まで」の上限で止め、崩れの残った絵を渡していた。止まるのは次の 3 つだけにする。
- 利用者が止めるボタンを押した
- 崩れの数が、別の手（種、模型、強さ、範囲）を一周すべて試しても一番良かった回より減らなかった（回しても良くならない）
- 残った崩れが「検品できなかった」（部品が無い・読めない）だけで、それを理由に 1 回描き直しても変わらなかった
どこで止まっても、一番良かった回の絵を使い、残った崩れは知らせる（「描けませんでした」にしない）。

前の形は、崩れの言葉の並びが前の回と全く同じときだけ数えていた。種を替えると言葉が少しずつ変わるので数が溜まらず、
崩れの減らない描き直しと、部品が無くて検品できない絵の描き直しが、止めるボタンを押すまで続いた。
"""
from __future__ import annotations

import itertools

UNCHECKED = "検品できなかった"


class Persist:
    """hands は試す手の並び。崩れが減った回は同じ手を続け、減らなかった回は次の手へ替える。go_on(崩れ) が False なら止める"""

    def __init__(self, hands=None, stopped=lambda: False):
        self.hands = list(hands or [None])
        self.stopped = stopped
        self.k = 0
        self.stale = 0          # 一番良かった回より崩れが減らなかった回が、続けて何回か
        self.best_n = None
        self.seen_unchecked: dict = {}   # 検品できなかった理由 → それで描き直した回数
        self.reason = ""
        self.last = None

    def hand(self):
        return self.hands[self.k % len(self.hands)]

    def rounds(self):
        """0, 1, 2, … と回の番号を出し続ける（止めるのは go_on）"""
        return itertools.count()

    def go_on(self, bad) -> bool:
        bad = [str(b) for b in (bad or [])]
        if not bad:
            self.reason = "崩れが無くなった"
            return False
        if self.stopped():
            self.reason = "止めるボタンで止めた"
            return False
        real = [b for b in bad if not b.startswith(UNCHECKED)]
        unread = [b for b in bad if b.startswith(UNCHECKED)]
        fresh = [u for u in unread if self.seen_unchecked.get(u, 0) < 1]   # 同じ理由での描き直しは 1 回だけ
        for u in unread:
            self.seen_unchecked[u] = self.seen_unchecked.get(u, 0) + 1
        self.last = tuple(sorted(set(bad)))
        if not real and not fresh:
            self.reason = "検品できなかった物は、1 回描き直しても変わらなかった（崩れとして知らせます）"
            return False
        n = len(real) + len(fresh)
        improved = self.best_n is None or n < self.best_n
        if improved:
            self.best_n, self.stale = n, 0
        else:
            self.stale += 1
            self.k += 1     # 減らなかったので手を替える
        from chatdraw import debuglog
        if self.stale >= len(self.hands) and not debuglog.lifted("steps"):   # デバッグモードで工程の上限を外したときは止めない
            self.reason = f"崩れの数が、別の手を {len(self.hands)} 通り試しても減らなかった"
            return False
        return True


def counter(limit):
    """limit が None なら上限なしの回の番号。数なら試験のための上限（本番では None）"""
    return itertools.count() if limit is None else range(limit)
