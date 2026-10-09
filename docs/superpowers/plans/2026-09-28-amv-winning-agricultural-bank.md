# 农业银行备选持仓 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 将 amv_winning 正式入口的备选持仓替换为农业银行 601288.SH，默认保留 8% 固定止盈，并完成同期回测。

**Architecture:** 扩展现有共享持仓循环的标的、费用和现金分红参数，保留旧银行 ETF 和纯现金 API 的默认行为。正式入口读取同目录防守策略使用的农行 5 分钟 parquet 和分红表，指标使用截至当日已生效现金分红的连续价格，成交使用原始价格。

**Tech Stack:** Python、pandas、pyarrow、pytest、现有 FeeConfig 与统一回测入口。

**Spec:** 本文下述交易规则。

## 交易规则

- 主仓规则、原有同日收盘成交口径不变；任意实际主仓卖出后观察农行。
- 使用农行自身动态周线 KDJ(9,3,3)，每日收盘 J 严格小于 10 时用可用现金按 100 股取整买入；初始现金阶段不买农行。
- 默认 8% 固定价格止盈、无止损；无止盈可显式关闭；有效主仓进场优先，先清仓农行再按原规则买主仓。8% 价格止盈，目标价按股票最小 0.01 元向上取整，次日起检测。
- 农行不使用银行 ETF 的份额拆分。沿用相邻策略 stock_legacy 费用：股票卖出印花税 0.001、双向过户费 0.00001，佣金与滑点跟随主仓配置；明确不是历史税率调整模型。
- 沿用相邻策略已核对的分红表：前一交易日收盘持有者在除息日计入现金和所属交易收益，仅记一次，除息日新买者不领取；个人股息税未建模。2020 与 2025 公告确认除息与派息同日。
- 指标价格在现金分红生效日起乘以前收盘价 / (前收盘价 - 每股派息)，历史值不因未来分红改变；使用 2019 年起行情预热，标准分红表审计范围为 2019—2025。
- 原主仓交易日缺农行行情则报错，不静默删除交易日；保留运行使用的农行输入、分红和代码快照。

## Global Constraints

- 保留工作区已有改动，不提交或修改其他策略规则。
- 正式实现位于 python/strategies/amv_winning/，共享指标位于 python/factors/。
- 回测不能利用观察日以后的行情或公司行动改变观察日信号。

## Review Focus

- 股票不能套用 ETF 的拆分，费用必须按交易标的选择。
- 现金分红不能因已卖出或除息日新买错误领取，NAV 与交易 PnL 不重复入账。
- 动态 J 使用农行自身历史，开始日期截断不能丢失预热。
- 缺行情必须失败，配置与报告必须披露实际标的、费用和止盈开关。
- 旧 ETF 和纯现金版本的逐笔交易、NAV 保持相同。

### Task 1: 指标、股票持仓及分红

**Files:** 修改 z_indicators.py 和 amv_winning/runner.py；新增 test_amv_winning_agricultural_bank.py。

**Interfaces:** compute_dynamic_weekly_kdj(..., cash_dividends=None)；run_bank_kdj_backtest(..., bank_code=BANK, bank_fees=None, dividends=None) 保留旧默认。

- [x] 写确定性测试并确认失败：不同费用、无拆分、无止盈轮换、分红资格/账务、分红连续化与无未来数据。
- [x] 最小扩展共享循环与指标，运行新增测试及原 ETF/纯现金相关测试。

### Task 2: 行情与正式入口

**Files:** 新增 amv_winning/bank_stock.py、config.yaml；修改 runner.py、task_registry.py、README.md 和入口相关测试。

**Interfaces:** load_stock_history(data_dir, last_date) -> (bars, audit)；run_research(..., bank_code=BANK, stock_data_dir=..., stock_dividends_path=...)；统一入口配置默认选择 601288.SH、bank_take_profit=true（用户已明确选择保留 8%）。

- [x] 写行情预热、缺数据、注册入口及产物测试并确认失败。
- [x] 接入相邻策略的行情格式、分红表及独立股票费用；输出实际行情/公司行动/代码快照和指标口径。
- [x] 更新文档和运行命令，跑完整 python/tests 与 git diff --check。

### Task 3: 回测和交付

- [x] 通过统一入口跑 20200101—20251231 农行默认版本，核对清单和交易。
- [x] 与旧纯现金、银行 ETF 无止盈/8% 版本做同区间比较，核对原基线字节一致和主仓信号时间一致。
- [x] 请求独立代码复核，修复实质问题后交付报告与简要结果。
