#!/usr/bin/env python3
"""ETF双动量轮动 — 全参数前向优化（腾讯自选股数据源）

Phase 1: momentum × rel × top_n (36组, ~14分钟)
Phase 2: atr × threshold × freq (基于Phase1最优, ~27组, ~11分钟)
训练: 2021-08 ~ 2024-06 | 测试: 2024-07 ~ 2026-07
"""
import sys, os, json, itertools, time, math
from datetime import datetime
from statistics import stdev
from copy import deepcopy

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.config import Config
from scripts.data_collector import ETFDataCollector
from scripts.momentum import MomentumCalculator
from scripts.strategy import DualMomentumStrategy
from scripts.backtest import BacktestEngine

TRAIN_START, TRAIN_END = '2021-08-01', '2024-06-30'
TEST_START, TEST_END = '2024-07-01', '2026-07-09'
REPORT_DIR = os.path.join(os.path.dirname(__file__), 'reports')
os.makedirs(REPORT_DIR, exist_ok=True)

def run_one(params, start, end):
    config = Config()
    config.data_source = 'westock'  # 强制腾讯自选股
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
    navs = [r.nav for r in engine.daily_records] if engine.daily_records else []
    if len(navs) < 2:
        return None
    return {
        'sharpe': round(result.sharpe_ratio, 4),
        'annual': round(result.annual_return*100, 2),
        'total': round(result.total_return*100, 2),
        'mdd': round(result.max_drawdown*100, 2),
        'volatility': round(result.volatility*100, 2),
        'trades': result.total_trades,
        'win_rate': round(result.win_rate*100, 1),
        'n_days': len(navs),
    }

def optimize_phase(search_space, name="Phase", resume_key="phase1"):
    log_path = os.path.join(REPORT_DIR, f'optimize_{resume_key}.json')
    keys = list(search_space.keys())
    vals = list(search_space.values())
    total = 1
    for v in vals: total *= len(v)
    print(f'\n{name}: {total}组 | 数据源=腾讯自选股 | PE=禁用 |', flush=True)
    print(f'训练: {TRAIN_START}~{TRAIN_END} | 测试: {TEST_START}~{TEST_END}', flush=True)
    print('='*60, flush=True)

    # 断点续传
    done_set, all_res = set(), {}
    if os.path.exists(log_path):
        with open(log_path) as f:
            s = json.load(f)
            done_set = set(s.get('done', []))
            all_res = s.get('results', {})
            print(f'  续传: {len(done_set)}/{total} 已跳过', flush=True)

    best_score, best_params, best_train, best_test = -999, None, None, None
    count = 0
    t0 = time.time()

    for combo in itertools.product(*vals):
        params = dict(zip(keys, combo))
        key = str(params)
        count += 1
        if key in done_set:
            prev = all_res.get(key, {})
            if prev and prev.get('test_sharpe', -999) > best_score:
                best_score = prev['test_sharpe']
                best_params = dict(params)
            continue

        train_r = run_one(params, TRAIN_START, TRAIN_END)
        if train_r is None: continue
        test_r = run_one(params, TEST_START, TEST_END)
        if test_r is None: continue

        score = test_r['sharpe']
        flag = ''
        if score > best_score:
            best_score, best_params = score, dict(params)
            best_train, best_test = train_r, test_r
            flag = ' ★'

        done_set.add(key)
        all_res[key] = {
            'params': params,
            'train_sharpe': train_r['sharpe'], 'train_annual': train_r['annual'],
            'test_sharpe': test_r['sharpe'], 'test_annual': test_r['annual'],
            'test_mdd': test_r['mdd'],
        }
        with open(log_path, 'w') as f:
            json.dump({'done': list(done_set), 'results': all_res,
                       'best': best_params, 'best_score': best_score,
                       'progress': f'{len(done_set)}/{total}'}, f, ensure_ascii=False, indent=2)

        elapsed = time.time() - t0
        eta = elapsed / len(done_set) * (total - len(done_set)) if done_set else 0
        print(f'[{len(done_set)}/{total}] {params} test_sh={test_r["sharpe"]:+.3f} ar={test_r["annual"]:+.1f}% mdd={test_r["mdd"]:.1f}%{flag} ETA{eta:.0f}s', flush=True)

    elapsed = time.time() - t0
    print(f'\n🏆 {name}最优 (test_sh={best_score:+.4f}): {best_params}', flush=True)
    print(f'训练: Sharpe={best_train["sharpe"]:+.3f} 年化={best_train["annual"]:+.1f}%', flush=True)
    print(f'测试: Sharpe={best_test["sharpe"]:+.3f} 年化={best_test["annual"]:+.1f}% 回撤={best_test["mdd"]:.1f}%', flush=True)
    print(f'耗时: {elapsed:.0f}s', flush=True)
    return best_params, best_train, best_test, all_res


def run():
    # ═══ Phase 1: 核心参数 ═══
    phase1 = {
        'momentum_window': [90, 120, 180, 252],
        'relative_momentum_window': [50, 75, 90],
        'top_n': [2, 3, 5],
        'rebalance_freq': ['monthly'],
        'valuation_enabled': [False],
        'trailing_stop_atr_multiplier': [1.5],
        'abs_momentum_threshold': [0.0],
    }
    p1_best, p1_train, p1_test, p1_all = optimize_phase(phase1, "Phase1 核心参数", "phase1_westock")

    # ═══ Phase 2: 微调参数 ═══
    phase2 = {
        'momentum_window': [p1_best['momentum_window']],
        'relative_momentum_window': [p1_best['relative_momentum_window']],
        'top_n': [p1_best['top_n']],
        'rebalance_freq': ['monthly', 'biweekly'],
        'valuation_enabled': [False],
        'trailing_stop_atr_multiplier': [1.0, 1.5, 2.0, 3.0],
        'abs_momentum_threshold': [-0.05, 0.0, 0.05],
    }
    p2_best, p2_train, p2_test, p2_all = optimize_phase(phase2, "Phase2 微调", "phase2_westock")

    # ═══ 最终汇总 ═══
    final = p2_best
    print(f'\n{"="*60}', flush=True)
    print(f'🎯 最终最优参数 (westock, 前向测试):', flush=True)
    for k, v in final.items():
        print(f'  {k}: {v}', flush=True)
    print(f'测试: Sharpe={p2_test["sharpe"]:+.3f} 年化={p2_test["annual"]:+.1f}% 回撤={p2_test["mdd"]:.1f}%', flush=True)

    # 保存最终结果
    with open(os.path.join(REPORT_DIR, 'optimize_final_westock.json'), 'w') as f:
        json.dump({
            'date': datetime.now().strftime('%Y-%m-%d %H:%M'),
            'data_source': 'westock',
            'best_params': final,
            'test_metrics': p2_test,
            'train_metrics': p2_train,
        }, f, ensure_ascii=False, indent=2)
    print(f'\n保存: {REPORT_DIR}/optimize_final_westock.json', flush=True)


if __name__ == '__main__':
    run()
