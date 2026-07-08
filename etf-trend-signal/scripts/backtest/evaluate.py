#!/usr/bin/env python3
"""
通道突破策略回测评估框架 v2.0
=================================
支持历史数据回放、性能评估、优化搜索。

适配新的通道突破策略评分体系（Layer A唐奇安通道 + Layer B布林带 + 成交量确认）。
"""
import sys, os, json, math
from datetime import date, datetime, timedelta

# ── 路径自举 ──
BACKTEST_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(BACKTEST_DIR)

for p in [SKILL_DIR, BACKTEST_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    from scripts.collect_data import EtfDataCollector
    from scripts.indicators import _compute_indicators_numpy
    from scripts.scoring_system import calculate_composite_score
    from scripts.config import SECTOR_ETF_MAPPING, SECTOR_NAMES
except ImportError:
    from collect_data import EtfDataCollector
    from indicators import _compute_indicators_numpy
    from scoring_system import calculate_composite_score
    from config import SECTOR_ETF_MAPPING, SECTOR_NAMES

import pandas as pd
import numpy as np
from statistics import mean, stdev


def collect_data(sector_name: str, etf_code: str, days: int = 250) -> list:
    """从TDX采集历史日K线数据。"""
    collector = EtfDataCollector()
    klines = collector.get_etf_klines(sector_name, etf_code, days=days)
    if not klines or len(klines) < 60:
        return []
    return klines


def replay_scores(klines: list, step: int = 1, split_ratio: float = 1.0) -> list:
    """逐日滑动窗口回放通道突破评分。

    Args:
        klines: 历史K线列表（按时间升序）
        step: 回放步长（默认1天步进）
        split_ratio: 训练/测试分割比例（1.0=全部, <1.0=后段测试）

    Returns:
        [{'date': str, 'price': float, 'total': float, 'grade': str,
          'direction': str, 'signal_type': str,
          'dc20': float, 'dc55': float, 'bb': float, 'vol': float,
          'abs_score': float}, ...]
    """
    results = []
    min_bars = 60

    total = len(klines)
    split_idx = int(total * split_ratio)
    start = max(min_bars, split_idx)  # 从分割点开始（如果split_ratio<1，则从该点起步进）

    for i in range(start, total, step):
        window = klines[:i+1]
        closes = [float(r['close']) for r in window]

        df = pd.DataFrame({
            'open': [float(r['open']) for r in window],
            'high': [float(r['high']) for r in window],
            'low': [float(r['low']) for r in window],
            'close': closes,
            'volume': [float(r.get('volume', 0)) for r in window],
        })

        tech = _compute_indicators_numpy(df)
        if not tech or 'RSI14' not in tech:
            continue

        price = tech.get('last_price', closes[-1])
        sym = {'last_price': price}
        sc = calculate_composite_score(tech, sym)

        results.append({
            'date': window[-1].get('date', ''),
            'price': round(price, 3),
            'total': sc['total'],
            'abs_score': round(abs(sc['total']), 1),
            'grade': sc['grade'],
            'direction': sc['direction'],
            'signal_type': sc['signal_type'],
            'dc20': sc['sub_scores']['dc20'],
            'dc55': sc['sub_scores']['dc55'],
            'bb': sc['sub_scores']['bb'],
            'vol': sc['sub_scores']['vol'],
        })

    return results


def replay_scores_split(klines: list, step: int = 1, train_ratio: float = 0.7) -> dict:
    """严格时间分割回放：前train_ratio%训练 → 后(1-train_ratio)%测试。

    消除未来信息泄露（训练集和测试集严格不重叠）。
    """
    train_size = int(len(klines) * train_ratio)

    train_klines = klines[:train_size]
    test_klines = klines[train_size:]

    # 训练集从min_bars开始
    train_results = replay_scores(train_klines, step=step)
    # 测试集从训练集末尾+1开始
    test_window = train_klines + test_klines
    test_results = replay_scores(test_window, step=step, split_ratio=train_ratio)

    return {
        'train': train_results,
        'test': test_results,
        'train_range': f"{train_results[0]['date'] if train_results else '?'} ~ {train_results[-1]['date'] if train_results else '?'}",
        'test_range': f"{test_results[0]['date'] if test_results else '?'} ~ {test_results[-1]['date'] if test_results else '?'}",
    }


def evaluate_performance(results: list) -> dict:
    """按信号等级统计通道突破策略的绩效表现。"""
    if not results:
        return {'total_signals': 0}

    total = len(results)
    abs_scores = [r['abs_score'] for r in results]
    avg_score = mean(abs_scores) if abs_scores else 0
    std_score = stdev(abs_scores) if len(abs_scores) > 1 else 0

    strong = [r for r in results if r['grade'] == 'STRONG']
    watch = [r for r in results if r['grade'] == 'WATCH']
    weak = [r for r in results if r['grade'] == 'WEAK']
    noise = [r for r in results if r['grade'] == 'NOISE']

    bull = [r for r in results if r['direction'] == 'bull']
    bear = [r for r in results if r['direction'] == 'bear']

    # 按信号类型统计
    breakout = [r for r in results if r['signal_type'] == 'channel_breakout']
    trend_conf = [r for r in results if r['signal_type'] == 'trend_confirmation']
    squeeze = [r for r in results if r['signal_type'] == 'bb_squeeze_prebreakout']

    return {
        'total_signals': total,
        'avg_score': round(avg_score, 2),
        'std_score': round(std_score, 2),
        'strong_count': len(strong),
        'watch_count': len(watch),
        'weak_count': len(weak),
        'noise_count': len(noise),
        'bull_count': len(bull),
        'bear_count': len(bear),
        'breakout_count': len(breakout),
        'trend_conf_count': len(trend_conf),
        'squeeze_count': len(squeeze),
        'strong_ratio': round(len(strong) / max(total, 1) * 100, 1),
        'bull_ratio': round(len(bull) / max(total, 1) * 100, 1),
        'avg_strong_score': round(mean([r['abs_score'] for r in strong]), 1) if strong else 0,
        'avg_watch_score': round(mean([r['abs_score'] for r in watch]), 1) if watch else 0,
    }


def save_results(results: dict, output_dir: str = None) -> str:
    """保存回测结果。"""
    today = date.today().strftime('%Y%m%d_%H%M%S')
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        path = os.path.join(output_dir, f'backtest_{today}.json')
    else:
        path = os.path.join(BACKTEST_DIR, 'results', f'backtest_{today}.json')
        os.makedirs(os.path.dirname(path), exist_ok=True)

    with open(path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)
    return path


def main():
    """CLI入口。"""
    import argparse
    parser = argparse.ArgumentParser(description='通道突破策略回测评估 v2.0')
    parser.add_argument('--sectors', nargs='+', default=['半导体'],
                        help='回测行业列表（默认半导体）')
    parser.add_argument('--days', type=int, default=250,
                        help='历史数据天数（默认250）')
    parser.add_argument('--step', type=int, default=5,
                        help='回放步长（默认5天）')
    parser.add_argument('--split', action='store_true',
                        help='启用严格训练/测试分割')
    parser.add_argument('--train-ratio', type=float, default=0.7,
                        help='训练集比例（默认0.7）')
    parser.add_argument('--mode', choices=['collect', 'eval', 'full'], default='full',
                        help='模式：collect(只采集), eval(只评估已有数据), full(采集+评估)')
    args = parser.parse_args()

    print(f"{'='*60}")
    print(f"通道突破策略回测评估 v2.0")
    print(f"行业: {args.sectors}")
    print(f"{'='*60}")

    all_results = {}

    for sector_name in args.sectors:
        # 查找ETF代码
        etf_code = ''
        for s in SECTOR_ETF_MAPPING:
            if s[0] == sector_name:
                etf_code = s[2]
                break
        if not etf_code:
            print(f"[SKIP] 未知行业: {sector_name}")
            continue

        print(f"\n--- {sector_name} ({etf_code}) ---")
        klines = collect_data(sector_name, etf_code, days=args.days)
        if not klines or len(klines) < 60:
            print(f"[SKIP] 数据不足 ({len(klines) if klines else 0})")
            continue

        if args.split:
            split_results = replay_scores_split(klines, step=args.step, train_ratio=args.train_ratio)
            eval_train = evaluate_performance(split_results['train'])
            eval_test = evaluate_performance(split_results['test'])

            all_results[sector_name] = {
                'total_klines': len(klines),
                'train': eval_train,
                'test': eval_test,
                'train_range': split_results['train_range'],
                'test_range': split_results['test_range'],
            }

            print(f"  训练集 ({split_results['train_range']}): "
                  f"STRONG={eval_train['strong_count']}, WATCH={eval_train['watch_count']}, "
                  f"多头={eval_train['bull_ratio']}%")
            print(f"  测试集 ({split_results['test_range']}): "
                  f"STRONG={eval_test['strong_count']}, WATCH={eval_test['watch_count']}, "
                  f"多头={eval_test['bull_ratio']}%")
        else:
            replay = replay_scores(klines, step=args.step)
            perf = evaluate_performance(replay)

            all_results[sector_name] = {
                'total_klines': len(klines),
                'replay_points': len(replay),
                'performance': perf,
            }

            print(f"  回放: {len(replay)}个评分点")
            print(f"  STRONG={perf['strong_count']}, WATCH={perf['watch_count']}, "
                  f"WEAK={perf['weak_count']}, NOISE={perf['noise_count']}")
            print(f"  多头={perf['bull_count']}({perf['bull_ratio']}%), "
                  f"空头={perf['bear_count']}")
            print(f"  通道突破信号={perf['breakout_count']}, "
                  f"趋势确认={perf['trend_conf_count']}, "
                  f"BB挤压前兆={perf['squeeze_count']}")

    path = save_results(all_results)
    print(f"\n✅ 结果已保存: {path}")


if __name__ == '__main__':
    main()
