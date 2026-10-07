import { defineConfig } from '@playwright/test'
export default defineConfig({
  testDir: './tests', fullyParallel: false, workers: 1, timeout: 60000,
  use: { baseURL: 'http://127.0.0.1:5177', viewport: {width:1440,height:1000}, trace:'retain-on-failure', screenshot:'only-on-failure' },
  webServer: [
    {command:'python ../scripts/e2e_backend.py',url:'http://127.0.0.1:8010/api/health',reuseExistingServer:false,timeout:60000},
    {command:'npm run dev -- --port 5177 --strictPort',url:'http://127.0.0.1:5177',reuseExistingServer:false,env:{RIW_BACKEND_URL:'http://127.0.0.1:8010'},timeout:60000}
  ],
})
