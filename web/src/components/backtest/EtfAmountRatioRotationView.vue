<template>
  <div>
    <n-space align="center" style="margin-bottom: 12px;">
      <n-text depth="3" strong>回测区间：</n-text>
      <n-radio-group v-model:value="stage" @update:value="loadData">
        <n-radio-button value="train">TRAIN（2015-2023）</n-radio-button>
        <n-radio-button value="oos">OOS（2024-2025）</n-radio-button>
      </n-radio-group>
      <n-tag type="success" size="small" :bordered="false">动态候选池</n-tag>
    </n-space>

    <n-alert type="info" :show-icon="false" style="margin-bottom: 12px;">
      二/三类0AMV买点后，先筛选 MA10＞MA30 的ETF；成交额乖离优先Q1→Q3，剔除成交量Q5；无合格候选时回退510300ETF。卖点与风控沿用当前策略。
    </n-alert>
    <n-alert v-if="error" type="error" :show-icon="false" style="margin-bottom: 12px;">{{ error }}</n-alert>
    <n-spin :show="loading">
      <n-empty v-if="!loading && !result" description="暂无成交额低分位轮动回测数据" />
      <template v-else-if="result">
        <n-descriptions bordered size="small" :column="4" style="margin-bottom: 12px;">
          <n-descriptions-item label="总收益">{{ percent(result.summary.total_return_pct) }}</n-descriptions-item>
          <n-descriptions-item label="年化收益">{{ percent(result.summary.annualized_return_pct) }}</n-descriptions-item>
          <n-descriptions-item label="最大回撤">{{ percent(result.summary.max_drawdown_pct) }}</n-descriptions-item>
          <n-descriptions-item label="胜率">{{ percent(result.summary.win_rate_pct) }}</n-descriptions-item>
          <n-descriptions-item label="已平仓交易">{{ result.summary.closed_trade_count }}</n-descriptions-item>
          <n-descriptions-item label="入场信号">{{ result.summary.entry_signal_count }}</n-descriptions-item>
          <n-descriptions-item label="回退510300">{{ result.summary.fallback_510300_count }}</n-descriptions-item>
          <n-descriptions-item label="忽略重叠信号">{{ result.summary.ignored_buy_signals }}</n-descriptions-item>
        </n-descriptions>

        <div ref="chartRef" class="rotation-chart"></div>

        <n-text strong style="display:block;margin:16px 0 8px;">年度表现</n-text>
        <n-data-table :columns="annualColumns" :data="result.annual" :pagination="false" size="small" style="margin-bottom:16px;" />
        <n-text strong style="display:block;margin-bottom:8px;">实际交易明细</n-text>
        <n-data-table :columns="tradeColumns" :data="result.trades" :pagination="{ pageSize: 10 }" size="small" :scroll-x="1180" />
      </template>
    </n-spin>
  </div>
</template>

<script setup>
import { nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import {
  NAlert, NDataTable, NDescriptions, NDescriptionsItem, NEmpty, NRadioButton,
  NRadioGroup, NSpace, NSpin, NTag, NText,
} from 'naive-ui'
import { backtestApi } from '@/api/backtest'
import { useTheme } from '@/composables/useTheme'

const { colors, echartsTheme } = useTheme()
const stage = ref('oos')
const loading = ref(false)
const error = ref('')
const result = ref(null)
const chartRef = ref(null)
let chart = null

const percent = value => `${value >= 0 ? '+' : ''}${Number(value || 0).toFixed(2)}%`
const annualColumns = [
  { title: '年份', key: 'year' },
  { title: '年度收益', key: 'return_pct', render: row => percent(row.return_pct) },
  { title: '年内最大回撤', key: 'max_drawdown_pct', render: row => percent(row.max_drawdown_pct) },
  { title: '年末净值', key: 'end_nav', render: row => Number(row.end_nav).toLocaleString('zh-CN', { maximumFractionDigits: 0 }) },
]
const tradeColumns = [
  { title: 'ETF', key: 'code', width: 110 },
  { title: '名称', key: 'name', width: 85 },
  { title: '买入', key: 'buy_date', width: 95 },
  { title: '卖出', key: 'sell_date', width: 95 },
  { title: '0AMV信号', key: 'buy_signal_type', width: 90 },
  { title: '选择', key: 'selection_type', width: 125 },
  { title: '成交额分位', key: 'amount_quintile', width: 95 },
  { title: '成交量分位', key: 'volume_quintile', width: 95 },
  { title: '成交额乖离', key: 'amount_ratio_7_20', width: 100, render: row => row.amount_ratio_7_20?.toFixed(2) ?? '-' },
  { title: '收益', key: 'pnl_pct', width: 90, render: row => percent(row.pnl_pct) },
  { title: '持有天数', key: 'hold_days', width: 85 },
  { title: '卖出原因', key: 'sell_reason', width: 220 },
]

function buildChart() {
  if (!chartRef.value || !result.value) return
  chart?.dispose()
  chart = echarts.init(chartRef.value, echartsTheme.value)
  const points = result.value.nav || []
  const dates = points.map(point => point.date)
  chart.setOption({
    title: { text: `成交额低分位ETF轮动 · ${stage.value.toUpperCase()}`, left: 'center', textStyle: { fontSize: 15 } },
    tooltip: { trigger: 'axis' },
    legend: { top: 28, data: ['组合净值', '回撤'] },
    grid: [{ left: 65, right: 25, top: 62, height: '46%' }, { left: 65, right: 25, top: '69%', height: '17%' }],
    xAxis: [
      { type: 'category', data: dates, boundaryGap: false, axisLabel: { show: false } },
      { type: 'category', gridIndex: 1, data: dates, boundaryGap: false, axisLabel: { rotate: 45, fontSize: 10 } },
    ],
    yAxis: [
      { type: 'value', scale: true, splitLine: { lineStyle: { color: colors.value.border } } },
      { type: 'value', gridIndex: 1, axisLabel: { formatter: '{value}%' }, splitLine: { lineStyle: { color: colors.value.border } } },
    ],
    dataZoom: [{ type: 'inside', xAxisIndex: [0, 1] }, { type: 'slider', xAxisIndex: [0, 1], bottom: 8 }],
    series: [
      { name: '组合净值', type: 'line', data: points.map(point => point.nav), showSymbol: false, smooth: false, lineStyle: { width: 2, color: '#1565C0' } },
      { name: '回撤', type: 'line', xAxisIndex: 1, yAxisIndex: 1, data: points.map(point => point.drawdown_pct), showSymbol: false, areaStyle: { color: '#EF5350', opacity: 0.28 }, lineStyle: { color: '#E53935' } },
    ],
  })
}

async function loadData() {
  loading.value = true
  error.value = ''
  try {
    result.value = await backtestApi.getAmountRatioRotation(stage.value)
    await nextTick()
    buildChart()
  } catch (err) {
    result.value = null
    error.value = err.message || '成交额低分位轮动回测数据加载失败'
  } finally {
    loading.value = false
  }
}

watch(echartsTheme, () => { if (chart) nextTick(buildChart) })
onMounted(loadData)
onUnmounted(() => chart?.dispose())
</script>

<style scoped>
.rotation-chart { width: 100%; height: 560px; }
</style>
