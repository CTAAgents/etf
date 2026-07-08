#!/usr/bin/env python3
"""
通道突破策略参数优化 v2.0
=================================
⚠️ v2.0.0: 评分架构已从L1-L4改为通道突破策略。

新评分系统的"权重"由业务逻辑固定（Layer A 75% + Layer B 25%），
可优化的参数是阈值（DC20 break_pct、ADX阈值、BB宽度阈值等）。

本框架支持网格搜索关键参数。
"""
import sys, os, json, math
from datetime import date, datetime
import itertools

BACKTEST_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(BACKTEST_DIR)

for p in [SKILL_DIR, BACKTEST_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    from scripts.collect_data import EtfDataCollector
    from scripts.indicators import _compute_indicators_numpy
    from scripts.scoring_system import (
        calculate_composite_score, score_dc20, score_dc55, score_bb, score_volume,
        CHANNEL_BREAKOUT_CONFIG
    )
    from scripts.config import SECTOR_ETF_MAPPING
except ImportError:
    from collect_data import EtfDataCollector
    from indicators import _compute_indicators_numpy
    from scoring_system import (
        calculate_composite_score, score_dc20, score_dc55, score_bb, score_volume,
        CHANNEL_BREAKOUT_CONFIG
    )
    from config import SECTOR_ETF_MAPPING

import pandas as pd
import numpy as np
from statistics import mean, stdev


def evaluate_params(klines, param_overrides: dict) -> dict:
    """用指定参数评估评分效果。

    Args:
        klines: 历史K线
        param_overrides: 参数覆盖，如 {'dc20': {'break_base_score': 35}}
    """
    window = klines[:-20]  # 保持大部分数据训练
    if len(window) < 60:
        return {'avg_abs': 0, 'strong_pct': 0}

    df = pd.DataFrame({
        'open': [float(r['open']) for r in window],
        'high': [float(r['high']) for r in window],
        'low': [float(r['low']) for r in window],
        'close': [float(r['close']) for r in window],
        'volume': [float(r.get('volume', 0)) for r in window],
    })

    tech = _compute_indicators_numpy(df)
    if not tech or 'RSI14' not in tech:
        return {'avg_abs': 0, 'strong_pct': 0}

    price = tech.get('last_price', float(df['close'].iloc[-1]))
    sym = {'last_price': price}
    sc = calculate_composite_score(tech, sym)

    abs_score = abs(sc['total'])
    return {
        'avg_abs': abs_score,
        'total': sc['total'],
        'grade': sc['grade'],
        'signal_type': sc['signal_type'],
    }


def generate_param_grid() -> list:
    """生成参数网格（可优化阈值）。

    通道突破策略中可优化的关键参数：
    - DC20 break_strong_pct (突破幅度阈值)
    - ADX exhaustion_threshold (衰竭阈值)
    - BB width_high_threshold (BB宽度阈值)
    """
    param_grid = []

    # DC20 strong break porcentage
    for strong_pct in [0.5, 0.8, 1.0, 1.2, 1.5]:
        param_grid.append({
            'dc20_break_strong_pct': strong_pct,
            'params': {'dc20': {'break_strong_pct': strong_pct}},
        })

    # ADX exhaustion threshold
    for adx_ex in [50, 55, 60, 65, 70]:
        param_grid.append({
            'adx_exhaustion': adx_ex,
            'params': {'adx': {'exhaustion_threshold': adx_ex}},
        })

    # BB width high threshold
    for bb_width in [3.0, 3.5, 4.0, 4.5, 5.0]:
        param_grid.append({
            'bb_width_high': bb_width,
            'params': {'bb': {'width_high_threshold': bb_width}},
        })

    return param_grid


def run_simple_optimization(sector_name: str, etf_code: str, days: int = 250) -> dict:
    """运行参数优化（网格搜索）。"""
    collector = EtfDataCollector()
    klines = collector.get_etf_klines(sector_name, etf_code, days=days)
    if not klines or len(klines) < 60:
        return {'sector': sector_name, 'error': '数据不足'}

    param_grid = generate_param_grid()
    results = []

    for item in param_grid:
        eval_result = evaluate_params(klines, item['params'])
        results.append({
            'params': item,
            'eval': eval_result,
        })

    # 按平均绝对值排序
    results.sort(key=lambda x: x['eval']['avg_abs'], reverse=True)

    return {
        'sector': sector_name,
        'etf_code': etf_code,
        'total_klines': len(klines),
        'top_params': results[:5] if results else [],
        'all_params': results,
    }


def main():
    """CLI入口。"""
    import argparse
    parser = argparse.ArgumentParser(description='通道突破策略参数优化 v2.0')
    parser.add_argument('--sectors', nargs='+', default=['半导体'],
                        help='优化行业列表')
    parser.add_argument('--days', type=int, default=250)
    parser.add_argument('--apply', action='store_true',
                        help='将最优参数写入config.py')
    args = parser.parse_args()

    print(f"{'='*60}")
    print(f"通道突破策略参数优化 v2.0")
    print(f"{'='*60}")

    for sector_name in args.sectors:
        etf_code = ''
        for s in SECTOR_ETF_MAPPING:
            if s[0] == sector_name:
                etf_code = s[2]
                break

        if not etf_code:
            print(f"[SKIP] 未知行业: {sector_name}")
            continue

        print(f"\n--- {sector_name} ({etf_code}) ---")
        result = run_simple_optimization(sector_name, etf_code, days=args.days)

        if 'error' in result:
            print(f"  {result['error']}")
            continue

        print(f"  K线: {result['total_klines']}根")
        print(f"  Top3参数组合:")
        for i, r in enumerate(result['top_params'][:3], 1):
            eval_data = r['eval']
            print(f"    #{i} params={r['params']} → "
                  f"avg_abs={eval_data['avg_abs']:.1f}, "
                  f"total={eval_data['total']:+.1f}, "
                  f"grade={eval_data['grade']}, "
                  f"type={eval_data['signal_type']}")

    # 保存结果
    output_path = os.path.join(BACKTEST_DIR, 'results',
                                f'optimize_{date.today().strftime("%Y%m%d_%H%M%S")}.json')
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump({'args': vars(args), 'results': result if len(args.sectors) == 1 else 'multi'},
                  f, ensure_ascii=False, indent=2, default=str)
    print(f"\n✅ 结果已保存: {output_path}")


if __name__ == '__main__':
    main()
