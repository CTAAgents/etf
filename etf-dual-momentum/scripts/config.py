"""
行业ETF双动量轮动策略 - 配置模块 v1.0
31行业全覆盖 + 双动量 + 估值刹车 + ATR跟踪止损
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class ETFConfig:
    """ETF标的配置"""
    code: str
    name: str
    category: str  # benchmark / industry / defensive
    index_code: Optional[str] = None  # 跟踪指数代码（用于估值分位）


@dataclass
class Config:
    """策略主配置"""

    # ========== 标的池（32行业ETF + 基准 + 防御）==========
    benchmark: ETFConfig = field(default_factory=lambda: ETFConfig(
        code="510300", name="沪深300ETF", category="benchmark", index_code="000300"
    ))

    industry_etfs: List[ETFConfig] = field(default_factory=lambda: [
        # ── 金融 4只 ──
        ETFConfig(code="512800", name="银行ETF", category="industry", index_code="399986"),
        ETFConfig(code="512070", name="保险ETF", category="industry", index_code="399975"),
        ETFConfig(code="512880", name="证券ETF", category="industry", index_code="399975"),
        ETFConfig(code="512200", name="房地产ETF", category="industry", index_code="399393"),
        # ── 消费 6只 ──
        ETFConfig(code="515170", name="食品饮料ETF", category="industry", index_code="000807"),
        ETFConfig(code="512690", name="酒ETF", category="industry", index_code="399997"),
        ETFConfig(code="512010", name="医药ETF", category="industry", index_code="000933"),
        ETFConfig(code="159883", name="医疗器械ETF", category="industry", index_code="399989"),
        ETFConfig(code="159996", name="家电ETF", category="industry", index_code="930697"),
        ETFConfig(code="515650", name="消费50ETF", category="industry", index_code="000932"),
        # ── 科技 7只 ──
        ETFConfig(code="512480", name="半导体ETF", category="industry", index_code="990001"),
        ETFConfig(code="159995", name="芯片ETF", category="industry", index_code="990001"),
        ETFConfig(code="159997", name="电子ETF", category="industry", index_code="399006"),
        ETFConfig(code="512720", name="计算机ETF", category="industry", index_code="399363"),
        ETFConfig(code="515880", name="通信ETF", category="industry", index_code="931160"),
        ETFConfig(code="512980", name="传媒ETF", category="industry", index_code="399971"),
        ETFConfig(code="159869", name="游戏ETF", category="industry", index_code="399971"),
        # ── 制造 5只 ──
        ETFConfig(code="515030", name="新能源车ETF", category="industry", index_code="399976"),
        ETFConfig(code="515790", name="光伏ETF", category="industry", index_code="931151"),
        ETFConfig(code="512660", name="军工ETF", category="industry", index_code="399967"),
        ETFConfig(code="159886", name="机械ETF", category="industry", index_code="399976"),
        ETFConfig(code="159865", name="电池ETF", category="industry", index_code="980032"),
        # ── 周期 5只 ──
        ETFConfig(code="512400", name="有色ETF", category="industry", index_code="399395"),
        ETFConfig(code="515210", name="钢铁ETF", category="industry", index_code="399440"),
        ETFConfig(code="515220", name="煤炭ETF", category="industry", index_code="399998"),
        ETFConfig(code="516020", name="化工ETF", category="industry", index_code="399440"),
        ETFConfig(code="159930", name="能源ETF", category="industry", index_code="000805"),
        # ── 基建 3只 ──
        ETFConfig(code="159719", name="基建ETF", category="industry", index_code="399995"),
        ETFConfig(code="159766", name="交通ETF", category="industry", index_code="399967"),
        ETFConfig(code="159791", name="电力ETF", category="industry", index_code="399995"),
        # ── 农业 1只 ──
        ETFConfig(code="159825", name="农业ETF", category="industry", index_code="399997"),
    ])

    defensive: ETFConfig = field(default_factory=lambda: ETFConfig(
        code="511880", name="银华日利", category="defensive", index_code=None
    ))

    # ========== 动量参数（5.5年+PE刹车优化最优）==========
    momentum_window: int = 180  # 绝对动量窗口
    relative_momentum_window: int = 90  # 相对动量窗口
    rebalance_freq: str = "wednesday"  # 周三收盘信号，周四调仓
    top_n: int = 5  # Top-5分散

    # ========== 绝对动量参数 ==========
    abs_momentum_threshold: float = -0.05  # 宽松金丝雀（沪深300跌超5%才撤）

    # ========== 估值刹车参数 ==========
    valuation_pe_threshold: float = 80.0
    valuation_return_threshold: float = 0.30
    valuation_lookback_years: int = 5
    valuation_enabled: bool = True  # 逐ETF PE刹车（AKShare csindex 20条近期PE）

    # ========== ATR移动跟踪止损 ==========
    trailing_stop_enabled: bool = True
    trailing_stop_atr_period: int = 14
    trailing_stop_atr_multiplier: float = 1.0  # 紧止损（1.0×ATR）

    # ========== 资金与成本 ==========
    initial_capital: float = 1_000_000
    commission_rate: float = 0.001
    slippage_rate: float = 0.0001

    # ========== 数据源配置 ==========
    data_source: str = "westock"
    backup_data_source: str = "tdx"
    tdx_host: str = "http://127.0.0.1:17709/"
    tdx_dividend_type: str = "front"
    westock_dividend_type: str = "qfq"
    cache_dir: str = "cache"

    # ========== 回测配置 ==========
    backtest_start: str = "2021-08-01"
    backtest_end: str = "2026-07-09"
    benchmark_index: str = "000300"

    # ========== 输出配置 ==========
    output_dir: str = "reports"
    log_trades: bool = True

    # ========== ETF代码格式映射 ==========
    @staticmethod
    def to_westock_code(etf_code: str) -> str:
        if etf_code.startswith(("51", "56", "58", "60")): return f"sh{etf_code}"
        if etf_code.startswith(("15", "16", "30")): return f"sz{etf_code}"
        return f"sh{etf_code}"

    @staticmethod
    def to_tdx_code(etf_code: str) -> str:
        if etf_code.startswith(("51", "56", "58", "60")): return f"{etf_code}.SH"
        if etf_code.startswith(("15", "16", "30")): return f"{etf_code}.SZ"
        return f"{etf_code}.SH"

    @property
    def all_etf_codes(self) -> List[str]:
        return [self.benchmark.code] + [etf.code for etf in self.industry_etfs] + [self.defensive.code]

    @property
    def industry_codes(self) -> List[str]:
        return [etf.code for etf in self.industry_etfs]

    def get_etf_by_code(self, code: str) -> ETFConfig:
        if code == self.benchmark.code: return self.benchmark
        if code == self.defensive.code: return self.defensive
        for etf in self.industry_etfs:
            if etf.code == code: return etf
        raise ValueError(f"未知ETF代码: {code}")

    def get_index_code(self, etf_code: str) -> Optional[str]:
        return self.get_etf_by_code(etf_code).index_code
