"""MA5 crossing classification and fee-aware short-trade exit levels."""
import math
import numpy as np
from python.strategies.amv_winning.runner import generate_amv_signals

DEFAULT_TIERS = ((.015,.01,.015),(.03,.0125,.02),(math.inf,.015,.025))


def generate_signals(amv):
    result = generate_amv_signals(amv)
    result['high_signal'] = result.buy_signal
    crossed = result.close.gt(result.ma5) & result.close.shift().le(result.ma5.shift())
    result['weak_signal'] = crossed & ~result.high_signal
    result['buy_signal'] = result.high_signal | result.weak_signal
    result['entry_branch'] = np.where(result.high_signal,'high',np.where(result.weak_signal,'weak',''))
    return result


def weak_exit_parameters(rise, tiers=DEFAULT_TIERS):
    if not math.isfinite(rise):
        raise ValueError('开仓日涨幅必须有限')
    previous = -math.inf
    for upper,stop,profit in tiers:
        if upper<=previous or not 0<stop<1 or not 0<profit<1:
            raise ValueError('分档必须递增，止损止盈比例必须在0和1之间')
        previous=upper
    if not math.isinf(tiers[-1][0]):
        raise ValueError('最后一档必须覆盖全部涨幅')
    for upper,stop,profit in tiers:
        if rise<upper:
            return stop,profit
    raise ValueError('分档不能匹配涨幅')


def net_exit_price(buy_cost,quantity,target,fees):
    fixed=1-fees.stamp_duty_rate-fees.transfer_fee_rate
    variable=fixed-fees.commission_rate
    if buy_cost<=0 or quantity<=0 or target<=-1 or variable<=0:
        raise ValueError('退出价格参数无效')
    proceeds=buy_cost*(1+target)
    gross=max((proceeds+fees.min_commission)/fixed,proceeds/variable)
    return gross/(quantity*(1-fees.slippage_rate))


def filter_weak_signals(signals, minimum_return=None):
    """Filter weak crosses without changing high signals or delaying entries."""
    result = signals.copy()
    if minimum_return is None:
        return result
    if not math.isfinite(minimum_return):
        raise ValueError('弱信号涨幅门槛必须有限')
    result['weak_signal'] = result.weak_signal & result.day_return.ge(minimum_return)
    result['buy_signal'] = result.high_signal | result.weak_signal
    result['entry_branch'] = np.where(result.high_signal, 'high', np.where(result.weak_signal, 'weak', ''))
    return result
