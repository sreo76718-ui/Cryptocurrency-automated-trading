@echo off
rem ============================================================
rem launch_bot_shell.bat
rem 自動売買ボット開発用 IPython 起動スクリプト
rem
rem .env の APIキーを自動ロードした状態で IPython を起動する
rem プロジェクトルートに置いて使う
rem ============================================================

title bitbank Bot Shell

echo.
echo ========================================
echo  bitbank Bot 開発シェル
echo ========================================

rem .env ファイルの存在チェック
if not exist ".env" (
    echo.
    echo [警告] .env ファイルが見つかりません。
    echo        .env.example をコピーして .env を作成してください。
    echo.
    pause
    exit /b 1
)

rem IPython の存在チェック
ipython --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo [エラー] IPython がインストールされていません。
    echo          setup_repl.bat を先に実行してください。
    echo.
    pause
    exit /b 1
)

echo.
echo  .env 読み込み済み / プロジェクトルート設定済み
echo.
echo  よく使うコマンド:
echo    %%run scripts/check_api.py     APIキー疎通確認
echo    %%run scripts/notify_test.py   Discord通知テスト
echo    %%load_ext autoreload          コード変更を自動リロード
echo    %%autoreload 2                 （autoreload有効化後）
echo.
echo ========================================
echo.

rem IPython を起動（スタートアップスクリプト付き）
ipython --no-banner --profile=bot_dev -i startup_ipython.py 2>nul || ipython --no-banner -i startup_ipython.py 2>nul || ipython --no-banner
