"""
scripts/test_notify.py
======================
Discord通知の疎通確認スクリプト。
通知が届かない場合にここで原因を特定する。

使い方:
  python scripts/test_notify.py
"""
import os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import requests
import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

with open(ROOT / "config.yml", encoding="utf-8") as f:
    config = yaml.safe_load(f)

webhook_url = os.getenv("DISCORD_WEBHOOK_URL", "")
cfg_discord = config.get("notifier", {}).get("discord", {})
notify_on   = cfg_discord.get("notify_on", [])
enabled     = cfg_discord.get("enabled", False)

print("=== Discord通知 診断 ===")
print(f"  enabled    : {enabled}")
print(f"  notify_on  : {notify_on}")
print(f"  'entry' あり: {'entry' in notify_on}")
print(f"  Webhook URL: {'設定あり (' + webhook_url[:40] + '...)' if webhook_url else '【未設定】'}")
print()

if not webhook_url:
    print("❌ DISCORD_WEBHOOK_URL が .env に設定されていません")
    sys.exit(1)

if not enabled:
    print("❌ config.yml の notifier.discord.enabled が false です")
    sys.exit(1)

if "entry" not in notify_on:
    print("❌ config.yml の notify_on に 'entry' がありません")
    print(f"   現在の値: {notify_on}")
    sys.exit(1)

print("→ Discordへテストメッセージを送信中...")
payload = {"embeds": [{
    "title": "🔔 通知テスト",
    "description": "このメッセージが届いていれば通知は正常に動作しています。",
    "color": 0x2ECC71,
    "fields": [
        {"name": "enabled",   "value": str(enabled),   "inline": True},
        {"name": "notify_on", "value": str(notify_on), "inline": True},
    ]
}]}

try:
    r = requests.post(webhook_url, json=payload, timeout=10)
    print(f"  ステータス: {r.status_code}")
    if r.status_code in (200, 204):
        print("✅ 送信成功！Discordを確認してください。")
    else:
        print(f"❌ 送信失敗: {r.text[:200]}")
        print()
        print("→ Webhook URLが無効な可能性があります。")
        print("  Discordで新しいWebhook URLを作成して .env を更新してください。")
except Exception as e:
    print(f"❌ 接続エラー: {e}")
    print("  インターネット接続を確認してください。")
