"""
core/signal.py
==============
シグナルの型定義。
strategy.py が生成し、main.py が受け取って executor に渡す。
"""

from dataclasses import dataclass, field
from enum import Enum


class SignalType(Enum):
    BUY  = "buy"   # 新規買いエントリー
    SELL = "sell"  # 新規売りエントリー（将来対応）
    EXIT = "exit"  # ポジション決済
    HOLD = "hold"  # 様子見（何もしない）


@dataclass
class Signal:
    type: SignalType
    strength: float = 0.0        # 0.0〜1.0。強いほど積極的
    reason: str = ""             # ログ・通知用の理由文字列
    raw: dict = field(default_factory=dict)  # デバッグ用の計算値

    def is_entry(self) -> bool:
        return self.type in (SignalType.BUY, SignalType.SELL)

    def is_exit(self) -> bool:
        return self.type == SignalType.EXIT

    def is_hold(self) -> bool:
        return self.type == SignalType.HOLD

    def __str__(self) -> str:
        return f"Signal({self.type.value}, strength={self.strength:.2f}, reason={self.reason})"
