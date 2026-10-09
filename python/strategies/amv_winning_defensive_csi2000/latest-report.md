# 最新运行报告：amv_winning_defensive_csi2000

- 任务类型：`strategy`
- 运行时间（UTC）：`2026-10-08T03:27:51.067190+00:00`
- 请求区间：`20230914` ～ `20251231`
- 运行目录：[data/backtest_runs/amv_winning_defensive_csi2000__20261008T032751Z__4be22cc4](../../../data/backtest_runs/amv_winning_defensive_csi2000__20261008T032751Z__4be22cc4)
- 运行清单：[data/backtest_runs/amv_winning_defensive_csi2000__20261008T032751Z__4be22cc4/run_manifest.json](../../../data/backtest_runs/amv_winning_defensive_csi2000__20261008T032751Z__4be22cc4/run_manifest.json)
- 输入数据：
  - [data/backtest_data/0AMV-260612.csv](../../../data/backtest_data/0AMV-260612.csv)
  - [data/backtest_data/ETF_60min_2005_2025/563300.SH.csv](../../../data/backtest_data/ETF_60min_2005_2025/563300.SH.csv)
  - [data/backtest_data/ETF_60min_2005_2025/512100.SH.csv](../../../data/backtest_data/ETF_60min_2005_2025/512100.SH.csv)
  - [data/backtest_data/5m_price](../../../data/backtest_data/5m_price)
  - [python/strategies/amv_winning_defensive/dividends_601288.csv](../amv_winning_defensive/dividends_601288.csv)
- 关键结果文件：
  - [data/backtest_runs/amv_winning_defensive_csi2000__20261008T032751Z__4be22cc4/amv_signals.csv](../../../data/backtest_runs/amv_winning_defensive_csi2000__20261008T032751Z__4be22cc4/amv_signals.csv)
  - [data/backtest_runs/amv_winning_defensive_csi2000__20261008T032751Z__4be22cc4/annual_returns.csv](../../../data/backtest_runs/amv_winning_defensive_csi2000__20261008T032751Z__4be22cc4/annual_returns.csv)
  - [data/backtest_runs/amv_winning_defensive_csi2000__20261008T032751Z__4be22cc4/comparison_nav.csv](../../../data/backtest_runs/amv_winning_defensive_csi2000__20261008T032751Z__4be22cc4/comparison_nav.csv)
  - [data/backtest_runs/amv_winning_defensive_csi2000__20261008T032751Z__4be22cc4/metrics.json](../../../data/backtest_runs/amv_winning_defensive_csi2000__20261008T032751Z__4be22cc4/metrics.json)
  - [data/backtest_runs/amv_winning_defensive_csi2000__20261008T032751Z__4be22cc4/nav.csv](../../../data/backtest_runs/amv_winning_defensive_csi2000__20261008T032751Z__4be22cc4/nav.csv)
  - [data/backtest_runs/amv_winning_defensive_csi2000__20261008T032751Z__4be22cc4/paired_trades.csv](../../../data/backtest_runs/amv_winning_defensive_csi2000__20261008T032751Z__4be22cc4/paired_trades.csv)
  - [data/backtest_runs/amv_winning_defensive_csi2000__20261008T032751Z__4be22cc4/source_manifest.json](../../../data/backtest_runs/amv_winning_defensive_csi2000__20261008T032751Z__4be22cc4/source_manifest.json)
  - [data/backtest_runs/amv_winning_defensive_csi2000__20261008T032751Z__4be22cc4/trades.csv](../../../data/backtest_runs/amv_winning_defensive_csi2000__20261008T032751Z__4be22cc4/trades.csv)
  - [data/backtest_runs/amv_winning_defensive_csi2000__20261008T032751Z__4be22cc4/verification.json](../../../data/backtest_runs/amv_winning_defensive_csi2000__20261008T032751Z__4be22cc4/verification.json)

## 本次报告

### [data/backtest_runs/amv_winning_defensive_csi2000__20261008T032751Z__4be22cc4/report.md](../../../data/backtest_runs/amv_winning_defensive_csi2000__20261008T032751Z__4be22cc4/report.md)

# 中证2000 ETF＋农业银行直接防守回测

请求区间 20230914—20251231；实际区间 20230914—20251231；556个交易日；两组各从 200,000 元现金、无持仓开始。

唯一交易规则差异是进攻主仓：新版563300.SH，对照512100.SH；防守均为601288.SH。

| 方案 | 期末资金 | 总收益 | 年化收益 | 最大回撤 | 夏普 | 胜率 | 已平仓交易 | 税前分红 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 中证1000＋农行 | 591,596.67 | 195.80% | 60.29% | -16.78% | 2.584 | 63.89% | 36 | 12,907.31 |
| 中证2000＋农行 | 549,295.24 | 174.65% | 55.20% | -19.44% | 2.321 | 62.16% | 37 | 12,838.04 |

## 年度收益

首年为实际起点至年末，其后相对上年末净值。

| 年份 | 中证1000＋农行 | 中证2000＋农行 |
|---|---:|---:|
| 2023 | 6.59% | 6.76% |
| 2024 | 105.86% | 104.78% |
| 2025 | 34.80% | 25.62% |

## 规则、费用与可比范围

0AMV单日或两日累计涨幅≥4%且收盘≥MA5进主仓；收盘低于MA10或MACD死叉转农行；离场优先。
主仓2.5%硬止损；买入后某日最高价超过成交买价5%，收盘后启用前日实体低点跟踪退出，跟踪线每天更新，不保证只升不降。盘中退出当日不回买主仓；当天另有0AMV离场条件仍转农行。
农行从买入后的交易日起按5分钟K线检查费用后净价差8%止盈，分红不参与阈值；跳空越过阈值按开盘价卖出。止盈后现金锁定直到有效主仓入场；无独立止损。
主仓60分钟K线检查止损；所有买入按100份/股取整，剩余现金与股息不自动增持。
主仓费用：{"commission_rate": 0.0003, "min_commission": 5.0, "stamp_duty_rate": 0.0, "transfer_fee_rate": 0.0, "slippage_rate": 0.001}；股票费用：{"commission_rate": 0.0003, "min_commission": 5.0, "stamp_duty_rate": 0.001, "transfer_fee_rate": 1e-05, "slippage_rate": 0.001}。
保留原固定印花税和过户费、除息日税前现金分红模型，未计个人股息税及到账延迟。ETF沿用本地输入价格口径，不另加现金分红；512100份额折算仅用于512100。
legacy_same_close_idealized：0AMV信号在收盘后确认，同日收盘成交是理想化假设；未模拟涨跌停、停牌不可成交及盘口容量。
年化按实际起止日间隔、365自然日复利；夏普按243交易日、零无风险利率；期末持仓按收盘价估值，不强制平仓。
原主仓也在同一实际区间重跑，不能直接与2020—2025年全区间收益相比。区间内必需交易日缺失报错，上市前不回填价格。

根目录为新版；baseline/为同期原主仓。trades.csv为买卖流水，paired_trades.csv为闭合交易；inputs/、code_snapshot/及source_manifest.json保存实际输入、执行代码和SHA-256。
