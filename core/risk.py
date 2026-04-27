"""
core/risk.py
============
資金管理 — 1回の発注サイズを計算する。

方針:
  - 残高の max_order_ratio（デフォルト2%）を超えない
  - 最低発注額 min_order_jpy を下回る場合は発注しない
  - 発注数量は BTC 単位で返す（bitbank の最小発注単位: 0.0001 BTC）
"""


class RiskManager:
    def __init__(self, config: dict):
        cfg = config.get("risk", {})
        self.max_order_ratio = cfg.get("max_order_ratio", 0.02)
        self.min_order_jpy   = cfg.get("min_order_jpy", 1000)
        self.min_btc_unit    = 0.0001  # bitbankの最小発注単位

    def calc_order_amount(self, balance_jpy: float, price: float) -> float:
        """
        発注数量（BTC）を計算する。
        発注不可の場合は 0.0 を返す。
        """
        if price <= 0:
            return 0.0

        # 使える金額の上限（残高の max_order_ratio）
        max_jpy = balance_jpy * self.max_order_ratio

        if max_jpy < self.min_order_jpy:
            return 0.0  # 最低発注額に届かない

        # BTC 換算
        amount = max_jpy / price

        # bitbank 最小単位に切り捨て
        amount = self._floor(amount, self.min_btc_unit)

        # 最終チェック：切り捨て後の発注額が最低額を満たすか
        if amount * price < self.min_order_jpy:
            return 0.0

        return amount

    @staticmethod
    def _floor(value: float, unit: float) -> float:
        """unit 単位で切り捨て"""
        return int(value / unit) * unit

    def validate(self, amount: float, price: float) -> tuple[bool, str]:
        """発注前のバリデーション"""
        if amount <= 0:
            return False, "発注数量が0以下"
        if amount * price < self.min_order_jpy:
            return False, f"発注額({amount * price:.0f}円)が最低額({self.min_order_jpy}円)未満"
        if amount < self.min_btc_unit:
            return False, f"発注数量({amount})がbitbank最小単位({self.min_btc_unit})未満"
        return True, ""
