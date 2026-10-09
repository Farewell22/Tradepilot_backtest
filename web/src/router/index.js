/**
 * TradePilot 路由配置（回测项目，无认证）
 */
import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/', redirect: '/rater' },
  {
    path: '/rater',
    name: 'Rater',
    component: () => import('@/views/StockRater.vue'),
    meta: { title: '评分入口' },
  },
  {
    path: '/backtest',
    name: 'Backtest',
    component: () => import('@/views/Backtest.vue'),
    meta: { title: '回测分析' },
  },
]

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes,
})

router.afterEach((to) => {
  const title = to.meta?.title || 'TradePilot'
  document.title = `${title} - TradePilot`
})

export default router
export { routes }
