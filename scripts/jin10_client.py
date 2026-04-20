#!/usr/bin/env python3
"""
 Jin10 MCP 客戶端（urllib3 + SSE + Mcp-Session-Id 版）

 使用方式：
   from jin10_client import get_quote, get_macro_sentiment, check_macro_alerts

 原理：
   Jin10 MCP 使用 JSON-RPC 2.0 + SSE streaming
   流程：initialize → 取得 Mcp-Session-Id → 後續請求都要帶上此 header
   需要 Connection: keep-alive 保持同一 TCP session

 錯誤處理：
   所有 API 錯誤都轉為 RuntimeError，不讓系統靜默失敗
   網路/Token/解析失敗 get_macro_sentiment 返回中性 50
"""

import logging
import json
import threading
from typing import Optional, List, Dict, Any

import urllib3

# ── 配置 ──────────────────────────────────────────────────
ENDPOINT = "https://mcp.jin10.com/mcp"
TOKEN = "sk-bGGeFjnImN0jloqCYaZacEyR1XRmQaYkPhm7txTNtNs"
REQUEST_TIMEOUT = urllib3.Timeout(connect=10, read=20)

logger = logging.getLogger(__name__)

# ── MCP Session ───────────────────────────────────────────

class Jin10Session:
    """
    Jin10 MCP session manager
    流程：initialize → 取得 Mcp-Session-Id → 帶 header 發送 tools/call
    連接池大小 1，確保所有請求復用同一 TCP 連接
    """

    def __init__(self, token: str, endpoint: str = ENDPOINT):
        self.token = token
        self.endpoint = endpoint
        self._http = urllib3.PoolManager(num_pools=1, maxsize=1)
        self._session_id: Optional[str] = None
        self._lock = threading.Lock()
        self._init()

    def _init(self):
        """發送 initialize，保存 Mcp-Session-Id"""
        body = json.dumps({
            "jsonrpc": "2.0",
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"roots": {}, "sampling": {}},
                "clientInfo": {"name": "trade-core", "version": "1.0.0"},
            },
            "id": 1,
        }).encode("utf-8")

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json, text/event-stream",
            "Content-Length": str(len(body)),
        }

        r = self._http.request(
            "POST",
            self.endpoint,
            body=body,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )

        self._session_id = r.headers.get("Mcp-Session-Id")
        if not self._session_id:
            raise RuntimeError("initialize: no Mcp-Session-Id in response")

        # SSE uses LF line endings
        raw = r.data.decode("utf-8")
        for line in raw.split("\n"):
            line = line.strip("\r")  # strip any trailing CR
            if line.startswith("data: "):
                data = json.loads(line[6:])
                if "error" in data:
                    raise RuntimeError(f"initialize error: {data['error']}")
                if "result" in data:
                    self._server_info = data["result"]
                    return
        raise RuntimeError("initialize: no result in SSE response")

    def _headers(self) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json, text/event-stream",
            "Content-Length": None,  # will be filled per-request
            "Mcp-Session-Id": self._session_id,
        }

    def call(self, tool_name: str, arguments: dict) -> Any:
        """
        發送 tools/call（需带 Mcp-Session-Id）
        返回 parsed result
        """
        with self._lock:
            body = json.dumps({
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": arguments},
                "id": 1,
            }).encode("utf-8")

            hdrs = dict(self._headers())
            hdrs["Content-Length"] = str(len(body))

            r = self._http.request(
                "POST",
                self.endpoint,
                body=body,
                headers=hdrs,
                timeout=REQUEST_TIMEOUT,
            )

            raw = r.data.decode("utf-8")
            for line in raw.split("\n"):
                line = line.strip("\r")
                if line.startswith("data: "):
                    data = json.loads(line[6:])
                    if "error" in data:
                        raise RuntimeError(f"tools/call error: {data['error']}")
                    if "result" in data:
                        return data["result"]
            raise RuntimeError("tools/call: no result in SSE response")


# ── Global session (lazy, thread-safe) ─────────────────────

_session: Optional[Jin10Session] = None
_session_lock = threading.Lock()


def _get_session() -> Jin10Session:
    global _session
    if _session is None:
        with _session_lock:
            if _session is None:
                _session = Jin10Session(TOKEN)
    return _session


# ── Internal call wrapper ──────────────────────────────────

def _call(tool: str, args: dict) -> Any:
    """
    執行 MCP tool call
    返回 structuredContent（已解析的 dict）
    所有錯誤拋 RuntimeError
    """
    result = _get_session().call(tool, args)
    if isinstance(result, dict):
        # Prefer structuredContent (pre-parsed)
        sc = result.get("structuredContent")
        if sc is not None:
            return sc
        # Fall back to content[0].text (JSON string)
        content = result.get("content", [])
        if isinstance(content, list) and content:
            first = content[0]
            if isinstance(first, dict):
                text = first.get("text", first)
                try:
                    return json.loads(text)
                except (json.JSONDecodeError, TypeError):
                    return text
            return first
    elif isinstance(result, list):
        return result
    return result


# ── Public API ───────────────────────────────────────────

def get_quote(code: str) -> dict:
    """
    取得指定品種即時報價
    code: XAUUSD / USOIL / USDJPY / EURUSD / USDCNH 等
    返回: dict，含 close / ups_percent / volume 等
    """
    raw = _call("get_quote", {"code": code})
    if isinstance(raw, dict):
        return raw.get("data", raw)
    return raw if isinstance(raw, dict) else {}


def get_kline(code: str, count: int = 100,
              time: Optional[int] = None) -> List[dict]:
    """取得 K 線數據（分鐘 K）"""
    params = {"code": code, "count": count}
    if time:
        params["time"] = time
    result = _call("get_kline", params)
    return result.get("klines", []) if isinstance(result, dict) else []


def get_flash(keyword: Optional[str] = None, limit: int = 15) -> List[dict]:
    """
    取得 Jin10 快訊列表（keyword 搜索 or 最新）
    返回: List[dict]，含 content / time / url
    """
    if keyword:
        raw = _call("search_flash", {"keyword": keyword})
        if isinstance(raw, dict):
            items = raw.get("data", {}).get("data", [])
        else:
            items = raw if isinstance(raw, list) else []
    else:
        raw = _call("list_flash", {})
        if isinstance(raw, dict):
            items = raw.get("data", {}).get("items", [])
        else:
            items = raw if isinstance(raw, list) else []
    return items[:limit]


def get_news_list(cursor: Optional[str] = None) -> List[dict]:
    raw = _call("list_news", {"cursor": cursor} if cursor else {})
    return raw.get("data", []) if isinstance(raw, dict) else []


def get_news_article(news_id: str) -> dict:
    raw = _call("get_news", {"id": news_id})
    return raw if isinstance(raw, dict) else {}


def get_calendar() -> List[dict]:
    raw = _call("list_calendar", {})
    if isinstance(raw, dict):
        return raw.get("data", [])
    return raw if isinstance(raw, list) else []


# ── 宏觀情緒分數 ─────────────────────────────────────────

def get_macro_sentiment() -> float:
    """
    宏觀情緒分數（0-100）
    50  = 中性
    >60 = 多頭友好（避險情緒升溫有利風險資產）
    <40 = 空頭偏好

    算法：基礎 50 + 黃金漲幅×2 + 原油漲幅 + 美元漲幅
    """
    try:
        gold    = get_quote("XAUUSD")
        oil     = get_quote("USOIL")
        usd_jpy = get_quote("USDJPY")

        gold_change = float(gold.get("ups_percent", 0))
        oil_change  = float(oil.get("ups_percent", 0))
        usd_change  = float(usd_jpy.get("ups_percent", 0))

        score = 50 + gold_change * 2 + oil_change + usd_change
        return max(0.0, min(100.0, score))

    except Exception as e:
        logger.warning(f"get_macro_sentiment failed: {e}, returning neutral 50")
        return 50.0


# ── 宏觀警訊檢查 ─────────────────────────────────────────

def check_macro_alerts(keywords: Optional[List[str]] = None) -> Optional[str]:
    """
    掃描 Jin10 快訊，發現 Fed/降息/非農 等關鍵字返回警訊文字
    返回 None 表示無警訊
    """
    if keywords is None:
        keywords = [
            "美聯儲", "鮑威爾", "Fed", "聯準會",
            "鷹派", "鴿派", "降息", "升息",
            "通膨", "CPI", "PPI",
            "非農", "失業率", "就業",
            "利率", "FOMC", "QE",
            "戰爭", "地緣", "制裁", "黑天鵝",
        ]
    try:
        items = get_flash(limit=15)
        for item in items:
            title = item.get("content", "")
            for kw in keywords:
                if kw in title:
                    return f"⚠️ 宏觀警訊【{kw}】：{title}"
        return None
    except Exception as e:
        logger.warning(f"check_macro_alerts failed: {e}")
        return None


def check_macro_threshold(macro_score: float,
                          bull_threshold: float = 55.0,
                          bear_threshold: float = 45.0) -> str:
    """根據宏觀分數回傳 BULL / NEUTRAL / BEAR"""
    if macro_score >= bull_threshold:
        return "BULL"
    elif macro_score <= bear_threshold:
        return "BEAR"
    return "NEUTRAL"


# ── 測試入口 ─────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stdout,
    )

    print("=" * 60)
    print("Jin10 MCP 客戶端測試")
    print("=" * 60)

    for code in ["XAUUSD", "USOIL", "USDJPY"]:
        try:
            q = get_quote(code)
            price = q.get("close", "N/A")
            change = float(q.get("ups_percent", 0))
            print(f"  {code}: ${price} ({change:+.2f}%)")
        except Exception as e:
            print(f"  {code}: ❌ {e}")

    print()
    try:
        score = get_macro_sentiment()
        flag = check_macro_threshold(score)
        print(f"  宏觀情緒: {score:.1f}/100  [{flag}]")
    except Exception as e:
        print(f"  宏觀情緒: ❌ {e}")

    print()
    try:
        items = get_flash(limit=5)
        print(f"  最新快訊 ({len(items)} 條)：")
        for item in items:
            print(f"    - {item.get('content','')[:70]}")
    except Exception as e:
        print(f"  快訊: ❌ {e}")

    print()
    try:
        cal = get_calendar()
        print(f"  本週財經日曆 ({len(cal)} 項)：")
        for e in cal[:5]:
            print(f"    - {e.get('pub_time','?')} {e.get('title','')[:50]}")
    except Exception as e:
        print(f"  日曆: ❌ {e}")

    print("\n✅ 完成")