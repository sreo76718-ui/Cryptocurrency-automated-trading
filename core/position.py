"""
core/position.py
================
ポジション状態管理。
保有中のポジション情報を data/state/position_{symbol}.json に保存し、
再起動後も状態を引き継ぐ。複数銘柄に対応するため銘柄ごとに別ファイル。

状態:
  - open   : ポジション保有中
  - closed : ポジションなし
"""

import json
import os
import shutil
from datetime import datetime, timezone
from dataclasses import dataclass, asdict


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
    def __init__(self, config: dict, symbol: str = "btc_jpy"):
        # デフォルトTP/SL
        self.exit_cfg = config.get("exit", {})
        self.tp_ratio = self.exit_cfg.get("take_profit_ratio", 0.008)
        self.sl_ratio = self.exit_cfg.get("stop_loss_ratio",   0.004)
        # 銘柄別オーバーライド（targets[].exit_overrides）
        for t in config.get("targets", []):
            if t.get("symbol") == symbol:
                eo = t.get("exit_overrides", {})
                if "take_profit_ratio" in eo:
                    self.tp_ratio = eo["take_profit_ratio"]
                if "stop_loss_ratio" in eo:
                    self.sl_ratio = eo["stop_loss_ratio"]
                break
        os.makedirs("data/state", exist_ok=True)
        # 銘柄ごとに別ファイル（旧 position.json からの自動移行）
        self._state_path = f"data/state/position_{symbol}.json"
        self._migrate_legacy(symbol)
        self.state = self._load()

    def _migrate_legacy(self, symbol: str):
        legacy = "data/state/position.json"
        if symbol == "btc_jpy" and not os.path.exists(self._state_path) and os.path.exists(legacy):
            shutil.copy(legacy, self._state_path)

    def _load(self) -> PositionState:
        if os.path.exists(self._state_path):
            try:
                with open(self._state_path, encoding="utf-8") as f:
                    return PositionState.from_dict(json.load(f))
            except Exception:
                pass
        return PositionState()

    def _save(self):
        with open(self._state_path, "w", encoding="utf-8") as f:
            json.dump(self.state.to_dict(), f, ensure_ascii=False, indent=2)

    def is_open(self) -> bool:
        return self.state.status == "open"

    def get(self) -> PositionState:
        return self.state

    def open_position(self, symbol: str, side: str, order_id: str,
                      entry_price: float, amount: float):
        """エントリー後に呼ぶ"""
        if side == "buy":
            tp = entry_price * (1 + self.tp_ratio)
            sl = entry_price * (1 - self.sl_ratio)
        else:
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
        self.state = PositionState()
        self._save()
        return pnl

    def should_take_profit(self, current_price: float) -> bool:
        """現在価格が利確水準に達しているか"""
        if not self.is_open():
            return False
        p = self.state
        if p.side == "buy":
            return current_price >= p.take_profit
        else:
            return current_price <= p.take_profit

    def should_stop_loss(self, current_price: float) -> bool:
        """現在価格が損切り水準に達しているか"""
        if not self.is_open():
            return False
        p = self.state
        if p.side == "buy":
            return current_price <= p.stop_loss
        else:
            return current_price >= p.stop_loss
