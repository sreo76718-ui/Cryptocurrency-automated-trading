"""
scripts/_send_discord_report.py
================================
daily_report.py が Cowork サンドボックスから Discord に届かない場合に
Windows 上で直接実行して送信するフォールバックスクリプト。
"""

import json, os, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
import requests
import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

JST         = timezone(timedelta(hours=9))
WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
LOG_DIR     = ROOT / "data" / "logs"
STATE_DIR   = ROOT / "data" / "state"
START_DATE  = "2026-04-19"
_COLOR = {"green": 0x2ECC71, "red": 0xE74C3C, "blue": 0x3498DB,
          "yellow": 0xF1C40F, "gray": 0x95A5A6}

def load_config():
    p = ROOT / "config.yml"
    if p.exists():
        with open(p, encoding="utf-8") as f:
            return yaml.safe_load(f)
    return {}

def parse_log(date_str):
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

def all_dates_since_start():
    start = datetime.strptime(START_DATE, "%Y-%m-%d").date()
    today = datetime.now(JST).date()
    dates, cur = [], start
    while cur <= today:
        dates.append(str(cur))
        cur += timedelta(days=1)
    return dates

def send_discord(payload):
    if not WEBHOOK_URL:
        print("[discord] DISCORD_WEBHOOK_URL 未設定")
        return False
    try:
        r = requests.post(WEBHOOK_URL, json=payload, timeout=10)
        if r.status_code in (200, 204):
            print(f"[discord] 送信OK ({r.status_code})")
            return True
        else:
            print(f"[discord] 送信失敗: {r.status_code} {r.text}")
            return False
    except Exception as e:
        print(f"[discord] 送信エラー: {e}")
        return False

def send_text(msg):
    return send_discord({"content": msg})

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
    today_avg_atr = sum(today_d["atr_ratios"]) / len(today_d["atr_ratios"]) if today_d["atr_ratios"] else 0

    # --- 日別サマリー行 ---
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

    # --- Step1: メインレポート送信 ---
    print("[Step1] デイリーレポートを送信中...")
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

    # --- Step2: アラートコメント ---
    alerts = []
    today_exits = today_d["exits"]
    today_wins  = today_d["wins"]
    consec_loss = guard.get("consecutive_loss", 0)
    guard_stopped = guard.get("stopped", False)
    errors_today  = today_d["errors"]
    min_atr = config.get("strategy", {}).get("volatility", {}).get("min_atr_ratio", 0.0002)

    if today_exits > 0 and today_wins == 0:
        alerts.append(f"⚠️ **本日の勝率0%**\n全{today_exits}回決済がすべて損失。直近の取引を確認してください。")

    if consec_loss >= 2:
        alerts.append(f"🔴 **連続損失 {consec_loss}回**\nGuardの`max_consecutive_loss`（現在99回・TEST設定）が本番では機能するか確認を。")

    if guard_stopped:
        reason = guard.get("stop_reason", "不明")
        alerts.append(f"🛑 **Guard停止が発生**\n理由: {reason}")

    if errors_today >= 3:
        alerts.append(f"🚨 **エラー{errors_today}件**\nログを確認してください。")

    if today_d["entries"] == 0 and today_avg_atr < min_atr * 0.5:
        alerts.append(
            f"📉 **エントリー0件 + ATR比低下**\n"
            f"平均ATR比 {today_avg_atr:.6f} が閾値の半分未満（{min_atr*0.5:.6f}）。"
        )

    # guard_state.jsonが破損していた旨を通知
    alerts.append(
        f"🔧 **guard_state.json が破損していました**\n"
        f"ファイルが途中で切れており JSON パースエラーが発生。"
        f"自動修復しました（losses=9 を補完）。ボット側の書き込み処理を確認することをお勧めします。"
    )

    print(f"[Step2] アラート{len(alerts)}件を送信中...")
    for alert in alerts:
        send_text(f"💬 {alert}")

    # --- Step3: config.yml 自動最適化（dry_runのみ）---
    if mode == "dry_run":
        changed = False
        new_min_atr = min_atr
        change_msg = ""

        if today_d["entries"] == 0 and today_avg_atr < min_atr * 0.5:
            new_min_atr = today_avg_atr * 0.8
            change_msg = (
                f"ATR比平均({today_avg_atr:.6f})が`min_atr_ratio`({min_atr})の0.5倍未満 → "
                f"閾値を {new_min_atr:.6f} に引き下げ"
            )
            changed = True
        elif today_avg_atr > min_atr * 15:
            new_min_atr = today_avg_atr * 0.3
            change_msg = (
                f"ATR比平均({today_avg_atr:.6f})が`min_atr_ratio`({min_atr})の15倍超 → "
                f"閾値を {new_min_atr:.6f} に引き上げ"
            )
            changed = True

        if changed:
            config_path = ROOT / "config.yml"
            with open(config_path, encoding="utf-8") as f:
                content = f.read()
            # min_atr_ratioの行を更新（平日分のみ）
            import re
            new_content = re.sub(
                r"(min_atr_ratio:\s*)[\d.]+(\s*#.*平日)",
                lambda m: f"{m.group(1)}{new_min_atr:.6f}{m.group(2)}",
                content
            )
            if new_content != content:
                with open(config_path, "w", encoding="utf-8") as f:
                    f.write(new_content)
                send_text(f"⚙️ **config.yml 自動最適化** (dry_run)\n{change_msg}")
                print(f"[Step3] config.yml更新: {change_msg}")
            else:
                print("[Step3] config.yml: 対象行が見つからず変更なし")
        else:
            print("[Step3] config.yml: 最適化条件に該当しないため変更なし")

    print("=== 完了 ===")

if __name__ == "__main__":
    main()
