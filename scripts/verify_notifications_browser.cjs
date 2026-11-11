// 변화 알림함: 실제 Spring 저장·Python 조건 계산으로 원본 변경·매물 7일 재확인 알림 생성 → 메뉴 개수 → 개별 읽음·모두 읽음 →
// 확인하러 가기 이동 → 변경 반영·재확인 후 해결 → 390px 표시를 확인한다. 실행 후 임시 계정을 삭제한다.
// 분석 만료·새 실거래는 시간·수집 시각에 따른 조건이라 Python·Kotlin 회귀(tests/test_notification_conditions.py, NotificationIT)가 맡는다.
const fs = require('node:fs');
const assert = require('node:assert/strict');
const path = require('node:path');
const net = require('node:net');
const { spawn, spawnSync } = require('node:child_process');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || '../web/node_modules/playwright');
(async () => {
  const root = path.resolve(__dirname, '..');
  const output = path.join(root, 'evaluation-results');
  fs.mkdirSync(output, { recursive: true });
  let server, log, browser, context, page;
  let baseURL = process.env.E2E_BASE_URL || 'http://localhost:3002';
  if (process.argv[2] && !process.env.E2E_BASE_URL) {
    assert.ok(process.argv[2].startsWith('http://'));
    const port = await new Promise(resolve => { const s = net.createServer(); s.listen(0, '127.0.0.1', () => { const p = s.address().port; s.close(() => resolve(p)); }); });
    baseURL = `http://127.0.0.1:${port}`;
    log = fs.openSync(path.join(output, 'notifications-next.log'), 'w');
    server = spawn(process.execPath, [path.join(root, 'web/node_modules/next/dist/bin/next'), 'dev', '--hostname', '127.0.0.1', '--port', String(port)], {
      cwd: path.join(root, 'web'), env: { ...process.env, NEXT_PUBLIC_API_URL: process.argv[2] }, stdio: ['ignore', log, log], windowsHide: true,
    });
  }
  const errors = [];
  let registered = false;
  const evidence = { status: 'running', stages: [], frontend_mode: server ? 'development' : 'running_service',
    boundaries: ['가상 매물·후보로 실제 저장·조건 계산을 실행함. 분석 만료·새 실거래 알림은 시간 조건이라 자동 회귀가 맡음. 메일·푸시 발송은 없음'],
    started_at: new Date().toISOString() };
  try {
    browser = await chromium.launch(process.env.E2E_BROWSER === 'chromium' ? { headless: true } : { channel: 'chrome', headless: true });
    context = await browser.newContext({ baseURL });
    page = await context.newPage();
    page.setDefaultTimeout(45000);
    page.on('pageerror', error => errors.push(error.message));
    for (let i = 0; i < 40; i++) {
      const response = await context.request.get('/api/auth/me').catch(() => null);
      if (response?.status() === 401) break;
      await new Promise(resolve => setTimeout(resolve, 1000));
    }
    const register = await context.request.post('/api/auth/register', { data: {
      email: `notifications-browser-${Date.now()}@example.com`, password: 'notifications-browser-only-12345', name: '알림 검증 임시 계정',
    } });
    assert.equal(register.status(), 201); registered = true;

    // 가상 매물 3건: 방금 확인한 매물(후보로 저장 후 가격 변경), 확인 후 8·9일 지난 거래 가능 매물 2건.
    const header = 'external_id,name,property_type,transaction_type,address,legal_region_code,area_sqm,asking_price,confirmed_at,status';
    const ago = days => new Date(Date.now() - days * 86400000).toISOString();
    const csv = [header,
      `notify-fresh,알림 원본 매물,apartment,purchase,서울특별시 강남구 역삼동 123,1168010100,84,700000000,${ago(0.01)},active`,
      `notify-old-1,오래된 확인 매물,apartment,purchase,서울특별시 강남구 역삼동 124,1168010100,84,650000000,${ago(8)},active`,
      `notify-old-2,두번째 오래된 매물,apartment,purchase,서울특별시 강남구 역삼동 125,1168010100,59,520000000,${ago(9)},active`].join('\n') + '\n';
    const imported = await context.request.post('/api/listings/import', { data: { source_name: '알림 검증 가상 출처', csv_text: csv, commit: true } });
    assert.equal(imported.status(), 200, await imported.text());
    const listings = (await (await context.request.get('/api/listings?page_size=50')).json()).items;
    const byName = name => listings.find(item => item.name === name);
    const fresh = byName('알림 원본 매물'), old1 = byName('오래된 확인 매물'), old2 = byName('두번째 오래된 매물');
    assert.ok(fresh && old1 && old2, '가상 매물 3건 저장');
    const created = await context.request.post('/api/cases', { data: { title: '변화 알림 검증' } });
    const caseId = (await created.json()).id;
    const linked = await context.request.post(`/api/listings/${fresh.id}/candidate`, { data: { case_id: caseId } });
    assert.ok([200, 201].includes(linked.status()), await linked.text());
    const candidateId = (await linked.json()).id;
    const confirmed = await context.request.post(`/api/listings/${fresh.id}/confirm`, { data: {
      confirmed_at: new Date().toISOString(), status: 'active', asking_price: 750000000 } });
    assert.equal(confirmed.status(), 200, await confirmed.text());

    // 1) 메뉴에 읽지 않은 개수가 표시된다(로그인 직후 첫 계산).
    await page.goto('/');
    const badge = page.locator('aside').getByLabel(/읽지 않은 알림 \d+건/);
    await badge.waitFor();
    assert.equal(await badge.innerText(), '3');
    evidence.stages.push('menu_badge_counts_unread');

    // 2) 알림함에 원본 변경과 매물 재확인이 이유·값과 함께 보인다.
    await page.locator('aside').getByRole('link', { name: /변화 알림/ }).click();
    await page.waitForURL('**/notifications');
    const list = page.getByRole('list', { name: '알림 목록' });
    const source = list.getByRole('listitem').filter({ hasText: '원본 매물이 바뀌었습니다' });
    await source.getByText('희망가 7억원 → 7억 5,000만원', { exact: false }).waitFor();
    await source.getByText('원본 변경').waitFor();
    const old1Item = list.getByRole('listitem').filter({ hasText: '오래된 확인 매물 · 매물 재확인 필요' });
    await old1Item.getByText(/마지막 확인 후 8일이 지났습니다/).waitFor();
    await list.getByRole('listitem').filter({ hasText: '두번째 오래된 매물 · 매물 재확인 필요' }).waitFor();
    assert.equal(await list.getByRole('listitem').count(), 3);
    evidence.stages.push('inbox_shows_source_change_and_reconfirm_reasons');

    // 3) 하나를 읽으면 메뉴 개수가 바로 줄고, 모두 읽음으로 나머지를 처리한다.
    await old1Item.getByRole('button', { name: '읽음', exact: true }).click();
    await page.locator('aside').getByLabel('읽지 않은 알림 2건').waitFor();
    await page.getByRole('button', { name: /모두 읽음/ }).click();
    await page.locator('aside').getByLabel(/읽지 않은 알림/).waitFor({ state: 'detached' });
    assert.equal((await (await context.request.get('/api/notifications/summary')).json()).unread_count, 0);
    evidence.stages.push('read_one_and_read_all_update_menu');

    // 4) 확인하러 가기 → 후보 카드에서 변경을 반영하면 원본 변경 알림이 해결된다.
    await source.getByRole('button', { name: '확인하러 가기' }).click();
    await page.waitForURL(new RegExp(`/cases/${caseId}#candidate-${candidateId}$`));
    await page.getByRole('button', { name: '확인한 변경사항 반영' }).click();
    await page.getByText('원본 매물 재확인 필요').waitFor({ state: 'detached' });
    // 다시 확인한 매물의 재확인 알림도 해결된다.
    const reconfirmed = await context.request.post(`/api/listings/${old1.id}/confirm`, { data: {
      confirmed_at: new Date().toISOString(), status: 'active', asking_price: 650000000 } });
    assert.equal(reconfirmed.status(), 200);
    await page.waitForTimeout(11000);  // 알림함 재계산 최소 간격(10초)
    await page.goto('/notifications');
    await list.getByRole('listitem').first().waitFor();
    const titles = await list.getByRole('listitem').locator('h2').allInnerTexts();
    assert.deepEqual(titles, ['두번째 오래된 매물 · 매물 재확인 필요'], `남은 알림: ${titles.join(' / ')}`);
    evidence.stages.push('applied_change_and_reconfirmed_listing_resolve');

    // 5) 좁은 화면에서도 가로 넘침 없이 읽을 수 있고 메뉴 버튼에 새 알림 표시가 없다(모두 읽음).
    await page.setViewportSize({ width: 390, height: 900 });
    await page.reload();
    await list.getByRole('listitem').first().waitFor();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    assert.ok(overflow <= 1, `가로 넘침 ${overflow}px`);
    assert.equal(await page.getByRole('button', { name: '메뉴 열기' }).count(), 1);
    await page.screenshot({ path: path.join(output, server ? 'notifications-browser-ci.png' : 'notifications-browser.png'), fullPage: true });
    evidence.stages.push('narrow_viewport_without_page_overflow');

    assert.deepEqual(errors, []);
    evidence.stages.push('no_browser_runtime_errors');
    evidence.status = 'passed';
    console.log('PASS', evidence.stages.join(', '));
  } catch (error) {
    evidence.status = 'failed';
    evidence.error = error.message.split('Call log:')[0];
    console.log(evidence.error); process.exitCode = 1;
    if (page) console.log((await page.locator('body').innerText()).slice(0, 1800));
  } finally {
    if (registered) {
      const cleanup = await context.request.delete('/api/auth/me');
      evidence.cleanup_status = cleanup.status();
      if (cleanup.status() !== 200) process.exitCode = 1;
    }
    evidence.finished_at = new Date().toISOString();
    fs.writeFileSync(path.join(output, server ? 'notifications-browser-ci-result.json' : 'notifications-browser-result.json'), JSON.stringify(evidence, null, 2));
    if (browser) await browser.close();
    if (server?.pid) { if (process.platform === 'win32') spawnSync('taskkill', ['/PID', String(server.pid), '/T', '/F'], { windowsHide: true, stdio: 'ignore' }); else server.kill('SIGTERM'); }
    if (log !== undefined) fs.closeSync(log);
  }
})();
