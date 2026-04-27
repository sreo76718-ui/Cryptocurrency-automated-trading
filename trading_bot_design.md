# 自動売買システム 設計整理ドキュメント
**bitbank API 先行 / OANDA東京サーバー後置き / 改善しやすい構造優先**
作成日: 2026-04-19

---

## 1. 現在設計の問題点と改善方針

### 問題点

**① bitbankとOANDAを"同格"で並べすぎている**
- 現在案では bitbank / OANDA の両執行層をほぼ同時に設計しようとしており、MVP完成が遅れやすい。
- OANDA東京サーバーはMT5/EAという別技術スタックなので、最初から混ぜると設計が複雑になる。

**② 共通コアとbitbank実行層の境界が曖昧**
- 「共通コア」と「市場固有処理」の切れ目が明確に定義されていないと、後から拡張する際に迷いが生じる。
- 特にbitbank固有の手数料計算・板操作・注文種別の扱いが共通コアに混入しやすい。

**③ configの設計方針が「後から考える」になっている**
- 最初から調整可能にしたい箇所（閾値・資金比率・停止条件）が散在しており、管理ポイントが不明瞭。
- 一方で、configを増やしすぎてMVPが遅れるリスクもある。

**④ OANDAのNYサーバーの扱いが曖昧**
- 「将来拡張」と言いつつ、設計に入り込んでいる。初期実装で無視してよい旨を明記する必要がある。

**⑤ dry_run / 検証 / 本番の切替が明示されていない**
- どのファイルで何を切り替えるかが決まっていないと、本番誤爆リスクがある。

### 改善方針

| 問題 | 方針 |
|------|------|
| bitbank/OANDA同格設計 | Phase 1はbitbankのみに集中。OANDAは接続口だけ定義して後置き |
| 境界の曖昧さ | `core/` と `exchanges/bitbank/` の責任範囲をインターフェース定義で明確化 |
| config管理 | 1ファイル構成 + 環境変数で本番/dry_run切替。増やすのはPhase 2以降 |
| NYサーバー | インターフェースのみ定義、実装なしで放置でOK |
| 実行モード | `DRY_RUN=true` 環境変数 + config.ymlの`mode:`フィールドで一元管理 |

---

## 2. 改良版アーキテクチャ概要

```
┌─────────────────────────────────────────────────────────────────┐
│                        main.py (エントリーポイント)              │
│              モード判定(dry_run/verify/live) → ループ起動        │
└───────────────────────────┬─────────────────────────────────────┘
                            │
        ┌───────────────────▼───────────────────┐
        │              core/ (共通コア)           │
        │  ┌──────────┐  ┌──────────┐            │
        │  │ strategy │  │ position │            │
        │  │ (判断)   │  │ (状態管理)│           │
        │  └──────────┘  └──────────┘            │
        │  ┌──────────┐  ┌──────────┐            │
        │  │ risk     │  │ guard    │            │
        │  │ (資金管理)│  │ (停止制御)│           │
        │  └──────────┘  └──────────┘            │
        │  ┌──────────┐  ┌──────────┐            │
        │  │ logger   │  │ notifier │            │
        │  │ (JSONL)  │  │ (Discord)│            │
        │  └──────────┘  └──────────┘            │
        └───────────────────┬───────────────────┘
                            │ ExecutorInterface
             ┌──────────────┼──────────────────┐
             │              │                  │
    ┌────────▼────────┐     │          ┌───────▼───────────┐
    │ exchanges/      │     │          │ exchanges/        │
    │ bitbank/        │     │          │ oanda_tokyo/      │
    │ ① Phase 1 実装  │     │          │ ② Phase 2 実装    │
    │                 │     │          │ (MT5/EA連携)      │
    │ - order.py      │     │          │ - ea_bridge.py    │
    │ - fill.py       │     │          │ (stub/placeholder)│
    │ - fee.py        │     │          └───────────────────┘
    │ - spread.py     │     │
    └─────────────────┘     │          ┌───────────────────┐
                            │          │ exchanges/        │
                            │          │ oanda_ny/         │
                            └──────────│ ③ 将来拡張のみ    │
                                       │ (インターフェース) │
                                       └───────────────────┘
```

### 設計の核心原則

- **共通コアは「判断・資金管理・停止制御・ログ・通知」のみ**
- **執行層（`exchanges/`配下）は市場ごとに完全分離**
- **コアとの接続は `ExecutorInterface`（抽象基底クラス）だけ**
- **Phase 1でインターフェースを固めることが、Phase 2の横展開を速くする**

---

## 3. 改良版フォルダ構成

```
trading_bot/
├── main.py                    # エントリーポイント。モード判定・ループ制御
├── config.yml                 # 全設定の一元管理（dry_run/live切替もここ）
├── .env                       # APIキーのみ。.gitignoreに追加必須
├── requirements.txt
│
├── core/                      # 共通コア（市場に依存しない）
│   ├── __init__.py
│   ├── strategy.py            # エントリー判断ロジック（トレンド・ボラティリティ）
│   ├── signal.py              # シグナル構造体（買い/売り/見送り + 強度）
│   ├── position.py            # ポジション状態管理（保有中/未保有/決済待ち）
│   ├── risk.py                # 資金管理（1回あたりの発注サイズ計算）
│   ├── guard.py               # 停止制御（連敗停止・日次損失上限・同方向連続制御）
│   ├── logger.py              # JSONLログ出力（注文・約定・停止・エラー）
│   ├── notifier.py            # Discord通知（Webhook）
│   └── executor_interface.py  # 執行層の抽象基底クラス（Protocolで定義）
│
├── exchanges/                 # 執行層（市場ごとに完全分離）
│   ├── bitbank/               # ★ Phase 1 実装対象
│   │   ├── __init__.py
│   │   ├── executor.py        # ExecutorInterfaceの実装。core/から呼ばれる唯一の窓口
│   │   ├── order.py           # 注文発行（指値・成行・IOC）
│   │   ├── fill.py            # 約定確認・ステータスポーリング
│   │   ├── fee.py             # 手数料計算（メイカー/テイカー別）
│   │   ├── spread.py          # 板取得・スプレッド判定
│   │   ├── market_data.py     # OHLCV・ティッカー取得
│   │   └── exceptions.py      # bitbank固有のエラー定義
│   │
│   ├── oanda_tokyo/           # Phase 2 実装対象（MT5/EA連携）
│   │   ├── __init__.py
│   │   ├── executor.py        # stub: ExecutorInterfaceを継承、実装はPhase 2
│   │   └── ea_bridge.py       # MT5 EAとの連携口（ファイル渡し or ソケット）
│   │
│   └── oanda_ny/              # 将来拡張のみ（インターフェース定義だけ残す）
│       ├── __init__.py
│       └── executor.py        # stub: NotImplementedErrorのみ
│
├── strategies/                # 戦略モジュール（coreのstrategy.pyから呼び出す）
│   ├── __init__.py
│   ├── base.py                # 戦略の基底クラス
│   └── trend_follow.py        # Phase 1の初期戦略（順張り短期）
│
├── data/                      # ローカルデータ（状態・ログ保存先）
│   ├── logs/                  # JSONL形式のログ（日付別）
│   ├── state/                 # ポジション状態の永続化（JSONファイル）
│   └── backtest/              # バックテスト用データ（将来）
│
├── tests/                     # テスト
│   ├── test_core/
│   │   ├── test_strategy.py
│   │   ├── test_risk.py
│   │   └── test_guard.py
│   └── test_exchanges/
│       └── test_bitbank/
│           ├── test_order.py   # モックAPIを使ったテスト
│           └── test_fee.py
│
└── scripts/                   # 補助スクリプト
    ├── check_api.py            # APIキー疎通確認（最初に使う）
    ├── fetch_ohlcv.py          # 過去データ取得
    └── notify_test.py          # Discord通知テスト
```

---

## 4. 改良版 config 一覧

`config.yml` に一元管理。セクションごとに責任範囲を分割する。

```yaml
# config.yml
# ============================================================
# システム全体の設定ファイル
# APIキーは .env に書き、ここには書かない
# ============================================================

# --- 実行モード ---
mode:
  run: "dry_run"          # "dry_run" | "verify" | "live"
  # dry_run : 注文API呼び出しをスキップ、ログとDiscordは出す
  # verify  : 実際に極小量で注文を出し、動作確認する
  # live    : 本番稼働

# --- アクティブな市場 ---
active_exchange: "bitbank"  # "bitbank" | "oanda_tokyo" (Phase 2以降)

# --- ループ設定 ---
loop:
  interval_sec: 30          # 判断サイクル（秒）。短すぎるとレートリミット注意
  max_consecutive_errors: 5 # 連続エラーで強制停止する閾値

# --- 取引対象 ---
targets:
  - symbol: "BTC_JPY"
    enabled: true
    # 将来: ETH_JPY, XRP_JPY も追加予定

# --- 戦略設定 ---
strategy:
  name: "trend_follow"      # strategies/配下のモジュール名と対応
  trend:
    fast_period: 5          # 短期EMA期間
    slow_period: 20         # 長期EMA期間
  volatility:
    atr_period: 14
    min_atr_ratio: 0.003    # 最低ボラティリティ（無風時はエントリーしない）

# --- 資金管理 ---
risk:
  max_order_ratio: 0.02     # 1回の発注で使う残高の上限比率（2%）
  min_order_jpy: 5000       # 最低発注額（JPY）

# --- 損失制御 ---
guard:
  max_daily_loss_jpy: 10000  # 日次最大損失（この金額を超えたら当日停止）
  max_consecutive_loss: 3    # 連続損失でその日の取引を停止
  same_direction_limit: 2    # 同方向へ連続エントリーできる最大回数

# --- bitbank固有設定 ---
bitbank:
  order_type_default: "limit"   # "limit" | "market"
  taker_allowed_on_surge: true  # 急変時にtakerを許可するか
  spread_threshold_ratio: 0.002 # スプレッドがこれより広い時はエントリーしない
  fill_check_interval_sec: 2    # 約定確認ポーリング間隔
  fill_timeout_sec: 60          # この時間内に約定しなければキャンセル

# --- OANDA東京（Phase 2用。初期は無効のまま）---
oanda_tokyo:
  enabled: false              # Phase 2になるまで触らない

# --- OANDA NY（将来拡張用。初期は完全無効）---
oanda_ny:
  enabled: false

# --- Discord通知 ---
notifier:
  discord:
    enabled: true
    # Webhook URLは .env の DISCORD_WEBHOOK_URL から読む
    notify_on: ["entry", "exit", "error", "stop", "daily_summary"]
    silent_on_dry_run: false  # dry_runでも通知する（確認目的）

# --- ログ ---
logger:
  format: "jsonl"
  output_dir: "data/logs"
  rotate_daily: true
  level: "INFO"             # "DEBUG" | "INFO" | "WARNING" | "ERROR"
```

**`.env`（git管理しない）**
```
BITBANK_API_KEY=xxxx
BITBANK_API_SECRET=xxxx
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
OANDA_TOKYO_ACCOUNT_ID=     # Phase 2まで空欄でOK
OANDA_TOKYO_API_TOKEN=      # Phase 2まで空欄でOK
```

---

## 5. 改良版 関数一覧

### core/executor_interface.py（抽象インターフェース）

```python
from typing import Protocol

class ExecutorInterface(Protocol):
    """
    全執行層が実装しなければならないインターフェース。
    coreはこれだけを知る。市場固有の実装は exchanges/ 配下に隠蔽する。
    """
    def get_balance(self) -> dict:
        """残高取得。{"jpy": float, "btc": float, ...} を返す"""
        ...
    def get_ticker(self, symbol: str) -> dict:
        """最新ティッカー。{"best_bid": float, "best_ask": float, "last": float}"""
        ...
    def get_ohlcv(self, symbol: str, period: str, count: int) -> list[dict]:
        """OHLCV取得。[{"open":, "high":, "low":, "close":, "volume":, "ts":}]"""
        ...
    def place_order(self, symbol: str, side: str, amount: float,
                    order_type: str, price: float | None) -> dict:
        """注文発行。{"order_id": str, "status": str, ...} を返す"""
        ...
    def get_order_status(self, order_id: str) -> dict:
        """注文状態確認。{"status": "open"|"filled"|"cancelled", ...}"""
        ...
    def cancel_order(self, order_id: str) -> bool:
        """注文キャンセル。成功でTrue"""
        ...
    def is_dry_run(self) -> bool:
        """dry_runモードか否か"""
        ...
```

### core/strategy.py

| 関数名 | 引数 | 戻り値 | 説明 |
|--------|------|--------|------|
| `evaluate(ohlcv, ticker, position)` | リスト, dict, dict | `Signal` | エントリー・決済判断のメイン |
| `_calc_trend(ohlcv)` | リスト | `{"direction": "up"\|"down"\|"flat", "strength": float}` | EMAクロス計算 |
| `_calc_volatility(ohlcv)` | リスト | `float` | ATRベースのボラティリティ計算 |
| `_check_spread(ticker)` | dict | `bool` | スプレッドが許容範囲内か |

### core/signal.py

```python
from dataclasses import dataclass
from enum import Enum

class SignalType(Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"   # 様子見
    EXIT = "exit"   # 決済（ポジション保有中の判断）

@dataclass
class Signal:
    type: SignalType
    strength: float          # 0.0〜1.0。強いほど積極的に動く
    reason: str              # ログ・通知に使う理由文字列
    raw: dict                # デバッグ用。計算途中の数値を入れる
```

### core/position.py

| 関数名 | 引数 | 戻り値 | 説明 |
|--------|------|--------|------|
| `load()` | - | `PositionState` | data/state/から状態を読み込む |
| `save(state)` | `PositionState` | - | 状態をJSONで保存 |
| `open_position(order_id, side, amount, price, ts)` | 各種 | - | ポジションを持ち始めた時 |
| `close_position(exit_price, ts)` | float, datetime | `float` | 決済。PnLを返す |
| `is_open()` | - | `bool` | ポジション保有中か |

### core/risk.py

| 関数名 | 引数 | 戻り値 | 説明 |
|--------|------|--------|------|
| `calc_order_size(balance, price, config)` | float, float, dict | `float` | 発注額（BTC単位）を計算 |
| `validate_min_order(amount_jpy, config)` | float, dict | `bool` | 最低発注額チェック |

### core/guard.py

| 関数名 | 引数 | 戻り値 | 説明 |
|--------|------|--------|------|
| `can_trade(state)` | `GuardState` | `(bool, str)` | 取引可能か判定。Falseの場合は理由も返す |
| `record_loss(pnl, state)` | float, `GuardState` | `GuardState` | 損失記録・停止フラグ更新 |
| `record_win(pnl, state)` | float, `GuardState` | `GuardState` | 勝ち記録（連敗カウンタリセット） |
| `reset_daily(state)` | `GuardState` | `GuardState` | 日次リセット（日付が変わったら呼ぶ） |
| `is_same_direction_blocked(side, state)` | str, `GuardState` | `bool` | 同方向連続制限チェック |

### core/logger.py

| 関数名 | 引数 | 戻り値 | 説明 |
|--------|------|--------|------|
| `log_order(order_dict)` | dict | - | 注文をJSONLに記録 |
| `log_fill(fill_dict)` | dict | - | 約定をJSONLに記録 |
| `log_signal(signal)` | `Signal` | - | シグナルをJSONLに記録 |
| `log_stop(reason, state)` | str, dict | - | 停止イベントを記録 |
| `log_error(error, context)` | Exception, dict | - | エラーをJSONLに記録 |

### core/notifier.py

| 関数名 | 引数 | 戻り値 | 説明 |
|--------|------|--------|------|
| `notify_entry(signal, order)` | `Signal`, dict | - | エントリー通知 |
| `notify_exit(pnl, order)` | float, dict | - | 決済通知（損益付き） |
| `notify_error(msg)` | str | - | エラー通知（赤埋め込み） |
| `notify_stop(reason)` | str | - | 停止通知 |
| `notify_daily_summary(stats)` | dict | - | 日次サマリー通知 |
| `_send(payload)` | dict | - | Webhook送信の内部実装 |

### exchanges/bitbank/executor.py

| 関数名 | 引数 | 戻り値 | 説明 |
|--------|------|--------|------|
| `get_balance()` | - | dict | 残高取得 |
| `get_ticker(symbol)` | str | dict | ティッカー取得 |
| `get_ohlcv(symbol, period, count)` | str, str, int | list | OHLCV取得 |
| `place_order(...)` | 各種 | dict | dry_runならスキップして仮データ返す |
| `get_order_status(order_id)` | str | dict | 注文状態ポーリング |
| `cancel_order(order_id)` | str | bool | キャンセル |
| `is_dry_run()` | - | bool | dry_runか確認 |

### exchanges/bitbank/order.py

| 関数名 | 引数 | 戻り値 | 説明 |
|--------|------|--------|------|
| `send_limit_order(api, symbol, side, amount, price)` | 各種 | dict | 指値注文発行 |
| `send_market_order(api, symbol, side, amount)` | 各種 | dict | 成行注文発行（急変時のみ） |
| `cancel(api, order_id)` | 各種 | bool | キャンセル発行 |

### exchanges/bitbank/fill.py

| 関数名 | 引数 | 戻り値 | 説明 |
|--------|------|--------|------|
| `wait_for_fill(api, order_id, timeout_sec, interval_sec)` | 各種 | dict | ポーリングで約定待ち |
| `parse_fill(raw_order)` | dict | dict | APIレスポンスを統一形式に変換 |

### exchanges/bitbank/fee.py

| 関数名 | 引数 | 戻り値 | 説明 |
|--------|------|--------|------|
| `calc_fee(amount, order_type, symbol)` | float, str, str | float | 手数料計算（メイカー/テイカー別） |
| `effective_pnl(gross_pnl, entry_fee, exit_fee)` | 各float | float | 手数料控除後の損益 |

---

## 6. 実装優先順位

### Phase 1（MVP完成まで。OANDAには触れない）

| 順番 | 対象ファイル | 理由 |
|------|------------|------|
| 1 | `scripts/check_api.py` | APIキーの疎通確認。最初の壁をここで突破する |
| 2 | `scripts/notify_test.py` | Discord通知の疎通確認 |
| 3 | `.env` + `config.yml` | 設定基盤。ここが安定していないと何も動かない |
| 4 | `core/logger.py` | ログなしで動かすとデバッグが辛い。最初に作る |
| 5 | `core/notifier.py` | Discord通知。テスト済みを流用 |
| 6 | `core/executor_interface.py` | インターフェース定義。bitbankとcoreの境界を固める |
| 7 | `exchanges/bitbank/executor.py` | ExecutorInterfaceの実装。dry_runを先に動かす |
| 8 | `core/signal.py` | シグナル構造体。strategyの前に型を決める |
| 9 | `core/strategy.py` + `strategies/trend_follow.py` | エントリー判断。既存ロジックを移植 |
| 10 | `core/guard.py` | 停止制御。損失制御は最初から入れる |
| 11 | `core/risk.py` | 発注サイズ計算 |
| 12 | `core/position.py` | ポジション状態管理 |
| 13 | `exchanges/bitbank/order.py` | 実際の注文発行（指値から始める） |
| 14 | `exchanges/bitbank/fill.py` | 約定確認ポーリング |
| 15 | `exchanges/bitbank/fee.py` | 手数料計算。PnLの正確性に必要 |
| 16 | `main.py` | 全部をつないでループを回す |

### Phase 2（bitbank稼働・安定後）

- `exchanges/oanda_tokyo/executor.py` に ExecutorInterface 実装
- `exchanges/oanda_tokyo/ea_bridge.py` でMT5 EAとの連携口を作る
- `strategies/trend_follow.py` の通貨ペア対応拡張
- ETH/JPY、XRP/JPY などへの銘柄拡張

### Phase 3（余力があれば）

- OANDA NYサーバー対応（`exchanges/oanda_ny/executor.py`）
- バックテスト基盤（`data/backtest/`活用）
- 複数戦略の並走

---

## 7. MVPの範囲

**「動く最小限」の定義：**
```
bitbank API × BTC/JPY × trend_follow戦略 × 1ポジション × dry_runで完走
```

### MVPに含めるもの

- dry_runモードでのループ動作（実際の注文は出さない）
- EMAクロスベースのシグナル生成
- Discordへのエントリー/決済/停止通知
- JSONLログへの全イベント記録
- 連敗停止・日次損失停止
- 指値注文 + 約定ポーリング（dry_run解除後）
- configで閾値変更可能

### MVPに含めないもの（後回し）

- OANDA東京サーバー連携
- ETH/JPY、XRP/JPY対応
- バックテスト
- 複数ポジション管理
- 成行注文（急変時の例外処理）
- 日次サマリー自動送信
- Webダッシュボード

---

## 8. 将来拡張の差し込みポイント

### OANDA東京サーバー追加手順（Phase 2）

1. `exchanges/oanda_tokyo/executor.py` に `ExecutorInterface` を実装
2. `config.yml` の `active_exchange: "oanda_tokyo"` に変更するだけでcoreがそちらを使う
3. `main.py` は変更不要（ExecutorInterfaceを通じて動く）

```python
# main.py の executor 切替イメージ（変更なし）
from core.executor_interface import ExecutorInterface

def build_executor(config) -> ExecutorInterface:
    if config["active_exchange"] == "bitbank":
        from exchanges.bitbank.executor import BitbankExecutor
        return BitbankExecutor(config)
    elif config["active_exchange"] == "oanda_tokyo":
        from exchanges.oanda_tokyo.executor import OandaTokyoExecutor
        return OandaTokyoExecutor(config)
    elif config["active_exchange"] == "oanda_ny":
        from exchanges.oanda_ny.executor import OandaNyExecutor
        return OandaNyExecutor(config)
    else:
        raise ValueError(f"Unknown exchange: {config['active_exchange']}")
```

### 銘柄拡張（ETH/JPY等）

- `config.yml` の `targets:` にエントリーを追加するだけ
- 銘柄固有パラメータは `targets[].params:` に閉じ込める（coreには入れない）

### 戦略追加

- `strategies/` に新ファイルを追加
- `config.yml` の `strategy.name:` を変更するだけ

### OANDAのNYサーバー対応（将来）

- `exchanges/oanda_ny/executor.py` に実装するだけ
- インターフェースが共通なのでcoreは変更不要

---

## 9. やらないこと一覧

| やらないこと | 理由 |
|------------|------|
| 超高速HFT（ミリ秒オーダー） | bitbank APIのレートリミットに引っかかる。設計目標外 |
| bitbankでのテイカー連打 | 手数料が高くPnLを圧迫する。急変時の例外のみ許可 |
| FXと仮想通貨の執行コードの共通化 | 手数料構造・注文種別・約定確認方法が根本的に異なる |
| OANDA/bitbankの最初からの統合 | MVPを遅らせるだけ。Phase 2で自然に接続できれば十分 |
| configの過剰な細分化 | 管理負荷が上がりMVPが遅れる。パラメータは最小限から始める |
| 通知専用ボット（発注なし）で完結 | 目的は自動売買。通知は手段、目的ではない |
| 複数ポジション同時保有（初期） | リスク管理の複雑度が跳ね上がる。まず1ポジション管理を安定させる |
| WebUI・ダッシュボード（初期） | MVP後に必要を感じたら追加する |
| バックテスト基盤（初期） | 過去データ取得→戦略検証はPhase 2以降でよい |
| OANDAのNYサーバー（初期実装の必須要件として） | 東京サーバーで十分。NYはインターフェースだけ残す |
| 秒間多発注（OANDA） | ブローカー規約違反リスク。そもそも狙いは数分スパン |

---

## 10. 最初に着手すべき10ファイル

実装者が最初の1週間で作るべきファイルを、**この順番通りに**作成する。

```
【Day 1-2: 疎通確認と基盤】
1. .env                         # APIキーとWebhook URLを記載。まず鍵を揃える
2. scripts/check_api.py         # bitbank APIの疎通確認スクリプト
3. scripts/notify_test.py       # Discord Webhook通知の疎通確認

【Day 3: 設定と記録基盤】
4. config.yml                   # 全設定を記述。mode: dry_run から始める
5. core/logger.py               # JSONLログ。以後の全コードがこれに依存する
6. core/notifier.py             # Discord通知。既存ロジックがあれば流用する

【Day 4-5: コアロジック】
7. core/executor_interface.py   # インターフェース定義。bitbankとcoreの境界を固める
8. core/signal.py               # Signal型定義。strategyを書く前に型を決める
9. core/guard.py                # 停止制御。損失制御は最初から入れておく

【Day 6-7: 実行層の骨格】
10. exchanges/bitbank/executor.py  # dry_runモードで動くExecutor。orderは後でいい
```

**このファイルセットが完成すれば、「dry_runで動いてDiscordに通知が飛ぶ」状態になる。**
**その状態から、order.py → fill.py → fee.py → main.pyの順で肉付けしていく。**

---

## 補足：開発フローの推奨

```
1. dry_runで完全ループ動作を確認する
2. Discordに全イベント通知が届くことを確認する
3. modeをverifyにして極小額の実注文を出してみる
4. 結果を見てstrategy.pyのパラメータを調整する（config.ymlを変えるだけ）
5. 安定したらliveモードへ切替
6. 数週間分のJSONLログを見て、guard.pyの閾値を調整する
7. 利益が安定してからPhase 2（OANDA東京）へ進む
```

**「まず動かす→結果を見る→config.ymlを調整する→また動かす」**
**このサイクルを短く回せる構造になっていることが、この設計の最大の価値です。**
