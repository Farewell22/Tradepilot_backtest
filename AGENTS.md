# TradePilot - 股票回测系统

> 目录迁移提示（2026-09-24）：通用核心在 `python/backtest/`，正式策略在 `python/strategies/`，共享因子在 `python/factors/`，研究任务在 `python/research/`，数据审计在 `python/tools/`。B1 回测策略及旧 `python/backtest/run_*.py` 兼容入口已删除；实时 B1 评分和 B1 因子研究保留。统一命令为 `./scripts/backtest.sh list strategies|research` 和 `./scripts/backtest.sh run strategy|research <名称> [--start YYYYMMDD --end YYYYMMDD]`；详情见 `docs/backtest-development.md`。

## 项目简介
AI 驱动的量化交易**回测系统**，用于策略历史数据验证。
同时提供实时评分入口：输入股票代码即时输出 B1 / 砖型图评分结果。

## 技术架构
```
Vue 3 + Naive UI (:3000)
   ├── /api/*    →  Python FastAPI - main:app (:8081)        [评分服务 + 评分历史]
   └── /bt-api/* →  Python FastAPI - backtest_dashboard (:8082) [回测可视化]
                          ↕
                     parquet 文件 (data/backtest_data/, data/backtest_runs/)
                          ↕
                  东方财富 / 腾讯财经 / Tushare (实时 K 线)
```

无数据库（评分历史走 JSON 文件），无 Go 后端，无登录认证。

## 项目结构
```
TradePilot2/
├── python/                      Python 后端（两个 FastAPI 服务）
│   ├── main.py                  :8081 评分服务（含 /score/runs 评分历史）
│   ├── ratings_store.py         评分历史 JSON 持久化
│   ├── run_backtest.py          回测统一命令入口
│   ├── task_registry.py         正式策略与研究任务注册
│   ├── backtest/                回测通用核心（行情、成交、费用、绩效、报告）
│   ├── strategies/              正式策略：etf_amv、green_doji、amv_winning
│   ├── factors/                 共享指标、0AMV 信号及 B1 研究过滤
│   ├── research/                因子与策略研究任务
│   ├── factor_research/         B1 等因子实验
│   ├── tools/                   数据审计
│   ├── backtest_dashboard/      :8082 回测可视化 API
│   │   ├── api.py               FastAPI 路由
│   │   ├── service.py           读 parquet 的业务层
│   │   └── schemas.py           响应模型
│   ├── scoring/                 评分算法
│   │   ├── stock_rater.py       B1 评分主算法（回测 + 实时共用）
│   │   ├── brick_indicator.py   砖型图 + KDJ + 黄白线指标
│   │   ├── brick_rater.py       砖型图评分
│   │   ├── data_source.py       K 线数据源（tushare/腾讯）
│   │   ├── position_analyzer.py 持仓分析
│   │   └── weekly_invest.py     周线定投分析
│   ├── config/                  配置
│   │   └── stock_rater.yaml     评分参数
│   ├── data/ratings/            评分历史 JSON 存储（运行时生成）
│   └── requirements.txt
├── web/                         Vue 3 + Naive UI 前端
│   └── src/
│       ├── views/
│       │   ├── StockRater.vue   评分入口
│       │   └── Backtest.vue     回测分析
│       ├── components/
│       │   ├── backtest/        回测组件（4 个）
│       │   ├── stock/           评分组件（ConfigEditor）
│       │   └── RatingTable.vue  评分结果表
│       ├── api/                 backtest.js + stock.js + client.js
│       ├── stores/              backtest.js + stock.js
│       ├── router/              2 条路由无守卫
│       ├── layouts/             MainLayout.vue
│       ├── theme/               主题（亮色 + ECharts 主题）
│       └── composables/         useTheme / useTableFilter
├── data/                        回测数据（25GB+，不入 git）
│   ├── backtest_data/           5min K 线 parquet
│   └── backtest_runs/           回测运行结果
├── scripts/
│   └── dev.sh                   一键启动 3 个服务
├── CLAUDE.md
└── README.md
```

## 开发命令
```bash
# 一键启动全部服务（评分 + 回测可视化 + Vue）
./scripts/dev.sh

# 单独启动评分服务
cd python && ~/python_env/B1_RATE/bin/uvicorn main:app --port 8081 --reload

# 单独启动回测可视化（必须在项目根目录）
~/python_env/B1_RATE/bin/uvicorn python.backtest_dashboard.api:app --port 8082 --reload

# Vue 前端
cd web && npm run dev    # Vite :3000

# 运行回测（离线作业）
./scripts/backtest.sh run strategy etf_amv
```

## Python 端点（main.py :8081）

### 评分
- POST /api/v1/score              对传入 K 线批量评分（不持久化）
- POST /api/v1/score-brick        砖型图评分
- POST /api/v1/fetch-kline        拉取 K 线（走数据源）
- POST /api/v1/industry           查个股行业
- POST /api/v1/compute-zx-lines   计算知行黄白线序列

### 评分历史（JSON 持久化到 python/data/ratings/）
- GET  /api/v1/score/runs/next-id            下一个自增 ID
- GET  /api/v1/score/runs                    列出所有运行
- POST /api/v1/score/runs                    创建运行（含评分）
- GET  /api/v1/score/runs/{id}               运行详情（含 ratings）
- DELETE /api/v1/score/runs/{id}             删除运行
- PUT   /api/v1/score/runs/{id}/rename       重命名
- GET  /api/v1/score/runs/{id}/ratings       仅取评分结果

### 配置
- GET  /api/v1/config/stock-rater            读 stock_rater.yaml
- PUT  /api/v1/config/stock-rater            写 stock_rater.yaml

## Python 端点（backtest_dashboard/api.py :8082）

- GET /api/v1/health                          健康检查
- GET /api/v1/backtest/runs                   回测运行列表
- GET /api/v1/backtest/years/summary          年度汇总
- GET /api/v1/backtest/runs/{id}/nav          NAV 曲线
- GET /api/v1/backtest/runs/{id}/trades       交易列表（支持筛选）
- GET /api/v1/backtest/runs/{id}/report       回测报告
- GET /api/v1/backtest/runs/{id}/meta         运行元数据
- PUT  /api/v1/backtest/runs/{id}/meta        更新备注
- DELETE /api/v1/backtest/runs/{id}           删除运行
- PUT  /api/v1/backtest/runs/{id}/rename      重命名
- GET /api/v1/backtest/trades/reasons         所有止损原因
- GET /api/v1/backtest/config                 评分配置
- GET /api/v1/backtest/trades/{id}/kline      单笔交易的日K+5min K

## 前后端代理
Vite 将 `/api/*` 代理到 `localhost:8081`（评分服务），`/bt-api/*` 代理到 `localhost:8082`（回测可视化，并重写路径为 `/api/*`）。
前端运行在 :3000，Python 评分在 :8081，Python 回测可视化在 :8082。

## 股票专业术语速查

本项目包含大量 A 股量化交易特有术语，AI 在处理评分、回测、对话时需理解以下概念。

### 一、Z哥战法（核心短线评分系统）
由交易者 **Zettaranc（Z哥）** 创立的本项目核心短线交易方法论。
- **七步法**：完整操作流程 — 周线确认方向 → 日线找入场点 → N型回调到位 → B1/B2信号确认 → 止损保护 → 趋势破坏离场 → 复盘总结
- **N型起跳定式**：股票上涨—回调—再上涨的" N "字形态，回调到位是买入时机
- **四块砖理论**：持仓时间管理规则，红柱连红4根警惕变盘
- **捡钱点**：B1买点的俗称，指高胜率的入场时机
- **牵牛绳**：对知行黄白线系统的比喻，指通过黄白线牵引持仓方向
- **少妇战法**：对短线交易纪律的形象比喻 — 严格止损、不扛单
- **底仓 / 动仓**：底仓是中长期持有的核心仓位，动仓是短线波段交易的灵活仓位
- **放飞策略**：浮盈后逐步上移止损，让利润奔跑的策略
- **曼城阵容**：组合配置的比喻 — 前锋（高弹性）+ 中场（稳健）+ 后卫（防守）
- **防卖飞七条**：防止过早卖出的7条规则

#### B1/B2/B3 买入信号体系
- **B1买点（超级B1 / B1潜伏）**：回调到支撑位、地量企稳后的潜伏买入点。特征：缩量回调、黄白线多头排列、价格回踩白线/黄线不破。胜率高，但需要等待
- **B2买点（倍量起爆 / 平行重炮 / 跃跃欲试 / 灾后重建）**：放量突破关键位后的追涨买入点。特征：成交量倍量放大、中大阳线突破均线压制、N型突破前高。确认信号强，但成本较高
  - **倍量起爆**：成交量是前日的2倍以上，股价大幅上涨
  - **平行重炮**：连续中大阳线并列，多方碾压空方
  - **跃跃欲试**：小阳线反复试探前高，即将突破
  - **灾后重建**：大跌后的修复性上涨，重新站上关键均线
- **B3买点（箭在弦上牛）**：强势股连续大涨后短暂休整，即将启动第二波

#### S1/S2/S3 卖出信号体系
- **S1（第一警告）**：放量阴线、跌破5日线 — 减仓观察
- **S2（二次确认）**：连续走弱、跌破10日线 — 大幅减仓
- **S3（最后机会）**：跌破关键支撑（黄线/前低）— 清仓离场

#### 知行黄白线系统（本项目独创技术指标）
自定义的价格均线系统，区别于传统MA均线，采用特定算法计算。
- **ZXDQ（白线 / 短期线）**：代表短期持仓成本，反映散户+游资成本线。股价在白线上方 = 短期强势
- **ZXDKX（黄线 / 长期线）**：代表长期持仓成本，反映机构成本线。股价在黄线上方 = 中期趋势健康
- **金叉**：白线上穿黄线 = 做多信号，趋势转强
- **死叉**：白线下穿黄线 = 空仓信号，趋势转弱
- **三级止损体系**：N型低点（第1级）→ 白线（第2级）→ 黄线（第3级），逐级上移止损
- **股价跌破黄线 = 主力撤退**：中线趋势走坏，应考虑离场

#### 砖型图战法（本项目独创）
基于砖型图（Brick Chart）的趋势跟踪系统，不同于传统K线。
- **红柱（Red Brick）**：价格上涨的砖块，多方力量
- **绿柱（Green Brick）**：价格下跌的砖块，空方力量
- **红翻绿**：红柱转为绿柱 = 趋势转弱信号，考虑减仓
- **绿翻红**：绿柱转为红柱 = 趋势转强信号，考虑入场
- **连绿根数（green_run）**：连续绿柱数量，极值时预示反弹
- **红柱增长倍数（brick_growth）**：红柱高度相对均值倍数，倍数过大可能短期过热
- **空方力量线（VAR2A）**：EMA双平滑计算的压力线，下压则表示趋势承压
- **多方力量线（VAR5A）**：EMA双平滑计算的支撑线，上托则表示趋势健康
- **八道关卡（保守模式）**：砖型图入场前的8项严格筛选条件
- **四块砖卖出规则**：连红4砖后分批止盈的规则
- **拿信 / 清仓**：砖型图系统的操作指令，"拿信"=持有，"清仓"=全部卖出

### 二、评分维度

> **B1 v2 哲学（2026-06 重构）**：拥抱龙头深度回调。
> B1 不是万能买点 — 只在「强趋势好股被打折打到合理位置 + 多级别超卖 + 出现止跌阳线」时出手。
> 核心理念来自 Z哥 B1 教学：前期翻倍/几倍的龙头，回撤 50%-75%（前一轮顶底之间的 1/2 到 1/4），
> 大级别 J 值跌到极负后出现第一次反包阳线 = 捡钱点。

#### Z哥战法评分（B1评分）v2 维度
| 维度 | 权重 | 含义 |
|------|------|------|
| **龙头基因(leader_gene)** | **25%** | 半年涨幅(100-200%满分) + N型突破前高次数(≥3次=龙头)。杂毛/无行情股此项低分 |
| **B1触发(b1_trigger)** | **20%** | 反包前阴(100分) / 长阳反弹(85分) / 十字星止跌(70分) / 长下影锤头(60分)。B1信号需要此项≥70才生效 |
| **多级别KDJ(multi_level_kdj)** | **15%** | 周线J + 月线J共振。双线大负值=100分（多级别共振超卖），单线=75分。大级别超卖是B1的前提 |
| **回调区域(pullback_zone)** | **15%** | 从波段大顶（swing high + 后续回落≥20%）的回撤%。40-60%=黄金区(100分)，30-40%=可接受，>75%=可能真崩盘 |
| 趋势结构(trend) | 5% | 日线均线多头/空头排列（辅助） |
| 周线趋势(weekly_trend) | 5% | 周线级别的方向判断（辅助） |
| 量价行为(volume) | 5% | 量价配合、缩量/放量健康度（辅助） |
| 盈亏比(rr_score) | 10% | 预期涨幅/止损幅度比值（辅助） |
| 信号加成(bonus) | 0~8分 | B1/B2信号叠加加分 |

> 旧维度（position / abnormal / n_type_pullback / chart_perfection / kdj）权重已降为 0，但保留计算用于向后兼容。

#### 砖型图评分维度
| 维度 | 权重 | 含义 |
|------|------|------|
| 红柱增长倍数 | 35% | 多方力量强度 |
| 红柱高度 | 15% | 当前多头力度 |
| 连续绿柱数 | 12% | 调整深度，极值=反弹机会 |
| 知行线位置 | 8% | 股价相对黄白线位置 |
| 周线趋势 | 12% | 大周期方向 |
| K线形态 | 18% | 特定K线组合得分 |

### 三、评级与判定体系
- **S / A / B+ / B / C / D**：六档评级，S为最强，D为最弱
- **PASS / WATCH / FAIL**：三档判定结果，PASS=可入场，WATCH=观望，FAIL=放弃
- **多头控盘 / 震荡 / 逆势**：三种波段方式分类，多头控盘=顺势，逆势=反弹

### 四、择时与市场分析

#### 活跃市值（0AMV）择时
基于 A 股活跃市值指标判断市场整体资金流向的择时系统（回测内置）。
- **SignalEntry（增量入场）**：单日活跃市值增长 ≥ 4%，增量资金入场
- **SignalHalf（半仓试水）**：3日累计增长 ≥ 4%，资金温和流入
- **SignalExit（离场）**：单日活跃市值下跌 ≤ -2.3%，资金大幅流出
- **SignalHold（观望）**：无明确信号，保持仓位不动

### 五、K线形态检测（11种）
| 形态 | 含义 |
|------|------|
| 十字星 | 多空平衡，趋势翻转信号 |
| 蜻蜓十字（看涨） | 下影线极长的十字星，底部翻转 |
| 墓碑十字（看跌） | 上影线极长的十字星，顶部反转 |
| 锤头（看涨） | 小实体+长下影线，底部反转 |
| 倒锤头（看涨） | 小实体+长上影线，底部试盘 |
| 射击之星（看跌） | 小实体+长上影线，顶部反转 |
| 上吊线（看跌） | 小实体+长下影线，顶部预警 |
| 看涨吞噬 | 阳线完全包裹前日阴线，强势转多 |
| 看跌吞噬 | 阴线完全包裹前日阳线，强势转空 |
| 刺透形态（看涨） | 阴线后低开高走阳线，刺入阴线中部 |
| 乌云盖顶（看跌） | 阳线后高开低走阴线，盖过阳线中部 |

### 六、常见技术指标别名
| 缩写 | 含义 |
|------|------|
| HHV(N) | N日内最高价滚动计算 |
| LLV(N) | N日内最低价滚动计算 |
| EMA2 | 双指数平滑移动平均 |
| RSV | 未成熟随机值（KDJ前身指标） |
| 量比(volume_ratio) | 当日成交量 / 近期均量 |
| 前复权(qfq) | 复权方式，保持除权前价格连续性 |

## 开发者背景
嵌入式工程师，学习互联网全栈开发和量化交易软件。
输出回答时尽量以教会的形式，讲明白原理和量化交易的设计模式。
