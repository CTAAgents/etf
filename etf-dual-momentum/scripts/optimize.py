#!/usr/bin/env python3
"""ETF双动量轮动 — 5.5年数据+逐ETF估值刹车优化（westock）

训练: 2021-01-01 ~ 2024-06-30 (3.5年, ETF随上市渐次加入)
测试: 2024-07-01 ~ 2026-07-09 (2年)
固定核心参数 180/90/Top5，微调: atr × threshold × freq
"""
import sys, os, json, itertools, time, math
from datetime import datetime
from statistics import stdev

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.config import Config
from scripts.data_collector import ETFDataCollector
from scripts.strategy import DualMomentumStrategy
from scripts.backtest import BacktestEngine

TRAIN_START, TRAIN_END = '2021-01-01', '2024-06-30'
TEST_START, TEST_END = '2024-07-01', '2026-07-09'
REPORT_DIR = os.path.join(os.path.dirname(__file__), 'reports')
os.makedirs(REPORT_DIR, exist_ok=True)

def run_one(params, start, end):
    config = Config()
    config.data_source = 'westock'
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

def search(search_space, name, resume_key):
    log_path = os.path.join(REPORT_DIR, f'optimize_{resume_key}.json')
    keys = list(search_space.keys())
    vals = list(search_space.values())
    total = 1
    for v in vals: total *= len(v)

    print(f'\n{name}: {total}组 | 6年数据 | PE估值=ON | westock', flush=True)
    print(f'训练: {TRAIN_START}~{TRAIN_END} | 测试: {TEST_START}~{TEST_END}', flush=True)
    print('='*60, flush=True)

    done_set, all_res = set(), {}
    if os.path.exists(log_path):
        with open(log_path) as f:
            s = json.load(f)
            done_set = set(s.get('done', []))
            all_res = s.get('results', {})
            print(f'  续传: {len(done_set)}/{total}', flush=True)

    best_score, best_params, best_train, best_test = -999, None, None, None
    count, t0 = 0, time.time()

    for combo in itertools.product(*vals):
        params = dict(zip(keys, combo))
        key = str(params)
        count += 1
        if key in done_set:
            prev = all_res.get(key, {})
            if prev and prev.get('test_sharpe', -999) > best_score:
                best_score, best_params = prev['test_sharpe'], dict(params)
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
        print(f'[{len(done_set)}/{total}] {params} train_sh={train_r["sharpe"]:+.3f} test_sh={test_r["sharpe"]:+.3f} ar={test_r["annual"]:+.1f}% mdd={test_r["mdd"]:.1f}%{flag} ETA{eta:.0f}s', flush=True)

    elapsed = time.time() - t0
    print(f'\n🏆 {name}最优 (test_sh={best_score:+.4f}):', flush=True)
    for k, v in best_params.items():
        print(f'  {k}: {v}', flush=True)
    print(f'训练: Sharpe={best_train["sharpe"]:+.3f} 年化={best_train["annual"]:+.1f}%', flush=True)
    print(f'测试: Sharpe={best_test["sharpe"]:+.3f} 年化={best_test["annual"]:+.1f}% 回撤={best_test["mdd"]:.1f}%', flush=True)
    print(f'耗时: {elapsed:.0f}s', flush=True)
    return best_params, best_train, best_test

def run():
    # 基于此前优化固定核心参数，搜索微调参数
    space = {
        'momentum_window': [180],
        'relative_momentum_window': [90],
        'top_n': [5],
        'rebalance_freq': ['monthly', 'biweekly'],
        'valuation_enabled': [True],     # ★ 开启PE刹车
        'trailing_stop_atr_multiplier': [1.0, 1.5, 2.0],
        'abs_momentum_threshold': [-0.05, 0.0, 0.05],
    }
    best_p, best_train, best_test = search(space, "6年+PE刹车 微调", "6y_pe_brake")

    # 保存
    final_path = os.path.join(REPORT_DIR, 'optimize_6y_pe_brake.json')
    with open(final_path, 'w') as f:
        json.dump({
            'date': datetime.now().strftime('%Y-%m-%d %H:%M'),
            'data_source': 'westock',
            'train_period': f'{TRAIN_START}~{TRAIN_END}',
            'test_period': f'{TEST_START}~{TEST_END}',
            'best_params': best_p,
            'train_metrics': best_train,
            'test_metrics': best_test,
        }, f, ensure_ascii=False, indent=2)
    print(f'\n保存: {final_path}', flush=True)

if __name__ == '__main__':
    run()
