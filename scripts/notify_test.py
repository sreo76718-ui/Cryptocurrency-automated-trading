"""
scripts/notify_test.py
======================
Discord Webhook への通知テストスクリプト。
check_api.py の後に実行して、通知基盤が動くか確認する。

使い方:
    python scripts/notify_test.py

チェック項目:
    [1] シンプルなテキスト通知
    [2] エントリー通知（埋め込み形式）
    [3] エラー通知（赤色埋め込み）
    [4] 日次サマリー通知
"""

import os
import sys
import time
from datetime import datetime

import requests
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
TIMEOUT     = 10


# ============================================================
# 送信ヘルパー
# ============================================================
def _send(payload: dict) -> bool:
    """Discord Webhook にペイロードを送信する"""
    if not WEBHOOK_URL or not WEBHOOK_URL.startswith("https://discord.com"):
        print("    ✗ DISCORD_WEBHOOK_URL が設定されていません（.env を確認）")
        return False
    try:
        r = requests.post(WEBHOOK_URL, json=payload, timeout=TIMEOUT)
        if r.status_code == 204:
            return True
        print(f"    ✗ HTTPエラー: {r.status_code} {r.text[:200]}")
        return False
    except requests.exceptions.ConnectionError:
        print("    ✗ 接続失敗: ネットワークを確認してください")
        return False
    except Exception as e:
        print(f"    ✗ エラー: {e}")
        return False


def _color(name: str) -> int:
    """色名をDiscord embed color値に変換"""
    return {"green": 0x2ECC71, "red": 0xE74C3C, "blue": 0x3498DB, "yellow": 0xF1C40F}.get(name, 0x95A5A6)


# ============================================================
# テストケース
# ============================================================
def test_simple_text() -> bool:
    """[1] シンプルなテキスト通知"""
    print("\n[1] シンプルなテキスト通知")
    payload = {
        "content": "🔔 **bitbank Bot** — 疎通確認テスト (1/4)\n`scripts/notify_test.py` から送信"
    }
    ok = _send(payload)
    if ok:
        print("    ✓ 送信成功")
    return ok


def test_entry_notify() -> bool:
    """[2] エントリー通知（埋め込み形式）"""
    print("\n[2] エントリー通知（埋め込み）")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    payload = {
        "embeds": [{
            "title": "📈 エントリー（BUY） — dry_run",
            "color": _color("green"),
            "fields": [
                {"name": "銘柄",     "value": "BTC/JPY",          "inline": True},
                {"name": "方向",     "value": "**BUY（買い）**",   "inline": True},
                {"name": "注文種別", "value": "指値",              "inline": True},
                {"name": "価格",     "value": "¥9,999,999",       "inline": True},
                {"name": "数量",     "value": "0.0001 BTC",        "inline": True},
                {"name": "シグナル強度", "value": "0.82",          "inline": True},
                {"name": "理由",     "value": "EMAクロス上抜け / ATR=0.0041", "inline": False},
            ],
            "footer": {"text": f"trading_bot | {now} | ⚠️ dry_run"},
        }]
    }
    ok = _send(payload)
    if ok:
        print("    ✓ 送信成功")
    return ok


def test_error_notify() -> bool:
    """[3] エラー通知（赤色埋め込み）"""
    print("\n[3] エラー通知（赤色埋め込み）")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    payload = {
        "embeds": [{
            "title": "🚨 エラー発生",
            "description": "```\nConnectionError: bitbank API に接続できません\nURL: https://api.bitbank.cc/v1/user/assets\n```",
            "color": _color("red"),
            "fields": [
                {"name": "対応",   "value": "5秒後にリトライします（最大5回）", "inline": False},
            ],
            "footer": {"text": f"trading_bot | {now}"},
        }]
    }
    ok = _send(payload)
    if ok:
        print("    ✓ 送信成功")
    return ok


def test_daily_summary() -> bool:
    """[4] 日次サマリー通知"""
    print("\n[4] 日次サマリー通知")
    today = datetime.now().strftime("%Y-%m-%d")
    payload = {
        "embeds": [{
            "title": f"📊 日次サマリー — {today}",
            "color": _color("blue"),
            "fields": [
                {"name": "取引回数",   "value": "8 回",          "inline": True},
                {"name": "勝ち/負け",  "value": "5 勝 / 3 敗",  "inline": True},
                {"name": "勝率",       "value": "62.5%",         "inline": True},
                {"name": "実現損益",   "value": "**+¥3,240**",  "inline": True},
                {"name": "最大含み損", "value": "-¥1,100",      "inline": True},
                {"name": "連続損失",   "value": "最大 2 回",     "inline": True},
                {"name": "モード",     "value": "dry_run",       "inline": True},
            ],
            "footer": {"text": f"trading_bot | {today} 23:59"},
        }]
    }
    ok = _send(payload)
    if ok:
        print("    ✓ 送信成功")
    return ok


# ============================================================
# メイン
# ============================================================
def main():
    print("=" * 60)
    print("  Discord 通知テストスクリプト")
    print("=" * 60)
    hook_status = f"{WEBHOOK_URL[:40]}..." if len(WEBHOOK_URL) > 40 else WEBHOOK_URL or "（未設定）"
    print(f"  Webhook : {hook_status}")

    results = {}
    results["simple_text"]    = test_simple_text()
    time.sleep(1)   # レートリミット回避
    results["entry_notify"]   = test_entry_notify()
    time.sleep(1)
    results["error_notify"]   = test_error_notify()
    time.sleep(1)
    results["daily_summary"]  = test_daily_summary()

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
        print("  ✓ 全通知テスト通過。Discord チャンネルに4件のメッセージが届いているか確認してください。")
        print("  次のステップ: core/logger.py と core/executor_interface.py を実装してください。")
    else:
        print("  ✗ 一部失敗しています。.env の DISCORD_WEBHOOK_URL を確認してください。")
        print("  Webhook URL の作成: Discordサーバー設定 → 連携サービス → Webhooks → 新しいWebhook")
    print("=" * 60)

    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
