// 실제 계산 API와 후보 저장을 호출한다. 실행 후 임시 계정을 삭제한다.
const fs = require('node:fs');
const assert = require('node:assert/strict');
const path = require('node:path');
const net = require('node:net');
const { spawn, spawnSync } = require('node:child_process');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || '../frontend/node_modules/playwright');
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
    log = fs.openSync(path.join(output, 'funding-next.log'), 'w');
    server = spawn(process.execPath, [path.join(root, 'frontend/node_modules/next/dist/bin/next'), 'dev', '--hostname', '127.0.0.1', '--port', String(port)], {
      cwd: path.join(root, 'frontend'), env: { ...process.env, NEXT_PUBLIC_API_URL: process.argv[2] }, stdio: ['ignore', log, log], windowsHide: true,
    });
  }
  const errors = [];
  let registered = false;
  const evidence = { status: 'running', stages: [], calculator_mocked: false,
    frontend_mode: server ? 'development' : 'running_service',
    boundaries: ['검증용 후보로 실제 계산·저장을 호출함. 실호가·법령 예외·LLM 응답 품질 검증은 별도'], started_at: new Date().toISOString() };
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
      email: `funding-browser-${Date.now()}@example.com`, password: 'funding-browser-only-12345', name: '자금 검증 임시 계정',
    } });
    assert.equal(register.status(), 201); registered = true;
    const profile = { cash_available: 400000000, emergency_reserve: 50000000, monthly_payment_limit: 2000000,
      annual_income: 100000000, existing_loan_annual_payment: 1200000, loan_ratio: 0.5,
      annual_interest_rate: 4.25, loan_years: 27, owned_homes: 2, adjusted_area: false };
    const created = await context.request.post('/api/cases', { data: { title: '자금 의사결정 검증', buyer_profile: profile } });
    assert.equal(created.status(), 201);
    const caseId = (await created.json()).id;
    const casePath = `/api/cases/${caseId}`;
    const added = await context.request.post(`${casePath}/properties`, { data: {
      name: '자금 검증 후보', category: 'apartment', asking_price: 600000000,
    } });
    assert.equal(added.status(), 201);
    const candidateId = (await added.json()).id;
    await page.goto(`/cases/${caseId}`);
    await page.locator('a[href="/simulation"]').filter({ hasText: '자금 분석' }).click();
    await page.waitForURL('**/simulation');
    await page.getByPlaceholder('예: 8000만').waitFor();
    await page.waitForFunction(() => document.getElementById('owned-homes')?.value === '2');
    assert.equal(await page.getByLabel('매수가 (원)', { exact: true }).inputValue(), '60000만', '후보 가격 자동 채움');
    assert.equal(await page.locator('select').first().inputValue(), '아파트');
    assert.equal(await page.getByLabel('취득 후 주택 수', { exact: true }).inputValue(), '2');
    assert.equal(await page.getByLabel('보유 현금 (원)', { exact: true }).inputValue(), '350000000');
    assert.equal(await page.getByLabel('월 대출 상환 한도 (원)', { exact: true }).inputValue(), '2000000');
    assert.equal(await page.getByLabel('연 이율 (%)', { exact: true }).inputValue(), '4.25');
    assert.equal(await page.getByLabel('대출 기간 (년)', { exact: true }).inputValue(), '27');
    await page.getByLabel('취득 후 주택 수', { exact: true }).fill('0');
    await page.getByRole('button', { name: '💰 시뮬레이션 계산', exact: true }).click();
    await page.getByText('취득 후 주택 수는 1~100의 정수로 입력해주세요. 첫 주택 취득은 1입니다.').waitFor();
    await page.getByLabel('취득 후 주택 수', { exact: true }).fill('2');
    evidence.stages.push('common_profile_prefill_after_purchase_count', 'invalid_count_rejected');
    const calculate = async () => {
      const pending = page.waitForResponse(r => r.url().endsWith('/api/simulation') && r.request().method() === 'POST');
      await page.getByRole('button', { name: '💰 시뮬레이션 계산', exact: true }).click();
      const response = await pending;
      assert.equal(response.status(), 200);
      const body = await response.json(); assert.ok(!body.error);
      assert.equal(body.result.purchase_price, 600000000);
      assert.equal(body.result.owned_homes, 2);
      assert.equal(body.result.home_count_basis, 'after_purchase');
      assert.equal(body.result.acquisition_cost.acquisition_tax, 48000000);
      assert.ok(body.candidate_funding);
      return body;
    };
    const baseline = await (await context.request.post(`${casePath}/funding-scenarios`, { data: {} })).json();
    const fromProfile = await calculate();
    assert.deepEqual(fromProfile.candidate_funding, baseline.rows[0].baseline.summary);
    evidence.stages.push('browser_calculation_matches_case_scenario');
    await page.getByLabel('보유 현금 (원)', { exact: true }).fill('3억');
    await page.getByLabel('월 대출 상환 한도 (원)', { exact: true }).fill('10만');
    const first = await calculate();
    evidence.stages.push('candidate_price_type_prefill', 'real_calculation_saved');
    await page.getByRole('link', { name: '후보 비교·다음 행동 확인' }).click();
    await page.getByText('부족한 자금 조달 확인', { exact: true }).waitFor();
    await page.getByText('월 상환 부담 확인', { exact: true }).waitFor();
    const comparison = await (await context.request.get(`${casePath}/comparison`)).json();
    assert.equal(comparison.rows[0].funding.monthly_payment, first.result.loan.monthly_payment);
    assert.equal(comparison.rows[0].funding.cash_shortfall, first.result.acquisition_cost.total);
    assert.equal(comparison.rows[0].decision_ready, false);
    evidence.stages.push('comparison_funding_warnings');
    await page.goto(`/cases/${caseId}`);
    await page.locator('a[href="/simulation"]').filter({ hasText: '자금 분석' }).click();
    await page.waitForURL('**/simulation');
    await page.getByLabel('보유 현금 (원)', { exact: true }).waitFor();
    await page.waitForFunction(() => document.getElementById('owned-homes')?.value === '2');
    assert.equal(await page.getByLabel('보유 현금 (원)', { exact: true }).inputValue(), '300000000');
    await page.reload();
    await page.getByLabel('취득 후 주택 수', { exact: true }).waitFor();
    await page.waitForFunction(() => document.getElementById('owned-homes')?.value === '2');
    assert.equal(await page.getByLabel('취득 후 주택 수', { exact: true }).inputValue(), '2');
    assert.equal(await page.getByLabel('보유 현금 (원)', { exact: true }).inputValue(), '300000000');
    await page.getByRole('button', { name: '공통 자금 조건 적용', exact: true }).click();
    assert.equal(await page.getByLabel('보유 현금 (원)', { exact: true }).inputValue(), '350000000');
    assert.equal(await page.getByLabel('월 대출 상환 한도 (원)', { exact: true }).inputValue(), '2000000');
    evidence.stages.push('refresh_retains_saved_conditions', 'apply_common_profile_without_double_reserve');
    await page.getByLabel('보유 현금 (원)', { exact: true }).fill('6.5억');
    await page.getByLabel('월 대출 상환 한도 (원)', { exact: true }).fill('500만');
    const second = await calculate();
    assert.equal(second.candidate_funding.cash_available, 650000000);
    assert.equal(second.candidate_funding.cash_shortfall, 0);
    assert.equal(second.candidate_funding.monthly_payment_exceeded, false);
    const detail = await (await context.request.get(casePath)).json();
    assert.ok(!detail.properties[0].next_actions.some(a => a.code.startsWith('funding_')));
    evidence.stages.push('saved_criteria_prefill', 'decimal_money_parsing', 'recalculation_clears_warnings');
    await context.request.patch(`${casePath}/properties/${candidateId}`, { data: { asking_price: 610000000 } });
    await page.goto(`/cases/${caseId}`); await page.reload();
    await page.getByText('변경된 가격으로 자금 조건 확인', { exact: true }).waitFor();
    evidence.stages.push('price_change_requires_review');
    await page.goto(`/cases/${caseId}/summary`);
    await page.getByText('자금 분석에 사용한 입력 조건', { exact: true }).click();
    await page.getByText('취득 후 주택 수 (이번 취득 포함)', { exact: true }).waitFor();
    // 다음 행동에서도 기존 분석 조건을 전달해야 상세 화면과 결과가 같아진다.
    await page.getByRole('region', { name: '자금 검증 후보 다음 행동' }).getByRole('listitem').filter({ hasText: '변경된 가격으로 자금 조건 확인' }).getByRole('link', { name: '분석으로 이동', exact: true }).click();
    await page.waitForURL('**/simulation');
    await page.getByLabel('취득 후 주택 수', { exact: true }).waitFor();
    assert.equal(await page.getByLabel('취득 후 주택 수', { exact: true }).inputValue(), '2');
    assert.equal(await page.getByLabel('보유 현금 (원)', { exact: true }).inputValue(), '650000000');
    assert.equal(await page.getByLabel('매수가 (원)', { exact: true }).inputValue(), '61000만');
    evidence.stages.push('summary_next_action_uses_same_funding_seed');
    fs.mkdirSync('evaluation-results', { recursive: true });
    await page.screenshot({ path: path.join(output, server ? 'funding-browser-ci.png' : 'funding-browser.png'), fullPage: true });
    assert.deepEqual(errors, []);
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
    fs.mkdirSync('evaluation-results', { recursive: true });
    evidence.finished_at = new Date().toISOString();
    fs.writeFileSync(path.join(output, server ? 'funding-browser-ci-result.json' : 'funding-browser-result.json'), JSON.stringify(evidence, null, 2));
    if (browser) await browser.close();
    if (server?.pid) { if (process.platform === 'win32') spawnSync('taskkill', ['/PID', String(server.pid), '/T', '/F'], { windowsHide: true, stdio: 'ignore' }); else server.kill('SIGTERM'); }
    if (log !== undefined) fs.closeSync(log);
  }
})();
