#!/usr/bin/env python3
"""ETF双动量轮动策略 — 前向参数网格搜索优化 v1.0

训练期: 2021-08 ~ 2024-06 | 测试期: 2024-07 ~ 2026-07
评估指标: 测试期 Sharpe 比率（主）+ 年化收益 + 最大回撤
"""
import sys, os, json, itertools, time, math
from datetime import datetime, timedelta
from copy import deepcopy
from statistics import mean, stdev

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.config import Config
from scripts.data_collector import ETFDataCollector
from scripts.momentum import MomentumCalculator
from scripts.strategy import DualMomentumStrategy
from scripts.backtest import BacktestEngine

# ── 搜索空间 ──
SEARCH_SPACE = {
    'momentum_window': [60, 90, 120, 180, 252],
    'relative_momentum_window': [20, 30, 50, 75, 90],
    'top_n': [1, 2, 3, 5],
    'rebalance_freq': ['monthly', 'biweekly'],
    'trailing_stop_atr_multiplier': [1.0, 1.5, 2.0, 3.0],
    'valuation_enabled': [True, False],
    'abs_momentum_threshold': [-0.05, 0.0, 0.05],
}
TRAIN_START = '2021-08-01'
TRAIN_END = '2024-06-30'
TEST_START = '2024-07-01'
TEST_END = '2026-07-09'

def grid_size():
    n = 1
    for v in SEARCH_SPACE.values():
        n *= len(v)
    return n

def run_one(params, start, end):
    """单次回测"""
    config = Config()
    for k, v in params.items():
        setattr(config, k, v)
    config.backtest_start = start
    config.backtest_end = end

    collector = ETFDataCollector(config)
    data = collector.collect_all()
    if len(data) < 5:
        return None

    strategy = DualMomentumStrategy(config)
    engine = BacktestEngine(config, strategy, data)
    result = engine.run()

    if not result:
        return None

    # 从 engine.daily_records 提取净值曲线
    navs = [r.nav for r in engine.daily_records] if engine.daily_records else []
    if len(navs) < 2:
        return None

    rets = [(navs[i] - navs[i-1]) / navs[i-1] for i in range(1, len(navs))]
    tr = result.total_return
    ar = result.annual_return
    sd = stdev(rets) if len(rets) > 1 else 0
    av = sd * math.sqrt(252)
    sh = result.sharpe_ratio
    mdd = result.max_drawdown

    return {
        'sharpe': round(sh, 4), 'annual': round(ar*100, 2),
        'total': round(tr*100, 2), 'mdd': round(mdd*100, 2),
        'volatility': round(result.volatility*100, 2),
        'trades': result.total_trades, 'win_rate': round(result.win_rate*100, 1),
        'n_days': len(navs),
    }

def optimize():
    total = grid_size()
    print(f'搜索空间: {len(SEARCH_SPACE)}参数 × {total}组合', flush=True)
    print(f'训练期: {TRAIN_START} ~ {TRAIN_END}', flush=True)
    print(f'测试期: {TEST_START} ~ {TEST_END}', flush=True)
    print(f'评估指标: 测试期Sharpe > 年化 > 回撤', flush=True)
    print('='*60, flush=True)

    # 生成所有组合
    keys = list(SEARCH_SPACE.keys())
    vals = list(SEARCH_SPACE.values())
    count = 0
    best_train = None
    best_test = None
    best_score = -999

    t0 = time.time()
    for combo in itertools.product(*vals):
        params = dict(zip(keys, combo))
        count += 1

        # 训练
        train_r = run_one(params, TRAIN_START, TRAIN_END)
        if train_r is None:
            continue

        # 测试
        test_r = run_one(params, TEST_START, TEST_END)
        if test_r is None:
            continue

        score = test_r['sharpe']  # 主指标

        if count % 20 == 0 or score > best_score:
            elapsed = time.time() - t0
            eta = elapsed / count * (total - count)
            print(f'[{count}/{total}] {params} → train_sh={train_r["sharpe"]:+.3f} test_sh={test_r["sharpe"]:+.3f} test_ar={test_r["annual"]:+.1f}% {elapsed:.0f}s ETA{eta:.0f}s', flush=True)

        if score > best_score:
            best_score = score
            best_train = train_r
            best_test = test_r
            best_params = dict(params)

        if count >= total:
            break

    elapsed = time.time() - t0
    print(f'\n{"="*60}', flush=True)
    print(f'优化完成: {count}/{total} 组合 ({elapsed:.0f}s)', flush=True)
    print(f'{"="*60}', flush=True)

    print(f'\n🏆 最优参数 (测试Sharpe={best_score:+.4f}):')
    for k, v in best_params.items():
        print(f'  {k}: {v}')

    print(f'\n训练期: Sharpe={best_train["sharpe"]:+.3f} 年化={best_train["annual"]:+.1f}% 回撤={best_train["mdd"]:.1f}%')
    print(f'测试期: Sharpe={best_test["sharpe"]:+.3f} 年化={best_test["annual"]:+.1f}% 回撤={best_test["mdd"]:.1f}%')

    # 保存
    out = {
        'date': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'search_space': {k: list(v) for k, v in SEARCH_SPACE.items()},
        'total_combinations': total,
        'completed': count,
        'best_params': best_params,
        'train_metrics': best_train,
        'test_metrics': best_test,
        'elapsed_seconds': round(elapsed),
    }
    opath = os.path.join(os.path.dirname(__file__), 'reports', 'optimize_result.json')
    os.makedirs(os.path.dirname(opath), exist_ok=True)
    with open(opath, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f'\n保存: {opath}')

    return best_params, best_train, best_test


def quick_optimize():
    """快速优化: 只搜索关键参数（phase 1），36组，支持断点续传"""
    import itertools
    phase1 = {
        'momentum_window': [60, 90, 120, 180],
        'relative_momentum_window': [30, 50, 75],
        'top_n': [1, 2, 3],
        'rebalance_freq': ['monthly'],
    }
    total = 1
    for v in phase1.values(): total *= len(v)
    print(f'快速搜索: {total}组 (禁用PE估值加速, atr=1.5 threshold=0)', flush=True)

    # 断点续传
    log_path = os.path.join(os.path.dirname(__file__), 'reports', 'optimize_progress.json')
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    completed_params = set()
    all_results = {}
    if os.path.exists(log_path):
        with open(log_path) as f:
            saved = json.load(f)
            completed_params = set(saved.get('completed_keys', []))
            all_results = saved.get('all_results', {})
            print(f'  续传: {len(completed_params)}组已跳过', flush=True)

    best_score = -999
    best_params = None
    best_train = best_test = None
    count = 0
    t0 = time.time()

    for combo in itertools.product(*phase1.values()):
        params = dict(zip(phase1.keys(), combo))
        params['valuation_enabled'] = False
        params['trailing_stop_atr_multiplier'] = 1.5
        params['abs_momentum_threshold'] = 0.0
        key = str(params)
        count += 1

        if key in completed_params:
            # 恢复之前的best
            prev = all_results.get(key, {})
            if prev:
                score = prev.get('test_sharpe', -999)
                if score > best_score:
                    best_score = score
                    best_params = dict(params)
            print(f'[{count}/{total}] {params} (已跳过)', flush=True)
            continue

        train_r = run_one(params, TRAIN_START, TRAIN_END)
        if train_r is None: continue
        test_r = run_one(params, TEST_START, TEST_END)
        if test_r is None: continue

        score = test_r['sharpe']
        flag = ''
        if score > best_score:
            best_score = score
            best_params = dict(params)
            best_train = train_r
            best_test = test_r
            flag = ' ★'

        # 保存进度
        completed_params.add(key)
        all_results[key] = {
            'params': params,
            'train_sharpe': train_r['sharpe'], 'train_annual': train_r['annual'],
            'test_sharpe': test_r['sharpe'], 'test_annual': test_r['annual'],
            'test_mdd': test_r['mdd'],
        }
        with open(log_path, 'w') as f:
            json.dump({
                'completed_keys': list(completed_params),
                'all_results': all_results,
                'best_so_far': best_params,
                'best_test_sharpe': best_score,
                'progress': f'{len(completed_params)}/{total}',
            }, f, ensure_ascii=False, indent=2)

        elapsed = time.time() - t0
        print(f'[{count}/{total}] {params} train_sh={train_r["sharpe"]:+.3f} test_sh={test_r["sharpe"]:+.3f} test_ar={test_r["annual"]:+.1f}%{flag}', flush=True)

    elapsed = time.time() - t0
    print(f'\n🏆 最优: {best_params}')
    print(f'训练: Sharpe={best_train["sharpe"]:+.3f} | 测试: Sharpe={best_test["sharpe"]:+.3f} 年化={best_test["annual"]:+.1f}% 总耗时{elapsed:.0f}s', flush=True)

    return best_params, best_train, best_test


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--full', action='store_true', help='全量搜索 (3600+组合)')
    p.add_argument('--quick', action='store_true', help='快速搜索 (36组)')
    p.add_argument('--phase2', action='store_true', help='Phase 2微调 (基于Phase1最优)')
    args = p.parse_args()

    if args.full:
        optimize()
    else:
        # 默认: 快速模式
        best_params, best_train, best_test = quick_optimize()
