# 0AMV 必胜策略：离场后防守


`./scripts/backtest.sh run strategy amv_winning_defensive --start 20190118 --end 20251231`

同一批交易日分别测试红利低波 ETF `512890.SH` 和农业银行 `601288.SH`。只有 0AMV 日线收盘确认 MA10 跌破或 MACD 死叉时，才卖出主仓 `512100.SH` 并在当天尾盘买入防守标的。主仓盘中触发 2.5% 硬止损或盈利后实体低点跟踪止盈时，卖出后持现金；如果同日收盘又出现 0AMV 离场信号，则转入防守仓。下一次有效买入信号在尾盘卖出仍持有的防守仓、买回主仓。同日进出场条件并存时离场优先；防守仓不设独立止损。满仓按 100 份/股取整。

农业银行仓位从买入后的交易日起，若 5 分钟 K 线触及扣除买卖费用后的**价差净收益 +8%**，全仓止盈；跳空越过阈值按开盘价成交，否则按阈值价成交。止盈后持现金，连续 0AMV 离场信号不再买入银行，直到下一次有效 0AMV 买入信号转回 `512100.SH`。防守仓仍无独立止损，红利低波 ETF 不使用这条止盈规则。

ETF 使用 ETF 费用；农业银行另计股票印花税、过户费和公开公告的现金分红（`dividends_601288.csv`，仅持仓跨过股权登记日才在除息日入账；卖出时不重复计入现金，未扣个人股息税）。分红不参与 +8% 止盈判断。红利低波 ETF 的 2021-10-22 1:2 份额拆分已调整持仓，依据[上交所基金年报](https://www.sse.com.cn/disclosure/fund/announcement/c/new/2022-03-31/512890_20220331_2_9usASAs5.pdf)。其现金分红暂按零处理。共同交易日会排除 512890 停牌的拆分日 2021-10-22。

`report.md`、`metrics.json`、`nav.csv` 和三份逐笔交易文件记录两个版本及原版同期结果。`code_snapshot/` 保存本次执行的策略及依赖代码和 SHA-256，便于在工作区有未提交文件时核对版本。0AMV 收盘信号与收盘成交同日发生，属于理想化口径；回测未模拟尾盘流动性冲击、涨跌停和股息税。

## 2026 年数据补齐与回测

当前同口径 0AMV 数据只到 2026-06-29，因此可完整回测的 2026 年区间止于该日。运行以下命令生成独立输入快照，并通过配置指定这些输入；不会覆盖原有历史行情：

```bash
/home/wang/python_env/B1_RATE/bin/python -m python.strategies.amv_winning_defensive.prepare_2026
./scripts/backtest.sh run strategy amv_winning_defensive \
  --config data/backtest_data/amv_winning_defensive_2026_h1/config.yaml \
  --start 20260101 --end 20260629
```

快照使用本地农行 5 分钟行情至 2026-04-10，之后从腾讯分钟接口按历史时间戳分页获取；两只 ETF 的 60 分钟行情同样从腾讯获取。准备脚本会检查每日 K 线覆盖，并在衔接日期核对农行日 OHLC。`source_manifest.json` 记录源文件与生成文件的 SHA-256。2026-05-13 的农业银行每股 0.13 元分红按[公司 A 股分红公告](https://www.abchina.com/cN/aboutabc/investor_relations/announcements/a-announcement/202605/P020260506662272685289.pdf)补入快照，仍只在实际持仓跨过股权登记日时计入。
