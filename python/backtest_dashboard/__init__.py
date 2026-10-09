"""TradePilot2 回测可视化服务。

绕过 Go 后端，独立 FastAPI 微服务（端口 8082），与 python/main.py（评分引擎 :8081）解耦。
复用 python/backtest/data_loader.py 的 parquet 读取逻辑。
"""
