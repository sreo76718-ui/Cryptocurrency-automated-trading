"""
exchanges/bitbank/fill.py
=========================
約定確認ポーリング。
指定秒間隔でステータスを確認し、約定 or タイムアウトまで待つ。
"""

import time


class FillChecker:
    def __init__(self, config: dict):
        cfg = config.get("bitbank", {})
        self.interval = cfg.get("fill_check_interval_sec", 3)
        self.timeout  = cfg.get("fill_timeout_sec", 90)

    def wait(self, executor, order_id: str, symbol: str) -> dict | None:
        """
        約定まで待つ。
        Returns: 約定情報 dict  or  None（タイムアウト・キャンセル）
        """
        # dry_run は即座に返す
        if executor.is_dry_run():
            return executor.get_order_status(order_id, symbol)

        elapsed = 0
        while elapsed < self.timeout:
            status = executor.get_order_status(order_id, symbol)
            if status["status"] == "filled":
                return status
            if status["status"] == "cancelled":
                return None
            time.sleep(self.interval)
            elapsed += self.interval

        # タイムアウト → キャンセル
        print(f"[fill] 約定タイムアウト({self.timeout}秒) → キャンセル: {order_id}")
        executor.cancel_order(order_id, symbol)
        return None
