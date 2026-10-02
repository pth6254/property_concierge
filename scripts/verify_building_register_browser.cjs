// 외부 공급자만 격리 대역을 사용하고 주소 서명·조회·등록·후보·복원은 실제 Spring으로 검증한다.
const fs = require('node:fs');
const path = require('node:path');
const net = require('node:net');
const assert = require('node:assert/strict');
const { spawn, spawnSync } = require('node:child_process');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || '../web/node_modules/playwright');

(async () => {
  const root = path.resolve(__dirname, '..');
  const output = path.join(root, 'evaluation-results'); fs.mkdirSync(output, { recursive: true });
  const report = { status: 'running', checks: [], boundaries: ['건축HUB·카카오 응답은 격리 공급자 대역', 'Spring 서명·조회·실제 저장·후보·복원 검증', '전국 데이터 정확도는 별도 검증'] };
  let browser, context, registered = false, next, log;
  const checked = text => { report.checks.push(text); process.stdout.write(text + '\n'); };
  try {
    const api = process.argv[2];
    assert.equal(new URL(api).port, '8013', '격리 Spring 8013에서만 실행할 수 있습니다');
    const port = await new Promise(resolve => { const server = net.createServer(); server.listen(0, '127.0.0.1', () => { const port = server.address().port; server.close(() => resolve(port)); }); });
    const baseURL = `http://127.0.0.1:${port}`;
    log = fs.openSync(path.join(output, 'building-register-next.log'), 'w');
    next = spawn(process.execPath, [path.join(root, 'web/node_modules/next/dist/bin/next'), 'dev', '--webpack', '--hostname', '127.0.0.1', '--port', String(port)], {
      cwd: path.join(root, 'web'), env: { ...process.env, NEXT_PUBLIC_API_URL: api }, stdio: ['ignore', log, log], windowsHide: true,
    });
    browser = await chromium.launch(process.env.E2E_BROWSER === 'chromium' ? { headless: true } : { channel: 'chrome', headless: true });
    context = await browser.newContext({ baseURL, viewport: { width: 1440, height: 1000 } });
    for (let count = 0; count < 60; count++) { const response = await context.request.get('/api/auth/me').catch(() => null); if (response?.status() === 401) break; await new Promise(resolve => setTimeout(resolve, 1000)); }
    const record = values => ({ sigunguCd: '11680', bjdongCd: '10100', bun: '0123', ji: '0000', platGbCd: '0', ...values });
    const title = (id, dong) => record({ mgmBldrgstPk: id, bldNm: '건축물 조회 검증 단지', dongNm: dong, mainAtchGbCd: '0', mainPurpsCdNm: '아파트', strctCdNm: '철근콘크리트구조', totArea: '12000', useAprDay: '19991125', grndFlrCnt: '15', rideUseElvtCnt: '2' });
    const configuration = {
      documents: [{ x: '127.04', y: '37.5', address: { address_name: '서울 강남구 역삼동 123', b_code: '1168010100', main_address_no: '123', sub_address_no: '', mountain_yn: 'N' }, road_address: { address_name: '서울 강남구 테헤란로 123', building_name: '건축물 조회 검증 단지' } }],
      register_records: {
        getBrTitleInfo: [record({ mgmBldrgstPk: 'guard', dongNm: '경비실', mainAtchGbCd: '1', totArea: '5.5' }), title('building-main', '101동'), title('building-other', '102동')],
        getBrRecapTitleInfo: [record({ mgmBldrgstPk: 'complex', hhldCnt: '500', totPkngCnt: '600', totArea: '60000' })],
        getBrFlrOulnInfo: [record({ mgmBldrgstPk: 'building-main', dongNm: '101동', flrNoNm: '5층', area: '1000', mainPurpsCdNm: '아파트' })],
        getBrExposPubuseAreaInfo: [record({ mgmBldrgstPk: 'unit-main', dongNm: '101동', hoNm: '501호', exposPubuseGbCd: '1', area: '84.9', flrNo: '5', flrNoNm: '5층', mainPurpsCdNm: '아파트' }), record({ mgmBldrgstPk: 'unit-main', dongNm: '101동', hoNm: '501호', exposPubuseGbCd: '2', area: '35.5', flrNoNm: '각층' })],
      },
    };
    assert.equal((await context.request.post('http://127.0.0.1:8016/configure', { data: configuration })).status(), 200);
    const registration = await context.request.post('/api/auth/register', { data: { email: `building-browser-${Date.now()}@example.com`, password: 'building-browser-12345!', name: '건축물 검증' } });
    assert.equal(registration.status(), 201, await registration.text()); registered = true;
    const page = await context.newPage(); page.setDefaultTimeout(30000);
    const errors = []; page.on('pageerror', error => errors.push(error.message));
    const openForm = async () => { await page.goto('/listings'); await page.getByRole('link', { name: '매물 등록', exact: true }).click(); };
    const selectAddress = async () => {
      await page.getByLabel('주소·단지명 검색', { exact: true }).fill('테헤란로 123');
      await page.getByRole('button', { name: '주소 검색', exact: true }).click();
      await page.getByRole('button', { name: /건축물 조회 검증 단지.*도로명/ }).click();
    };
    const confirmed = new Date(Date.now() - 3600000); confirmed.setMinutes(confirmed.getMinutes() - confirmed.getTimezoneOffset());
    const completeForm = async () => {
      await page.getByLabel('확인한 호가 (원)', { exact: true }).fill('700000000');
      await page.getByLabel('정보 확인 일시 (현재 기기 시간대)', { exact: true }).fill(confirmed.toISOString().slice(0, 16));
      await page.getByLabel('확인한 거래 상태', { exact: true }).selectOption('active');
    };
    await openForm(); await selectAddress();
    await page.getByLabel('조회할 건물 선택', { exact: true }).waitFor();
    await page.getByText('여러 건물이 있거나 동을 특정하지 못했습니다. 건물을 선택하면 상세 정보를 확인할 수 있습니다.', { exact: true }).waitFor();
    assert.equal(await page.getByLabel('건물 동 (선택)', { exact: true }).getAttribute('required'), null);
    assert.equal(await page.getByLabel('호수 (선택)', { exact: true }).getAttribute('required'), null);
    assert.equal(await page.getByLabel('확인한 면적 (㎡)', { exact: true }).inputValue(), '');
    checked('주소 선택 → 단지·건물 정보 구분, 여러 동과 첫 경비실 임의 선택 방지');
    await page.getByLabel('조회할 건물 선택', { exact: true }).selectOption('building-main');
    await page.locator('#register-listing').getByText('선택한 건물: 건축물 조회 검증 단지 101동', { exact: true }).waitFor();
    await page.getByLabel('확인한 면적 (㎡)', { exact: true }).fill('80');
    await page.getByLabel('호수 (선택)', { exact: true }).fill('501');
    await page.getByRole('button', { name: '건물·호실 정보 조회', exact: true }).click();
    await page.getByRole('button', { name: '조회 정보 적용', exact: true }).waitFor();
    assert.equal(await page.getByLabel('확인한 면적 (㎡)', { exact: true }).inputValue(), '80');
    await page.getByText('조회한 전유면적: 84.9 ㎡ · 현재 입력 면적 80 ㎡와 다릅니다.', { exact: true }).waitFor();
    await page.getByRole('button', { name: '조회 정보 적용', exact: true }).click();
    assert.equal(await page.getByLabel('확인한 면적 (㎡)', { exact: true }).inputValue(), '84.9');
    assert.equal(await page.getByLabel('면적 기준', { exact: true }).inputValue(), 'exclusive');
    assert.equal(await page.getByLabel('층 (선택)', { exact: true }).inputValue(), '5층');
    checked('정확한 동·호 전유면적 조회 → 차이 표시 → 사용자 적용, 공용면적 미합산');
    await page.getByLabel('별칭 (선택)', { exact: true }).fill('첫 임장'); await completeForm();
    await page.screenshot({ path: path.join(output, 'building-register-form.png'), fullPage: true });
    await page.getByRole('button', { name: '관심 매물 등록', exact: true }).click();
    const card = page.getByRole('article').filter({ has: page.getByRole('heading', { name: '건축물 조회 검증 단지', exact: true }) });
    await card.getByText('별칭: 첫 임장', { exact: true }).waitFor();
    let items = (await (await context.request.get('/api/listings')).json()).items;
    assert.equal(items.length, 1); const listing = items[0];
    assert.equal(listing.area_sqm, 84.9); assert.equal(listing.identity.area_basis, 'exclusive');
    assert.equal(listing.address_details.building_register.area_matches_input, true);
    assert.ok(!('building_token' in listing)); assert.ok(!('address_token' in listing));
    await card.getByRole('button', { name: '매수 후보 저장', exact: true }).click();
    await page.getByRole('link', { name: '케이스 보기', exact: true }).waitFor();
    const caseId = (await (await context.request.get('/api/cases')).json()).items[0].id;
    const candidate = (await (await context.request.get(`/api/cases/${caseId}`)).json()).properties[0];
    assert.deepEqual(candidate.address_details.building_register, listing.address_details.building_register);
    await page.goto('/listings'); await page.reload(); await page.getByText('저장한 건축물대장 정보', { exact: true }).click();
    await page.getByText('등록한 전용면적이 조회한 전유면적과 일치합니다.', { exact: true }).waitFor();
    checked('공식 근거·별칭 실제 저장, 후보 스냅샷 유지와 새로고침 복원');
    await openForm(); await page.getByLabel('부동산 유형', { exact: true }).selectOption('detached'); await selectAddress();
    await page.getByLabel('조회할 건물 선택', { exact: true }).waitFor();
    assert.equal(await page.getByLabel('건물 동 (선택)', { exact: true }).inputValue(), '');
    assert.equal(await page.getByLabel('호수 (선택)', { exact: true }).inputValue(), '');
    await page.getByLabel('확인한 면적 (㎡)', { exact: true }).fill('120'); await completeForm();
    await page.getByRole('button', { name: '관심 매물 등록', exact: true }).click();
    await page.getByText('내가 등록한 매물 · 총 2건', { exact: true }).waitFor();
    items = (await (await context.request.get('/api/listings')).json()).items;
    assert.ok(items.some(item => item.property_type === 'detached' && item.identity.building_dong === '' && item.identity.unit_number === ''));
    checked('단독·다가구는 동·호 생략과 면적 직접 입력으로 등록 가능');
    await openForm();
    await page.route('**/api/listings/address/building', route => route.fulfill({ status: 503, json: { detail: '건축물 조회 실패 검증' } }));
    await selectAddress(); await page.getByText('건축물 조회 실패 검증', { exact: true }).waitFor();
    await page.getByLabel('확인한 면적 (㎡)', { exact: true }).fill('59'); await completeForm();
    await page.getByRole('button', { name: '관심 매물 등록', exact: true }).click();
    await page.getByText('내가 등록한 매물 · 총 3건', { exact: true }).waitFor();
    checked('건축물대장 조회 실패 시 주소 선택·면적 직접 입력·등록 유지');
    await page.unroute('**/api/listings/address/building');
    await openForm(); await selectAddress(); await page.getByLabel('조회할 건물 선택', { exact: true }).selectOption('building-main');
    await page.locator('#register-listing').getByText('선택한 건물: 건축물 조회 검증 단지 101동', { exact: true }).waitFor();
    await page.getByLabel('호수 (선택)', { exact: true }).fill('501');
    const pending = page.waitForRequest('**/api/listings/address/building');
    await page.route('**/api/listings/address/building', async route => { const response = await route.fetch(); await new Promise(resolve => setTimeout(resolve, 700)); await route.fulfill({ response }); });
    await page.getByRole('button', { name: '건물·호실 정보 조회', exact: true }).click(); await pending;
    await page.getByLabel('호수 (선택)', { exact: true }).fill('502'); await new Promise(resolve => setTimeout(resolve, 1000));
    assert.equal(await page.locator('input[name="building_token"]').inputValue(), '');
    assert.equal(await page.getByRole('button', { name: '조회 정보 적용', exact: true }).count(), 0);
    checked('조회 중 호수 변경 → 늦게 도착한 이전 결과와 확인 서명 적용 차단');
    await page.setViewportSize({ width: 390, height: 844 });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false); assert.deepEqual(errors, []);
    await page.screenshot({ path: path.join(output, 'building-register-mobile.png'), fullPage: true });
    checked('390px 화면 가로 넘침·런타임 오류 없음'); report.status = 'passed';
  } catch (error) { report.status = 'failed'; report.error = error.stack || String(error); process.exitCode = 1; console.error(report.error); }
  finally {
    if (registered && context) { const removed = await context.request.delete('/api/auth/me'); report.cleanup_status = removed.status(); if (removed.status() !== 200) { report.status = 'failed'; process.exitCode = 1; } }
    fs.writeFileSync(path.join(output, 'building-register-browser.json'), JSON.stringify(report, null, 2));
    await browser?.close(); if (next) { if (process.platform === 'win32') spawnSync('taskkill', ['/PID', String(next.pid), '/T', '/F'], { stdio: 'ignore', windowsHide: true }); else next.kill('SIGTERM'); } if (log !== undefined) fs.closeSync(log);
  }
})();
