@echo off
rem ============================================================
rem setup_repl.bat
rem Python REPL 環境セットアップスクリプト（Windows用）
rem
rem 使い方: このファイルをダブルクリック or コマンドプロンプトで実行
rem ============================================================

echo.
echo ========================================
echo  Python REPL 環境セットアップ
echo ========================================
echo.

rem Pythonバージョン確認
python --version
echo.

echo [1/3] IPython をインストール中...
pip install ipython --upgrade
echo.

echo [2/3] ptpython をインストール中...
pip install ptpython --upgrade
echo.

echo [3/3] rich（カラー出力ライブラリ）をインストール中...
pip install rich --upgrade
echo.

echo ========================================
echo  セットアップ完了！
echo ========================================
echo.
echo 起動方法:
echo   IPython   : ipython
echo   ptpython  : ptpython
echo   通常Python: python
echo.
echo ボット開発用の起動は launch_bot_shell.bat を使ってください。
echo.
pause
