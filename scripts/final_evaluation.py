"""
scripts/final_evaluation.py
============================
2026-04-19 〜 2026-04-29 の全データをもとに
「本番移行（live）可能か」を判定し、Discordに決算レポートを送信する。

判定基準:
  GO   : 全条件クリア → live移行を推奨
  COND : 一部条件クリア → 条件付きで移行検討可
  WAIT : 条件未達 → dry_run継続を推奨

使い方:
  python scripts/final_evaluation.py
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
END_DATE    = "2026-04-29"

# ---- 本番移行の判定基準 ----
CRITERIA = {
    "min_trades":       10,    # 最低取引回数
    "min_win_rate":     40.0,  # 最低勝率（%）
    "min_profit_factor": 1.3,  # 最低プロフィットファクター（総利益/総損失）
    "max_consec_loss":  3,     # 最大連続損失（guard設定と同じ）
    "max_error_rate":   0.05,  # エラー率（エラー数/シグナル数）の上限
    "min_active_days":  5,     # 最低稼働日数（ログがある日）
}


def load_config() -> dict:
    p = ROOT / "config.yml"
    if p.exists():
        with open(p, encoding="utf-8") as f:
            return yaml.safe_load(f)
    return {}


def parse_log(date_str: str) -> dict:
    path = LOG_DIR / f"{date_str}.jsonl"
    r = dict(signals=0, entries=0, exits=0, errors=0,
             wins=0, losses=0, pnl=0.0, atr_ratios=[],
             gross_profit=0.0, gross_loss=0.0, max_consec=0)
    if not path.exists():
        return r
    consec = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line.strip())
            except Exception:
                continue
            ev = rec.get("event", "")
            if ev == "signal":
                r["signals"] += 1
                raw = rec.get("raw", {})
                if "atr_ratio" in raw:
                    r["atr_ratios"].append(raw["atr_ratio"])
            elif ev == "order":
                r["entries"] += 1
            elif ev == "exit":
                r["exits"] += 1
                pnl = rec.get("net_pnl", rec.get("gross_pnl", 0))
                r["pnl"] += pnl
                if pnl >= 0:
                    r["wins"] += 1
                    r["gross_profit"] += pnl
                    consec = 0
                else:
                    r["losses"] += 1
                    r["gross_loss"] += abs(pnl)
                    consec += 1
                    r["max_consec"] = max(r["max_consec"], consec)
            elif ev == "error":
                r["errors"] += 1
    return r


def all_dates() -> list:
    start = datetime.strptime(START_DATE, "%Y-%m-%d").date()
    end   = datetime.strptime(END_DATE,   "%Y-%m-%d").date()
    today = datetime.now(JST).date()
    end   = min(end, today)
    dates, cur = [], start
    while cur <= end:
        dates.append(str(cur))
        cur += timedelta(days=1)
    return dates


def send_discord(payload: dict):
    if not WEBHOOK_URL:
        print("[eval] DISCORD_WEBHOOK_URL 未設定")
        return
    try:
        r = requests.post(WEBHOOK_URL, json=payload, timeout=10)
        if r.status_code not in (200, 204):
            print(f"[eval] 送信失敗: {r.status_code}")
    except Exception as e:
        print(f"[eval] 送信エラー: {e}")


def main():
    now_jst = datetime.now(JST)
    config  = load_config()
    mode    = config.get("mode", {}).get("run", "dry_run")
    dates   = all_dates()

    # ---- 全日累計 ----
    total = dict(signals=0, entries=0, exits=0, errors=0,
                 wins=0, losses=0, pnl=0.0,
                 gross_profit=0.0, gross_loss=0.0,
                 max_consec=0, active_days=0, atr_all=[])
    daily_rows = []

    for date in dates:
        d = parse_log(date)
        if d["signals"] > 0 or d["entries"] > 0:
            total["active_days"] += 1
        total["signals"]      += d["signals"]
        total["entries"]      += d["entries"]
        total["exits"]        += d["exits"]
        total["errors"]       += d["errors"]
        total["wins"]         += d["wins"]
        total["losses"]       += d["losses"]
        total["pnl"]          += d["pnl"]
        total["gross_profit"] += d["gross_profit"]
        total["gross_loss"]   += d["gross_loss"]
        total["max_consec"]    = max(total["max_consec"], d["max_consec"])
        total["atr_all"]      += d["atr_ratios"]
        avg_atr = sum(d["atr_ratios"]) / len(d["atr_ratios"]) if d["atr_ratios"] else 0
        daily_rows.append((date, d, avg_atr))

    trades     = total["wins"] + total["losses"]
    win_rate   = total["wins"] / trades * 100 if trades > 0 else 0
    pf         = total["gross_profit"] / total["gross_loss"] if total["gross_loss"] > 0 else float("inf")
    error_rate = total["errors"] / total["signals"] if total["signals"] > 0 else 0
    avg_win    = total["gross_profit"] / total["wins"]   if total["wins"]   > 0 else 0
    avg_loss   = total["gross_loss"]   / total["losses"] if total["losses"] > 0 else 0

    # ---- 判定 ----
    checks = {
        "取引回数":         (trades >= CRITERIA["min_trades"],          f"{trades}回（基準: {CRITERIA['min_trades']}回以上）"),
        "勝率":             (win_rate >= CRITERIA["min_win_rate"],       f"{win_rate:.1f}%（基準: {CRITERIA['min_win_rate']}%以上）"),
        "PF":               (pf >= CRITERIA["min_profit_factor"],        f"{pf:.2f}（基準: {CRITERIA['min_profit_factor']}以上）"),
        "最大連続損失":     (total["max_consec"] <= CRITERIA["max_consec_loss"], f"{total['max_consec']}回（基準: {CRITERIA['max_consec_loss']}回以下）"),
        "エラー率":         (error_rate <= CRITERIA["max_error_rate"],   f"{error_rate:.3%}（基準: {CRITERIA['max_error_rate']:.0%}以下）"),
        "稼働日数":         (total["active_days"] >= CRITERIA["min_active_days"], f"{total['active_days']}日（基準: {CRITERIA['min_active_days']}日以上）"),
    }

    passed = sum(1 for ok, _ in checks.values() if ok)
    total_checks = len(checks)

    if passed == total_checks:
        verdict = "GO"
        verdict_text = "本番移行を推奨"
        verdict_emoji = "✅"
        color = 0x2ECC71
    elif passed >= total_checks - 1:
        verdict = "COND"
        verdict_text = "条件付きで移行を検討可"
        verdict_emoji = "⚠️"
        color = 0xF1C40F
    else:
        verdict = "WAIT"
        verdict_text = "dry_run 継続を推奨"
        verdict_emoji = "🔄"
        color = 0x95A5A6

    # ---- 判定詳細テキスト ----
    checks_text = ""
    for name, (ok, desc) in checks.items():
        mark = "✅" if ok else "❌"
        checks_text += f"{mark} {name}: {desc}\n"

    # ---- 日別サマリー ----
    rows_text = ""
    for date, d, avg_atr in daily_rows:
        ps = "+" if d["pnl"] >= 0 else ""
        wr_day = d["wins"]/(d["wins"]+d["losses"])*100 if (d["wins"]+d["losses"])>0 else 0
        rows_text += f"`{date}` {d['exits']}取引 {d['wins']}勝{d['losses']}敗 {ps}{d['pnl']:.1f}円 ATR:{avg_atr:.5f}\n"

    # ---- 改善提案 ----
    suggestions = []
    if win_rate < CRITERIA["min_win_rate"]:
        suggestions.append("EMAパラメータ（fast/slow期間）を見直してシグナル精度を上げる")
    if pf < CRITERIA["min_profit_factor"]:
        suggestions.append("TP比率を上げる or SL比率を下げて損益比を改善する")
    if total["max_consec"] >= CRITERIA["max_consec_loss"]:
        suggestions.append("連続損失上限に接触。guard設定かエントリー条件を絞る")
    if avg_win < avg_loss * 1.5:
        suggestions.append(f"平均利確({avg_win:.1f}円) が平均損切り({avg_loss:.1f}円)の1.5倍未満。TPを広げる余地あり")
    if not suggestions:
        suggestions.append("現在の設定は良好。live移行後も同じパラメータで継続")

    suggest_text = "\n".join(f"• {s}" for s in suggestions)
    pnl_sign = "+" if total["pnl"] >= 0 else ""

    # ---- Discord送信 ----
    payload = {"embeds": [{
        "title":  f"🏁 最終決算レポート — {START_DATE} 〜 {now_jst.strftime('%Y-%m-%d')}",
        "color":  color,
        "fields": [
            {
                "name":   f"{verdict_emoji} 判定: {verdict} — {verdict_text}",
                "value":  f"**{passed}/{total_checks}** 項目クリア",
                "inline": False,
            },
            {
                "name":   "判定項目",
                "value":  checks_text[:1000],
                "inline": False,
            },
            {
                "name":   "パフォーマンス指標",
                "value":  (
                    f"取引回数: **{trades}回** ({total['wins']}勝/{total['losses']}敗)\n"
                    f"勝率: **{win_rate:.1f}%**\n"
                    f"プロフィットファクター: **{pf:.2f}**\n"
                    f"累計損益: **{pnl_sign}¥{total['pnl']:.1f}**\n"
                    f"平均利確: +¥{avg_win:.1f} / 平均損切り: −¥{avg_loss:.1f}\n"
                    f"最大連続損失: {total['max_consec']}回\n"
                    f"稼働日数: {total['active_days']}日 / {len(dates)}日"
                ),
                "inline": False,
            },
            {
                "name":   "日別履歴",
                "value":  rows_text[:900] if rows_text else "—",
                "inline": False,
            },
            {
                "name":   "改善提案",
                "value":  suggest_text[:500],
                "inline": False,
            },
        ],
        "footer": {"text": f"trading_bot final eval | {now_jst.strftime('%Y-%m-%d %H:%M')} JST | mode={mode}"},
    }]}

    send_discord(payload)

    # コンソール出力
    print(f"\n{'='*50}")
    print(f"  最終決算: {verdict} — {verdict_text}")
    print(f"  {passed}/{total_checks} 項目クリア")
    print(f"  取引={trades}  勝率={win_rate:.1f}%  PF={pf:.2f}  累計PnL={pnl_sign}¥{total['pnl']:.1f}")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    main()
