#!/usr/bin/env bash
# cron_wrapper.sh — daily_pipeline.py 的 cron 包裝腳本
# 由 setup_cron.py 管理，請勿直接編輯
# 用法：/home/snow/trade-core/scripts/cron_wrapper.sh

set -euo pipefail

# ── 環境設定 ────────────────────────────────────────────
export TZ="Asia/Taipei"
export PYTHONPATH="/home/snow/trade-core/scripts"

# ── FinMind Token（從 ~/.trade_core.env 載入）──
if [ -f "$HOME/.trade_core.env" ]; then
    set -a
    source "$HOME/.trade_core.env"
    set +a
fi

# ── Log 目錄確認 ─────────────────────────────────────────
LOG_DIR="/home/snow/trade-core/logs"
mkdir -p "$LOG_DIR"

# ── 執行 ─────────────────────────────────────────────────
exec /usr/bin/python3 /home/snow/trade-core/scripts/daily_pipeline.py \
    >> /home/snow/trade-core/logs/cron_daily.log 2>&1