#!/usr/bin/env bash
# cron_wrapper.sh — daily_pipeline.py 的 cron 包裝腳本
# 由 setup_cron.py 管理，請勿直接編輯
# 用法：/home/snow/trade-core/scripts/cron_wrapper.sh

set -euo pipefail

# ── 環境設定 ────────────────────────────────────────────
export TZ="Asia/Taipei"
export PYTHONPATH="/home/snow/trade-core/scripts"

# FINMIND_TOKEN 從環境繼承（如 cron 環境變數有設的話）
# 若無，wrapper 本身不改，直接 passthrough

# ── Log 目錄確認 ─────────────────────────────────────────
LOG_DIR="/home/snow/trade-core/logs"
mkdir -p "$LOG_DIR"

# ── 執行 ─────────────────────────────────────────────────
exec /usr/bin/python3 /home/snow/trade-core/scripts/daily_pipeline.py \
    >> /home/snow/trade-core/logs/cron_daily.log 2>&1