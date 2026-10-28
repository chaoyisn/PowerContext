import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The UI talks to the FastAPI backend. Two paths are supported:
//  1. direct  - VITE_API_BASE_URL (default http://127.0.0.1:8787), backend CORS
//     already allows http://localhost:5173 / http://127.0.0.1:5173;
//  2. proxy   - set VITE_API_BASE_URL= (empty) and every /api/* request below
//     goes through this dev-server proxy, no CORS involved at all.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8787',
        changeOrigin: true,
      },
    },
  },
})
