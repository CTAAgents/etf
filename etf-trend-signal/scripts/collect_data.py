# -*- coding: utf-8 -*-
"""
ETF数据采集脚本 v2.3 — 双数据源（腾讯自选股为主，通达信TQ-Local为备）。

默认数据源：腾讯自选股 westock-mcp（前复权日线，通过JSON缓存文件加载）。
备选数据源：通达信TQ-Local HTTP（--source tdx）。
缓存机制：MCP预取 → JSON文件 → scan_all.py读取，避免Python脚本直接调MCP的局限。

核心数据接口：
  - ETF日K线:  westock data_kline(fq="qfq") 或 TDX get_market_data(dividend_type="qfq")
  - ETF溢价率:   TDX get_more_info(field_list=["More_YJL"])
  - 市场融资数据: TDX get_scjy_value(field_list=["SC01","SC02","SC08"])

缓存文件路径：~/.workbuddy/cache/etf_westock_data.json
刷新缓存: 通过 WorkBuddy MCP 调用 westock-mcp data_kline 写入该文件

用法:
    python -m scripts.collect_data [--source westock|tdx] [--cache <path>]
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

# ── 缓存文件默认路径 ──
DEFAULT_CACHE_PATH = os.path.join(os.path.expanduser('~'), '.workbuddy', 'cache', 'etf_westock_data.json')


# ============================================================
# 代码格式转换
# ============================================================

def etf_to_westock(etf_code: str) -> str:
    """512480.SH → sh512480, 159995.SZ → sz159995"""
    parts = etf_code.split('.')
    return f"{parts[1].lower()}{parts[0]}"


def westock_to_etf(wcode: str) -> str:
    """sh512480 → 512480.SH, sz159995 → 159995.SZ"""
    return f"{wcode[2:]}.{wcode[:2].upper()}"


# ============================================================
# 腾讯自选股数据采集器（JSON缓存 → 标准OHLCV格式）
# ============================================================

class WestockCollector:
    """腾讯自选股数据采集器 — 从JSON缓存文件加载K线数据。

    缓存文件格式（由 westock-mcp data_kline 批量请求产出）:
        {"ok":true, "data":{"data":[{"symbol":"sh512480","data":{"nodes":[...]}},...]}}

    或简化格式:
        {"512480.SH": [{"date":"...","open":...,"high":...,"low":...,"close":...,"volume":...,"amount":...}, ...], ...}
    """

    def __init__(self, cache_path: str = None):
        self.cache_path = cache_path or DEFAULT_CACHE_PATH
        self._klines_cache = {}
        self._available = False
        self._load_cache()

    def _load_cache(self):
        """加载缓存文件，自动识别两种格式。"""
        if not os.path.exists(self.cache_path):
            self._available = False
            return

        try:
            with open(self.cache_path, 'r', encoding='utf-8') as f:
                raw = json.load(f)
        except Exception:
            self._available = False
            return

        # 格式A: westock-mcp 原生格式 {"ok":true, "data":{"data":[...]}}
        if raw.get('ok') and 'data' in raw:
            items = raw['data'].get('data', [])
            if items:
                for item in items:
                    symbol = item.get('symbol', '')
                    nodes = item.get('data', {}).get('nodes', [])
                    if symbol and nodes:
                        etf_code = westock_to_etf(symbol)
                        self._klines_cache[etf_code] = self._parse_westock_nodes(nodes)
                self._available = len(self._klines_cache) > 0
                return

        # 格式B: 简化格式 {"512480.SH": [{...}]}
        if isinstance(raw, dict) and all(isinstance(v, list) for v in raw.values()):
            self._klines_cache = raw
            self._available = len(self._klines_cache) > 0
            return

        self._available = False

    def _parse_westock_nodes(self, nodes: List[dict]) -> List[dict]:
        """将westock节点转换为标准OHLCV格式（日期升序）。"""
        klines = []
        for node in nodes:
            try:
                klines.append({
                    'date': str(node.get('date', '')),
                    'open': float(node.get('open', 0)),
                    'high': float(node.get('high', 0)),
                    'low': float(node.get('low', 0)),
                    'close': float(node.get('last', 0)),
                    'volume': float(node.get('volume', 0)),
                    'amount': float(node.get('amount', 0)),
                })
            except (ValueError, TypeError):
                continue
        klines.sort(key=lambda x: x['date'])
        return klines

    @property
    def available(self) -> bool:
        return self._available

    def get_etf_kline(self, etf_code: str, count: int = 180) -> List[dict]:
        """获取ETF日K线（前复权）。"""
        klines = self._klines_cache.get(etf_code, [])
        if klines and len(klines) > count:
            return klines[-count:]
        return klines

    def get_benchmark_kline(self, count: int = 120) -> List[dict]:
        """获取沪深300日K线。"""
        klines = self._klines_cache.get('000300.SH', [])
        if klines and len(klines) > count:
            return klines[-count:]
        return klines

    def get_benchmark_closes(self, count: int = 120) -> List[float]:
        """获取沪深300近N日收盘价序列。"""
        klines = self.get_benchmark_kline(count)
        return [k['close'] for k in klines]


# ============================================================
# 通达信 TQ-Local HTTP 客户端（保留作为备选）
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
        if params is None:
            params = {}
        payload = {"id": 1, "method": method, "params": params}
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
        code = etf_code.replace('.SH', '').replace('.SZ', '')
        if code.startswith(('6', '5', '51')):
            return f"{code}.SH"
        elif code.startswith(('0', '1', '159')):
            return f"{code}.SZ"
        return etf_code

    def get_etf_kline(self, etf_code: str, count: int = None) -> List[dict]:
        if count is None:
            count = self.days_history
        full_code = self._fmt_code(etf_code)
        result = self._call('get_market_data', {
            'stock_list': [full_code],
            'count': count,
            'dividend_type': TDX_CONFIG['dividend_type'],
            'period': '1d',
        })

        raw = result.get('Value', result)
        col_data = raw.get(full_code, raw) if isinstance(raw, dict) else raw

        if not isinstance(col_data, dict) or 'Date' not in col_data:
            return []

        dates = col_data.get('Date', [])
        if not isinstance(dates, list) or len(dates) < 2:
            return []

        opens = col_data.get('Open', [])
        highs = col_data.get('High', [])
        lows = col_data.get('Low', [])
        closes = col_data.get('Close', [])
        volumes = col_data.get('Volume', [])
        amounts = col_data.get('Amount', [])

        n = min(len(dates), len(opens), len(highs), len(lows), len(closes))
        parsed = []
        for i in range(n):
            try:
                parsed.append({
                    'date': str(dates[i]),
                    'open': float(opens[i] or 0),
                    'high': float(highs[i] or 0),
                    'low': float(lows[i] or 0),
                    'close': float(closes[i] or 0),
                    'volume': float(volumes[i] or 0) if i < len(volumes) else 0,
                    'amount': float(amounts[i] or 0) * 10000 if i < len(amounts) else 0,
                })
            except (ValueError, TypeError):
                continue
        return parsed

    def get_market_data(self) -> dict:
        margin = {}
        r1 = self._call('get_scjy_value', {'field_list': ['SC01']})
        v1 = r1.get('Value', r1.get('SC01', {}))
        if isinstance(v1, dict):
            margin = {
                'margin_balance': float(v1.get('SC01_1', 0) or 0),
                'short_balance': float(v1.get('SC01_2', 0) or 0),
            }
        return {'margin': margin}

    def get_benchmark_kline(self, count: int = 120) -> List[dict]:
        return self.get_etf_kline('000300.SH', count=count)

    def get_benchmark_closes(self, count: int = 120) -> List[float]:
        klines = self.get_benchmark_kline(count)
        return [k['close'] for k in klines]


# ============================================================
# ETF数据采集器（统一入口，双源调度）
# ============================================================

class EtfDataCollector:
    """ETF数据采集器 — 默认腾讯自选股，--source tdx 切换通达信。"""

    def __init__(self, source: str = 'westock', cache_path: str = None):
        self.source = source
        if source == 'tdx':
            self._collector = TdxCollector()
            if not self._collector.available:
                raise RuntimeError(
                    "通达信TQ-Local 不可用。请确保：\n"
                    "  1. 通达信客户端已安装并运行\n"
                    "  2. TQ-Local HTTP服务已启动（默认端口17709）"
                )
            print(f"  [数据源] 通达信TQ-Local ✅ ({self._collector.base_url})")
        else:
            self._collector = WestockCollector(cache_path=cache_path)
            if not self._collector.available:
                raise RuntimeError(
                    "腾讯自选股数据缓存不可用。请先通过 WorkBuddy MCP 刷新缓存：\n"
                    f"  缓存路径: {cache_path or DEFAULT_CACHE_PATH}\n"
                    "  提示：在 WorkBuddy 中运行 /etf-trend-signal 自动刷新缓存"
                )
            cnt = len(self._collector._klines_cache)
            print(f"  [数据源] 腾讯自选股 westock-mcp ✅ ({cnt}个标的前复权日线)")

    def get_etf_klines(self, sector_name: str, etf_code: str, days: int = 180) -> List[dict]:
        return self._collector.get_etf_kline(etf_code, count=days)

    def get_benchmark_closes(self, count: int = 120) -> List[float]:
        return self._collector.get_benchmark_closes(count)


# ============================================================
# 缓存管理
# ============================================================

def save_westock_cache(raw_mcp_data: dict, cache_path: str = None):
    """将 westock-mcp 原始返回数据写入缓存文件。
    
    供 MCP 预取流程使用：DeferExecuteTool → 保存到缓存 → scan_all.py 读取。
    """
    cache_path = cache_path or DEFAULT_CACHE_PATH
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    with open(cache_path, 'w', encoding='utf-8') as f:
        json.dump(raw_mcp_data, f, ensure_ascii=False)
    print(f"✅ 缓存已写入: {cache_path}")


# ============================================================
# 采集所有ETF数据
# ============================================================

def collect_etf_data(sector_name: str, etf_code: str, collector: EtfDataCollector,
                     days: int = 180) -> dict:
    """采集单个ETF的完整数据。"""
    klines = collector.get_etf_klines(sector_name, etf_code, days)
    if not klines or len(klines) < 50:
        return {}

    last = klines[-1]
    prev = klines[-2] if len(klines) > 1 else last
    change_pct = round((last['close'] / prev['close'] - 1) * 100, 2) if prev['close'] > 0 else 0

    return {
        'sector': sector_name,
        'etf_code': etf_code,
        'last_price': last['close'],
        'change_pct': change_pct,
        'klines': klines,
        'data_source': collector.source,
        'timestamp': datetime.now().isoformat(),
    }


def collect_all_etfs(days: int = 180, source: str = 'westock',
                     cache_path: str = None) -> List[dict]:
    """采集所有行业ETF的数据。"""
    print(f"\n{'='*60}")
    print(f"行业ETF数据采集（{source}）- {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}\n")

    collector = EtfDataCollector(source=source, cache_path=cache_path)
    results = []
    total = len(SECTOR_ETF_MAPPING)

    for i, (sector_name, _, etf_code, etf_name, _) in enumerate(SECTOR_ETF_MAPPING):
        print(f"[{i+1}/{total}] {sector_name} ({etf_code})...", end=' ', flush=True)
        data = collect_etf_data(sector_name, etf_code, collector, days)
        if data and data.get('klines') and len(data['klines']) >= 50:
            results.append(data)
            n = len(data['klines'])
            print(f"OK ({n}根, 价格={data['last_price']:.2f})")
        else:
            klen = len(data['klines']) if data and data.get('klines') else 0
            print(f"SKIP (K线不足, {klen}根)")
        time.sleep(0.05)

    print(f"\n采集完成: {len(results)}/{total} | 数据源: {source}")
    return results


def save_etf_data(etf_data: List[dict], output_dir: str) -> str:
    """保存数据到JSON。"""
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, 'etf_market_data.json')
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(etf_data, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n数据已保存: {output_path}")
    return output_path


def main():
    parser = argparse.ArgumentParser(description='行业ETF数据采集（双源）')
    parser.add_argument('--output-dir', default=None, help='输出目录')
    parser.add_argument('--days', type=int, default=180, help='历史K线天数')
    parser.add_argument('--source', default='westock', choices=['westock', 'tdx'],
                       help='数据源（默认westock）')
    parser.add_argument('--cache', default=None, help='westock缓存文件路径')
    args = parser.parse_args()

    skill_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    output_dir = args.output_dir or os.path.join(skill_dir, 'data')

    etf_data = collect_all_etfs(days=args.days, source=args.source,
                                cache_path=args.cache)
    if etf_data:
        save_etf_data(etf_data, output_dir)
    return etf_data


if __name__ == '__main__':
    main()
