# 最新运行报告：amv_winning_defensive_ma20_entry

- 任务类型：`strategy`
- 运行时间（UTC）：`2026-09-29T08:42:33.282838+00:00`
- 请求区间：`20200102` ～ `20251231`
- 运行目录：[data/backtest_runs/amv_winning_defensive_ma20_entry__20260929T084233Z__e4f4e6ad](../../../data/backtest_runs/amv_winning_defensive_ma20_entry__20260929T084233Z__e4f4e6ad)
- 运行清单：[data/backtest_runs/amv_winning_defensive_ma20_entry__20260929T084233Z__e4f4e6ad/run_manifest.json](../../../data/backtest_runs/amv_winning_defensive_ma20_entry__20260929T084233Z__e4f4e6ad/run_manifest.json)
- 输入数据：
  - [data/backtest_runs/amv_winning_defensive_second_entry__20260929T074431Z__d81ce173/inputs/0AMV.csv](../../../data/backtest_runs/amv_winning_defensive_second_entry__20260929T074431Z__d81ce173/inputs/0AMV.csv)
  - [data/backtest_runs/amv_winning_defensive_second_entry__20260929T074431Z__d81ce173/inputs/512100.SH.csv](../../../data/backtest_runs/amv_winning_defensive_second_entry__20260929T074431Z__d81ce173/inputs/512100.SH.csv)
  - [data/backtest_runs/amv_winning_defensive_second_entry__20260929T074431Z__d81ce173/inputs/601288.SH.csv](../../../data/backtest_runs/amv_winning_defensive_second_entry__20260929T074431Z__d81ce173/inputs/601288.SH.csv)
  - [data/backtest_runs/amv_winning_defensive_second_entry__20260929T074431Z__d81ce173/inputs/dividends_601288.csv](../../../data/backtest_runs/amv_winning_defensive_second_entry__20260929T074431Z__d81ce173/inputs/dividends_601288.csv)
- 关键结果文件：
  - [data/backtest_runs/amv_winning_defensive_ma20_entry__20260929T084233Z__e4f4e6ad/amv_signals.csv](../../../data/backtest_runs/amv_winning_defensive_ma20_entry__20260929T084233Z__e4f4e6ad/amv_signals.csv)
  - [data/backtest_runs/amv_winning_defensive_ma20_entry__20260929T084233Z__e4f4e6ad/annual_returns.csv](../../../data/backtest_runs/amv_winning_defensive_ma20_entry__20260929T084233Z__e4f4e6ad/annual_returns.csv)
  - [data/backtest_runs/amv_winning_defensive_ma20_entry__20260929T084233Z__e4f4e6ad/comparison_nav.csv](../../../data/backtest_runs/amv_winning_defensive_ma20_entry__20260929T084233Z__e4f4e6ad/comparison_nav.csv)
  - [data/backtest_runs/amv_winning_defensive_ma20_entry__20260929T084233Z__e4f4e6ad/metrics.json](../../../data/backtest_runs/amv_winning_defensive_ma20_entry__20260929T084233Z__e4f4e6ad/metrics.json)
  - [data/backtest_runs/amv_winning_defensive_ma20_entry__20260929T084233Z__e4f4e6ad/nav.csv](../../../data/backtest_runs/amv_winning_defensive_ma20_entry__20260929T084233Z__e4f4e6ad/nav.csv)
  - [data/backtest_runs/amv_winning_defensive_ma20_entry__20260929T084233Z__e4f4e6ad/paired_trades.csv](../../../data/backtest_runs/amv_winning_defensive_ma20_entry__20260929T084233Z__e4f4e6ad/paired_trades.csv)
  - [data/backtest_runs/amv_winning_defensive_ma20_entry__20260929T084233Z__e4f4e6ad/primary_trades.csv](../../../data/backtest_runs/amv_winning_defensive_ma20_entry__20260929T084233Z__e4f4e6ad/primary_trades.csv)
  - [data/backtest_runs/amv_winning_defensive_ma20_entry__20260929T084233Z__e4f4e6ad/signal_trade_stats.csv](../../../data/backtest_runs/amv_winning_defensive_ma20_entry__20260929T084233Z__e4f4e6ad/signal_trade_stats.csv)
  - [data/backtest_runs/amv_winning_defensive_ma20_entry__20260929T084233Z__e4f4e6ad/source_manifest.json](../../../data/backtest_runs/amv_winning_defensive_ma20_entry__20260929T084233Z__e4f4e6ad/source_manifest.json)
  - [data/backtest_runs/amv_winning_defensive_ma20_entry__20260929T084233Z__e4f4e6ad/trades.csv](../../../data/backtest_runs/amv_winning_defensive_ma20_entry__20260929T084233Z__e4f4e6ad/trades.csv)
  - [data/backtest_runs/amv_winning_defensive_ma20_entry__20260929T084233Z__e4f4e6ad/verification.json](../../../data/backtest_runs/amv_winning_defensive_ma20_entry__20260929T084233Z__e4f4e6ad/verification.json)

## 本次报告

### [data/backtest_runs/amv_winning_defensive_ma20_entry__20260929T084233Z__e4f4e6ad/report.md](../../../data/backtest_runs/amv_winning_defensive_ma20_entry__20260929T084233Z__e4f4e6ad/report.md)

# 农行直接防守：单日≥4%或MA20上穿后5日确认

区间 20200102—20251231，1454个交易日，初始资金 200,000 元。

第二买点：0AMV上穿MA20，从上穿当日起5个交易日内首次同时满足三日动量>4%且收盘>MA60。两种买点均要求收盘≥MA5、离场优先，全仓整手买512100；同时满足时归因于原单日买点。

| 入场规则 | 总收益 | 年化 | 最大回撤 | 夏普 | 主仓买入次数 | 主仓闭合胜率 |
|---|---:|---:|---:|---:|---:|---:|
| 仅单日 | 391.21% | 30.38% | -18.49% | 1.877 | 32 | 65.62% |
| 单日+MA20确认 | 320.69% | 27.06% | -20.82% | 1.630 | 38 | 57.89% |

## 主仓完整交易归因

| variant      | entry_branch         |   closed_positions |   wins |   win_rate_pct |   avg_net_pnl_pct |   total_pnl |
|:-------------|:---------------------|-------------------:|-------:|---------------:|------------------:|------------:|
| second_entry | ma20_confirmation_5d |                  8 |      1 |          12.50 |             -1.12 |    -3261.73 |
| second_entry | single_day_ge_4pct   |                 30 |     21 |          70.00 |              2.80 |   278139.78 |
| single_day   | single_day_ge_4pct   |                 32 |     21 |          65.62 |              2.46 |   318025.95 |

## 年度收益

|    year |   second_entry_return_pct |   single_day_return_pct |
|--------:|--------------------------:|------------------------:|
| 2020.00 |                      4.73 |                    6.04 |
| 2021.00 |                     -5.97 |                   10.82 |
| 2022.00 |                     14.50 |                   17.53 |
| 2023.00 |                     28.28 |                   27.39 |
| 2024.00 |                    131.72 |                  132.19 |
| 2025.00 |                     25.52 |                   20.23 |

## 执行与限制

两组均信号收盘确认、下一共同交易日开盘执行，主仓买入日不可卖出。期末信号不执行。
0AMV低于MA10或MACD死叉优先离场转农行；主仓盘中2.5%硬止损，盈利超过5%后按原规则激活前日实体低点跟踪退出。盘中退出取消当日主仓买入信号。
农行无止损、费用后净价差8%止盈，股息不计入阈值；止盈后持现金直到主仓买点。
年化按365自然日，夏普按243交易日。100份/股整手、费用、主仓份额合并及农行税前现金分红沿用原模型，ETF现金派息未单独记账。未完整模拟股息税、到账延迟、停牌涨跌停和成交容量。新增交易盈亏不等于组合相对基线的增量收益。
根目录为实验组，baseline/为同口径单日组；inputs/、code_snapshot/和source_manifest.json保存本次输入、代码及SHA256。
