#!/usr/bin/env python3
"""
ETF周频调仓信号生成器 v1.0
================================
每周三收盘后计算信号，周四开盘执行。

=== 两部分架构 ===

Part 1 — 信号计算排序（可独立调用）
    scan_all.py → run_scan()
    输出：31行业ETF的信号评分、排序、Z-score

Part 2 — 调仓决策（可独立调用，也可整合Part 1）
    独立调用：
        python weekly_rebalance.py [--holdings <path>] [--dry-run]
        → 自动调用scan_all做信号计算 → 调仓决策 → 输出方案
    编程整合：
        from weekly_rebalance import compute_rebalance
        scan_results = run_scan()           # Part 1: 信号计算
        plan = compute_rebalance(scan_results, current_holdings)  # Part 2: 调仓决策

调仓规则（优化参数 v2）：
1. 全行业扫描 → 按总分降序排列
2. 选出 TOP3 且 总分>55 的行业作为候选池
3. 持仓处理（逐行业判定）：
   - 持仓行业在候选池内 → 继续持有（仓位不变）
   - 持仓行业不在候选池内：
       · 排名掉出TOP3 **且** 总分<30 → 清仓
       · 否则（只满足一个条件）→ 继续持有
4. 全市场最高分<35 → 强制空仓
5. 新开仓：候选池中非持仓行业，均分剩余仓位
6. 总仓位 = 100%

用法：
    python weekly_rebalance.py [--holdings <path>] [--output <dir>] [--dry-run]

holdings文件格式（JSON）：
    {"半导体": 0.25, "电子": 0.25, ...}   # 各行业持仓比例，和=1.0
"""
import sys, os, json
from datetime import date, datetime
from typing import Dict, List, Optional

# ── 路径自举 ──
SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
for p in [SKILL_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    from scripts.scan_all import run_scan
    from scripts.config import SECTOR_ETF_MAPPING, SECTOR_NAMES
    from scripts.mx_moni_client import (
        is_configured as _mx_ready, cancel_all, buy_market, sell_all_of,
        post_experience,
    )
    from scripts.stock_mapper import StockMapper
except ImportError:
    from scan_all import run_scan
    from config import SECTOR_ETF_MAPPING, SECTOR_NAMES
    from mx_moni_client import (
        is_configured as _mx_ready, cancel_all, buy_market, sell_all_of,
        post_experience,
    )
    from stock_mapper import StockMapper

# 导出符号
__all__ = [
    'compute_rebalance', 'load_holdings', 'save_holdings',
    'TOP_N', 'SCORE_ENTRY_THRESHOLD', 'SCORE_EXIT_THRESHOLD', 'FORCE_CASH_THRESHOLD',
    'SECTOR_TO_ETF',
]


# ══════════════════════════════════════════════════════════════
# 配置
# ══════════════════════════════════════════════════════════════
TOP_N = 3                  # 优化: 3 (网格搜索900组最优)
SCORE_ENTRY_THRESHOLD = 55  # 优化: 55 (网格搜索900组最优)
SCORE_EXIT_THRESHOLD = 30   # 优化: 30 (平原25~40,取中点)
FORCE_CASH_THRESHOLD = 35   # 优化: 35 (平原30~40,取中点)

# 行业→ETF代码快速查找
SECTOR_TO_ETF = {s[0]: s[2] for s in SECTOR_ETF_MAPPING}


# ══════════════════════════════════════════════════════════════
# 核心逻辑
# ══════════════════════════════════════════════════════════════

def compute_rebalance(scan_results: dict,
                       current_holdings: Dict[str, float] = None) -> dict:
    """计算周频调仓方案。

    Args:
        scan_results: run_scan() 的返回结果（含 all_ranked）
        current_holdings: 当前持仓 {行业名: 仓位比例}, 和=1.0, None=空仓

    Returns:
        {
            'date': str,
            'target_pool': [{'sector','score','etf_code'}, ...],    # 候选池
            'actions': [{'sector','action','reason','etf_code','old_pct','new_pct'}, ...],
            'final_positions': {sector: pct, ...},                   # 最终仓位, 和=1.0
            'summary': { ... }
        }
    """
    if current_holdings is None:
        current_holdings = {}

    today = date.today()
    today_str = today.strftime('%Y-%m-%d')

    # ── Step 1: 从扫描结果中提取多头信号排序 ──
    all_ranked = scan_results.get('all_ranked', [])
    if not all_ranked:
        # 回退：从 bull_signals 取
        all_ranked = scan_results.get('bull_signals', [])

    # 按总分降序排列，只取bull方向
    bull_sorted = sorted(
        [r for r in all_ranked if r.get('direction') == 'bull'],
        key=lambda x: x.get('total', 0),
        reverse=True
    )

    # ── Step 1.5: 强制空仓检测 ──
    # 如果所有多头信号的最高分都 < FORCE_CASH_THRESHOLD(40)，
    # 说明全市场信号极弱，应清空所有持仓，不做任何买入
    max_bull_score = max((r.get('total', 0) for r in bull_sorted), default=0)
    force_cash = max_bull_score < FORCE_CASH_THRESHOLD

    if force_cash:
        # 强制空仓：卖出所有持仓，不买入
        actions = []
        for sector, old_pct in current_holdings.items():
            if old_pct > 0:
                actions.append({
                    'sector': sector,
                    'etf_code': SECTOR_TO_ETF.get(sector, ''),
                    'action': 'SELL',
                    'reason': f'强制空仓：全市场最高分{max_bull_score:.0f}<{FORCE_CASH_THRESHOLD}，所有持仓清仓',
                    'old_pct': old_pct,
                    'new_pct': 0.0,
                })

        return {
            'date': today_str,
            'force_cash': True,
            'force_cash_reason': f'全市场所有多头信号总分<{FORCE_CASH_THRESHOLD}（最高={max_bull_score:.0f}），强制空仓',
            'target_pool': [],
            'actions': actions,
            'final_positions': {},
            'summary': {
                'date': today_str,
                'total_sectors_scanned': len(bull_sorted),
                'target_pool_size': 0,
                'held_sectors': len(current_holdings),
                'keep_sectors': 0,
                'sell_sectors': len(actions),
                'new_buys': 0,
                'final_positions_count': 0,
                'total_allocation': 0.0,
                'force_cash': True,
                'max_bull_score': max_bull_score,
            },
        }

    # ── Step 2: 构建候选池（TOP5 且 总分>50）──
    target_pool = []
    for i, r in enumerate(bull_sorted):
        if len(target_pool) >= TOP_N:
            break
        score = r.get('total', 0)
        if score > SCORE_ENTRY_THRESHOLD:
            target_pool.append({
                'rank': i + 1,
                'sector': r['sector'],
                'score': score,
                'etf_code': r.get('etf_code', ''),
                'price': r.get('price', 0),
                'change_pct': r.get('change_pct', 0),
            })

    target_sectors = {p['sector'] for p in target_pool}
    target_scores = {p['sector']: p['score'] for p in target_pool}

    # ── Step 3: 对每个当前持仓行业做判定 ──
    actions = []
    held_sectors = set(current_holdings.keys())  # 上周持仓
    to_keep = set()      # 继续持有的行业
    to_sell = set()      # 清仓的行业

    # 构建全行业分数映射（用于排名掉出判断）
    all_scores = {}
    for r in bull_sorted:
        all_scores[r['sector']] = r.get('total', 0)

    for sector in held_sectors:
        old_pct = current_holdings.get(sector, 0)
        in_target = sector in target_sectors
        current_score = all_scores.get(sector, 0)

        # 获取排名
        rank = next((i+1 for i, r in enumerate(bull_sorted) if r['sector'] == sector), 999)
        rank_out = rank > TOP_N

        if in_target:
            # 在候选池内 → 保持
            to_keep.add(sector)
            actions.append({
                'sector': sector,
                'etf_code': SECTOR_TO_ETF.get(sector, ''),
                'action': 'HOLD',
                'reason': f'在候选池(总分{current_score:.0f}, 排名#{rank})，继续持有',
                'old_pct': old_pct,
                'new_pct': old_pct,
            })
        else:
            # 不在候选池 → 检查是否清仓
            if rank_out and current_score < SCORE_EXIT_THRESHOLD:
                # 排名掉出TOP5 **且** 总分<40 → 清仓
                to_sell.add(sector)
                actions.append({
                    'sector': sector,
                    'etf_code': SECTOR_TO_ETF.get(sector, ''),
                    'action': 'SELL',
                    'reason': f'排名#{rank}(>5)且总分{current_score:.0f}(<40)，清仓',
                    'old_pct': old_pct,
                    'new_pct': 0.0,
                })
            else:
                # 只满足一个条件 → 继续持有
                to_keep.add(sector)
                reasons = []
                if rank_out:
                    reasons.append(f'排名#{rank}(>5)')
                if current_score < SCORE_EXIT_THRESHOLD:
                    reasons.append(f'总分{current_score:.0f}(<40)')
                actions.append({
                    'sector': sector,
                    'etf_code': SECTOR_TO_ETF.get(sector, ''),
                    'action': 'HOLD',
                    'reason': f'仅{"、".join(reasons)}，条件二不满足，继续持有',
                    'old_pct': old_pct,
                    'new_pct': old_pct,
                })

    # ── Step 4: 新开仓 ──
    new_buys = [p for p in target_pool if p['sector'] not in to_keep and p['sector'] not in to_sell]

    # ── Step 5: 仓位计算 ──
    # 已持有仓位总和
    kept_allocation = sum(current_holdings.get(s, 0) for s in to_keep)
    remaining = max(0.0, 1.0 - kept_allocation)

    if new_buys:
        alloc_per_new = round(remaining / len(new_buys), 4)
        for p in new_buys:
            actions.append({
                'sector': p['sector'],
                'etf_code': p['etf_code'],
                'action': 'BUY',
                'reason': f'候选池#{p["rank"]}(总分{p["score"]:.0f})，开仓{alloc_per_new:.1%}',
                'old_pct': 0.0,
                'new_pct': alloc_per_new,
            })
    elif remaining > 0.01 and not new_buys:
        # 有剩余仓位但没有新目标 → 按比例分配给持有行业
        pass  # 持有行业的仓位保持不变

    # ── Step 6: 组装最终仓位 ──
    final_positions = {}
    for a in actions:
        if a['new_pct'] > 0:
            final_positions[a['sector']] = round(a['new_pct'], 4)

    # 验证仓位和 ≈ 1.0
    total_pct = sum(final_positions.values())
    if abs(total_pct - 1.0) > 0.001:
        # 微调最后一笔
        if final_positions:
            last = list(final_positions.keys())[-1]
            final_positions[last] = round(final_positions[last] + (1.0 - total_pct), 4)

    # ── 统计摘要 ──
    summary = {
        'date': today_str,
        'total_sectors_scanned': len(bull_sorted),
        'target_pool_size': len(target_pool),
        'held_sectors': len(held_sectors),
        'keep_sectors': len(to_keep),
        'sell_sectors': len(to_sell),
        'new_buys': len(new_buys),
        'final_positions_count': len(final_positions),
        'total_allocation': round(sum(final_positions.values()), 4),
    }

    return {
        'date': today_str,
        'target_pool': target_pool,
        'actions': actions,
        'final_positions': final_positions,
        'summary': summary,
    }


# ══════════════════════════════════════════════════════════════
# 持仓状态管理
# ══════════════════════════════════════════════════════════════

DEFAULT_HOLDINGS_PATH = os.path.join(
    SKILL_DIR, '..', 'Reports', 'holdings_state.json'
)


def load_holdings(path: str = None) -> Dict[str, float]:
    """加载上周持仓状态。文件不存在返回空仓。"""
    path = path or DEFAULT_HOLDINGS_PATH
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get('positions', {})
    return {}


def save_holdings(positions: Dict[str, float], path: str = None):
    """保存持仓状态到文件。"""
    path = path or DEFAULT_HOLDINGS_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump({
            'date': str(date.today()),
            'positions': positions,
        }, f, ensure_ascii=False, indent=2)


LATEST_PLAN_PATH = os.path.join(SKILL_DIR, '..', 'Reports', 'latest_plan.json')


def save_latest_plan(plan_data: dict, report_dir: str = None):
    """保存调仓计划到 latest_plan.json（供周四 --execute 读取）。"""
    os.makedirs(os.path.dirname(LATEST_PLAN_PATH), exist_ok=True)
    with open(LATEST_PLAN_PATH, 'w', encoding='utf-8') as f:
        json.dump(plan_data, f, ensure_ascii=False, indent=2, default=str)

    # 同时保存归档副本
    if report_dir:
        os.makedirs(report_dir, exist_ok=True)
        archive = os.path.join(report_dir,
                               f'rebalance_{date.today().strftime("%Y%m%d")}.json')
        with open(archive, 'w', encoding='utf-8') as f:
            json.dump(plan_data, f, ensure_ascii=False, indent=2, default=str)


def load_latest_plan() -> dict:
    """加载最近一次保存的调仓计划（用于 --execute）。"""
    if os.path.exists(LATEST_PLAN_PATH):
        with open(LATEST_PLAN_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    raise FileNotFoundError(
        f'调仓计划不存在: {LATEST_PLAN_PATH}。请先运行 --calc-only 计算信号。')


# ══════════════════════════════════════════════════════════════
# CLI 入口
# ══════════════════════════════════════════════════════════════

def _print_rebalance_plan(plan: dict):
    """打印调仓方案的可读输出（CLI共有逻辑）。"""
    is_force_cash = plan.get('force_cash', False)
    if is_force_cash:
        max_s = plan['summary'].get('max_bull_score', 0)
        print(f'\n🔴 强制空仓：全市场最高分={max_s:.0f} < {FORCE_CASH_THRESHOLD}')
        return

    pool = plan.get('target_pool', [])
    if pool:
        print(f'\n🎯 候选池 (TOP{TOP_N}, 总分>{SCORE_ENTRY_THRESHOLD}):')
        for p in pool:
            print(f'  #{p["rank"]} {p["sector"]:<8} {p["score"]:>+5.0f}  {p["etf_code"]}')

    print(f'\n📌 操作:')
    for a in plan.get('actions', []):
        act = a['action']
        tag = '🟢' if act == 'BUY' else ('🔴' if act == 'SELL' else '🔄')
        if act == 'HOLD':
            print(f'  {tag} {a["sector"]:<8} HOLD  {a["new_pct"]:.1%}')
        elif act == 'BUY':
            print(f'  {tag} {a["sector"]:<8} BUY   {a["new_pct"]:.1%}')
        elif act == 'SELL':
            print(f'  {tag} {a["sector"]:<8} SELL  原{a["old_pct"]:.1%}')

    s = plan['summary']
    print(f'\n📈 扫描{s["total_sectors_scanned"]} → 候选{s["target_pool_size"]} | '
          f'HOLD{s["keep_sectors"]} SELL{s["sell_sectors"]} BUY{s["new_buys"]}')


def _run_calc_only(holdings_path: str, output_dir: str, dry_run: bool):
    """周三收盘后模式：计算信号+保存计划，不执行交易。"""
    print(f'{"="*60}')
    print(f'ETF周频调仓 — 周三收盘信号计算   {date.today()}')
    print(f'数据源: 通达信TQ-Local | 策略: 通道突破 v2.1')
    print(f'{"="*60}')

    current = load_holdings(holdings_path)
    print(f'\n[1] 持仓: {len(current)}个行业' + ('' if not current else ''))
    for s, p in sorted(current.items(), key=lambda x: -x[1]):
        print(f'    {s}: {p:.1%}')

    print(f'\n[2] 全行业扫描...')
    scan = run_scan()

    print(f'\n[3] 调仓计算...')
    plan = compute_rebalance(scan, current)

    # ETF→股票映射
    print(f'\n[4] ETF→股票映射...')
    mapper = StockMapper()
    mapped = mapper.map_rebalance_to_stocks(plan)
    stock_acts = mapped.get('stock_actions', [])
    buys = len([a for a in stock_acts if a['action'] == 'BUY'])
    sells = len([a for a in stock_acts if a['action'] == 'SELL'])
    print(f'    待执行（周四开盘）: BUY {buys}只 / SELL {sells}只')

    _print_rebalance_plan(plan)

    # 保存
    report_dir = os.path.join(SKILL_DIR, '..', 'Reports',
                              date.today().strftime('%Y-%m-%d'))
    pipeline_result = {
        'date': str(date.today()),
        'strategy': 'etf-trend-signal v2.1 通道突破',
        'data_source': '通达信TQ-Local',
        'top_signals': [
            {'sector': r['sector'], 'total': r['total'], 'grade': r['grade']}
            for r in scan.get('all_ranked', [])[:5]
        ],
        'rebalance': plan,
        'stock_actions': stock_acts,
        'summary_html': mapped.get('summary_html', ''),
        'execution_status': 'pending',
    }
    save_latest_plan(pipeline_result, report_dir)
    print(f'\n📋 调仓计划已保存: {os.path.relpath(LATEST_PLAN_PATH, SKILL_DIR)}')

    if not dry_run:
        save_holdings(plan['final_positions'], holdings_path)
        print(f'✅ 持仓已更新')


def _run_execute(dry_run: bool):
    """周四开盘模式：读取计划+执行交易。"""
    print(f'{"="*60}')
    print(f'ETF周频调仓 — 周四开盘执行   {date.today()}')
    print(f'执行模式: {"DRY-RUN" if dry_run else "LIVE"}')
    print(f'{"="*60}')

    if not dry_run and not _mx_ready():
        print('❌ MX_APIKEY 未配置，无法执行交易')
        sys.exit(1)

    plan_data = load_latest_plan()
    stock_actions = plan_data.get('stock_actions', [])
    summary_html = plan_data.get('summary_html', '')

    print(f'\n计划日期: {plan_data.get("date", "?")}')
    print(f'待执行: {len(stock_actions)} 笔交易')

    if not stock_actions:
        print('⚠ 无交易指令，跳过执行')
        return

    if dry_run:
        print('\n[DRY-RUN] 预览:')
        for a in stock_actions:
            print(f'  {a["action"]:>4} {a["stock_code"]} {a["stock_name"]}')
        return

    # ① 撤旧单
    print('\n[1] 撤销未成交委托...')
    r = cancel_all()
    print(f'    撤单: {r.get("message", r.get("code", ""))}')

    # ② 执行交易
    print(f'\n[2] 执行交易...')
    results = []
    for a in stock_actions:
        code = a['stock_code']
        name = a['stock_name']
        act = a['action']
        if act == 'BUY':
            r = buy_market(code, 100)
        else:
            r = sell_all_of(code)
        ok = r.get('code') in ('200', '0', 'skip')
        results.append({'code': code, 'name': name, 'action': act,
                        'ok': ok, 'msg': r.get('message', r.get('code', ''))})
        print(f'  {"✅" if ok else "❌"} {act} {code} {name}: '
              f'{r.get("message", r.get("code", ""))}')

    # ③ 发帖
    if summary_html and any(r['ok'] for r in results):
        print(f'\n[3] 发布经验交流帖...')
        pr = post_experience(summary_html)
        print(f'    发帖: {pr.get("message", pr.get("code", ""))}')

    # 保存执行结果
    plan_data['execution_status'] = 'executed'
    plan_data['trade_results'] = results
    report_dir = os.path.join(SKILL_DIR, '..', 'Reports',
                              plan_data.get('date', str(date.today())))
    save_latest_plan(plan_data, report_dir)
    print(f'\n✅ 执行完成')


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description='ETF周频调仓信号生成器 v2.0 — 周三收盘计算，周四开盘执行',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
模式:
  --calc-only    周三收盘后：计算信号+生成调仓计划（不执行交易）
  --execute      周四开盘：读取最新计划并执行交易
  （无参数）      全流程：计算+立即执行（手动调试用）

示例:
  %(prog)s --calc-only            # 周三收盘后运行
  %(prog)s --execute              # 周四开盘运行
  %(prog)s --calc-only --dry-run  # 周三预览
  %(prog)s --execute --dry-run    # 周四预览
        """)
    parser.add_argument('--calc-only', action='store_true',
                        help='仅计算信号（周三收盘后使用）')
    parser.add_argument('--execute', action='store_true',
                        help='仅执行交易（周四开盘使用）')
    parser.add_argument('--holdings', '-H', help='持仓JSON路径')
    parser.add_argument('--output', '-o', help='输出目录')
    parser.add_argument('--dry-run', action='store_true', help='仅预览')

    args = parser.parse_args()

    if args.calc_only and args.execute:
        print('❌ --calc-only 和 --execute 不能同时使用')
        sys.exit(1)

    holdings_path = args.holdings or DEFAULT_HOLDINGS_PATH
    output_dir = args.output or os.path.join(SKILL_DIR, '..', 'Reports',
                                             date.today().strftime('%Y-%m-%d'))

    # ── 模式分发 ──
    if args.calc_only:
        _run_calc_only(holdings_path, output_dir, args.dry_run)
    elif args.execute:
        _run_execute(args.dry_run)
    else:
        # ── 完整模式：计算 + 执行（周四盘前使用）──
        print(f'{"="*60}')
        print(f'ETF周频调仓 — {date.today()}')
        print(f'数据源: 通达信TQ-Local | 策略: 通道突破 v2.1')
        print(f'{"="*60}')

        current = load_holdings(holdings_path)
        print(f'\n[1] 持仓: {len(current)}个行业')
        for s, p in sorted(current.items(), key=lambda x: -x[1]):
            print(f'    {s}: {p:.1%}')

        print(f'\n[2] 全行业扫描...')
        scan = run_scan()

        print(f'\n[3] 调仓计算...')
        plan = compute_rebalance(scan, current)
        _print_rebalance_plan(plan)

        # ETF→股票映射
        print(f'\n[4] ETF→股票映射...')
        mapper = StockMapper()
        mapped = mapper.map_rebalance_to_stocks(plan)
        stock_acts = mapped.get('stock_actions', [])

        # 执行交易
        if stock_acts and not args.dry_run:
            if not _mx_ready():
                print('❌ MX_APIKEY 未配置，跳过交易执行')
            else:
                print(f'\n[5] 执行 mx-moni 交易 ({len(stock_acts)} 笔)...')
                cancel_all()
                results = []
                for a in stock_acts:
                    code = a['stock_code']
                    name = a['stock_name']
                    act = a['action']
                    r = buy_market(code, 100) if act == 'BUY' else sell_all_of(code)
                    ok = r.get('code') in ('200', '0', 'skip')
                    results.append({'code': code, 'name': name, 'action': act,
                                    'ok': ok, 'msg': r.get('message', r.get('code', ''))})
                    print(f'  {"✅" if ok else "❌"} {act} {code} {name}: '
                          f'{r.get("message", r.get("code", ""))}')

                if mapped.get('summary_html') and any(r['ok'] for r in results):
                    post_experience(mapped['summary_html'])
                    print(f'\n  已发布经验交流帖')
        elif args.dry_run and stock_acts:
            print(f'\n[5] [DRY-RUN] 待执行: {len(stock_acts)} 笔')
        else:
            print(f'\n[5] 无交易指令')

        # 保存
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir,
                                   f'rebalance_{date.today().strftime("%Y%m%d")}.json')
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(plan, f, ensure_ascii=False, indent=2, default=str)
        print(f'\n📊 调仓方案已保存: {output_path}')

        if not args.dry_run:
            save_holdings(plan['final_positions'], holdings_path)
            print(f'✅ 持仓已更新: {holdings_path}')


if __name__ == '__main__':
    main()
