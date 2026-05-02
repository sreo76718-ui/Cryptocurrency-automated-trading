"""
strategies/trend_follow.py
==========================
EMAクロス + ATRボラティリティ + RSI + 出来高フィルターによる順張り短期戦略。

エントリー条件（全て満たす必要あり）:
  1. 短期EMA が 長期EMA を上抜け（買い） / 下抜け（売り）
  2. ATR/価格 が min_atr_ratio 以上（無風時はエントリーしない）
     ※ 土日は min_atr_ratio_weekend を使用（ボラティリティが低いため閾値を緩める）
  3. RSI フィルター（銘柄ごとにオン/オフ・閾値を設定）
     - BUY: RSI >= rsi_buy_min (default 50)
     - SELL: RSI <= rsi_sell_max (default 50)
     [Supertrend戦略参考: トレンド方向とRSIが一致する場合のみエントリー]
  4. 出来高フィルター（銘柄ごとにオン/オフ）
     - 直近出来高 > volume_sma_period 期間平均 × volume_ratio_min
     [Strategy005参考: 出来高の伴わないシグナルを除外]
  5. ポジションなし

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

        # 銘柄別オーバーライドを targets から取得してキャッシュ
        self._symbol_overrides = {}
        for t in config.get("targets", []):
            sym = t.get("symbol", "")
            so = t.get("strategy_overrides", {})
            eo = t.get("exit_overrides", {})
            if so or eo:
                self._symbol_overrides[sym] = {"strategy": so, "exit": eo}

    def _get_params(self, symbol: str) -> dict:
        """銘柄ごとのパラメータを返す（オーバーライドがあれば適用）"""
        so = self._symbol_overrides.get(symbol, {}).get("strategy", {})
        return {
            "fast_period":       so.get("fast_period",      self.fast_period),
            "slow_period":       so.get("slow_period",      self.slow_period),
            "min_atr_ratio":     so.get("min_atr_ratio",    self.min_atr_ratio),
            "rsi_period":        so.get("rsi_period",       0),    # 0=無効
            "rsi_buy_min":       so.get("rsi_buy_min",      50),
            "rsi_sell_max":      so.get("rsi_sell_max",     50),
            "volume_filter":     so.get("volume_filter",    False),
            "volume_sma_period": so.get("volume_sma_period", 20),
            "volume_ratio_min":  so.get("volume_ratio_min", 1.5),
        }

    def _effective_atr_ratio(self, min_atr_ratio: float) -> float:
        """曜日に応じた ATR 閾値を返す（土=5, 日=6）"""
        weekday = datetime.now(JST).weekday()
        if weekday >= 5:
            return self.min_atr_ratio_weekend
        return min_atr_ratio

    # ----------------------------------------------------------------
    # メイン評価
    # ----------------------------------------------------------------
    def evaluate(self, ohlcv: list, ticker: dict, has_position: bool,
                 symbol: str = "") -> Signal:
        """
        ohlcv  : get_ohlcv() の戻り値リスト（古い順）
        ticker : get_ticker() の戻り値
        has_position: 現在ポジションを持っているか
        symbol : 銘柄（オーバーライド参照用）

        Returns: Signal
        """
        params = self._get_params(symbol)
        fast_period       = params["fast_period"]
        slow_period       = params["slow_period"]
        min_atr_ratio     = params["min_atr_ratio"]
        rsi_period        = params["rsi_period"]
        rsi_buy_min       = params["rsi_buy_min"]
        rsi_sell_max      = params["rsi_sell_max"]
        volume_filter     = params["volume_filter"]
        volume_sma_period = params["volume_sma_period"]
        volume_ratio_min  = params["volume_ratio_min"]

        # データ本数チェック
        min_count = slow_period + 2
        if len(ohlcv) < min_count:
            return Signal(
                type=SignalType.HOLD,
                reason=f"OHLCVデータ不足({len(ohlcv)}<{min_count})",
            )

        closes  = [c["close"]  for c in ohlcv]
        highs   = [c["high"]   for c in ohlcv]
        lows    = [c["low"]    for c in ohlcv]
        volumes = [c["volume"] for c in ohlcv]

        # EMA計算（最新2点分）
        fast_now  = self._ema(closes, fast_period)
        slow_now  = self._ema(closes, slow_period)
        fast_prev = self._ema(closes[:-1], fast_period)
        slow_prev = self._ema(closes[:-1], slow_period)

        # ATR / ボラティリティフィルター
        atr           = self._atr(highs, lows, closes, self.atr_period)
        last_price    = closes[-1]
        atr_ratio     = atr / last_price if last_price > 0 else 0
        atr_threshold = self._effective_atr_ratio(min_atr_ratio)
        is_weekend    = datetime.now(JST).weekday() >= 5

        # RSI計算（rsi_period > 0 の場合のみ）
        rsi_val = None
        if rsi_period > 0 and len(closes) >= rsi_period + 1:
            rsi_val = self._rsi(closes, rsi_period)

        # 出来高フィルター
        vol_ok = True
        vol_ratio = None
        if volume_filter and len(volumes) >= volume_sma_period:
            vol_sma   = sum(volumes[-volume_sma_period:]) / volume_sma_period
            vol_ratio = volumes[-1] / vol_sma if vol_sma > 0 else 0
            vol_ok    = vol_ratio >= volume_ratio_min

        raw = {
            "fast_ema":      round(fast_now, 2),
            "slow_ema":      round(slow_now, 2),
            "atr":           round(atr, 2),
            "atr_ratio":     round(atr_ratio, 6),
            "atr_threshold": atr_threshold,
            "last":          last_price,
            "is_weekend":    is_weekend,
        }
        if rsi_val is not None:
            raw["rsi"] = round(rsi_val, 1)
        if vol_ratio is not None:
            raw["vol_ratio"] = round(vol_ratio, 2)

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

        # 出来高不足
        if not vol_ok:
            return Signal(
                type=SignalType.HOLD,
                reason=f"出来高不足(ratio={vol_ratio:.2f}<{volume_ratio_min})",
                raw=raw,
            )

        # クロス判定
        bullish_cross = (fast_prev <= slow_prev) and (fast_now > slow_now)
        bearish_cross = (fast_prev >= slow_prev) and (fast_now < slow_now)

        if bullish_cross:
            # RSIフィルター（BUY: RSIが上昇トレンド側か確認）
            if rsi_val is not None and rsi_val < rsi_buy_min:
                return Signal(
                    type=SignalType.HOLD,
                    reason=f"EMAクロス上抜けだがRSI低値(RSI={rsi_val:.1f}<{rsi_buy_min})",
                    raw=raw,
                )
            strength = min(1.0, atr_ratio / atr_threshold / 2)
            rsi_info = f" RSI={rsi_val:.1f}" if rsi_val is not None else ""
            return Signal(
                type=SignalType.BUY,
                strength=round(strength, 2),
                reason=f"EMAクロス上抜け[{day_label}] ATR比={atr_ratio:.5f}{rsi_info}",
                raw=raw,
            )

        if bearish_cross:
            # RSIフィルター（SELL: RSIが下降トレンド側か確認）
            if rsi_val is not None and rsi_val > rsi_sell_max:
                return Signal(
                    type=SignalType.HOLD,
                    reason=f"EMAクロス下抜けだがRSI高値(RSI={rsi_val:.1f}>{rsi_sell_max})",
                    raw=raw,
                )
            strength = min(1.0, atr_ratio / atr_threshold / 2)
            rsi_info = f" RSI={rsi_val:.1f}" if rsi_val is not None else ""
            return Signal(
                type=SignalType.SELL,
                strength=round(strength, 2),
                reason=f"EMAクロス下抜け[{day_label}] ATR比={atr_ratio:.5f}{rsi_info}",
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
        ema = sum(values[:period]) / period
        for v in values[period:]:
            ema = v * k + ema * (1 - k)
        return ema

    @staticmethod
    def _rsi(closes: list, period: int = 14) -> float:
        """RSI（相対力指数）計算"""
        if len(closes) < period + 1:
            return 50.0
        gains, losses = [], []
        for i in range(1, len(closes)):
            diff = closes[i] - closes[i - 1]
            gains.append(max(diff, 0))
            losses.append(max(-diff, 0))
        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

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
