// 격리 Spring·실제 작업 실행기로 임대료 계산, 필지 조회, 이력 복원, 비교 제외를 확인한다.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const net = require('node:net');
const { spawn, spawnSync } = require('node:child_process');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || '../web/node_modules/playwright');

(async () => {
  const root = path.resolve(__dirname, '..'), output = path.join(root, 'evaluation-results');
  const report = { status: 'running', checks: [], boundaries: ['공공 API 응답은 격리 공급자 대역', '실제 Kotlin 계산·Python 작업·저장·웹·복원', '시장가격 정확도 평가는 아님'] };
  const check = label => { report.checks.push(label); console.log(`PASS ${label}`); };
  let server, log, browser, context, page, registered = false;
  try {
    assert.ok(process.argv[2]?.startsWith('http://'), 'scripts/run_spring_tests.py --browser로 격리 API를 지정해주세요');
    const port = await new Promise(resolve => { const s = net.createServer(); s.listen(0, '127.0.0.1', () => { const p = s.address().port; s.close(() => resolve(p)); }); });
    log = fs.openSync(path.join(output, 'valuation-support-next.log'), 'w');
    server = spawn(process.execPath, [path.join(root, 'web/node_modules/next/dist/bin/next'), 'dev', '--webpack', '--hostname', '127.0.0.1', '--port', String(port)], {
      cwd: path.join(root, 'web'), env: { ...process.env, NEXT_PUBLIC_API_URL: process.argv[2], NEXT_TELEMETRY_DISABLED: '1' }, stdio: ['ignore', log, log], windowsHide: true,
    });
    browser = await chromium.launch(process.env.E2E_BROWSER === 'chromium' ? { headless: true } : { channel: 'chrome', headless: true });
    context = await browser.newContext({ baseURL: `http://127.0.0.1:${port}`, viewport: { width: 1440, height: 1000 } });
    for (let i = 0; i < 60; i++) { if ((await context.request.get('/api/auth/me').catch(() => null))?.status() === 401) break; await new Promise(resolve => setTimeout(resolve, 1000)); }
    const register = await context.request.post('/api/auth/register', { data: { email: `valuation-${Date.now()}@example.com`, password: 'valuation-check-12345!', name: '유형별 검토 임시 계정' } });
    assert.equal(register.status(), 201); registered = true;
    const created = await context.request.post('/api/cases', { data: { title: '수익 시나리오 검증' } });
    assert.equal(created.status(), 201); const caseId = (await created.json()).id;
    assert.equal((await context.request.post(`/api/cases/${caseId}/properties`, { data: { name: '입력 임대료 검증 상가', address: '서울 중구 태평로1가 31', category: '상가', area_sqm: 100, asking_price: 2000000000 } })).status(), 201);
    const candidateId = (await (await context.request.get(`/api/cases/${caseId}`)).json()).properties[0].id;
    page = await context.newPage(); page.setDefaultTimeout(45000);
    const errors = []; page.on('pageerror', error => errors.push(error.message));
    await page.goto(`/appraisal?caseId=${caseId}&candidateId=${candidateId}`);
    await page.getByLabel('평가 범위', { exact: true }).selectOption('whole_building');
    await page.getByLabel('현재 받는 월세 합계(원)', { exact: true }).fill('10000000');
    await page.getByLabel('월 소유자 운영비 최소(원)', { exact: true }).fill('1000000');
    await page.getByLabel('월 소유자 운영비 최대(원)', { exact: true }).fill('2000000');
    await page.getByLabel('가정 환원율 최소(%)', { exact: true }).fill('4');
    await page.getByLabel('가정 환원율 최대(%)', { exact: true }).fill('6');
    await page.getByRole('button', { name: '수익·가격 범위 계산', exact: true }).click();
    await page.waitForURL(/\/report\/\d+$/, { timeout: 60000 });
    await page.getByText('조건부 가격 범위: 1,600,000,000원 ~ 2,700,000,000원', { exact: true }).waitFor();
    await page.getByText('4.8% ~ 5.4%', { exact: true }).waitFor();
    check('실제 입력 → Kotlin 가격·수익률 범위 → 작업 결과 이력 연결');
    await page.reload(); await page.getByText('조건부 가격 범위: 1,600,000,000원 ~ 2,700,000,000원', { exact: true }).waitFor();
    const summary = await (await context.request.get(`/api/cases/${caseId}/summary`)).json();
    const price = summary.decision.candidates.find(c => c.property_id === candidateId).axes.find(a => a.key === 'price');
    assert.equal(price.status, 'unknown');
    const candidate = (await (await context.request.get(`/api/cases/${caseId}`)).json()).properties[0];
    assert.equal(candidate.appraisal.valuation.result_kind, 'conditional_scenario');
    assert.equal(candidate.appraisal.valuation.comparison_eligible, false);
    assert.equal(candidate.appraisal.valuation.subject.scope, 'whole_building');
    await page.getByRole('heading', { name: '평가 결과 · 조건부 시나리오', exact: true }).waitFor();
    assert.equal(candidate.appraisal.estimated_value, null);
    assert.equal(candidate.checklist.find(c => c.category === 'price').status, 'todo');
    check('새로고침 복원·조건부 결과의 확정 시세 비교 및 완료 표시 차단');
    await page.screenshot({ path: path.join(output, 'valuation-support-browser-income.png'), fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await page.screenshot({ path: path.join(output, 'valuation-support-browser-income-mobile.png'), fullPage: true });
    await page.setViewportSize({ width: 1440, height: 1000 });
    const pnu = '1114010300100310000', year = String(new Date().getFullYear());
    const fixture = { documents: [{ address_name: '서울 중구 태평로1가 31', x: '126.978', y: '37.566',
      address: { address_name: '서울 중구 태평로1가 31', b_code: '1114010300', main_address_no: '31', sub_address_no: '', mountain_yn: 'N' },
      road_address: { address_name: '서울 중구 세종대로 110' } }],
      land_records: {
        ladfrlList: [{ pnu, lndpclAr: '100.5', lndcgrCodeNm: '대', lastUpdtDt: `${year}-01-01` }],
        getLandCharacteristics: [{ pnu, stdrYear: year, stdrMt: '01', lndpclAr: '100', ladUseSittnNm: '상업용', tpgrphHgCodeNm: '평지', tpgrphFrmCodeNm: '정방형', roadSideCodeNm: '소로한면', prposArea1Nm: '일반상업지역', prposArea2Nm: '지정되지않음' }],
        getIndvdLandPriceAttr: [{ pnu, stdrYear: year, stdrMt: '01', pblntfPclnd: '12345' }],
        getLandUseAttr: [{ pnu, prposAreaDstrcCodeNm: '일반상업지역', cnflcAtNm: '포함', lastUpdtDt: `${year}-01-01` }],
      } };
    fixture.places = fixture.documents;
    const provider = process.env.PROVIDER_TEST_URL || 'http://127.0.0.1:8016';
    assert.equal((await context.request.post(`${provider}/configure`, { data: fixture })).status(), 200);
    await page.goto('/appraisal'); await page.getByRole('button', { name: /^토지/ }).click();
    await page.getByPlaceholder('예: 래미안원베일리, 서초구 반포동...').fill('서울 중구 태평로1가 31');
    await page.getByRole('button', { name: '검색', exact: true }).click();
    await page.locator('li').filter({ hasText: '서울 중구 태평로1가 31' }).first().click();
    await page.getByText('필지 공개정보 · 조회됨', { exact: true }).waitFor();
    await page.getByText('100.5㎡', { exact: true }).waitFor(); await page.getByText('1,234,500원', { exact: true }).waitFor();
    check('주소 선택 → PNU 대조 → 토지대장·특성·공시지가·이용계획 자동 조회');
    await page.getByRole('button', { name: '토지 공개정보 결과 저장', exact: true }).click();
    await page.waitForURL(/\/report\/\d+$/, { timeout: 60000 });
    await page.reload(); await page.getByText('필지 공개정보 · 조회됨', { exact: true }).waitFor();
    await page.getByText(pnu, { exact: true }).waitFor();
    check('토지 결과·출처·기준연도 저장 및 새로고침 복원');
    await page.getByRole('heading', { name: '평가 결과 · 공개자료 참고', exact: true }).waitFor();
    await page.screenshot({ path: path.join(output, 'valuation-support-browser-land.png'), fullPage: true });
    const failed = await context.request.post(`${provider}/configure`, { data: { ...fixture, land_error: 'EXPIRE_KEY' } }); assert.equal(failed.status(), 200);
    const unavailable = await context.request.post('/api/address/land', { data: { address: '서울 중구 태평로1가 31' } });
    const data = await unavailable.json(); assert.equal(data.status, 'unavailable'); assert.equal(data.fields.official_price_won_per_sqm, null);
    check('만료 키 응답에서 공시지가를 0원·조회 성공으로 표시하지 않음');
    const added = await context.request.post(`/api/cases/${caseId}/properties`, { data: { name: '면적 미확인 아파트', address: '서울 중구 태평로1가 31', category: '아파트', area_sqm: 84, asking_price: 800000000 } });
    assert.equal(added.status(), 201); const apartmentId = (await added.json()).id;
    await page.goto(`/appraisal?caseId=${caseId}&candidateId=${apartmentId}`);
    await page.getByRole('button', { name: '시세추정 시작', exact: true }).click();
    await page.waitForURL(/\/report\/\d+$/, { timeout: 60000 });
    await page.getByRole('heading', { name: '평가 결과 · 추정 보류', exact: true }).waitFor();
    await page.reload(); await page.getByRole('heading', { name: '평가 결과 · 추정 보류', exact: true }).waitFor();
    const apartment = (await (await context.request.get(`/api/cases/${caseId}`)).json()).properties.find(p => p.id === apartmentId);
    assert.equal(apartment.appraisal.valuation.subject.area_basis, 'unknown');
    assert.equal(apartment.appraisal.estimated_value, null);
    assert.equal(apartment.checklist.find(c => c.category === 'price').status, 'todo');
    check('아파트 면적 기준 미확인 → 가격 보류·다음 확인 항목·이력 복원');
    const changed = await context.request.patch(`/api/cases/${caseId}/properties/${candidateId}`, { data: { identity: { unit_number: '502', area_basis: 'exclusive' } } });
    assert.equal(changed.status(), 200);
    const revised = (await (await context.request.get(`/api/cases/${caseId}`)).json()).properties.find(p => p.id === candidateId);
    assert.equal(revised.analyses.find(a => a.analysis_type === 'appraisal').status, 'stale');
    assert.equal(revised.appraisal.valuation.subject.ho, '');
    assert.equal(revised.identity.unit_number, '502');
    check('후보 호실 변경 → 재검토 전환·기존 평가 대상과 기준 보존');
    assert.deepEqual(errors, []); report.status = 'passed';
  } catch (error) {
    report.status = 'failed'; report.error = error.message;
    if (page) await page.screenshot({ path: path.join(output, 'valuation-support-browser-failure.png'), fullPage: true }).catch(() => {});
    throw error;
  } finally {
    try { if (registered) assert.equal((await context.request.delete('/api/auth/me')).status(), 200); }
    finally {
      report.finished_at = new Date().toISOString(); fs.writeFileSync(path.join(output, 'valuation-support-browser.json'), JSON.stringify(report, null, 2));
      if (browser) await browser.close();
      if (server?.pid) { if (process.platform === 'win32') spawnSync('taskkill', ['/PID', String(server.pid), '/T', '/F'], { windowsHide: true, stdio: 'ignore' }); else server.kill('SIGTERM'); }
      if (log !== undefined) fs.closeSync(log);
    }
  }
})().catch(error => { console.error(error.message); process.exitCode = 1; });
