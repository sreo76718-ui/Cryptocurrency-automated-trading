"""
scripts/daily_report.py
=======================
スタート日（2026-04-19）からの累計 + 当日 のデイリーレポートを
Discordに送信するスクリプト。毎日23:00 JST にスケジュール実行される。

使い方:
  python scripts/daily_report.py
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

JST         = timezone(timedelta(hours=9))
WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
LOG_DIR     = ROOT / "data" / "logs"
STATE_DIR   = ROOT / "data" / "state"
START_DATE  = "2026-04-19"

_COLOR = {"green": 0x2ECC71, "red": 0xE74C3C, "blue": 0x3498DB,
          "yellow": 0xF1C40F, "gray": 0x95A5A6}


def load_config() -> dict:
    p = ROOT / "config.yml"
    if p.exists():
        with open(p, encoding="utf-8") as f:
            return yaml.safe_load(f)
    return {}


def parse_log(date_str: str) -> dict:
    path = LOG_DIR / f"{date_str}.jsonl"
    result = dict(signals=0, entries=0, exits=0, errors=0,
                  wins=0, losses=0, pnl=0.0, atr_ratios=[])
    if not path.exists():
        return result
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line.strip())
            except Exception:
                continue
            ev = r.get("event", "")
            if ev == "signal":
                result["signals"] += 1
                raw = r.get("raw", {})
                if "atr_ratio" in raw:
                    result["atr_ratios"].append(raw["atr_ratio"])
            elif ev == "order":
                result["entries"] += 1
            elif ev == "exit":
                result["exits"] += 1
                pnl = r.get("net_pnl", r.get("gross_pnl", 0))
                result["pnl"] += pnl
                if pnl >= 0:
                    result["wins"] += 1
                else:
                    result["losses"] += 1
            elif ev == "error":
                result["errors"] += 1
    return result


def all_dates_since_start() -> list:
    start = datetime.strptime(START_DATE, "%Y-%m-%d").date()
    today = datetime.now(JST).date()
    dates = []
    cur = start
    while cur <= today:
        dates.append(str(cur))
        cur += timedelta(days=1)
    return dates


def send_discord(payload: dict):
    if not WEBHOOK_URL:
        print("[daily_report] DISCORD_WEBHOOK_URL 未設定")
        return
    try:
        r = requests.post(WEBHOOK_URL, json=payload, timeout=10)
        if r.status_code not in (200, 204):
            print(f"[daily_report] 送信失敗: {r.status_code}")
    except Exception as e:
        print(f"[daily_report] 送信エラー: {e}")


def main():
    now_jst = datetime.now(JST)
    today   = str(now_jst.date())
    config  = load_config()
    mode    = config.get("mode", {}).get("run", "dry_run")

    # --- 全日集計 ---
    dates = all_dates_since_start()
    cumulative = dict(entries=0, exits=0, wins=0, losses=0, pnl=0.0, errors=0)
    daily_rows = []

    for date in dates:
        d = parse_log(date)
        cumulative["entries"] += d["entries"]
        cumulative["exits"]   += d["exits"]
        cumulative["wins"]    += d["wins"]
        cumulative["losses"]  += d["losses"]
        cumulative["pnl"]     += d["pnl"]
        cumulative["errors"]  += d["errors"]
        avg_atr = sum(d["atr_ratios"]) / len(d["atr_ratios"]) if d["atr_ratios"] else 0
        daily_rows.append((date, d, avg_atr))

    total_trades = cumulative["wins"] + cumulative["losses"]
    win_rate = cumulative["wins"] / total_trades * 100 if total_trades > 0 else 0
    pnl_sign = "+" if cumulative["pnl"] >= 0 else ""
    color = _COLOR["green"] if cumulative["pnl"] >= 0 else _COLOR["red"]

    # --- Guard状態 ---
    guard = {}
    gp = STATE_DIR / "guard_state.json"
    if gp.exists():
        with open(gp, encoding="utf-8") as f:
            guard = json.load(f)

    # --- 当日ログ ---
    today_d = parse_log(today)
    today_pnl_sign = "+" if today_d["pnl"] >= 0 else ""

    # --- 日別サマリー行を組み立て ---
    rows_text = ""
    for date, d, avg_atr in daily_rows:
        wr = d["wins"] / (d["wins"] + d["losses"]) * 100 if (d["wins"] + d["losses"]) > 0 else 0
        ps = "+" if d["pnl"] >= 0 else ""
        rows_text += (
            f"`{date}`  "
            f"取引:{d['exits']}回 {d['wins']}勝{d['losses']}敗 "
            f"PnL:{ps}{d['pnl']:.1f}円 "
            f"ATR:{avg_atr:.5f}\n"
        )

    # --- Discord送信 ---
    payload = {"embeds": [{
        "title":  f"📅 デイリーレポート — {today} ({mode})",
        "color":  color,
        "fields": [
            {
                "name":   "スタート日〜本日 累計",
                "value":  (
                    f"期間: {START_DATE} 〜 {today}（{len(dates)}日間）\n"
                    f"取引: {cumulative['exits']}回  {cumulative['wins']}勝 / {cumulative['losses']}敗\n"
                    f"勝率: {win_rate:.1f}%\n"
                    f"累計損益: **{pnl_sign}¥{cumulative['pnl']:.1f}**\n"
                    f"エラー: {cumulative['errors']}件"
                ),
                "inline": False,
            },
            {
                "name":   f"本日（{today}）",
                "value":  (
                    f"シグナル: {today_d['signals']}回\n"
                    f"エントリー: {today_d['entries']}回\n"
                    f"決済: {today_d['exits']}回 "
                    f"（{today_d['wins']}勝{today_d['losses']}敗）\n"
                    f"本日損益: {today_pnl_sign}¥{today_d['pnl']:.1f}\n"
                    f"連続損失: {guard.get('consecutive_loss', 0)}回\n"
                    f"Guard停止: {'あり — ' + guard.get('stop_reason','') if guard.get('stopped') else 'なし'}"
                ),
                "inline": False,
            },
            {
                "name":   "日別履歴",
                "value":  rows_text[:1000] if rows_text else "—",
                "inline": False,
            },
        ],
        "footer": {"text": f"trading_bot | {now_jst.strftime('%Y-%m-%d %H:%M')} JST"},
    }]}

    send_discord(payload)

    # コンソール出力
    print(f"[daily_report] {today}")
    print(f"  累計: {cumulative['exits']}取引 {cumulative['wins']}勝{cumulative['losses']}敗 "
          f"勝率{win_rate:.1f}% PnL={pnl_sign}¥{cumulative['pnl']:.1f}")
    print(f"  本日: entry={today_d['entries']} exit={today_d['exits']} "
          f"PnL={today_pnl_sign}¥{today_d['pnl']:.1f}")
    print("  → Discord送信完了")


if __name__ == "__main__":
    main()
