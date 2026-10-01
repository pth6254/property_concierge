// 주소 응답은 가상 입력이며 저장·후보 연결·복원은 실제 API를 사용한다.
const fs = require('node:fs');
const path = require('node:path');
const net = require('node:net');
const assert = require('node:assert/strict');
const { spawn, spawnSync } = require('node:child_process');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || '../frontend/node_modules/playwright');

(async () => {
  const root = path.resolve(__dirname, '..');
  const output = path.join(root, 'evaluation-results'); fs.mkdirSync(output, {recursive:true});
  const report = {status:'running', checks:[], boundaries:['주소 검색은 서명된 가상 응답', '실제 저장·후보·새로고침·별칭 선택 입력', '실제 주소 API 품질은 별도 확인']};
  let browser, context, registered=false, next, log;
  let baseURL = process.env.E2E_BASE_URL || 'http://localhost:3002';
  const checked = title => {report.checks.push(title);process.stdout.write(title+'\n');};
  try {
    if (process.argv[2] && !process.env.E2E_BASE_URL) {
      const port = await new Promise(resolve => {const server=net.createServer();server.listen(0,'127.0.0.1',()=>{const port=server.address().port;server.close(()=>resolve(port));});});
      baseURL=`http://127.0.0.1:${port}`;
      log=fs.openSync(path.join(output,'address-next.log'),'w');
      next=spawn(process.execPath,[path.join(root,'frontend/node_modules/next/dist/bin/next'),'dev','--webpack','--hostname','127.0.0.1','--port',String(port)],{cwd:path.join(root,'frontend'),env:{...process.env,NEXT_PUBLIC_API_URL:process.argv[2]},stdio:['ignore',log,log],windowsHide:true});
    }
    browser=await chromium.launch(process.env.E2E_BROWSER==='chromium'?{headless:true}:{channel:'chrome',headless:true});
    context=await browser.newContext({baseURL,viewport:{width:1440,height:1000}});
    for(let i=0;i<60;i++){const response=await context.request.get('/api/auth/me').catch(()=>null);if(response?.status()===401)break;await new Promise(resolve=>setTimeout(resolve,1000));}
    const registration=await context.request.post('/api/auth/register',{data:{email:`address-browser-${Date.now()}@example.com`,password:'address-browser-12345!',name:'주소 등록 검증'}});
    assert.equal(registration.status(),201,await registration.text());registered=true;
    const owner=await(await context.request.get('/api/auth/me')).json();
    const helper='scripts/listing_address_browser_fixture.py';
    const fixture=process.platform==='win32'
      ? spawnSync('wsl',['--cd',root.replaceAll('\\','/').replace(/^([A-Za-z]):/,(_,drive)=>'/mnt/'+drive.toLowerCase()),'./venv-wsl/bin/python',helper,String(owner.id)],{encoding:'utf8',windowsHide:true})
      : spawnSync(process.env.E2E_PYTHON || 'python',[helper,String(owner.id)],{cwd:root,encoding:'utf8'});
    assert.equal(fixture.status,0,fixture.stderr);const choices=JSON.parse(fixture.stdout);
    const page=await context.newPage();page.setDefaultTimeout(30000);const errors=[];page.on('pageerror',error=>errors.push(error.message));
    await page.route('**/api/listings/address/search?*',route=>route.fulfill({json:choices}));
    await page.goto('/listings');await page.getByRole('link',{name:'매물 등록',exact:true}).click();
    assert.equal(await page.getByLabel('별칭 (선택)',{exact:true}).getAttribute('required'),null);
    await page.getByLabel('주소·단지명 검색',{exact:true}).fill('테헤란로 123');
    await page.getByRole('button',{name:'주소 검색',exact:true}).click();
    await page.getByRole('button',{name:/주소 등록 검증 단지.*도로명/}).click();
    assert.equal(await page.getByLabel('매물 이름',{exact:true}).inputValue(),'주소 등록 검증 단지');
    assert.equal(await page.getByLabel('매물 이름',{exact:true}).getAttribute('readonly'),'');
    await page.getByLabel('선택한 주소 확인 정보').getByText(/지번: 서울 강남구 역삼동 123/).waitFor();
    checked('주소 선택 → 조회 이름·도로명·지번 자동 채움');
    const alias='출퇴근 후보, "첫 임장"';
    await page.getByLabel('별칭 (선택)',{exact:true}).fill(alias);
    await page.getByLabel('확인한 면적 (㎡)',{exact:true}).fill('84');
    await page.getByLabel('확인한 호가 (원)',{exact:true}).fill('700000000');
    const confirmed=new Date(Date.now()-3600000);confirmed.setMinutes(confirmed.getMinutes()-confirmed.getTimezoneOffset());
    await page.getByLabel('정보 확인 일시 (현재 기기 시간대)',{exact:true}).fill(confirmed.toISOString().slice(0,16));
    await page.getByLabel('확인한 거래 상태',{exact:true}).selectOption('active');
    await page.screenshot({path:path.join(output,'address-browser-form.png'),fullPage:true});
    await page.getByRole('button',{name:'관심 매물 등록',exact:true}).click();
    const card=page.getByRole('article').filter({has:page.getByRole('heading',{name:'주소 등록 검증 단지',exact:true})});
    await card.getByText(`별칭: ${alias}`,{exact:true}).waitFor();
    let items=(await(await context.request.get('/api/listings')).json()).items;
    assert.equal(items.length,1);assert.equal(items[0].alias,alias);assert.equal(items[0].name,'주소 등록 검증 단지');
    assert.equal(items[0].address_details.road_address,'서울특별시 강남구 테헤란로 123');assert.ok(!('address_token' in items[0]));
    checked('쉼표·따옴표 별칭을 조회 이름과 분리해 실제 DB 저장');
    await card.getByRole('button',{name:'매수 후보 저장',exact:true}).click();await page.getByRole('link',{name:'케이스 보기',exact:true}).waitFor();
    const cases=(await(await context.request.get('/api/cases')).json()).items;
    const caseId=cases[0].id;const candidate=(await(await context.request.get(`/api/cases/${caseId}`)).json()).properties[0];
    assert.equal(candidate.alias,alias);assert.equal(candidate.name,'주소 등록 검증 단지');assert.equal(candidate.address_details.legal_region_code,'1168010100');
    await page.goto(`/cases/${caseId}`);await page.getByText(`별칭: ${alias}`,{exact:true}).waitFor();await page.reload();await page.getByText(`별칭: ${alias}`,{exact:true}).waitFor();
    await page.goto(`/cases/${caseId}/summary`);await page.getByText(`별칭: ${alias}`,{exact:true}).waitFor();
    checked('후보와 매수 검토 요약에서 주소·이름·별칭 유지 및 새로고침 복원');
    await page.screenshot({path:path.join(output,'address-browser-desktop.png'),fullPage:true});
    await page.goto('/listings');await page.getByRole('link',{name:'매물 등록',exact:true}).click();
    await page.getByLabel('주소·단지명 검색',{exact:true}).fill('테헤란로 123');await page.getByRole('button',{name:'주소 검색',exact:true}).click();await page.getByRole('button',{name:/주소 등록 검증 단지.*도로명/}).click();
    await page.getByLabel('확인한 면적 (㎡)',{exact:true}).fill('59');await page.getByLabel('확인한 호가 (원)',{exact:true}).fill('600000000');
    await page.getByLabel('정보 확인 일시 (현재 기기 시간대)',{exact:true}).fill(confirmed.toISOString().slice(0,16));await page.getByLabel('확인한 거래 상태',{exact:true}).selectOption('active');
    await page.getByRole('button',{name:'관심 매물 등록',exact:true}).click();await page.getByText('내가 등록한 매물 · 총 2건',{exact:true}).waitFor();
    items=(await(await context.request.get('/api/listings')).json()).items;assert.equal(items.length,2);assert.equal(items.find(item=>item.area_sqm===59).alias,'');
    checked('별칭 생략 가능·같은 주소의 서로 다른 매물을 임의 병합하지 않음');
    await page.getByLabel('주소·단지명 검색',{exact:true}).fill('다른 주소');
    await page.getByRole('button',{name:'관심 매물 등록',exact:true}).click();
    await page.getByText('주소 검색 결과를 선택하거나 주소·이름 직접 입력으로 전환해주세요.',{exact:true}).waitFor();
    assert.equal((await(await context.request.get('/api/listings')).json()).total,2);
    checked('검색어 변경 후 이전 주소 확인 정보를 사용해 저장하지 않음');
    await page.unroute('**/api/listings/address/search?*');
    await page.route('**/api/listings/address/search?*',route=>route.fulfill({status:502,json:{detail:'검증용 주소 검색 실패'}}));
    await page.getByRole('button',{name:'주소 검색',exact:true}).click();await page.getByText('검증용 주소 검색 실패',{exact:true}).waitFor();
    await page.getByRole('button',{name:'주소·이름 직접 입력으로 전환',exact:true}).click();
    await page.getByLabel('매물 이름',{exact:true}).fill('직접 입력 검증 물건');await page.getByLabel('확인한 주소',{exact:true}).fill('서울특별시 강남구 역삼동 123');
    await page.getByRole('button',{name:'관심 매물 등록',exact:true}).click();await page.getByRole('heading',{name:'직접 입력 검증 물건',exact:true}).waitFor();
    const manual=(await(await context.request.get('/api/listings')).json()).items.find(item=>item.name==='직접 입력 검증 물건');
    assert.equal(manual.address_details,null);checked('주소 검색 실패 → 직접 입력으로 저장하고 조회 미확인 유지');
    await page.setViewportSize({width:390,height:844});await page.reload();await page.getByRole('heading',{name:'매물 보관함',exact:true}).waitFor();
    await page.getByRole('link',{name:'매물 등록',exact:true}).click();await page.getByLabel('별칭 (선택)',{exact:true}).waitFor();
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);assert.deepEqual(errors,[]);
    await page.screenshot({path:path.join(output,'address-browser-mobile.png'),fullPage:true});checked('390px 웹 화면 가로 넘침·런타임 오류 없음');
    report.status='passed';
  } catch(error){report.status='failed';report.error=error.stack||String(error);process.exitCode=1;console.error(report.error);}
  finally {
    if(registered&&context){const removed=await context.request.delete('/api/auth/me');report.cleanup_status=removed.status();if(removed.status()!==200){report.status='failed';process.exitCode=1;}}
    fs.writeFileSync(path.join(output,'address-browser-result.json'),JSON.stringify(report,null,2));
    await browser?.close();if(next){if(process.platform==='win32')spawnSync('taskkill',['/PID',String(next.pid),'/T','/F'],{stdio:'ignore',windowsHide:true});else next.kill('SIGTERM');}if(log!==undefined)fs.closeSync(log);
  }
})();
