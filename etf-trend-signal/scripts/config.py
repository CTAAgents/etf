# -*- coding: utf-8 -*-
"""配置管理模块（通道突破策略 v2.0）

基于 signal_layer_business_logic.md 的业务逻辑定义。
数据源：通达信TQ-Local（纯本地数据，无第三方库依赖）。

架构：Layer A唐奇安通道(75%) + Layer B布林带(25%) + 成交量独立加减分
"""

# ============================================================
# 申万一级31行业 ↔ ETF代码映射表（保留不变）
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

# 行业ETF可做空（有融券标的，保留仅供参考）
MARGINABLE_SECTORS = ['银行', '证券', '食品饮料', '医药生物', '有色金属',
                       '半导体', '芯片', '新能源汽车', '军工', '化工']

# ============================================================
# 信号等级阈值
# ============================================================
SIGNAL_GRADE_THRESHOLDS = {
    "strong": 50,    # STRONG: abs >= 50 → 进入辩论流程
    "watch": 40,     # WATCH: abs >= 40 → 观察信号
    "weak": 20,      # WEAK: abs >= 20 → 弱趋势
    "noise": 0,      # NOISE: < 20 → 噪音过滤
}

# ============================================================
# ATR移动跟踪止损配置 (v2.4.0 新增)
# ============================================================
# 基于两阶段网格搜索优化结果（2026-07-08, 5年时间序列分割60/40）
# 最优: Sharpe 1.168 | 年化 26.1% | 卡玛 1.22 (vs 无止损 Sharpe 0.291)
ATR_STOP_CONFIG = {
    "atr_period": 20,        # ATR计算周期
    "atr_multiplier": 1.5,   # ATR倍数（止损距离 = 最高收盘价 - 倍数×ATR）
    "weekday": 4,            # 调仓日 (0=周一 ... 4=周五)
    "top_n": 2,              # 候选池行业数
    "entry_threshold": 55,   # 开仓分数门槛
    "exit_threshold": 25,    # 退出分数门槛
    "force_cash_threshold": 30,  # 强制空仓阈值
}

# 无止损模式下的策略参数（原始通道突破）
CHANNEL_BREAKOUT_NO_STOP = {
    "top_n": 3,
    "entry_threshold": 55,
    "exit_threshold": 30,
    "force_cash_threshold": 35,
    "weekday": 2,  # 周三
}

# ============================================================
# 通道突破策略完整参数 (CHANNEL_BREAKOUT_CONFIG)
# ============================================================
CHANNEL_BREAKOUT_CONFIG = {
    # ── 时间窗口 ──
    'trading_min_per_day': 345,
    'dc20_period': 20,
    'dc55_period': 55,
    'ma60_period': 60,
    'min_bars_required': 60,

    # ── DC20 突破参数 ──
    'dc20': {
        'break_base_score': 30.0,
        'break_strong_pct': 1.0,         # 大幅突破阈值(%)
        'break_strong_bonus': 10.0,
        'break_moderate_pct': 0.3,       # 中等突破阈值(%)
        'break_moderate_bonus': 5.0,
        'pos_upper_threshold': 0.7,       # 上轨附近阈值(DC20_POS)
        'pos_upper_bonus': 5.0,
        'pos_lower_threshold': 0.3,       # 下轨附近阈值(DC20_POS)
        'pos_lower_bonus': -5.0,
    },

    # ── ADX 调整 ──
    'adx': {
        'exhaustion_threshold': 60,       # ADX>60 → 趋势可能衰竭
        'exhaustion_penalty': 5.0,        # 衰竭惩罚（向0靠拢）
        'trend_threshold': 25,            # ADX>=25 → 趋势健康
        'trend_bonus': 3.0,              # 趋势健康加分
    },

    # ── DC55 位置评分（6级阶梯）──
    'dc55_position': {
        'extreme_upper_threshold': 0.85,
        'extreme_upper_score': 30.0,  # 优化: 25→30 (样本外composite+11.6)
        'upper_threshold': 0.70,
        'upper_score': 20.0,              # 优化: 15→20 (样本外composite+9.7)
        'mid_upper_score': 7.0,           # 优化: 5→7 (样本外composite+9.3)
        'extreme_lower_threshold': 0.15,
        'extreme_lower_score': -25.0,
        'lower_threshold': 0.30,
        'lower_score': -15.0,
        'mid_lower_score': -5.0,         # <0.50
    },

    # ── DC55 趋势方向 ──
    'dc55_trend': {
        'trend_base_score': 10.0,
        'trend_alignment_bonus': 7.0,     # 优化: 5→7 (样本外composite+9.7)
        'divergence_penalty': 10.0,       # 方向背离减分
    },

    # ── 布林带 (BB) ──
    'bb': {
        'width_high_threshold': 4.0,      # BB宽度高阈值(%)
        'width_high_score': 6.0,
        'width_moderate_threshold': 2.5,  # BB宽度中等阈值(%)
        'width_moderate_score': 3.0,
        'squeeze_bonus': 2.0,            # BB挤压加分
        'pos_extreme_threshold': 1.05,    # %b极端阈值
        'pos_extreme_score': 6.0,
        'pos_upper_threshold': 1.0,      # %b上轨阈值
        'pos_upper_score': 4.0,
        'pos_mid_upper_threshold': 0.7,  # %b中上阈值
        'pos_mid_upper_score': 2.0,
        'pos_mid_lower_threshold': 0.15, # %b中下阈值
        'pos_mid_lower_score': -2.0,
        'pos_lower_score': -4.0,         # %b下轨
        'pos_extreme_lower_score': -6.0,  # %b极端下轨
        'dc_consistency_bonus': 2.0,     # DC-BB一致性加分
    },

    # ── 成交量 ──
    'volume': {
        'ma_period': 20,
        'explosive_ratio': 1.3,          # 优化: 1.5→1.3 (样本外composite+9.7)
        'explosive_score': 10.0,
        'elevated_ratio': 1.1,           # 优化: 1.2→1.1 (样本外composite+9.3)
        'elevated_score': 5.0,
        'normal_lower_ratio': 0.8,       # 正常量下界
        'weak_penalty': -3.0,            # 缩量惩罚（始终为负）
    },

    # ── 信号类型判定阈值 ──
    'signal_type': {
        'channel_breakout_dc20_min': 30,     # DC20得分需≥此值
        'channel_breakout_dc_total_min': 20, # DC总分需≥此值
        'trend_confirmation_dc55_min': 15,   # DC55得分需≥此值
    },
}

# ============================================================
# 行业β配置（保留，用于参考和过滤）
# ============================================================
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
# 市场类型参数适配表
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
    },
    'benchmark': '沪深300',
    'benchmark_code': '000300.SH',
}

# ============================================================
# 宏观时钟 → 行业轮动映射
# ============================================================
MACRO_CLOCK_SECTOR = {
    '复苏': ['金融', '消费', '科技'],
    '过热1': ['周期', '制造'],
    '过热2': ['周期', '制造', '科技'],
    '滞胀': ['消费', '基建', '公用事业'],
    '衰退1': ['科技', '基建'],
    '衰退2': ['消费', '基建', '公用'],
    'default': ['消费', '金融', '基建'],
}

# ============================================================
# 通达信 TQ-Local 配置
# ============================================================
TDX_CONFIG = {
    'base_url': 'http://127.0.0.1:17709/',
    'timeout': 30,
    'etf_market_code': '31',
    'benchmark_code': '000300.CSI',
    'period': '1d',
    'days_history': 180,
    'dividend_type': 'front',
    'priority_chain': ['tdx_local'],
}

# TDX 数据字段映射
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
    """获取行业专属阈值（保留兼容接口）。"""
    return {'volatility_threshold': 2.5, 'atr_stop_mult': 1.5}

def get_etf_code(sector_name: str) -> str:
    for s in SECTOR_ETF_MAPPING:
        if s[0] == sector_name:
            return s[2]
    return ''

def get_sector_name(etf_code: str) -> str:
    for s in SECTOR_ETF_MAPPING:
        if s[2] == etf_code:
            return s[0]
    return etf_code

def get_group_sectors(group: str) -> list:
    return SECTOR_GROUPS.get(group, [])

def get_macro_preferred_sectors(macro_phase: str = 'default') -> list:
    preferred = MACRO_CLOCK_SECTOR.get(macro_phase, MACRO_CLOCK_SECTOR['default'])
    sectors = []
    for group in preferred:
        sectors.extend(SECTOR_GROUPS.get(group, []))
    return sectors
