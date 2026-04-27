"""
core/logger.py
==============
JSONLログ出力。全イベント（注文・約定・停止・エラー・シグナル）を記録する。
1日1ファイル（data/logs/YYYY-MM-DD.jsonl）に書き出す。
"""

import json
import os
from datetime import datetime, timezone


class Logger:
    def __init__(self, config: dict):
        self.output_dir = config.get("logger", {}).get("output_dir", "data/logs")
        os.makedirs(self.output_dir, exist_ok=True)

    def _log(self, event_type: str, data: dict):
        """JSONLファイルに1行書き出す"""
        now = datetime.now(timezone.utc)
        record = {
            "ts":    now.isoformat(),
            "event": event_type,
            **data,
        }
        date_str = now.strftime("%Y-%m-%d")
        path = os.path.join(self.output_dir, f"{date_str}.jsonl")
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    # --- 各イベント用メソッド ---

    def log_signal(self, symbol: str, signal):
        self._log("signal", {
            "symbol":   symbol,
            "signal":   signal.type.value,
            "strength": signal.strength,
            "reason":   signal.reason,
            "raw":      signal.raw,
        })

    def log_order(self, order: dict):
        self._log("order", order)

    def log_fill(self, fill: dict):
        self._log("fill", fill)

    def log_exit(self, data: dict):
        self._log("exit", data)

    def log_stop(self, reason: str, state: dict = None):
        self._log("stop", {"reason": reason, "state": state or {}})

    def log_error(self, error: Exception, context: dict = None):
        self._log("error", {
            "error_type": type(error).__name__,
            "message":    str(error),
            "context":    context or {},
        })

    def log_info(self, message: str, data: dict = None):
        self._log("info", {"message": message, **(data or {})})

    def log_daily_summary(self, stats: dict):
        self._log("daily_summary", stats)
