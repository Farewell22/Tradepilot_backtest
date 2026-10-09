# 最新运行报告：amv_winning_ccb

- 任务类型：`strategy`
- 运行时间（UTC）：`2026-09-28T15:51:17.745549+00:00`
- 请求区间：`20200102` ～ `20251231`
- 运行目录：[data/backtest_runs/amv_winning_ccb__20260928T155117Z__106e2210](../../../data/backtest_runs/amv_winning_ccb__20260928T155117Z__106e2210)
- 运行清单：[data/backtest_runs/amv_winning_ccb__20260928T155117Z__106e2210/run_manifest.json](../../../data/backtest_runs/amv_winning_ccb__20260928T155117Z__106e2210/run_manifest.json)
- 输入数据：
  - [data/backtest_data/0AMV-260612.csv](../../../data/backtest_data/0AMV-260612.csv)
  - [data/backtest_data/ETF_60min_2005_2025/512100.SH.csv](../../../data/backtest_data/ETF_60min_2005_2025/512100.SH.csv)
  - [data/backtest_data/5m_price](../../../data/backtest_data/5m_price)
  - [python/strategies/amv_winning_ccb/dividends_601939.csv](dividends_601939.csv)
- 关键结果文件：
  - [data/backtest_runs/amv_winning_ccb__20260928T155117Z__106e2210/annual_returns.csv](../../../data/backtest_runs/amv_winning_ccb__20260928T155117Z__106e2210/annual_returns.csv)
  - [data/backtest_runs/amv_winning_ccb__20260928T155117Z__106e2210/bank_weekly_kdj.csv](../../../data/backtest_runs/amv_winning_ccb__20260928T155117Z__106e2210/bank_weekly_kdj.csv)
  - [data/backtest_runs/amv_winning_ccb__20260928T155117Z__106e2210/metrics.json](../../../data/backtest_runs/amv_winning_ccb__20260928T155117Z__106e2210/metrics.json)
  - [data/backtest_runs/amv_winning_ccb__20260928T155117Z__106e2210/nav.csv](../../../data/backtest_runs/amv_winning_ccb__20260928T155117Z__106e2210/nav.csv)
  - [data/backtest_runs/amv_winning_ccb__20260928T155117Z__106e2210/original_nav.csv](../../../data/backtest_runs/amv_winning_ccb__20260928T155117Z__106e2210/original_nav.csv)
  - [data/backtest_runs/amv_winning_ccb__20260928T155117Z__106e2210/original_trades.csv](../../../data/backtest_runs/amv_winning_ccb__20260928T155117Z__106e2210/original_trades.csv)
  - [data/backtest_runs/amv_winning_ccb__20260928T155117Z__106e2210/source_manifest.json](../../../data/backtest_runs/amv_winning_ccb__20260928T155117Z__106e2210/source_manifest.json)
  - [data/backtest_runs/amv_winning_ccb__20260928T155117Z__106e2210/trades.csv](../../../data/backtest_runs/amv_winning_ccb__20260928T155117Z__106e2210/trades.csv)

## 本次报告

### [data/backtest_runs/amv_winning_ccb__20260928T155117Z__106e2210/direct/report.md](../../../data/backtest_runs/amv_winning_ccb__20260928T155117Z__106e2210/direct/report.md)

# 0AMV 主仓与建设银行（601939.SH）回测

实际区间 20200102—20251231，1454 个交易日；初始 200,000 元。

| 版本 | 期末资金（元） | 总收益 | 年化收益 | 最大回撤 | 夏普 | 已平仓交易 | 税前分红（元） |
|---|---:|---:|---:|---:|---:|---:|---:|
| 0AMV 收盘离场直接买入 | 606,640.27 | 203.32% | 20.31% | -22.48% | 1.152 | 86 | 37,597.40 |

## 年度收益（相对上年末净值；首年相对初始资金）

| 年份 | 直接买入 | 周线 J<10 | 原主仓离场持现金 |
|---|---:|---:|---:|
| 2020 | 10.58% | 13.97% | 23.07% |
| 2021 | -3.24% | -5.04% | -4.74% |
| 2022 | -6.10% | 0.58% | -4.07% |
| 2023 | 31.11% | 7.67% | 3.94% |
| 2024 | 89.37% | 42.37% | 33.62% |
| 2025 | 21.59% | 29.53% | 15.62% |

## 规则与可比范围

主仓 512100.SH：0AMV 单日/两日增长至少 4% 且不低于 MA5 进场；低于 MA10 或 MACD 死叉离场；盘中 2.5% 硬止损、上涨超过 5% 后次日起按前一日实体低点退出。银行无止损，有效主仓进场信号卖出全部银行并按原主仓规则买入，冲突日离场信号优先。

直接版完全沿用 amv_winning_defensive：0AMV 收盘离场即买银行；主仓仅盘中止损后先持现金。银行扣交易费用后净价差达到 8% 止盈（分红不计入阈值），止盈后持现金至主仓实际进场。主仓盘中退出当日不重新进场。

J 版完全沿用 amv_winning：实际卖出主仓才开启银行观察，现金且当日可见的动态周线 J 严格小于 10 才买；使用本股 2019 年以来的预热行情和截至当日的分红连续指标。银行成交买价上涨 8% 止盈，目标向上取整至分；止盈当日不能再买银行，次日可继续观察，主仓可盘中止损后当日按有效信号再进场。

两版的差异沿用此前农行对照，因此差别并非只有 J 过滤。银行买卖使用未复权价格，分红按上一交易日持仓于除息日入账；2020—2025 两股 A 股派息日均为除息日。每次买入按可用现金买整手 100 股，剩余零头及股息现金不自动增持，银行当日买入次日才能卖出。

费用：主仓 `{"commission_rate": 0.0003, "min_commission": 5.0, "stamp_duty_rate": 0.0, "transfer_fee_rate": 0.0, "slippage_rate": 0.001}`；银行 `{"commission_rate": 0.0003, "min_commission": 5.0, "stamp_duty_rate": 0.001, "transfer_fee_rate": 1e-05, "slippage_rate": 0.001}`。

成交口径为 legacy_same_close_idealized：收盘才能确认的信号按同日收盘成交；盘中用 OHLC 触价成交。保留旧固定印花税/过户费与税前股息，未模拟个人股息税、历史税率变更、停牌涨跌停成交及盘口容量。这是同口径比较结果，不能直接视为可实盘复制的收益。

年化按实际起止日间隔和 365 天复利，夏普以日收益、无风险利率 0、243 个交易日计算；期末持仓按收盘价估值，不强制平仓。完整主仓交易日全部保留，数据缺口直接报错。

## 输出与复现

direct/ 与 weekly_j/ 各含 nav.csv、trades.csv、metrics.json、report.md；直接版另外保留 events.csv。根目录 nav.csv、trades.csv、metrics.json 的主结果为直接版；metrics.json.variants 包含两版完整绩效。另有 original_nav.csv、original_trades.csv、annual_returns.csv、bank_weekly_kdj.csv、inputs/、code_snapshot/及 source_manifest.json（SHA256）。统一命令另保存 run_manifest.json 的请求、配置与执行口径。

分红来源：
[建设银行官方分红记录](https://accounts2.ccb.com/chn/home/investor/summary/fhqk/index.shtml)，与 Tushare 已实施事件核对日期、每股税前金额及无送转。

### [data/backtest_runs/amv_winning_ccb__20260928T155117Z__106e2210/report.md](../../../data/backtest_runs/amv_winning_ccb__20260928T155117Z__106e2210/report.md)

# 0AMV 主仓与建设银行（601939.SH）回测

实际区间 20200102—20251231，1454 个交易日；初始 200,000 元。

| 版本 | 期末资金（元） | 总收益 | 年化收益 | 最大回撤 | 夏普 | 已平仓交易 | 税前分红（元） |
|---|---:|---:|---:|---:|---:|---:|---:|
| 0AMV 收盘离场直接买入 | 606,640.27 | 203.32% | 20.31% | -22.48% | 1.152 | 86 | 37,597.40 |
| 主仓卖出后周线 J<10 买入 | 432,306.59 | 116.15% | 13.71% | -16.19% | 0.945 | 75 | 13,109.30 |

## 年度收益（相对上年末净值；首年相对初始资金）

| 年份 | 直接买入 | 周线 J<10 | 原主仓离场持现金 |
|---|---:|---:|---:|
| 2020 | 10.58% | 13.97% | 23.07% |
| 2021 | -3.24% | -5.04% | -4.74% |
| 2022 | -6.10% | 0.58% | -4.07% |
| 2023 | 31.11% | 7.67% | 3.94% |
| 2024 | 89.37% | 42.37% | 33.62% |
| 2025 | 21.59% | 29.53% | 15.62% |

## 规则与可比范围

主仓 512100.SH：0AMV 单日/两日增长至少 4% 且不低于 MA5 进场；低于 MA10 或 MACD 死叉离场；盘中 2.5% 硬止损、上涨超过 5% 后次日起按前一日实体低点退出。银行无止损，有效主仓进场信号卖出全部银行并按原主仓规则买入，冲突日离场信号优先。

直接版完全沿用 amv_winning_defensive：0AMV 收盘离场即买银行；主仓仅盘中止损后先持现金。银行扣交易费用后净价差达到 8% 止盈（分红不计入阈值），止盈后持现金至主仓实际进场。主仓盘中退出当日不重新进场。

J 版完全沿用 amv_winning：实际卖出主仓才开启银行观察，现金且当日可见的动态周线 J 严格小于 10 才买；使用本股 2019 年以来的预热行情和截至当日的分红连续指标。银行成交买价上涨 8% 止盈，目标向上取整至分；止盈当日不能再买银行，次日可继续观察，主仓可盘中止损后当日按有效信号再进场。

两版的差异沿用此前农行对照，因此差别并非只有 J 过滤。银行买卖使用未复权价格，分红按上一交易日持仓于除息日入账；2020—2025 两股 A 股派息日均为除息日。每次买入按可用现金买整手 100 股，剩余零头及股息现金不自动增持，银行当日买入次日才能卖出。

费用：主仓 `{"commission_rate": 0.0003, "min_commission": 5.0, "stamp_duty_rate": 0.0, "transfer_fee_rate": 0.0, "slippage_rate": 0.001}`；银行 `{"commission_rate": 0.0003, "min_commission": 5.0, "stamp_duty_rate": 0.001, "transfer_fee_rate": 1e-05, "slippage_rate": 0.001}`。

成交口径为 legacy_same_close_idealized：收盘才能确认的信号按同日收盘成交；盘中用 OHLC 触价成交。保留旧固定印花税/过户费与税前股息，未模拟个人股息税、历史税率变更、停牌涨跌停成交及盘口容量。这是同口径比较结果，不能直接视为可实盘复制的收益。

年化按实际起止日间隔和 365 天复利，夏普以日收益、无风险利率 0、243 个交易日计算；期末持仓按收盘价估值，不强制平仓。完整主仓交易日全部保留，数据缺口直接报错。

## 输出与复现

direct/ 与 weekly_j/ 各含 nav.csv、trades.csv、metrics.json、report.md；直接版另外保留 events.csv。根目录 nav.csv、trades.csv、metrics.json 的主结果为直接版；metrics.json.variants 包含两版完整绩效。另有 original_nav.csv、original_trades.csv、annual_returns.csv、bank_weekly_kdj.csv、inputs/、code_snapshot/及 source_manifest.json（SHA256）。统一命令另保存 run_manifest.json 的请求、配置与执行口径。

分红来源：
[建设银行官方分红记录](https://accounts2.ccb.com/chn/home/investor/summary/fhqk/index.shtml)，与 Tushare 已实施事件核对日期、每股税前金额及无送转。

### [data/backtest_runs/amv_winning_ccb__20260928T155117Z__106e2210/weekly_j/report.md](../../../data/backtest_runs/amv_winning_ccb__20260928T155117Z__106e2210/weekly_j/report.md)

# 0AMV 主仓与建设银行（601939.SH）回测

实际区间 20200102—20251231，1454 个交易日；初始 200,000 元。

| 版本 | 期末资金（元） | 总收益 | 年化收益 | 最大回撤 | 夏普 | 已平仓交易 | 税前分红（元） |
|---|---:|---:|---:|---:|---:|---:|---:|
| 主仓卖出后周线 J<10 买入 | 432,306.59 | 116.15% | 13.71% | -16.19% | 0.945 | 75 | 13,109.30 |

## 年度收益（相对上年末净值；首年相对初始资金）

| 年份 | 直接买入 | 周线 J<10 | 原主仓离场持现金 |
|---|---:|---:|---:|
| 2020 | 10.58% | 13.97% | 23.07% |
| 2021 | -3.24% | -5.04% | -4.74% |
| 2022 | -6.10% | 0.58% | -4.07% |
| 2023 | 31.11% | 7.67% | 3.94% |
| 2024 | 89.37% | 42.37% | 33.62% |
| 2025 | 21.59% | 29.53% | 15.62% |

## 规则与可比范围

主仓 512100.SH：0AMV 单日/两日增长至少 4% 且不低于 MA5 进场；低于 MA10 或 MACD 死叉离场；盘中 2.5% 硬止损、上涨超过 5% 后次日起按前一日实体低点退出。银行无止损，有效主仓进场信号卖出全部银行并按原主仓规则买入，冲突日离场信号优先。

直接版完全沿用 amv_winning_defensive：0AMV 收盘离场即买银行；主仓仅盘中止损后先持现金。银行扣交易费用后净价差达到 8% 止盈（分红不计入阈值），止盈后持现金至主仓实际进场。主仓盘中退出当日不重新进场。

J 版完全沿用 amv_winning：实际卖出主仓才开启银行观察，现金且当日可见的动态周线 J 严格小于 10 才买；使用本股 2019 年以来的预热行情和截至当日的分红连续指标。银行成交买价上涨 8% 止盈，目标向上取整至分；止盈当日不能再买银行，次日可继续观察，主仓可盘中止损后当日按有效信号再进场。

两版的差异沿用此前农行对照，因此差别并非只有 J 过滤。银行买卖使用未复权价格，分红按上一交易日持仓于除息日入账；2020—2025 两股 A 股派息日均为除息日。每次买入按可用现金买整手 100 股，剩余零头及股息现金不自动增持，银行当日买入次日才能卖出。

费用：主仓 `{"commission_rate": 0.0003, "min_commission": 5.0, "stamp_duty_rate": 0.0, "transfer_fee_rate": 0.0, "slippage_rate": 0.001}`；银行 `{"commission_rate": 0.0003, "min_commission": 5.0, "stamp_duty_rate": 0.001, "transfer_fee_rate": 1e-05, "slippage_rate": 0.001}`。

成交口径为 legacy_same_close_idealized：收盘才能确认的信号按同日收盘成交；盘中用 OHLC 触价成交。保留旧固定印花税/过户费与税前股息，未模拟个人股息税、历史税率变更、停牌涨跌停成交及盘口容量。这是同口径比较结果，不能直接视为可实盘复制的收益。

年化按实际起止日间隔和 365 天复利，夏普以日收益、无风险利率 0、243 个交易日计算；期末持仓按收盘价估值，不强制平仓。完整主仓交易日全部保留，数据缺口直接报错。

## 输出与复现

direct/ 与 weekly_j/ 各含 nav.csv、trades.csv、metrics.json、report.md；直接版另外保留 events.csv。根目录 nav.csv、trades.csv、metrics.json 的主结果为直接版；metrics.json.variants 包含两版完整绩效。另有 original_nav.csv、original_trades.csv、annual_returns.csv、bank_weekly_kdj.csv、inputs/、code_snapshot/及 source_manifest.json（SHA256）。统一命令另保存 run_manifest.json 的请求、配置与执行口径。

分红来源：
[建设银行官方分红记录](https://accounts2.ccb.com/chn/home/investor/summary/fhqk/index.shtml)，与 Tushare 已实施事件核对日期、每股税前金额及无送转。
