"""
Feedback Model — 追蹤訊號執行結果
用於 Evolution Engine 的學習資料
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from enum import Enum


class ExitReason(Enum):
    STOP_LOSS = "STOP_LOSS"
    TAKE_PROFIT = "TAKE_PROFIT"
    TIME_UP = "TIME_UP"
    MANUAL = "MANUAL"
    SIGNAL_EXPIRED = "SIGNAL_EXPIRED"


@dataclass
class ExecutionInfo:
    """執行資訊"""
    executed: bool = False
    entry_price: float = None
    entry_time: datetime = None
    exit_price: float = None
    exit_time: datetime = None
    shares: int = 0
    commission: float = 0.0  # 手續費


@dataclass
class ResultInfo:
    """交易結果"""
    pnl_pct: float = None    # 報酬率（已扣手續費）
    hold_days: int = 0
    exit_reason: ExitReason = ExitReason.MANUAL
    realized: bool = False


@dataclass
class MarketContext:
    """市場狀態（當時）"""
    index_change: float = 0.0      # 大盤漲跌%
    sector_performance: float = 0.0 # 產業表現
    macro_sentiment: str = "NEUTRAL"  # BULL / BEAR / NEUTRAL
    regime: str = "NEUTRAL"


@dataclass
class SignalFeedback:
    """
    訊號 Feedback 記錄
    
    用於追蹤：
    - Signal 是否有被執行
    - 執行後的結果如何
    - 市場當時的狀態
    """
    # 關聯
    signal_id: int
    symbol: str
    market: str = "TW"
    
    # 執行
    execution: ExecutionInfo = field(default_factory=ExecutionInfo)
    
    # 結果
    result: ResultInfo = field(default_factory=ResultInfo)
    
    # 市場狀態
    market_context: MarketContext = field(default_factory=MarketContext)
    
    # 時間戳
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    
    # 附加資料
    notes: str = ""
    
    def to_dict(self) -> dict:
        return {
            "signal_id": self.signal_id,
            "symbol": self.symbol,
            "market": self.market,
            "execution": {
                "executed": self.execution.executed,
                "entry_price": round(self.execution.entry_price, 2) if self.execution.entry_price else None,
                "entry_time": self.execution.entry_time.isoformat() if self.execution.entry_time else None,
                "exit_price": round(self.execution.exit_price, 2) if self.execution.exit_price else None,
                "exit_time": self.execution.exit_time.isoformat() if self.execution.exit_time else None,
                "shares": self.execution.shares,
                "commission": round(self.execution.commission, 2)
            },
            "result": {
                "pnl_pct": round(self.result.pnl_pct, 3) if self.result.pnl_pct else None,
                "hold_days": self.result.hold_days,
                "exit_reason": self.result.exit_reason.value,
                "realized": self.result.realized
            },
            "market_context": {
                "index_change": round(self.market_context.index_change, 2),
                "sector_performance": round(self.market_context.sector_performance, 2),
                "macro_sentiment": self.market_context.macro_sentiment,
                "regime": self.market_context.regime
            },
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "notes": self.notes
        }
    
    def mark_closed(self, exit_price: float, exit_reason: ExitReason, pnl_pct: float, hold_days: int):
        """標記為已結束"""
        self.execution.exit_price = exit_price
        self.execution.exit_time = datetime.now()
        self.result.pnl_pct = pnl_pct
        self.result.exit_reason = exit_reason
        self.result.hold_days = hold_days
        self.result.realized = True
        self.updated_at = datetime.now()
