import {test,expect} from '@playwright/test';

async function addView(page, name) {
  await page.goto('/config#/views/new');
  await page.locator('#view-name').fill(name);
  await page.getByRole('button',{name:'Preview changes'}).click();
  await expect(page.locator('#review')).toContainText(`added: ${name}`);
}

async function apply(page) {
  await page.locator('#apply').click();
  await expect(page.locator('#message')).toContainText('Changes applied');
}

test('phone browser preview/apply, stale edit, two owners, rollback and logout',async ({page,browser})=>{
  await page.goto('/test/login/alice');
  await expect(page.locator('#message')).toContainText('Configuration loaded');
  await addView(page,'phone');
  await apply(page);
  await page.goto('/config#/views');
  await expect(page.locator('#views')).toContainText('phone');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({path:'test-results/phone-admin.png',fullPage:true});
  const stale = await page.context().newPage();
  await stale.goto('/config#/json');
  await expect(stale.locator('#message')).toContainText('Configuration loaded');
  await addView(page,'newer');
  await apply(page);
  await stale.locator('#preview').click();
  await expect(stale.locator('#message')).toContainText('Configuration changed');
  const other = await browser.newContext({viewport:{width:390,height:844}});
  const bob = await other.newPage();
  await bob.goto('http://127.0.0.1:8769/test/login/bob');
  await expect(bob.locator('#message')).toContainText('Configuration loaded');
  await bob.goto('http://127.0.0.1:8769/config#/json');
  await expect(bob.locator('#config')).not.toHaveValue(/phone/);
  await page.goto('/config#/history');
  await page.getByRole('button',{name:'Preview rollback'}).last().click();
  await expect(page.locator('#apply')).toBeEnabled();
  await apply(page);
  await page.goto('/config#/views');
  await expect(page.locator('#views')).not.toContainText('newer');
  await page.locator('#logout').click();
  await expect(page).not.toHaveURL(/\/config$/);
  await other.close();
});

test('server editor keeps full arguments and creates own API keys',async ({page})=>{
  await page.goto('/test/login/bob');
  await page.goto('/config#/servers/new');
  await page.locator('#server-name').fill('args');
  await page.locator('[id^="cmd-"]').fill('fixture');
  for (const value of ['--user-agent','My Agent 1.0']) {
    await page.getByRole('button',{name:'Add argument'}).click();
    await page.getByLabel('Argument').last().fill(value);
  }
  await page.getByRole('button',{name:'Preview changes'}).click();
  await expect(page.locator('#review')).toContainText('added: args');
  await apply(page);
  await page.goto('/config#/servers/args');
  await expect(page.getByText('Stored value (hidden)')).toHaveCount(2);
  await page.goto('/config#/keys');
  await page.getByLabel('Name').fill('phone-agent');
  await page.getByRole('button',{name:'Create key'}).click();
  await expect(page.locator('.secret-box code')).toContainText('mcp_key_');
  await expect(page.locator('tbody')).toContainText('phone-agent');
  page.once('dialog',dialog=>dialog.accept());
  await page.getByRole('button',{name:'Revoke'}).click();
  await expect(page.locator('tbody')).toContainText('revoked');
});

test('sandboxed MCP App uses standard bridge and rejects inline credentials',async ({page})=>{
  await page.goto('/test/login/alice');
  await page.goto('/test/host');
  const app = page.frameLocator('#app');
  await expect(app.locator('#message')).toContainText('Configuration loaded');
  await expect(app.locator('#logout')).toBeHidden();
  await expect(app.locator('#browser-link')).toBeVisible();
  await expect(app.getByRole('link',{name:'API keys'})).toHaveCount(0);
  await app.getByRole('link',{name:'JSON'}).click();
  const config = JSON.parse(await app.locator('#config').inputValue());
  config.tool_views.embedded = {include_all:true};
  await app.locator('#config').fill(JSON.stringify(config));
  await app.locator('#preview').click();
  await expect(app.locator('#review')).toContainText('added: embedded');
  await app.locator('#apply').click();
  await expect(app.locator('#message')).toContainText('Changes applied');
  await app.getByRole('link',{name:'JSON'}).click();
  const next = JSON.parse(await app.locator('#config').inputValue());
  next.mcp_servers.private={command:'echo',env:{KEY:'do-not-send'}};
  await app.locator('#config').fill(JSON.stringify(next));
  await app.locator('#preview').click();
  await expect(app.locator('#message')).toContainText('Invalid request');
  await page.screenshot({path:'test-results/embedded-admin.png',fullPage:true});
});

test('phone view edit applies while an existing MCP call finishes',async ({page,request})=>{
  await page.goto('/test/login/alice');
  await page.goto('/config#/servers/new');
  await page.locator('#server-name').fill('fixture');
  await page.locator('[id^="cmd-"]').fill('fixture');
  await page.getByRole('button',{name:'Preview changes'}).click();
  await expect(page.getByRole('button',{name:'Test fixture'})).toBeVisible();
  await page.getByRole('button',{name:'Test fixture'}).click();
  await expect(page.locator('#message')).toContainText('connected');
  await apply(page);
  const pending=request.post('/mcp',{headers:{Authorization:'Bearer alice',Accept:'application/json, text/event-stream','MCP-Protocol-Version':'2025-03-26'},data:{jsonrpc:'2.0',id:1,method:'tools/call',params:{name:'hold',arguments:{}}}});
  await expect.poll(async()=>{
    const response=await request.get('/config/api/status',{headers:{Authorization:'Bearer alice'}});
    return (await response.json()).in_flight;
  }).toBe(1);
  await addView(page,'during-call');
  await apply(page);
  const result=await pending;
  expect(result.ok()).toBe(true);
  expect(await result.text()).toContain('fixture:completed');
});
