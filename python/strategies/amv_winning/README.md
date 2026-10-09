# 0AMV 必胜策略：离场后择机持有农业银行

正式入口：`./scripts/backtest.sh run strategy amv_winning`。默认主仓 `512100.SH`，备选持仓改为农业银行 `601288.SH`，**8% 固定价格止盈、无止损**。配置见 [config.yaml](config.yaml)；`bank_take_profit: false` 可关闭固定止盈。

## 交易规则

主仓保留原规则：0AMV 单日或两日累计上涨至少 4%，且收盘不低于 MA5 时进场；跌破 MA10 或 MACD 死叉时离场。同日进出场信号冲突以离场优先。主仓买入后执行 2.5% 盘中硬止损；盘中涨幅超过 5% 后，从下一交易日起以昨日 K 线实体下沿跟踪止盈。

主仓因任何规则实际卖出后，开始观察农业银行；回测开始尚未首次持有主仓时保持现金。每日收盘使用农业银行自身截至当天的本周最高、最低、收盘价计算动态周线 KDJ(9,3,3)，J **严格小于 10** 且没有有效主仓进场信号时，以全部可用现金买入农行，整百股取整并预留费用。使用 2019 年起、回测起点前的行情预热；不足 9 根周线不买入。每天临时周线从上一完整周 K、D 递推，不重复累计周内读数。

有效主仓进场信号优先：先按当天收盘价全部卖出农行，再按原规则买入主仓。持有农行期间，J 回升、重复的 0AMV 离场信号和价格下跌均不触发独立卖出。分红留在现金，不自动追加农行股份。期末持仓按收盘价估值，不强制卖出。

默认 8% 止盈以含买入滑点的成交价 ×1.08 为目标，向上取整到 0.01 元，分红不参与目标价计算。买入后的下一交易日起检查 5 分钟 K 线：开盘越过目标按开盘价卖出，否则最高价触及目标按目标价卖出；另计卖出滑点和费用，净收益不保证为 8%。止盈当天不回买农行，有效主仓进场仍优先；下一交易日收盘满足 J<10 时可再次买入。

## 行情、费用与分红

复用相邻 [amv_winning_defensive](../amv_winning_defensive/README.md) 的 `data/backtest_data/5m_price/YYYY/YYYYMMDD.parquet` 农行数据和 [分红表](../amv_winning_defensive/dividends_601288.csv)。按代码过滤读取，检查每个交易日完整 48/49 根 K 线，并逐日核对价格与成交额/成交量。2024 年 7 个已核实交易日的成交量放大 100 倍，读取副本按成交均价核对后修正，原 parquet 不修改，修正记录在 `source_manifest.json`。校验支持农行行情为未复权价格；旧通用审计脚本“已确认前复权”的说明不适用于这批农行行情。

成交、估值使用原始行情；动态周线指标在每笔现金分红生效日起乘以前收盘价÷（前收盘价−每股分红），使除息前后价格连续，不用未来分红重写过去的 J。默认分红表核对范围为 2019—2025，超过范围需提供完整的新分红表。农行不使用银行 ETF 的 2025 年份额拆分；主仓 2022-09-02 份额合并处理保留。

沿用相邻策略固定费用口径：主仓 `FeeConfig.etf_legacy()`，农行卖出印花税 0.001、双向过户费 0.00001，佣金、最低佣金、滑点默认跟随统一入口；农行专属费用可通过 YAML `bank_fees` 覆盖。实际费用记录在 `metrics.json` 的 `fees`、`bank_fees`；该模型未按年份调整历史税率。

仅前一交易日收盘持有的农行股份在除息日领取税前现金分红，除息日新买入不领取；现金只记一次，所属交易 PnL 包含分红。沿用相邻策略除息日到账口径；例如 [2020 年公告](https://www.abchina.com/cn/aboutabc/investor_relations/announcements/a-announcement/202007/P020200706324872175526.pdf)与 [2025 年末期分红公告](https://www.abchina.com/cn/AboutABC/investor_relations/announcements/a-announcement/202507/P020250708628470506905.pdf)均列明除息日与派息同日。**未扣个人股息税**。

## 运行与产物

```bash
./scripts/backtest.sh run strategy amv_winning --start 20200101 --end 20251231
# 自定义配置，可将 bank_take_profit 改为 false 做无止盈对照
./scripts/backtest.sh run strategy amv_winning --config /path/to/config.yaml \
  --start 20200101 --end 20251231
```

直接 runner 默认也使用农行 +8% 止盈。需要做无止盈对照时：

```bash
/home/wang/python_env/B1_RATE/bin/python -m python.strategies.amv_winning.runner \
  --no-bank-take-profit --start 20200101 --end 20251231 \
  --output-dir data/backtest_runs/amv_winning_abc_no_tp \
  --report-path data/backtest_runs/amv_winning_abc_no_tp/report.md
```

运行目录保存交易、NAV、年度收益、动态周线 KDJ、参数、指标及报告。`position_quantity` 表示主仓数量，`bank_quantity` 表示备选持仓数量，`position_code` 标明实际代码；农行版本增加累计 `dividend_income`。交易列记录股票过户费、卖出印花税及所属现金分红。期末未平仓信息在 `metrics.json`。`inputs/` 保存农行完整预热行情、主仓/0AMV 原始输入和分红表；`code_snapshot/`、`source_manifest.json` 保存运行代码与 SHA-256。

`original_nav.csv`、`original_trades.csv` 保存同数据、日期和主仓费用下的原纯现金版本；报告比较改造后、原纯现金及主仓买入持有。主仓交易日缺农行行情会报错，不静默取交集。

旧 `run_full_position_backtest()` 保留纯现金行为。旧 `run_bank_kdj_backtest()`、`run_research()` 的 Python API 默认仍为 `512800.SH` 银行 ETF +8% 止盈，以便复现已有对照；调用时传 `bank_code="601288.SH"` 即使用农行，缺省保留 8% 止盈。直接 runner 传 `--bank-code 512800.SH` 可复现 ETF，`--no-bank-take-profit` 可做 ETF 无止盈对照。

沿用“收盘后确认信号、按当日收盘成交”的理想化口径，清单标记 `legacy_same_close_idealized`。农行收盘买入、最早次日卖出满足本策略的 T+1 时序；未模拟盘口容量、涨跌停无法成交或个人股息税，结果不能直接视为可复制的实盘收益。
