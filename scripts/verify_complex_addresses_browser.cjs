// 실제 주소 표시·지도 링크와 확인 대기 처리만 검증한다. 임시 계정은 종료 시 삭제한다.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('../frontend/node_modules/playwright');

(async () => {
  const output = path.resolve(__dirname, '../evaluation-results');
  fs.mkdirSync(output, {recursive:true});
  const report = {status:'running', checks:[], boundaries:[
    '실제 API 응답의 단지 대표 주소·지도 검색 링크 표시를 대조함',
    '미확인 주소 처리 두 시나리오는 브라우저 응답을 대체한 회귀 검증',
    '개별 매물 재고·호가·동호수의 정확도는 검증하지 않음'
  ]};
  const check = name => {report.checks.push(name);console.log(`PASS ${name}`);};
  let browser, context, page, registered=false;
  try {
    browser=await chromium.launch({channel:'chrome', headless:true});
    context=await browser.newContext({baseURL:process.env.E2E_BASE_URL||'http://127.0.0.1:3002',viewport:{width:1440,height:1000}});
    const register=await context.request.post('/api/auth/register',{data:{email:`address-check-${Date.now()}@example.com`,password:'address-browser-check-123!',name:'주소 표시 검증'}});
    assert.equal(register.status(),201);registered=true;
    page=await context.newPage();page.setDefaultTimeout(60000);
    const errors=[];page.on('pageerror',error=>errors.push(error.message));
    const selectDong = async name => {
      await page.getByLabel('읍·면·동 (법정동)',{exact:true}).locator('option').filter({hasText:name}).waitFor({state:'attached'});
      const code=await page.getByLabel('읍·면·동 (법정동)',{exact:true}).locator('option').filter({hasText:name}).getAttribute('value');
      await page.getByLabel('읍·면·동 (법정동)',{exact:true}).selectOption(code);
    };
    await page.goto('/explore');
    await page.getByLabel('시·군·구',{exact:true}).locator('option[value="1135000000"]').waitFor({state:'attached'});
    await page.getByLabel('시·군·구',{exact:true}).selectOption('1135000000');
    let responsePromise=page.waitForResponse(response=>response.url().includes('/api/recommendation/complexes')&&response.status()===200);
    await selectDong('중계동');
    const response=await responsePromise;
    assert.equal(response.request().postDataJSON().require_complete_address,true);
    const data=await response.json();assert.ok(data.results.length>0);
    await page.getByRole('article').first().waitFor();
    assert.equal(await page.getByRole('article').count(),data.results.length);
    for(const item of data.results){
      assert.ok(item.road_address && item.jibun_address && item.address_status==='matched');
      const card=page.getByRole('article',{name:`${item.complex_name} 후보 저장`,exact:true});
      await card.getByText(`도로명: ${item.road_address}`,{exact:true}).waitFor();
      await card.getByText(`지번: ${item.jibun_address}`,{exact:true}).waitFor();
      for(const [label,address] of [['도로명',item.road_address],['지번',item.jibun_address]]){
        const href=await card.getByRole('link',{name:`${label}주소로 네이버 지도 검색 (새 탭)`,exact:true}).getAttribute('href');
        assert.equal(decodeURIComponent(href),`https://map.naver.com/p/search/${address}`);
      }
    }
    report.real_candidates=data.results.map(item=>({name:item.complex_name,road_address:item.road_address,jibun_address:item.jibun_address}));
    check('실제 동별 추천 후보 전부에 두 주소 표시·정확한 주소로 지도 링크 연결');
    await page.screenshot({path:path.join(output,'complex-address-desktop.png'),fullPage:true});
    await page.setViewportSize({width:390,height:844});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    await page.screenshot({path:path.join(output,'complex-address-mobile.png'),fullPage:true});
    check('모바일 주소 줄바꿈·가로 넘침 없음');

    const created=await context.request.post('/api/cases',{data:{title:'주소 검증 케이스'}});
    assert.equal(created.status(),201);const target=await created.json();
    await page.goto(`/explore?case_id=${target.id}`);
    await page.getByLabel('시·군·구',{exact:true}).locator('option[value="1135000000"]').waitFor({state:'attached'});
    await page.getByLabel('시·군·구',{exact:true}).selectOption('1135000000');
    responsePromise=page.waitForResponse(response=>response.url().includes(`/api/cases/${target.id}/recommendations?`)&&response.status()===200);
    await selectDong('상계동');
    const linkedResponse=await responsePromise;
    assert.equal(new URL(linkedResponse.url()).searchParams.get('require_complete_address'),'true');
    const linked=await linkedResponse.json();assert.ok(linked.results.length>0);
    assert.ok(linked.results.every(item=>item.road_address&&item.jibun_address&&item.address_status==='matched'));
    await page.getByRole('article').first().waitFor();
    check('케이스를 연결한 탐색도 동일한 주소 확인 기준 적용');

    await page.goto('/explore');
    await page.getByLabel('시·군·구',{exact:true}).locator('option[value="1135000000"]').waitFor({state:'attached'});
    await page.getByLabel('시·군·구',{exact:true}).selectOption('1135000000');
    let mockedResults=[data.results[0],{...data.results[0],complex_name:'주소미확인검증단지',road_address:''}];
    const pending=[{complex_name:'주소미확인검증단지',dong:'상계동',address_status:'unresolved',reason:'도로명 주소 확인 대기'}];
    await page.route('**/api/recommendation/complexes',route=>route.fulfill({json:{...data,results:mockedResults,address_pending:pending,address_policy:'verified_only'}}));
    await selectDong('상계동');
    await page.getByRole('article',{name:`${data.results[0].complex_name} 후보 저장`,exact:true}).waitFor();
    assert.equal(await page.getByRole('article').count(),1);
    await page.getByText('주소 확인 대기 1개 단지 · 후보에서 제외',{exact:true}).click();
    await page.getByText('도로명 주소 확인 대기',{exact:true}).waitFor();
    assert.equal(await page.getByRole('article',{name:'주소미확인검증단지 후보 저장'}).count(),0);
    check('일부 주소 누락 후보는 카드에서 제외·확인 대기 사유 표시');
    mockedResults=[];
    await selectDong('중계동');
    await page.getByText('지번·도로명 주소를 모두 확인한 단지 후보가 아직 없습니다. 주소 확인 대기 사유를 확인하거나 지역 범위를 넓혀보세요.',{exact:true}).waitFor();
    assert.equal(await page.getByRole('article').count(),0);
    check('모든 주소 미확인 시 빈 결과·대기 사유 안내');
    assert.deepEqual(errors,[]);
    report.status='passed';
  } catch(error){report.status='failed';report.error=error.message;if(page)await page.screenshot({path:path.join(output,'complex-address-browser-failure.png'),fullPage:true}).catch(()=>{});throw error;}
  finally {
    try{if(registered)assert.equal((await context.request.delete('/api/auth/me')).status(),200);}
    finally{report.checked_at=new Date().toISOString();fs.writeFileSync(path.join(output,'complex-address-browser.json'),JSON.stringify(report,null,2));if(browser)await browser.close();}
  }
})().catch(error=>{console.error(error.message);process.exitCode=1;});
