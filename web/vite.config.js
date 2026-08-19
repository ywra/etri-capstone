import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// /api 요청을 web_api.py로 넘긴다. 브라우저에는 동일 출처로 보이므로 CORS 설정이 필요 없다.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    strictPort: true,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000' },
    },
  },
})
