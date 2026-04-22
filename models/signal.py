"""
Signal Model — 統一訊號格式
Trade Core 的標準輸出，供交易系統使用
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class SignalAction(Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class Market(Enum):
    TW = "TW"      # 台股
    US = "US"      # 美股
    CRYPTO = "CRYPTO"
    FX = "FX"


class AssetClass(Enum):
    EQUITY = "EQUITY"
    CRYPTO = "CRYPTO"
    FOREX = "FOREX"
    COMMODITY = "COMMODITY"


class Regime(Enum):
    BULL = "BULL"
    BEAR = "BEAR"
    NEUTRAL = "NEUTRAL"


@dataclass
class IndicatorSnapshot:
    """技術指標快照"""
    KD_K: float = None
    KD_D: float = None
    KD_cross: str = None  # GOLDEN / DEAD / NONE
    
    MACD_dif: float = None
    MACD_dea: float = None
    MACD_hist: float = None
    
    RSI: float = None
    MA5: float = None
    MA20: float = None
    MA60: float = None
    
    momentum_pct: float = None  # 20日漲幅%
    volume_ratio: float = None


@dataclass
class DimensionScores:
    """多維度評分"""
    momentum: float = 50.0   # 0-100
    technical: float = 50.0
    fund_flow: float = 50.0
    liquidity: float = 50.0
    volatility: float = 50.0
    leverage: float = 50.0
    industry: float = 50.0


@dataclass
class BacktestStats:
    """歷史回測統計"""
    win_rate: float = None
    avg_pnl: float = None
    sample_size: int = 0
    max_drawdown: float = None


@dataclass
class Signal:
    """
    統一訊號格式
    
    Usage:
        signal = Signal(
            symbol="6821",
            market=Market.TW,
            action=SignalAction.BUY,
            score=85.5,
            confidence=0.9,
            indicators=IndicatorSnapshot(...),
            dimensions=DimensionScores(...),
            valid_until=datetime.now() + timedelta(hours=24)
        )
    """
    # 識別
    symbol: str
    market: Market = Market.TW
    
    # 動作
    action: SignalAction = SignalAction.HOLD
    score: float = 0.0          # 0-100 評分
    confidence: float = 0.0     # 0-1 信心度
    
    # 支撐數據
    indicators: IndicatorSnapshot = field(default_factory=IndicatorSnapshot)
    dimensions: DimensionScores = field(default_factory=DimensionScores)
    
    # 入場/出場建議
    entry_price_target: float = None
    stop_loss_price: float = None
    take_profit_price: float = None
    position_size_pct: float = 5.0  # 預設 5% 倉位
    
    # 時效
    generated_at: datetime = field(default_factory=datetime.now)
    valid_until: datetime = None
    
    # 市場狀態
    regime: Regime = Regime.NEUTRAL
    
    # 來源
    source: str = "unknown"  # daily_scan / breakout / manual / etc.
    
    # 回測歷史
    backtest_stats: BacktestStats = None
    
    # 追蹤
    signal_id: int = None
    execution_status: str = "PENDING"  # PENDING / EXECUTED / EXPIRED / CANCELLED
    executed_trade_id: int = None
    
    def to_dict(self) -> dict:
        """轉換為字典格式（用於 JSON API）"""
        return {
            "symbol": self.symbol,
            "market": self.market.value,
            "action": self.action.value,
            "score": round(self.score, 2),
            "confidence": round(self.confidence, 2),
            
            "indicators": {
                "KD": {
                    "K": round(self.indicators.KD_K, 2) if self.indicators.KD_K else None,
                    "D": round(self.indicators.KD_D, 2) if self.indicators.KD_D else None,
                    "cross": self.indicators.KD_cross
                },
                "MACD": {
                    "dif": round(self.indicators.MACD_dif, 4) if self.indicators.MACD_dif else None,
                    "dea": round(self.indicators.MACD_dea, 4) if self.indicators.MACD_dea else None,
                    "hist": round(self.indicators.MACD_hist, 4) if self.indicators.MACD_hist else None
                },
                "RSI": round(self.indicators.RSI, 2) if self.indicators.RSI else None,
                "MA": {
                    "MA5": round(self.indicators.MA5, 2) if self.indicators.MA5 else None,
                    "MA20": round(self.indicators.MA20, 2) if self.indicators.MA20 else None,
                    "MA60": round(self.indicators.MA60, 2) if self.indicators.MA60 else None
                },
                "momentum_pct": round(self.indicators.momentum_pct, 2) if self.indicators.momentum_pct else None,
                "volume_ratio": round(self.indicators.volume_ratio, 2) if self.indicators.volume_ratio else None
            },
            
            "dimensions": {
                "momentum": round(self.dimensions.momentum, 1),
                "technical": round(self.dimensions.technical, 1),
                "fund_flow": round(self.dimensions.fund_flow, 1),
                "liquidity": round(self.dimensions.liquidity, 1),
                "volatility": round(self.dimensions.volatility, 1),
                "leverage": round(self.dimensions.leverage, 1),
                "industry": round(self.dimensions.industry, 1)
            },
            
            "entry_price_target": round(self.entry_price_target, 2) if self.entry_price_target else None,
            "stop_loss_price": round(self.stop_loss_price, 2) if self.stop_loss_price else None,
            "take_profit_price": round(self.take_profit_price, 2) if self.take_profit_price else None,
            "position_size_pct": round(self.position_size_pct, 1),
            
            "generated_at": self.generated_at.isoformat() if self.generated_at else None,
            "valid_until": self.valid_until.isoformat() if self.valid_until else None,
            
            "regime": self.regime.value,
            "source": self.source,
            
            "backtest_stats": {
                "win_rate": round(self.backtest_stats.win_rate, 2) if self.backtest_stats and self.backtest_stats.win_rate else None,
                "avg_pnl": round(self.backtest_stats.avg_pnl, 3) if self.backtest_stats and self.backtest_stats.avg_pnl else None,
                "sample_size": self.backtest_stats.sample_size if self.backtest_stats else 0
            } if self.backtest_stats else None,
            
            "signal_id": self.signal_id,
            "execution_status": self.execution_status,
            "executed_trade_id": self.executed_trade_id
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "Signal":
        """從字典建立 Signal"""
        from datetime import timedelta
        
        # Parse nested objects
        ind_data = data.get("indicators", {})
        dim_data = data.get("dimensions", {})
        bs_data = data.get("backtest_stats", {})
        
        indicators = IndicatorSnapshot(
            KD_K=ind_data.get("KD", {}).get("K"),
            KD_D=ind_data.get("KD", {}).get("D"),
            KD_cross=ind_data.get("KD", {}).get("cross"),
            MACD_dif=ind_data.get("MACD", {}).get("dif"),
            MACD_dea=ind_data.get("MACD", {}).get("dea"),
            MACD_hist=ind_data.get("MACD", {}).get("hist"),
            RSI=ind_data.get("RSI"),
            MA5=ind_data.get("MA", {}).get("MA5"),
            MA20=ind_data.get("MA", {}).get("MA20"),
            MA60=ind_data.get("MA", {}).get("MA60"),
            momentum_pct=ind_data.get("momentum_pct"),
            volume_ratio=ind_data.get("volume_ratio")
        )
        
        dimensions = DimensionScores(**dim_data) if dim_data else DimensionScores()
        
        backtest_stats = BacktestStats(
            win_rate=bs_data.get("win_rate"),
            avg_pnl=bs_data.get("avg_pnl"),
            sample_size=bs_data.get("sample_size", 0)
        ) if bs_data else None
        
        # Parse enums
        market = Market(data.get("market", "TW"))
        action = SignalAction(data.get("action", "HOLD"))
        regime = Regime(data.get("regime", "NEUTRAL"))
        
        # Parse timestamps
        generated_at = datetime.fromisoformat(data["generated_at"]) if data.get("generated_at") else datetime.now()
        valid_until = datetime.fromisoformat(data["valid_until"]) if data.get("valid_until") else None
        
        return cls(
            symbol=data["symbol"],
            market=market,
            action=SignalAction(action) if isinstance(action, str) else action,
            score=data.get("score", 0),
            confidence=data.get("confidence", 0),
            indicators=indicators,
            dimensions=dimensions,
            entry_price_target=data.get("entry_price_target"),
            stop_loss_price=data.get("stop_loss_price"),
            take_profit_price=data.get("take_profit_price"),
            position_size_pct=data.get("position_size_pct", 5.0),
            generated_at=generated_at,
            valid_until=valid_until,
            regime=Regime(regime) if isinstance(regime, str) else regime,
            source=data.get("source", "unknown"),
            backtest_stats=backtest_stats,
            signal_id=data.get("signal_id"),
            execution_status=data.get("execution_status", "PENDING"),
            executed_trade_id=data.get("executed_trade_id")
        )
