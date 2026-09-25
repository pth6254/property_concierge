// 시장 집계는 고정 입력, 매물·케이스 저장은 격리 API로 검증한다. 생성한 계정은 종료 시 삭제한다.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const net = require('node:net');
const { spawn, spawnSync } = require('node:child_process');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || '../frontend/node_modules/playwright');

(async () => {
  const backend = process.argv[2];
  assert.ok(backend?.startsWith('http://'));
  const root = path.resolve(__dirname, '..');
  const output = path.join(root, 'evaluation-results');
  fs.mkdirSync(output, {recursive:true});
  const report = {status:'running',checks:[],boundaries:['시장 집계·단지 추천은 고정 입력', '네이버 링크의 주소·새 탭 이동 설정 검증, 외부 검색 결과 품질은 제외']};
  const check = name => report.checks.push(name);
  const port = await new Promise(resolve => {const server=net.createServer();server.listen(0,'127.0.0.1',()=>{const value=server.address().port;server.close(()=>resolve(value));});});
  const log = fs.openSync(path.join(output,'navigation-next.log'),'w');
  const server = spawn(process.execPath,[path.join(root,'frontend/node_modules/next/dist/bin/next'),'dev','--hostname','127.0.0.1','--port',String(port)],{cwd:path.join(root,'frontend'),env:{...process.env,NEXT_PUBLIC_API_URL:backend},stdio:['ignore',log,log],windowsHide:true});
  let browser, context, registered=false;
  try {
    browser = await chromium.launch(process.env.E2E_BROWSER==='chromium'?{headless:true}:{channel:'chrome',headless:true});
    context = await browser.newContext({baseURL:`http://127.0.0.1:${port}`,viewport:{width:1440,height:1000}});
    for(let i=0;i<60;i++){try{if((await context.request.get('/api/auth/me')).status()===401)break;}catch{}await new Promise(r=>setTimeout(r,1000));}
    const registration=await context.request.post('/api/auth/register',{data:{email:`navigation-${Date.now()}@example.com`,password:'navigation-check-12345!',name:'화면 연결 검증'}});
    assert.equal(registration.status(),201);registered=true;
    const target=await(await context.request.post('/api/cases',{data:{title:'화면 연결 검증 케이스'}})).json();
    const page=await context.newPage();page.setDefaultTimeout(20000);
    const errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.route('**/api/market/regions/summary?*',route=>{
      const scope=new URL(route.request().url()).searchParams.get('region_code');
      const district=scope==='1100000000';
      return route.fulfill({json:{source:'검증용 고정 집계',price_unit:'만원',period:{from:'202509',to:'202608'},items:[{
        region_name:district?'서울특별시 강남구':'서울특별시 강남구 역삼동',region_code:district?'1168000000':'1168010100',lawd_code:'11680',
        deal_count:20,sample_size:20,avg_price:80000,median_price:80000,price_q1:70000,price_q3:90000,
        avg_per_sqm:1000,median_per_sqm:1000,asset_count:4,last_deal_ym:'202608',budget_fit_count:10,budget_fit_ratio:0.5,confidence:'medium'
      }]}});
    });
    await page.route('**/api/recommendation/complexes',route=>route.fulfill({json:{results:[{complex_name:'화면검증단지',dong:'역삼동',road_address:'서울특별시 강남구 테헤란로 123',jibun_address:'서울특별시 강남구 역삼동 123',address_status:'matched',address_source:'검증용 주소',avg_price:80000,avg_per_sqm:1000,avg_area_m2:77.3,deal_count:20,build_year:2000,last_deal_ym:'202608',score:80,reasons:['검증용 집계']}]}}));
    await page.goto('/explore');
    await page.getByLabel('검토할 케이스',{exact:true}).selectOption(String(target.id));
    await page.getByLabel('시·군·구',{exact:true}).selectOption('1168000000');
    await page.getByLabel('읍·면·동 (법정동)',{exact:true}).selectOption('1168010100');
    const card=page.getByRole('article',{name:'화면검증단지 후보 저장',exact:true});
    await card.waitFor();
    const external=card.getByRole('link',{name:/네이버 부동산에서 찾기/});
    const destination=new URL(await external.getAttribute('href'));
    assert.equal(destination.origin,'https://fin.land.naver.com');assert.equal(destination.pathname,'/search');
    assert.equal(destination.searchParams.get('q'),'서울특별시 강남구 테헤란로 123');
    assert.equal(decodeURIComponent(new URL(await card.getByRole('link',{name:'도로명주소로 네이버 지도 검색 (새 탭)',exact:true}).getAttribute('href')).pathname),'/p/search/서울특별시 강남구 테헤란로 123');
    assert.equal(decodeURIComponent(new URL(await card.getByRole('link',{name:'지번주소로 네이버 지도 검색 (새 탭)',exact:true}).getAttribute('href')).pathname),'/p/search/서울특별시 강남구 역삼동 123');
    assert.equal(await external.getAttribute('target'),'_blank');
    await context.grantPermissions(['clipboard-read','clipboard-write']);
    await card.getByRole('button',{name:'주소 복사',exact:true}).click();
    await card.getByRole('status').filter({hasText:'주소를 복사했습니다'}).waitFor();
    assert.equal(await page.evaluate(()=>navigator.clipboard.readText()),'서울특별시 강남구 테헤란로 123');
    await card.getByRole('button',{name:'매물 링크 없이 후보 직접 입력'}).click();
    assert.equal(await card.getByLabel('실제 검토 전용면적 (㎡)').inputValue(),'');
    await card.getByLabel('검토 주소',{exact:true}).fill('서울특별시 강남구 역삼동 123');
    assert.equal(new URL(await external.getAttribute('href')).searchParams.get('q'),'서울특별시 강남구 역삼동 123');
    await card.getByRole('button',{name:'주소 복사',exact:true}).click();
    assert.equal(await page.evaluate(()=>navigator.clipboard.readText()),'서울특별시 강남구 역삼동 123');
    await card.getByLabel('검토 주소',{exact:true}).fill('서울특별시 강남구 테헤란로 123');
    await card.getByRole('button',{name:'직접 입력 닫기'}).click();
    check('단지명을 덧붙이지 않고 주소를 네이버 검색에 전달하며 평균 면적을 실제 면적으로 채우지 않음');
    await page.evaluate(()=>window.scrollTo(0,0));await page.screenshot({path:path.join(output,'navigation-explore-desktop.png'),fullPage:true});
    await page.setViewportSize({width:390,height:844});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    await page.evaluate(()=>window.scrollTo(0,0));await page.screenshot({path:path.join(output,'navigation-explore-mobile.png'),fullPage:true});
    await card.getByRole('link',{name:'이 단지 매물 등록',exact:true}).click();
    await page.getByRole('heading',{name:'매물 보관함',exact:true}).waitFor();
    for(let i=0;i<2;i++){
      await page.getByLabel('저장할 케이스',{exact:true}).getByRole('option',{name:'화면 연결 검증 케이스',exact:true}).waitFor({state:'attached'});
      assert.equal(await page.getByLabel('매물 이름',{exact:true}).inputValue(),'화면검증단지');
      assert.equal(await page.getByLabel('확인한 주소',{exact:true}).inputValue(),'서울특별시 강남구 테헤란로 123');
      assert.equal(await page.getByLabel('확인한 면적 (㎡)').inputValue(),'');
      assert.equal(await page.getByLabel('저장할 케이스',{exact:true}).inputValue(),String(target.id));
      if(i===0) await page.reload();
    }
    check('탐색 → 등록에서 단지·주소·케이스 유지 및 새로고침 복원');
    assert.equal(await page.getByRole('link',{name:'찾은 매물 등록',exact:true}).count(),0);
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    await page.evaluate(()=>window.scrollTo(0,0));await page.screenshot({path:path.join(output,'navigation-register-mobile.png'),fullPage:true});
    await page.getByLabel('네이버 매물 링크').fill('https://fin.land.naver.com/articles/9990001234');
    await page.getByLabel('매물 이름',{exact:true}).fill('연결검증 가상 매물');
    await page.getByLabel('확인한 주소',{exact:true}).fill('서울특별시 강남구 역삼동 123');
    await page.getByLabel('확인한 면적 (㎡)').fill('84');
    await page.getByLabel('확인한 호가 (원)').fill('700000000');
    const local=new Date(Date.now()-3600000);local.setMinutes(local.getMinutes()-local.getTimezoneOffset());
    await page.getByLabel('원문 확인 일시 (현재 기기 시간대)').fill(local.toISOString().slice(0,16));
    await page.getByLabel('확인한 거래 상태').selectOption('active');
    await page.getByRole('button',{name:'관심 매물 등록',exact:true}).click();
    const item=page.getByRole('article').filter({has:page.getByRole('heading',{name:'연결검증 가상 매물',exact:true})});
    await item.waitFor();
    const savedResponse=page.waitForResponse(response=>response.url().includes('/candidate') && response.request().method()==='POST');
    await item.getByRole('button',{name:'매수 후보 저장',exact:true}).click();
    assert.ok([200,201].includes((await savedResponse).status()));
    await page.getByRole('link',{name:'케이스 보기',exact:true}).waitFor();
    const detail=await(await context.request.get(`/api/cases/${target.id}`)).json();
    assert.equal(detail.properties.length,1);assert.equal(detail.properties[0].area_sqm,84);assert.equal(detail.properties[0].asking_price,700000000);
    check('직접 확인한 값으로 매물 등록 후 지정한 케이스에 후보 저장');
    const listingId=detail.properties[0].source_listing_id;
    const original=await context.request.get(`/api/listings/${listingId}`);assert.equal(original.status(),200);
    const row=await original.json();
    const keys=['external_id','name','property_type','transaction_type','address','legal_region_code','area_sqm','asking_price','source_url','confirmed_at','status'];
    row.asking_price=750000000;row.confirmed_at=new Date().toISOString();
    const csv=keys.join(',')+'\n'+keys.map(key=>'"'+String(row[key]).replaceAll('"','""')+'"').join(',')+'\n';
    const updated=await context.request.post('/api/listings/import',{data:{source_name:row.source_name,csv_text:csv,commit:true}});
    assert.equal(updated.status(),200);assert.equal((await updated.json()).updated,1);
    await page.goto(`/cases/${target.id}`);
    await page.getByRole('link',{name:'보관함에서 이 매물 확인',exact:true}).click();
    await page.waitForURL(url=>url.pathname==='/listings' && url.searchParams.get('listing_id')===String(listingId));
    assert.equal(new URL(page.url()).searchParams.get('listing_id'),String(listingId));
    await page.getByRole('heading',{name:'케이스에 연결된 원본 매물 · 총 1건'}).waitFor();
    assert.equal(await page.getByLabel('저장할 케이스',{exact:true}).inputValue(),String(target.id));
    check('원본 매물 딥링크가 해당 매물만 표시하고 케이스 유지');
    await page.setViewportSize({width:1440,height:1000});await page.evaluate(()=>window.scrollTo(0,0));await page.screenshot({path:path.join(output,'navigation-listings-desktop.png'),fullPage:true});
    await page.getByRole('navigation',{name:'매수 검토 단계'}).getByRole('link',{name:'1. 동네 탐색',exact:true}).click();
    await page.getByLabel('검토할 케이스',{exact:true}).getByRole('option',{name:'화면 연결 검증 케이스',exact:true}).waitFor({state:'attached'});
    assert.equal(await page.getByLabel('검토할 케이스',{exact:true}).inputValue(),String(target.id));
    check('단계 안내를 통해 탐색으로 돌아가도 선택한 케이스 유지');
    await page.goto(`/cases/${target.id}/summary`);
    await page.getByRole('heading',{name:'매수 검토 요약',exact:true}).waitFor();
    const checklist=page.getByRole('link',{name:'검토 항목 보기',exact:true}).first();
    assert.ok((await checklist.getAttribute('href')).startsWith(`/cases/${target.id}#candidate-checklist-`));
    await checklist.click();
    await page.waitForURL(url=>url.pathname===`/cases/${target.id}` && url.hash.startsWith('#candidate-checklist-'));
    check('검토 요약에서 실제 후보 체크리스트로 이동');
    await page.goto('/');
    assert.equal(await page.locator('main').getByRole('link').filter({hasText:'동네 탐색'}).first().getAttribute('href'),'/explore');
    assert.equal(await page.locator('main').getByRole('link').filter({hasText:'후보 검토·비교'}).first().getAttribute('href'),'/cases');
    await page.setViewportSize({width:390,height:844});
    await page.getByRole('button',{name:'메뉴 열기'}).click();
    await page.getByRole('link',{name:'매물 보관함',exact:true}).filter({visible:true}).click();
    await page.getByRole('heading',{name:'매물 보관함',exact:true}).waitFor();
    assert.equal(await page.getByRole('button',{name:'메뉴 닫기'}).count(),0);
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    check('홈의 주요 링크·모바일 메뉴 이동·가로 넘침 없음');
    assert.deepEqual(errors,[]);report.status='passed';console.log(`PASS navigation: ${report.checks.length} checks`);
  } catch(error) {report.status='failed';report.error=error.message;throw error;}
  finally {
    fs.writeFileSync(path.join(output,'navigation-browser.json'),JSON.stringify(report,null,2));
    try {if(registered)assert.equal((await context.request.delete('/api/auth/me')).status(),200);}
    finally {if(browser)await browser.close();if(server.pid){if(process.platform==='win32')spawnSync('taskkill',['/PID',String(server.pid),'/T','/F'],{windowsHide:true,stdio:'ignore'});else server.kill('SIGTERM');}fs.closeSync(log);}
  }
})().catch(error=>{console.error(error.message);process.exitCode=1;});
