# 绿色十字星策略

入口：`./scripts/backtest.sh run strategy green_doji`。策略选择、尾盘买入和止盈止损由 `strategy.py` 控制；费用由 `FeeConfig` 注入。沿用历史理想化日内口径，不等同于新事件引擎的下一根成交规则。
