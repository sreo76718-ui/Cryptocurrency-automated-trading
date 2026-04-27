"""
core/position.py
================
ポジション状態管理。
保有中のポジション情報を data/state/position.json に保存し、
再起動後も状態を引き継ぐ。

状態:
  - open   : ポジション保有中
  - closed : ポジションなし
"""

import json
import os
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict


POSITION_STATE_PATH = "data/state/position.json"


@dataclass
class PositionState:
    status: str = "closed"       # "open" | "closed"
    side: str = ""               # "buy" | "sell"
    symbol: str = ""
    order_id: str = ""
    entry_price: float = 0.0
    amount: float = 0.0
    entry_ts: str = ""
    take_profit: float = 0.0    # 利確価格
    stop_loss: float = 0.0      # 損切り価格

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "PositionState":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class PositionManager:
    def __init__(self, config: dict):
        self.exit_cfg = config.get("exit", {})
        self.tp_ratio = self.exit_cfg.get("take_profit_ratio", 0.008)
        self.sl_ratio = self.exit_cfg.get("stop_loss_ratio",   0.004)
        os.makedirs("data/state", exist_ok=True)
        self.state = self._load()

    # ----------------------------------------------------------------
    # 読み書き
    # ----------------------------------------------------------------
    def _load(self) -> PositionState:
        if os.path.exists(POSITION_STATE_PATH):
            try:
                with open(POSITION_STATE_PATH, encoding="utf-8") as f:
                    return PositionState.from_dict(json.load(f))
            except Exception:
                pass
        return PositionState()

    def _save(self):
        with open(POSITION_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(self.state.to_dict(), f, ensure_ascii=False, indent=2)

    # ----------------------------------------------------------------
    # 状態確認
    # ----------------------------------------------------------------
    def is_open(self) -> bool:
        return self.state.status == "open"

    def get(self) -> PositionState:
        return self.state

    # ----------------------------------------------------------------
    # ポジション操作
    # ----------------------------------------------------------------
    def open_position(self, symbol: str, side: str, order_id: str,
                      entry_price: float, amount: float):
        """エントリー後に呼ぶ"""
        if side == "buy":
            tp = entry_price * (1 + self.tp_ratio)
            sl = entry_price * (1 - self.sl_ratio)
        else:  # sell
            tp = entry_price * (1 - self.tp_ratio)
            sl = entry_price * (1 + self.sl_ratio)

        self.state = PositionState(
            status      = "open",
            side        = side,
            symbol      = symbol,
            order_id    = order_id,
            entry_price = entry_price,
            amount      = amount,
            entry_ts    = datetime.now(timezone.utc).isoformat(),
            take_profit = tp,
            stop_loss   = sl,
        )
        self._save()
        return self.state

    def close_position(self, exit_price: float) -> float:
        """決済後に呼ぶ。粗利を返す（手数料未控除）"""
        if not self.is_open():
            return 0.0

        p = self.state
        if p.side == "buy":
            pnl = (exit_price - p.entry_price) * p.amount
        else:
            pnl = (p.entry_price - exit_price) * p.amount

        self.state = PositionState()  # closed
        self._save()
        return pnl

    # ----------------------------------------------------------------
    # 利確・損切りチェック
    # ----------------------------------------------------------------
    def should_take_profit(self, current_price: float) -> bool:
        if not self.is_open():
            return False
        p = self.state
        if p.side == "buy":
            return current_price >= p.take_profit
        else:
            return current_price <= p.take_profit

    def should_stop_loss(self, current_price: float) -> bool:
        if not self.is_open():
            return False
        p = self.state
        if p.side == "buy":
            return current_price <= p.stop_loss
        else:
            return current_price >= p.stop_loss
