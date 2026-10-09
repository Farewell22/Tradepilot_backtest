/**
 * TradePilot 应用入口
 */
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import naive from 'naive-ui'
import * as echarts from 'echarts'
import { echartsLightTheme } from './theme/echarts-light'
import App from './App.vue'
import router from './router'

echarts.registerTheme('tradepilot-light', echartsLightTheme)

const app = createApp(App)
const pinia = createPinia()

app.use(pinia)
app.use(router)
app.use(naive)

app.mount('#app')

const loadingEl = document.getElementById('app-loading')
if (loadingEl) {
  loadingEl.classList.add('fade-out')
  setTimeout(() => loadingEl.parentNode && loadingEl.remove(), 300)
}
