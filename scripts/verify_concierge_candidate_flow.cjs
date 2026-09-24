const assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE_PATH);
(async()=>{
const browser=await chromium.launch({channel:'chrome',headless:true});
const context=await browser.newContext({baseURL:'http://localhost:3001'});const page=await context.newPage();page.setDefaultTimeout(60000);let registered=false;
try{
 assert.equal((await context.request.post('/api/auth/register',{data:{email:`save-complex-${Date.now()}@example.com`,password:'save-complex-test-12345',name:'후보 연결 검증'}})).status(),201);registered=true;
 await page.goto('/');await page.getByRole('button',{name:'AI 컨시어지 열기',exact:true}).click();
 async function resultAfter(action){const pending=page.waitForResponse(r=>r.url().endsWith('/concierge/jobs')&&r.request().method()==='POST');await action();const {job_id}=await(await pending).json();let job;for(let i=0;i<180;i++){job=await(await context.request.get(`/api/concierge/jobs/${job_id}`)).json();if(['done','error'].includes(job.status))break;await new Promise(r=>setTimeout(r,1000));}assert.equal(job.status,'done',JSON.stringify(job));await page.getByText(job.result.answer,{exact:true}).waitFor();return job.result;}
 async function ask(text){return resultAfter(async()=>{await page.getByPlaceholder('예산과 희망 지역을 말씀해 주세요').fill(text);await page.getByRole('button',{name:'메시지 보내기',exact:true}).click();});}
 let result=await ask('서울특별시 강남구 역삼동 8억 이하 아파트 매매 단지 추천해줘');assert.equal(result.tool_used,'select_properties');
 const item=result.data.results[0];const card=page.getByRole('article',{name:`${item.complex_name} 후보 저장`});
 assert.equal(await card.getByLabel('확인한 희망가 (만원, 선택)').inputValue(),'');
 await card.getByLabel('실제 검토 전용면적 (㎡)').fill('49');await card.getByLabel('확인한 희망가 (만원, 선택)').fill('70000');
 await card.getByRole('button',{name:'후보 저장·선택'}).click();await page.getByText(/후보를 저장하고 선택했습니다/).waitFor();
 const caseId=Number(await page.getByLabel('검토 케이스',{exact:true}).inputValue());const candidateId=Number(await page.getByLabel('분석할 후보',{exact:true}).inputValue());assert.ok(candidateId);
 let detail=await(await context.request.get(`/api/cases/${caseId}`)).json();assert.equal(detail.properties.length,1);assert.equal(detail.properties[0].asking_price,700000000);assert.equal(detail.properties[0].area_sqm,49);assert.equal(detail.properties[0].category,'apartment');
 await card.getByRole('button',{name:'후보 저장·선택'}).click();await page.getByText(/既存|기존 목록에서 선택/).waitFor();detail=await(await context.request.get(`/api/cases/${caseId}`)).json();assert.equal(detail.properties.length,1);
 result=await resultAfter(()=>page.getByRole('button',{name:'선택 후보 자금 분석',exact:true}).click());assert.equal(result.tool_used,'simulate_investment');assert.equal(result.data.candidate_id,candidateId);assert.equal(result.status,'needs_input');assert.ok(!result.missing_fields.includes('asking_price'));
 console.log('PASS recommendation → save → deduplicate → selected candidate funding tool');
 result=await resultAfter(()=>page.getByRole('button',{name:'선택 후보 AVM 실행',exact:true}).click());assert.equal(result.status,'queued');assert.equal(result.data.candidate_id,candidateId);const avmJob=result.data.job_id;
 for(let i=0;i<300;i++){const job=await(await context.request.get(`/api/appraisal/jobs/${avmJob}`)).json();if(['done','error'].includes(job.status)){assert.equal(job.status,'done',JSON.stringify({status:job.status,error:job.error}));console.log('PASS AVM completed from saved chat candidate');break;}if(i===299)throw Error('AVM timed out');await new Promise(r=>setTimeout(r,1000));}
 await page.getByRole('button',{name:'새 대화 시작 · 기억한 조건 초기화',exact:true}).click();
 result=await ask('성인 자녀에게 현금 5억 원을 증여하면 증여세 얼마야?');assert.equal(result.tool_used,'answer_tax_legal');
 result=await ask('그럼 같은 금액을 배우자에게 증여하면?');assert.equal(result.tool_used,'answer_tax_legal');
 assert.match(result.answer, /0\s*원/);console.log('PASS legal followup retains gift amount and changes relation');
 await page.screenshot({path:'evaluation-results/concierge-save-context.png',fullPage:true});
}finally{try{if(registered)assert.equal((await context.request.delete('/api/auth/me')).status(),200);}finally{await browser.close();}}
})().catch(e=>{console.error(e.message);process.exitCode=1;});
