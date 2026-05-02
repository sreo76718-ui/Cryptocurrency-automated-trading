"""
core/notifier.py
================
Discord Webhook 通知。
全イベント（エントリー・決済・停止・エラー・日次サマリー）を通知する。
"""

import os
from datetime import datetime

import requests
from dotenv import load_dotenv

load_dotenv()

_COLOR = {
    "green":  0x2ECC71,
    "red":    0xE74C3C,
    "blue":   0x3498DB,
    "yellow": 0xF1C40F,
    "gray":   0x95A5A6,
}


class Notifier:
    def __init__(self, config: dict):
        cfg = config.get("notifier", {}).get("discord", {})
        self.enabled     = cfg.get("enabled", True)
        self.notify_on   = set(cfg.get("notify_on", ["entry", "exit", "error", "stop"]))
        self.webhook_url = os.getenv("DISCORD_WEBHOOK_URL", "")
        self.is_dry      = config.get("mode", {}).get("run", "dry_run") == "dry_run"

    def _send(self, payload: dict):
        if not self.enabled or not self.webhook_url:
            return
        try:
            r = requests.post(self.webhook_url, json=payload, timeout=10)
            if r.status_code not in (200, 204):
                print(f"[notifier] Discord送信失敗: {r.status_code} {r.text[:100]}")
        except Exception as e:
            print(f"[notifier] Discord送信エラー: {e}")

    def _ts(self) -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _dry_tag(self) -> str:
        return " | ⚠️ dry_run" if self.is_dry else ""

    # ----------------------------------------------------------------

    def notify_entry(self, symbol: str, side: str, price: float,
                     amount: float, order_type: str, signal):
        if "entry" not in self.notify_on:
            return
        color = _COLOR["green"] if side == "buy" else _COLOR["red"]
        direction = "BUY（買い）" if side == "buy" else "SELL（売り）"
        dry_label = " — dry_run" if self.is_dry else ""
        payload = {"embeds": [{
            "title":  f"{'📈' if side == 'buy' else '📉'} エントリー（{side.upper()}）{dry_label}",
            "color":  color,
            "fields": [
                {"name": "銘柄",     "value": symbol.upper().replace("_", "/"), "inline": True},
                {"name": "方向",     "value": f"**{direction}**",               "inline": True},
                {"name": "注文種別", "value": order_type,                        "inline": True},
                {"name": "価格",     "value": f"¥{price:,.0f}",                 "inline": True},
                {"name": "数量",     "value": f"{amount:.6f} {symbol.split('_')[0].upper()}", "inline": True},
                {"name": "シグナル強度", "value": f"{signal.strength:.2f}",     "inline": True},
                {"name": "理由",     "value": signal.reason,                    "inline": False},
            ],
            "footer": {"text": f"trading_bot | {self._ts()}{self._dry_tag()}"},
        }]}
        self._send(payload)

    def notify_exit(self, symbol: str, side: str, price: float,
                    amount: float, pnl: float, reason: str):
        if "exit" not in self.notify_on:
            return
        pnl_sign = "+" if pnl >= 0 else ""
        color = _COLOR["green"] if pnl >= 0 else _COLOR["red"]
        payload = {"embeds": [{
            "title":  f"🔒 決済（{side.upper()}）",
            "color":  color,
            "fields": [
                {"name": "銘柄",   "value": symbol.upper().replace("_", "/"), "inline": True},
                {"name": "価格",   "value": f"¥{price:,.0f}",                 "inline": True},
                {"name": "数量",   "value": f"{amount:.6f} {symbol.split('_')[0].upper()}", "inline": True},
                {"name": "損益",   "value": f"**{pnl_sign}¥{pnl:,.0f}**",    "inline": True},
                {"name": "理由",   "value": reason,                           "inline": True},
            ],
            "footer": {"text": f"trading_bot | {self._ts()}{self._dry_tag()}"},
        }]}
        self._send(payload)

    def notify_stop(self, reason: str):
        if "stop" not in self.notify_on:
            return
        payload = {"embeds": [{
            "title":       "🛑 取引停止",
            "description": reason,
            "color":       _COLOR["yellow"],
            "footer":      {"text": f"trading_bot | {self._ts()}"},
        }]}
        self._send(payload)

    def notify_error(self, message: str):
        if "error" not in self.notify_on:
            return
        payload = {"embeds": [{
            "title":       "🚨 エラー発生",
            "description": f"```\n{message[:1000]}\n```",
            "color":       _COLOR["red"],
            "footer":      {"text": f"trading_bot | {self._ts()}"},
        }]}
        self._send(payload)

    def notify_daily_summary(self, stats: dict):
        if "daily_summary" not in self.notify_on:
            return
        today = datetime.now().strftime("%Y-%m-%d")
        pnl   = stats.get("total_pnl", 0)
        sign  = "+" if pnl >= 0 else ""
        color = _COLOR["blue"] if pnl >= 0 else _COLOR["red"]
        payload = {"embeds": [{
            "title": f"📊 日次サマリー — {today}",
            "color": color,
            "fields": [
                {"name": "取引回数",     "value": str(stats.get("trades",       0)),       "inline": True},
                {"name": "勝ち/負け",    "value": f"{stats.get('wins',0)} 勝 / {stats.get('losses',0)} 敗", "inline": True},
                {"name": "勝率",         "value": f"{stats.get('win_rate', 0):.1f}%",      "inline": True},
                {"name": "実現損益",     "value": f"**{sign}¥{pnl:,.0f}**",               "inline": True},
                {"name": "最大連続損失", "value": f"{stats.get('max_consec_loss', 0)} 回", "inline": True},
                {"name": "モード",       "value": "dry_run" if self.is_dry else "live",    "inline": True},
            ],
            "footer": {"text": f"trading_bot | {today} 集計"},
        }]}
        self._send(payload)

    def notify_startup(self, mode: str, symbol: str):
        payload = {"embeds": [{
            "title":  "🚀 Bot 起動",
            "color":  _COLOR["blue"],
            "fields": [
                {"name": "モード",   "value": mode,                              "inline": True},
                {"name": "対象",     "value": symbol.upper().replace("_", "/"), "inline": True},
            ],
            "footer": {"text": f"trading_bot | {self._ts()}"},
        }]}
        self._send(payload)
