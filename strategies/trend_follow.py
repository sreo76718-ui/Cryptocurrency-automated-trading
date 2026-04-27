"""
strategies/trend_follow.py
==========================
EMAクロス + ATRボラティリティ フィルターによる順張り短期戦略。

エントリー条件（全て満たす必要あり）:
  1. 短期EMA が 長期EMA を上抜け（買い） / 下抜け（売り）
  2. ATR/価格 が min_atr_ratio 以上（無風時はエントリーしない）
     ※ 土日は min_atr_ratio_weekend を使用（ボラティリティが低いため閾値を緩める）
  3. ポジションなし

決済シグナルはこの戦略では出さない（position.py の TP/SL に委ねる）。
"""

from datetime import datetime, timezone, timedelta

from core.signal import Signal, SignalType

JST = timezone(timedelta(hours=9))


class TrendFollowStrategy:
    def __init__(self, config: dict):
        cfg              = config.get("strategy", {})
        trend_cfg        = cfg.get("trend", {})
        vol_cfg          = cfg.get("volatility", {})
        self.fast_period         = trend_cfg.get("fast_period", 5)
        self.slow_period         = trend_cfg.get("slow_period", 20)
        self.atr_period          = vol_cfg.get("atr_period", 14)
        self.min_atr_ratio         = vol_cfg.get("min_atr_ratio", 0.0002)
        self.min_atr_ratio_weekend = vol_cfg.get("min_atr_ratio_weekend", 0.00008)

    def _effective_atr_ratio(self) -> float:
        """曜日に応じた ATR 閾値を返す（土=5, 日=6）"""
        weekday = datetime.now(JST).weekday()
        if weekday >= 5:
            return self.min_atr_ratio_weekend
        return self.min_atr_ratio

    # ----------------------------------------------------------------
    # メイン評価
    # ----------------------------------------------------------------
    def evaluate(self, ohlcv: list, ticker: dict, has_position: bool) -> Signal:
        """
        ohlcv: get_ohlcv() の戻り値リスト（古い順）
        ticker: get_ticker() の戻り値
        has_position: 現在ポジションを持っているか

        Returns: Signal
        """
        # データ本数チェック
        min_count = self.slow_period + 2
        if len(ohlcv) < min_count:
            return Signal(
                type=SignalType.HOLD,
                reason=f"OHLCVデータ不足({len(ohlcv)}<{min_count})",
            )

        closes = [c["close"] for c in ohlcv]
        highs  = [c["high"]  for c in ohlcv]
        lows   = [c["low"]   for c in ohlcv]

        # EMA計算（最新2点分）
        fast_now  = self._ema(closes, self.fast_period)
        slow_now  = self._ema(closes, self.slow_period)
        fast_prev = self._ema(closes[:-1], self.fast_period)
        slow_prev = self._ema(closes[:-1], self.slow_period)

        # ATR / ボラティリティフィルター（曜日で閾値を切り替え）
        atr           = self._atr(highs, lows, closes, self.atr_period)
        last_price    = closes[-1]
        atr_ratio     = atr / last_price if last_price > 0 else 0
        atr_threshold = self._effective_atr_ratio()
        is_weekend    = datetime.now(JST).weekday() >= 5

        raw = {
            "fast_ema":     round(fast_now, 2),
            "slow_ema":     round(slow_now, 2),
            "atr":          round(atr, 2),
            "atr_ratio":    round(atr_ratio, 6),
            "atr_threshold": atr_threshold,
            "last":         last_price,
            "is_weekend":   is_weekend,
        }

        # ポジション保有中はエントリーシグナルを出さない
        if has_position:
            return Signal(type=SignalType.HOLD, reason="ポジション保有中", raw=raw)

        # ボラティリティ不足
        day_label = "土日" if is_weekend else "平日"
        if atr_ratio < atr_threshold:
            return Signal(
                type=SignalType.HOLD,
                reason=f"ボラティリティ不足[{day_label}](ATR比={atr_ratio:.5f}<{atr_threshold})",
                raw=raw,
            )

        # クロス判定
        bullish_cross = (fast_prev <= slow_prev) and (fast_now > slow_now)
        bearish_cross = (fast_prev >= slow_prev) and (fast_now < slow_now)

        if bullish_cross:
            strength = min(1.0, atr_ratio / atr_threshold / 2)
            return Signal(
                type=SignalType.BUY,
                strength=round(strength, 2),
                reason=f"EMAクロス上抜け[{day_label}] / ATR比={atr_ratio:.5f}",
                raw=raw,
            )

        if bearish_cross:
            # 現在は BUY のみ対応。SELL は将来拡張
            return Signal(
                type=SignalType.HOLD,
                reason=f"EMAクロス下抜け（SELL未対応）[{day_label}] / ATR比={atr_ratio:.5f}",
                raw=raw,
            )

        return Signal(
            type=SignalType.HOLD,
            reason=f"クロスなし[{day_label}](fast={fast_now:.0f}, slow={slow_now:.0f})",
            raw=raw,
        )

    # ----------------------------------------------------------------
    # 計算ヘルパー（pandas不使用）
    # ----------------------------------------------------------------
    @staticmethod
    def _ema(values: list, period: int) -> float:
        """指数移動平均（最後の値を返す）"""
        if len(values) < period:
            return sum(values) / len(values)
        k = 2 / (period + 1)
        ema = sum(values[:period]) / period  # 初期値はSMA
        for v in values[period:]:
            ema = v * k + ema * (1 - k)
        return ema

    @staticmethod
    def _atr(highs: list, lows: list, closes: list, period: int) -> float:
        """ATR（Average True Range）計算"""
        trs = []
        for i in range(1, len(closes)):
            h, l, pc = highs[i], lows[i], closes[i - 1]
            tr = max(h - l, abs(h - pc), abs(l - pc))
            trs.append(tr)
        if not trs:
            return 0.0
        recent = trs[-period:] if len(trs) >= period else trs
        return sum(recent) / len(recent)
