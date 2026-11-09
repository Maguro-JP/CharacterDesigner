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

    # 良くならない回がこの数だけ続いたら、一番良かった回の絵で終える。描き直しても良くならない絵を何十回も描き直し、
    # 1 枚に何十倍も時間がかかって、描けなくなっていた（2026-11-09）
    NO_GAIN = 2

    def go_on(self, bad) -> bool:
        # 「検品できなかった」は描き直しても直らない（部品が無い・読めない）。知らせには残すが、描き直しの理由にしない
        bad = [b for b in (bad or []) if not str(b).startswith("検品できなかった")]
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
        from chatdraw import debuglog
        self.no_gain = 0 if improved else getattr(self, "no_gain", 0) + 1
        if not debuglog.lifted("steps"):   # デバッグモードで工程の上限を外したときは止めない
            if self.same >= len(self.hands):
                self.reason = f"同じ崩れが、別の手を {len(self.hands)} 通り試しても変わらなかった"
                return False
            if self.no_gain >= self.NO_GAIN:
                self.reason = f"描き直しても {self.NO_GAIN} 回続けて良くならなかったので、一番良かった絵を使う"
                return False
        return True


def counter(limit):
    """limit が None なら上限なしの回の番号。数なら試験のための上限（本番では None）"""
    return itertools.count() if limit is None else range(limit)
