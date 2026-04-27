"""
main.py
=======
自動売買ボット メインループ。

起動方法:
    python main.py

処理フロー（1ループ）:
    1. 日次リセットチェック
    2. guard.can_trade() → 停止中なら待機
    3. OHLCV / ティッカー取得
    4. ポジション保有中 → TP/SL チェック → 必要なら決済
    5. ポジションなし   → strategy.evaluate() → BUY シグナルなら発注
    6. ログ・通知
    7. interval_sec 待機
"""

import os
import sys
import time
import traceback

import yaml
from dotenv import load_dotenv

# パスを通す
sys.path.insert(0, os.path.dirname(__file__))
load_dotenv()

from core.guard    import Guard
from core.logger   import Logger
from core.notifier import Notifier
from core.position import PositionManager
from core.risk     import RiskManager
from core.signal   import SignalType
from exchanges.bitbank.executor  import BitbankExecutor
from exchanges.bitbank.fee       import FeeCalculator
from strategies.trend_follow     import TrendFollowStrategy


# ----------------------------------------------------------------
# 設定読み込み
# ----------------------------------------------------------------
def load_config(path: str = "config.yml") -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


# ----------------------------------------------------------------
# Executor ファクトリ（将来 OANDA に切り替えるときここだけ変える）
# ----------------------------------------------------------------
def build_executor(config: dict):
    exchange = config.get("active_exchange", "bitbank")
    if exchange == "bitbank":
        return BitbankExecutor(config)
    else:
        raise NotImplementedError(f"未対応の取引所: {exchange}")


# ----------------------------------------------------------------
# メインループ
# ----------------------------------------------------------------
def main():
    config   = load_config()
    mode     = config["mode"]["run"]
    symbol   = config["targets"][0]["symbol"]  # 初期は1銘柄
    interval = config["loop"]["interval_sec"]
    max_err  = config["loop"]["max_consecutive_errors"]

    # コンポーネント初期化
    executor = build_executor(config)
    strategy = TrendFollowStrategy(config)
    guard    = Guard(config)
    position = PositionManager(config)
    risk     = RiskManager(config)
    logger   = Logger(config)
    notifier = Notifier(config)
    fee_calc = FeeCalculator(config)
    order_type = config.get("bitbank", {}).get("order_type_default", "limit")

    dry_tag = "[DRY_RUN] " if executor.is_dry_run() else "[LIVE] "
    print(f"\n{dry_tag}===== Trading Bot 起動 =====")
    print(f"  取引所 : {config['active_exchange']}")
    print(f"  銘柄   : {symbol.upper()}")
    print(f"  モード : {mode}")
    print(f"  間隔   : {interval}秒")
    print("=" * 40)

    logger.log_info("Bot起動", {"mode": mode, "symbol": symbol})
    notifier.notify_startup(mode, symbol)

    consec_errors = 0

    while True:
        try:
            # ---- 日次リセット ----
            if guard.reset_if_new_day():
                logger.log_info("日次リセット")
                print("[main] 日次リセット")

            # ---- 停止チェック ----
            ok, stop_reason = guard.can_trade()
            if not ok:
                print(f"[main] 取引停止中: {stop_reason}")
                time.sleep(interval)
                continue

            # ---- 市場データ取得 ----
            ticker = executor.get_ticker(symbol)
            ohlcv  = executor.get_ohlcv(symbol, period="1min", count=60)
            last   = ticker["last"]
            print(f"[main] {symbol.upper()} last={last:,.0f}  "
                  f"bid={ticker['best_bid']:,.0f}  ask={ticker['best_ask']:,.0f}")

            # ---- ポジション保有中 → TP/SL チェック ----
            if position.is_open():
                pos = position.get()
                exit_reason = None

                if position.should_take_profit(last):
                    exit_reason = f"利確(TP={pos.take_profit:,.0f})"
                elif position.should_stop_loss(last):
                    exit_reason = f"損切り(SL={pos.stop_loss:,.0f})"

                if exit_reason:
                    # 決済注文
                    exit_side = "sell" if pos.side == "buy" else "buy"
                    exit_order = executor.place_order(
                        symbol     = symbol,
                        side       = exit_side,
                        amount     = pos.amount,
                        order_type = "limit" if order_type == "limit" else "market",
                        price      = last,
                    )
                    fill = executor.wait_for_fill(exit_order["order_id"], symbol)
                    exit_price = fill["avg_price"] if fill and fill.get("avg_price") else last

                    # 損益計算
                    gross_pnl = position.close_position(exit_price)
                    net_pnl   = fee_calc.effective_pnl(
                        gross_pnl,
                        symbol, pos.amount, pos.entry_price, order_type,
                        symbol, pos.amount, exit_price,      order_type,
                    )
                    guard.record_trade(net_pnl, pos.side)

                    # ログ・通知
                    logger.log_exit({
                        "symbol":      symbol,
                        "side":        exit_side,
                        "exit_price":  exit_price,
                        "amount":      pos.amount,
                        "gross_pnl":   round(gross_pnl, 2),
                        "net_pnl":     round(net_pnl, 2),
                        "reason":      exit_reason,
                    })
                    notifier.notify_exit(symbol, exit_side, exit_price,
                                         pos.amount, net_pnl, exit_reason)

                    pnl_sign = "+" if net_pnl >= 0 else ""
                    print(f"  → 決済 {exit_reason}  PnL={pnl_sign}{net_pnl:,.0f}円")
                else:
                    print(f"  → ポジション保有中 "
                          f"entry={pos.entry_price:,.0f} "
                          f"TP={pos.take_profit:,.0f} "
                          f"SL={pos.stop_loss:,.0f}")

            # ---- ポジションなし → エントリー判断 ----
            else:
                signal = strategy.evaluate(ohlcv, ticker, position.is_open())
                logger.log_signal(symbol, signal)
                print(f"  → シグナル: {signal}")

                if signal.type == SignalType.BUY:
                    # 同方向制限チェック
                    can_enter, enter_reason = guard.can_enter_side("buy")
                    if not can_enter:
                        print(f"  → エントリースキップ: {enter_reason}")
                    else:
                        # 発注サイズ計算
                        balance = executor.get_balance()
                        amount  = risk.calc_order_amount(balance.get("jpy", 0), last)
                        valid, val_reason = risk.validate(amount, last)

                        if not valid:
                            print(f"  → 発注スキップ: {val_reason}")
                        else:
                            entry_price = ticker["best_ask"]  # 指値はask基準
                            order = executor.place_order(
                                symbol     = symbol,
                                side       = "buy",
                                amount     = amount,
                                order_type = order_type,
                                price      = entry_price,
                            )
                            print(f"  → 発注: {order['order_id']} "
                                  f"price={entry_price:,.0f} amount={amount:.6f}")

                            fill = executor.wait_for_fill(order["order_id"], symbol)
                            if fill:
                                filled_price = fill.get("avg_price") or entry_price
                                position.open_position(
                                    symbol      = symbol,
                                    side        = "buy",
                                    order_id    = order["order_id"],
                                    entry_price = filled_price,
                                    amount      = amount,
                                )
                                logger.log_order({**order, "filled_price": filled_price})
                                notifier.notify_entry(
                                    symbol, "buy", filled_price, amount,
                                    order_type, signal
                                )
                                print(f"  → 約定: price={filled_price:,.0f}")
                            else:
                                print("  → 約定タイムアウト: キャンセル済み")

            consec_errors = 0  # 正常終了でリセット

        except KeyboardInterrupt:
            print("\n[main] Ctrl+C 受信 → 停止")
            guard.manual_stop("手動停止(Ctrl+C)")
            notifier.notify_stop("手動停止 (Ctrl+C)")
            stats = guard.get_stats()
            logger.log_daily_summary(stats)
            notifier.notify_daily_summary(stats)
            break

        except Exception as e:
            consec_errors += 1
            tb = traceback.format_exc()
            print(f"[main] エラー({consec_errors}/{max_err}): {e}")
            logger.log_error(e, {"traceback": tb})

            if consec_errors >= max_err:
                msg = f"連続エラー{max_err}回 → 強制停止: {e}"
                print(f"[main] {msg}")
                guard.manual_stop(msg)
                notifier.notify_stop(msg)
                break

            notifier.notify_error(f"{type(e).__name__}: {e}")
            time.sleep(interval)
            continue

        time.sleep(interval)


if __name__ == "__main__":
    main()
