#!/usr/bin/env python3
"""
Stephanie 量化系統 - 資料庫初始化腳本
執行方式：python3 init_database.py
"""

import sqlite3
import os
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "stock_quant.db"

def init_database():
    """初始化 SQLite 資料庫（若已存在則跳過）"""

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # ──────────────────────────────────────────────
    # TABLE 1: 日K資料（OHLCV）
    # ──────────────────────────────────────────────
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS daily_price (
        stock_id      TEXT    NOT NULL,  -- 股票代碼（如 4967）
        date          TEXT    NOT NULL,  -- 日期（YYYY-MM-DD）
        open          REAL    NOT NULL,  -- 開盤價
        high          REAL    NOT NULL,  -- 最高價
        low           REAL    NOT NULL,  -- 最低價
        close         REAL    NOT NULL,  -- 收盤價
        volume        INTEGER NOT NULL,  -- 成交量
        PRIMARY KEY (stock_id, date)
    )
    """)

    # ──────────────────────────────────────────────
    # TABLE 2: 法人買賣
    # ──────────────────────────────────────────────
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS institutional (
        stock_id      TEXT    NOT NULL,
        date          TEXT    NOT NULL,
        foreign_buy   INTEGER DEFAULT 0,   -- 外資買超張數
        foreign_sell  INTEGER DEFAULT 0,   -- 外資賣超張數
        prop_buy      INTEGER DEFAULT 0,    -- 投信買超張數
        prop_sell     INTEGER DEFAULT 0,    -- 投信賣超張數
        dealer_buy    INTEGER DEFAULT 0,   -- 自營商買超張數
        dealer_sell   INTEGER DEFAULT 0,   -- 自營商賣超張數
        net_buy       INTEGER DEFAULT 0,   -- 合計買賣超
        PRIMARY KEY (stock_id, date)
    )
    """)

    # ──────────────────────────────────────────────
    # TABLE 3: 每月營收
    # ──────────────────────────────────────────────
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS monthly_revenue (
        stock_id      TEXT    NOT NULL,
        revenue_month TEXT    NOT NULL,   -- 營收所屬月份（YYYY-MM）
        revenue       REAL    NOT NULL,   -- 營收金額（萬元）
        yoy_change    REAL    DEFAULT NULL, -- 年增率（%）
        mom_change    REAL    DEFAULT NULL, -- 月增率（%）
        PRIMARY KEY (stock_id, revenue_month)
    )
    """)

    # ──────────────────────────────────────────────
    # TABLE 4: 季財報
    # ──────────────────────────────────────────────
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS financials (
        stock_id         TEXT    NOT NULL,
        quarter          TEXT    NOT NULL,   -- 財報季度（YYYYQN，如 2025Q1）
        eps              REAL    NOT NULL,   -- 每股盈餘
        revenue          REAL    DEFAULT NULL,  -- 營收（千元）
        gross_profit     REAL    DEFAULT NULL,  -- 毛利
        gross_margin     REAL    DEFAULT NULL,  -- 毛利率（%）
        operating_income REAL    DEFAULT NULL,  -- 營業利益
        operating_margin REAL    DEFAULT NULL,  -- 營益率（%）
        net_income       REAL    DEFAULT NULL,  -- 淨利
        net_margin       REAL    DEFAULT NULL,  -- 淨利率（%）
        roe              REAL    DEFAULT NULL,  -- 股東權益報酬率（%）
        roa              REAL    DEFAULT NULL,  -- 資產報酬率（%）
        debt_ratio       REAL    DEFAULT NULL,  -- 負債比（%）
        PRIMARY KEY (stock_id, quarter)
    )
    """)

    # ──────────────────────────────────────────────
    # TABLE 5: 個股基本資料（快取）
    # ──────────────────────────────────────────────
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS stock_info (
        stock_id     TEXT    PRIMARY KEY,
        name         TEXT    NOT NULL,    -- 股票名稱
        industry     TEXT    DEFAULT NULL,  -- 產業類別
        listed_date  TEXT    DEFAULT NULL,  -- 上市日期
        capital      REAL    DEFAULT NULL,  -- 實收資本額（億元）
        shares        INTEGER DEFAULT NULL,  -- 流通在外股數（千股）
        par_value     REAL    DEFAULT 10,  -- 面值（通常10元）
        updated_at   TEXT    NOT NULL     -- 最後更新時間
    )
    """)

    # ──────────────────────────────────────────────
    # TABLE 6: 交易訊號記錄
    # ──────────────────────────────────────────────
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS trade_signals (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        stock_id         TEXT    NOT NULL,
        signal_date      TEXT    NOT NULL,   -- 訊號產生日期
        signal_type      TEXT    NOT NULL,   -- 訊號類型（KD_GOLD_CROSS / MACD_BULL 等）
        signal_source    TEXT    NOT NULL,   -- 訊號來源（SCANNER / MANUAL）
        market           TEXT    DEFAULT 'TW', -- 市場（TW / US / CRYPTO）
        price_at_signal  REAL    NOT NULL,   -- 訊號產生時的價格
        indicators_json  TEXT    DEFAULT NULL, -- 當下技術指標數值（JSON格式儲存）
        expected_direction TEXT  NOT NULL,   -- 預期方向（LONG / SHORT）
        notes            TEXT    DEFAULT NULL,
        created_at       TEXT    NOT NULL DEFAULT (datetime('now'))
    )
    """)

    # ──────────────────────────────────────────────
    # TABLE 7: 交易紀錄（實際成交）
    # ──────────────────────────────────────────────
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS trades (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        stock_id         TEXT    NOT NULL,
        entry_date       TEXT    NOT NULL,   -- 進場日期
        entry_price      REAL    NOT NULL,   -- 進場價格
        exit_date        TEXT    DEFAULT NULL, -- 出場日期（NULL=尚未出場）
        exit_price       REAL    DEFAULT NULL, -- 出場價格
        shares           INTEGER NOT NULL,   -- 股數
        position_type    TEXT    NOT NULL,   -- 短線 / 波段 / 中線
        signal_id        INTEGER DEFAULT NULL, -- 關聯訊號ID
        realized_pnl     REAL    DEFAULT NULL, -- 已實現損益
        realized_pnl_pct REAL   DEFAULT NULL, -- 已實現報酬率%
        status           TEXT    DEFAULT 'OPEN', -- OPEN / CLOSED / STOPPED
        notes            TEXT    DEFAULT NULL,
        created_at       TEXT    NOT NULL DEFAULT (datetime('now'))
    )
    """)

    # ──────────────────────────────────────────────
    # TABLE 8: 警示日誌
    # ──────────────────────────────────────────────
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS alerts (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        stock_id    TEXT    NOT NULL,
        alert_time  TEXT    NOT NULL,
        alert_type  TEXT    NOT NULL,   -- 進場 / 停損 / 停利 / 法人 / 消息
        message     TEXT    NOT NULL,
        triggered   INTEGER DEFAULT 1,   -- 1=已觸發 0=已忽略
        sent        INTEGER DEFAULT 0,   -- 1=已發送通知 0=尚未發送
        created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
    )
    """)

    # ──────────────────────────────────────────────
    # TABLE 9: 融資融券（信用交易）
    # ──────────────────────────────────────────────
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS margin_short (
        stock_id          TEXT    NOT NULL,  -- 股票代碼
        date              TEXT    NOT NULL,  -- 日期（YYYY-MM-DD）
        margin_buy        INTEGER DEFAULT 0,  -- 融資買進（張）
        margin_buy_amount REAL    DEFAULT 0,  -- 融資買進金額（元）
        margin_sell       INTEGER DEFAULT 0,  -- 融資賣出（張）
        margin_balance    INTEGER DEFAULT 0,  -- 融资余额（張）
        short_sell        INTEGER DEFAULT 0,  -- 融券賣出（張）
        short_cover       INTEGER DEFAULT 0,  -- 融券買進（張）
        short_balance     INTEGER DEFAULT 0,  -- 融券餘額（張）
        margin_call       REAL    DEFAULT 0,  -- 融資維持率（%）
        short_call        REAL    DEFAULT 0,  -- 融券維持率（%）
        lend_balance      INTEGER DEFAULT 0,  -- 借券餘額（張）
        updated_at        TEXT    NOT NULL DEFAULT (datetime('now')),
        PRIMARY KEY (stock_id, date)
    )
    """)

    # ──────────────────────────────────────────────
    # TABLE 9: 宏觀經濟數據
    # ──────────────────────────────────────────────
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS macro_data (
        indicator_code TEXT    NOT NULL,   -- 指標代碼（如 TAIEX / VIX / TEDRATE）
        date           TEXT    NOT NULL,
        value          REAL    NOT NULL,
        unit           TEXT    DEFAULT NULL,  -- 數值單位
        source         TEXT    DEFAULT NULL,
        PRIMARY KEY (indicator_code, date)
    )
    """)

    # ──────────────────────────────────────────────
    # TABLE 10: 系統日誌
    # ──────────────────────────────────────────────
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS system_log (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        log_time    TEXT    NOT NULL DEFAULT (datetime('now')),
        module      TEXT    NOT NULL,   -- 資料攝取 / 策略 / 風控 / 警示
        level       TEXT    NOT NULL,   -- INFO / WARNING / ERROR
        message     TEXT    NOT NULL,
        details     TEXT    DEFAULT NULL
    )
    """)

    # ──────────────────────────────────────────────
    # INDEX 加速查詢
    # ──────────────────────────────────────────────
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_daily_date ON daily_price(date)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_institutional_date ON institutional(date)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_financials_quarter ON financials(quarter)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_stock ON trades(stock_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_alerts_stock ON alerts(stock_id)")

    conn.commit()
    conn.close()

    print(f"✅ 資料庫初始化完成：{DB_PATH}")
    print("已建立以下資料表：")
    tables = [
        "daily_price        — 日K資料（OHLCV）",
        "institutional      — 三大法人買賣",
        "monthly_revenue    — 月營收",
        "financials         — 季財報",
        "stock_info         — 個股基本資料",
        "trade_signals      — 交易訊號記錄",
        "trades             — 實際交易紀錄",
        "alerts             — 警示日誌",
        "margin_short       — 融資融券（信用交易）",
        "macro_data         — 宏觀經濟數據",
        "system_log         — 系統日誌",
    ]
    for t in tables:
        print(f"  ├── {t}")

if __name__ == "__main__":
    init_database()
