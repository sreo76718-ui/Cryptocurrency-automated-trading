"""
exchanges/bitbank/fee.py
========================
bitbank の手数料計算。

bitbank 手数料（2025年時点）:
  BTC/JPY  メイカー: -0.02%（リベート）  テイカー: +0.12%
  ETH/JPY  メイカー: -0.02%（リベート）  テイカー: +0.12%
  XRP/JPY  メイカー:  0.00%             テイカー: +0.12%

メイカー = 指値注文（板に並ぶ）
テイカー = 成行注文（板を食う）

手数料はマイナス（リベート）になることもある点に注意。
"""


# 銘柄別手数料率（比率）
FEE_TABLE = {
    "btc_jpy": {"maker": -0.0002, "taker": 0.0012},
    "eth_jpy": {"maker": -0.0002, "taker": 0.0012},
    "xrp_jpy": {"maker":  0.0000, "taker": 0.0012},
    # 他の銘柄はテイカー0.12%で統一しておく
    "_default": {"maker": 0.0000, "taker": 0.0012},
}


class FeeCalculator:
    def __init__(self, config: dict):
        cfg = config.get("bitbank", {})
        self.default_order_type = cfg.get("order_type_default", "limit")

    def calc_fee(self, symbol: str, amount_btc: float,
                 price_jpy: float, order_type: str) -> float:
        """
        手数料を JPY で返す（マイナスはリベート = 受け取り）。
        order_type: "limit" → maker  /  "market" → taker
        """
        table = FEE_TABLE.get(symbol, FEE_TABLE["_default"])
        role  = "maker" if order_type == "limit" else "taker"
        rate  = table[role]
        trade_amount_jpy = amount_btc * price_jpy
        return trade_amount_jpy * rate

    def effective_pnl(self, gross_pnl: float,
                      entry_symbol: str, entry_amount: float,
                      entry_price: float, entry_type: str,
                      exit_symbol: str,  exit_amount: float,
                      exit_price: float, exit_type: str) -> float:
        """
        手数料を差し引いた実質損益を返す。
        エントリー手数料 + 決済手数料 を gross_pnl から引く。
        """
        entry_fee = self.calc_fee(entry_symbol, entry_amount, entry_price, entry_type)
        exit_fee  = self.calc_fee(exit_symbol,  exit_amount,  exit_price,  exit_type)
        return gross_pnl - entry_fee - exit_fee
