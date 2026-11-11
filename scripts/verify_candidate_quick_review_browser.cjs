// 후보 한 번에 검토: 실제 Spring·Kotlin 계산·작업 실행기로 조건 부족 미실행 → 자금 저장·시세추정 접수 → 새로고침 후 진행 조회 →
// 유효한 분석 재실행 방지 → 권리 안내 → 390px 표시를 확인한다. 실행 후 임시 계정을 삭제한다.
// 시세추정 결과의 가격 정확도는 검증하지 않는다(보류·오류도 화면이 진행 상태를 끝내고 이유를 보여주면 통과).
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
    log = fs.openSync(path.join(output, 'quick-review-next.log'), 'w');
    server = spawn(process.execPath, [path.join(root, 'web/node_modules/next/dist/bin/next'), 'dev', '--hostname', '127.0.0.1', '--port', String(port)], {
      cwd: path.join(root, 'web'), env: { ...process.env, NEXT_PUBLIC_API_URL: process.argv[2] }, stdio: ['ignore', log, log], windowsHide: true,
    });
  }
  const errors = [];
  let registered = false;
  const evidence = { status: 'running', stages: [], frontend_mode: server ? 'development' : 'running_service',
    boundaries: ['실제 자금 계산·저장과 시세추정 작업을 실행함. 시세 결과의 정확도·실호가·권리 판독은 검증하지 않음'],
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
      email: `quick-review-browser-${Date.now()}@example.com`, password: 'quick-review-browser-only-12345', name: '한 번에 검토 임시 계정',
    } });
    assert.equal(register.status(), 201); registered = true;
    const created = await context.request.post('/api/cases', { data: { title: '한 번에 검토 검증' } });
    assert.equal(created.status(), 201);
    const caseId = (await created.json()).id;
    const casePath = `/api/cases/${caseId}`;
    const name = '한 번에 검토 후보';
    const added = await context.request.post(`${casePath}/properties`, { data: {
      name, category: '아파트', asking_price: 900000000, address: '서울특별시 서초구 반포동 18-1', area_sqm: 84.9,
      identity: { area_basis: 'unknown' },
    } });
    assert.equal(added.status(), 201, await added.text());
    const candidateId = (await added.json()).id;
    const analyses = async () => {
      const value = await (await context.request.get(casePath)).json();
      return Object.fromEntries(value.properties.find(item => item.id === candidateId).analyses.map(item => [item.analysis_type, item]));
    };
    const section = () => page.getByRole('region', { name: `${name} 한 번에 검토` });
    // 시세추정 작업이 끝나면 화면이 같은 탭의 진행 기록을 지운다. 결과(연결·보류·오류)와 무관하게 진행 종료를 이 값으로 판단한다.
    const jobKey = `quickReviewJob:${caseId}:${candidateId}`;
    const appraisalIdle = () => page.waitForFunction(key => sessionStorage.getItem(key) === null, jobKey, { timeout: 360000 });

    // 1) 공통 조건이 없고 면적 기준이 미확인이면 계산도 작업도 만들지 않고 필요한 입력을 알려준다.
    await page.goto(`/cases/${caseId}`);
    await section().getByRole('button', { name: '한 번에 검토' }).click();
    await section().getByText(/계산하지 않았습니다\. 필요한 조건: .*보유 현금/).waitFor();
    await section().getByText(/시작하지 않았습니다\. 필요한 정보: 면적 기준/).waitFor();
    assert.ok(await section().getByRole('link', { name: '공통 매수 조건 입력' }).isVisible());
    assert.equal(await section().getByRole('link', { name: '시세추정 화면에서 입력' }).getAttribute('href'), `/appraisal?caseId=${caseId}&candidateId=${candidateId}`);
    assert.deepEqual(await analyses(), {}, '조건 부족 시 분석을 저장하지 않음');
    evidence.stages.push('missing_inputs_not_executed');

    // 2) 조건을 채우면 자금은 즉시 계산·저장되고 시세추정은 작업으로 접수된다.
    const profile = { cash_available: 700000000, emergency_reserve: 50000000, monthly_payment_limit: 3000000,
      annual_income: 120000000, existing_loan_annual_payment: 0, loan_ratio: 0.4,
      annual_interest_rate: 4.0, loan_years: 30, owned_homes: 1, adjusted_area: false };
    assert.equal((await context.request.patch(casePath, { data: { buyer_profile: profile } })).status(), 200);
    const identity = await context.request.patch(`${casePath}/properties/${candidateId}`, { data: { identity: { area_basis: 'exclusive' } } });
    assert.equal(identity.status(), 200, await identity.text());
    await page.reload();
    await section().getByRole('button', { name: '한 번에 검토' }).click();
    await section().getByText('공통 매수 조건으로 계산해 저장했습니다.').waitFor();
    await section().getByText(/필요 현금 [0-9,]+만원/).waitFor();
    const funding = (await analyses()).simulation;
    assert.ok(funding, '자금 분석 저장');
    assert.equal(funding.summary.purchase_price, 900000000);
    assert.equal(funding.summary.inputs.cash_available, 650000000, '비상자금은 한 번만 제외');
    evidence.stages.push('funding_saved_with_common_profile');

    // 3) 새로고침해도 같은 탭에서 진행 중인 시세추정을 다시 조회해 결과를 보여준다.
    assert.ok(await page.evaluate(key => sessionStorage.getItem(key), jobKey), '시세추정 작업 접수');
    await page.reload();
    await appraisalIdle();
    const appraisalRow = section().getByRole('listitem').filter({ hasText: /^시세/ });
    await appraisalRow.getByText(/시세추정을 마치고 후보에 연결했습니다|시세추정을 완료하지 못했습니다|오래 걸립니다|확인하지 못했습니다/).waitFor();
    const appraisalDone = await appraisalRow.getByText('시세추정을 마치고 후보에 연결했습니다', { exact: false }).count() > 0;
    evidence.appraisal_outcome = appraisalDone ? 'linked' : (await appraisalRow.innerText()).replace(/\s+/g, ' ').slice(0, 200);
    if (appraisalDone) {
      assert.ok((await analyses()).appraisal, '시세 분석이 후보에 연결됨');
      // 보류처럼 가격이 없는 결과도 분석 카드에 "미입력" 대신 결과 종류를 보여야 한다.
      const tile = await page.locator(`a[href="/appraisal?caseId=${caseId}&candidateId=${candidateId}"]`).filter({ hasText: '시세 분석' }).first().innerText();
      assert.ok(!tile.includes('미입력'), `시세 분석 카드 표시: ${tile}`);
      evidence.appraisal_tile = tile.replace(/\s+/g, ' ').trim();
    }
    assert.equal(await section().getByRole('button', { name: '한 번에 검토' }).isEnabled(), true);
    evidence.stages.push('refresh_resumes_appraisal_progress');

    // 4) 유효한 분석은 다시 실행하지 않는다. 시세 결과가 없으면(오류) 시세추정만 다시 접수된다.
    await section().getByRole('button', { name: '한 번에 검토' }).click();
    await section().getByText('유효한 자금 분석이 있어 그대로 두었습니다.', { exact: false }).waitFor();
    if (appraisalDone) await section().getByText('유효한 시세 분석이 있어 다시 실행하지 않았습니다.').waitFor();
    await appraisalIdle();
    evidence.stages.push('current_analyses_not_rerun');

    // 5) 권리 점검은 실행하지 않고 문서가 필요하다고 안내한다.
    await section().getByText('등기부등본 PDF를 올려야 점검할 수 있습니다.').waitFor();
    await section().getByRole('link', { name: '권리 점검으로 이동' }).click();
    await page.waitForURL('**/rights');
    const seeded = await page.evaluate(() => sessionStorage.getItem('rightsCandidate'));
    assert.equal(JSON.parse(seeded).candidate_id, candidateId);
    evidence.stages.push('rights_guidance_carries_candidate');

    // 6) 좁은 화면에서도 가로 넘침 없이 결과를 읽을 수 있다.
    await page.setViewportSize({ width: 390, height: 900 });
    await page.goto(`/cases/${caseId}`);
    await section().getByRole('button', { name: '한 번에 검토' }).click();
    await section().getByText('유효한 자금 분석이 있어 그대로 두었습니다.', { exact: false }).waitFor();
    await appraisalIdle();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    assert.ok(overflow <= 1, `가로 넘침 ${overflow}px`);
    await page.screenshot({ path: path.join(output, server ? 'quick-review-browser-ci.png' : 'quick-review-browser.png'), fullPage: true });
    evidence.stages.push('narrow_viewport_without_page_overflow');

    assert.deepEqual(errors, []);
    evidence.stages.push('no_browser_runtime_errors');
    evidence.status = 'passed';
    console.log('PASS', evidence.stages.join(', '), `(appraisal: ${evidence.appraisal_outcome})`);
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
    fs.writeFileSync(path.join(output, server ? 'quick-review-browser-ci-result.json' : 'quick-review-browser-result.json'), JSON.stringify(evidence, null, 2));
    if (browser) await browser.close();
    if (server?.pid) { if (process.platform === 'win32') spawnSync('taskkill', ['/PID', String(server.pid), '/T', '/F'], { windowsHide: true, stdio: 'ignore' }); else server.kill('SIGTERM'); }
    if (log !== undefined) fs.closeSync(log);
  }
})();
