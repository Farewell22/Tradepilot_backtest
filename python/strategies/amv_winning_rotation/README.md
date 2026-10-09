# 0AMV 必胜策略：死叉轮动

运行：

```bash
./scripts/backtest.sh run strategy amv_winning_rotation --start 20200302 --end 20251231
```

使用 0AMV 日线生成原策略的买入、MA10 退出和 MACD 死叉信号。512100.SH 的买入、2.5% 硬止损及盈利超过 5% 后的移动止盈沿用 `amv_winning`。0AMV MACD 死叉当天，卖出 512100.SH（如有），将当时可用资金各按 50% 买入红利 ETF `510880.SH` 和煤炭 ETF `515220.SH`；若已持有这两只 ETF，不重复调仓。下一次原策略买入信号成立且当天没有 MA10 退出或死叉时，卖出两只 ETF 并切回 512100.SH。仅有 MA10 退出时，512100.SH 清仓后保持现金。防守 ETF 期间不设额外止损或定期再平衡。

信号日收盘成交沿用原策略的理想化口径。所有交易按 ETF 费用模型计佣金和双向滑点，买入数量按 100 份取整。只回测 0AMV 与三只 ETF 都有行情的共同交易日；煤炭 ETF 数据从 2020-03-02 开始。`nav.csv` 包含轮动与原策略同期 NAV，`trades.csv` 是轮动逐笔委托，`metrics.json` 和 `report.md` 为同期对照结果。回测按权益登记日确认现金分红，在除息日起计入应收款、发放日计入可用现金；煤炭 ETF 在 2024-04-12 的 1:2 拆分同步调整持仓份额。权益分派和拆分依据基金公告及年度报告，例如 [煤炭 ETF 拆分公告](https://www.sse.com.cn/disclosure/fund/announcement/c/new/2024-04-12/515220_20240412_5CZN.pdf)、[煤炭 ETF 2022 年年报](https://www.sse.com.cn/disclosure/fund/announcement/c/new/2023-03-30/515220_20230330_XWGO.pdf) 和 [红利 ETF 2025 年年报](https://www.sse.com.cn/disclosure/fund/announcement/c/new/2026-03-31/510880_20260331_JVU4.pdf)。
