// 금액 입력 해석·삭제 확인·분석 화면의 케이스 복귀·보관함 저장 불가 사유와 패널 위치를 실제 화면에서 확인한다.
// 임시 계정과 그 계정의 케이스·매물만 만들고 종료 시 계정을 삭제한다.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const net = require('node:net');
const {spawn, spawnSync} = require('node:child_process');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE_PATH || '../web/node_modules/playwright');

(async () => {
  const root=path.resolve(__dirname,'..'), output=path.join(root,'evaluation-results');
  fs.mkdirSync(output,{recursive:true});
  const report={status:'running',checks:[],boundaries:['임시 계정의 케이스·후보·가상 매물','실제 저장·화면 이동','AVM·권리 분석 실행 결과는 다루지 않음']};
  const check=title=>{report.checks.push(title);console.log(`PASS ${title}`);};
  let server,log,browser,context,page,registered=false;
  try {
    let baseURL=process.env.E2E_BASE_URL || (process.argv[2] ? undefined : 'http://localhost:3002');
    if(!baseURL){
      assert.ok(process.argv[2]?.startsWith('http://'),'격리 API 주소 또는 E2E_BASE_URL이 필요합니다');
      const port=await new Promise(resolve=>{const s=net.createServer();s.listen(0,'127.0.0.1',()=>{const p=s.address().port;s.close(()=>resolve(p));});});
      baseURL=`http://127.0.0.1:${port}`;log=fs.openSync(path.join(output,'ux-safeguards-next.log'),'w');
      server=spawn(process.execPath,[path.join(root,'web/node_modules/next/dist/bin/next'),'dev','--webpack','--hostname','127.0.0.1','--port',String(port)],{cwd:path.join(root,'web'),env:{...process.env,NEXT_PUBLIC_API_URL:process.argv[2],NEXT_TELEMETRY_DISABLED:'1'},stdio:['ignore',log,log],windowsHide:true});
    }
    browser=await chromium.launch(process.env.E2E_BROWSER==='chromium'?{headless:true}:{channel:'chrome',headless:true});
    context=await browser.newContext({baseURL,viewport:{width:1440,height:1000}});
    for(let i=0;i<60;i++){if((await context.request.get('/api/auth/me').catch(()=>null))?.status()===401)break;await new Promise(resolve=>setTimeout(resolve,1000));}
    const registration=await context.request.post('/api/auth/register',{data:{email:`ux-${Date.now()}@example.com`,password:'ux-safeguards-12345!',name:'화면 안전장치 임시 계정'}});
    assert.equal(registration.status(),201);registered=true;
    page=await context.newPage();page.setDefaultTimeout(45000);const errors=[];page.on('pageerror',error=>errors.push(error.message));

    // 1) 케이스 예산: 해석 미리보기와 단위 경고, 저장 값
    await page.goto('/cases');await page.getByRole('button',{name:'새 케이스'}).click();
    await page.getByPlaceholder('예: 서초구 실거주 매수').fill('화면 안전장치 검증 케이스');
    const budget=page.getByLabel('최대 예산',{exact:true});
    await budget.fill('90000');await page.getByText('= 9만원 · 부동산 금액으로는 작습니다',{exact:false}).waitFor();
    await budget.fill('9억');await page.getByText('= 9억원',{exact:true}).waitFor();
    await page.getByRole('button',{name:'생성',exact:true}).click();await page.waitForURL(/\/cases\/\d+/);
    const caseId=Number(new URL(page.url()).pathname.split('/')[2]);
    assert.equal((await(await context.request.get(`/api/cases/${caseId}`)).json()).budget_max,900000000);
    check('금액 입력: 숫자만 입력하면 원으로 해석해 단위 경고, "9억" 저장 값 9억원');

    // 2) 후보 추가 금액
    await page.getByRole('button',{name:'후보 추가'}).click();
    await page.getByPlaceholder('후보명 또는 건물명').fill('안전장치 검증 후보');await page.getByPlaceholder('주소',{exact:true}).fill('서울특별시 강남구 역삼동 123');
    await page.getByLabel('매도 희망가',{exact:true}).fill('8억 5000만');await page.getByText('= 8억 5,000만원',{exact:true}).waitFor();
    await page.getByPlaceholder('면적(㎡)').fill('84');await page.getByLabel('후보 물건 종류').selectOption('아파트');
    await page.getByRole('button',{name:'후보 저장'}).click();await page.getByRole('heading',{name:'안전장치 검증 후보'}).waitFor();
    const candidate=(await(await context.request.get(`/api/cases/${caseId}`)).json()).properties[0];
    assert.equal(candidate.asking_price,850000000);check('후보 희망가 "8억 5000만" → 850,000,000원 저장');

    // 2-1) 케이스 화면 배치: 진행 안내 하나 → 후보 목록 → 공통 매수 조건 순서
    const order=await page.evaluate(()=>['[aria-label="매수 검토 진행 안내"]','#candidates','#buyer-profile'].map(selector=>document.querySelector(selector)?.getBoundingClientRect().top??-1));
    assert.ok(order.every(value=>value>=0)&&order[0]<order[1]&&order[1]<order[2],`배치 순서 ${order}`);
    assert.equal(await page.getByRole('navigation',{name:'매수 검토 단계'}).count(),0);
    const guide=page.getByRole('region',{name:'매수 검토 진행 안내'});
    await guide.getByRole('heading',{name:'다음 단계: 매수 조건 입력'}).waitFor();
    assert.equal(await guide.getByRole('link',{name:/이어서 하기/}).getAttribute('href'),`/cases/${caseId}#buyer-profile`);
    await page.getByText('공통 매수 조건',{exact:true}).waitFor();
    await page.getByText(/예산 9억원 · 보유 현금 미입력/).waitFor();
    await page.screenshot({path:path.join(output,'ux-safeguards-case.png'),fullPage:true});
    check('케이스 화면: 진행 안내 하나와 이어서 하기, 후보 목록이 공통 조건보다 위, 조건 요약 표시');

    // 3) 삭제는 확인 단계를 거치고 취소하면 유지
    const card=page.locator(`#candidate-${candidate.id}`);
    await card.getByRole('button',{name:'후보 삭제'}).click();const confirm=card.getByRole('group',{name:'후보 삭제 확인'});await confirm.waitFor();
    await confirm.getByRole('button',{name:'취소'}).click();await card.getByRole('heading',{name:'안전장치 검증 후보'}).waitFor();
    assert.equal((await(await context.request.get(`/api/cases/${caseId}`)).json()).properties.length,1);check('후보 삭제: 확인 단계 표시, 취소 시 삭제하지 않음');

    // 3-1) 공통 매수 조건 금액 칸도 같은 해석을 쓴다
    await page.getByLabel('보유 현금',{exact:true}).fill('3억 5000만');await page.getByText('= 3억 5,000만원',{exact:true}).waitFor();
    await page.getByLabel('월 상환 한도',{exact:true}).fill('200만');
    await page.getByRole('button',{name:'매수 조건 저장',exact:true}).click();await page.getByRole('status').filter({hasText:'매수 조건을 저장했습니다'}).waitFor();
    const savedProfile=(await(await context.request.get(`/api/cases/${caseId}`)).json()).buyer_profile;
    assert.equal(savedProfile.cash_available,350000000);assert.equal(savedProfile.monthly_payment_limit,2000000);
    check('공통 매수 조건: "3억 5000만"·"200만"을 원으로 저장');

    // 4) 자금 분석 화면의 케이스 배너와 후보 복귀
    await card.getByRole('link',{name:/자금 분석/}).click();await page.waitForURL(/\/simulation/);
    const banner=page.getByRole('region',{name:'분석 중인 케이스 후보'});
    await banner.getByText('화면 안전장치 검증 케이스 · 안전장치 검증 후보',{exact:true}).waitFor();
    await banner.getByText('후보에 저장된 자금 분석이 아직 없습니다.',{exact:true}).waitFor();
    await page.getByText('= 8억 5,000만원',{exact:true}).first().waitFor();
    await banner.getByRole('link',{name:'후보로 돌아가기'}).click();await page.waitForURL(new RegExp(`/cases/${caseId}(#[^#]*)?#candidate-${candidate.id}$`));
    await page.locator(`#candidate-${candidate.id}`).waitFor();
    await page.waitForFunction(id=>{const box=document.getElementById(id)?.getBoundingClientRect();return Boolean(box&&box.top>=0&&box.top<innerHeight/2);},`candidate-${candidate.id}`);
    check('자금 분석: 케이스·후보·저장 상태 배너, 후보 카드로 복귀');

    // 4-1) 후보 비교표: 묶음 제목·값이 다른 항목만 보기·미확인 흐림
    const second=await context.request.post(`/api/cases/${caseId}/properties`,{data:{name:'비교용 두 번째 후보',address:'서울특별시 강남구 역삼동 125',asking_price:900000000,area_sqm:84,category:'아파트',source:'manual'}});
    assert.ok(second.ok(),await second.text());
    await page.goto(`/cases/${caseId}/comparison`);const table=page.getByRole('region',{name:'후보 비교표'});
    for(const title of ['물건·가격','자금','권리·검토 상태'])await table.getByText(title,{exact:true}).waitFor();
    await table.getByRole('rowheader',{name:'적용 금리',exact:true}).waitFor();
    const unknownCell=table.getByRole('row').filter({has:page.getByRole('rowheader',{name:'적용 금리',exact:true})}).getByRole('cell').first();
    assert.match(await unknownCell.getAttribute('class'),/text-slate-400/);
    await table.getByLabel('후보 간 값이 다른 항목만 보기').check();
    await table.getByRole('rowheader',{name:'희망가',exact:true}).waitFor();
    assert.equal(await table.getByRole('rowheader',{name:'적용 금리',exact:true}).count(),0);
    await page.screenshot({path:path.join(output,'ux-safeguards-comparison.png'),fullPage:true});
    check('후보 비교표: 묶음 제목, 값이 다른 항목만 보기, 미확인 값 흐림');
    await page.goto(`/cases/${caseId}`);
    const secondId=(await second.json()).id;
    await page.locator(`#candidate-${secondId}`).getByRole('button',{name:'후보 삭제'}).click();
    await page.locator(`#candidate-${secondId}`).getByRole('group',{name:'후보 삭제 확인'}).getByRole('button',{name:'삭제',exact:true}).click();
    await page.locator(`#candidate-${secondId}`).waitFor({state:'detached'});

    // 5) 확인 후 실제 삭제
    await page.locator(`#candidate-${candidate.id}`).getByRole('button',{name:'후보 삭제'}).click();
    await page.getByRole('group',{name:'후보 삭제 확인'}).getByRole('button',{name:'삭제',exact:true}).click();
    await page.getByText('검토할 부동산을 후보로 추가해보세요.',{exact:true}).waitFor();
    assert.equal((await(await context.request.get(`/api/cases/${caseId}`)).json()).properties.length,0);check('후보 삭제: 확인 후 삭제 반영');

    // 5-1) 홈: 진행 중 케이스와 다음 단계, 사이드바 접힘 그룹과 계정 관리
    await page.goto('/');const activeCases=page.getByRole('region',{name:'진행 중인 매수 검토'});
    const caseCard=activeCases.getByRole('article').filter({hasText:'화면 안전장치 검증 케이스'});
    await caseCard.getByText('다음 단계:',{exact:false}).waitFor();
    assert.equal(await caseCard.getByRole('link',{name:/이어서 하기/}).getAttribute('href'),`/cases/${caseId}#buyer-profile`);
    await page.screenshot({path:path.join(output,'ux-safeguards-home.png'),fullPage:true});
    const sidebar=page.locator('aside');
    assert.equal(await sidebar.getByRole('link',{name:'샘플 매물 비교',exact:true}).isVisible(),false);
    assert.equal(await sidebar.getByRole('button',{name:'회원 탈퇴'}).isVisible(),false);
    await sidebar.locator('summary',{hasText:'샘플 도구'}).click();await sidebar.getByRole('link',{name:'샘플 매물 비교',exact:true}).waitFor();
    await page.getByLabel('단지명 또는 주소',{exact:true}).fill('검증단지');await page.getByRole('button',{name:'매물로 등록',exact:true}).click();
    await page.waitForURL(url=>url.pathname==='/listings'&&url.searchParams.get('name')==='검증단지');
    check('홈: 진행 중 케이스의 다음 단계, 샘플 도구·회원 탈퇴는 접힘, 검색은 매물 등록으로 연결');

    // 6) 권리점검의 복합 단위 금액(이전에는 "3억5천만"을 잘못 환산)
    await page.goto('/rights');await page.getByLabel('시세',{exact:true}).fill('3억5천만');await page.getByText('= 3억 5,000만원',{exact:true}).waitFor();
    await page.getByLabel('시세',{exact:true}).fill('1.5억');await page.getByText('= 1억 5,000만원',{exact:true}).waitFor();
    check('권리점검: "3억5천만"·"1.5억"을 공통 규칙으로 해석');

    // 7) 보관함: 저장 불가 사유와 카드 안 패널
    const confirmed=new Date().toISOString();
    const csv='external_id,name,property_type,transaction_type,address,legal_region_code,area_sqm,asking_price,confirmed_at,status\n'+
      `ux-active,안전장치 거래 가능 매물,apartment,purchase,서울특별시 강남구 역삼동 123,1168010100,84,700000000,${confirmed},active\n`+
      `ux-withdrawn,안전장치 철회 매물,apartment,purchase,서울특별시 강남구 역삼동 124,1168010100,84,710000000,${confirmed},withdrawn\n`;
    const imported=await context.request.post('/api/listings/import',{data:{source_name:'화면 검증용 가상 출처',csv_text:csv,commit:true}});
    assert.equal(imported.status(),200,await imported.text());
    await page.goto('/listings');
    const withdrawn=page.locator('article').filter({hasText:'안전장치 철회 매물'});const active=page.locator('article').filter({hasText:'안전장치 거래 가능 매물'});
    await withdrawn.getByText("후보 저장 불가: 거래 상태가 '철회'라 저장할 수 없습니다.",{exact:false}).waitFor();
    assert.equal(await withdrawn.getByRole('button',{name:'매수 후보 저장'}).isDisabled(),true);
    assert.equal(await active.getByText('후보 저장 불가',{exact:false}).count(),0);
    await active.getByRole('button',{name:'타임라인'}).click();await active.getByRole('region',{name:'매물 타임라인'}).waitFor();
    await active.getByRole('button',{name:'변경 이력'}).click();await active.getByRole('heading',{name:'최근 변경 이력 (최대 100건)'}).waitFor();
    check('보관함: 저장 불가 사유 표시, 타임라인·변경 이력을 누른 카드 안에 표시');

    // 7-1) 다시 확인해 저장: 상태·가격만 새 이력으로 저장하고 저장 불가 사유가 풀린다
    await withdrawn.getByRole('button',{name:'다시 확인해 저장'}).click();
    const confirmForm=withdrawn.getByRole('form',{name:'안전장치 철회 매물 다시 확인'});
    await confirmForm.getByLabel('거래 상태',{exact:true}).selectOption('active');
    await confirmForm.getByLabel('확인한 희망가',{exact:true}).fill('7억 500만');await confirmForm.getByText('= 7억 500만원',{exact:true}).waitFor();
    await confirmForm.getByRole('button',{name:'확인 내용 저장'}).click();
    await page.getByRole('status').filter({hasText:'안전장치 철회 매물의 확인 내용을 저장했습니다'}).waitFor();
    assert.equal(await withdrawn.getByText('후보 저장 불가',{exact:false}).count(),0);
    assert.equal(await withdrawn.getByRole('button',{name:'매수 후보 저장'}).isDisabled(),false);
    const reconfirmed=(await(await context.request.get('/api/listings')).json()).items.find(item=>item.external_id==='ux-withdrawn');
    assert.equal(reconfirmed.status,'active');assert.equal(reconfirmed.asking_price,705000000);assert.equal(reconfirmed.address,'서울특별시 강남구 역삼동 124');
    assert.equal((await(await context.request.get(`/api/listings/${reconfirmed.id}/history`)).json()).items.length,2);
    check('보관함: 다시 확인해 저장 → 상태·가격만 새 이력으로 저장, 저장 불가 사유 해제');

    await page.screenshot({path:path.join(output,'ux-safeguards-browser.png'),fullPage:true});
    await page.setViewportSize({width:390,height:844});await page.goto(`/cases/${caseId}`);await page.getByRole('heading',{name:'화면 안전장치 검증 케이스'}).waitFor();
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    await page.goto('/listings');await page.locator('article').first().waitFor();
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    assert.deepEqual(errors,[]);check('좁은 화면 가로 넘침 없음·화면 오류 없음');
    report.status='passed';
  }catch(error){report.status='failed';report.error=error.message;if(page)await page.screenshot({path:path.join(output,'ux-safeguards-browser-failure.png'),fullPage:true}).catch(()=>{});throw error;}
  finally{try{if(registered)assert.equal((await context.request.delete('/api/auth/me')).status(),200);}finally{report.finished_at=new Date().toISOString();fs.writeFileSync(path.join(output,'ux-safeguards-browser.json'),JSON.stringify(report,null,2));if(browser)await browser.close();if(server?.pid){if(process.platform==='win32')spawnSync('taskkill',['/PID',String(server.pid),'/T','/F'],{windowsHide:true,stdio:'ignore'});else server.kill('SIGTERM');}if(log!==undefined)fs.closeSync(log);}}
})().catch(error=>{console.error(error.message);process.exitCode=1;});
