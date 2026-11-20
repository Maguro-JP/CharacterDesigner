"""描画処理から画面へ渡す、構造化された進行イベント。

表示文の解析に依存せず、処理側が実際の工程境界で発行する。
画像本体は別の preview 経路で渡し、イベントには重い画像データを載せない。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal

EventKind = Literal[
    "phase_started", "drawing", "inspection", "correction",
    "reinspection", "phase_completed", "blocked", "completed",
]


@dataclass(frozen=True)
class DrawEvent:
    kind: EventKind
    message: str
    phase: str | None = None
    index: int | None = None
    total: int | None = None
    details: dict[str, Any] = field(default_factory=dict)


def emit_event(callback: Callable[[DrawEvent], None] | None, kind: EventKind, message: str,
               phase: str | None = None, index: int | None = None, total: int | None = None,
               **details: Any) -> None:
    """コールバック未設定でも描画を止めず、イベント通知の失敗も描画本体へ波及させない。"""
    if callback is None:
        return
    try:
        callback(DrawEvent(kind, message, phase, index, total, details))
    except Exception:
        pass
