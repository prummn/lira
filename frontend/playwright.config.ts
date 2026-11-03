import { defineConfig } from '@playwright/test'
import { randomUUID } from 'node:crypto'
const frontendPort=Number(process.env.RIW_E2E_PORT || 5177)
if (!Number.isInteger(frontendPort) || frontendPort < 1024 || frontendPort > 65535 || [5173,59877,8000,8010].includes(frontendPort)) throw new Error('E2E frontend must use a dedicated test port')
const mockOnly=process.env.RIW_E2E_MOCK==='1'
const isolationToken=process.env.RIW_E2E_TOKEN || randomUUID()
process.env.RIW_E2E_TOKEN=isolationToken
export default defineConfig({
  globalSetup:mockOnly?undefined:'./testing/isolated-backend.mjs',
  testDir: './tests', fullyParallel: false, workers: 1, timeout: 60000,
  use: { baseURL: `http://127.0.0.1:${frontendPort}`, viewport: {width:1440,height:1000}, trace:'retain-on-failure', screenshot:'only-on-failure' },
  webServer: mockOnly ? [{command:`npm run dev -- --port ${frontendPort} --strictPort`,url:`http://127.0.0.1:${frontendPort}`,reuseExistingServer:false,env:{RIW_BACKEND_URL:'http://127.0.0.1:1'},timeout:60000}] : [
    {command:"powershell -NoProfile -ExecutionPolicy Bypass -Command \"& '../backend/.venv/Scripts/python.exe' '../scripts/e2e_backend.py'\"",url:'http://127.0.0.1:8010/api/health',reuseExistingServer:false,env:{RIW_E2E_TOKEN:isolationToken},timeout:60000},
    {command:`npm run dev -- --config vite.config.ts --port ${frontendPort} --strictPort`,url:`http://127.0.0.1:${frontendPort}`,reuseExistingServer:false,env:{RIW_BACKEND_URL:'http://127.0.0.1:8010'},timeout:60000}
  ],
})
