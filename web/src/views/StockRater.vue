<template>
  <div class="stock-rater-page">
    <div class="page-header">
      <div class="header-main">
        <div class="header-title">
          <span class="title-emoji">📊</span>
          <h1>评分入口</h1>
        </div>
        <p class="header-subtitle">B1 方法 / 砖型图方法 智能评分</p>
      </div>
    </div>

    <n-card class="input-card" :bordered="false">
      <n-space vertical :size="16">
        <n-space align="center" :size="12" wrap>
          <span class="method-label">评分方法：B1 方法</span>
          <n-input v-model:value="runName" placeholder="运行名称（可选）" style="width: 220px" />
        </n-space>

        <n-input
          v-model:value="stockInput"
          type="textarea"
          placeholder="输入股票代码，每行一个&#10;支持格式：&#10;• 000423&#10;• 000423 东阿阿胶&#10;• 600519 贵州茅台"
          :rows="8"
          :loading="store.loading"
          @keyup.ctrl.enter="handleRate"
        />

        <n-space align="center" justify="space-between">
          <n-text depth="3">已识别 {{ parsedCodes.length }} 只</n-text>
          <n-button
            type="primary"
            size="large"
            :loading="store.loading"
            :disabled="parsedCodes.length === 0"
            @click="handleRate"
          >
            <template #icon><n-icon><RocketIcon /></n-icon></template>
            开始评分 (Ctrl+Enter)
          </n-button>
        </n-space>
      </n-space>
    </n-card>

    <transition name="fade">
      <n-card
        v-if="store.hasResults"
        class="results-card"
        :bordered="false"
      >
        <template #header>
          <div class="card-header">
            <span class="card-title">📈 评分结果</span>
            <n-space>
              <n-tag type="success">PASS: {{ store.passCount }}</n-tag>
              <n-tag type="warning">WATCH: {{ store.watchCount }}</n-tag>
              <n-tag type="error">FAIL: {{ store.failCount }}</n-tag>
            </n-space>
          </div>
        </template>
        <RatingTable :data="store.currentResults" />
        <template #footer>
          <n-space justify="end">
            <n-button @click="store.clearResults()">清除结果</n-button>
          </n-space>
        </template>
      </n-card>
    </transition>

    <n-card class="history-card" :bordered="false">
      <template #header>
        <div class="card-header">
          <span class="card-title">🗄️ 历史评分运行</span>
          <n-button text @click="loadHistory">
            <template #icon><n-icon><ReloadIcon /></n-icon></template>
            刷新
          </n-button>
        </div>
      </template>
      <n-empty v-if="store.runHistory.length === 0" description="暂无历史运行" />
      <n-list v-else hoverable clickable>
        <n-list-item
          v-for="run in store.runHistory"
          :key="run.id"
          @click="viewRun(run.id)"
        >
          <n-thing :title="`${run.name} (${run.id})`" :description="`方法：${run.method} · 模式：${run.mode} · 股票数：${run.stock_count} · 时间：${run.created_at}`">
            <template #footer>
              <n-button size="small" quaternary @click.stop="onRename(run)">重命名</n-button>
              <n-button size="small" quaternary type="error" @click.stop="onDelete(run)">删除</n-button>
            </template>
          </n-thing>
        </n-list-item>
      </n-list>
    </n-card>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useMessage } from 'naive-ui'
import { RocketOutlined as RocketIcon, ReloadOutlined as ReloadIcon } from '@vicons/antd'
import { useStockStore } from '@/stores/stock'
import { stockApi } from '@/api'
import RatingTable from '@/components/RatingTable.vue'

const store = useStockStore()
const message = useMessage()

const stockInput = ref('')
const runName = ref('')

const CODE_NAME_RE = /^\s*(\d{6})\s*(.*?)\s*$/

const parsedCodes = computed(() => {
  const items = []
  for (const line of stockInput.value.split('\n')) {
    if (!line.trim()) continue
    const m = line.match(CODE_NAME_RE)
    if (m) items.push({ code: m[1], name: m[2] || '' })
  }
  return items
})

function dateStr(d) {
  return d.getFullYear().toString() +
    String(d.getMonth() + 1).padStart(2, '0') +
    String(d.getDate()).padStart(2, '0')
}

async function handleRate() {
  const codes = parsedCodes.value
  if (codes.length === 0) {
    message.warning('请输入至少一个股票代码')
    return
  }
  try {
    const today = new Date()
    const start = new Date(today)
    start.setFullYear(start.getFullYear() - 1)
    const startStr = dateStr(start)
    const endStr = dateStr(today)

    const stocks = []
    for (const { code, name } of codes) {
      const resp = await stockApi.fetchKLine([code], startStr, endStr)
      const klines = (resp && resp.data && resp.data[code]) || []
      stocks.push({ code, name, klines })
    }
    await store.rateStocks(stocks, 'b1', 'aggressive', runName.value)
    message.success(`评分完成，共 ${store.currentResults.length} 只`)
    runName.value = ''
  } catch (e) {
    message.error(e.message)
  }
}

async function loadHistory() {
  try {
    await store.fetchRuns()
  } catch (e) {
    message.error(e.message)
  }
}

async function viewRun(id) {
  try {
    await store.fetchRun(id)
    message.info(`已加载运行 ${id}`)
  } catch (e) {
    message.error(e.message)
  }
}

async function onDelete(run) {
  if (!confirm(`确认删除运行 ${run.name}？`)) return
  try {
    await store.deleteRun(run.id)
    message.success('已删除')
  } catch (e) {
    message.error(e.message)
  }
}

async function onRename(run) {
  const name = prompt('新的运行名称：', run.name)
  if (name === null || name === run.name) return
  try {
    await store.renameRun(run.id, name)
    message.success('已重命名')
  } catch (e) {
    message.error(e.message)
  }
}

onMounted(() => {
  loadHistory()
})
</script>

<style scoped>
.stock-rater-page {
  padding: 16px 24px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.page-header {
  margin-bottom: 4px;
}
.header-title {
  display: flex;
  align-items: center;
  gap: 12px;
}
.title-emoji { font-size: 28px; }
.header-title h1 { margin: 0; font-size: 22px; }
.header-subtitle { color: var(--n-text-color-3, #999); margin: 4px 0 0; font-size: 13px; }
.method-label { font-weight: 500; }
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.card-title { font-weight: 600; }
.fade-enter-active, .fade-leave-active { transition: opacity .3s; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
