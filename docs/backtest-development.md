# 回测框架开发与兼容指南

## 目录与职责

`python/backtest/` 仅放通用行情读取、账户/成交、费用、时间推进、绩效与报告。`python/strategies/<id>/` 放正式策略和其 runner；`python/factors/` 放可复用的指标/信号；`python/research/amv/<id>/study.py`、`python/research/etf/<id>/study.py`、`python/research/stock/<id>/study.py` 放各自独立的研究任务；`python/tools/` 放数据审计。评分服务仍在 `python/scoring/`，仪表盘仍在 `python/backtest_dashboard/`。`python/factor_research/` 暂不迁移。

仓库中保留策略源码，运行时按名称导入，不复制到工程目录。`.worktrees/` 只供隔离开发，不作长期策略归档。输入行情位于 `data/backtest_data/`；每次策略与研究运行的完整产物分别位于被忽略的 `data/backtest_runs/`、`data/factor_research_runs/`。统一命令成功后还会在任务源码目录更新可提交的 `latest-report.md`，其中附本次报告、输入数据、运行目录与清单路径。历史结论仍留在 `docs/run-result/` 或 `docs/factor-result/`，不自动迁移。

## 命令与运行记录

在项目根目录运行：

```bash
./scripts/backtest.sh list strategies
./scripts/backtest.sh list research
./scripts/backtest.sh run strategy etf_amv --start 20200101 --end 20251231
./scripts/backtest.sh run strategy amv_winning --start 20240101 --end 20240331 \
  --commission-rate 0.0002 --slippage-rate 0.0005
./scripts/backtest.sh run strategy amv_winning_rotation --start 20200302 --end 20251231
./scripts/backtest.sh run strategy amv_winning_ccb --start 20200102 --end 20251231
./scripts/backtest.sh run strategy amv_winning_cmb --start 20200102 --end 20251231
./scripts/backtest.sh run strategy amv_winning_defensive_3d --start 20200102 --end 20251231
./scripts/backtest.sh run strategy amv_winning_defensive_single_day --start 20200102 --end 20251231
./scripts/backtest.sh run strategy amv_winning_defensive_second_entry --start 20200102 --end 20251231
./scripts/backtest.sh run strategy amv_winning_defensive_ma20_entry --start 20200102 --end 20251231
./scripts/backtest.sh run strategy amv_winning_defensive_5d --start 20200302 --end 20251231
./scripts/backtest.sh run strategy amv_below_ma_defensive_etfs --start 20220516 --end 20251231
./scripts/backtest.sh run research amv_3d_momentum --start 20240101 --end 20240331
```

日期为闭区间，格式 `YYYYMMDD`，未指定时使用任务的默认日期：原有任务为20200101—20251231，`amv_below_ma_defensive_etfs` 为20220516—20251231。可用 `--config PATH` 覆盖支持配置文件的策略，用 `--output-root DIR` 改运行根目录。支持 `--commission-rate`、`--min-commission`、`--stamp-duty-rate`、`--transfer-fee-rate`、`--slippage-rate`；覆盖只作用本次运行。运行前验证任务、日期、配置文件和注册的数据源。每次运行目录均有 `run_manifest.json`，记录数据源、配置文本快照、费用、执行口径、Git 修订/脏工作区和运行状态。失败也会记录异常。此文件不与仪表盘用户备注 `meta.json` 混用。

保留的策略继续输出各自原有格式；各研究任务仍保留自己的统计表。不是所有策略都有相同报告格式，读取端应按任务类型识别。最新报告会收录 Markdown 或文本原报告；多阶段任务会收录全部阶段报告。失败运行不覆盖上一份成功报告；直接运行单个脚本不会更新最新报告。旧 `python.backtest.run_*.py` 命令兼容层已删除，统一使用 `./scripts/backtest.sh`。

`amv_winning_ccb`（建设银行 601939.SH）与 `amv_winning_cmb`（招商银行 600036.SH）是独立入口；一次分别运行此前农行对照的直接防守和周线 J<10 两版，默认 20200102—20251231、初始 20 万元。保留旧模拟循环及两版止盈/再进场差异，不改变农行正式入口。两股用原价执行、已发生分红连续周线和税前现金股息记账。根目录主结果为直接版，`direct/`、`weekly_j/` 各保存净值与成对交易，`metrics.json.variants` 保存两版绩效；详情见对应 README。

`amv_winning_defensive_3d` 基于农行直接防守版，只将主仓多日入场分支改为0AMV三日累计涨幅≥4.5%；单日≥4%、MA5、退出、农行8%净价差止盈和现金锁定规则保留。每次运行同时按相同输入重跑原两日≥4%基线，默认20200102—20251231。配置中的 `stock_data` 支持股票5分钟CSV或parquet目录；主仓交易日数据缺失报错。根目录为新版，`baseline/` 为原版，另有年度、逐日净值与入场分支统计；成交仍为 `legacy_same_close_idealized`，详见策略 README。

`amv_winning_defensive_single_day` 是取消所有多日入场分支的独立版本，仅保留0AMV单日涨幅≥4%且收盘≥MA5的主仓入场，其余规则与农行直接防守版一致。输出和原版对照口径与三日版相同；运行详情见对应 README。

`amv_winning_defensive_second_entry` 在单日版上增加MA10>MA30、正MA10乖离度首次进入[P60,P80)的第二买点。两种买点均全仓买512100，保留MA5、退出和农行防守。主结果与单日基线均采用次日开盘成交、主仓T+1；同次运行另输出两组同日收盘理想化对照，分别保存买点归因、年度及净值比较。详情见策略 README。

`amv_winning_defensive_ma20_entry` 是另一项独立实验：0AMV上穿MA20后，从上穿当日起5个交易日内首次满足三日动量>4%、收盘>MA60时确认第二买点。保留单日买点、MA5、原退出及农行8%止盈；同时满足时归因于单日。根目录与`baseline/`分别回测双买点和仅单日，两组均次日开盘、主仓T+1，保存完整交易归因、年度和净值比较。详情见策略 README。

`etf_size_rs20_percentile` 是独立因子研究：512100相对510050的20日总收益差，在包含当日的100日窗口中取百分位，比较未来5/10/20/60日收盘到收盘的两只ETF收益及收益差。默认正式区间2020—2025，2019年预热；公司行动核对范围2019—2025。统计包含固定十档、时期与年度、120日分块bootstrap及全部非重叠相位，不依赖0AMV或生成策略交易。完整输入和代码快照随运行保存，详情见研究目录README。

## 时间、成交与费用约定

新策略接口在 `python/backtest/engine.py`：`on_bar(StrategyContext) -> list[OrderIntent]`。上下文只含当根及以前可见信息和只读持仓快照；订单最早在**下一根可交易 K 线开盘**成交。账户和费用计算由 `Engine`、`FeeConfig` 负责，不应在新策略里直接扣现金。一个最小策略：

```python
from python.backtest.engine import OrderIntent

class OneShot:
    def __init__(self):
        self.sent = False

    def on_bar(self, context):
        if not self.sent and "510300.SH" in context.bars:
            self.sent = True
            return [OrderIntent("510300.SH", "buy", 100)]
        return []
```

用 `Engine().run(bars, OneShot(), initial_cash=100_000)` 执行；`bars` 必含 `timestamp, code, open, high, low, close`。新策略接入 CLI 时，在 `python/task_registry.py` 显式注册任务、数据源、默认费用、执行口径与 handler，并补充测试。研究任务也需注册；研究可以用未来收益作**标签**，但不能把未来数据用于当日交易决策。

保留的旧策略仍使用原有模拟循环，并非都已切换 `Engine`。这保住历史收益可比性：ETF AMV、绿色十字星仍采用各自的旧时点/交易限制；`amv_winning` 特别保留“收盘后才能确定的 0AMV 信号按同日收盘成交”的理想化假设，manifest 明示 `legacy_same_close_idealized`，不可当作可实盘复制的收益。B1、09:35 B1 及其熊市分支已从回测策略库移除；实时 B1 评分与 B1 因子研究仍保留。新引擎默认保持原有行为，新增可选 `enforce_t1`、按可用现金/一手买入的 `CashBuyIntent`、整笔清仓的 `SellAllIntent` 及分红/拆分记账；停牌/涨跌停成交、盘口容量仍未模拟，不能据此把旧策略无差别迁入。若改这些规则，须单独做收益对照。

`amv_below_ma_defensive_etfs` 使用这些可选接口，分别回测0AMV低于MA30、MA60的四只防守ETF，次日开盘成交，现金派息到账后次日再投资。公司行动核对区间为20220516—20251231，超出区间会报错；详见策略目录的 `README.md`。此任务保存16组比较结果、净值和逐笔账本，以及完整输入/代码快照。

`FeeConfig.stock_legacy()` 为旧股票默认：佣金 0.0003、最低 5 元、卖出印花税 0.001、过户费 0.00001、双向滑点 0.001。`FeeConfig.etf_legacy()` 无印花税、无过户费。`amv_winning` 默认 ETF 口径；其他策略沿用迁移前口径。改费用参数可能改变买入数量、现金及后续路径，比较时必须同时核对交易和 NAV，不能只看最终收益。

## 测试、迁移和归档

```bash
/home/wang/python_env/B1_RATE/bin/python -m pytest -q python/tests
git diff --check
```

迁移时先固定同一数据、日期、费用与配置的基线，再比对交易代码、日期、价格、数量、费用和 NAV。至少覆盖有交易、空仓、止损及缺失行情的样本。研究任务需断言实际观察日期落在用户请求区间，不能只检查 manifest。当前主要测试见 `python/tests/backtest/`；旧 `run_*.py` 命令及指标/研究模块旧导入路径均不再保证兼容。

目前已通过单元、API 和短区间实跑验证，但尚未对所有旧策略完成迁移前后逐笔交易/NAV 对照；特别是旧式交易时点及数据缺口需要在使用长期收益结论前按具体策略复核。统一入口先检查数据路径和配置，部分旧 runner 的完整字段/全区间覆盖检查仍由 runner 自身执行。

停止维护的正式策略可在注册表标为 `archived`，源码仍留在受 Git 管理的策略目录且不出现在默认 `list`；因子实验留在研究目录，避免把临时脚本塞回 `python/backtest/`。策略目录内可放自己的配置与说明；ETF YAML 暂留 `python/config/`，统一入口会把实际配置内容快照写入运行记录。
