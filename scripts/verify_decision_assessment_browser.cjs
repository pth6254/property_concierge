// 검증용 후보로 실제 자금 계산과 저장을 호출한다. 모든 계정·후보는 실행 후 삭제한다.
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
  let server, log, browser, context, page, registered = false;
  let baseURL = process.env.E2E_BASE_URL || 'http://localhost:3002';
  if (process.argv[2] && !process.env.E2E_BASE_URL) {
    assert.ok(process.argv[2].startsWith('http://'));
    const port = await new Promise(resolve => {
      const socket = net.createServer();
      socket.listen(0, '127.0.0.1', () => { const port = socket.address().port; socket.close(() => resolve(port)); });
    });
    baseURL = `http://127.0.0.1:${port}`;
    log = fs.openSync(path.join(output, 'assessment-next.log'), 'w');
    server = spawn(process.execPath, [path.join(root, 'web/node_modules/next/dist/bin/next'), 'dev', '--hostname', '127.0.0.1', '--port', String(port)], {
      cwd: path.join(root, 'web'), env: { ...process.env, NEXT_PUBLIC_API_URL: process.argv[2] },
      stdio: ['ignore', log, log], windowsHide: true,
    });
  }
  const evidence = { status: 'running', stages: [], calculation_mocked: false,
    frontend_mode: server ? 'development' : 'running_service',
    boundaries: ['검증용 후보의 자금 분석·저장·UI 연결을 확인함. 실제 AVM·권리 PDF 품질과 실호가 검증은 별도'],
    started_at: new Date().toISOString() };
  const errors = [];
  try {
    browser = await chromium.launch(process.env.E2E_BROWSER === 'chromium' ? { headless: true } : { channel: 'chrome', headless: true });
    context = await browser.newContext({ baseURL, viewport: { width: 1365, height: 900 } });
    page = await context.newPage();
    page.setDefaultTimeout(45000);
    page.on('pageerror', error => errors.push(error.message));
    for (let i = 0; i < 40; i++) {
      const response = await context.request.get('/api/auth/me').catch(() => null);
      if (response?.status() === 401) break;
      await new Promise(resolve => setTimeout(resolve, 1000));
    }
    const register = await context.request.post('/api/auth/register', { data: {
      email: `assessment-browser-${Date.now()}@example.com`, password: 'assessment-browser-only-12345', name: '판단 축 검증 임시 계정',
    } });
    assert.equal(register.status(), 201); registered = true;
    const profile = { cash_available: 650000000, emergency_reserve: 0, monthly_payment_limit: 2500000,
      annual_income: 100000000, existing_loan_annual_payment: 0, loan_ratio: 0.5,
      annual_interest_rate: 4.25, loan_years: 30, owned_homes: 1, adjusted_area: false,
      property_types: ['apartment'], min_area_sqm: 70, max_area_sqm: 90 };
    const created = await context.request.post('/api/cases', { data: { title: '의사결정 통합 검증', budget_max: 650000000, buyer_profile: profile } });
    assert.equal(created.status(), 201);
    const caseId = (await created.json()).id;
    const casePath = `/api/cases/${caseId}`;
    const add = async data => {
      const response = await context.request.post(`${casePath}/properties`, { data });
      assert.equal(response.status(), 201);
      return (await response.json()).id;
    };
    const candidateId = await add({ name: '조건 일치 후보', address: '검증용 주소', category: 'apartment', area_sqm: 84, asking_price: 600000000 });
    const otherId = await add({ name: '조건 불일치 후보', address: '검증용 주소 2', category: 'industrial', area_sqm: 50, asking_price: 700000000 });
    const summary = async () => {
      const response = await context.request.get(`${casePath}/summary`);
      assert.equal(response.status(), 200); return response.json();
    };
    let data = await summary();
    assert.equal(data.case.selected_property_id, null);
    assert.equal(data.decision.candidates.length, 2);
    const first = () => data.decision.candidates.find(candidate => candidate.property_id === candidateId);
    const status = key => first().axes.find(axis => axis.key === key).status;
    assert.equal(status('fit'), 'confirmed');
    assert.equal(status('price'), 'unknown');
    assert.equal(status('risk'), 'unknown');
    assert.equal(first().metrics.required_cash, null);
    assert.equal(data.decision.candidates.find(candidate => candidate.property_id === otherId).axes[0].status, 'warning');
    await page.goto(`/cases/${caseId}/summary`);
    await page.getByRole('heading', { name: '매수 검토 요약', exact: true }).waitFor();
    await page.getByRole('region', { name: '후보별 판단 축 비교' }).waitFor();
    const candidate = page.locator(`#decision-candidate-${candidateId}`);
    for (const label of ['적합성', '가격성', '자금성', '위험성', '실행성']) {
      await candidate.getByRole('heading', { name: label, exact: true }).waitFor();
    }
    await candidate.getByRole('region', { name: '조건 일치 후보 위험성', exact: true }).getByText('미확인', { exact: true }).first().waitFor();
    evidence.stages.push('five_axes_and_candidate_comparison', 'missing_analysis_not_zero_or_safe', 'fit_uses_budget_area_type');

    const funding = candidate.getByRole('region', { name: '조건 일치 후보 자금성', exact: true });
    await funding.getByRole('link', { name: '자금 조건 확인·재계산 →', exact: true }).click();
    await page.waitForURL('**/simulation');
    await page.waitForFunction(() => document.getElementById('owned-homes')?.value === '1');
    assert.equal(await page.getByLabel('매수가 (원)', { exact: true }).inputValue(), '60000만');
    assert.equal(await page.getByLabel('보유 현금 (원)', { exact: true }).inputValue(), '650000000');
    const pending = page.waitForResponse(response => response.url().endsWith('/api/simulation') && response.request().method() === 'POST');
    await page.getByRole('button', { name: '💰 시뮬레이션 계산', exact: true }).click();
    const calculated = await pending;
    assert.equal(calculated.status(), 200);
    const actual = await calculated.json();
    assert.ok(actual.candidate_funding); assert.ok(!actual.error);
    data = await summary();
    assert.equal(status('funding'), 'confirmed');
    assert.equal(first().metrics.required_cash, actual.candidate_funding.required_cash);
    assert.equal(first().metrics.monthly_payment, actual.result.loan.monthly_payment);
    assert.equal(first().metrics.price_gap, null);
    assert.equal(data.case.selected_property_id, null);
    evidence.stages.push('axis_link_preserves_candidate_and_common_inputs', 'actual_funding_calculation_saved_and_displayed', 'no_automatic_purchase_choice');
    const compared = await (await context.request.get(`${casePath}/comparison`)).json();
    const comparedCandidate = compared.rows.find(row => row.property_id === candidateId);
    assert.equal(comparedCandidate.decision_ready, first().review_ready);
    assert.equal(comparedCandidate.funding.required_cash, first().metrics.required_cash);
    assert.equal(comparedCandidate.price_gap, first().metrics.price_gap);
    evidence.stages.push('summary_comparison_use_same_assessment');

    await page.goto(`/cases/${caseId}/summary`);
    await candidate.getByRole('heading', { name: '자금성', exact: true }).waitFor();
    const fundingDetails = candidate.getByRole('region', { name: '조건 일치 후보 자금성', exact: true });
    await fundingDetails.locator('summary').click();
    await fundingDetails.getByText('계산 결과 · 기준 시각', { exact: false }).first().waitFor();
    await candidate.getByText('자금 분석에 사용한 입력 조건', { exact: true }).click();
    await candidate.getByText('취득 후 주택 수 (이번 취득 포함)', { exact: true }).waitFor();
    await page.screenshot({ path: path.join(output, server ? 'assessment-browser-ci-desktop.png' : 'assessment-browser-desktop.png'), fullPage: true });
    evidence.stages.push('evidence_provenance_dates_and_recorded_inputs');

    const actions = candidate.getByRole('region', { name: '조건 일치 후보 다음 행동', exact: true });
    await actions.getByRole('button', { name: '희망가 수정', exact: true }).click();
    await actions.getByLabel('희망가(원)', { exact: true }).fill('610000000');
    await actions.getByRole('button', { name: '저장', exact: true }).click();
    await fundingDetails.getByText('갱신 필요', { exact: true }).waitFor();
    data = await summary();
    assert.equal(status('funding'), 'stale');
    assert.equal(first().metrics.required_cash, null);
    const changedComparison = await (await context.request.get(`${casePath}/comparison`)).json();
    assert.equal(changedComparison.rows.find(row => row.property_id === candidateId).funding, null);
    await actions.getByText('변경된 가격으로 자금 조건 확인', { exact: true }).waitFor();
    assert.equal(await candidate.locator('dt').filter({ hasText: /^필요 현금$/ }).first().locator('..').locator('dd').first().innerText(), '미확인');
    await page.reload();
    await candidate.getByRole('heading', { name: '자금성', exact: true }).waitFor();
    await candidate.getByRole('region', { name: '조건 일치 후보 자금성', exact: true }).getByText('갱신 필요', { exact: true }).waitFor();
    evidence.stages.push('price_edit_invalidates_current_funding_metrics', 'refresh_restores_review_state');

    const selected = await context.request.post(`${casePath}/decision`, { data: { property_id: candidateId, reason: '실제 확인을 더 진행할 선호 후보' } });
    assert.equal(selected.status(), 200);
    await page.reload();
    await candidate.getByText('선호 후보 · 확인 필요', { exact: true }).waitFor();
    await candidate.getByText('이 후보는 선택됐지만 필수 검토가 끝나지 않았습니다.', { exact: false }).waitFor();
    evidence.stages.push('user_selected_candidate_does_not_bypass_missing_reviews');

    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({ path: path.join(output, server ? 'assessment-browser-ci-mobile.png' : 'assessment-browser-mobile.png'), fullPage: true });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), '좁은 화면에서 페이지 전체가 가로로 넘치지 않음');
    assert.deepEqual(errors, []);
    evidence.stages.push('narrow_viewport_without_page_overflow', 'no_browser_runtime_errors');
    evidence.status = 'passed';
    console.log('PASS', evidence.stages.join(', '));
  } catch (error) {
    evidence.status = 'failed'; evidence.error = error.message.split('Call log:')[0];
    console.log(evidence.error); process.exitCode = 1;
    if (page) console.log((await page.locator('body').innerText()).slice(0, 1500));
  } finally {
    if (registered) {
      const cleanup = await context.request.delete('/api/auth/me');
      evidence.cleanup_status = cleanup.status();
      if (cleanup.status() !== 200) process.exitCode = 1;
    }
    evidence.finished_at = new Date().toISOString();
    fs.writeFileSync(path.join(output, server ? 'assessment-browser-ci-result.json' : 'assessment-browser-result.json'), JSON.stringify(evidence, null, 2));
    if (browser) await browser.close();
    if (server?.pid) {
      if (process.platform === 'win32') spawnSync('taskkill', ['/PID', String(server.pid), '/T', '/F'], { windowsHide: true, stdio: 'ignore' });
      else server.kill('SIGTERM');
    }
    if (log !== undefined) fs.closeSync(log);
  }
})();
