# 农行直接防守：三日累计涨幅入场

基于 `amv_winning_defensive` 的农业银行直接防守版本，新建独立策略入口
`amv_winning_defensive_3d`。主仓为中证1000ETF `512100.SH`，防守仓为农业银行
`601288.SH`，初始资金20万元。

唯一的信号修改是将0AMV两日累计涨幅≥4%替换为**三日累计涨幅≥4.5%**。
单日涨幅≥4%的强信号分支保留，不添加MA30过滤。三日涨幅按当日收盘与三个交易日前
收盘计算，即三个交易日的复合涨幅。入场仍要求0AMV收盘≥MA5；0AMV收盘低于MA10
或MACD死叉时退出优先。

复用原策略的模拟循环：主仓全仓买入，盘中2.5%硬止损，上涨超过5%后次日起按前日
实体低点跟踪退出；主仓盘中退出当天不再买回。0AMV收盘离场时直接全仓买农行；
单独盘中止损后先持现金。农行不要求周线J、不设止损；费用后的净价差达到8%时止盈，
股息不参与止盈阈值，止盈后现金锁定直到下一次有效主仓入场。

```bash
./scripts/backtest.sh list strategies
./scripts/backtest.sh run strategy amv_winning_defensive_3d --start 20200102 --end 20251231
```

`config.yaml` 可通过 `--config PATH` 替换。`paths.stock_data` 支持原始5分钟行情CSV，
或本项目按年份/日期分区的股票parquet目录；默认目录模式复用银行行情审计加载器。
主仓交易日必须有0AMV及农行行情，缺失直接报错。所有指标先用完整输入预热，再截取
请求日期。股票佣金与滑点沿用CLI费用，印花税、过户费可用 `bank_fees` 配置。

每次运行同时使用相同输入重跑原版，输出：

- 根目录：新版 `nav.csv`、买卖事件 `trades.csv`、已平仓 `paired_trades.csv`、
  主仓入场分支 `primary_trades.csv`、`metrics.json`、`amv_signals.csv`、`report.md`。
- `baseline/`：两日≥4%原版的同类结果；`comparison_nav.csv` 为逐日净值对照，
  `annual_returns.csv` 为两版年度收益，`signal_trade_stats.csv` 为入场分支胜率与平均收益。
- `inputs/`、`code_snapshot/`、`source_manifest.json`：输入、代码和SHA256快照；
  `run_manifest.json` 记录请求、配置、来源、费用及成交口径，`latest-report.md` 发布最新结果。

成交仍为 `legacy_same_close_idealized`：收盘才能确定的信号按同日收盘执行。
这是保留旧口径的对照实验，不可当作可实盘复制的收益。分红在模型除息日进入可用现金，
未扣个人股息税；固定旧税费、涨跌停与停牌成交、实际到账延迟和盘口容量尚未完整建模。
年化按365自然日，夏普按243交易日与零无风险利率，期末持仓按市值估值，不强制平仓。

2020—2025的首次同输入对照复现原版288.26%总收益、25.37%年化、-21.55%最大回撤；
新版为264.64%、24.06%、-28.41%。完整改动后的仅三日分支产生29笔已平仓主仓交易，
胜率37.93%、平均单笔净收益-0.33%。原交易初筛不包含新增或变化的入场机会，
不能替代本次完整回测；结果详情见 `latest-report.md`。
