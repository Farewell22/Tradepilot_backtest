<template>
  <n-layout class="main-layout" has-sider>
    <n-layout-sider
      bordered
      :collapsed="collapsed"
      collapse-mode="width"
      :collapsed-width="64"
      :width="220"
      show-trigger="arrow-circle"
      @collapse="collapsed = true"
      @expand="collapsed = false"
      class="layout-sider"
    >
      <div class="sidebar-header">
        <img src="/favicon.svg" class="logo-icon" alt="TradePilot">
        <div v-if="!collapsed" class="logo-text">
          <div class="logo-title">TradePilot</div>
          <div class="logo-subtitle">回测系统</div>
        </div>
      </div>
      <n-menu
        :options="menuOptions"
        :value="route.name"
        @update:value="onMenuClick"
        class="sidebar-menu"
      />
    </n-layout-sider>

    <n-layout>
      <n-layout-header bordered class="layout-header">
        <div class="header-title">{{ currentTitle }}</div>
        <div class="header-actions">
          <n-button quaternary circle @click="toggleTheme" :title="isDark ? '切换到亮色' : '切换到暗色'">
            <template #icon>
              <n-icon size="18">
                <component :is="isDark ? BulbFilled : BulbOutlined" />
              </n-icon>
            </template>
          </n-button>
        </div>
      </n-layout-header>
      <n-layout-content class="layout-content">
        <router-view />
      </n-layout-content>
    </n-layout>
  </n-layout>
</template>

<script setup>
import { ref, computed, h } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NIcon } from 'naive-ui'
import { BarChartOutlined, LineChartOutlined, BulbOutlined, BulbFilled } from '@vicons/antd'
import { useTheme } from '@/composables/useTheme'

const route = useRoute()
const router = useRouter()
const collapsed = ref(false)
const { isDark, toggle: toggleTheme } = useTheme()

const menuOptions = [
  {
    label: '评分入口',
    key: 'Rater',
    icon: () => h(NIcon, null, () => h(LineChartOutlined)),
  },
  {
    label: '回测分析',
    key: 'Backtest',
    icon: () => h(NIcon, null, () => h(BarChartOutlined)),
  },
]

const currentTitle = computed(() => {
  const item = menuOptions.find(m => m.key === route.name)
  return item ? item.label : ''
})

function onMenuClick(key) {
  router.push({ name: key })
}
</script>

<style scoped>
.main-layout { height: 100vh; }
.layout-sider { background: var(--bg-sider); }
.sidebar-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border-primary);
}
.logo-icon { width: 28px; height: 28px; }
.logo-title { font-size: 16px; font-weight: 700; color: var(--text-gold); }
.logo-subtitle { font-size: 11px; color: var(--text-muted); }
.sidebar-menu { padding: 12px 8px; }
.layout-header {
  height: 56px;
  padding: 0 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: var(--bg-header);
}
.header-title { font-size: 16px; font-weight: 600; }
.layout-content {
  padding: 0;
  background: var(--bg-primary);
  overflow-y: auto;
  height: calc(100vh - 56px);
}
</style>
