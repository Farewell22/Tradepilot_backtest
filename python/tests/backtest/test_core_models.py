from python.backtest.models import Portfolio, Trade


def test_portfolio_nav_uses_cash_and_last_known_close():
    position = Trade(
        code="000001", buy_date="20240101", buy_time="13:05:00",
        buy_signal_price=10.0, buy_exec_price=10.01,
        buy_quantity=100, buy_cost=1006.01, last_close=11.0,
    )
    portfolio = Portfolio(initial_cash=2000.0, cash=993.99, positions=[position])
    assert portfolio.total_value == 2093.99
