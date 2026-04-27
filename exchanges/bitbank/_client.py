"""
exchanges/bitbank/_client.py
============================
bitbank REST API クライアント。
HMAC-SHA256 認証と HTTP リクエストを担当する内部モジュール。
executor.py からのみ使う。
"""

import hashlib
import hmac
import os
import time

import requests
from dotenv import load_dotenv

load_dotenv()

PUBLIC_BASE  = "https://public.bitbank.cc"
PRIVATE_BASE = "https://api.bitbank.cc/v1"
TIMEOUT      = 15


class BitbankClient:
    def __init__(self):
        self.api_key    = os.getenv("BITBANK_API_KEY", "")
        self.api_secret = os.getenv("BITBANK_API_SECRET", "")
        if not self.api_key or not self.api_secret:
            raise ValueError(
                "BITBANK_API_KEY / BITBANK_API_SECRET が .env に設定されていません"
            )

    # ----------------------------------------------------------------
    # 認証
    # ----------------------------------------------------------------
    def _nonce(self) -> str:
        return str(int(time.time() * 1000))

    def _sign(self, nonce: str, path_and_query: str) -> str:
        message = nonce + "/v1" + path_and_query
        return hmac.new(
            self.api_secret.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _sign_post(self, nonce: str, body: str) -> str:
        message = nonce + body
        return hmac.new(
            self.api_secret.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _auth_headers_get(self, path_and_query: str) -> dict:
        nonce = self._nonce()
        return {
            "ACCESS-KEY":       self.api_key,
            "ACCESS-NONCE":     nonce,
            "ACCESS-SIGNATURE": self._sign(nonce, path_and_query),
        }

    def _auth_headers_post(self, body: str) -> dict:
        nonce = self._nonce()
        return {
            "ACCESS-KEY":       self.api_key,
            "ACCESS-NONCE":     nonce,
            "ACCESS-SIGNATURE": self._sign_post(nonce, body),
            "Content-Type":     "application/json",
        }

    # ----------------------------------------------------------------
    # パブリックAPI
    # ----------------------------------------------------------------
    def get_ticker(self, pair: str) -> dict:
        """ティッカー取得"""
        url = f"{PUBLIC_BASE}/{pair}/ticker"
        r = requests.get(url, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        self._check(data)
        return data["data"]

    def get_candlestick(self, pair: str, candle_type: str, date_str: str) -> dict:
        """ローソク足取得"""
        url = f"{PUBLIC_BASE}/{pair}/candlestick/{candle_type}/{date_str}"
        r = requests.get(url, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        self._check(data)
        return data["data"]

    # ----------------------------------------------------------------
    # プライベートAPI
    # ----------------------------------------------------------------
    def get_assets(self) -> dict:
        """残高取得"""
        path = "/user/assets"
        r = requests.get(
            PRIVATE_BASE + path,
            headers=self._auth_headers_get(path),
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
        self._check(data)
        return data["data"]

    def create_order(self, pair: str, amount: str, side: str,
                     order_type: str, price: str | None = None) -> dict:
        """注文発行"""
        import json as _json
        body_dict = {
            "pair":       pair,
            "amount":     amount,
            "side":       side,
            "type":       order_type,
        }
        if price is not None:
            body_dict["price"] = price
        body = _json.dumps(body_dict)
        r = requests.post(
            PRIVATE_BASE + "/user/spot/order",
            headers=self._auth_headers_post(body),
            data=body,
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
        self._check(data)
        return data["data"]

    def get_order(self, pair: str, order_id: int) -> dict:
        """注文状態取得"""
        path = f"/user/spot/order?pair={pair}&order_id={order_id}"
        r = requests.get(
            PRIVATE_BASE + path,
            headers=self._auth_headers_get(path),
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
        self._check(data)
        return data["data"]

    def cancel_order(self, pair: str, order_id: int) -> dict:
        """注文キャンセル"""
        import json as _json
        body = _json.dumps({"pair": pair, "order_id": order_id})
        r = requests.post(
            PRIVATE_BASE + "/user/spot/cancel_order",
            headers=self._auth_headers_post(body),
            data=body,
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
        self._check(data)
        return data["data"]

    # ----------------------------------------------------------------
    # エラーチェック
    # ----------------------------------------------------------------
    @staticmethod
    def _check(data: dict):
        if data.get("success") != 1:
            code = data.get("data", {}).get("code", "?")
            raise RuntimeError(f"bitbank APIエラー (code={code}): {data}")
