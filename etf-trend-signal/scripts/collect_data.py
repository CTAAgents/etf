# -*- coding: utf-8 -*-
"""
ETF数据采集脚本（单一数据源：通达信TQ-Local HTTP）。

仅通过通达信本地客户端的 JSON-RPC HTTP 接口获取数据。
不使用任何第三方库（akshare / tqsdk / requests）。

核心数据接口：
  - ETF日K线:  get_market_data(period="1d", dividend_type="qfq")
  - ETF实时快照: get_market_snapshot() → Jjjz (基金净值=IOPV)
  - ETF溢价率:   get_more_info(field_list=["More_YJL"])
  - ETF基础信息: get_stock_info() → underly_code (跟踪指数)
  - 市场融资融券: get_scjy_value(field_list=["SC01"])
  - 陆股通资金:   get_scjy_value(field_list=["SC02"])
  - ETF基金规模:  get_scjy_value(field_list=["SC08"])

用法:
    python -m scripts.collect_data [--output-dir DIR]
"""

import argparse
import json
import os
import sys
import urllib.request
import urllib.error
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional

try:
    from config import SECTOR_ETF_MAPPING, SECTOR_NAMES, TDX_CONFIG
except ImportError:
    from scripts.config import SECTOR_ETF_MAPPING, SECTOR_NAMES, TDX_CONFIG


# ============================================================
# 通达信 TQ-Local HTTP 客户端（唯一数据源）
# ============================================================

class TdxCollector:
    """通达信TQ-Local HTTP数据采集器。

    通过 JSON-RPC 向本地通达信客户端（http://127.0.0.1:17709/）发送请求。
    仅依赖 Python 标准库 urllib。
    """

    def __init__(self, base_url: str = None, timeout: int = None):
        cfg = TDX_CONFIG
        self.base_url = base_url or cfg['base_url']
        self.timeout = timeout or cfg['timeout']
        self.days_history = cfg['days_history']
        self._available = self._check_connectivity()

    def _check_connectivity(self) -> bool:
        """检查通达信HTTP服务是否可用。"""
        try:
            result = self._call('get_match_stkinfo', {'key_word': '茅台'})
            return result is not None
        except Exception:
            self._available = False
            return False

    @property
    def available(self) -> bool:
        return self._available

    def _call(self, method: str, params: dict = None) -> dict:
        """发送 JSON-RPC 请求到 TQ-Local。"""
        if params is None:
            params = {}
        payload = {
            "id": 1,
            "method": method,
            "params": params,
        }
        req = urllib.request.Request(
            self.base_url,
            data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                result = json.loads(resp.read().decode('utf-8'))
        except Exception:
            return {}
        if 'error' in result:
            return {}
        return result.get('result', {})

    def _fmt_code(self, etf_code: str) -> str:
        """将ETF代码转换为TDX格式（如 512480.SH）。"""
        code = etf_code.replace('.SH', '').replace('.SZ', '')
        if code.startswith(('6', '5', '51')):
            return f"{code}.SH"
        elif code.startswith(('0', '1', '159')):
            return f"{code}.SZ"
        return etf_code

    # ── 核心数据 ──

    def get_etf_kline(self, etf_code: str, count: int = None) -> List[dict]:
        """获取ETF日K线数据。

        Args:
            etf_code: ETF代码（如 512480.SH）
            count: 获取K线条数，默认使用 config 设定

        Returns:
            [{'date','open','high','low','close','volume','amount'}, ...]
        """
        if count is None:
            count = self.days_history
        full_code = self._fmt_code(etf_code)
        result = self._call('get_market_data', {
            'stock_list': [full_code],
            'count': count,
            'dividend_type': 'qfq',
            'period': '1d',
        })

        raw = result.get('Value', result)
        klines = raw.get(full_code, raw) if isinstance(raw, dict) else raw

        if not isinstance(klines, list) or len(klines) < 2:
            return []

        parsed = []
        for k in klines:
            try:
                parsed.append({
                    'date': str(k.get('Date', '')),
                    'open': float(k.get('Open', 0) or 0),
                    'high': float(k.get('High', 0) or 0),
                    'low': float(k.get('Low', 0) or 0),
                    'close': float(k.get('Close', 0) or 0),
                    'volume': float(k.get('Volume', 0) or 0) * 100,  # 手→股
                    'amount': float(k.get('Amount', 0) or 0) * 10000,  # 万元→元
                })
            except (ValueError, TypeError, KeyError):
                continue
        return parsed

    def get_market_snapshot(self, etf_code: str) -> dict:
        """获取ETF实时行情快照（含基金净值 Jjjz = IOPV）。"""
        full_code = self._fmt_code(etf_code)
        result = self._call('get_market_snapshot', {'stock_code': full_code})
        val = result.get('Value', result)
        if not isinstance(val, dict):
            return {}
        iopv = float(val.get('Jjjz', 0) or 0)
        now = float(val.get('Now', 0) or 0)
        premium = (now / iopv - 1) * 100 if iopv > 0 else 0
        return {
            'price': now,
            'open': float(val.get('Open', 0) or 0),
            'high': float(val.get('Max', 0) or 0),
            'low': float(val.get('Min', 0) or 0),
            'volume': float(val.get('Volume', 0) or 0),
            'amount': float(val.get('Amount', 0) or 0),
            'iopv': iopv,
            'pre_close': float(val.get('LastClose', 0) or 0),
            'premium_pct': round(premium, 2),
        }

    def get_etf_premium(self, etf_code: str) -> float:
        """获取ETF最新溢价率（More_YJL字段）。"""
        full_code = self._fmt_code(etf_code)
        result = self._call('get_more_info', {
            'stock_code': full_code,
            'field_list': ['More_YJL'],
        })
        val = result.get('Value', result)
        if isinstance(val, dict):
            raw = val.get('More_YJL', '0')
            try:
                return float(raw) if raw else 0.0
            except (ValueError, TypeError):
                return 0.0
        return 0.0

    # ── 市场统计 ──

    def get_market_data(self) -> dict:
        """获取全市场ETF/融资/北向数据（一次调用聚合）。"""
        # 融资融券 (SC01)
        margin = {}
        r1 = self._call('get_scjy_value', {'field_list': ['SC01']})
        v1 = r1.get('Value', r1.get('SC01', {}))
        if isinstance(v1, dict):
            margin = {
                'margin_balance': float(v1.get('SC01_1', 0) or 0),
                'short_balance': float(v1.get('SC01_2', 0) or 0),
            }

        # 北向资金 (SC02)
        northbound = {}
        r2 = self._call('get_scjy_value', {'field_list': ['SC02']})
        v2 = r2.get('Value', r2.get('SC02', {}))
        if isinstance(v2, dict):
            northbound = {
                'sh_inflow': float(v2.get('SC02_1', 0) or 0),
                'sz_inflow': float(v2.get('SC02_2', 0) or 0),
            }

        # ETF基金规模 (SC08)
        scale = {}
        r3 = self._call('get_scjy_value', {'field_list': ['SC08']})
        v3 = r3.get('Value', r3.get('SC08', {}))
        if isinstance(v3, dict):
            scale = {
                'total_scale': float(v3.get('SC08_1', 0) or 0),     # 规模(亿份)
                'net_subscribe': float(v3.get('SC08_2', 0) or 0),    # 净申赎(亿份)
            }

        return {'margin': margin, 'northbound': northbound, 'scale': scale}

    def get_benchmark_kline(self, count: int = 60) -> List[dict]:
        """获取沪深300指数日K线。"""
        return self.get_etf_kline('000300.SH', count=count)

    def get_stock_info(self, etf_code: str) -> dict:
        """获取ETF基础信息（名称、跟踪指数、是否两融/港股通）。"""
        full_code = self._fmt_code(etf_code)
        result = self._call('get_stock_info', {'stock_code': full_code})
        val = result.get('Value', result)
        if not isinstance(val, dict):
            return {}
        return {
            'name': val.get('Name', ''),
            'underly_code': val.get('underly_code', ''),
            'marginable': str(val.get('BelongRZRQ', '0')) == '1',
            'hgt': str(val.get('BelongHSGT', '0')) == '1',
        }


# ============================================================
# ETF数据采集器（纯TDX）
# ============================================================

class EtfDataCollector:
    """ETF数据采集器（纯通达信TQ-Local，无降级）。"""

    def __init__(self):
        self.tdx = TdxCollector()
        if self.tdx.available:
            print(f"  [数据源] 通达信TQ-Local ✅ 已连接 ({self.tdx.base_url})")
        else:
            raise RuntimeError(
                "通达信TQ-Local 不可用。请确保：\n"
                "  1. 通达信客户端已安装并运行\n"
                "  2. TQ-Local HTTP服务已启动（默认端口17709）\n"
                "  3. 火绒/360等安全软件未拦截端口\n"
                "  可通过浏览器访问 http://127.0.0.1:17709/ 测试"
            )

    def get_etf_klines(self, sector_name: str, etf_code: str, days: int = 180) -> List[dict]:
        """获取ETF日K线（纯TDX）。"""
        return self.tdx.get_etf_kline(etf_code, count=days)

    def get_etf_premium(self, etf_code: str) -> dict:
        """获取ETF溢价率。"""
        # 优先用快照的Jjjz精确计算
        snap = self.tdx.get_market_snapshot(etf_code)
        premium = snap.get('premium_pct', 0)
        # 再用More_YJL接口验证
        more_yjl = self.tdx.get_etf_premium(etf_code)
        # 取差异小于2%的数据，否则取快照数据
        if abs(premium - more_yjl) > 2.0 and abs(more_yjl) > 0:
            premium = more_yjl
        return {'premium_pct': round(premium, 2), 'source': 'tdx'}

    def get_market_data(self) -> dict:
        """获取全市场融资/北向/规模数据。"""
        return self.tdx.get_market_data()

    def get_northbound_signal(self, sector_name: str) -> dict:
        """获取北向资金信号（行业权重估算）。

        通达信SC02给出全市场沪股通+深股通每日净流入。
        行业级北向通过ETF跟踪指数的成分股北向持仓比例估算。
        """
        md = self.get_market_data()
        nb = md.get('northbound', {})
        total_inflow = nb.get('sh_inflow', 0) + nb.get('sz_inflow', 0)

        # 行业权重估算：基于该行业占全市场ETF市值的比例
        # 金融/科技类北向权重高，基建/农业权重低
        sector_weight_map = {
            '银行': 0.08, '非银金融': 0.05, '证券': 0.04, '保险': 0.03, '房地产': 0.02,
            '食品饮料': 0.10, '白酒': 0.08, '医药生物': 0.06, '医疗器械': 0.03,
            '家用电器': 0.04, '商贸零售': 0.01,
            '半导体': 0.06, '芯片': 0.04, '电子': 0.05, '计算机': 0.04, '通信': 0.02,
            '传媒': 0.02, '游戏': 0.01,
            '新能源汽车': 0.06, '光伏': 0.04, '军工': 0.03, '机械设备': 0.03, '电力设备': 0.04,
            '有色金属': 0.04, '钢铁': 0.02, '煤炭': 0.02, '化工': 0.03, '石油石化': 0.03,
            '建筑装饰': 0.01, '交通运输': 0.02, '公用事业': 0.02,
            '农林牧渔': 0.01,
        }
        weight = sector_weight_map.get(sector_name, 0.03)
        est_5d = total_inflow * weight * 5
        est_20d = total_inflow * weight * 20

        return {
            'net_inflow_5d': round(est_5d, 1),
            'net_inflow_20d': round(est_20d, 1),
            'direction': 'positive' if total_inflow > 0 else 'negative',
            'data_source': 'tdx_sc02_estimated',
        }

    def get_benchmark_return(self) -> float:
        """计算沪深300近60日收益率。"""
        klines = self.tdx.get_benchmark_kline(count=60)
        if len(klines) >= 2:
            return klines[-1]['close'] / klines[0]['close'] - 1
        return 0

    def get_benchmark_closes(self) -> List[float]:
        """获取沪深300近120日收盘价序列（用于行业相对强度计算）。"""
        klines = self.tdx.get_benchmark_kline(count=120)
        return [k['close'] for k in klines]


# ============================================================
# 采集所有ETF数据
# ============================================================

def collect_etf_data(sector_name: str, etf_code: str, collector: EtfDataCollector,
                     days: int = 180) -> dict:
    """采集单个ETF的完整数据（纯TDX）。"""
    klines = collector.get_etf_klines(sector_name, etf_code, days)
    if not klines or len(klines) < 50:
        return {}

    last = klines[-1]
    prev = klines[-2] if len(klines) > 1 else last
    change_pct = round((last['close'] / prev['close'] - 1) * 100, 2) if prev['close'] > 0 else 0

    premium_data = collector.get_etf_premium(etf_code)
    northbound = collector.get_northbound_signal(sector_name)

    result = {
        'sector': sector_name,
        'etf_code': etf_code,
        'last_price': last['close'],
        'change_pct': change_pct,
        'klines': klines,
        # 通达信不提供ETF日频份额历史，用市场级规模数据替代
        'share_market_scale': {},
        'premium_data': premium_data,
        'northbound': northbound,
        # 融资数据使用全市场数据
        'margin': collector.get_market_data().get('margin', {}),
        'scale': collector.get_market_data().get('scale', {}),
        'data_source': 'tdx',
        'timestamp': datetime.now().isoformat(),
    }
    return result


def collect_all_etfs(days: int = 180) -> List[dict]:
    """采集所有行业ETF的数据（纯TDX）。"""
    print(f"\n{'='*60}")
    print(f"行业ETF数据采集（纯通达信TQ-Local）- {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}\n")

    collector = EtfDataCollector()
    results = []
    total = len(SECTOR_ETF_MAPPING)

    for i, (sector_name, _, etf_code, etf_name, _) in enumerate(SECTOR_ETF_MAPPING):
        print(f"[{i+1}/{total}] {sector_name} ({etf_code})...", end=' ', flush=True)
        data = collect_etf_data(sector_name, etf_code, collector, days)
        if data and data.get('klines') and len(data['klines']) >= 50:
            results.append(data)
            n = len(data['klines'])
            print(f"OK ({n}根K线, 价格={data['last_price']:.2f}, "
                  f"溢价={data['premium_data'].get('premium_pct',0):.2f}%)")
        else:
            print("SKIP (数据不足)")
        time.sleep(0.1)

    print(f"\n采集完成: {len(results)}/{total} | 数据源: tdx")
    return results


def save_etf_data(etf_data: List[dict], output_dir: str) -> str:
    """保存数据到JSON。"""
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, 'etf_market_data.json')
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(etf_data, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n数据已保存: {output_path}")
    return output_path


# ============================================================
# 主入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(description='行业ETF数据采集（纯通达信TQ-Local）')
    parser.add_argument('--output-dir', default=None, help='输出目录')
    parser.add_argument('--days', type=int, default=180, help='历史K线天数')
    args = parser.parse_args()

    skill_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    output_dir = args.output_dir or os.path.join(skill_dir, 'data')

    etf_data = collect_all_etfs(days=args.days)
    if etf_data:
        save_etf_data(etf_data, output_dir)
    return etf_data


if __name__ == '__main__':
    main()
