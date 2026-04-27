"""
core/executor_interface.py
==========================
全執行層（bitbank / oanda_tokyo など）が実装するインターフェース。
core/ はこのクラスだけを知る。市場固有の実装は exchanges/ 配下に隠蔽する。
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class ExecutorInterface(Protocol):
    """
    執行層の抽象インターフェース。
    exchanges/bitbank/executor.py などがこれを実装する。
    """

    def get_balance(self) -> dict:
        """
        残高取得。
        Returns: {"jpy": float, "btc": float, "eth": float, ...}
        """
        ...

    def get_ticker(self, symbol: str) -> dict:
        """
        最新ティッカー取得。
        Returns: {"best_bid": float, "best_ask": float, "last": float}
        """
        ...

    def get_ohlcv(self, symbol: str, period: str, count: int) -> list:
        """
        OHLCVデータ取得。
        Returns: [{"open": float, "high": float, "low": float,
                   "close": float, "volume": float, "ts": int}, ...]
        period: "1min" | "5min" | "15min" | "1hour"
        """
        ...

    def place_order(self, symbol: str, side: str, amount: float,
                    order_type: str, price: float | None = None) -> dict:
        """
        注文発行。dry_run時はモックデータを返す。
        side: "buy" | "sell"
        order_type: "limit" | "market"
        Returns: {"order_id": str, "status": str, "side": str,
                  "price": float, "amount": float, "is_dry_run": bool}
        """
        ...

    def get_order_status(self, order_id: str, symbol: str) -> dict:
        """
        注文状態確認。
        Returns: {"order_id": str, "status": "open"|"filled"|"cancelled",
                  "filled_amount": float, "avg_price": float}
        """
        ...

    def cancel_order(self, order_id: str, symbol: str) -> bool:
        """注文キャンセル。成功でTrue"""
        ...

    def is_dry_run(self) -> bool:
        """dry_runモードか否か"""
        ...
