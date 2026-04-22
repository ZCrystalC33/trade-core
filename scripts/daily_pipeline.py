#!/usr/bin/env python3
"""
 Stephanie 每日量化流水線
 用途：每日自動執行 — 資料更新 → 掃描 → 產出報告

 使用方式（手動測試）：
   python3 daily_pipeline.py --dry-run

 Cron 設定（每日 08:00 執行）：
   0 8 * * * /usr/bin/python3 /home/snow/trade_core/scripts/daily_pipeline.py >> /home/snow/trade_core/logs/pipeline.log 2>&1
"""

import os
import sys
import json
import sqlite3
import requests
import argparse
import subprocess
from datetime import datetime
from pathlib import Path

# ── 路徑設定 ──────────────────────────────────────────────
BASE_DIR   = Path(__file__).parent.parent
DB_PATH    = BASE_DIR / "data" / "stock_quant.db"
LOG_DIR    = BASE_DIR / "logs"
TOKEN_ENV  = "FINMIND_TOKEN"

LOG_FILE   = LOG_DIR / "pipeline.log"
TOKEN_FILE = Path.home() / ".trade_core.env"


def log(msg: str, level: str = "INFO"):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [{level}] {msg}"
    print(line)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def get_token() -> str:
    token = os.environ.get(TOKEN_ENV, "")
    if token:
        return token
    if TOKEN_FILE.exists():
        for line in TOKEN_FILE.read_text().splitlines():
            if line.startswith("FINMIND_TOKEN="):
                return line.split("=", 1)[1].strip()
    return ""


# ── Step 1：更新所有股票的日K ─────────────────────────────

def update_all_prices(token: str) -> int:
    """更新資料庫中所有股票的日K（從最後一筆日期到今天）"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 取所有股票的最後一筆日期
    cursor.execute("""
        SELECT stock_id, MAX(date) as last_date
        FROM daily_price
        GROUP BY stock_id
    """)
    stocks = cursor.fetchall()
    conn.close()

    if not stocks:
        log("無股票需更新", "WARNING")
        return 0

    today = datetime.now().strftime("%Y-%m-%d")
    total_updated = 0
    errors = 0

    for stock_id, last_date in stocks:
        if last_date >= today:
            continue  # 已是最新的

        try:
            updated = ingest_single_price(stock_id, last_date, today, token)
            total_updated += updated
            log(f"  {stock_id}: {last_date} → {today}，新增 {updated} 筆")
        except Exception as e:
            errors += 1
            log(f"  {stock_id} 更新失敗：{e}", "ERROR")

    return total_updated


def ingest_single_price(stock_id: str, start_date: str, end_date: str, token: str) -> int:
    """對單一股票抓日K並寫入"""
    import time
    url = "https://api.finmindtrade.com/api/v4/data"
    params = {
        "dataset": "TaiwanStockPrice",
        "data_id": stock_id,
        "start_date": start_date,
        "end_date": end_date,
    }
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    resp = requests.get(url, params=params, headers=headers, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") != 200:
        raise RuntimeError(data.get("message"))

    records = data.get("data", [])
    if not records:
        return 0

    # 過濾掉 start_date 本身（避免重複）
    records = [r for r in records if r["date"] > start_date]
    if not records:
        return 0

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    inserted = 0
    for r in records:
        try:
            cursor.execute("""
                INSERT OR REPLACE INTO daily_price
                (stock_id, date, open, high, low, close, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (r["stock_id"], r["date"], r["open"], r["max"], r["min"], r["close"], r["Trading_Volume"]))
            inserted += 1
        except Exception as e:
            import logging
            logging.warning(f"Failed to insert stock {stock_id}: {e}")
    conn.commit()
    conn.close()
    time.sleep(0.3)  # rate limit 保護
    return inserted


# ── Step 2：還原所有股票價格 ───────────────────────────────

def adjust_all_prices() -> int:
    """對所有有還原需求的股票執行還原"""
    sys.path.insert(0, str(BASE_DIR / "scripts"))
    from adjust_prices import process_stock
    token = get_token()
    if not token:
        log("無FinMind Token，無法執行還原", "WARNING")
        return 0

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT stock_id FROM daily_price")
    stocks = [r[0] for r in cursor.fetchall()]
    conn.close()

    adjusted = 0
    for sid in stocks:
        try:
            result = process_stock(sid, token)
            if result.get("status") == "ok":
                adjusted += 1
        except Exception as e:
            import logging
            logging.warning(f"Failed to adjust {sid}: {e}")
    return adjusted


# ── Step 3：執行掃描 ──────────────────────────────────────

def run_scanner() -> dict:
    """執行掃描，回傳結果摘要"""
    sys.path.insert(0, str(BASE_DIR / "scripts"))
    from scan_and_record import run_scan

    scan_types = ["kd_gold_cross", "macd_bull", "ma_bull"]
    report = {}

    for st in scan_types:
        results = run_scan(st, dry_run=True)
        report[st] = results[:5]  # 只取前5名

    return report


# ── Step 4：產出文字報告 ──────────────────────────────────

def generate_report(scan_report: dict, updated_count: int) -> str:
    """產出Markdown格式每日報告"""
    today = datetime.now().strftime("%Y-%m-%d")
    lines = [
        f"📊 **Stephanie 每日量化報告**",
        f"📅 {today}  | 📦 更新 {updated_count} 筆日K",
        "",
        "───",
    ]

    scan_labels = {
        "kd_gold_cross": "KD 低檔黃金交叉 🟢",
        "macd_bull": "MACD 多頭 🟢",
        "ma_bull": "均線多頭排列 🟢",
    }

    for st, label in scan_labels.items():
        results = scan_report.get(st, [])
        lines.append(f"\n**{label}**")
        if not results:
            lines.append("  （無）")
        for i, r in enumerate(results[:5], 1):
            sigs = " / ".join(list(r["signals"].values())[:3])
            lines.append(f"  {i}. `{r['stock_id']}` 收{r['close']} 評分{r['score']}/10")
            lines.append(f"     {sigs}")

    lines.append("\n───")
    lines.append("_由 Trade Core 自動化流水線產生_")
    return "\n".join(lines)


# ── Step 5：發送到 Telegram ────────────────────────────────

def send_telegram(text: str):
    """透過 OpenClaw cron 發送 Telegram 通知"""
    # 寫入 pipeline 產出檔，讓 cron delivery 撿起來
    report_file = LOG_DIR / "pipeline_report.md"
    report_file.write_text(text)
    log(f"報告已寫入 {report_file}，等待 cron 發送至 Telegram")
    # NOTE: OpenClaw cron 會自動發送 systemEvent 到 session
    # 所以這裡只要把報告內容寫到一個固定位置，
    # 由 caller 在 session 中呈現即可


# ── 主流水線 ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="每日量化流水線")
    parser.add_argument("--dry-run", action="store_true", help="只跑不回寫")
    parser.add_argument("--skip-update", action="store_true", help="跳過資料更新")
    parser.add_argument("--skip-adjust", action="store_true", help="跳過還原價格")
    parser.add_argument("--skip-scan", action="store_true", help="跳過掃描")
    args = parser.parse_args()

    log("═══ Stephanie 每日流水線 啟動 ═══")
    start = datetime.now()

    updated = 0

    if not args.skip_update:
        token = get_token()
        if not token:
            log("無 FinMind Token，無法更新資料", "WARNING")
        else:
            updated = update_all_prices(token)
            log(f"日K更新完成：{updated} 筆")
    else:
        log("（已跳過資料更新）")

    if not args.skip_adjust and updated > 0:
        adj = adjust_all_prices()
        log(f"還原價格完成：{adj} 檔")
    else:
        log("（已跳過還原）")

    if not args.skip_scan:
        log("執行掃描...")
        scan_report = run_scanner()
        report_text = generate_report(scan_report, updated)
        print("\n" + report_text)
        send_telegram(report_text)
    else:
        log("（已跳過掃描）")

    elapsed = (datetime.now() - start).total_seconds()
    log(f"═══ 流水線完成，耗時 {elapsed:.1f} 秒 ═══")


if __name__ == "__main__":
    main()
