# -*- coding: utf-8 -*-
"""妙想模拟交易 (mx-moni) REST API 客户端。

提供统一的 HTTP 接口封装，供 weekly_rebalance 管道使用。
依赖: 环境变量 MX_APIKEY, MX_API_URL（可选，默认 https://mkapi2.dfcfs.com/finskillshub）
"""

import json
import os
import urllib.request
import urllib.error

MX_API_URL = os.environ.get('MX_API_URL', 'https://mkapi2.dfcfs.com/finskillshub')
MX_APIKEY = os.environ.get('MX_APIKEY', '')


def _call(endpoint: str, data: dict) -> dict:
    """底层 HTTP POST 调用。"""
    url = f'{MX_API_URL}{endpoint}'
    payload = json.dumps(data, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(
        url, data=payload,
        headers={'apikey': MX_APIKEY,
                 'Content-Type': 'application/json; charset=UTF-8'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        return {'code': str(e.code), 'message': f'HTTP {e.code}: {body}'}
    except Exception as e:
        return {'code': 'error', 'message': str(e)}


def is_configured() -> bool:
    """检查 API 密钥是否已配置。"""
    return bool(MX_APIKEY)


# ── 查询接口 ──

def query_positions() -> dict:
    """查询当前持仓。返回包含 posList / totalAssets / availBalance 等字段。"""
    return _call('/api/claw/mockTrading/positions', {'moneyUnit': 1})


def query_balance() -> dict:
    """查询账户资金。返回 totalAssets / availBalance / totalPosValue 等。"""
    return _call('/api/claw/mockTrading/balance', {'moneyUnit': 1})


def query_orders(flt_order_drt: int = 0, flt_order_status: int = 0) -> dict:
    """查询委托订单。drt: 0=全部 1=买入 2=卖出；status: 0=全部 2=已报 4=已成。"""
    return _call('/api/claw/mockTrading/orders', {
        'fltOrderDrt': flt_order_drt,
        'fltOrderStatus': flt_order_status,
    })


# ── 交易接口 ──

def cancel_all() -> dict:
    """一键撤单：撤销所有未成交委托。"""
    return _call('/api/claw/mockTrading/cancel', {'type': 'all'})


def trade(stock_code: str, trade_type: str,
          price: float = None, quantity: int = 100) -> dict:
    """执行买入或卖出。

    Args:
        stock_code: 6位A股代码 (如 600036)
        trade_type: 'BUY' 或 'SELL'
        price: 限价（None=市价）
        quantity: 数量（股），必须为100的整数倍
    """
    data = {
        'type': 'buy' if trade_type.upper() == 'BUY' else 'sell',
        'stockCode': stock_code,
        'quantity': quantity,
        'useMarketPrice': price is None,
    }
    if price is not None and not data['useMarketPrice']:
        data['price'] = price
    return _call('/api/claw/mockTrading/trade', data)


def sell_all_of(stock_code: str) -> dict:
    """卖出指定股票的全部持仓。先查询可用数量，再市价卖出。"""
    pos = query_positions()
    qty = 0
    for p in pos.get('data', {}).get('posList', []) or []:
        if p.get('secCode') == stock_code:
            qty = p.get('availCount', 0)
            break
    if qty == 0:
        return {'code': 'skip', 'message': f'{stock_code} 无持仓'}
    return trade(stock_code, 'SELL', quantity=qty)


def buy_market(stock_code: str, quantity: int = 100) -> dict:
    """市价买入。"""
    return trade(stock_code, 'BUY', quantity=quantity)


# ── 发帖接口 ──

def post_experience(html_content: str) -> dict:
    """发布经验交流帖。html_content 为轻量 HTML 格式。"""
    return _call('/api/claw/mockTrading/newPost', {'text': html_content})
