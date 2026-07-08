# -*- coding: utf-8 -*-
"""ETF → A股股票 持仓映射模块。

将行业ETF的调仓信号映射为具体的A股交易指令，
通过 etf_stock_mapping.json 配置文件完成代码→股票转换。

典型用法:
    from stock_mapper import StockMapper
    mapper = StockMapper()
    actions = mapper.map_rebalance_to_stocks(rebalance_plan)
"""

import json
import os
from datetime import date
from typing import Dict, List, Optional

# 映射文件位置（与模块同目录）
_MAPPING_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              'etf_stock_mapping.json')

# 行业→ETF代码的快速查找
try:
    from config import SECTOR_ETF_MAPPING
except ImportError:
    SECTOR_ETF_MAPPING = []

SECTOR_TO_ETF = {s[0]: s[2] for s in SECTOR_ETF_MAPPING}


class StockMapper:
    """ETF调仓方案 → 股票交易指令 的映射器。"""

    def __init__(self, mapping_path: str = None, top_n: int = 3):
        self.top_n = top_n
        self._mapping = {}
        self._load(mapping_path or _MAPPING_PATH)

    def _load(self, path: str):
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                self._mapping = json.load(f)

    @property
    def etf_count(self) -> int:
        """已加载的ETF映射数量。"""
        return len([k for k in self._mapping if not k.startswith('_')])

    @property
    def last_updated(self) -> str:
        """映射文件最后更新日期。"""
        meta = self._mapping.get('_meta', {})
        return meta.get('updated', 'unknown')

    def get_stocks(self, etf_code: str) -> List[dict]:
        """获取某ETF的前N大持仓股票。"""
        etf_info = self._mapping.get(etf_code, {})
        return etf_info.get('stocks', [])[:self.top_n]

    def map_rebalance_to_stocks(self,
                                 rebalance_plan: dict,
                                 top_n: int = None) -> dict:
        """将ETF调仓方案映射为股票级交易指令。

        Args:
            rebalance_plan: compute_rebalance() 返回的调仓方案
            top_n: 每个ETF取前N只股票（覆盖实例默认值）

        Returns:
            {
                'stock_actions': [
                    {'stock_code': '600036', 'stock_name': '招商银行',
                     'action': 'BUY', 'sector': '银行', ...},
                    ...
                ],
                'summary_html': str,
            }
        """
        n = top_n or self.top_n
        actions = rebalance_plan.get('actions', [])
        stock_actions = []

        for a in actions:
            act_type = a['action']
            sector = a['sector']
            etf_code = a.get('etf_code', SECTOR_TO_ETF.get(sector, ''))
            stocks = self.get_stocks(etf_code)

            if act_type == 'HOLD':
                continue

            if act_type == 'SELL':
                for stock in stocks[:n]:
                    stock_actions.append({
                        'stock_code': stock['code'],
                        'stock_name': stock.get('name', ''),
                        'action': 'SELL',
                        'sector': sector,
                        'reason': f'{sector}清仓: {a["reason"]}',
                    })

            if act_type == 'BUY':
                alloc = a.get('new_pct', 0)
                count = min(len(stocks), n)
                for stock in stocks[:n]:
                    stock_actions.append({
                        'stock_code': stock['code'],
                        'stock_name': stock.get('name', ''),
                        'action': 'BUY',
                        'sector': sector,
                        'allocation_pct': round(alloc / max(count, 1) * 100, 1),
                        'reason': f'{sector}开仓{alloc:.1%}: {a["reason"]}',
                    })

        return {
            'stock_actions': stock_actions,
            'summary_html': _build_summary_html(rebalance_plan),
        }


def _build_summary_html(plan: dict) -> str:
    """构建 mx-moni 发帖用的 HTML 摘要。"""
    lines = ['<h3>本周ETF趋势信号调仓总结</h3>']

    if plan.get('force_cash'):
        lines.append(
            f'<p><strong>强制空仓：</strong>{plan.get("force_cash_reason", "")}</p>'
        )
    else:
        pool = plan.get('target_pool', [])
        if pool:
            lines.append('<p><strong>候选池：</strong></p><ul>')
            for p in pool:
                lines.append(
                    f'<li>#{p["rank"]} {p["sector"]}（{p.get("etf_code","")}）: '
                    f'总分{p["score"]:+.0f}</li>'
                )
            lines.append('</ul>')

        for label, act_key in [('新开仓', 'BUY'), ('清仓', 'SELL')]:
            acts = [a for a in plan.get('actions', []) if a['action'] == act_key]
            if acts:
                lines.append(f'<p><strong>{label}：</strong></p><ul>')
                for a in acts:
                    pct = a.get('new_pct', a.get('old_pct', 0))
                    lines.append(f'<li>{a["sector"]}: {pct:.1%} — {a["reason"]}</li>')
                lines.append('</ul>')

    s = plan.get('summary', {})
    lines.append(
        f'<p>扫描{s.get("total_sectors_scanned", 0)}行业 | '
        f'HOLD {s.get("keep_sectors", 0)} | '
        f'SELL {s.get("sell_sectors", 0)} | '
        f'BUY {s.get("new_buys", 0)}</p>'
    )
    lines.append(
        '<p><strong>策略：</strong>通道突破 v2.1 | TOP3+55/30/35 | 数据源：通达信TQ-Local</p>'
    )
    lines.append(
        '<p><strong>风险提示：</strong>基于通道突破策略自动调仓，不构成投资建议。</p>'
    )
    return ''.join(lines)
