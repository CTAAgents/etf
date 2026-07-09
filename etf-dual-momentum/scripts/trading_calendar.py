"""交易日检测工具"""
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional

try:
    import akshare as ak
    _has_akshare = True
except ImportError:
    _has_akshare = False

_calendar_cache = None
_cache_date = None


def is_trading_day(date: Optional[datetime] = None) -> bool:
    """判断是否为A股交易日（使用AKShare交易日历）。"""
    global _calendar_cache, _cache_date
    if date is None:
        date = datetime.now()

    try:
        if _has_akshare:
            # 缓存交易日历（当天有效）
            today = datetime.now().strftime('%Y%m%d')
            if _calendar_cache is None or _cache_date != today:
                df = ak.tool_trade_date_hist_sina()
                _calendar_cache = set(df['trade_date'].astype(str).tolist())
                _cache_date = today
            date_str = date.strftime('%Y%m%d')
            return date_str in _calendar_cache
    except Exception:
        pass

    # Fallback: 周末判断
    return date.weekday() < 5


def get_last_trading_day(ref=None) -> datetime:
    """获取最近的一个交易日。"""
    if ref is None:
        ref = datetime.now()
    d = ref
    for _ in range(10):
        if is_trading_day(d):
            return d.replace(hour=0, minute=0, second=0, microsecond=0)
        d -= timedelta(days=1)
    return ref


def data_is_fresh(data) -> bool:
    """检查日线数据是否包含今天的更新（非假期判断）。"""
    for df in data.values():
        if df is not None and not df.empty and 'date' in df.columns:
            last_date = pd.Timestamp(df['date'].iloc[-1])
            if (pd.Timestamp.now().normalize() - last_date.normalize()).days <= 1:
                return True
    return False
