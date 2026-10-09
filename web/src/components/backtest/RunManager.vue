<template>
  <div>
    <n-space align="center" style="margin-bottom: 12px;">
      <n-text depth="3" strong>共 {{ runs.length }} 个回测运行</n-text>
      <n-button size="small" @click="refresh" :loading="refreshing">刷新</n-button>
    </n-space>

    <n-data-table
      :columns="columns"
      :data="runs"
      :bordered="false"
      :single-line="false"
      size="small"
      max-height="700"
      virtual-scroll
    />

    <!-- 重命名弹窗 -->
    <n-modal v-model:show="renameModal.show" title="重命名" preset="dialog" :mask-closable="false"
      :positive-text="'确认'" :negative-text="'取消'"
      @positive-click="doRename"
      @negative-click="renameModal.show = false"
    >
      <n-input v-model:value="renameModal.newName" placeholder="输入新目录名" />
      <n-text depth="3" style="font-size: 12px;">仅允许字母、数字、下划线、横线。操作不可逆。</n-text>
    </n-modal>

    <!-- 备注弹窗 -->
    <n-modal v-model:show="notesModal.show" title="编辑备注" preset="dialog" :mask-closable="false"
      :positive-text="'保存'" :negative-text="'取消'"
      @positive-click="doSaveNotes"
      @negative-click="notesModal.show = false"
    >
      <n-input v-model:value="notesModal.text" type="textarea" :rows="4" placeholder="输入备注内容" />
    </n-modal>
  </div>
</template>

<script setup>
import { ref, h, onMounted } from 'vue'
import { backtestApi } from '@/api/backtest'
import { NDataTable, NSpace, NText, NButton, NModal, NInput, useMessage } from 'naive-ui'

const emit = defineEmits(['runs-changed'])

const msg = useMessage()
const runs = ref([])
const refreshing = ref(false)

const renameModal = ref({ show: false, runId: '', newName: '' })
const notesModal = ref({ show: false, runId: '', text: '' })

async function load() {
  try {
    runs.value = await backtestApi.listRuns()
  } catch (e) {
    msg.error('加载失败')
  }
}

async function refresh() {
  refreshing.value = true
  await load()
  emit('runs-changed')
  refreshing.value = false
}

function openRename(runId) {
  renameModal.value = { show: true, runId, newName: runId }
}

function openNotes(runId) {
  notesModal.value = { show: true, runId, text: '' }
  backtestApi.getRunMeta(runId)
    .then(m => notesModal.value.text = m?.notes || '')
    .catch(() => {})
}

async function doRename() {
  const r = renameModal.value
  if (!r.newName || r.newName === r.runId) return false
  try {
    await backtestApi.renameRun(r.runId, r.newName)
    msg.success('已重命名')
    r.show = false
    await load()
    emit('runs-changed')
  } catch (e) {
    msg.error(e.message || '重命名失败')
    return false
  }
  return true
}

async function doSaveNotes() {
  const r = notesModal.value
  try {
    await backtestApi.updateRunMeta(r.runId, r.text)
    msg.success('备注已保存')
    r.show = false
  } catch (e) {
    msg.error(e.message || '保存失败')
    return false
  }
  return true
}

async function doDelete(runId) {
  try {
    await backtestApi.deleteRun(runId)
    msg.success('已删除')
    await load()
    emit('runs-changed')
  } catch (e) {
    msg.error(e.message || '删除失败')
  }
}

const columns = [
  { title: '目录名', key: 'run_id', width: 220, fixed: 'left' },
  { title: '年份', key: 'year', width: 60 },
  { title: '有报告', key: 'has_report', width: 70,
    render: (r) => r.has_report ? '✅' : '—' },
  { title: '有NAV', key: 'has_nav', width: 65,
    render: (r) => r.has_nav ? '✅' : '—' },
  { title: '有交易', key: 'has_trades', width: 65,
    render: (r) => r.has_trades ? '✅' : '—' },
  {
    title: '操作', key: 'actions', width: 200, fixed: 'right',
    render: (r) => {
      const btns = []
      if (r.has_report) {
        btns.push(h('span', {
          style: { cursor: 'pointer', color: 'var(--n-color-target, #2196F3)', fontSize: '12px', marginRight: '10px' },
          onClick: () => openRename(r.run_id),
        }, '重命名'))
        btns.push(h('span', {
          style: { cursor: 'pointer', color: 'var(--n-color-target, #2196F3)', fontSize: '12px', marginRight: '10px' },
          onClick: () => openNotes(r.run_id),
        }, '备注'))
        btns.push(h('span', {
          style: { cursor: 'pointer', color: '#FF1744', fontSize: '12px' },
          onClick: () => {
            if (window.confirm(`确认删除「${r.run_id}」？不可恢复！`))
              doDelete(r.run_id)
          },
        }, '删除'))
      }
      return h('span', {}, btns)
    }
  },
]

onMounted(load)
</script>
