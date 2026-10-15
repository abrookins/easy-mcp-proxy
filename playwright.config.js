import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir:'./tests/ui', fullyParallel:false, workers:1,
  use:{baseURL:'http://127.0.0.1:8769',viewport:{width:390,height:844}},
  webServer:{command:'uv run python -m tests.ui_server',url:'http://127.0.0.1:8769/health',reuseExistingServer:false},
  reporter:'list',
});
