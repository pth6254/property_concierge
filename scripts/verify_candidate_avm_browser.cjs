const fs = require('node:fs');
// 별도 설치된 Playwright도 사용할 수 있게 해 앱의 런타임 의존성에 섞지 않는다.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || '../frontend/node_modules/playwright');
(async () => {
  const browser = await chromium.launch({channel:'chrome',headless:true});
  const context = await browser.newContext({baseURL:process.env.E2E_BASE_URL || 'http://localhost:3001'});
  fs.mkdirSync('evaluation-results',{recursive:true});
  const page = await context.newPage();
  const pageErrors=[];
  page.on('pageerror', error=>{pageErrors.push(error.message);console.log('PAGE ERROR:',error.message.slice(0,400));});
  page.on('response', res=>{if(res.status()>=400)console.log('HTTP',res.status(),new URL(res.url()).pathname);});
  page.on('requestfailed', req=>console.log('REQUEST FAILED',new URL(req.url()).pathname,req.failure()?.errorText));
  page.setDefaultTimeout(45000);
  const email = `avm-browser-${Date.now()}@example.com`;
  let registered=false;
  const evidence={mode:'live',model_mocked:false,stages:[]};
  const formFlow=process.argv.includes('--form');
  const decisionFlow=process.argv.includes('--decision-flow');
  evidence.flow=decisionFlow?'decision':formFlow?'form':'chat';
  let caseId;
  try {
    console.log('Browser live validation started');
    for(let attempt=0;attempt<40;attempt++) {
      const probe=await context.request.get('/api/auth/me').catch(()=>null);
      if(probe?.status()===401)break;
      await new Promise(r=>setTimeout(r,1000));
    }
    const reg=await context.request.post('/api/auth/register',{data:{email,password:'avm-browser-only-12345',name:'AVM 검증 임시 계정'}});
    if(reg.status()!==201) throw Error(`register ${reg.status()}`);
    registered=true;
    const created=await context.request.post('/api/cases',{data:{title:'AVM 실제 연결 검증'}});
    caseId=(await created.json()).id;
    const added=await context.request.post(`/api/cases/${caseId}/properties`,{data:{name:'래미안퍼스티지',address:'서울특별시 서초구 반포동 18-1',category:'아파트',area_sqm:84.9,asking_price:3000000000}});
    const candidate=(await added.json());
    if(!candidate.id) throw Error(`candidate ${added.status()}`);
    await page.goto(`/appraisal?caseId=${caseId}&candidateId=${candidate.id}`);
    await page.getByRole('heading',{name:'상세 정보 입력'}).waitFor();
    if(await page.getByRole('spinbutton',{name:'면적(㎡)',exact:true}).inputValue()!=='84.9') throw Error('area prefill mismatch');
    await page.getByText('서울특별시 서초구 반포동 18-1',{exact:true}).waitFor();
    evidence.stages.push('address_area_prefill'); console.log('PASS address/area prefill');
    let jobId;
    if(formFlow){
      const response=page.waitForResponse(r=>r.url().endsWith('/appraisal/jobs')&&r.request().method()==='POST');
      await page.getByRole('button',{name:'시세추정 시작',exact:true}).click();
      jobId=(await (await response).json()).job_id;
      evidence.stages.push('form_queued'); console.log('PASS form starts AVM');
    }else{
    await page.goto(`/cases/${caseId}`);
    await page.getByRole('button',{name:'AI 컨시어지 열기',exact:true}).click();
    const dialog=page.getByRole('dialog',{name:'AI 부동산 컨시어지'});
    await dialog.getByRole('combobox',{name:'분석할 후보'}).selectOption(String(candidate.id));
    await dialog.getByPlaceholder('예산과 희망 지역을 말씀해 주세요').fill('선택한 후보의 AVM 시세를 추정해줘');
    const replyPromise=page.waitForResponse(r=>r.url().endsWith('/concierge/jobs')&&r.request().method()==='POST',{timeout:180000});
    await dialog.getByRole('button',{name:'메시지 보내기'}).click();
    const reply=await replyPromise;
    const accepted=await reply.json();
    let conversationJob;
    const conversationDeadline=Date.now()+180000;
    while(Date.now()<conversationDeadline){
      conversationJob=await (await context.request.get(`/api/concierge/jobs/${accepted.job_id}`)).json();
      if(['done','error'].includes(conversationJob.status))break;
      await new Promise(resolve=>setTimeout(resolve,1000));
    }
    if(conversationJob?.status!=='done')throw Error('Concierge job did not complete');
    const data=conversationJob.result;
    evidence.chat_status=data.status; evidence.intent=data.intent;
    if(!data.data?.job_id) throw Error(`chat ${data.status}: ${data.answer}`);
    evidence.stages.push('chat_queued'); console.log('PASS chat starts AVM');
    jobId=data.data.job_id;
    }
    const deadline=Date.now()+480000;
    let job;
    while(Date.now()<deadline){
      const res=await context.request.get(`/api/appraisal/jobs/${jobId}`);
      job=await res.json();
      console.log(`AVM ${job.status}: ${job.step||''}`);
      if(['done','error'].includes(job.status))break;
      await new Promise(r=>setTimeout(r,15000));
    }
    evidence.job_status=job?.status;
    if(job?.status!=='done'||!job.history_id)throw Error('AVM did not complete and persist');
    const detail=await (await context.request.get(`/api/cases/${caseId}`)).json();
    const linked=detail.properties.find(p=>p.id===candidate.id);
    if(linked.history_id!==job.history_id||!(linked.appraisal?.estimated_value>0))throw Error('candidate result not linked');
    const raw=job.result.analysis_result;
    const expectedWon=raw.estimated_value*(raw.value_unit==='만원'?10000:1);
    if(linked.appraisal.estimated_value!==expectedWon)throw Error('AVM/candidate currency unit mismatch');
    const comparison=await (await context.request.get(`/api/cases/${caseId}/comparison`)).json();
    if(comparison.rows[0].estimated_value!==expectedWon)throw Error('comparison currency unit mismatch');
    if(job.result.intent.area_min!==84.9)throw Error('confirmed area was not used');
    evidence.raw_unit=raw.value_unit; evidence.area_sqm=job.result.intent.area_min;
    evidence.stages.push('won_conversion_and_confirmed_area');
    evidence.history_id=job.history_id; evidence.estimated_value=linked.appraisal.estimated_value;
    evidence.stages.push('live_avm_saved_to_candidate');
    if(decisionFlow){
      await page.goto(`/cases/${caseId}`);
      await page.getByRole('link').filter({hasText:'자금 분석'}).click();
      await page.getByLabel('보유 현금 (원)',{exact:true}).fill('20억');
      await page.getByLabel('월 대출 상환 한도 (원)',{exact:true}).fill('1000만');
      await page.getByPlaceholder('예: 8000만').fill('3억');
      const calculated=page.waitForResponse(r=>r.url().endsWith('/api/simulation')&&r.request().method()==='POST');
      await page.getByRole('button',{name:'💰 시뮬레이션 계산',exact:true}).click();
      const simulation=await(await calculated).json();
      if(simulation.error||!simulation.candidate_funding)throw Error('실제 자금 계산 저장 실패');
      evidence.stages.push('real_funding_calculated_and_saved');
      // 두 번째 후보도 실제 계산기로 분석해 비교 값이 섞이지 않는지 확인한다.
      const other=await(await context.request.post(`/api/cases/${caseId}/properties`,{data:{name:'비교용 직접 입력 후보',address:'서울특별시 서초구 반포동',category:'아파트',area_sqm:84.9,asking_price:3100000000}})).json();
      const otherCalculation=await context.request.post('/api/simulation',{data:{case_id:caseId,candidate_id:other.id,purchase_price:3100000000,cash_available:2000000000,monthly_payment_limit:10000000,annual_income:300000000}});
      if(otherCalculation.status()!==200)throw Error('두 번째 후보 계산 실패');
      await page.goto(`/cases/${caseId}/comparison`);
      await page.getByRole('button',{name:'이 후보를 최종 선택',exact:true}).first().click();
      await page.locator('textarea').fill('검증용 선택: 실제 AVM·자금 결과를 비교했으며 권리서류 미확인 상태를 인지함');
      await page.getByRole('button',{name:'선택 저장',exact:true}).click();
      await page.getByText('최종 선택과 근거가 저장되었습니다. 남은 확인 사항은 거래 준비에서 이어가세요.',{exact:true}).waitFor();
      await page.reload();
      const persisted=await(await context.request.get(`/api/cases/${caseId}/summary`)).json();
      if(persisted.case.selected_property_id!==candidate.id)throw Error('최종 선택 복원 실패');
      const selected=persisted.comparison.rows.find(r=>r.property_id===candidate.id);
      if(selected.funding.required_cash!==simulation.candidate_funding.required_cash)throw Error('자금 결과 비교 불일치');
      if(selected.estimated_value!==expectedWon)throw Error('AVM 결과 비교 불일치');
      if(!selected.missing.some(v=>v.includes('권리')))throw Error('미확인 위험 누락');
      await page.goto(`/cases/${caseId}/summary`);
      await page.getByRole('heading',{name:'매수 검토 요약',exact:true}).waitFor();
      await page.getByText('권리서류 분석',{exact:true}).first().waitFor();
      if(!(await page.getByRole('link',{name:'검토 항목 보기',exact:true}).first().getAttribute('href')).startsWith(`/cases/${caseId}#candidate-checklist-`))throw Error('요약의 체크리스트 이동 경로 오류');
      await page.screenshot({path:'evaluation-results/decision-live-summary.png',fullPage:true});
      evidence.stages.push('two_candidate_comparison','selection_and_reload','summary_matches_saved_analysis');
    }
    await page.goto(`/cases/${caseId}`); await page.reload();
    await page.getByRole('link',{name:'시세추정 리포트 보기'}).waitFor();
    await page.screenshot({path:'evaluation-results/avm-browser.png',fullPage:true});
    evidence.stages.push('browser_reload_verified');
    if(pageErrors.length)throw Error('브라우저 실행 오류가 발생했습니다. 로그를 확인하세요.');
    console.log('PASS live AVM candidate persistence and browser reload');
  }catch(error){ evidence.error=error.message.split('Call log:')[0]; console.log(evidence.error); console.log((await page.locator('body').innerText().catch(()=>'' )).slice(-1600)); process.exitCode=1; }
  finally {
    fs.writeFileSync(`evaluation-results/avm-browser-result-${evidence.flow}.json`,JSON.stringify(evidence,null,2));
    try{ if(registered){const clean=await context.request.delete('/api/auth/me');console.log(`Temporary account cleanup ${clean.status()}`);if(clean.status()!==200)throw Error('cleanup failed');} }
    catch{console.log(`Cleanup pending for ${email}`);process.exitCode=1;}
    await browser.close();
  }
})();
