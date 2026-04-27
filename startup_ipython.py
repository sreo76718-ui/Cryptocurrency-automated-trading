"""
startup_ipython.py
==================
IPython 起動時に自動実行されるスタートアップスクリプト。
launch_bot_shell.bat から呼ばれる。

自動でやること:
  - .env のAPIキーをロード
  - プロジェクトのパスを sys.path に追加
  - よく使うモジュールをインポート済みにする
  - autoreload を有効化
"""

import os
import sys

# --- プロジェクトルートを sys.path に追加 ---
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# --- .env を読み込む ---
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(project_root, ".env"))
    _key = os.getenv("BITBANK_API_KEY", "")
    _key_status = f"{_key[:6]}***" if len(_key) > 6 else "（未設定）"
    print(f"[startup] .env 読み込み完了  APIキー: {_key_status}")
except ImportError:
    print("[startup] python-dotenv が未インストールです: pip install python-dotenv")

# --- autoreload 有効化（コードを変更したら自動反映） ---
try:
    from IPython import get_ipython
    _ip = get_ipython()
    if _ip:
        _ip.run_line_magic("load_ext", "autoreload")
        _ip.run_line_magic("autoreload", "2")
        print("[startup] autoreload 有効化済み（コード変更が自動反映されます）")
except Exception:
    pass

# --- よく使うモジュールをあらかじめインポート ---
import json
import time
import hmac
import hashlib
import datetime
import requests

print("[startup] import 済み: json / time / hmac / hashlib / datetime / requests")

# --- rich を使える場合はカラー表示を有効化 ---
try:
    from rich import print as rprint
    from rich.pretty import pprint
    from rich.table import Table
    from rich import inspect
    print("[startup] rich 有効化済み（rprint / pprint / inspect が使えます）")
except ImportError:
    pass

# --- 便利関数：APIレスポンスを整形表示 ---
def show(obj, title=""):
    """辞書やリストをきれいに表示する"""
    try:
        from rich.pretty import pprint as _pp
        if title:
            print(f"\n--- {title} ---")
        _pp(obj)
    except ImportError:
        import pprint as _pprint
        if title:
            print(f"\n--- {title} ---")
        _pprint.pprint(obj)

# --- 便利関数：bitbank パブリックAPIから最新ティッカーを取得 ---
def ticker(symbol="btc_jpy"):
    """ticker('btc_jpy') でBTC/JPYの最新価格を取得"""
    r = requests.get(f"https://public.bitbank.cc/{symbol}/ticker", timeout=10)
    data = r.json()
    if data.get("success") == 1:
        t = data["data"]
        print(f"{symbol.upper()}  last={float(t['last']):,.0f}  "
              f"bid={float(t['buy']):,.0f}  ask={float(t['sell']):,.0f}")
        return data["data"]
    else:
        print(f"エラー: {data}")
        return None

print()
print("=" * 50)
print("  bitbank Bot Shell — 起動完了")
print("=" * 50)
print()
print("  show(obj)         — 辞書をきれいに表示")
print("  ticker()          — BTC/JPYの最新価格を取得")
print("  ticker('eth_jpy') — ETH/JPYの価格を取得")
print()
print("  %run scripts/check_api.py      — API疎通確認")
print("  %run scripts/notify_test.py    — Discord通知テスト")
print()
