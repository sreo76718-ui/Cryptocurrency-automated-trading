"""
scripts/check_api.py
====================
bitbank API の疎通確認スクリプト。
最初に必ずこれを動かして、APIキーと接続が正常か確認する。

使い方:
    python scripts/check_api.py

チェック項目:
    [1] パブリックAPI — ticker 取得（認証不要）
    [2] パブリックAPI — OHLCV 取得（認証不要）
    [3] プライベートAPI — 残高取得（APIキー認証あり）
    [4] プライベートAPI — アクティブな注文一覧取得
"""

import hashlib
import hmac
import os
import sys
import time

import requests
from dotenv import load_dotenv

# .env を読み込む（スクリプトの親ディレクトリを探す）
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

# ============================================================
# 定数
# ============================================================
PUBLIC_BASE  = "https://public.bitbank.cc"
PRIVATE_BASE = "https://api.bitbank.cc/v1"
SYMBOL       = "btc_jpy"          # チェック対象の銘柄
TIMEOUT      = 10                  # リクエストタイムアウト（秒）

# APIキー（.env から読み込む）
API_KEY    = os.getenv("BITBANK_API_KEY", "")
API_SECRET = os.getenv("BITBANK_API_SECRET", "")


# ============================================================
# 認証ヘルパー
# ============================================================
def _nonce() -> str:
    """ミリ秒単位のUnixタイムスタンプ文字列を返す"""
    return str(int(time.time() * 1000))


def _sign(nonce: str, path_and_query: str) -> str:
    """
    bitbank プライベートAPI の署名を生成する。
    署名対象: nonce + "/v1" + path_and_query
    """
    message = nonce + "/v1" + path_and_query
    return hmac.new(
        API_SECRET.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _private_headers(nonce: str, path_and_query: str) -> dict:
    return {
        "ACCESS-KEY":       API_KEY,
        "ACCESS-NONCE":     nonce,
        "ACCESS-SIGNATURE": _sign(nonce, path_and_query),
        "Content-Type":     "application/json",
    }


# ============================================================
# パブリックAPI チェック
# ============================================================
def check_ticker() -> bool:
    """[1] ティッカー取得（認証不要）"""
    print("\n[1] パブリックAPI — ticker 取得")
    url = f"{PUBLIC_BASE}/{SYMBOL}/ticker"
    try:
        r = requests.get(url, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        if data.get("success") != 1:
            print(f"    ✗ レスポンスエラー: {data}")
            return False
        t = data["data"]
        print(f"    ✓ 取得成功")
        print(f"      銘柄  : {SYMBOL.upper()}")
        print(f"      最終価格: {float(t['last']):,.0f} JPY")
        print(f"      買値  : {float(t['buy']):,.0f} JPY")
        print(f"      売値  : {float(t['sell']):,.0f} JPY")
        print(f"      高値  : {float(t['high']):,.0f} JPY")
        print(f"      安値  : {float(t['low']):,.0f} JPY")
        return True
    except requests.exceptions.ConnectionError:
        print("    ✗ 接続失敗: ネットワークを確認してください")
        return False
    except Exception as e:
        print(f"    ✗ エラー: {e}")
        return False


def check_ohlcv() -> bool:
    """[2] OHLCV（ローソク足）取得（認証不要）"""
    print("\n[2] パブリックAPI — OHLCV 取得（1分足 最新10本）")
    # bitbankのOHLCV URLは日付が必要なため、今日の日付を使う
    import datetime
    today = datetime.datetime.utcnow().strftime("%Y%m%d")
    url = f"{PUBLIC_BASE}/{SYMBOL}/candlestick/1min/{today}"
    try:
        r = requests.get(url, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        if data.get("success") != 1:
            print(f"    ✗ レスポンスエラー: {data}")
            return False
        candles = data["data"]["candlestick"][0]["ohlcv"]
        latest = candles[-1]  # 最新の1本
        print(f"    ✓ 取得成功（{len(candles)} 本取得）")
        print(f"      最新足 O:{float(latest[0]):,.0f}  H:{float(latest[1]):,.0f}"
              f"  L:{float(latest[2]):,.0f}  C:{float(latest[3]):,.0f}"
              f"  Vol:{float(latest[4]):.6f}")
        return True
    except Exception as e:
        print(f"    ✗ エラー: {e}")
        return False


# ============================================================
# プライベートAPI チェック
# ============================================================
def check_balance() -> bool:
    """[3] 残高取得（APIキー認証あり）"""
    print("\n[3] プライベートAPI — 残高取得")
    if not API_KEY or not API_SECRET:
        print("    ✗ APIキーが設定されていません。.env を確認してください")
        return False

    path = "/user/assets"
    nonce = _nonce()
    headers = _private_headers(nonce, path)
    url = PRIVATE_BASE + path
    try:
        r = requests.get(url, headers=headers, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        if data.get("success") != 1:
            code = data.get("data", {}).get("code", "?")
            print(f"    ✗ APIエラー (code={code})")
            _print_error_hint(code)
            return False
        assets = data["data"]["assets"]
        print(f"    ✓ 認証成功")
        # JPYとBTCだけ表示（他はゼロが多いので省略）
        for a in assets:
            amt = float(a["free_amount"])
            if a["asset"] in ("jpy", "btc", "eth", "xrp") or amt > 0:
                print(f"      {a['asset'].upper():6s}: {amt:>18.8f}"
                      f"  (利用可能: {float(a['free_amount']):.8f})")
        return True
    except requests.exceptions.HTTPError as e:
        print(f"    ✗ HTTPエラー: {e.response.status_code} {e.response.text[:200]}")
        return False
    except Exception as e:
        print(f"    ✗ エラー: {e}")
        return False


def check_open_orders() -> bool:
    """[4] アクティブな注文一覧取得"""
    print("\n[4] プライベートAPI — アクティブな注文一覧")
    if not API_KEY or not API_SECRET:
        print("    ✗ APIキーが未設定のためスキップ")
        return False

    path = f"/user/spot/active_orders?pair={SYMBOL}"
    nonce = _nonce()
    headers = _private_headers(nonce, path)
    url = PRIVATE_BASE + path
    try:
        r = requests.get(url, headers=headers, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        if data.get("success") != 1:
            code = data.get("data", {}).get("code", "?")
            print(f"    ✗ APIエラー (code={code})")
            return False
        orders = data["data"]["orders"]
        print(f"    ✓ 取得成功")
        if orders:
            print(f"      アクティブな注文: {len(orders)} 件")
            for o in orders[:3]:  # 最大3件表示
                print(f"        ID:{o['order_id']}  {o['side']}  "
                      f"{float(o['price']):,.0f} JPY × {o['remaining_amount']} BTC")
        else:
            print("      アクティブな注文: なし（正常）")
        return True
    except Exception as e:
        print(f"    ✗ エラー: {e}")
        return False


# ============================================================
# エラーコードのヒント表示
# ============================================================
def _print_error_hint(code):
    hints = {
        10000: "URLが正しくありません",
        10001: "認証エラー: APIキーまたはシークレットが間違っています",
        10002: "認証エラー: Nonceが不正です（時計のズレを確認）",
        10003: "認証エラー: 署名が不正です",
        10004: "認証エラー: APIキーの権限が不足しています",
        10005: "IPアドレスが制限されています",
        10006: "APIキーが無効です（有効期限切れまたは削除済み）",
        20001: "残高不足",
        40001: "注文が見つかりません",
        50000: "内部エラー（時間を置いて再試行してください）",
    }
    hint = hints.get(code, "bitbank APIエラーコード一覧: https://github.com/bitbankinc/bitbank-api-docs")
    print(f"      ヒント: {hint}")


# ============================================================
# メイン
# ============================================================
def main():
    print("=" * 60)
    print("  bitbank API 疎通確認スクリプト")
    print("=" * 60)
    print(f"  対象銘柄 : {SYMBOL.upper()}")
    key_status = f"{API_KEY[:6]}***" if len(API_KEY) > 6 else "（未設定）"
    print(f"  APIキー  : {key_status}")

    results = {}
    results["ticker"]       = check_ticker()
    results["ohlcv"]        = check_ohlcv()
    results["balance"]      = check_balance()
    results["open_orders"]  = check_open_orders()

    # サマリー
    print("\n" + "=" * 60)
    print("  結果サマリー")
    print("=" * 60)
    all_ok = True
    for name, ok in results.items():
        status = "✓ OK  " if ok else "✗ FAIL"
        print(f"  [{status}] {name}")
        if not ok:
            all_ok = False

    print()
    if all_ok:
        print("  ✓ 全チェック通過。次は scripts/notify_test.py を実行してください。")
    else:
        print("  ✗ 一部失敗しています。.env のAPIキー設定を確認してください。")
        print("  参考: https://bitbank.cc/api/setting")
    print("=" * 60)

    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
