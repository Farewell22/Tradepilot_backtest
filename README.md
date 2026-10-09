# TradePilot2 - 股票回测系统

AI 驱动的量化交易回测系统，核心理念：**让历史数据验证你的策略**。

## 0AMV 因子研究

0AMV 研究独立于正式策略回测：它检验收盘后可得的 0AMV 特征与指数未来收益、全市场上涨比例之间的历史关系，不构成交易建议。

```bash
/home/wang/python_env/B1_RATE/bin/python -m python.factor_research.run_experiment \
  --config python/config/factor_research_0amv.yaml
```

首次运行会缓存上证指数与深证成指日线；缓存存在时默认不访问网络。传入 `--refresh` 才更新指数缓存。每次运行在 `data/factor_research_runs/` 下生成独立目录，包含 `observations.csv`、`factor_summary.csv`、`metadata.json` 与 `report.md`。

## 功能

统一入口位于项目根目录，可先列出任务，再按名称运行：

```bash
./scripts/backtest.sh list strategies
./scripts/backtest.sh list research
./scripts/backtest.sh run strategy amv_winning --start 20240101 --end 20240331
./scripts/backtest.sh run research amv_3d_momentum --start 20240101 --end 20240331
```

默认日期为 20200101—20251231。每次运行在 `data/backtest_runs/` 或 `data/factor_research_runs/` 新建目录，并写入 `run_manifest.json`（数据源、配置快照、费用、执行口径与 Git 状态）。目录和策略开发约定见 [回测开发指南](docs/backtest-development.md)。

- **回测分析**：运行已注册的 ETF/0AMV 等策略，查看历史区间收益与交易明细；B1 回测策略已移除
- **可视化报告**：NAV 曲线、交易明细、绩效指标、单笔交易 K 线回放
- **实时评分**：输入股票代码 → 即时输出 B1 / 砖型图评分

## 架构

```
Vue 3 + Naive UI (:3000)
   ├── /api/*    →  Python main.py (:8081)        [评分 + 评分历史]
   └── /bt-api/* →  Python backtest_dashboard (:8082) [回测可视化]
                     ↕
                 parquet 文件 (data/)
```

无数据库，无登录，无 Go 后端。

## 快速开始

### 1. 准备 Python 环境

```bash
# 创建虚拟环境并安装依赖
python -m venv ~/python_env/B1_RATE
source ~/python_env/B1_RATE/bin/activate
cd python
pip install -r requirements.txt
```

### 2. 准备前端

```bash
cd web
npm install
```

### 3. 准备数据

回测 K 线数据放在 `data/backtest_data/5m_price/`，回测结果在 `data/backtest_runs/`。
首次使用需要自行准备 parquet 文件（结构参见 `python/backtest/data_loader.py`）。

### 4. 一键启动

```bash
./scripts/dev.sh
```

启动后访问 http://localhost:3000

| 服务 | 地址 |
|------|------|
| Vue 前端 | http://localhost:3000 |
| Python 评分服务 | http://localhost:8081 |
| Python 回测可视化 | http://localhost:8082 |

## 单独启动某个服务

```bash
# 评分服务
cd python && ~/python_env/B1_RATE/bin/uvicorn main:app --port 8081 --reload

# 回测可视化（必须在项目根目录执行）
~/python_env/B1_RATE/bin/uvicorn python.backtest_dashboard.api:app --port 8082 --reload

# 前端
cd web && npm run dev

# 跑一次回测（离线作业）
./scripts/backtest.sh run strategy etf_amv
```

## 目录速查

- `python/backtest/` — 通用回测核心；旧 `run_*.py` 兼容入口已移除
- `python/strategies/` — 正式策略库；`python/research/` — 研究任务
- `python/factors/` — 可复用指标和信号；`python/run_backtest.py` — 统一入口
- `python/backtest_dashboard/` — 回测可视化 API（:8082）
- `python/main.py` — 评分服务（:8081）
- `python/scoring/` — 评分算法（B1 + 砖型图）
- `python/config/stock_rater.yaml` — 评分参数
- `python/data/ratings/` — 评分历史 JSON（运行时生成）
- `web/src/views/StockRater.vue` — 评分入口页
- `web/src/views/Backtest.vue` — 回测分析页
- `data/backtest_data/` — 5min K 线 parquet
- `data/backtest_runs/` — 回测运行结果

## 日志位置

启动脚本会把日志写到：
- `/tmp/scoring-service.log`
- `/tmp/backtest-service.log`
- `/tmp/vue-service.log`

## 术语

本项目使用 Z哥战法体系（B1/B2/S1/S2、知行黄白线、砖型图、N型起跳、四块砖、0AMV 择时等）。
完整术语表见 [CLAUDE.md](./CLAUDE.md)。
