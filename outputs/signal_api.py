"""
Signal Output API — 輸出訊號給交易系統

提供 REST API 端點：
- GET  /signals         — 取得所有活跃訊號
- POST /signals         — 創建新訊號
- GET  /signals/<id>    — 取得特定訊號
- POST /signals/<id>/execute — 標記為已執行
- POST /signals/<id>/close  — 標記為已結束（回傳 Feedback）
"""

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

# Resolve DB path relative to this file
DB_PATH = Path(__file__).parent.parent / "data" / "stock_quant.db"


class SignalStore:
    """Signal 持久化儲存"""
    
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._ensure_table()
    
    def _ensure_table(self):
        """確保 trade_signals 表存在並包含 market 欄位"""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        
        # Check columns
        cur.execute("PRAGMA table_info(trade_signals)")
        cols = [r[1] for r in cur.fetchall()]
        
        # Add market column if missing
        if "market" not in cols:
            cur.execute("ALTER TABLE trade_signals ADD COLUMN market TEXT DEFAULT 'TW'")
        
        conn.commit()
        conn.close()
    
    def save(self, signal: dict) -> int:
        """儲存 Signal，返回 signal_id"""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        
        cur.execute("""
            INSERT INTO trade_signals
            (stock_id, signal_date, signal_type, signal_source, price_at_signal,
             indicators_json, expected_direction, market, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            signal["symbol"],
            signal.get("signal_date", datetime.now().strftime("%Y-%m-%d")),
            signal.get("signal_type", "BUY"),
            signal.get("signal_source", "API"),
            signal.get("price_at_signal", 0),
            json.dumps(signal.get("indicators", {})),
            signal.get("action", "LONG"),
            signal.get("market", "TW"),
            signal.get("notes", "")
        ))
        
        signal_id = cur.lastrowid
        conn.commit()
        conn.close()
        return signal_id
    
    def get_active(self, limit: int = 50) -> List[dict]:
        """取得活躍訊號"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        cur.execute("""
            SELECT * FROM trade_signals
            WHERE id NOT IN (
                SELECT signal_id FROM trades WHERE signal_id IS NOT NULL AND status = 'CLOSED'
            )
            ORDER BY id DESC
            LIMIT ?
        """, (limit,))
        
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows
    
    def mark_executed(self, signal_id: int, trade_id: int):
        """標記為已執行"""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("""
            UPDATE trade_signals
            SET notes = notes || ' | EXECUTED: trade_id=' || ?
            WHERE id = ?
        """, (str(trade_id), signal_id))
        conn.commit()
        conn.close()
    
    def to_signal_dict(self, row: dict) -> dict:
        """將 DB row 轉為 Signal API 格式"""
        indicators = json.loads(row.get("indicators_json", "{}"))
        return {
            "signal_id": row["id"],
            "symbol": row["stock_id"],
            "market": row.get("market", "TW"),
            "action": row["expected_direction"],
            "score": 75.0,  # 預設評分
            "confidence": 0.8,
            "indicators": indicators,
            "generated_at": row["created_at"],
            "source": row["signal_source"]
        }


class SignalAPI:
    """Signal API Server"""
    
    def __init__(self, store: SignalStore = None):
        self.store = store or SignalStore()
        self.routes = {
            "GET": {
                "/signals": self._get_signals,
                "/signals/active": self._get_active_signals
            },
            "POST": {
                "/signals": self._create_signal,
                "/signals/execute": self._execute_signal,
                "/signals/close": self._close_signal
            }
        }
    
    def handle(self, method: str, path: str, body: dict = None) -> dict:
        """處理請求"""
        route_key = f"{method.upper()}"
        
        # Exact match
        if path in self.routes.get(method.upper(), {}):
            return self.routes[method.upper()][path](body or {})
        
        # Pattern match
        for pattern, handler in self.routes.get(method.upper(), {}).items():
            if pattern in path:
                return handler(body or {}, signal_id=self._extract_id(path))
        
        return {"error": "Not found", "status": 404}
    
    def _extract_id(self, path: str) -> Optional[int]:
        parts = path.split("/")
        for i, p in enumerate(parts):
            if p == "signals" and i + 1 < len(parts):
                try:
                    return int(parts[i + 1])
                except ValueError:
                    pass
        return None
    
    def _get_signals(self, params: dict) -> dict:
        signals = self.store.get_active()
        return {
            "signals": [self.store.to_signal_dict(s) for s in signals],
            "count": len(signals)
        }
    
    def _get_active_signals(self, params: dict) -> dict:
        signals = self.store.get_active(limit=30)
        return {
            "signals": [self.store.to_signal_dict(s) for s in signals],
            "count": len(signals),
            "timestamp": datetime.now().isoformat()
        }
    
    def _create_signal(self, data: dict) -> dict:
        if not data.get("symbol"):
            return {"error": "symbol required", "status": 400}
        
        signal_id = self.store.save(data)
        return {"signal_id": signal_id, "status": "created"}
    
    def _execute_signal(self, data: dict, signal_id: int = None) -> dict:
        if not signal_id:
            return {"error": "signal_id required", "status": 400}
        
        trade_id = data.get("trade_id")
        if trade_id:
            self.store.mark_executed(signal_id, trade_id)
        
        return {"signal_id": signal_id, "status": "executed", "trade_id": trade_id}
    
    def _close_signal(self, data: dict, signal_id: int = None) -> dict:
        if not signal_id:
            return {"error": "signal_id required", "status": 400}
        
        # TODO: Write to feedback table
        return {"signal_id": signal_id, "status": "closed", "feedback": data}


# Standalone HTTP server
def run_server(port: int = 18792):
    """啟動 Signal API Server"""
    from http.server import HTTPServer, BaseHTTPRequestHandler
    import urllib.parse
    
    store = SignalStore()
    api = SignalAPI(store)
    
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            result = api.handle("GET", parsed.path)
            self._send_json(result)
        
        def do_POST(self):
            parsed = urllib.parse.urlparse(self.path)
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.read(length)) if length > 0 else {}
            result = api.handle("POST", parsed.path, body)
            self._send_json(result)
        
        def _send_json(self, data):
            self.send_response(data.get("status", 200))
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(data, default=str).encode())
        
        def log_message(self, fmt, *args):
            print(f"[SignalAPI] {args[0]}")
    
    server = HTTPServer(("0.0.0.0", port), Handler)
    print(f"✅ Signal API running on http://0.0.0.0:{port}")
    server.serve_forever()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Trade Core Signal API")
    parser.add_argument("--port", type=int, default=18792)
    args = parser.parse_args()
    run_server(args.port)
