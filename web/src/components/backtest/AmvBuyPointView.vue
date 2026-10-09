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
      <n-grid :cols="3" :x-gap="12" :y-gap="12" style="margin-bottom: 16px;">
        <n-gi v-for="item in summary" :key="item.signal_type">
          <n-card size="small">
            <n-statistic :label="item.signal_name" :value="item.count" suffix=" 次" />
          </n-card>
        </n-gi>
      </n-grid>

      <n-data-table v-if="summary.length" :columns="columns" :data="summary" :bordered="true" size="small" />
      <div ref="chartRef" class="amv-chart"></div>
    </n-spin>
  </div>
</template>

<script setup>
import { ref, watch, onMounted, onUnmounted } from 'vue'
import * as echarts from 'echarts'
import { NAlert, NButton, NCard, NDataTable, NGi, NGrid, NInput, NSpace, NSpin, NStatistic, NText } from 'naive-ui'
import { backtestApi } from '@/api/backtest'
import { useTheme } from '@/composables/useTheme'

const { echartsTheme, colors } = useTheme()
const loading = ref(false)
const error = ref('')
const startDate = ref('')
const endDate = ref('')
const points = ref([])
const summary = ref([])
const chartRef = ref(null)
let chart = null

const signalColors = { class_2: '#FF9800', class_3: '#00C853' }
const signalNames = { class_2: '二类买点', class_3: '三类买点' }
const visibleBuySignalTypes = new Set(['class_2', 'class_3'])
const sellColors = { sell_1: '#FF6D00', sell_2: '#D50000' }
const sellNames = { sell_1: '1类卖点', sell_2: '2类卖点' }
const warningColors = { sell_1: '#FFC107', sell_2: '#8E24AA' }
const warningNames = { sell_1: '1类极端预警', sell_2: '2类极端预警' }
const columns = [
  { title: '买点', key: 'signal_name' },
  { title: '次数', key: 'count' },
  ...[1, 3, 5, 10].map(horizon => ({
    title: `${horizon}日平均收益`,
    key: `avg_forward_return_${horizon}_pct`,
    render: row => formatPct(row[`avg_forward_return_${horizon}_pct`]),
  })),
  ...[1, 3, 5, 10].map(horizon => ({
    title: `${horizon}日上涨比例`,
    key: `win_rate_${horizon}_pct`,
    render: row => formatPct(row[`win_rate_${horizon}_pct`]),
  })),
]

function formatPct(value) {
  return value == null ? '-' : `${Number(value).toFixed(2)}%`
}

async function loadData() {
  loading.value = true
  error.value = ''
  try {
    const result = await backtestApi.get0AMVBuyPoints(startDate.value.trim(), endDate.value.trim())
    points.value = result.points || []
    summary.value = result.summary || []
    await Promise.resolve()
    buildChart()
  } catch (err) {
    error.value = err.message || '加载买点统计失败'
    points.value = []
    summary.value = []
  } finally {
    loading.value = false
  }
}

function resetDates() {
  startDate.value = ''
  endDate.value = ''
  loadData()
}

function buildChart() {
  if (!chartRef.value || !points.value.length) return
  chart?.dispose()
  chart = echarts.init(chartRef.value, echartsTheme.value)
  const data = points.value
  const dates = data.map(point => point.date)
  const ohlc = data.map(point => [point.open, point.close, point.low, point.high])
  const buyMarkers = type => data.flatMap((point, index) =>
    point.signal_type === type && visibleBuySignalTypes.has(type)
      ? [{ value: [dates[index], point.low], itemStyle: { color: signalColors[point.signal_type] } }]
      : []
  )
  const sellMarkers = type => data.flatMap((point, index) =>
    (point.sell_types || []).includes(type)
      ? [{ value: [dates[index], point.high], itemStyle: { color: sellColors[type] } }]
      : []
  )
  const warningMarkers = type => data.flatMap((point, index) =>
    (point.sell_warning_types || []).includes(type)
      ? [{ value: [dates[index], point.high], itemStyle: { color: warningColors[type] } }]
      : []
  )
  chart.setOption({
    tooltip: { trigger: 'axis' },
    legend: { data: ['0AMV', 'MA10', 'MA20', '二类买点', '三类买点', '1类卖点', '2类卖点', '1类极端预警', '2类极端预警'], top: 4 },
    grid: { left: 60, right: 20, top: 40, bottom: 50 },
    xAxis: { type: 'category', data: dates, axisLabel: { rotate: 45, fontSize: 10 } },
    yAxis: { type: 'value', scale: true, splitLine: { lineStyle: { color: colors.value.border } } },
    series: [
      { name: '0AMV', type: 'candlestick', data: ohlc },
      { name: 'MA10', type: 'line', data: data.map(point => point.ma10), symbol: 'none', connectNulls: false, lineStyle: { color: '#2196F3', width: 1.5 } },
      { name: 'MA20', type: 'line', data: data.map(point => point.ma20), symbol: 'none', connectNulls: false, lineStyle: { color: '#9C27B0', width: 1.5 } },
      { name: signalNames.class_2, type: 'scatter', data: buyMarkers('class_2'), symbol: 'triangle', symbolSize: 12, z: 10, tooltip: { show: false } },
      { name: signalNames.class_3, type: 'scatter', data: buyMarkers('class_3'), symbol: 'triangle', symbolSize: 12, symbolOffset: [0, 10], z: 10, tooltip: { show: false } },
      { name: sellNames.sell_1, type: 'scatter', data: sellMarkers('sell_1'), symbol: 'triangle', symbolRotate: 180, symbolOffset: [0, -8], symbolSize: 14, itemStyle: { color: sellColors.sell_1 }, z: 11, tooltip: { show: false } },
      { name: sellNames.sell_2, type: 'scatter', data: sellMarkers('sell_2'), symbol: 'triangle', symbolRotate: 180, symbolOffset: [0, -20], symbolSize: 14, itemStyle: { color: sellColors.sell_2 }, z: 11, tooltip: { show: false } },
      { name: warningNames.sell_1, type: 'scatter', data: warningMarkers('sell_1'), symbol: 'diamond', symbolOffset: [0, -32], symbolSize: 12, itemStyle: { color: warningColors.sell_1 }, z: 12, tooltip: { show: false } },
      { name: warningNames.sell_2, type: 'scatter', data: warningMarkers('sell_2'), symbol: 'diamond', symbolOffset: [0, -44], symbolSize: 12, itemStyle: { color: warningColors.sell_2 }, z: 12, tooltip: { show: false } },
    ],
    dataZoom: [{ type: 'inside' }, { type: 'slider', bottom: 0 }],
  })
}

watch(echartsTheme, () => buildChart())
onMounted(loadData)
onUnmounted(() => chart?.dispose())
</script>

<style scoped>
.amv-chart { width: 100%; height: 620px; margin-top: 16px; }
</style>
