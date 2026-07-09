#!/usr/bin/env python3
"""ATR 移动跟踪止损 — 每日收盘检查脚本

用法: python -m scripts.atr_stop_check [--state-file path]
输出: stop_signals.json（需卖出的ETF列表）或空文件表示无需止损
"""
import sys, os, json
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.config import Config
from scripts.data_collector import ETFDataCollector
from scripts.trading_calendar import is_trading_day

STATE_FILE = os.path.join(os.path.dirname(__file__), "reports", "atr_state.json")
SIGNAL_FILE = os.path.join(os.path.dirname(__file__), "reports", "stop_signals.json")


def load_entry_state():
    """加载入场时的ATR状态: {code: {entry_price, entry_atr, entry_date, highest}}"""
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}


def save_stop_signals(signals):
    """保存止损信号供次日开盘执行"""
    os.makedirs(os.path.dirname(SIGNAL_FILE), exist_ok=True)
    with open(SIGNAL_FILE, 'w') as f:
        json.dump(signals, f, ensure_ascii=False, indent=2)


def check_stops(config=None):
    """检查当前持仓是否触发ATR跟踪止损。返回需要卖出的ETF列表。"""
    if not is_trading_day():
        return []

    if config is None:
        config = Config()

    collector = ETFDataCollector(config)
    data = collector.collect_all()

    state = load_entry_state()
    if not state:
        return []  # 无持仓记录

    from scripts.momentum import calculate_atr

    sell_list = []

    for code, st in state.items():
        df = data.get(code)
        if df is None or df.empty:
            continue

        # 计算ATR
        atr_series = calculate_atr(df, config.trailing_stop_atr_period)
        if atr_series is None:
            continue

        # 获取今日收盘价
        today_close = float(df['close'].iloc[-1])
        today_high = float(df['high'].iloc[-1])

        entry_price = st['entry_price']
        entry_atr = st['entry_atr']
        highest = st.get('highest', entry_price)

        # 更新最高价
        if today_high > highest:
            highest = today_high
            st['highest'] = highest
            # 回写更新
            with open(STATE_FILE, 'w') as f:
                json.dump(state, f, ensure_ascii=False, indent=2)

        # 止损价 = 最高HIGH - multiplier × 入场ATR
        stop_price = highest - config.trailing_stop_atr_multiplier * entry_atr

        if today_close <= stop_price:
            dd_pct = (today_close / entry_price - 1) * 100
            etf_info = config.get_etf_info(code)
            sell_list.append({
                "code": code,
                "name": etf_info.name if etf_info else code,
                "entry_price": round(entry_price, 4),
                "stop_price": round(stop_price, 4),
                "exit_price": round(today_close, 4),
                "dd_pct": round(dd_pct, 2),
                "reason": f"ATR止损: 收盘{today_close:.4f} ≤ 止损{stop_price:.4f} (入场{entry_price:.4f})",
            })

    save_stop_signals(sell_list)
    return sell_list


if __name__ == '__main__':
    stops = check_stops()
    if stops:
        print(f"⚠ 触发 {len(stops)} 个ATR止损:")
        for s in stops:
            print(f"  {s['code']} {s['name']}: {s['reason']}")
        print(f"\n止损信号已保存: {SIGNAL_FILE}")
    else:
        print("✓ 无止损触发")
