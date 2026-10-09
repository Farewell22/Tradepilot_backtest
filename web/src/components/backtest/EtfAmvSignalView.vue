<template>
  <div>
    <n-space align="center" style="margin-bottom: 16px;">
      <n-text depth="3">日期：</n-text>
      <n-input v-model:value="startDate" placeholder="开始日期 YYYYMMDD" style="width: 180px;" />
      <n-input v-model:value="endDate" placeholder="结束日期 YYYYMMDD" style="width: 180px;" />
      <n-button type="primary" :loading="loading" @click="loadData">查询</n-button>
      <n-button :disabled="loading" @click="resetDates">全历史</n-button>
    </n-space>

    <n-alert v-if="error" type="error" style="margin-bottom: 16px;">{{ error }}</n-alert>
    <n-spin :show="loading">
      <n-data-table v-if="signalRows.length" :columns="columns" :data="signalRows" :bordered="true" size="small" />
      <n-empty v-else-if="!loading" description="当前区间没有 0AMV 买卖点或风险预警" />
      <div ref="chartRef" class="etf-amv-chart"></div>
    </n-spin>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import { NAlert, NButton, NDataTable, NEmpty, NInput, NSpace, NSpin, NText } from 'naive-ui'
import { backtestApi } from '@/api/backtest'
import { useTheme } from '@/composables/useTheme'

const { colors, echartsTheme } = useTheme()
const loading = ref(false)
const error = ref('')
const startDate = ref('')
const endDate = ref('')
const points = ref([])
const chartRef = ref(null)
let chart = null

const labels = {
  best: '1类买点',
  secondary: '2类买点',
  sell_1: '1类卖点',
  sell_2: '2类卖点',
}
const warningLabels = {
  sell_1: '1类极端预警',
  sell_2: '2类极端预警',
}
const momentumWarningLabels = {
  sell_1: '1类低动量预警',
  sell_2: '2类低动量预警',
}
const colorsByType = { sell_1: '#FF6D00', sell_2: '#D50000' }
const warningColors = { sell_1: '#FFC107', sell_2: '#8E24AA' }
const momentumWarningColors = { sell_1: '#0288D1', sell_2: '#00897B' }

const signalRows = computed(() => points.value
  .filter(point => point.buy_types?.length || point.sell_types?.length || point.sell_warning_types?.length || point.sell_momentum_warning_types?.length)
  .map(point => ({
    date: point.date,
    buy_types: (point.buy_types || []).map(type => labels[type]).join('、') || '-',
    sell_types: (point.sell_types || []).map(type => labels[type]).join('、') || '-',
    sell_warning_types: (point.sell_warning_types || []).map(type => warningLabels[type]).join('、') || '-',
    sell_momentum_warning_types: (point.sell_momentum_warning_types || []).map(type => momentumWarningLabels[type]).join('、') || '-',
    close: point.close,
  })))

const columns = [
  { title: '日期', key: 'date' },
  { title: '买点', key: 'buy_types' },
  { title: '正式卖点', key: 'sell_types' },
  { title: '极端风险预警', key: 'sell_warning_types' },
  { title: '低动量早期预警', key: 'sell_momentum_warning_types' },
  { title: 'ETF收盘价', key: 'close', render: row => Number(row.close).toFixed(3) },
]

function dateLabel(date) {
  return date?.length === 8 ? `${date.slice(0, 4)}-${date.slice(4, 6)}-${date.slice(6, 8)}` : date
}

async function loadData() {
  loading.value = true
  error.value = ''
  try {
    const result = await backtestApi.getEtfAmvSignals(startDate.value.trim(), endDate.value.trim())
    points.value = result.points || []
    await nextTick()
    buildChart()
  } catch (err) {
    error.value = err.message || 'ETF 0AMV 卖点加载失败'
    points.value = []
  } finally {
    loading.value = false
  }
}

function resetDates() {
  startDate.value = ''
  endDate.value = ''
  loadData()
}

function markerData(type, warning = false) {
  const field = warning ? 'sell_warning_types' : 'sell_types'
  return points.value.flatMap(point => (point[field] || []).includes(type)
    ? [{ value: [dateLabel(point.date), point.high] }]
    : [])
}

function buyMarkerData(type) {
  return points.value.flatMap(point => (point.buy_types || []).includes(type)
    ? [{ value: [dateLabel(point.date), point.low] }]
    : [])
}

function momentumWarningMarkerData(type) {
  return points.value.flatMap(point => (point.sell_momentum_warning_types || []).includes(type)
    ? [{ value: [dateLabel(point.date), point.high] }]
    : [])
}

function buildChart() {
  if (!chartRef.value || !points.value.length) return
  chart?.dispose()
  chart = echarts.init(chartRef.value, echartsTheme.value)
  const dates = points.value.map(point => dateLabel(point.date))
  const ohlc = points.value.map(point => [point.open, point.close, point.low, point.high])
  chart.setOption({
    title: { text: '510300.SH ETF 日K线 · 0AMV买卖点与风险预警', left: 'center', textStyle: { fontSize: 15 } },
    legend: { top: 28, data: ['ETF K线', '1类买点', '2类买点', '1类卖点', '2类卖点', '1类极端预警', '2类极端预警', '1类低动量预警', '2类低动量预警'] },
    tooltip: { trigger: 'axis', axisPointer: { type: 'cross' } },
    grid: { left: 65, right: 25, top: 65, bottom: 70 },
    xAxis: { type: 'category', data: dates, axisLabel: { rotate: 45, fontSize: 10 } },
    yAxis: { type: 'value', scale: true, splitLine: { lineStyle: { color: colors.value.border } } },
    series: [
      { name: 'ETF K线', type: 'candlestick', data: ohlc },
      { name: '1类买点', type: 'scatter', data: buyMarkerData('best'), symbol: 'triangle', symbolSize: 14, symbolOffset: [0, 8], itemStyle: { color: '#00C853' }, z: 10 },
      { name: '2类买点', type: 'scatter', data: buyMarkerData('secondary'), symbol: 'triangle', symbolSize: 14, symbolOffset: [0, 20], itemStyle: { color: '#FF9800' }, z: 10 },
      { name: '1类卖点', type: 'scatter', data: markerData('sell_1'), symbol: 'triangle', symbolRotate: 180, symbolOffset: [0, -8], symbolSize: 14, itemStyle: { color: colorsByType.sell_1 }, z: 10 },
      { name: '2类卖点', type: 'scatter', data: markerData('sell_2'), symbol: 'triangle', symbolRotate: 180, symbolOffset: [0, -20], symbolSize: 14, itemStyle: { color: colorsByType.sell_2 }, z: 10 },
      { name: '1类极端预警', type: 'scatter', data: markerData('sell_1', true), symbol: 'diamond', symbolOffset: [0, -32], symbolSize: 12, itemStyle: { color: warningColors.sell_1 }, z: 11 },
      { name: '2类极端预警', type: 'scatter', data: markerData('sell_2', true), symbol: 'diamond', symbolOffset: [0, -44], symbolSize: 12, itemStyle: { color: warningColors.sell_2 }, z: 11 },
      { name: '1类低动量预警', type: 'scatter', data: momentumWarningMarkerData('sell_1'), symbol: 'pin', symbolOffset: [0, -56], symbolSize: 16, itemStyle: { color: momentumWarningColors.sell_1 }, z: 12 },
      { name: '2类低动量预警', type: 'scatter', data: momentumWarningMarkerData('sell_2'), symbol: 'pin', symbolOffset: [0, -70], symbolSize: 16, itemStyle: { color: momentumWarningColors.sell_2 }, z: 12 },
    ],
    dataZoom: [{ type: 'inside' }, { type: 'slider', bottom: 0 }],
  })
}

watch(echartsTheme, () => buildChart())
onMounted(loadData)
onUnmounted(() => chart?.dispose())
</script>

<style scoped>
.etf-amv-chart { width: 100%; height: 620px; margin-top: 16px; }
</style>
