#!/usr/bin/env python3
"""
通道突破策略参数优化 v2.2 — 基于真实信号触发频率的优化
============================================================
根据信号触发频率分析：
- DC20突破率 ≈ 0% → 不适合优化DC20参数
- 有效优化方向：DC55位置阈值 + BB带宽阈值 + 成交量阈值
- 评价指标：区分度（bull/bear分离度）+ STRING信号质量
"""
import sys, os, json, copy
from datetime import date
from statistics import mean, stdev

BACKTEST_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(BACKTEST_DIR)
SKILL_ROOT = os.path.dirname(SKILL_DIR)
for p in [SKILL_ROOT, SKILL_DIR, BACKTEST_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)

from collect_data import EtfDataCollector
from indicators import _compute_indicators_numpy
from config import CHANNEL_BREAKOUT_CONFIG
import pandas as pd

import scoring_system as SS  # 统一模块引用，确保配置注入一致


# ══════════════════════════════════════════════════════════════
# 配置
# ══════════════════════════════════════════════════════════════
REPRESENTATIVE_SECTORS = [
    ('半导体', '512480.SH'),
    ('电子', '159997.SZ'),
    ('食品饮料', '515170.SH'),
    ('有色金属', '512400.SH'),
    ('军工', '512660.SH'),
    ('证券', '512880.SH'),
]

# 只优化实际会触发的参数
PARAM_GRID = {
    # DC55位置阈值（最大影响）
    'dc55_position__extreme_upper_score': [15, 20, 25, 30],
    'dc55_position__upper_score': [10, 12, 15, 18, 20],
    'dc55_position__mid_upper_score': [3, 5, 7],
    # DC55趋势方向分值
    'dc55_trend__trend_alignment_bonus': [3, 5, 7],
    # BB带宽阈值
    'bb__width_high_threshold': [3.0, 3.5, 4.0, 4.5, 5.0],
    'bb__width_moderate_threshold': [2.0, 2.5, 3.0],
    # 成交量阈值
    'volume__explosive_ratio': [1.3, 1.5, 1.8],
    'volume__elevated_ratio': [1.1, 1.2, 1.3],
    # 信号类型阈值
    'signal_type__channel_breakout_dc20_min': [25, 30, 35],
    'signal_type__trend_confirmation_dc55_min': [10, 12, 15, 18],
}


def _set_nested(config: dict, key: str, value):
    parts = key.split('__')
    d = config
    for p in parts[:-1]:
        d = d.setdefault(p, {})
    d[parts[-1]] = value


def make_config(param_overrides: dict) -> dict:
    """创建带覆盖的配置副本。"""
    config = copy.deepcopy(CHANNEL_BREAKOUT_CONFIG)
    for key, value in param_overrides.items():
        _set_nested(config, key, value)
    return config


# ══════════════════════════════════════════════════════════════
# 评分管线（单窗口）
# ══════════════════════════════════════════════════════════════

def score_window(window_klines: list) -> dict:
    """对一个K线窗口做通道突破评分。

    通过在 scoring_system 模块中注入临时配置实现参数覆盖。
    """
    df = pd.DataFrame({
        'open': [float(r['open']) for r in window_klines],
        'high': [float(r['high']) for r in window_klines],
        'low': [float(r['low']) for r in window_klines],
        'close': [float(r['close']) for r in window_klines],
        'volume': [float(r.get('volume', 0)) for r in window_klines],
    })

    tech = _compute_indicators_numpy(df)
    if not tech or 'RSI14' not in tech:
        return None

    price = tech.get('last_price', float(df['close'].iloc[-1]))
    sym = {'last_price': price}

    # 使用SS模块全局计算的函数（已通过模块属性注入配置）
    sc = SS.calculate_composite_score(tech, sym)

    return {
        'total': sc['total'],
        'direction': sc['direction'],
        'grade': sc['grade'],
        'signal_type': sc['signal_type'],
        'sub': sc['sub_scores'],
    }


def run_config_on_klines(klines: list, config: dict) -> list:
    """用指定配置对K线做滑动窗口评分。"""
    min_bars = 60
    if len(klines) < min_bars:
        return []

    # 注入配置
    orig_cfg = SS.CHANNEL_BREAKOUT_CONFIG
    SS.CHANNEL_BREAKOUT_CONFIG = config

    results = []
    try:
        for i in range(min_bars, len(klines), 3):
            window = klines[:i+1]
            sc = score_window(window)
            if sc:
                results.append(sc)
    finally:
        SS.CHANNEL_BREAKOUT_CONFIG = orig_cfg

    return results


# ══════════════════════════════════════════════════════════════
# 评估指标
# ══════════════════════════════════════════════════════════════

def evaluate_results(results: list) -> dict:
    """评估评分结果的质量。

    指标说明：
    - bull_pct: 多头信号占比（越高说明系统越倾向于发现多头机会）
    - avg_bull: 多头信号平均分（越高越好）
    - avg_bear_bull_ratio: 空头平均绝对值 / 多头平均分（区分度）
    - strong_pct: STRONG信号占比（质量指标）
    - composite: avg_bull × (1 + strong_pct) × bull_pct（综合）
    """
    if not results:
        return {'bull_pct': 0, 'avg_bull': 0, 'avg_bear': 0,
                'strong_pct': 0, 'composite': 0}

    n = len(results)
    bull = [r for r in results if r['direction'] == 'bull']
    bear = [r for r in results if r['direction'] == 'bear']
    strong = [r for r in results if r['grade'] == 'STRONG']

    bull_pct = len(bull) / n
    strong_pct = len(strong) / n
    avg_bull = mean([r['total'] for r in bull]) if bull else 0
    avg_bear = mean([abs(r['total']) for r in bear]) if bear else 0

    # 区分度：空头均分/多头均分（越大说明正负向分离越好）
    sep = avg_bear / avg_bull if avg_bull > 0 else 0

    composite = avg_bull * (1 + strong_pct) * bull_pct

    return {
        'n': n,
        'bull_pct': round(bull_pct, 4),
        'avg_bull': round(avg_bull, 2),
        'avg_bear': round(avg_bear, 2),
        'strong_pct': round(strong_pct, 4),
        'separation': round(sep, 3),
        'composite': round(composite, 2),
    }


# ══════════════════════════════════════════════════════════════
# 优化主流程
# ══════════════════════════════════════════════════════════════

def main():
    print(f'{"="*60}')
    print(f'通道突破策略参数优化 v2.2')
    print(f'日期: {date.today()}')
    print(f'已确认信号触发频率：DC20突破≈0%，DC55趋势=16-30%，BB挤压=8-19%')
    print(f'优化方向：DC55阈值 + BB带宽 + 成交量阈值')
    print(f'{"="*60}')

    # Step 1: 采集数据
    print('\n[1] 采集历史数据...')
    collector = EtfDataCollector()
    all_data = {}
    for sector, code in REPRESENTATIVE_SECTORS:
        klines = collector.get_etf_klines(sector, code, days=250)
        if klines and len(klines) >= 60:
            all_data[sector] = {'code': code, 'klines': klines}
            print(f'  ✅ {sector} ({code}): {len(klines)} bars')
    print(f'  共 {len(all_data)} 个行业')

    # Step 2: 基准评估
    print('\n[2] 评估基准 (默认参数)...')
    baseline_cfg = make_config({})
    baseline_scores = []
    for sec, d in all_data.items():
        baseline_scores.extend(run_config_on_klines(d['klines'], baseline_cfg))
    base_ev = evaluate_results(baseline_scores)
    print(f'  基准: avg_bull={base_ev["avg_bull"]}, bull_pct={base_ev["bull_pct"]:.1%}, '
          f'strong_pct={base_ev["strong_pct"]:.1%}, separation={base_ev["separation"]}, '
          f'composite={base_ev["composite"]}')

    # Step 3: 网格搜索
    print(f'\n[3] 网格搜索...')
    results = []
    total_params = 0
    for key, values in PARAM_GRID.items():
        for v in values:
            total_params += 1

    idx = 0
    for key, values in PARAM_GRID.items():
        for v in values:
            idx += 1
            param_set = {key: v}
            mod_cfg = make_config(param_set)

            # 在测试集（后30%数据）上评估
            test_scores = []
            for sec, d in all_data.items():
                klines = d['klines']
                split = int(len(klines) * 0.7)
                test_scores.extend(run_config_on_klines(klines[split:], mod_cfg))

            ev = evaluate_results(test_scores)
            improvement = ev['composite'] - base_ev['composite']

            results.append({
                'params': param_set,
                'composite': ev['composite'],
                'avg_bull': ev['avg_bull'],
                'bull_pct': ev['bull_pct'],
                'strong_pct': ev['strong_pct'],
                'improvement': round(improvement, 2),
            })

            arrow = '🟢' if improvement > 1 else ('🟡' if improvement > 0 else '🔴')
            if idx % 5 == 0 or idx == total_params:
                print(f'    [{idx}/{total_params}] {key}={v} → '
                      f'composite={ev["composite"]}(base={base_ev["composite"]}), '
                      f'avg_bull={ev["avg_bull"]} {arrow}')

    # Step 4: 排序
    results.sort(key=lambda x: x['composite'], reverse=True)

    print(f'\n{"="*60}')
    print('[4] 优化结果排名')
    print(f'{"="*60}')
    print(f'\n基准: composite={base_ev["composite"]}, avg_bull={base_ev["avg_bull"]}, '
          f'separation={base_ev["separation"]}')

    print(f'\nTop 15 参数优化:')
    print(f'{"#":>3} {"参数":<40} {"值":>8} {"Composite":>10} {"AvgBull":>8} {"改善":>8}')
    print('-' * 75)
    for i, r in enumerate(results[:15], 1):
        k = list(r['params'].keys())[0]
        v = r['params'][k]
        imp = r['improvement']
        arrow = '🟢' if imp > 1 else ('🟡' if imp > 0 else '🔴')
        print(f'{i:>3} {k:<40} {str(v):>8} {r["composite"]:>10.2f} {r["avg_bull"]:>8.2f} {imp:>+7.1f} {arrow}')

    # Best improvements
    improving = [r for r in results if r['improvement'] > 1]
    if improving:
        best = improving[0]
        print(f'\n✅ 最优改善: {best["params"]}')
        print(f'  composite: {base_ev["composite"]} → {best["composite"]} (+{best["improvement"]})')
        print(f'  avg_bull: {base_ev["avg_bull"]} → {best["avg_bull"]}')
        print(f'  strong_pct: {base_ev["strong_pct"]:.1%} → {best["strong_pct"]:.1%}')
    else:
        print(f'\n⚠️ 当前默认参数已较优，无超过1分的改善')
        # 列出最好的几个
        for r in results[:5]:
            print(f'  {r["params"]}: improvement={r["improvement"]}')

    # Save
    output = {
        'date': str(date.today()),
        'baseline': base_ev,
        'top15': results[:15],
        'all_results_count': len(results),
    }
    out_path = os.path.join(BACKTEST_DIR, 'results',
                            f'optimize_{date.today().strftime("%Y%m%d_%H%M%S")}.json')
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)
    print(f'\n📊 结果已保存: {out_path}')


if __name__ == '__main__':
    main()
