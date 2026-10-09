/**
 * API 客户端配置（走 vite proxy /api → Python main.py :8081）
 */
import axios from 'axios'

const client = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api/v1',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json'
  }
})

client.interceptors.response.use(
  response => response.data,
  error => {
    const message = error.response?.data?.detail
      || error.response?.data?.error
      || error.message
      || '请求失败'
    console.error('[API Error]', message)
    return Promise.reject(new Error(message))
  }
)

export default client
