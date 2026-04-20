#!/usr/bin/env python3
"""
 美股資料攝取模組
 資料來源：Yahoo Finance（yfinance）
 支援：個股日K、還原股價、因子分割資料

 使用方式：
   python3 ingest_us_stocks.py --add AAPL TSLA NVDA
   python3 ingest_us_stocks.py --add SPY QQQ      # 指數ETF
   python3 ingest_us_stocks.py --update            # 更新所有已追蹤標的
"""

import os
import sys
import sqlite3
import argparse
from pathlib import Path
from datetime import datetime
import time

DB_PATH = Path(__file__).parent.parent / "data" / "stock_quant.db"

try:
    import yfinance as yf
except ImportError:
    print("❌ 需先安裝：pip3 install yfinance --break-system-packages")
    sys.exit(1)


# ── 資料表設定 ─────────────────────────────────────────

US_TABLES = {
    "us_daily_price": """
        CREATE TABLE IF NOT EXISTS us_daily_price (
            ticker      TEXT    NOT NULL,
            date        TEXT    NOT NULL,
            open        REAL,
            high        REAL,
            low         REAL,
            close       REAL,
            adj_close   REAL,
            volume      INTEGER,
            dividends   REAL    DEFAULT 0,
            stock_splits REAL   DEFAULT 0,
            PRIMARY KEY (ticker, date)
        )
    """,
    "us_stock_info": """
        CREATE TABLE IF NOT EXISTS us_stock_info (
            ticker       TEXT    PRIMARY KEY,
            name         TEXT,
            sector       TEXT,
            industry     TEXT,
            currency     TEXT,
            market_cap   REAL,
            exchange     TEXT,
            updated_at   TEXT
        )
    """,
}


def ensure_tables():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    for sql in US_TABLES.values():
        cursor.execute(sql)
    conn.commit()
    conn.close()


# ── 日K攝取 ─────────────────────────────────────────────

def fetch_us_daily(ticker: str, period: str = "2y") -> list:
    """
    用 yfinance 抓取日K資料
    yfinance 的 history() 自動處理股票分割與股息還原
    adj_close 就是還原後的價格
    """
    try:
        ticker_obj = yf.Ticker(ticker)
        data = ticker_obj.history(period=period, auto_adjust=False)
        if data.empty:
            return []
        records = []
        for dt, row in data.iterrows():
            records.append({
                "ticker":       ticker,
                "date":         dt.strftime("%Y-%m-%d"),
                "open":         float(row["Open"]),
                "high":         float(row["High"]),
                "low":          float(row["Low"]),
                "close":        float(row["Close"]),
                "adj_close":    float(row["Adj Close"]),
                "volume":       int(row["Volume"]),
                "dividends":    float(row["Dividends"]) if "Dividends" in row else 0,
                "stock_splits": float(row["Stock Splits"]) if "Stock Splits" in row else 0,
            })
        return records
    except Exception as e:
        print(f"  ⚠️ {ticker} fetch error: {e}")
        return []


def save_us_daily(records: list) -> int:
    if not records:
        return 0
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    inserted = 0
    for r in records:
        try:
            cursor.execute("""
                INSERT OR REPLACE INTO us_daily_price
                (ticker, date, open, high, low, close, adj_close, volume, dividends, stock_splits)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (r["ticker"], r["date"], r["open"], r["high"], r["low"],
                  r["close"], r["adj_close"], r["volume"], r["dividends"], r["stock_splits"]))
            inserted += 1
        except Exception:
            pass
    conn.commit()
    conn.close()
    return inserted


def save_us_info(ticker: str, info: dict):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT OR REPLACE INTO us_stock_info
            (ticker, name, sector, industry, currency, market_cap, exchange, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            ticker,
            info.get("shortName") or info.get("longName", ""),
            info.get("sector", ""),
            info.get("industry", ""),
            info.get("currency", "USD"),
            info.get("marketCap"),
            info.get("exchange", ""),
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        ))
        conn.commit()
    except Exception:
        pass
    conn.close()


def fetch_and_save(ticker: str, period: str = "2y") -> dict:
    """對單一標的執行完整攝取"""
    print(f"📡 {ticker}：抓取中...")
    records = fetch_us_daily(ticker, period)
    if not records:
        return {"ticker": ticker, "status": "no_data"}

    # 順便抓 info
    try:
        info = yf.Ticker(ticker).info
        save_us_info(ticker, info)
    except Exception:
        pass

    inserted = save_us_daily(records)
    return {"ticker": ticker, "status": "ok", "records": len(records), "inserted": inserted}


# ── 主程式 ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="美股資料攝取")
    parser.add_argument("--add", nargs="+", help="新增追蹤標的（如：AAPL TSLA NVDA）")
    parser.add_argument("--update", action="store_true", help="更新所有已追蹤標的")
    parser.add_argument("--period", type=str, default="2y",
                       choices=["1mo","3mo","6mo","1y","2y","5y","max"],
                       help="yfinance history period（預設2y）")
    args = parser.parse_args()

    ensure_tables()

    if args.add:
        tickers = args.add
    elif args.update:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT ticker FROM us_daily_price")
        tickers = [r[0] for r in cursor.fetchall()]
        conn.close()
        if not tickers:
            print("❌ 資料庫中沒有美股資料，先用 --add 新增")
            sys.exit(0)
    else:
        print("用法：--add AAPL TSLA NVDA  或  --update")
        sys.exit(0)

    print(f"📦 攝取 {len(tickers)} 檔美股...")
    total = 0
    for i, t in enumerate(tickers, 1):
        print(f"\n[{i}/{len(tickers)}] {t}...")
        result = fetch_and_save(t, args.period)
        if result["status"] == "ok":
            print(f"  ✅ {result['inserted']} 筆寫入")
            total += result["inserted"]
        else:
            print(f"  ⚠️ {result['status']}")
        time.sleep(0.3)  # 友善

    print(f"\n✅ 美股攝取完成，共寫入 {total} 筆")


if __name__ == "__main__":
    main()
