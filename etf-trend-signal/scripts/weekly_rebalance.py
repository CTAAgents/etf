#!/usr/bin/env python3
"""
ETF周频调仓信号生成器 v1.0
================================
每周三收盘后计算信号，周四开盘执行。

调仓规则：
1. 全行业扫描 → 按总分降序排列
2. 选出 TOP5 且总分>50的行业作为候选池
3. 持仓处理（逐行业判定）：
   - 持仓行业在候选池内 → 继续持有（仓位不变）
   - 持仓行业不在候选池内：
       · 排名掉出TOP5 **且** 总分<40 → 清仓
       · 否则（只满足一个条件）→ 继续持有
4. 新开仓：候选池中非持仓行业，均分剩余仓位
5. 总仓位 = 100%

用法：
    python weekly_rebalance.py [--holdings <path>] [--output <dir>]

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
except ImportError:
    from scan_all import run_scan
    from config import SECTOR_ETF_MAPPING, SECTOR_NAMES


# ══════════════════════════════════════════════════════════════
# 配置
# ══════════════════════════════════════════════════════════════
TOP_N = 5                  # 选前N个行业
SCORE_ENTRY_THRESHOLD = 50  # 信号总分>50才进入候选池
SCORE_EXIT_THRESHOLD = 40   # 掉出TOP5+总分<40才清仓

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


# ══════════════════════════════════════════════════════════════
# CLI 入口
# ══════════════════════════════════════════════════════════════

def main():
    import argparse
    parser = argparse.ArgumentParser(
        description='ETF周频调仓信号生成器 v1.0 — 每周三收盘计算，周四开盘执行')
    parser.add_argument('--holdings', '-H', help='持仓状态JSON路径（默认Reports/holdings_state.json）')
    parser.add_argument('--output', '-o', help='输出目录（默认Reports）')
    parser.add_argument('--dry-run', action='store_true', help='仅预览，不写入持仓文件')
    args = parser.parse_args()

    holdings_path = args.holdings or DEFAULT_HOLDINGS_PATH
    output_dir = args.output or os.path.join(SKILL_DIR, '..', 'Reports',
                                             date.today().strftime('%Y-%m-%d'))

    print(f'{"="*60}')
    print(f'ETF周频调仓信号生成 — {date.today()}')
    print(f'持仓文件: {holdings_path}')
    print(f'输出目录: {output_dir}')
    print(f'{"="*60}')

    # Step 1: 加载上周持仓
    current = load_holdings(holdings_path)
    if current:
        print(f'\n[1] 上周持仓 ({len(current)}个行业):')
        for s, p in sorted(current.items(), key=lambda x: -x[1]):
            print(f'    {s}: {p:.1%}')
    else:
        print('\n[1] 上周持仓: 空仓')

    # Step 2: 执行全行业扫描
    print(f'\n[2] 全行业扫描...')
    scan_output_dir = output_dir if args.output else None
    scan_results = run_scan(output_dir=scan_output_dir, output_prefix='weekly_scan')

    total_bull = len(scan_results.get('bull_signals', scan_results.get('all_ranked', [])))
    print(f'    多头信号: {total_bull}个')

    # Step 3: 计算调仓方案
    print(f'\n[3] 调仓计算...')
    plan = compute_rebalance(scan_results, current)

    # Step 4: 输出调仓方案
    print(f'\n{"="*60}')
    print(f'📋 调仓方案')
    print(f'{"="*60}')

    # 候选池
    if plan['target_pool']:
        print(f'\n🎯 候选池 (TOP{TOP_N} 且 总分>{SCORE_ENTRY_THRESHOLD}):')
        print(f'  {"#":>3} {"行业":<8} {"总分":>6} {"代码":>10} {"价格":>8} {"涨跌":>6}')
        print(f'  {"---":>3} {"------":<8} {"------":>6} {"----------":>10} {"--------":>8} {"------":>6}')
        for p in plan['target_pool']:
            chg = p.get('change_pct', 0)
            chg_str = f'{chg:+.1f}%' if chg else 'N/A'
            print(f'  #{p["rank"]:>2} {p["sector"]:<8} {p["score"]:>+5.0f} {p["etf_code"]:>10} {p.get("price",0):>8.2f} {chg_str:>6}')
    else:
        print(f'\n⚠️ 候选池为空：无行业同时满足 TOP{TOP_N} + 总分>{SCORE_ENTRY_THRESHOLD}')

    # 操作明细
    print(f'\n📌 操作明细:')
    for a in plan['actions']:
        act = a['action']
        sec = a['sector']
        if act == 'HOLD':
            print(f'  🔄 {sec:<8} HOLD  {a["new_pct"]:.1%} (保持不变)')
            print(f'      理由: {a["reason"]}')
        elif act == 'BUY':
            print(f'  🟢 {sec:<8} BUY   {a["new_pct"]:.1%}')
            print(f'      理由: {a["reason"]}')
        elif act == 'SELL':
            print(f'  🔴 {sec:<8} SELL  (原{a["old_pct"]:.1%})')
            print(f'      理由: {a["reason"]}')

    # 最终仓位
    if plan['final_positions']:
        print(f'\n📊 最终仓位 (总和={sum(plan["final_positions"].values()):.1%}):')
        print(f'  {"行业":<8} {"仓位":>8}')
        print(f'  {"------":<8} {"------":>8}')
        for s, p in sorted(plan['final_positions'].items(), key=lambda x: -x[1]):
            print(f'  {s:<8} {p:.1%}')
    else:
        print(f'\n⚠️ 最终仓位为空')

    # 统计
    s = plan['summary']
    print(f'\n📈 统计: 扫描{s["total_sectors_scanned"]}行业 | '
          f'候选池{s["target_pool_size"]}个 | '
          f'HOLD{s["keep_sectors"]}个 | '
          f'SELL{s["sell_sectors"]}个 | '
          f'BUY{s["new_buys"]}个')

    # Step 5: 保存
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f'rebalance_{date.today().strftime("%Y%m%d")}.json')
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(plan, f, ensure_ascii=False, indent=2, default=str)
    print(f'\n📊 调仓方案已保存: {output_path}')

    # 非dry-run时更新持仓状态
    if not args.dry_run:
        save_holdings(plan['final_positions'], holdings_path)
        print(f'✅ 持仓状态已更新: {holdings_path}')


if __name__ == '__main__':
    main()
