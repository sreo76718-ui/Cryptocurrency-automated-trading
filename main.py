"""
main.py  -  Trading Bot main loop (multi-symbol + BUY/SELL)
"""

import os
import sys
import time
import traceback

import yaml
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(__file__))
load_dotenv()

from core.guard    import Guard
from core.logger   import Logger
from core.notifier import Notifier
from core.position import PositionManager
from core.risk     import RiskManager
from core.signal   import SignalType
from exchanges.bitbank.executor import BitbankExecutor
from exchanges.bitbank.fee      import FeeCalculator
from strategies.trend_follow    import TrendFollowStrategy


def load_config(path="config.yml"):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def build_executor(config):
    exchange = config.get("active_exchange", "bitbank")
    if exchange == "bitbank":
        return BitbankExecutor(config)
    raise NotImplementedError(f"Unsupported exchange: {exchange}")


def _place_entry(executor, guard, risk, position, logger, notifier,
                 balance, symbol, side, ticker, order_type, signal):
    can_enter, reason = guard.can_enter_side(side)
    if not can_enter:
        print(f"  [{symbol.upper()}] skip({side}): {reason}")
        return

    last = ticker["last"]
    amount = risk.calc_order_amount(balance.get("jpy", 0), last, symbol)
    valid, val_reason = risk.validate(amount, last)
    if not valid:
        print(f"  [{symbol.upper()}] size skip: {val_reason}")
        return

    entry_price = ticker["best_ask"] if side == "buy" else ticker["best_bid"]
    order = executor.place_order(
        symbol=symbol, side=side, amount=amount,
        order_type=order_type, price=entry_price,
    )
    print(f"  [{symbol.upper()}] order({side}): {order['order_id']} "
          f"price={entry_price:,.0f} amount={amount:.6f}")

    fill = executor.wait_for_fill(order["order_id"], symbol)
    if fill:
        filled_price = fill.get("avg_price") or entry_price
        position.open_position(
            symbol=symbol, side=side, order_id=order["order_id"],
            entry_price=filled_price, amount=amount,
        )
        logger.log_order({**order, "filled_price": filled_price})
        notifier.notify_entry(symbol, side, filled_price, amount, order_type, signal)
        print(f"  [{symbol.upper()}] filled({side}): price={filled_price:,.0f}")
    else:
        print(f"  [{symbol.upper()}] fill timeout: cancelled")


def main():
    config     = load_config()
    mode       = config["mode"]["run"]
    interval   = config["loop"]["interval_sec"]
    max_err    = config["loop"]["max_consecutive_errors"]
    symbols    = [t["symbol"] for t in config.get("targets", [])
                  if t.get("enabled", True)]
    order_type = config.get("bitbank", {}).get("order_type_default", "limit")

    if not symbols:
        print("[main] No active symbols in config.yml")
        return

    executor  = build_executor(config)
    strategy  = TrendFollowStrategy(config)
    guard     = Guard(config)
    positions = {sym: PositionManager(config, sym) for sym in symbols}
    risk      = RiskManager(config)
    logger    = Logger(config)
    notifier  = Notifier(config)
    fee_calc  = FeeCalculator(config)

    dry_tag = "[DRY_RUN] " if executor.is_dry_run() else "[LIVE] "
    print(f"\n{dry_tag}===== Trading Bot =====")
    print(f"  Exchange : {config['active_exchange']}")
    print(f"  Symbols  : {', '.join(s.upper() for s in symbols)}")
    print(f"  Mode     : {mode}")
    print(f"  Interval : {interval}s")
    print("=" * 40)

    logger.log_info("Bot start", {"mode": mode, "symbols": symbols})
    notifier.notify_startup(mode, symbols[0])

    consec_errors = 0

    while True:
        try:
            if guard.reset_if_new_day():
                logger.log_info("Daily reset")
                print("[main] Daily reset")

            ok, stop_reason = guard.can_trade()
            if not ok:
                print(f"[main] Stopped: {stop_reason}")
                time.sleep(interval)
                continue

            balance = executor.get_balance()

            for symbol in symbols:
                position = positions[symbol]
                try:
                    ticker = executor.get_ticker(symbol)
                    ohlcv  = executor.get_ohlcv(symbol, period="1min", count=60)
                    last   = ticker["last"]
                    print(f"[{symbol.upper()}] last={last:,.0f}  "
                          f"bid={ticker['best_bid']:,.0f}  "
                          f"ask={ticker['best_ask']:,.0f}")
                except Exception as e:
                    print(f"[{symbol.upper()}] data error: {e}")
                    logger.log_error(e, {"symbol": symbol,
                                         "traceback": traceback.format_exc()})
                    continue

                if position.is_open():
                    pos = position.get()
                    exit_reason = None
                    if position.should_take_profit(last):
                        exit_reason = f"TP={pos.take_profit:,.0f}"
                    elif position.should_stop_loss(last):
                        exit_reason = f"SL={pos.stop_loss:,.0f}"

                    if exit_reason:
                        exit_side  = "sell" if pos.side == "buy" else "buy"
                        exit_order = executor.place_order(
                            symbol=symbol, side=exit_side, amount=pos.amount,
                            order_type=order_type, price=last,
                        )
                        fill = executor.wait_for_fill(exit_order["order_id"], symbol)
                        exit_price = (fill["avg_price"]
                                      if fill and fill.get("avg_price") else last)

                        gross_pnl = position.close_position(exit_price)
                        net_pnl   = fee_calc.effective_pnl(
                            gross_pnl,
                            symbol, pos.amount, pos.entry_price, order_type,
                            symbol, pos.amount, exit_price, order_type,
                        )
                        guard.record_trade(net_pnl, pos.side)

                        logger.log_exit({
                            "symbol": symbol, "side": exit_side,
                            "exit_price": exit_price, "amount": pos.amount,
                            "gross_pnl": round(gross_pnl, 2),
                            "net_pnl":   round(net_pnl, 2),
                            "reason":    exit_reason,
                        })
                        notifier.notify_exit(symbol, exit_side, exit_price,
                                             pos.amount, net_pnl, exit_reason)
                        sign = "+" if net_pnl >= 0 else ""
                        print(f"  [{symbol.upper()}] exit {exit_reason} "
                              f"PnL={sign}{net_pnl:,.0f}JPY")
                    else:
                        print(f"  [{symbol.upper()}] holding "
                              f"side={pos.side} entry={pos.entry_price:,.0f} "
                              f"TP={pos.take_profit:,.0f} SL={pos.stop_loss:,.0f}")

                else:
                    signal = strategy.evaluate(ohlcv, ticker, False, symbol)
                    logger.log_signal(symbol, signal)
                    print(f"  [{symbol.upper()}] signal: {signal}")

                    if signal.type == SignalType.BUY:
                        _place_entry(executor, guard, risk, position, logger,
                                     notifier, balance, symbol,
                                     "buy", ticker, order_type, signal)
                    elif signal.type == SignalType.SELL:
                        # 現物取引のみのため空売りはスキップ
                        print(f"  [{symbol.upper()}] SELL signal skipped (現物のみ)")

            consec_errors = 0

        except KeyboardInterrupt:
            print("\n[main] Ctrl+C -> stopping")
            # Ctrl+C は一時停止扱い。stopped フラグは立てない（再起動後も取引継続可能）
            notifier.notify_stop("Manual stop (Ctrl+C)")
            stats = guard.get_stats()
            logger.log_daily_summary(stats)
            notifier.notify_daily_summary(stats)
            break

        except Exception as e:
            consec_errors += 1
            tb = traceback.format_exc()
            print(f"[main] error ({consec_errors}/{max_err}): {e}")
            logger.log_error(e, {"traceback": tb})
            if consec_errors >= max_err:
                msg = f"Forced stop after {max_err} errors: {e}"
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
