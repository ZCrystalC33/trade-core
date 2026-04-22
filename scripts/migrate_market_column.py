#!/usr/bin/env python3
"""Migration: Add market column to trade_signals"""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "stock_quant.db"

def migrate():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    # Check if column exists
    cur.execute("PRAGMA table_info(trade_signals)")
    cols = [r[1] for r in cur.fetchall()]
    
    if "market" not in cols:
        cur.execute("ALTER TABLE trade_signals ADD COLUMN market TEXT DEFAULT 'TW'")
        print("✅ Added 'market' column to trade_signals")
    else:
        print("ℹ️  'market' column already exists")
    
    conn.commit()
    conn.close()

if __name__ == "__main__":
    migrate()