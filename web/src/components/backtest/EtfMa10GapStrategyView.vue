<template>
  <div>
    <n-space align="center" style="margin-bottom: 12px;">
      <n-text depth="3" strong>回测区间：</n-text>
      <n-radio-group v-model:value="stage" @update:value="loadData">
        <n-radio-button value="train">TRAIN（2015-2023）</n-radio-button>
        <n-radio-button value="oos">OOS（2024-2025）</n-radio-button>
      </n-radio-group>
      <n-tag type="info" size="small" :bordered="false">二类 + 三类组合 · 实际成交点</n-tag>
    </n-space>

    <n-descriptions bordered size="small" :column="3" style="margin-bottom: 12px;">
      <n-descriptions-item label="买入">信号后下一交易日开盘，全仓</n-descriptions-item>
      <n-descriptions-item label="低动量减仓">单信号卖初始仓位 50%；同日一、二类同时预警则清仓</n-descriptions-item>
      <n-descriptions-item label="风控">买入次日起，ETF日内触及成本价 -5%</n-descriptions-item>
    </n-descriptions>

    <n-alert v-if="error" type="error" :show-icon="false" style="margin-bottom: 12px;">{{ error }}</n-alert>
    <n-spin :show="loading">
      <n-empty v-if="!loading && !bars.length" :description="`暂无 ${strategyLabel} 回测数据`" />
      <div v-else ref="chartRef" class="strategy-chart"></div>
    </n-spin>
  </div>
</template>

<script setup>
import { nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import {
  NAlert, NDescriptions, NDescriptionsItem, NEmpty, NRadioButton, NRadioGroup, NSpace, NSpin, NTag, NText,
} from 'naive-ui'
import { backtestApi } from '@/api/backtest'
import { useTheme } from '@/composables/useTheme'

const props = defineProps({
  symbol: { type: String, default: '510300.SH' },
  strategyLabel: { type: String, default: 'MA10乖离策略' },
  loadStrategy: { type: Function, default: stageValue => backtestApi.getEtfMa10GapStrategy(stageValue) },
})

const { colors, echartsTheme } = useTheme()
const stage = ref('oos')
const loading = ref(false)
const error = ref('')
const bars = ref([])
const trades = ref([])
const chartRef = ref(null)
let chart = null

const buyColors = { class_2: '#FF9800', class_3: '#00C853' }
const buyNames = { class_2: '二类买点', class_3: '三类买点' }
const exitStyles = {
  momentumSell1: { name: '1类低动量减半', color: '#0288D1' },
  momentumSell2: { name: '2类低动量减半', color: '#00897B' },
  momentumClear1: { name: '1类低动量清仓', color: '#1565C0' },
  momentumClear2: { name: '2类低动量清仓', color: '#00695C' },
  momentumClearBoth: { name: '1+2类低动量清仓', color: '#37474F' },
  trend: { name: 'MA10≤MA30清仓', color: '#5C6BC0' },
  stop: { name: '5%硬止损', color: '#757575' },
  trail: { name: '7%后实体低点止盈', color: '#8E24AA' },
}

function dateLabel(date) {
  return date?.length === 8 ? `${date.slice(0, 4)}-${date.slice(4, 6)}-${date.slice(6, 8)}` : date
}

function exitStyle(reason = '', isPartialExit = false) {
  if (reason.startsWith('momentum_warning')) {
    if (reason.includes('sell_1') && reason.includes('sell_2')) return exitStyles.momentumClearBoth
    if (reason.includes('sell_1')) return isPartialExit ? exitStyles.momentumSell1 : exitStyles.momentumClear1
    return isPartialExit ? exitStyles.momentumSell2 : exitStyles.momentumClear2
  }
  if (reason.startsWith('sell_signal')) {
    return { name: '旧卖点清仓', color: '#B71C1C' }
  }
  if (reason.startsWith('trend_exit')) return exitStyles.trend
  if (reason.startsWith('profit_trail')) return exitStyles.trail
  return exitStyles.stop
}

async function loadData() {
  loading.value = true
  error.value = ''
  bars.value = []
  trades.value = []
  try {
    const data = await props.loadStrategy(stage.value)
    bars.value = data.bars || []
    trades.value = data.trades || []
    await nextTick()
    buildChart()
  } catch (err) {
    error.value = err.message || `${props.strategyLabel}K线加载失败`
  } finally {
    loading.value = false
  }
}

function buyPoints(type, dates) {
  const seen = new Set()
  return trades.value.flatMap(trade => {
    const date = dateLabel(trade.buy_date)
    const key = `${date}_${trade.signal_type}`
    if (seen.has(key)) return []
    seen.add(key)
    return trade.signal_type === type && dates.has(date)
      ? [{ value: [date, trade.buy_price], label: { formatter: buyNames[type] } }]
      : []
  })
}

function exitPoints(kind, dates) {
  return trades.value.flatMap(trade => {
    const date = dateLabel(trade.sell_date)
    const style = exitStyle(trade.sell_reason, trade.is_partial_exit)
    if (!date || !dates.has(date) || style.name !== kind) return []
    return [{
      value: [date, trade.sell_price],
      label: { formatter: `${style.name}\n${trade.pnl_pct >= 0 ? '+' : ''}${trade.pnl_pct.toFixed(1)}%` },
    }]
  })
}

function buildChart() {
  if (!chartRef.value || !bars.value.length) return
  chart?.dispose()
  chart = echarts.init(chartRef.value, echartsTheme.value)
  const dates = bars.value.map(bar => dateLabel(bar.date))
  const dateSet = new Set(dates)
  const ohlc = bars.value.map(bar => [bar.open, bar.close, bar.low, bar.high])
  const exitNames = ['1类低动量减半', '2类低动量减半', '1类低动量清仓', '2类低动量清仓', '1+2类低动量清仓', 'MA10≤MA30清仓', '5%硬止损', '7%后实体低点止盈']
  const exitColors = {
    '1类低动量减半': exitStyles.momentumSell1.color,
    '2类低动量减半': exitStyles.momentumSell2.color,
    '1类低动量清仓': exitStyles.momentumClear1.color,
    '2类低动量清仓': exitStyles.momentumClear2.color,
    '1+2类低动量清仓': exitStyles.momentumClearBoth.color,
    'MA10≤MA30清仓': exitStyles.trend.color,
    '5%硬止损': exitStyles.stop.color,
    '7%后实体低点止盈': exitStyles.trail.color,
  }
  chart.setOption({
    title: { text: `${props.symbol} ETF 日K线 · ${props.strategyLabel}（${stage.value.toUpperCase()}）`, left: 'center', textStyle: { fontSize: 15 } },
    legend: { top: 28, data: ['ETF K线', '二类买点', '三类买点', ...exitNames] },
    tooltip: { trigger: 'axis', axisPointer: { type: 'cross' } },
    grid: { left: 65, right: 25, top: 65, bottom: 70 },
    xAxis: { type: 'category', data: dates, axisLabel: { rotate: 45, fontSize: 10 } },
    yAxis: { type: 'value', scale: true, splitLine: { lineStyle: { color: colors.value.border } } },
    series: [
      { name: 'ETF K线', type: 'candlestick', data: ohlc },
      { name: '二类买点', type: 'scatter', data: buyPoints('class_2', dateSet), symbol: 'triangle', symbolRotate: 180, symbolSize: 14, symbolOffset: [0, 9], itemStyle: { color: buyColors.class_2 }, label: { show: true, position: 'bottom', fontSize: 9 }, z: 10 },
      { name: '三类买点', type: 'scatter', data: buyPoints('class_3', dateSet), symbol: 'triangle', symbolRotate: 180, symbolSize: 14, symbolOffset: [0, 20], itemStyle: { color: buyColors.class_3 }, label: { show: true, position: 'bottom', fontSize: 9 }, z: 10 },
      ...exitNames.map(name => ({ name, type: 'scatter', data: exitPoints(name, dateSet), symbol: 'triangle', symbolSize: 14, symbolOffset: [0, -10], itemStyle: { color: exitColors[name] }, label: { show: true, position: 'top', fontSize: 9 }, z: 10 })),
    ],
    dataZoom: [{ type: 'inside' }, { type: 'slider', bottom: 10 }],
  })
}

watch(echartsTheme, () => { if (chart) nextTick(buildChart) })
onMounted(loadData)
onUnmounted(() => chart?.dispose())
</script>

<style scoped>
.strategy-chart { width: 100%; height: 620px; }
</style>
