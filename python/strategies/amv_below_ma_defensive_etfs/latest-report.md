# 最新运行报告：amv_below_ma_defensive_etfs

- 任务类型：`strategy`
- 运行时间（UTC）：`2026-09-28T08:59:39.264668+00:00`
- 请求区间：`20220516` ～ `20251231`
- 运行目录：[data/backtest_runs/amv_below_ma_defensive_etfs__20260928T085939Z__4f1b0c11](../../../data/backtest_runs/amv_below_ma_defensive_etfs__20260928T085939Z__4f1b0c11)
- 运行清单：[data/backtest_runs/amv_below_ma_defensive_etfs__20260928T085939Z__4f1b0c11/run_manifest.json](../../../data/backtest_runs/amv_below_ma_defensive_etfs__20260928T085939Z__4f1b0c11/run_manifest.json)
- 输入数据：
  - [data/backtest_data/0AMV-260612.csv](../../../data/backtest_data/0AMV-260612.csv)
  - [data/backtest_data/ETF_60min_2005_2025/512800.SH.csv](../../../data/backtest_data/ETF_60min_2005_2025/512800.SH.csv)
  - [data/backtest_data/ETF_60min_2005_2025/561560.SH.csv](../../../data/backtest_data/ETF_60min_2005_2025/561560.SH.csv)
  - [data/backtest_data/ETF_60min_2005_2025/515220.SH.csv](../../../data/backtest_data/ETF_60min_2005_2025/515220.SH.csv)
  - [data/backtest_data/ETF_60min_2005_2025/512890.SH.csv](../../../data/backtest_data/ETF_60min_2005_2025/512890.SH.csv)
  - [data/backtest_data/ETF_60min_2005_2025/510300.SH.csv](../../../data/backtest_data/ETF_60min_2005_2025/510300.SH.csv)
  - [python/strategies/amv_below_ma_defensive_etfs/corporate_actions.csv](corporate_actions.csv)
  - [python/strategies/amv_below_ma_defensive_etfs/corporate_action_audit.json](corporate_action_audit.json)
- 关键结果文件：
  - [data/backtest_runs/amv_below_ma_defensive_etfs__20260928T085939Z__4f1b0c11/annual_returns.csv](../../../data/backtest_runs/amv_below_ma_defensive_etfs__20260928T085939Z__4f1b0c11/annual_returns.csv)
  - [data/backtest_runs/amv_below_ma_defensive_etfs__20260928T085939Z__4f1b0c11/corporate_action_audit.json](../../../data/backtest_runs/amv_below_ma_defensive_etfs__20260928T085939Z__4f1b0c11/corporate_action_audit.json)
  - [data/backtest_runs/amv_below_ma_defensive_etfs__20260928T085939Z__4f1b0c11/corporate_action_ledger.csv](../../../data/backtest_runs/amv_below_ma_defensive_etfs__20260928T085939Z__4f1b0c11/corporate_action_ledger.csv)
  - [data/backtest_runs/amv_below_ma_defensive_etfs__20260928T085939Z__4f1b0c11/episodes.csv](../../../data/backtest_runs/amv_below_ma_defensive_etfs__20260928T085939Z__4f1b0c11/episodes.csv)
  - [data/backtest_runs/amv_below_ma_defensive_etfs__20260928T085939Z__4f1b0c11/execution_metadata.json](../../../data/backtest_runs/amv_below_ma_defensive_etfs__20260928T085939Z__4f1b0c11/execution_metadata.json)
  - [data/backtest_runs/amv_below_ma_defensive_etfs__20260928T085939Z__4f1b0c11/nav.csv](../../../data/backtest_runs/amv_below_ma_defensive_etfs__20260928T085939Z__4f1b0c11/nav.csv)
  - [data/backtest_runs/amv_below_ma_defensive_etfs__20260928T085939Z__4f1b0c11/summary.csv](../../../data/backtest_runs/amv_below_ma_defensive_etfs__20260928T085939Z__4f1b0c11/summary.csv)
  - [data/backtest_runs/amv_below_ma_defensive_etfs__20260928T085939Z__4f1b0c11/trades.csv](../../../data/backtest_runs/amv_below_ma_defensive_etfs__20260928T085939Z__4f1b0c11/trades.csv)

## 本次报告

### [data/backtest_runs/amv_below_ma_defensive_etfs__20260928T085939Z__4f1b0c11/report.md](../../../data/backtest_runs/amv_below_ma_defensive_etfs__20260928T085939Z__4f1b0c11/report.md)

# 0AMV 低于 MA30、MA60 时的防守 ETF 回测

区间：2022-05-16—2025-12-31，885 个交易日；每组初始资金 200,000 元。
MA30、MA60 分别独立回测。0AMV 收盘低于对应简单均线，下一交易日开盘买入；回到均线上或相等，下一交易日开盘卖出。首日依据区间前一交易日信号建仓。

## 四只 ETF 主结果

| ETF   | 代码        | 规则   |   含分红收益% |   年化% |   最大回撤% |   已结束区间 |   区间胜率% |   持仓时间% |    分红收入元 |   分红补买次数 |
|:------|:----------|:-----|---------:|------:|--------:|--------:|--------:|--------:|---------:|---------:|
| 银行    | 512800.SH | ma30 |    28.84 |  7.23 |  -13.74 |      27 |   55.56 |   57.51 |     0.00 |        0 |
| 电力    | 561560.SH | ma30 |    -5.12 | -1.44 |  -21.12 |      27 |   44.44 |   57.51 |     0.00 |        0 |
| 煤炭    | 515220.SH | ma30 |   -20.76 | -6.21 |  -42.95 |      27 |   51.85 |   57.51 | 20646.00 |        3 |
| 红利低波  | 512890.SH | ma30 |    15.50 |  4.05 |  -17.33 |      27 |   62.96 |   57.51 |     0.00 |        0 |
| 银行    | 512800.SH | ma60 |    21.63 |  5.54 |  -12.59 |      14 |   64.29 |   54.01 |     0.00 |        0 |
| 电力    | 561560.SH | ma60 |    -9.17 | -2.62 |  -22.44 |      14 |   64.29 |   54.01 |     0.00 |        0 |
| 煤炭    | 515220.SH | ma60 |   -27.70 | -8.55 |  -44.05 |      14 |   57.14 |   54.01 | 21068.00 |        4 |
| 红利低波  | 512890.SH | ma60 |    -0.15 | -0.04 |  -17.17 |      14 |   50.00 |   54.01 |     0.00 |        0 |

## 同期基准与超额收益

`buy_hold` 为首日开盘买入并再投资分红；现金为零收益。超额收益单位为百分点，分别对比自身买入持有和 510300 同均线择时。

| name   | code      | mode     |   total_return_pct |   max_drawdown_pct |   dividend_income |   excess_buy_hold_pp |   excess_market_timing_pp |
|:-------|:----------|:---------|-------------------:|-------------------:|------------------:|---------------------:|--------------------------:|
| 银行     | 512800.SH | ma30     |              28.84 |             -13.74 |              0.00 |               -20.87 |                     34.65 |
| 电力     | 561560.SH | ma30     |              -5.12 |             -21.12 |              0.00 |               -25.18 |                      0.68 |
| 煤炭     | 515220.SH | ma30     |             -20.76 |             -42.95 |          20646.00 |               -28.29 |                    -14.96 |
| 红利低波   | 512890.SH | ma30     |              15.50 |             -17.33 |              0.00 |               -23.82 |                     21.30 |
| 沪深300  | 510300.SH | ma30     |              -5.81 |             -21.10 |           6339.90 |               -31.62 |                      0.00 |
| 银行     | 512800.SH | ma60     |              21.63 |             -12.59 |              0.00 |               -28.08 |                     26.72 |
| 电力     | 561560.SH | ma60     |              -9.17 |             -22.44 |              0.00 |               -29.23 |                     -4.08 |
| 煤炭     | 515220.SH | ma60     |             -27.70 |             -44.05 |          21068.00 |               -35.23 |                    -22.61 |
| 红利低波   | 512890.SH | ma60     |              -0.15 |             -17.17 |              0.00 |               -39.46 |                      4.94 |
| 沪深300  | 510300.SH | ma60     |              -5.09 |             -21.50 |          10692.60 |               -30.90 |                      0.00 |
| 银行     | 512800.SH | buy_hold |              49.71 |             -17.26 |              0.00 |                 0.00 |                    nan    |
| 电力     | 561560.SH | buy_hold |              20.06 |             -15.69 |              0.00 |                 0.00 |                    nan    |
| 煤炭     | 515220.SH | buy_hold |               7.53 |             -29.41 |          25237.00 |                 0.00 |                    nan    |
| 红利低波   | 512890.SH | buy_hold |              39.31 |             -13.79 |              0.00 |                 0.00 |                    nan    |
| 沪深300  | 510300.SH | buy_hold |              25.81 |             -26.84 |          11243.40 |                 0.00 |                    nan    |
| 现金     | CASH      | cash     |               0.00 |               0.00 |              0.00 |               nan    |                    nan    |

## 分红与执行口径

登记日收盘确定分红资格，除息日记应收款，到账日收盘转入现金。若仍满足持有条件，下一交易日开盘使用分红和剩余现金补买；退出优先。不足一手余额等待后续派息或开仓。
分红金额是账户实际获得的 ETF 派息，成份股分红留存在基金中的部分已反映在基金资产中。基金年报核实银行、电力、红利低波在本区间没有向持有人现金派息；煤炭及沪深300派息已逐笔核算。
银行和煤炭的 1:2 份额拆分已按登记日资格调整份额及单位成本，避免将价格折半当作亏损。现金、持仓市值及应收分红共同组成净值，到账和再投资不会再次确认收入。
本次费用：{"commission_rate": 0.0003, "min_commission": 5.0, "stamp_duty_rate": 0.0, "transfer_fee_rate": 0.0, "slippage_rate": 0.001}。按100份买入，按批次检查T+1。费用覆盖也作用于所有非现金基准。
区间胜率按完整持有区间计算，分红补买仍属于同一区间；期末未卖出区间单独列示。持有区间收益按该区间账户财富变化计算，包含现金及应收款。
年化采用自然日365天口径；夏普采用252个交易日、无风险收益为零。每日最大回撤包含初始资金基线。

## 年度收益

|    year |   510300.SH_buy_hold |   510300.SH_ma30 |   510300.SH_ma60 |   512800.SH_buy_hold |   512800.SH_ma30 |   512800.SH_ma60 |   512890.SH_buy_hold |   512890.SH_ma30 |   512890.SH_ma60 |   515220.SH_buy_hold |   515220.SH_ma30 |   515220.SH_ma60 |   561560.SH_buy_hold |   561560.SH_ma30 |   561560.SH_ma60 |   cash |
|--------:|---------------------:|-----------------:|-----------------:|---------------------:|-----------------:|-----------------:|---------------------:|-----------------:|-----------------:|---------------------:|-----------------:|-----------------:|---------------------:|-----------------:|-----------------:|-------:|
| 2022.00 |                -1.68 |           -12.41 |            -7.48 |                -1.95 |           -10.24 |            -8.28 |                -3.09 |            -1.67 |            -4.28 |                 1.03 |             3.07 |             2.93 |                 2.24 |             4.20 |             2.30 |   0.00 |
| 2023.00 |                -9.76 |             1.31 |             2.59 |                -3.34 |             3.28 |             0.30 |                11.73 |             6.07 |             1.73 |                10.99 |            -5.26 |             4.04 |                 1.94 |            -9.49 |            -4.23 |   0.00 |
| 2024.00 |                17.40 |             1.39 |            -5.17 |                42.51 |            22.38 |            17.23 |                22.97 |             5.60 |             2.10 |                 1.77 |            -8.78 |           -10.44 |                13.77 |             2.39 |            -0.50 |   0.00 |
| 2025.00 |                20.78 |             4.70 |             5.45 |                10.84 |            13.58 |            12.79 |                 4.63 |             4.86 |             0.45 |                -5.78 |           -11.04 |           -24.61 |                 1.25 |            -1.75 |            -6.82 |   0.00 |

## 曲线

![MA30 NAV and drawdown](/home/wang/workspace/TradePilot_backtest/data/backtest_runs/amv_below_ma_defensive_etfs__20260928T085939Z__4f1b0c11/ma30_nav_drawdown.png)

![MA60 NAV and drawdown](/home/wang/workspace/TradePilot_backtest/data/backtest_runs/amv_below_ma_defensive_etfs__20260928T085939Z__4f1b0c11/ma60_nav_drawdown.png)

## 数据与复现

行情为未复权价格；分红/拆分表与来源核对记录见 corporate_action_audit.json。原始输入和运行代码快照及 SHA-256 见 execution_metadata.json 和 source_snapshot/；统一入口另生成 run_manifest.json。

- 银行（512800.SH）：核对 0 次现金派息、1 次拆分。[来源1](https://static.cninfo.com.cn/finalpage/2024-03-29/1219454067.PDF)、[来源2](https://www.sse.com.cn/disclosure/fund/announcement/c/new/2026-03-31/512800_20260331_88RL.pdf)、[来源3](https://www.sse.com.cn/disclosure/fund/announcement/c/new/2025-07-07/512800_20250707_PJ9L.pdf)
- 电力（561560.SH）：核对 0 次现金派息、0 次拆分。[来源1](https://pdf.dfcfw.com/pdf/H2_AN202403291629062999_1.pdf)、[来源2](https://www.sse.com.cn/disclosure/fund/announcement/c/new/2026-03-31/561560_20260331_8W1D.pdf)、[来源3](https://fund.eastmoney.com/561560.html)
- 红利低波（512890.SH）：核对 0 次现金派息、0 次拆分。[来源1](https://www.sse.com.cn/disclosure/fund/announcement/c/new/2025-03-31/512890_20250331_101D.pdf)、[来源2](https://www.sse.com.cn/disclosure/fund/announcement/c/new/2026-03-31/512890_20260331_5BME.pdf)
- 煤炭（515220.SH）：核对 4 次现金派息、1 次拆分。[来源1](https://www.sse.com.cn/disclosure/fund/announcement/c/new/2023-03-30/515220_20230330_XWGO.pdf)、[来源2](https://www.sse.com.cn/disclosure/fund/announcement/c/new/2023-12-26/515220_20231226_XFT5.pdf)、[来源3](https://www.sse.com.cn/disclosure/fund/announcement/c/new/2024-12-19/515220_20241219_H6AW.pdf)、[来源4](https://pdf.dfcfw.com/pdf/H2_AN202603291820839907_1.pdf)、[来源5](https://www.sse.com.cn/disclosure/fund/announcement/c/new/2024-04-12/515220_20240412_5CZN.pdf)、[来源6](https://fundf10.eastmoney.com/fhsp_515220.html)、[来源7](https://quote.cfi.cn/jjsyfp/101779/515220.html)
- 沪深300（510300.SH）：核对 3 次现金派息、0 次拆分。[来源1](https://www.sse.com.cn/disclosure/fund/announcement/c/new/2023-01-09/510300_20230109_0ED5.pdf)、[来源2](https://pdf.dfcfw.com/pdf/H2_AN202408301639638994_1.pdf)、[来源3](https://3g.zszq.com/about/notice?id=FHeP2sOG)、[来源4](https://www.sse.com.cn/disclosure/fund/announcement/c/new/2025-06-11/510300_20250611_ZAU4.pdf)、[来源5](https://www.sse.com.cn/disclosure/fund/announcement/c/new/2026-01-12/510300_20260112_VTCZ.pdf)、[来源6](https://fundf10.eastmoney.com/fhsp_510300.html)

本回测使用日开盘作为成交价格，未模拟涨跌停成交限制、盘口容量和订单排队。数据覆盖缺口会报错。2022年为5月16日起的部分年度。
