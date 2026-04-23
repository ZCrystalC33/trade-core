#!/usr/bin/env python3
"""
init_database.py — 資料庫 Schema 管理

每次變更請同時更新 SCHEMA_VERSION。
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "stock_quant.db"
SCHEMA_VERSION = "3"


def init_database():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # ── TABLE 1: 日K（OHLCV）────────────────────────────────
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS daily_price (
        stock_id      TEXT    NOT NULL,
        date          TEXT    NOT NULL,
        open          REAL    NOT NULL,
        high          REAL    NOT NULL,
        low           REAL    NOT NULL,
        close         REAL    NOT NULL,
        volume        INTEGER NOT NULL,
        market        TEXT    DEFAULT 'TW',
        PRIMARY KEY (stock_id, date)
    )
    """)

    # ── TABLE 2: 法人買賣 ──────────────────────────────────
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS institutional (
        stock_id      TEXT    NOT NULL,
        date          TEXT    NOT NULL,
        foreign_buy   INTEGER DEFAULT 0,
        foreign_sell  INTEGER DEFAULT 0,
        prop_buy      INTEGER DEFAULT 0,
        prop_sell     INTEGER DEFAULT 0,
        dealer_buy    INTEGER DEFAULT 0,
        dealer_sell   INTEGER DEFAULT 0,
        net_buy       INTEGER DEFAULT 0,
        PRIMARY KEY (stock_id, date)
    )
    """)

    # ── TABLE 3: 月營收 ─────────────────────────────────────
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS monthly_revenue (
        stock_id      TEXT    NOT NULL,
        revenue_month TEXT    NOT NULL,
        revenue       REAL    NOT NULL,
        yoy_change    REAL    DEFAULT NULL,
        mom_change    REAL    DEFAULT NULL,
        PRIMARY KEY (stock_id, revenue_month)
    )
    """)

    # ── TABLE 4: 季財報 ─────────────────────────────────────
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS financials (
        stock_id         TEXT    NOT NULL,
        quarter          TEXT    NOT NULL,
        eps              REAL    NOT NULL,
        revenue          REAL    DEFAULT NULL,
        gross_profit     REAL    DEFAULT NULL,
        gross_margin     REAL    DEFAULT NULL,
        operating_income REAL    DEFAULT NULL,
        operating_margin REAL    DEFAULT NULL,
        net_income       REAL    DEFAULT NULL,
        net_margin       REAL    DEFAULT NULL,
        roe              REAL    DEFAULT NULL,
        roa              REAL    DEFAULT NULL,
        debt_ratio       REAL    DEFAULT NULL,
        PRIMARY KEY (stock_id, quarter)
    )
    """)

    # ── TABLE 5: 個股基本資料 ────────────────────────────────
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS stock_info (
        stock_id     TEXT    PRIMARY KEY,
        name         TEXT    NOT NULL,
        industry     TEXT    DEFAULT NULL,
        listed_date  TEXT    DEFAULT NULL,
        capital      REAL    DEFAULT NULL,
        shares       INTEGER DEFAULT NULL,
        par_value    REAL    DEFAULT 10,
        market       TEXT    DEFAULT 'TW',
        updated_at   TEXT    NOT NULL
    )
    """)

    # ── TABLE 6: 交易訊號記錄 ───────────────────────────────
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS trade_signals (
        id                INTEGER PRIMARY KEY AUTOINCREMENT,
        stock_id          TEXT    NOT NULL,
        signal_date       TEXT    NOT NULL,
        signal_type       TEXT    NOT NULL,
        signal_source     TEXT    NOT NULL,
        market            TEXT    DEFAULT 'TW',
        price_at_signal   REAL    NOT NULL,
        indicators_json   TEXT    DEFAULT NULL,
        expected_direction TEXT  NOT NULL,
        notes             TEXT    DEFAULT NULL,
        created_at        TEXT    NOT NULL DEFAULT (datetime('now'))
    )
    """)

    # ── TABLE 7: 實際交易紀錄 ────────────────────────────────
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS trades (
        id                INTEGER PRIMARY KEY AUTOINCREMENT,
        stock_id          TEXT    NOT NULL,
        entry_date        TEXT    NOT NULL,
        entry_price       REAL    NOT NULL,
        exit_date         TEXT    DEFAULT NULL,
        exit_price        REAL    DEFAULT NULL,
        shares            INTEGER NOT NULL,
        position_type     TEXT    NOT NULL,
        signal_id         INTEGER DEFAULT NULL,
        realized_pnl      REAL    DEFAULT NULL,
        realized_pnl_pct  REAL    DEFAULT NULL,
        status            TEXT    DEFAULT 'OPEN',
        notes             TEXT    DEFAULT NULL,
        created_at        TEXT    NOT NULL DEFAULT (datetime('now'))
    )
    """)

    # ── TABLE 8: 警示日誌 ──────────────────────────────────
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS alerts (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        stock_id    TEXT    NOT NULL,
        alert_time  TEXT    NOT NULL,
        alert_type  TEXT    NOT NULL,
        message     TEXT    NOT NULL,
        triggered   INTEGER DEFAULT 1,
        sent        INTEGER DEFAULT 0,
        created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
    )
    """)

    # ── TABLE 9: 宏觀經濟數據 ────────────────────────────────
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS macro_data (
        indicator_code TEXT    NOT NULL,
        date           TEXT    NOT NULL,
        value          REAL    NOT NULL,
        unit           TEXT    DEFAULT NULL,
        source         TEXT    DEFAULT NULL,
        PRIMARY KEY (indicator_code, date)
    )
    """)

    # ── TABLE 10: 系統日誌 ──────────────────────────────────
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS system_log (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        log_time    TEXT    NOT NULL DEFAULT (datetime('now')),
        module      TEXT    NOT NULL,
        level       TEXT    NOT NULL,
        message     TEXT    NOT NULL,
        details     TEXT    DEFAULT NULL
    )
    """)

    # ── TABLE 11: 願望清單（白名單）──────────────────────────
    # ★ 新增：Scanner 只掃這張表的股票，杜絕全資料庫掃描
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS watchlist (
        stock_id     TEXT    PRIMARY KEY,
        name         TEXT    DEFAULT NULL,
        market       TEXT    DEFAULT 'TW',
        industry     TEXT    DEFAULT NULL,
        added_at     TEXT    NOT NULL DEFAULT (datetime('now')),
        notes        TEXT    DEFAULT NULL,
        active       INTEGER DEFAULT 1
    )
    """)

    # ── TABLE 12: 指標快取 ──────────────────────────────────
    # ★ 新增：每日只計算一次指標，之後直接讀快取
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS indicator_cache (
        stock_id          TEXT    NOT NULL,
        cached_at         TEXT    NOT NULL,
        close_at_cache    REAL    NOT NULL,
        indicators_json   TEXT    NOT NULL,
        score             REAL    DEFAULT NULL,
        score_label       TEXT    DEFAULT NULL,
        PRIMARY KEY (stock_id)
    )
    """)

    # ── INDEX ───────────────────────────────────────────────
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_daily_date ON daily_price(date)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_daily_market ON daily_price(market)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_institutional_date ON institutional(date)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_financials_quarter ON financials(quarter)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_stock ON trades(stock_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_alerts_stock ON alerts(stock_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_watchlist_market ON watchlist(market)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_indicator_cache_date ON indicator_cache(cached_at)")

    # ── 寫入 SCHEMA 版本 ────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)
    """)
    cursor.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', ?)",
                   (SCHEMA_VERSION,))

    conn.commit()
    conn.close()

    print(f"✅ 資料庫初始化完成 v{SCHEMA_VERSION}：{DB_PATH}")


if __name__ == "__main__":
    init_database()
