# -*- coding: utf-8 -*-
"""配置管理模块（ETF趋势信号发现版）：申万行业ETF映射、L1-L4权重、阈值参数。"""

# ============================================================
# 申万一级31行业 ↔ ETF代码映射表
# ============================================================
# 格式: (行业代码, 行业名称, ETF代码, ETF名称, ETF类型)
SECTOR_ETF_MAPPING = [
    # 大金融
    ('银行', '银行', '512800.SH', '银行ETF', '金融'),
    ('非银金融', '非银金融', '512070.SH', '非银ETF', '金融'),
    ('证券', '证券', '512880.SH', '证券ETF', '金融'),
    ('保险', '保险', '512230.SH', '保险ETF', '金融'),
    ('房地产', '房地产', '512200.SH', '房地产ETF', '金融'),

    # 大消费
    ('食品饮料', '食品饮料', '515170.SH', '食品饮料ETF', '消费'),
    ('白酒', '白酒', '512690.SH', '酒ETF', '消费'),
    ('医药生物', '医药生物', '512010.SH', '医药ETF', '消费'),
    ('医疗器械', '医疗器械', '159883.SZ', '医疗器械ETF', '消费'),
    ('家用电器', '家用电器', '159996.SZ', '家电ETF', '消费'),
    ('商贸零售', '商贸零售', '515650.SH', '消费50ETF', '消费'),

    # 科技成长
    ('半导体', '半导体', '512480.SH', '半导体ETF', '科技'),
    ('芯片', '芯片', '159995.SZ', '芯片ETF', '科技'),
    ('电子', '电子', '159997.SZ', '电子ETF', '科技'),
    ('计算机', '计算机', '512720.SH', '计算机ETF', '科技'),
    ('通信', '通信', '515880.SH', '通信ETF', '科技'),
    ('传媒', '传媒', '512980.SH', '传媒ETF', '科技'),
    ('游戏', '游戏', '159869.SZ', '游戏ETF', '科技'),

    # 制造与周期
    ('新能源汽车', '新能源汽车', '515030.SH', '新能源车ETF', '制造'),
    ('光伏', '光伏', '515790.SH', '光伏ETF', '制造'),
    ('军工', '军工', '512660.SH', '军工ETF', '制造'),
    ('机械设备', '机械设备', '159886.SZ', '机械ETF', '制造'),
    ('电力设备', '电力设备', '159865.SZ', '电池ETF', '制造'),

    # 周期资源
    ('有色金属', '有色金属', '512400.SH', '有色ETF', '周期'),
    ('钢铁', '钢铁', '515210.SH', '钢铁ETF', '周期'),
    ('煤炭', '煤炭', '515220.SH', '煤炭ETF', '周期'),
    ('化工', '化工', '516020.SH', '化工ETF', '周期'),
    ('石油石化', '石油石化', '159930.SZ', '能源ETF', '周期'),

    # 基建公用
    ('建筑装饰', '建筑装饰', '159719.SZ', '基建ETF', '基建'),
    ('交通运输', '交通运输', '159766.SZ', '交通ETF', '基建'),
    ('公用事业', '公用事业', '159791.SZ', '电力ETF', '基建'),

    # 农业
    ('农林牧渔', '农林牧渔', '159825.SZ', '农业ETF', '农业'),
]

# 映射索引
SECTOR_NAMES = [s[0] for s in SECTOR_ETF_MAPPING]
SECTOR_ETF_CODES = [s[2] for s in SECTOR_ETF_MAPPING]
SECTOR_TYPE = {s[0]: s[4] for s in SECTOR_ETF_MAPPING}

# 行业分类分组
SECTOR_GROUPS = {
    '金融': ['银行', '非银金融', '证券', '保险', '房地产'],
    '消费': ['食品饮料', '白酒', '医药生物', '医疗器械', '家用电器', '商贸零售'],
    '科技': ['半导体', '芯片', '电子', '计算机', '通信', '传媒', '游戏'],
    '制造': ['新能源汽车', '光伏', '军工', '机械设备', '电力设备'],
    '周期': ['有色金属', '钢铁', '煤炭', '化工', '石油石化'],
    '基建': ['建筑装饰', '交通运输', '公用事业'],
    '农业': ['农林牧渔'],
}

# 行业ETF可做空（有融券标的）
MARGINABLE_SECTORS = ['银行', '证券', '食品饮料', '医药生物', '有色金属',
                       '半导体', '芯片', '新能源汽车', '军工', '化工']

# ============================================================
# 系统配置
# ============================================================
CONFIG_MANAGER = {
    'system': {
        'version': '1.0.0',
        'debug': False,
        'log_level': 'INFO',
        'max_symbols': 50,
        'enable_cache': True,
        'cache_ttl': 300,
        'parallel_processing': True,
        'max_workers': 4,
    },
    'market_state': {
        'trend_threshold': 25,
        'range_threshold': 10,
        'volatile_threshold': 2.0,
        'adx_trend': 25,
        'adx_range': 20,
    },
    'trading': {
        'entry_atr_multiplier': 0.5,
        'entry_validity_hours': 4,
        'target_return': 0.08,
        'atr_multiplier': 2.0,
        'max_position': 10,
        'min_position': 1,
        'base_position': 3,
    },
    'risk': {
        'max_drawdown': 15,
        'sharpe_ratio_min': 0.8,
        'win_rate_min': 50,
    },
}

# ============================================================
# 指标参数配置（ETF版）
# ============================================================
INDICATOR_CONFIG = {
    'MA':   {'periods': [5, 10, 20, 40, 60, 120], 'weight': 30},
    'MACD': {'fast': 12, 'slow': 26, 'signal': 9, 'weight': 20},
    'RSI':  {'period': 14, 'overbought': 70, 'oversold': 30, 'weight': 10},
    'DMI':  {'period': 14, 'smooth': 6, 'weight': 20},
    'ATR':  {'period': 14, 'high_threshold': 3.0, 'low_threshold': 1.0, 'use_for_scoring': False},
    'VOLUME': {'obv_ma_period': 20, 'weight': 10},
    'PRICE_POSITION': {'ma_period': 20, 'weight': 15},
    'CHANNEL_BREAKOUT': {'bb_period': 20, 'bb_std': 2, 'dc_period': 20, 'weight': 15},
    'CHANNEL_POSITION': {'bb_period': 20, 'dc_period': 20, 'weight': 10},
    # ETF专属
    'SHARE': {'weight': 15},           # 基金份额变化
    'IOPV': {'weight': 10},            # IOPV折溢价
    'NORTHBOUND': {'weight': 10},      # 北向资金
    'MARGIN': {'weight': 5},           # 融资余额
}

# ============================================================
# L1-L4四层打分配置（ETF优化版）
# ============================================================
SCORING_CONFIG = {
    'thresholds': {
        'strong_signal': 75,   # ≥75分：STRONG
        'watch_signal': 60,    # 60-74分：WATCH
        'weak_signal': 40,     # 40-59分：WEAK
        'noise': 0,            # <40分：NOISE
        'overheat': 90,        # >90分：警惕过热
    },
    'dimensions': {
        'L1_germination': {'max': 40, 'weight': 0.40, 'type': 'L1萌芽/资金结构'},
        'L2_volume_price': {'max': 30, 'weight': 0.30, 'type': 'L2量价领先'},
        'L3_structure': {'max': 20, 'weight': 0.20, 'type': 'L3价格结构'},
        'L4_confirmation': {'max': 10, 'weight': 0.10, 'type': 'L4确认'},
        'veto': {'max': -20, 'weight': 0.0, 'type': '否决'},
    },
    'layer_description': {
        'L1': '最早信号（10-30根K）：份额-价格背离、IOPV折溢价、北向资金、融资余额、通达信专业数据、ROC零轴、%b中线、ATR百分位',
        'L2': '次早信号（3-10根K）：Vortex、CCI、Supertrend、HMA、量价背离',
        'L3': '中等信号（2-5根K）：RSI健康区、DMI方向、前高突破、行业相对强度',
        'L4': '确认信号（0根K，基准）：通道突破、均线排列、MACD、ADX确认',
    },
    'tier_system': {
        'T2_main': {'min': 75, 'max': 90, 'desc': '主仓信号，正常仓位'},
        'T1_watch': {'min': 60, 'max': 75, 'desc': '观察/预加载，轻仓试探'},
        'T3_caution': {'min': 90, 'max': 100, 'desc': '警惕过热，减仓或观望'},
        'T0_ignore': {'min': 0, 'max': 60, 'desc': '弱信号/噪音，忽略'},
    },
    'ranking': {
        'use_ranking': True,
        'top_n': 10,
        'min_absolute_score': 40,
    },
    'time_decay': {
        'enabled': True,
        'curve_type': 'etf_slow',  # ETF版：趋势周期更长，衰减更缓
        'decay_curve': {
            0: 1.0,    # 当天：100%
            5: 0.95,   # 5天：95%（期货3天就90%）
            10: 0.85,  # 10天：85%
            20: 0.65,  # 20天：65%（期货14天就50%）
            30: 0.50,  # 30天：50%
            40: 0.30,  # 40天+：30%
        },
    },
    # ETF专属配置
    'etf_specific': {
        'share_surge_threshold': 0.05,     # 份额突变阈值（单日环比>5%）
        'premium_threshold': 0.01,         # 溢价率阈值（>1%）
        'discount_high_threshold': 0.02,   # 折价过高阈值（>2%）
        'northbound_ma_short': 5,          # 北向资金短期MA
        'northbound_ma_long': 20,          # 北向资金长期MA
        'margin_slope_period': 5,          # 融资余额斜率周期
        'share_weight': 5,                 # 份额信号分值
        'premium_weight': 4,               # 折溢价信号分值
        'northbound_weight': 4,            # 北向信号分值
        'margin_weight': 3,                # 融资信号分值
        'sector_rotation_weight': 4,       # 行业轮动信号分值
        'beta_threshold': 1.1,             # β过滤阈值
    },
}

# ============================================================
# 行业β配置
# ============================================================
# 各行业ETF相对沪深300的典型β值（近120日滚动）
SECTOR_BETA_DEFAULT = {
    '银行': 0.8, '非银金融': 1.2, '证券': 1.5, '保险': 1.1, '房地产': 1.0,
    '食品饮料': 1.0, '白酒': 1.1, '医药生物': 0.9, '医疗器械': 0.9,
    '家用电器': 1.0, '商贸零售': 0.8,
    '半导体': 1.6, '芯片': 1.7, '电子': 1.3, '计算机': 1.4,
    '通信': 1.2, '传媒': 1.1, '游戏': 1.3,
    '新能源汽车': 1.4, '光伏': 1.5, '军工': 1.2, '机械设备': 1.1, '电力设备': 1.3,
    '有色金属': 1.3, '钢铁': 1.2, '煤炭': 1.1, '化工': 1.2, '石油石化': 1.0,
    '建筑装饰': 0.9, '交通运输': 0.8, '公用事业': 0.7,
    '农林牧渔': 0.9,
}

# ============================================================
# 市场类型参数适配表（ETF版）
# ============================================================
MARKET_PARAMS = {
    'etf': {
        'name': '行业ETF',
        'examples': '证券ETF、半导体ETF、光伏ETF',
        'dc_period_short': 20,
        'dc_period_long': 55,
        'bb_period': 20,
        'bb_std': 2,
        'vol_filter_mult': 1.8,
        'atr_stop_mult': 1.5,
        'atr_target_mult': 2.0,
        'note': '关注份额变化和北向资金流向，均线结构比期货更可靠',
    },
    'benchmark': '沪深300',
    'benchmark_code': '000300.SH',
}

# ============================================================
# ETF特有品种阈值
# ============================================================
ETF_THRESHOLDS = {
    '金融': {'volatility_threshold': 2.0, 'atr_stop_mult': 1.3},
    '消费': {'volatility_threshold': 2.2, 'atr_stop_mult': 1.4},
    '科技': {'volatility_threshold': 3.0, 'atr_stop_mult': 1.6},
    '制造': {'volatility_threshold': 2.8, 'atr_stop_mult': 1.5},
    '周期': {'volatility_threshold': 2.5, 'atr_stop_mult': 1.4},
    '基建': {'volatility_threshold': 2.0, 'atr_stop_mult': 1.3},
    '农业': {'volatility_threshold': 2.2, 'atr_stop_mult': 1.4},
}

# ============================================================
# 宏观时钟 → 行业轮动映射
# ============================================================
MACRO_CLOCK_SECTOR = {
    '复苏': ['金融', '消费', '科技'],       # 复苏期：配金融消费科技
    '过热1': ['周期', '制造'],               # 过热前期：配周期制造
    '过热2': ['周期', '制造', '科技'],        # 过热后期：配周期制造科技
    '滞胀': ['消费', '基建', '公用事业'],     # 滞胀：配必选消费基建公用
    '衰退1': ['科技', '基建'],               # 衰退前期：科技基建先行
    '衰退2': ['消费', '基建', '公用'],        # 衰退后期：防御消费基建
    'default': ['消费', '金融', '基建'],      # 默认均衡配置
}

# ============================================================
# 通达信 TQ-Local 配置
# ============================================================
TDX_CONFIG = {
    'base_url': 'http://127.0.0.1:17709/',
    'timeout': 30,
    'etf_market_code': '31',          # get_stock_list market=31 → ETF基金
    'benchmark_code': '000300.CSI',   # 沪深300指数代码（TQ格式）
    'period': '1d',                   # 日线
    'days_history': 180,              # 获取K线天数
    'dividend_type': 'qfq',           # 前复权
    # 数据源优先级
    'priority_chain': ['tdx_local', 'akshare'],
}

# ============================================================
# TDX 数据字段映射（ETF相关专用接口）
# ============================================================
# 通达信 TQ-Local 接口对应的ETF数据获取方式
TDX_DATA_MAP = {
    'etf_kline': {
        'method': 'get_market_data',
        'params': {'period': '1d', 'dividend_type': 'qfq'},
        'description': 'ETF日K线（OHLCV）',
    },
    'etf_snapshot': {
        'method': 'get_market_snapshot',
        'description': 'ETF实时快照（含Jjjz基金净值=IOPV）',
    },
    'etf_premium': {
        'method': 'get_more_info',
        'params': {'field_list': ['More_YJL']},
        'description': 'ETF溢价率',
    },
    'etf_list': {
        'method': 'get_stock_list',
        'params': {'market': '31', 'list_type': 1},
        'description': '所有ETF基金列表',
    },
    'market_margin': {
        'method': 'get_scjy_value',
        'params': {'field_list': ['SC01']},
        'description': '市场融资融券余额',
    },
    'market_northbound': {
        'method': 'get_scjy_value',
        'params': {'field_list': ['SC02']},
        'description': '陆股通资金流入',
    },
    'etf_scale': {
        'method': 'get_scjy_value',
        'params': {'field_list': ['SC08']},
        'description': 'ETF基金规模份额数据',
    },
    'benchmark_kline': {
        'method': 'get_market_data',
        'params': {'period': '1d', 'dividend_type': 'none'},
        'description': '基准指数K线（沪深300）',
    },
}

# ============================================================
# 工具函数
# ============================================================

def get_sector_thresholds(sector_name: str) -> dict:
    """获取行业专属阈值。"""
    sector_type = SECTOR_TYPE.get(sector_name, '科技')
    return ETF_THRESHOLDS.get(sector_type, ETF_THRESHOLDS['科技'])

def get_etf_code(sector_name: str) -> str:
    """根据行业名称获取ETF代码。"""
    for s in SECTOR_ETF_MAPPING:
        if s[0] == sector_name:
            return s[2]
    return ''

def get_sector_name(etf_code: str) -> str:
    """根据ETF代码获取行业名称。"""
    for s in SECTOR_ETF_MAPPING:
        if s[2] == etf_code:
            return s[0]
    return etf_code

def get_group_sectors(group: str) -> list:
    """获取行业分组下的所有行业。"""
    return SECTOR_GROUPS.get(group, [])

def get_macro_preferred_sectors(macro_phase: str = 'default') -> list:
    """根据宏观时钟获取偏好的行业组。"""
    preferred = MACRO_CLOCK_SECTOR.get(macro_phase, MACRO_CLOCK_SECTOR['default'])
    sectors = []
    for group in preferred:
        sectors.extend(SECTOR_GROUPS.get(group, []))
    return sectors
