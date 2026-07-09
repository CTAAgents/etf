# ETF双动量轮动策略 v1.1.0

**etf-dual-momentum** — 32行业全覆盖 × 双动量 × Top-5分散 × 逐ETF PE刹车 × ATR日频止损 × 妙想自动化交易

## 策略概述

基于 Gary Antonacci 双动量框架，扩展到 A股 32 个申万一级行业 ETF 全覆盖。绝对动量择时（沪深300金丝雀）+ 相对动量轮动（32行业赛马）+ PE估值刹车 + ATR移动跟踪止损，四层风控体系。

## 标的池（34只ETF）

| 板块 | ETF数量 | ETF列表 |
|------|:------:|------|
| 基准（金丝雀） | 1 | 沪深300ETF (510300) |
| 金融 | 5 | 银行(512800) 非银(512070) 证券(512880) 保险(512230) 房地产(512200) |
| 消费 | 6 | 食品饮料(515170) 酒(512690) 医药(512010) 医疗器械(159883) 家电(159996) 消费50(515650) |
| 科技 | 7 | 半导体(512480) 芯片(159995) 电子(159997) 计算机(512720) 通信(515880) 传媒(512980) 游戏(159869) |
| 制造 | 5 | 新能源车(515030) 光伏(515790) 军工(512660) 机械(159886) 电池(159865) |
| 周期 | 5 | 有色(512400) 钢铁(515210) 煤炭(515220) 化工(516020) 能源(159930) |
| 基建 | 3 | 基建(159719) 交通(159766) 电力(159791) |
| 农业 | 1 | 农业(159825) |
| 防御 | 1 | 银华日利(511880) |

**总计**: 32只行业ETF + 1只基准 + 1只货币 = 34只

## 核心参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `momentum_window` | 180 | 绝对动量窗口 |
| `relative_momentum_window` | 90 | 相对动量窗口 |
| `rebalance_freq` | **biweekly** | 双周调仓 — #1最优 |
| `top_n` | **5** | Top-5分散 |
| `abs_momentum_threshold` | **-0.05** | 宽松金丝雀（-5%门槛） |
| `valuation_enabled` | **True** | 逐ETF PE刹车（AKShare csindex） |
| `trailing_stop_atr_multiplier` | **1.0** | ATR紧止损 |

## 策略逻辑

```
月末调仓:

Step 1: 绝对动量（金丝雀）
  └─ 沪深300ETF 180日收益率 ≤ 0 → 全仓银华日利

Step 2: 相对动量（行业赛马 ★32只）
  └─ 32行业ETF按90日收益率降序排列

Step 3: 估值刹车（逐ETF PE——AKShare csindex）
  └─ 单只ETF跟踪指数PE在近期20条数据中处于高位(>80%) 且 涨幅>30% → 跳过该ETF
  └─ 无PE数据的ETF默认不刹车

Step 4: Top-5等权持仓
  └─ 每只20%仓位

Step 5: ATR移动跟踪止损
  └─ 日频检查：价格跌破(入场价-1.0×入场ATR) → 次日开盘退出

Step 6: 交易执行
  └─ 卖出非目标ETF → 买入选中ETF
  └─ 扣除买卖双边手续费+滑点
```

## 使用方式

```bash
# 运行回测
python -m scripts.main backtest

# 指定数据源
python -m scripts.main backtest --source tdx

# 生成实时信号
python -m scripts.main signal

# 更新数据
python -m scripts.main update --force

# 查看配置
python -m scripts.main config

# 禁用估值刹车
python -m scripts.main backtest --no-valuation

# 指定回测区间
python -m scripts.main backtest --start 2021-08-01 --end 2026-07-01
```

## 模块结构

```
industry-etf-dual-momentum/
├── SKILL.md                     # 本文档
├── scripts/
│   ├── config.py                # 配置（34ETF池 + 策略参数）
│   ├── data_collector.py        # 多源数据采集（westock/TDX/缓存）
│   ├── momentum.py              # 动量计算 + 估值刹车
│   ├── strategy.py              # 策略核心 + 调仓信号生成
│   ├── backtest.py              # 回测引擎 + 绩效统计
│   ├── report.py                # HTML报告生成
│   └── main.py                  # CLI入口
```

## 与 a-share-etf-momentum 的差异

| 维度 | a-share-etf-momentum | industry-etf-dual-momentum |
|------|---------------------|---------------------------|
| 行业ETF数量 | 6只 | **32只** |
| 选股数量 | Top-1 | **Top-3** |
| 持仓集中度 | 100%单行业 | 各33%三行业 |
| 行业覆盖 | 6个代表性行业 | 全申万一级行业 |
| 策略框架 | 双动量+估值刹车+ATR止损 | 继承 + AKShare市场级估值刹车 |
| 绝对动量窗口 | 90天 | **180天（Phase2最优）** |
| 相对动量窗口 | 30天 | **90天（Phase2最优）** |
| 调仓频率 | 月频 | **双周（Phase2最优）** |
| 估值刹车 | PE分位（逐ETF） | **沪深300 PE分位（AKShare）** |

## 仓库管理

- **GitHub**: [CTAAgents/etf](https://github.com/CTAAgents/etf) · 子目录 `etf-dual-momentum/`
- **同步**: `bash sync_etf_skill.sh` → rsync → commit → push
- **SSH Key**: `~/.ssh/cta_deploy_ed25519`
- **同级 skills**: `etf-trend-signal` / `a-share-etf-momentum` / `quantitative-momentum-stock-selection`

## 风险提示

- 动量衰减：行业快速轮动期可能表现不佳
- PE估值数据依赖 AKShare csindex（20条近期数据），分位计算精度有限
- 回测不代表未来收益
- 双周调仓+紧止损导致高换手（年化~27倍），实盘成本不可忽略

## 仓库管理

- **GitHub**: [CTAAgents/etf](https://github.com/CTAAgents/etf) · 子目录 `etf-dual-momentum/`
- **同步**: `bash sync_etf_skill.sh` → rsync → commit → push

## 自动化任务

| 时间 | 任务 |
|:---:|------|
| T日 15:30 | 盘后跟踪：信号计算 + ATR止损检查 → daily_{timestamp}.html/json |
| T+1 9:30 | 开盘执行：止损卖出→买511880 → 调仓买卖 → daily_{timestamp}_exec.html/log |

## 版本历史

### v1.1.0 (2026-07-09)
- **逐ETF PE刹车**：AKShare csindex 20条近期PE算相对位置，替代市场级一刀切
- **参数优化**（5.5年westock数据，训练/测试分离）：
  - 最优: momentum=180, rel=90, top_n=5, biweekly, atr=1.0, thr=-0.05
  - 5年回测: 累计+1243%, Sharpe 4.88, 最大回撤-6.3%
- **ATR 日频止损**：每日收盘检查 + 次日开盘执行 + 自动买入511880
- **妙想自动化流水线**：盘后跟踪 + 开盘执行，2个自动化覆盖全流程
- **交易日历**：AKShare tool_trade_date_hist_sina 自动跳过非交易日
- **统一报告**：daily_{timestamp}.html/json/log，全线可追溯

### v1.0.0 (2026-07-09)
- 初始版本：基于 a-share-etf-momentum v2.0 框架扩展
- 32行业ETF全池 + Top-3分散 + 前向参数优化 + 沪深300 PE刹车
