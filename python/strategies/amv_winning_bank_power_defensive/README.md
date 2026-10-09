# 0AMV 银行 ETF＋电力 ETF 各半防守

主仓为 `512100.SH`。0AMV 收盘信号触发离场（跌破 MA10 或 MACD 死叉）时，卖出主仓，并以可用现金的各 50% 买入 `512800.SH` 银行 ETF 与 `561560.SH` 电力 ETF。交易按整百份取整，未用完的资金留现金。防守期不再平衡；连续离场信号不重复建仓。下一次有效 0AMV 买入信号卖出两只防守 ETF，使用全部可用现金买回主仓。防守 ETF 没有独立止盈、止损；农行个股的 +8% 止盈不适用于本策略。

主仓沿用现有 2.5% 盘中硬止损及盈利后的跟踪止盈。主仓仅盘中止损时持现金，若同日收盘出现 0AMV 离场信号则转入双 ETF 防守。0AMV 信号收盘后才可确认，历史分支仍假设同日收盘成交，因此结果属于理想化口径。

`512800.SH` 于 2025-07-04 登记、2025-07-07 按 1:2 拆分；回测会在除权交易日前调整已持仓份额，避免将拆分误算成跌幅。[上交所拆分公告](https://www.sse.com.cn/disclosure/fund/announcement/c/new/2025-07-07/512800_20250707_PJ9L.pdf)。两只 ETF 的基金年报显示 2022—2025 区间未向 ETF 持有人作现金分配，因此不另计成分股派息：[银行 ETF 2023 年报](https://static.cninfo.com.cn/finalpage/2024-03-29/1219454067.PDF)、[银行 ETF 2025 年报](https://www.sse.com.cn/disclosure/fund/announcement/c/new/2026-03-31/512800_20260331_88RL.pdf)、[电力 ETF 2023 年报](https://pdf.dfcfw.com/pdf/H2_AN202403291629062999_1.pdf)、[电力 ETF 2025 年报](https://www.sse.com.cn/disclosure/fund/announcement/c/new/2026-03-31/561560_20260331_8W1D.pdf)。

电力 ETF 从 2022-05-16 才有上市行情，当前本地小时线截至 2025-12-31。统一入口会自动选三只 ETF 与 0AMV 的共同交易日，并在相同日期跑原版持现金策略作比较。默认使用 ETF 费用，包含佣金、最低佣金和滑点；不计股票印花税。

现金对照沿用原版独立 runner。原版与防守分支在主仓盘中止损后同日能否根据买入信号回补上有差异，因此两者的收益差不完全等于防守 ETF 的贡献。

```bash
./scripts/backtest.sh run strategy amv_winning_bank_power_defensive --start 20220516 --end 20251231
```

输出目录包含 `run_manifest.json`、`metrics.json`、`nav.csv`、`trades.csv`、`report.md`。改动成交时点或费用时，应在同一区间另跑对照，不可直接与旧运行的绝对收益比较。
