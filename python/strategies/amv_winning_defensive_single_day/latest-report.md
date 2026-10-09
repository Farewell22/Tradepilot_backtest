# 最新运行报告：amv_winning_defensive_single_day

- 任务类型：`strategy`
- 运行时间（UTC）：`2026-09-29T06:34:36.112718+00:00`
- 请求区间：`20161104` ～ `20201231`
- 运行目录：[data/backtest_runs/amv_winning_defensive_single_day__20260929T063436Z__d522be8a](../../../data/backtest_runs/amv_winning_defensive_single_day__20260929T063436Z__d522be8a)
- 运行清单：[data/backtest_runs/amv_winning_defensive_single_day__20260929T063436Z__d522be8a/run_manifest.json](../../../data/backtest_runs/amv_winning_defensive_single_day__20260929T063436Z__d522be8a/run_manifest.json)
- 输入数据：
  - [data/backtest_data/0AMV-260612.csv](../../../data/backtest_data/0AMV-260612.csv)
  - [data/backtest_data/ETF_60min_2005_2025/512100.SH.csv](../../../data/backtest_data/ETF_60min_2005_2025/512100.SH.csv)
  - [data/backtest_data/amv_defensive_pre2021_inputs/601288.SH.csv](../../../data/backtest_data/amv_defensive_pre2021_inputs/601288.SH.csv)
  - [data/backtest_data/amv_defensive_pre2021_inputs/dividends_601288.csv](../../../data/backtest_data/amv_defensive_pre2021_inputs/dividends_601288.csv)
- 关键结果文件：
  - [data/backtest_runs/amv_winning_defensive_single_day__20260929T063436Z__d522be8a/amv_signals.csv](../../../data/backtest_runs/amv_winning_defensive_single_day__20260929T063436Z__d522be8a/amv_signals.csv)
  - [data/backtest_runs/amv_winning_defensive_single_day__20260929T063436Z__d522be8a/annual_returns.csv](../../../data/backtest_runs/amv_winning_defensive_single_day__20260929T063436Z__d522be8a/annual_returns.csv)
  - [data/backtest_runs/amv_winning_defensive_single_day__20260929T063436Z__d522be8a/comparison_nav.csv](../../../data/backtest_runs/amv_winning_defensive_single_day__20260929T063436Z__d522be8a/comparison_nav.csv)
  - [data/backtest_runs/amv_winning_defensive_single_day__20260929T063436Z__d522be8a/metrics.json](../../../data/backtest_runs/amv_winning_defensive_single_day__20260929T063436Z__d522be8a/metrics.json)
  - [data/backtest_runs/amv_winning_defensive_single_day__20260929T063436Z__d522be8a/nav.csv](../../../data/backtest_runs/amv_winning_defensive_single_day__20260929T063436Z__d522be8a/nav.csv)
  - [data/backtest_runs/amv_winning_defensive_single_day__20260929T063436Z__d522be8a/paired_trades.csv](../../../data/backtest_runs/amv_winning_defensive_single_day__20260929T063436Z__d522be8a/paired_trades.csv)
  - [data/backtest_runs/amv_winning_defensive_single_day__20260929T063436Z__d522be8a/primary_trades.csv](../../../data/backtest_runs/amv_winning_defensive_single_day__20260929T063436Z__d522be8a/primary_trades.csv)
  - [data/backtest_runs/amv_winning_defensive_single_day__20260929T063436Z__d522be8a/signal_trade_stats.csv](../../../data/backtest_runs/amv_winning_defensive_single_day__20260929T063436Z__d522be8a/signal_trade_stats.csv)
  - [data/backtest_runs/amv_winning_defensive_single_day__20260929T063436Z__d522be8a/source_manifest.json](../../../data/backtest_runs/amv_winning_defensive_single_day__20260929T063436Z__d522be8a/source_manifest.json)
  - [data/backtest_runs/amv_winning_defensive_single_day__20260929T063436Z__d522be8a/trades.csv](../../../data/backtest_runs/amv_winning_defensive_single_day__20260929T063436Z__d522be8a/trades.csv)
  - [data/backtest_runs/amv_winning_defensive_single_day__20260929T063436Z__d522be8a/verification.json](../../../data/backtest_runs/amv_winning_defensive_single_day__20260929T063436Z__d522be8a/verification.json)

## 本次报告

### [data/backtest_runs/amv_winning_defensive_single_day__20260929T063436Z__d522be8a/report.md](../../../data/backtest_runs/amv_winning_defensive_single_day__20260929T063436Z__d522be8a/report.md)

# 农行直接防守策略：仅单日涨幅≥4%入场

实际区间 20161104—20201231；1015个交易日，初始资金 200,000 元。

取消所有多日涨幅入场分支，仅保留0AMV单日涨幅≥4%且收盘≥MA5的主仓入场。
0AMV低于MA10或MACD死叉优先离场；复用原成交、仓位、止损、跟踪退出和农行8%净价差止盈规则。

| 版本 | 总收益 | 年化 | 最大回撤 | 夏普 | 期末资金 | 闭合交易数 |
|---|---:|---:|---:|---:|---:|---:|
| 原版：两日≥4% | 30.26% | 6.56% | -30.35% | 0.468 | 260,519.81 | 63 |
| 新版：仅单日≥4% | 81.44% | 15.40% | -17.66% | 1.068 | 362,871.17 | 38 |

## 年度收益

| 年份 | 原版 | 新版 |
|---|---:|---:|
| 2016 | -6.39% | -3.84% |
| 2017 | 39.17% | 27.41% |
| 2018 | -21.67% | 15.48% |
| 2019 | 26.97% | 28.10% |
| 2020 | 0.53% | 0.10% |

## 成交口径与限制

legacy_same_close_idealized：收盘确定信号、同日收盘执行，是原策略的理想化假设。
主仓盘中2.5%硬止损、浮盈超过5%后次日起按前日实体低点退出；盘中退出当日不回买主仓。
仅0AMV收盘离场条件触发时直接买农行，不要求周线J。农行无止损，费用后净价差8%止盈，止盈后现金锁定直到有效主仓入场；单独主仓盘中退出后先持现金。
主仓100份、股票100股整手；税前现金分红按原模型除息日计入可用现金，不计入止盈阈值。
年化按365自然日，夏普按243交易日、零无风险利率。期末持仓按收盘价估值，不强制平仓。
固定旧印花税/过户费，未充分模拟股息税、到账延迟、涨跌停、停牌及成交容量。
输入、代码快照及SHA256在inputs/、code_snapshot/、source_manifest.json；baseline/为同输入重跑原版。
