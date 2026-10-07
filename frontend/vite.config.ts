import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: { host: '127.0.0.1', port: 5173, proxy: { '/api': { target: process.env.RIW_BACKEND_URL || 'http://127.0.0.1:8000', changeOrigin: true } } },
  build: { rollupOptions: {output: {manualChunks: {pdf: ['pdfjs-dist'], vendor: ['react', 'react-dom']}}} }
})
