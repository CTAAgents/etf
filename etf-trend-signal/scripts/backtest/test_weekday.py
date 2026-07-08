#!/usr/bin/env python3
"""
测试周频调仓在不同工作日的表现差异。
"""
import sys, os, json, math
from statistics import mean, stdev
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from collect_data import EtfDataCollector
from config import SECTOR_ETF_MAPPING

# 固定参数（优化结果）
TOP_N, ENTRY, EXIT, FC = 3, 55, 30, 35

CACHE = os.path.join(os.path.dirname(__file__), 'results', 'cached_scores.json')
WEEKDAY_NAMES = {0:'周一',1:'周二',2:'周三',3:'周四',4:'周五'}


def load_cache_and_data():
    with open(CACHE) as f:
        cache_data = json.load(f)
    cached = cache_data['scores']

    collector = EtfDataCollector()
    all_data = {}
    for s in SECTOR_ETF_MAPPING:
        sector, code = s[0], s[2]
        klines = collector.get_etf_klines(sector, code, days=750)
        if klines and len(klines) >= 100:
            all_data[sector] = {'code': code, 'klines': klines}

    # 日期列表
    first = list(all_data.keys())[0]
    klines = all_data[first]['klines']
    dates = []
    for i in range(len(klines)):
        ds = str(klines[i].get('date', ''))
        try:
            dt = datetime.strptime(ds, '%Y%m%d')
            dates.append((ds, i, dt.weekday()))
        except:
            continue

    return cached, all_data, dates


def simulate(cached, all_data, dates, weekday):
    """用指定工作日作为信号计算日，次日开盘执行。"""
    rebal = [(ds, idx, i) for i, (ds, idx, w) in enumerate(dates) if i >= 60 and w == weekday]

    holdings = {}
    equity = [1.0]
    rets = []

    for ri in range(len(rebal)):
        ds, data_idx, cache_idx = rebal[ri]
        scores = cached.get(str(cache_idx), [])
        if not scores:
            continue

        bull = sorted([s for s in scores if s['d'] == 'bull'], key=lambda x: x['t'], reverse=True)
        max_bull = max((s['t'] for s in bull), default=0)

        if max_bull < FC:
            r = calc_ret(holdings, all_data, data_idx, rebal, ri)
            rets.append(r)
            equity.append(equity[-1] * (1 + r))
            holdings = {}
            continue

        pool = []
        for r_rec in bull:
            if len(pool) >= TOP_N:
                break
            if r_rec['t'] > ENTRY:
                pool.append(r_rec['s'])

        pool_set = set(pool)
        scores_map = {s['s']: s['t'] for s in scores}

        keep = set()
        for sec in list(holdings.keys()):
            in_t = sec in pool_set
            sc = scores_map.get(sec, 0)
            rk = next((i+1 for i, r_rec in enumerate(bull) if r_rec['s'] == sec), 999)
            if in_t:
                keep.add(sec)
            elif rk > TOP_N and sc < EXIT:
                continue
            else:
                keep.add(sec)

        new_b = [s for s in pool if s not in keep]
        kept = sum(holdings.get(s, 0) for s in keep)
        rem = max(0.0, 1.0 - kept)

        pos = {}
        for s in keep:
            pos[s] = holdings.get(s, 0)
        if new_b and rem > 0:
            p = round(rem / len(new_b), 4)
            for s in new_b:
                pos[s] = p

        tot = sum(pos.values())
        if abs(tot - 1.0) > 0.001 and pos:
            last = list(pos.keys())[-1]
            pos[last] = round(pos[last] + (1.0 - tot), 4)

        r = calc_ret(holdings, all_data, data_idx, rebal, ri)
        rets.append(r)
        equity.append(equity[-1] * (1 + r))
        holdings = pos

    return metrics(rets, equity)


def calc_ret(holdings, all_data, data_idx, rebal, ri):
    if not holdings:
        return 0.0
    next_idx = rebal[ri+1][1] if ri+1 < len(rebal) else data_idx + 5
    ret = 0.0
    for sec, alloc in holdings.items():
        k = all_data.get(sec, {}).get('klines', [])
        if not k:
            continue
        bi = data_idx + 1
        if bi >= len(k):
            continue
        bp = float(k[bi].get('open', 0))
        if bp == 0:
            continue
        si = next_idx + 1
        if si >= len(k):
            si = len(k) - 1
        sp = float(k[si].get('open', 0))
        if sp == 0:
            sp = bp
        ret += alloc * (sp - bp) / bp
    return ret


def metrics(rets, eq):
    n = len(rets)
    if n == 0:
        return {'sharpe': 0, 'total_return': 0, 'max_drawdown': 0}

    tr = eq[-1] - 1.0
    ny = n / 252.0
    ar = (1 + tr) ** (1 / max(ny, 0.01)) - 1
    sw = stdev(rets) if len(rets) > 1 else 0
    av = sw * math.sqrt(252)
    sh = (ar - 0.02) / av if av > 0 else 0

    peak = eq[0]
    mdd = 0.0
    for e in eq[1:]:
        if e > peak:
            peak = e
        dd = (peak - e) / peak if peak > 0 else 0
        if dd > mdd:
            mdd = dd

    cal = ar / mdd if mdd > 0 else 0
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r < 0]
    aw = mean(wins) if wins else 0
    al = abs(mean(losses)) if losses else 0
    pf = (len(wins) * aw) / (len(losses) * al) if (losses and al > 0) else 0

    return {
        'sharpe': round(sh, 3),
        'annual_return': round(ar * 100, 2),
        'max_drawdown': round(mdd * 100, 2),
        'calmar': round(cal, 3),
        'win_rate': round(len(wins) / max(n, 1) * 100, 1),
        'profit_factor': round(pf, 2),
        'n': n,
    }


def main():
    print('加载缓存评分 + 数据...')
    cached, all_data, dates = load_cache_and_data()
    print(f'  缓存: {len(cached)} 天, 行业: {len(all_data)}')

    print()
    header = f'{"工作日":<6} {"Sharpe":>7} {"年化%":>7} {"回撤%":>7} {"卡玛":>6} {"胜率":>5} {"盈亏比":>6} {"调仓":>4}'
    print(header)
    print('-' * len(header))

    results = []
    for wd in range(5):
        m = simulate(cached, all_data, dates, wd)
        results.append({'weekday': wd, **m})
        print(f'{WEEKDAY_NAMES[wd]:<6} {m["sharpe"]:>7.3f} {m["annual_return"]:>+6.1f} '
              f'{m["max_drawdown"]:>6.1f} {m["calmar"]:>6.3f} {m["win_rate"]:>5.1f} '
              f'{m["profit_factor"]:>6.2f} {m["n"]:>4}')

    best = max(results, key=lambda x: x['sharpe'])
    print(f'\n🏆 最优: {WEEKDAY_NAMES[best["weekday"]]}调仓 '
          f'(Sharpe={best["sharpe"]:.3f}, 年化={best["annual_return"]:+.1f}%)')
    print(f'当前默认: 周三计算+周四执行 (Sharpe={results[2]["sharpe"]:.3f})')

    # 各工作日与最优的差距
    for r in sorted(results, key=lambda x: -x['sharpe']):
        gap = (best['sharpe'] - r['sharpe']) / best['sharpe'] * 100
        print(f'  {WEEKDAY_NAMES[r["weekday"]]}: Sharpe={r["sharpe"]:.3f} '
              f'(距最优{gap:+.1f}%)')


if __name__ == '__main__':
    main()
