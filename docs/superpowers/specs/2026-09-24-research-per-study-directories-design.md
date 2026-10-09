# 研究任务按主题、按研究独立目录设计

日期：2026-09-24

## 目标与边界

用户希望 `python/research/` 保留 `amv/`、`etf/` 主题分组，同时每项研究再拥有独立目录，方便日后收纳该研究的代码、说明、配置与专属复盘资料。迁移仅改变源码组织和内部导入路径，不改变研究算法、输入数据、输出格式、任务名称及统一 CLI 命令。

`python/factor_research/` 是另一套现存的因子实验流程，本次不迁移。`python/factors/`、`python/strategies/`、`python/backtest/` 的职责和位置不变。`data/` 中的行情、历史结果及 `docs/` 中的历史研究报告不移动、不删除。

## 目录契约

每项研究使用注册表中的 `task_id` 作为目录名；当前单文件实现移为该目录内的 `study.py`，保留 `run_research` 和既有直接运行入口。每个研究目录增加简短 `README.md`，记录研究目的、统一运行命令、主要输入和结果。日后专属配置或复盘材料可放入相同目录，但本次不新增技能或复盘逻辑。

```text
python/research/
├── date_scope.py                       # 所有研究共用的日期范围工具
├── amv/
│   ├── amv_3d_momentum/
│   │   ├── study.py
│   │   └── README.md
│   ├── amv_buy_reentry_filters/
│   ├── amv_quantile_window_impact/
│   ├── amv_sell_momentum/
│   ├── ma10_above_ma30_gap/
│   ├── ma10_below_ma30_gap/
│   └── ma10_gap/
└── etf/
    ├── etf_amount_ratio_rotation/
    ├── amv_buy_etf_cross_section/
    ├── etf_kdj_rotation/
    ├── etf_rs20_rotation/
    ├── etf_amv_correlation/
    ├── etf_relative_volume/
    └── industry_etf_relative_strength/
```

表中省略的目录与 `amv_3d_momentum/` 一样，均含 `study.py` 和 `README.md`。主题目录不再存放具体研究的顶层 `.py` 文件。`date_scope.py` 不属于任何单项研究，因此仍留在 `python/research/` 根部。

## 代码与运行契约

`python/task_registry.py` 继续显式注册全部 14 项研究，原 `task_id` 不变；仅模块路径改为 `python.research.<主题>.<task_id>.study`。`./scripts/backtest.sh list research` 应仍列出同样 14 个名称；`./scripts/backtest.sh run research <名称> [--start ... --end ...]` 的参数、运行记录与产物保持原状。

研究脚本之间目前有跨主题和主题内导入。迁移时将这些导入、测试导入和运行时动态导入一次性更新到新路径，避免依赖失效。公共工具仍从 `python.research.date_scope` 导入；不要把公共函数复制到多个研究目录。旧 `python.research.amv.research_*.py`、`python.research.etf.research_*.py` 路径不保留薄兼容文件，因为这会重新制造主题目录中的零散脚本；直接模块调用者改用统一 CLI 或新模块路径。

文档只更新当前开发指南、README 与适用的代理说明。已发表的历史研究报告是当时运行的记录，不因本次目录迁移而重写结论；若其中旧源码链接影响浏览，可单独修复链接，但不能修改报告中的结果数据。

## 验收与风险

1. 14 个注册任务与原名称逐一对应，每个任务有独立目录和可导入的 `study.py`；`amv/`、`etf/` 顶层不再有具体研究脚本。
2. 所有跨研究导入、测试导入和动态注册路径在新目录下可用，保留的策略、评分和仪表盘导入不受影响。
3. 全套 Python 测试通过，统一 CLI 列表仍为 14 项；至少选择一个 AMV 和一个 ETF 研究执行短区间冒烟验证。若数据缺失，明确记录无法实跑的项目，并使用导入和测试证据代替，不伪称收益等价。
4. 文件迁移不改算法；对可能写入结果的冒烟运行使用独立临时输出根目录，不覆盖历史运行。既有结果不删除。
5. 当前工作树包含未提交的前期改造和用户其他改动，因此在原工作树精确迁移这些研究文件；不新建与当前状态脱节的 Git worktree，也不整理无关文件。

主要风险是路径迁移造成漏改导入，尤其是 ETF 研究复用 AMV 的买点函数。以显式注册表、全局旧路径扫描、全套测试和两类研究的实际运行共同控制。另一个风险是旧直接模块命令失效；这是已确认的兼容性边界，统一 CLI 保持稳定。
