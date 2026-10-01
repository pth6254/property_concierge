// 실제 서비스 또는 격리 API에서 조건 전달·자금 표시·의견 저장을 검증한다. 임시 계정만 생성·삭제한다.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const net = require('node:net');
const {spawn, spawnSync} = require('node:child_process');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE_PATH || '../web/node_modules/playwright');

(async () => {
  const root = path.resolve(__dirname, '..');
  const output = path.join(root, 'evaluation-results');
  fs.mkdirSync(output, {recursive:true});
  const report = {status:'running',started_at:new Date().toISOString(),checks:[],boundaries:[
    '시장·자금 계산은 연결된 API 응답을 사용하며 모킹하지 않음',
    '직접 저장한 후보는 검증용 가상 매물이며 실호가 검증이 아님',
    '법령 검색·AVM 정확도·관리자 화면은 별도 평가'
  ]};
  const check = name => {report.checks.push(name);console.log(`PASS ${name}`);};
  let server, log, browser, context, registered=false, page;
  let baseURL = process.env.E2E_BASE_URL;
  if (!baseURL) {
    const backend = process.argv[2];
    assert.ok(backend?.startsWith('http://'), '격리 API 주소 또는 E2E_BASE_URL을 지정하세요');
    const port = await new Promise(resolve=>{const s=net.createServer();s.listen(0,'127.0.0.1',()=>{const p=s.address().port;s.close(()=>resolve(p));});});
    baseURL = `http://127.0.0.1:${port}`;
    log = fs.openSync(path.join(output,'service-quality-next.log'),'w');
    server = spawn(process.execPath,[path.join(root,'web/node_modules/next/dist/bin/next'),'dev','--hostname','127.0.0.1','--port',String(port)],{
      cwd:path.join(root,'web'),env:{...process.env,NEXT_PUBLIC_API_URL:backend},stdio:['ignore',log,log],windowsHide:true});
  }
  try {
    browser = await chromium.launch(process.env.E2E_BROWSER==='chromium'?{headless:true}:{channel:'chrome',headless:true});
    context = await browser.newContext({baseURL,viewport:{width:1440,height:1000}});
    for(let i=0;i<60;i++){
      try{if((await context.request.get('/api/auth/me')).status()===401)break;}catch{}
      await new Promise(resolve=>setTimeout(resolve,1000));
    }
    const reg = await context.request.post('/api/auth/register',{data:{email:`quality-${Date.now()}@example.com`,password:'quality-check-12345!',name:'서비스 품질 검증'}});
    assert.equal(reg.status(),201);registered=true;
    const profile={cash_available:2000000000,emergency_reserve:10000000,monthly_payment_limit:20000000,annual_income:500000000,
      loan_ratio:.5,annual_interest_rate:4,loan_years:30,owned_homes:1,adjusted_area:false,
      min_area_sqm:50,max_area_sqm:100,min_build_year:1980,max_build_year:2030,market_months:12,priority:'cash'};
    const created=await context.request.post('/api/cases',{data:{title:'서비스 품질 검증 케이스',budget_max:5000000000,buyer_profile:profile}});
    assert.equal(created.status(),201);
    const target=await created.json();
    page=await context.newPage();page.setDefaultTimeout(90000);
    const errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.goto(`/cases/${target.id}`);
    await page.getByRole('region',{name:'매수 검토 진행 안내'}).waitFor();
    await page.getByText('공통 매수 조건',{exact:true}).click();
    await page.locator('input[name="max_area_sqm"]').fill('90');
    // 동일 초에 만들어진 케이스만 검사하면 갱신 후 폼 재생성 문제를 놓칠 수 있다.
    await new Promise(resolve=>setTimeout(resolve,1100));
    await page.getByRole('button',{name:'매수 조건 저장',exact:true}).click();
    await page.getByRole('status').filter({hasText:'매수 조건을 저장했습니다'}).waitFor();
    assert.equal((await(await context.request.get(`/api/cases/${target.id}`)).json()).buyer_profile.max_area_sqm,90);
    check('매수 조건 입력·저장과 진행 단계 안내');

    const initialResponse=page.waitForResponse(r=>r.url().includes('/api/market/regions/summary?')&&r.status()===200);
    await page.goto(`/explore?case_id=${target.id}`);
    const initial=await initialResponse;
    const query=new URL(initial.url()).searchParams;
    for(const [key,value] of Object.entries({area_min_sqm:'50',area_max_sqm:'90',min_build_year:'1980',max_build_year:'2030',months:'12',budget_max:'500000'}))assert.equal(query.get(key),value);
    assert.equal(await page.getByLabel('최대 면적',{exact:true}).inputValue(),'90');
    assert.equal(await page.getByLabel('최대 면적',{exact:true}).getAttribute('readonly'),'');
    check('케이스 예산·면적·연식·기간을 동네 집계에 일관되게 전달');
    await page.getByLabel('시·군·구',{exact:true}).selectOption('1168000000');
    const recommendationResponse=page.waitForResponse(r=>r.url().includes(`/api/cases/${target.id}/recommendations?`)&&r.status()===200);
    await page.getByLabel('읍·면·동 (법정동)',{exact:true}).selectOption('1168010100');
    const response=await recommendationResponse;
    const recommendations=await response.json();
    assert.ok(recommendations.results.length>0, recommendations.error||'조건에 맞는 거래가 없습니다');
    report.funding_previews=recommendations.results.map(item=>({name:item.complex_name,status:item.funding_preview?.status,missing:item.funding_preview?.missing}));
    assert.ok(recommendations.results.every(item=>item.funding_preview?.status==='calculated'),JSON.stringify(report.funding_previews));
    const item=recommendations.results[0];
    assert.equal(item.funding_preview.status,'calculated');
    const card=page.getByRole('article',{name:`${item.complex_name} 후보 저장`,exact:true});
    await card.getByText('내 자금 기준 참고 계산',{exact:true}).waitFor();
    await card.getByText(`예상 필요 현금 ${item.funding_preview.summary.required_cash.toLocaleString()}원 · 월 상환액 ${item.funding_preview.summary.monthly_payment.toLocaleString()}원`,{exact:true}).waitFor();
    check('실제 계산기의 필요 현금·월 상환액을 단지 카드에 표시');
    await card.getByRole('button',{name:'매물 링크 없이 후보 직접 입력'}).click();
    assert.equal(await card.getByLabel('확인한 희망가 (만원, 선택)').inputValue(),'');
    await card.getByLabel('검토 주소',{exact:true}).fill('서울특별시 강남구 역삼동 123');
    await card.getByLabel('실제 검토 전용면적 (㎡)').fill('84');
    await card.getByLabel('확인한 희망가 (만원, 선택)').fill('80000');
    await card.getByRole('button',{name:'케이스에 후보 저장',exact:true}).click();
    await card.getByRole('button',{name:'이 케이스에 후보 저장됨'}).waitFor();
    const detail=await(await context.request.get(`/api/cases/${target.id}`)).json();
    assert.equal(detail.properties.length,1);assert.equal(detail.properties[0].asking_price,800000000);
    assert.equal(detail.buyer_profile.max_area_sqm,90);
    assert.equal(detail.regions[0].stats_snapshot.comparison_criteria.area_max_sqm,90);
    check('평균 실거래가를 호가에 자동 입력하지 않고 확인한 후보만 저장');

    await page.getByText('사용 중 문제·개선 의견 보내기',{exact:true}).click();
    await page.getByLabel('의견 종류',{exact:true}).selectOption('suggestion');
    const message='브라우저 검증용 의견: 비교 조건과 자금 안내를 확인했습니다.';
    await page.getByLabel('문제 상황',{exact:true}).fill(message);
    await page.getByRole('button',{name:'의견 보내기',exact:true}).click();
    await page.getByRole('status').filter({hasText:'의견을 접수했습니다'}).waitFor();
    const feedback=await(await context.request.get('/api/feedback')).json();
    assert.equal(feedback.items[0].message,message);assert.equal(feedback.items[0].feature,'explore');
    assert.equal((await context.request.get('/api/operations/metrics')).status(),403);
    check('사용자 의견 실제 DB 저장과 일반 사용자 운영 API 접근 제한');
    await page.evaluate(()=>window.scrollTo(0,0));
    await page.screenshot({path:path.join(output,'service-quality-desktop.png'),fullPage:true});
    await page.setViewportSize({width:390,height:844});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    await page.screenshot({path:path.join(output,'service-quality-mobile.png'),fullPage:true});
    check('데스크톱·모바일 표시와 가로 넘침 없음');
    await page.goto(`/cases/${target.id}`);await page.reload();
    await page.getByRole('region',{name:'매수 검토 진행 안내'}).waitFor();
    await page.getByText(item.complex_name,{exact:true}).first().waitFor();
    assert.equal((await(await context.request.get(`/api/cases/${target.id}`)).json()).buyer_profile.max_area_sqm,90);
    assert.deepEqual(errors,[]);
    check('새로고침 후 저장한 조건·후보 복원과 브라우저 실행 오류 없음');
    report.status='passed';
  }catch(error){report.status='failed';report.error=error.message;if(page)await page.screenshot({path:path.join(output,'service-quality-failure.png'),fullPage:true}).catch(()=>{});throw error;}
  finally{
    try{if(registered)assert.equal((await context.request.delete('/api/auth/me')).status(),200);}
    finally{
      report.finished_at=new Date().toISOString();fs.writeFileSync(path.join(output,'service-quality-browser.json'),JSON.stringify(report,null,2));
      if(browser)await browser.close();
      if(server?.pid){if(process.platform==='win32')spawnSync('taskkill',['/PID',String(server.pid),'/T','/F'],{windowsHide:true,stdio:'ignore'});else server.kill('SIGTERM');}
      if(log!==undefined)fs.closeSync(log);
    }
  }
})().catch(error=>{console.error(error.message);process.exitCode=1;});
