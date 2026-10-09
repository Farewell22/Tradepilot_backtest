# 最新运行报告：amv_winning_defensive_3d

- 任务类型：`strategy`
- 运行时间（UTC）：`2026-09-29T04:39:26.609579+00:00`
- 请求区间：`20200102` ～ `20251231`
- 运行目录：[data/backtest_runs/amv_winning_defensive_3d__20260929T043926Z__641076dd](../../../data/backtest_runs/amv_winning_defensive_3d__20260929T043926Z__641076dd)
- 运行清单：[data/backtest_runs/amv_winning_defensive_3d__20260929T043926Z__641076dd/run_manifest.json](../../../data/backtest_runs/amv_winning_defensive_3d__20260929T043926Z__641076dd/run_manifest.json)
- 输入数据：
  - [data/backtest_runs/amv_winning__20260928T141655Z__0456a927/inputs/0AMV.csv](../../../data/backtest_runs/amv_winning__20260928T141655Z__0456a927/inputs/0AMV.csv)
  - [data/backtest_runs/amv_winning__20260928T141655Z__0456a927/inputs/512100.SH.csv](../../../data/backtest_runs/amv_winning__20260928T141655Z__0456a927/inputs/512100.SH.csv)
  - [data/backtest_runs/amv_winning__20260928T141655Z__0456a927/inputs/601288.SH.csv](../../../data/backtest_runs/amv_winning__20260928T141655Z__0456a927/inputs/601288.SH.csv)
  - [data/backtest_runs/amv_winning__20260928T141655Z__0456a927/inputs/dividends_601288.csv](../../../data/backtest_runs/amv_winning__20260928T141655Z__0456a927/inputs/dividends_601288.csv)
- 关键结果文件：
  - [data/backtest_runs/amv_winning_defensive_3d__20260929T043926Z__641076dd/amv_signals.csv](../../../data/backtest_runs/amv_winning_defensive_3d__20260929T043926Z__641076dd/amv_signals.csv)
  - [data/backtest_runs/amv_winning_defensive_3d__20260929T043926Z__641076dd/annual_returns.csv](../../../data/backtest_runs/amv_winning_defensive_3d__20260929T043926Z__641076dd/annual_returns.csv)
  - [data/backtest_runs/amv_winning_defensive_3d__20260929T043926Z__641076dd/comparison_nav.csv](../../../data/backtest_runs/amv_winning_defensive_3d__20260929T043926Z__641076dd/comparison_nav.csv)
  - [data/backtest_runs/amv_winning_defensive_3d__20260929T043926Z__641076dd/metrics.json](../../../data/backtest_runs/amv_winning_defensive_3d__20260929T043926Z__641076dd/metrics.json)
  - [data/backtest_runs/amv_winning_defensive_3d__20260929T043926Z__641076dd/nav.csv](../../../data/backtest_runs/amv_winning_defensive_3d__20260929T043926Z__641076dd/nav.csv)
  - [data/backtest_runs/amv_winning_defensive_3d__20260929T043926Z__641076dd/paired_trades.csv](../../../data/backtest_runs/amv_winning_defensive_3d__20260929T043926Z__641076dd/paired_trades.csv)
  - [data/backtest_runs/amv_winning_defensive_3d__20260929T043926Z__641076dd/primary_trades.csv](../../../data/backtest_runs/amv_winning_defensive_3d__20260929T043926Z__641076dd/primary_trades.csv)
  - [data/backtest_runs/amv_winning_defensive_3d__20260929T043926Z__641076dd/signal_trade_stats.csv](../../../data/backtest_runs/amv_winning_defensive_3d__20260929T043926Z__641076dd/signal_trade_stats.csv)
  - [data/backtest_runs/amv_winning_defensive_3d__20260929T043926Z__641076dd/source_manifest.json](../../../data/backtest_runs/amv_winning_defensive_3d__20260929T043926Z__641076dd/source_manifest.json)
  - [data/backtest_runs/amv_winning_defensive_3d__20260929T043926Z__641076dd/trades.csv](../../../data/backtest_runs/amv_winning_defensive_3d__20260929T043926Z__641076dd/trades.csv)
  - [data/backtest_runs/amv_winning_defensive_3d__20260929T043926Z__641076dd/verification.json](../../../data/backtest_runs/amv_winning_defensive_3d__20260929T043926Z__641076dd/verification.json)

## 本次报告

### [data/backtest_runs/amv_winning_defensive_3d__20260929T043926Z__641076dd/report.md](../../../data/backtest_runs/amv_winning_defensive_3d__20260929T043926Z__641076dd/report.md)

# 农行直接防守策略：三日累计涨幅≥4.5%

实际区间 20200102—20251231；1454个交易日，初始资金 200,000 元。

仅将主仓两日累计≥4%入场替换为三日累计≥4.5%；单日≥4%、收盘≥MA5条件保留。
0AMV低于MA10或MACD死叉优先离场；复用原成交、仓位、止损、跟踪退出和农行8%净价差止盈规则。

| 版本 | 总收益 | 年化 | 最大回撤 | 夏普 | 期末资金 | 闭合交易数 |
|---|---:|---:|---:|---:|---:|---:|
| 原版：两日≥4% | 288.26% | 25.37% | -21.55% | 1.467 | 776,526.58 | 87 |
| 新版：三日≥4.5% | 264.64% | 24.06% | -28.41% | 1.424 | 729,279.42 | 93 |

## 年度收益

| 年份 | 原版 | 新版 |
|---|---:|---:|
| 2020 | 1.71% | 2.34% |
| 2021 | 2.20% | -9.47% |
| 2022 | -0.94% | 0.41% |
| 2023 | 35.85% | 43.90% |
| 2024 | 105.88% | 99.26% |
| 2025 | 34.81% | 36.70% |

## 成交口径与限制

legacy_same_close_idealized：收盘确定信号、同日收盘执行，是原策略的理想化假设。
主仓盘中2.5%硬止损、浮盈超过5%后次日起按前日实体低点退出；盘中退出当日不回买主仓。
仅0AMV收盘离场条件触发时直接买农行，不要求周线J。农行无止损，费用后净价差8%止盈，止盈后现金锁定直到有效主仓入场；单独主仓盘中退出后先持现金。
主仓100份、股票100股整手；税前现金分红按原模型除息日计入可用现金，不计入止盈阈值。
年化按365自然日，夏普按243交易日、零无风险利率。期末持仓按收盘价估值，不强制平仓。
固定旧印花税/过户费，未充分模拟股息税、到账延迟、涨跌停、停牌及成交容量。
输入、代码快照及SHA256在inputs/、code_snapshot/、source_manifest.json；baseline/为同输入重跑原版。
