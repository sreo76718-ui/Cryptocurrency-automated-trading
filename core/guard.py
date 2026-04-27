"""
core/guard.py
=============
取引停止制御。以下の条件をチェックして取引可否を判定する。

  1. 日次最大損失を超えた
  2. 連続損失が上限に達した
  3. 同方向への連続エントリーが上限に達した

状態は data/state/guard_state.json に保存し、再起動後も引き継ぐ。
日付が変わると日次カウンタを自動リセットする。
"""

import json
import os
from datetime import date, datetime


GUARD_STATE_PATH = "data/state/guard_state.json"


class GuardState:
    def __init__(self):
        self.date: str = str(date.today())
        self.daily_pnl: float = 0.0          # 当日の累計損益
        self.consecutive_loss: int = 0        # 現在の連続損失カウント
        self.max_consec_loss: int = 0         # 当日の最大連続損失
        self.same_direction_count: int = 0    # 同方向連続エントリー数
        self.last_side: str = ""              # 直前のエントリー方向
        self.stopped: bool = False            # 当日停止フラグ
        self.stop_reason: str = ""
        self.trades: int = 0
        self.wins: int = 0
        self.losses: int = 0

    def to_dict(self) -> dict:
        return self.__dict__.copy()

    @classmethod
    def from_dict(cls, d: dict) -> "GuardState":
        s = cls()
        for k, v in d.items():
            if hasattr(s, k):
                setattr(s, k, v)
        return s


class Guard:
    def __init__(self, config: dict):
        cfg = config.get("guard", {})
        self.max_daily_loss      = abs(cfg.get("max_daily_loss_jpy", 5000))
        self.max_consec_loss     = cfg.get("max_consecutive_loss", 3)
        self.same_dir_limit      = cfg.get("same_direction_limit", 2)
        os.makedirs("data/state", exist_ok=True)
        self.state = self._load()

    # ----------------------------------------------------------------
    # 状態の読み書き
    # ----------------------------------------------------------------
    def _load(self) -> GuardState:
        if os.path.exists(GUARD_STATE_PATH):
            try:
                with open(GUARD_STATE_PATH, encoding="utf-8") as f:
                    return GuardState.from_dict(json.load(f))
            except Exception:
                pass
        return GuardState()

    def _save(self):
        with open(GUARD_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(self.state.to_dict(), f, ensure_ascii=False, indent=2)

    # ----------------------------------------------------------------
    # 日次リセット（日付が変わったら呼ぶ）
    # ----------------------------------------------------------------
    def reset_if_new_day(self):
        today = str(date.today())
        if self.state.date != today:
            self.state = GuardState()
            self.state.date = today
            self._save()
            return True
        return False

    # ----------------------------------------------------------------
    # 取引可否チェック
    # ----------------------------------------------------------------
    def can_trade(self) -> tuple[bool, str]:
        """
        取引可能か判定。
        Returns: (True, "") or (False, "停止理由")
        """
        if self.state.stopped:
            return False, f"当日停止済み: {self.state.stop_reason}"
        if self.state.daily_pnl <= -self.max_daily_loss:
            self._stop(f"日次最大損失到達: {self.state.daily_pnl:,.0f}円")
            return False, self.state.stop_reason
        if self.state.consecutive_loss >= self.max_consec_loss:
            self._stop(f"連続損失 {self.state.consecutive_loss} 回到達")
            return False, self.state.stop_reason
        return True, ""

    def can_enter_side(self, side: str) -> tuple[bool, str]:
        """同方向連続エントリー制限チェック"""
        if (self.state.last_side == side and
                self.state.same_direction_count >= self.same_dir_limit):
            return False, f"同方向（{side}）連続 {self.state.same_direction_count} 回制限"
        return True, ""

    # ----------------------------------------------------------------
    # 結果の記録
    # ----------------------------------------------------------------
    def record_trade(self, pnl: float, side: str):
        """決済後に呼ぶ。PnLを記録して状態を更新する"""
        self.state.daily_pnl += pnl
        self.state.trades    += 1

        if pnl >= 0:
            self.state.wins             += 1
            self.state.consecutive_loss  = 0  # 連敗リセット
        else:
            self.state.losses           += 1
            self.state.consecutive_loss += 1
            self.state.max_consec_loss = max(
                self.state.max_consec_loss, self.state.consecutive_loss
            )

        # 同方向カウント更新
        if side == self.state.last_side:
            self.state.same_direction_count += 1
        else:
            self.state.same_direction_count = 1
        self.state.last_side = side

        self._save()

    # ----------------------------------------------------------------
    # 停止処理
    # ----------------------------------------------------------------
    def _stop(self, reason: str):
        self.state.stopped     = True
        self.state.stop_reason = reason
        self._save()

    def manual_stop(self, reason: str = "手動停止"):
        self._stop(reason)

    # ----------------------------------------------------------------
    # 統計情報取得
    # ----------------------------------------------------------------
    def get_stats(self) -> dict:
        s = self.state
        total = s.wins + s.losses
        win_rate = (s.wins / total * 100) if total > 0 else 0.0
        return {
            "trades":          s.trades,
            "wins":            s.wins,
            "losses":          s.losses,
            "win_rate":        win_rate,
            "total_pnl":       s.daily_pnl,
            "max_consec_loss": s.max_consec_loss,
        }
