// 격리 API 주소를 인자로 받고 임시 Next 서버에서 CSV 수입 흐름을 검증한다.
const assert=require('node:assert/strict');const path=require('node:path');const fs=require('node:fs');
const {spawn,spawnSync}=require('node:child_process');const net=require('node:net');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE_PATH||'playwright');
(async()=>{
 const backend=process.argv[2];assert.ok(backend?.startsWith('http://'));
 const port=await new Promise(resolve=>{const s=net.createServer();s.listen(0,'127.0.0.1',()=>{const p=s.address().port;s.close(()=>resolve(p));});});
 const root=path.resolve(__dirname,'..');const log=fs.openSync(path.join(root,'evaluation-results/listing-next.log'),'w');
 const server=spawn(process.execPath,[path.join(root,'frontend/node_modules/next/dist/bin/next'),'dev','--hostname','127.0.0.1','--port',String(port)],{cwd:path.join(root,'frontend'),env:{...process.env,NEXT_PUBLIC_API_URL:backend},stdio:['ignore',log,log],windowsHide:true});
 let browser,context,registered=false;
 try{
  browser=await chromium.launch({channel:'chrome',headless:true});context=await browser.newContext({baseURL:`http://127.0.0.1:${port}`});
  for(let i=0;i<60;i++){try{if((await context.request.get('/api/auth/me')).status()===401)break;}catch{}await new Promise(r=>setTimeout(r,1000));}
  const reg=await context.request.post('/api/auth/register',{data:{email:`listing-browser-${Date.now()}@example.com`,password:'listing-browser-12345',name:'매물 수입 검증'}});assert.equal(reg.status(),201);registered=true;
  const page=await context.newPage();page.setDefaultTimeout(60000);await page.goto('/listings');
  await page.getByRole('heading',{name:'매물 보관함',exact:true}).waitFor();
  await page.getByText('여러 매물 등록 (CSV)',{exact:true}).click();
  const header='external_id,name,property_type,transaction_type,address,legal_region_code,area_sqm,asking_price,confirmed_at,status';
  const confirmed=new Date(Date.now()-3600000).toISOString();
  const csv=header+'\nfixture-1,브라우저 검증용 가상 매물,apartment,purchase,서울특별시 강남구 역삼동 123,1168010100,84,700000000,'+confirmed+',active\n';
  await page.getByPlaceholder('제공 중개업소 또는 직접 등록').fill('검증용 가상 출처');
  await page.getByLabel('매물 CSV 파일').setInputFiles({name:'listings.csv',mimeType:'text/csv',buffer:Buffer.from(csv)});
  await page.getByRole('button',{name:'검증·미리보기'}).click();await page.getByText('총 1행 · 오류 0건 · 주의 0건',{exact:true}).waitFor();
  assert.equal((await(await context.request.get('/api/listings')).json()).total,0);
  await page.getByRole('button',{name:'검증된 자료 저장'}).click();await page.getByRole('heading',{name:'브라우저 검증용 가상 매물',exact:true}).waitFor();
  let list=await(await context.request.get('/api/listings')).json();assert.equal(list.total,1);assert.equal(list.items[0].asking_price,700000000);
  await page.getByLabel('지역 (서울)',{exact:true}).selectOption('1168000000');
  await page.getByLabel('법정동',{exact:true}).selectOption('1168010100');
  await page.getByRole('button',{name:'검색',exact:true}).click();await page.getByText(/총 1건/).waitFor();
  await page.getByRole('button',{name:'매수 후보 저장'}).click();await page.getByRole('link',{name:'케이스 보기'}).waitFor();
  const cases=await(await context.request.get('/api/cases')).json();const detail=await(await context.request.get(`/api/cases/${cases.items[0].id}`)).json();assert.equal(detail.properties[0].asking_price,700000000);
  const bad=csv.replace('700000000','7억');await page.getByLabel('매물 CSV 파일').setInputFiles({name:'invalid.csv',mimeType:'text/csv',buffer:Buffer.from(bad)});
  await page.getByRole('button',{name:'검증·미리보기'}).click();await page.getByText(/오류가 있어 저장하지 않습니다/).waitFor();assert.ok(await page.getByRole('button',{name:'검증된 자료 저장'}).isDisabled());
  assert.equal((await(await context.request.get('/api/listings')).json()).total,1);
  await page.getByRole('button',{name:'변경 이력'}).click();await page.getByRole('heading',{name:'최근 변경 이력 (최대 100건)'}).waitFor();
  assert.equal(await page.getByRole('link',{name:'네이버페이 부동산에서 매물 보기 ↗'}).getAttribute('href'),'https://land.naver.com/');
  await page.getByLabel('네이버 매물 링크').fill('https://example.com/articles/123456');
  await page.getByLabel('매물 이름',{exact:true}).fill('링크 등록 검증용 가상 매물');
  await page.getByLabel('확인한 주소').fill('서울특별시 강남구 역삼동 123');
  await page.getByLabel('확인한 면적 (㎡)').fill('84');
  await page.getByLabel('확인한 호가 (원)').fill('800000000');
  await page.getByLabel('원문 확인 일시 (현재 기기 시간대)').fill(new Date(Date.now()-3600000).toISOString().slice(0,16));
  await page.getByRole('button',{name:'관심 매물 등록',exact:true}).click();
  await page.getByText('네이버페이 부동산의 HTTPS 매물 링크를 입력해주세요.',{exact:true}).waitFor();
  assert.equal((await(await context.request.get('/api/listings')).json()).total,1);
  await page.getByLabel('네이버 매물 링크').fill('https://fin.land.naver.com/articles/123456');
  await page.getByRole('button',{name:'관심 매물 등록',exact:true}).click();
  await page.getByRole('heading',{name:'링크 등록 검증용 가상 매물',exact:true}).waitFor();
  list=await(await context.request.get('/api/listings')).json();
  const linked=list.items.find(item=>item.external_id==='123456');
  assert.equal(linked.asking_price,800000000);assert.equal(linked.status,'unknown');assert.equal(linked.source_url,'https://fin.land.naver.com/articles/123456');
  // 실제 수집 성공 여부와 구분해서, 고정 응답으로 추출값 검토 UI를 검증한다.
  const observation={observation_id:999,external_id:'987654',source_url:'https://fin.land.naver.com/articles/987654',requested_at:Date.now()/1000,fetched_at:Date.now()/1000,outcome:'observed',message:'고정 응답 검증',fields:{name:'추출 검증용 가상 매물',address:'서울특별시 강남구 역삼동 123',area_sqm:84,asking_price:900000000,transaction_type:'purchase'}};
  await page.route('**/api/listings/collection/**',route=>{
    const url=route.request().url();
    return route.fulfill({json:url.includes('/history?')?{items:[observation]}:url.endsWith('/jobs')?{job_id:'fixture'}:{status:'done',result:observation}});
  });
  await page.getByLabel('수집할 매물 링크').fill(observation.source_url);
  await page.getByRole('button',{name:'원문 수집·재확인',exact:true}).click();
  await page.getByRole('button',{name:'추출값을 아래 등록 폼에 적용',exact:true}).click();
  assert.equal(await page.getByLabel('매물 이름',{exact:true}).inputValue(),observation.fields.name);
  assert.equal(await page.getByLabel('확인한 호가 (원)').inputValue(),'900000000');
  assert.equal(await page.getByLabel('확인한 거래 상태').inputValue(),'unknown');
  assert.equal(await page.getByLabel('원문 확인 일시 (현재 기기 시간대)').inputValue(),'');
  await page.screenshot({path:path.join(root,'evaluation-results/listing-import-browser.png'),fullPage:true});
  console.log('PASS CSV preview → commit → region search → candidate; invalid batch blocked; history displayed');
 }finally{
  try{if(registered)assert.equal((await context.request.delete('/api/auth/me')).status(),200);}finally{
   if(browser)await browser.close();if(server.pid)spawnSync('taskkill',['/PID',String(server.pid),'/T','/F'],{windowsHide:true,stdio:'ignore'});fs.closeSync(log);
  }
 }
})().catch(e=>{console.error(e.message);process.exitCode=1;});
