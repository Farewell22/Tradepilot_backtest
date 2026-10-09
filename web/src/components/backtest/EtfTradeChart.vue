<template>
  <div>
    <n-space align="center" style="margin-bottom: 12px;">
      <n-text depth="3" strong>回测运行：</n-text>
      <n-select
        v-model:value="localRunId"
        :options="runOptions"
        placeholder="选择回测运行"
        style="width: 360px"
        filterable
        @update:value="onRunChange"
      />
      <n-tag v-if="tradeCount" type="info" size="small" :bordered="false">
        {{ tradeCount }} 笔交易 · 买卖成对标记
      </n-tag>
    </n-space>

    <n-descriptions bordered size="small" :column="4" style="margin-bottom: 12px;">
      <n-descriptions-item label="买入">信号确认后次日开盘</n-descriptions-item>
      <n-descriptions-item label="止损">固定 5%</n-descriptions-item>
        <n-descriptions-item label="止盈更新">1/2类盈利超过 8%，最差类超过 5% 后更新</n-descriptions-item>
      <n-descriptions-item label="更新依据">上一日 K 线实体最低价</n-descriptions-item>
      <n-descriptions-item label="检查频率">每根 60 分钟 K 线</n-descriptions-item>
      <n-descriptions-item label="最佳信号">最多持仓 60 个交易日</n-descriptions-item>
      <n-descriptions-item label="次级信号">最多持仓 60 个交易日</n-descriptions-item>
      <n-descriptions-item label="止盈">跌破实体低点</n-descriptions-item>
      <n-descriptions-item label="交易制度">A股 T+1</n-descriptions-item>
      <n-descriptions-item label="标的">510300.SH</n-descriptions-item>
    </n-descriptions>

    <n-spin :show="loading">
      <n-alert v-if="error" type="error" :show-icon="false">{{ error }}</n-alert>
      <n-empty v-else-if="!loading && !bars.length" description="请选择 ETF 回测运行" />
      <div v-else ref="chartRef" class="etf-chart"></div>
    </n-spin>
  </div>
</template>

<script setup>
import { computed, nextTick, onUnmounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import { NAlert, NDescriptions, NDescriptionsItem, NEmpty, NSelect, NSpace, NSpin, NTag, NText } from 'naive-ui'
import { backtestApi } from '@/api/backtest'
import { useTheme } from '@/composables/useTheme'

const props = defineProps({
  runId: { type: String, default: '' },
  allRuns: { type: Array, default: () => [] },
})
const emit = defineEmits(['update:runId'])
const { colors, echartsTheme } = useTheme()

const localRunId = ref(props.runId)
const loading = ref(false)
const error = ref('')
const bars = ref([])
const trades = ref([])
const amvSignals = ref([])
const chartRef = ref(null)
let chart = null

const runOptions = computed(() => props.allRuns
  .filter(r => r.has_nav && r.has_trades && r.run_id.startsWith('etf_510300_0amv__'))
  .map(r => ({ label: r.label, value: r.run_id })))
const tradeCount = computed(() => trades.value.length)

const signalColors = { best: '#D32F2F', secondary: '#F57C00', worst: '#757575', unknown: '#607D8B' }

function dateLabel(date) {
  return date?.length === 8 ? `${date.slice(0, 4)}-${date.slice(4, 6)}-${date.slice(6, 8)}` : date
}

async function load(runId) {
  if (!runId) return
  loading.value = true
  error.value = ''
  bars.value = []
  trades.value = []
  amvSignals.value = []
  try {
    const data = await backtestApi.getEtfKLine(runId)
    bars.value = data.bars || []
    trades.value = data.trades || []
    amvSignals.value = data.amv_signals || []
    await nextTick()
    buildChart()
  } catch (e) {
    error.value = e.message || 'ETF K线加载失败'
  } finally {
    loading.value = false
  }
}

function onRunChange(runId) {
  emit('update:runId', runId)
  load(runId)
}

function buildChart() {
  if (!chartRef.value || !bars.value.length) return
  chart?.dispose()
  chart = echarts.init(chartRef.value, echartsTheme.value)
  const dates = bars.value.map(b => dateLabel(b.date))
  const dateSet = new Set(dates)
  const ohlc = bars.value.map(b => [b.open, b.close, b.low, b.high])
  const markPoints = []
  const markLines = []

  for (const trade of trades.value) {
    const buyDate = dateLabel(trade.buy_date)
    const sellDate = dateLabel(trade.sell_date)
    const color = signalColors[trade.signal_type] || signalColors.unknown
    if (dateSet.has(buyDate)) {
      markPoints.push({
        name: `买入-${trade.signal_type}`,
        coord: [buyDate, trade.buy_price],
        value: `买 ${trade.signal_type} ${trade.buy_price.toFixed(2)}`,
        symbol: 'triangle', symbolRotate: 180, symbolSize: 13,
        itemStyle: { color }, label: { show: true, position: 'top', fontSize: 10 },
      })
    }
    if (sellDate && dateSet.has(sellDate)) {
      markPoints.push({
        name: '卖出', coord: [sellDate, trade.sell_price],
        value: `卖 ${trade.sell_price.toFixed(2)} ${trade.pnl_pct >= 0 ? '+' : ''}${trade.pnl_pct.toFixed(2)}%`,
        symbol: 'triangle', symbolSize: 13,
        itemStyle: { color: trade.pnl_pct >= 0 ? '#00C853' : '#FF1744' },
        label: { show: true, position: 'bottom', fontSize: 10 },
      })
      if (dateSet.has(buyDate)) {
        markLines.push([
          { coord: [buyDate, trade.buy_price] },
          { coord: [sellDate, trade.sell_price] },
        ])
      }
    }
  }

  const amvSellColors = { sell_1: '#FF6D00', sell_2: '#D50000' }
  const amvWarningColors = { sell_1: '#FFC107', sell_2: '#8E24AA' }
  const amvSellNames = { sell_1: '0AMV 1类卖点', sell_2: '0AMV 2类卖点' }
  const amvWarningNames = { sell_1: '0AMV 1类极端预警', sell_2: '0AMV 2类极端预警' }
  const amvMarker = (point, type, warning) => {
    const date = dateLabel(point.date)
    const field = warning ? 'sell_warning_types' : 'sell_types'
    if (!dateSet.has(date) || !(point[field] || []).includes(type)) return null
    return {
      name: warning ? amvWarningNames[type] : amvSellNames[type],
      coord: [date, point.high],
      value: warning ? '极端预警' : '0AMV卖点',
      symbol: warning ? 'diamond' : 'triangle',
      symbolRotate: warning ? 0 : 180,
      symbolSize: warning ? 12 : 14,
      symbolOffset: [0, warning ? -26 : -10],
      itemStyle: { color: warning ? amvWarningColors[type] : amvSellColors[type] },
      label: { show: true, position: 'top', fontSize: 9 },
    }
  }
  for (const point of amvSignals.value) {
    for (const type of ['sell_1', 'sell_2']) {
      const formal = amvMarker(point, type, false)
      const warning = amvMarker(point, type, true)
      if (formal) markPoints.push(formal)
      if (warning) markPoints.push(warning)
    }
  }

  chart.setOption({
    title: { text: '510300.SH ETF 日K线 · 交易与0AMV卖点', left: 'center', textStyle: { fontSize: 15 } },
    legend: { top: 28, data: ['最佳信号', '次级信号', '卖出盈利', '卖出亏损', '0AMV 1类卖点', '0AMV 2类卖点', '0AMV 1类极端预警', '0AMV 2类极端预警'] },
    tooltip: {
      trigger: 'axis', axisPointer: { type: 'cross' },
      formatter: params => {
        const p = params?.find(item => item.seriesType === 'candlestick')
        if (!p) return params?.[0]?.axisValue || ''
        const v = p.data
        return `${p.axisValue}<br/>开 ${v[1].toFixed(3)}　收 ${v[2].toFixed(3)}<br/>低 ${v[3].toFixed(3)}　高 ${v[4].toFixed(3)}`
      },
    },
    grid: { left: 65, right: 25, top: 65, bottom: 70 },
    xAxis: { type: 'category', data: dates, axisLabel: { rotate: 45, fontSize: 10 } },
    yAxis: { type: 'value', scale: true, splitLine: { lineStyle: { color: colors.value.border } } },
    series: [
      { name: 'K线', type: 'candlestick', data: ohlc, markPoint: { data: markPoints, animation: false }, markLine: { data: markLines, silent: true, symbol: 'none', lineStyle: { color: '#90A4AE', type: 'dashed', width: 1 }, animation: false } },
    ],
    dataZoom: [{ type: 'inside' }, { type: 'slider', bottom: 12 }],
  })
}

watch([() => props.runId, runOptions], ([id, options]) => {
  const target = options.some(option => option.value === id) ? id : options[0]?.value
  if (target && target !== localRunId.value) {
    localRunId.value = target
    emit('update:runId', target)
    load(target)
  } else if (target && !bars.value.length && !loading.value) {
    load(target)
  }
}, { immediate: true })
watch(echartsTheme, () => { if (chart) nextTick(buildChart) })
onUnmounted(() => chart?.dispose())
</script>

<style scoped>
.etf-chart { width: 100%; height: 620px; }
</style>
