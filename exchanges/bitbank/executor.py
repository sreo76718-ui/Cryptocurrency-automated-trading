"""
exchanges/bitbank/executor.py
=============================
ExecutorInterface の bitbank 実装。
core/ はこのクラスを通じてのみ bitbank API を呼ぶ。

dry_run モード:
  - get_ticker / get_ohlcv は実際のAPIを呼ぶ（価格データは本物）
  - place_order はAPIを呼ばずにモックデータを返す
  - get_balance はモック残高を返す
"""

import datetime
import time
import uuid

from exchanges.bitbank._client import BitbankClient
from exchanges.bitbank.fee import FeeCalculator
from exchanges.bitbank.fill import FillChecker


class BitbankExecutor:
    def __init__(self, config: dict):
        self.config   = config
        self._dry_run = config.get("mode", {}).get("run", "dry_run") == "dry_run"
        self._cfg_bb  = config.get("bitbank", {})

        # dry_run でも API疎通エラーを早めに検出するためクライアントは常に作る
        self._client  = BitbankClient()
        self._fee     = FeeCalculator(config)
        self._filler  = FillChecker(config)

    # ----------------------------------------------------------------
    # ExecutorInterface の実装
    # ----------------------------------------------------------------

    def is_dry_run(self) -> bool:
        return self._dry_run

    def get_balance(self) -> dict:
        """
        残高取得。
        dry_run 時はモック残高（JPY: 100,000 / BTC: 0）を返す。
        """
        if self._dry_run:
            return {"jpy": 100_000.0, "btc": 0.0, "eth": 0.0, "xrp": 0.0}

        assets_data = self._client.get_assets()
        result = {}
        for a in assets_data["assets"]:
            result[a["asset"]] = float(a["free_amount"])
        return result

    def get_ticker(self, symbol: str) -> dict:
        """ティッカー取得（dry_run でも実データ）"""
        raw = self._client.get_ticker(symbol)
        return {
            "best_bid": float(raw["buy"]),
            "best_ask": float(raw["sell"]),
            "last":     float(raw["last"]),
            "high":     float(raw["high"]),
            "low":      float(raw["low"]),
            "vol":      float(raw["vol"]),
        }

    def get_ohlcv(self, symbol: str, period: str = "1min", count: int = 60) -> list:
        """
        OHLCVデータ取得（dry_run でも実データ）。
        Returns: [{"open", "high", "low", "close", "volume", "ts"}, ...]
        新しい順に count 本返す。

        注意: UTC基準ではなくJST基準で日付を計算する。
        UTC 0:00（JST 9:00）直後にbitbankの当日データが存在しない場合、
        前日データにフォールバックする。
        """
        JST = datetime.timezone(datetime.timedelta(hours=9))
        now_jst   = datetime.datetime.now(JST)
        date_str  = now_jst.strftime("%Y%m%d")
        yesterday = (now_jst - datetime.timedelta(days=1)).strftime("%Y%m%d")

        # 当日データ取得（404なら前日のみで代替）
        candles = []
        try:
            raw     = self._client.get_candlestick(symbol, period, date_str)
            candles = raw["candlestick"][0]["ohlcv"]
        except Exception:
            pass  # 日付変わり直後でデータ未生成の場合は空のまま続行

        # 本数が足りない場合は前日分を先頭に追加
        if len(candles) < count:
            try:
                raw_prev     = self._client.get_candlestick(symbol, period, yesterday)
                prev_candles = raw_prev["candlestick"][0]["ohlcv"]
                candles      = prev_candles + candles
            except Exception:
                pass

        result = []
        for c in candles[-count:]:
            result.append({
                "open":   float(c[0]),
                "high":   float(c[1]),
                "low":    float(c[2]),
                "close":  float(c[3]),
                "volume": float(c[4]),
                "ts":     int(c[5]),
            })
        return result

    def place_order(self, symbol: str, side: str, amount: float,
                    order_type: str, price: float | None = None) -> dict:
        """
        注文発行。
        dry_run: APIを呼ばずモックデータを返す。
        live:    実際にAPIを呼ぶ。
        """
        if self._dry_run:
            mock_id = f"DRY-{uuid.uuid4().hex[:8].upper()}"
            return {
                "order_id":   mock_id,
                "status":     "filled",   # dry_runは即約定扱い
                "side":       side,
                "symbol":     symbol,
                "order_type": order_type,
                "price":      price or 0.0,
                "amount":     amount,
                "is_dry_run": True,
            }

        # live モード
        price_str = str(int(price)) if price else None
        amount_str = f"{amount:.6f}"
        raw = self._client.create_order(
            pair       = symbol,
            amount     = amount_str,
            side       = side,
            order_type = order_type,
            price      = price_str,
        )
        return {
            "order_id":   str(raw["order_id"]),
            "status":     raw["status"],
            "side":       raw["side"],
            "symbol":     symbol,
            "order_type": raw["type"],
            "price":      float(raw.get("price", 0) or 0),
            "amount":     float(raw.get("start_amount", amount)),
            "is_dry_run": False,
        }

    def get_order_status(self, order_id: str, symbol: str) -> dict:
        """注文状態確認"""
        if self._dry_run:
            return {
                "order_id":      order_id,
                "status":        "filled",
                "filled_amount": 0.0,
                "avg_price":     0.0,
            }
        raw = self._client.get_order(symbol, int(order_id))
        status_map = {
            "UNFILLED":             "open",
            "PARTIALLY_FILLED":     "open",
            "FULLY_FILLED":         "filled",
            "CANCELED_UNFILLED":    "cancelled",
            "CANCELED_PARTIALLY_FILLED": "cancelled",
        }
        return {
            "order_id":      str(raw["order_id"]),
            "status":        status_map.get(raw["status"], raw["status"]),
            "filled_amount": float(raw.get("executed_amount", 0) or 0),
            "avg_price":     float(raw.get("average_price", 0) or 0),
        }

    def cancel_order(self, order_id: str, symbol: str) -> bool:
        """注文キャンセル"""
        if self._dry_run:
            return True
        try:
            self._client.cancel_order(symbol, int(order_id))
            return True
        except Exception:
            return False

    # ----------------------------------------------------------------
    # 約定待ち（fill.py への委譲）
    # ----------------------------------------------------------------
    def wait_for_fill(self, order_id: str, symbol: str) -> dict:
        """
        注文が約定するまでポーリングして待つ。
        タイムアウトしたらキャンセルして None を返す。
        """
        return self._filler.wait(self, order_id, symbol)
