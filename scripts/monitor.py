"""
scripts/monitor.py
==================
ボット稼働状況の監視スクリプト。
スケジュールタスクから定期実行され、Discordに状態サマリーを送る。

チェック内容:
  - 直近ログの最終更新時刻（ボットが止まっていないか）
  - 当日のシグナル・エントリー・決済・エラー件数
  - 当日の損益・連続損失・Guard状態
  - 現在のポジション状態
  - 最適化提案（ATR比・閾値の乖離など）

使い方:
  python scripts/monitor.py
"""

import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
import yaml
from dotenv import load_dotenv

# プロジェクトルートをパスに追加
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

JST            = timezone(timedelta(hours=9))
WEBHOOK_URL    = os.getenv("DISCORD_WEBHOOK_URL", "")
LOG_DIR        = ROOT / "data" / "logs"
STATE_DIR      = ROOT / "data" / "state"
CONFIG_PATH    = ROOT / "config.yml"
TIMEOUT_MIN    = 10   # この分数ログ更新がなければ「停止疑い」とみなす

_COLOR = {"green": 0x2ECC71, "red": 0xE74C3C,
          "blue": 0x3498DB, "yellow": 0xF1C40F, "gray": 0x95A5A6}


# ----------------------------------------------------------------
# 設定読み込み
# ----------------------------------------------------------------
def load_config() -> dict:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, encoding="utf-8") as f:
            return yaml.safe_load(f)
    return {}


# ----------------------------------------------------------------
# ログ解析
# ----------------------------------------------------------------
def parse_today_log() -> dict:
    """今日のJSONLログを読んでイベントを集計する"""
    today = datetime.now(JST).strftime("%Y-%m-%d")
    log_path = LOG_DIR / f"{today}.jsonl"

    stats = {
        "log_exists":    False,
        "last_update":   None,
        "signals":       0,
        "holds":         0,
        "entries":       0,
        "exits":         0,
        "errors":        0,
        "stops":         0,
        "atr_ratios":    [],   # シグナルrawから収集
        "pnl_list":      [],   # exitイベントから収集
        "last_signal":   None,
    }

    if not log_path.exists():
        return stats

    stats["log_exists"]  = True
    stats["last_update"] = datetime.fromtimestamp(log_path.stat().st_mtime, tz=JST)

    with open(log_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue

            event = rec.get("event", "")
            if event == "signal":
                stats["signals"] += 1
                if rec.get("signal") == "hold":
                    stats["holds"] += 1
                raw = rec.get("raw", {})
                if "atr_ratio" in raw:
                    stats["atr_ratios"].append(raw["atr_ratio"])
                stats["last_signal"] = rec
            elif event == "order":
                stats["entries"] += 1
            elif event == "exit":
                stats["exits"] += 1
                pnl = rec.get("net_pnl", rec.get("gross_pnl", 0))
                stats["pnl_list"].append(pnl)
            elif event == "error":
                stats["errors"] += 1
            elif event == "stop":
                stats["stops"] += 1

    return stats


# ----------------------------------------------------------------
# 状態ファイル読み込み
# ----------------------------------------------------------------
def load_guard_state() -> dict:
    path = STATE_DIR / "guard_state.json"
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def load_position_state() -> dict:
    path = STATE_DIR / "position.json"
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


# ----------------------------------------------------------------
# 最適化提案
# ----------------------------------------------------------------
def suggest_optimizations(stats: dict, guard: dict, config: dict) -> list[str]:
    suggestions = []
    vol_cfg = config.get("strategy", {}).get("volatility", {})

    # ATR比の分析
    if stats["atr_ratios"]:
        avg_atr = sum(stats["atr_ratios"]) / len(stats["atr_ratios"])
        max_atr = max(stats["atr_ratios"])
        threshold = vol_cfg.get("min_atr_ratio", 0.0002)
        weekend_threshold = vol_cfg.get("min_atr_ratio_weekend", 0.00008)
        from datetime import datetime, timezone, timedelta
        is_weekend = datetime.now(timezone(timedelta(hours=9))).weekday() >= 5
        active_threshold = weekend_threshold if is_weekend else threshold

        # ATR比が閾値の2倍以下 → 少し閾値を下げる余地あり
        if avg_atr < active_threshold * 2 and stats["entries"] == 0 and stats["signals"] > 10:
            key = "min_atr_ratio_weekend" if is_weekend else "min_atr_ratio"
            new_val = round(avg_atr * 0.8, 6)
            suggestions.append(
                f"📉 ATR平均({avg_atr:.5f}) が閾値({active_threshold})の2倍未満。\n"
                f"　→ `config.yml` の `{key}` を `{new_val}` に下げるとエントリーしやすくなります"
            )
        # ATR比が閾値の10倍以上 → 閾値が低すぎてノイズエントリーの恐れ
        if avg_atr > active_threshold * 10 and stats["entries"] > 0:
            key = "min_atr_ratio_weekend" if is_weekend else "min_atr_ratio"
            new_val = round(avg_atr * 0.3, 6)
            suggestions.append(
                f"📈 ATR平均({avg_atr:.5f}) が閾値({active_threshold})の10倍超。\n"
                f"　→ `config.yml` の `{key}` を `{new_val}` に上げると質の良いエントリーに絞れます"
            )

    # 連続損失が多い
    consec = guard.get("consecutive_loss", 0)
    if consec >= 2:
        suggestions.append(
            f"⚠️ 連続損失 {consec} 回。損切り比率の見直しを検討してください\n"
            f"　→ `config.yml` の `stop_loss_ratio` を小さくすると早めに損切りできます"
        )

    # エラーが多い
    if stats["errors"] >= 3:
        suggestions.append(
            f"🚨 エラー {stats['errors']} 件。ネットワーク状況またはAPIレートリミットを確認してください"
        )

    return suggestions


# ----------------------------------------------------------------
# Discord 送信
# ----------------------------------------------------------------
def send_discord(payload: dict):
    if not WEBHOOK_URL:
        print("[monitor] DISCORD_WEBHOOK_URL 未設定")
        return
    try:
        r = requests.post(WEBHOOK_URL, json=payload, timeout=10)
        if r.status_code not in (200, 204):
            print(f"[monitor] Discord送信失敗: {r.status_code}")
    except Exception as e:
        print(f"[monitor] Discord送信エラー: {e}")


# ----------------------------------------------------------------
# メイン
# ----------------------------------------------------------------
def main():
    now_jst = datetime.now(JST)
    config  = load_config()
    mode    = config.get("mode", {}).get("run", "dry_run")
    symbol  = config.get("targets", [{}])[0].get("symbol", "btc_jpy").upper().replace("_", "/")

    stats    = parse_today_log()
    guard    = load_guard_state()
    position = load_position_state()
    suggests = suggest_optimizations(stats, guard, config)

    # ---- ボット稼働状態の判定 ----
    is_stopped   = guard.get("stopped", False)
    stop_reason  = guard.get("stop_reason", "")
    last_update  = stats.get("last_update")

    if not stats["log_exists"]:
        bot_status = "❓ ログなし（未起動 or 日付変わり直後）"
        color = _COLOR["gray"]
    elif is_stopped:
        bot_status = f"🛑 停止中: {stop_reason}"
        color = _COLOR["red"]
    elif last_update and (now_jst - last_update).seconds > TIMEOUT_MIN * 60:
        lag_min = (now_jst - last_update).seconds // 60
        bot_status = f"⚠️ 応答なし ({lag_min}分更新なし)"
        color = _COLOR["yellow"]
    else:
        bot_status = "✅ 稼働中"
        color = _COLOR["green"]

    # ---- 損益集計 ----
    total_pnl  = sum(stats["pnl_list"])
    wins       = sum(1 for p in stats["pnl_list"] if p >= 0)
    losses     = len(stats["pnl_list"]) - wins
    win_rate   = wins / len(stats["pnl_list"]) * 100 if stats["pnl_list"] else 0
    pnl_sign   = "+" if total_pnl >= 0 else ""
    daily_pnl  = guard.get("daily_pnl", 0)

    # ---- ポジション情報 ----
    pos_status = "なし"
    if position.get("status") == "open":
        ep = position.get("entry_price", 0)
        tp = position.get("take_profit", 0)
        sl = position.get("stop_loss", 0)
        pos_status = (f"{position.get('side','').upper()} "
                      f"entry={ep:,.0f}  TP={tp:,.0f}  SL={sl:,.0f}")

    # ---- ATR平均 ----
    avg_atr_str = "—"
    if stats["atr_ratios"]:
        avg = sum(stats["atr_ratios"]) / len(stats["atr_ratios"])
        avg_atr_str = f"{avg:.5f}"

    # ---- Discord ペイロード組み立て ----
    fields = [
        {"name": "稼働状態",     "value": bot_status,                    "inline": False},
        {"name": "モード",       "value": mode,                          "inline": True},
        {"name": "対象銘柄",     "value": symbol,                        "inline": True},
        {"name": "ポジション",   "value": pos_status,                    "inline": False},
        {"name": "シグナル数",   "value": str(stats["signals"]),         "inline": True},
        {"name": "エントリー",   "value": str(stats["entries"]),         "inline": True},
        {"name": "決済",         "value": str(stats["exits"]),           "inline": True},
        {"name": "当日損益(ログ)","value": f"{pnl_sign}¥{total_pnl:,.0f} ({wins}勝{losses}敗 勝率{win_rate:.0f}%)", "inline": False},
        {"name": "Guard損益",    "value": f"¥{daily_pnl:,.0f}",        "inline": True},
        {"name": "連続損失",     "value": str(guard.get("consecutive_loss", 0)), "inline": True},
        {"name": "エラー数",     "value": str(stats["errors"]),         "inline": True},
        {"name": "ATR比(平均)",  "value": avg_atr_str,                  "inline": True},
    ]

    # 最適化提案があれば追加
    if suggests:
        fields.append({
            "name":  "💡 最適化提案",
            "value": "\n".join(suggests)[:1000],
            "inline": False,
        })

    payload = {"embeds": [{
        "title":  f"🔍 Bot 監視レポート — {now_jst.strftime('%m/%d %H:%M')} JST",
        "color":  color,
        "fields": fields,
        "footer": {"text": f"trading_bot monitor | {now_jst.strftime('%Y-%m-%d %H:%M')} JST"},
    }]}

    send_discord(payload)

    # コンソール出力
    print(f"[monitor] {now_jst.strftime('%Y-%m-%d %H:%M JST')}")
    print(f"  稼働状態: {bot_status}")
    print(f"  シグナル={stats['signals']}  エントリー={stats['entries']}  決済={stats['exits']}  エラー={stats['errors']}")
    print(f"  当日損益={pnl_sign}¥{total_pnl:,.0f}  ATR平均={avg_atr_str}")
    if suggests:
        print("  最適化提案:")
        for s in suggests:
            print(f"    {s}")
    print("  → Discord送信完了")


if __name__ == "__main__":
    main()
