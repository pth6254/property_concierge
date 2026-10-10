// 검증용 후보로 물건 입력·복원·재검토와 실제 손상 PDF의 실패 표시를 확인한다.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const net = require('node:net');
const {spawn, spawnSync} = require('node:child_process');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE_PATH || '../web/node_modules/playwright');

// 실제 발급 문서 없이 PDF 추출·페이지·최소 근거 저장 경로를 확인하는 가상 문서다.
function textPdf(pages) {
  const chars=[...new Set(pages.join('').replace(/\n/g,'').split(''))];
  const ids=new Map(chars.map((char,index)=>[char,index+1]));
  const hex=value=>value.toString(16).padStart(4,'0');
  const cmap=`/CIDInit /ProcSet findresource begin\n12 dict begin\nbegincmap\n/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def\n/CMapName /TestUnicode def\n/CMapType 2 def\n1 begincodespacerange\n<0000> <FFFF>\nendcodespacerange\n${chars.length} beginbfchar\n${chars.map(char=>`<${hex(ids.get(char))}> <${hex(char.charCodeAt(0))}>`).join('\n')}\nendbfchar\nendcmap\nCMapName currentdict /CMap defineresource pop\nend\nend`;
  const stream=value=>`<< /Length ${Buffer.byteLength(value,'ascii')} >>\nstream\n${value}\nendstream`;
  const objects=['<< /Type /Catalog /Pages 2 0 R >>',`<< /Type /Pages /Kids [${pages.map((_,i)=>`${7+i*2} 0 R`).join(' ')}] /Count ${pages.length} >>`,
    '<< /Type /Font /Subtype /Type0 /BaseFont /TestFont /Encoding /Identity-H /DescendantFonts [4 0 R] /ToUnicode 5 0 R >>',
    '<< /Type /Font /Subtype /CIDFontType2 /BaseFont /TestFont /CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) /Supplement 0 >> /FontDescriptor 6 0 R /DW 1000 /CIDToGIDMap /Identity >>',stream(cmap),
    '<< /Type /FontDescriptor /FontName /TestFont /Flags 4 /FontBBox [0 0 1000 1000] /ItalicAngle 0 /Ascent 1000 /Descent 0 /CapHeight 1000 /StemV 80 >>'];
  pages.forEach((text,i)=>{objects.push(`<< /Type /Page /Parent 2 0 R /MediaBox [0 0 600 840] /Resources << /Font << /F1 3 0 R >> >> /Contents ${8+i*2} 0 R >>`);
    objects.push(stream(`BT /F1 12 Tf 40 800 Td ${text.split('\n').map((line,index)=>`${index?'0 -16 Td ':''}<${line.split('').map(char=>hex(ids.get(char))).join('')}> Tj`).join('\n')} ET`));});
  let pdf='%PDF-1.7\n';const offsets=[0];objects.forEach((obj,i)=>{offsets.push(Buffer.byteLength(pdf,'ascii'));pdf+=`${i+1} 0 obj\n${obj}\nendobj\n`;});
  const start=Buffer.byteLength(pdf,'ascii');pdf+=`xref\n0 ${objects.length+1}\n0000000000 65535 f \n${offsets.slice(1).map(value=>`${String(value).padStart(10,'0')} 00000 n \n`).join('')}trailer\n<< /Size ${objects.length+1} /Root 1 0 R >>\nstartxref\n${start}\n%%EOF`;
  return Buffer.from(pdf,'ascii');
}

(async () => {
  const root=path.resolve(__dirname,'..'), output=path.join(root,'evaluation-results');
  fs.mkdirSync(output,{recursive:true});
  const report={status:'running',checks:[],boundaries:['검증용 후보·손상 PDF·가상 텍스트 PDF','실제 등록·저장·화면·복원','실제 AVM·발급 문서 탐지 정확도는 별도 평가']};
  const check=title=>{report.checks.push(title);console.log(`PASS ${title}`);};
  let server,log,browser,context,page,registered=false;
  try {
    let baseURL=process.env.E2E_BASE_URL || (process.argv[2] ? undefined : 'http://localhost:3002');
    if(!baseURL){
      assert.ok(process.argv[2]?.startsWith('http://'),'격리 API 주소 또는 E2E_BASE_URL이 필요합니다');
      const port=await new Promise(resolve=>{const s=net.createServer();s.listen(0,'127.0.0.1',()=>{const p=s.address().port;s.close(()=>resolve(p));});});
      baseURL=`http://127.0.0.1:${port}`;log=fs.openSync(path.join(output,'property-evidence-next.log'),'w');
      server=spawn(process.execPath,[path.join(root,'web/node_modules/next/dist/bin/next'),'dev','--webpack','--hostname','127.0.0.1','--port',String(port)],{cwd:path.join(root,'web'),env:{...process.env,NEXT_PUBLIC_API_URL:process.argv[2],NEXT_TELEMETRY_DISABLED:'1'},stdio:['ignore',log,log],windowsHide:true});
    }
    browser=await chromium.launch(process.env.E2E_BROWSER==='chromium'?{headless:true}:{channel:'chrome',headless:true});
    context=await browser.newContext({baseURL,viewport:{width:1440,height:1000}});
    for(let i=0;i<60;i++){if((await context.request.get('/api/auth/me').catch(()=>null))?.status()===401)break;await new Promise(resolve=>setTimeout(resolve,1000));}
    const registration=await context.request.post('/api/auth/register',{data:{email:`evidence-${Date.now()}@example.com`,password:'property-evidence-12345!',name:'근거 검증 임시 계정'}});
    assert.equal(registration.status(),201);registered=true;
    const createdCase=await context.request.post('/api/cases',{data:{title:'물건 식별 검증'}});assert.equal(createdCase.status(),201);
    const caseId=(await createdCase.json()).id;
    page=await context.newPage();page.setDefaultTimeout(45000);const errors=[];page.on('pageerror',error=>errors.push(error.message));
    await page.goto(`/cases/${caseId}`);await page.getByRole('button',{name:'후보 추가'}).click();
    await page.getByPlaceholder('후보명 또는 건물명').fill('개별 호 검증 후보');await page.getByPlaceholder('주소',{exact:true}).fill('서울특별시 강남구 역삼동 123');
    await page.getByLabel('매도 희망가', { exact: true }).fill('8억');await page.getByPlaceholder('면적(㎡)').fill('84');await page.getByLabel('후보 물건 종류').selectOption('아파트');
    await page.getByLabel('건물 동 (선택)').fill('101');await page.getByLabel('호수 (선택)').fill('501');await page.getByLabel('층 (선택)').fill('5');await page.getByLabel('면적 기준',{exact:true}).selectOption('exclusive');
    const createdPromise=page.waitForResponse(r=>r.url().endsWith(`/cases/${caseId}/properties`)&&r.request().method()==='POST');await page.getByRole('button',{name:'후보 저장',exact:true}).click();
    const created=await createdPromise;assert.equal(created.status(),201);const candidateId=(await created.json()).id;
    await page.getByText('동: 101 · 호: 501 · 층: 5',{exact:true}).waitFor();await page.reload();await page.getByText('동: 101 · 호: 501 · 층: 5',{exact:true}).waitFor();
    check('동·호·층·면적 기준 화면 입력·저장·새로고침 복원');
    const other=await context.request.post(`/api/cases/${caseId}/properties`,{data:{name:'다른 호 후보',address:'서울특별시 강남구 역삼동 123',category:'아파트',area_sqm:84,identity:{building_dong:'101',unit_number:'502',floor:'5',area_basis:'exclusive'}}});assert.equal(other.status(),201);
    await page.goto(`/cases/${caseId}/comparison`);await page.getByText('동·호·면적 기준',{exact:true}).waitFor();assert.equal((await(await context.request.get(`/api/cases/${caseId}`)).json()).properties.length,2);check('같은 주소의 다른 호 구분·자동 병합 없음');
    assert.equal((await context.request.post(`/api/cases/${caseId}/decision`,{data:{property_id:candidateId,reason:'검증용 사용자 후보 선택'}})).status(),200);
    await page.goto(`/cases/${caseId}`);const card=page.locator('article').filter({has:page.getByRole('heading',{name:'개별 호 검증 후보',exact:true})});
    await card.getByText('동·호·층 정보 수정',{exact:true}).click();await card.getByLabel('호수 (선택)').fill('503');await card.getByRole('button',{name:'물건 정보 저장',exact:true}).click();
    await card.getByText('동: 101 · 호: 503 · 층: 5',{exact:true}).waitFor();const changed=await(await context.request.get(`/api/cases/${caseId}`)).json();assert.equal(changed.selected_property_id,null);assert.ok(changed.properties[0].source_reviews.length);check('물건 변경 → 선택 해제·과거 검토 이력 보존');
    await page.goto('/rights');await page.locator('input[type=file]').first().setInputFiles({name:'invalid.pdf',mimeType:'application/pdf',buffer:Buffer.from('%PDF-1.7\ninvalid-document')});
    const analyzedPromise=page.waitForResponse(r=>r.url().endsWith('/rights/analyze')&&r.request().method()==='POST');await page.getByRole('button',{name:'위험 점검 시작',exact:true}).click();
    const analyzed=await(await analyzedPromise).json();assert.equal(analyzed.risk_grade,'unknown');assert.equal(analyzed.risk_score,null);
    await page.getByText('문서 판독 실패 — 권리 미확인').waitFor();await page.getByText('위험 점수 산정 불가').waitFor();assert.equal(await page.getByText('특이 위험 신호 없음',{exact:true}).count(),0);check('실제 손상 PDF → 판독 실패·미확인·안전 및 0점 표시 없음');
    await page.screenshot({path:path.join(output,'property-evidence-browser-rights-failure.png'),fullPage:true});
    await page.goto(`/cases/${caseId}`);await card.getByRole('link',{name:'권리 분석'}).click();
    const registry=textPdf(['발급일자: 2026.10.02\n[집합건물] 서울특별시 강남구 역삼동 123 제101동 제503호\n주요 등기사항 요약\n소유지분현황 (갑구) 소유자 가상검증자', '가압류\n채권최고액 금50,000,000원']);
    await page.locator('input[type=file]').first().setInputFiles({name:'synthetic-registry.pdf',mimeType:'application/pdf',buffer:registry});
    const parsedPromise=page.waitForResponse(r=>r.url().endsWith('/rights/analyze')&&r.request().method()==='POST');await page.getByRole('button',{name:'위험 점검 시작',exact:true}).click();
    const parsed=await(await parsedPromise).json();assert.equal(parsed.subject_match.status,'unit_match');assert.equal(parsed.risk_grade,'danger');assert.equal(parsed.evidence[0].page,2);assert.equal(parsed.evidence[0].issued_at,'2026-10-02');
    await page.locator('summary').filter({hasText:'문서별 최소 근거'}).click();await page.getByText('등기부 2쪽 · 가압류',{exact:true}).waitFor();check('가상 PDF 실제 판독 → 물건 대조·페이지·발급일·최소 발췌 표시');
    const summary=await(await context.request.get(`/api/cases/${caseId}/summary`)).json();const risk=summary.decision.candidates.find(item=>item.property_id===candidateId).axes.find(item=>item.key==='risk');
    const evidence=risk.evidence.find(item=>item.provenance?.item==='가압류');assert.equal(evidence.value,'가압류');assert.equal(evidence.provenance.page,2);assert.ok(!JSON.stringify(risk).includes('가상검증자'));
    await page.goto(`/cases/${caseId}/summary`);await page.reload();const riskCard=page.getByRole('region',{name:'개별 호 검증 후보 위험성'});await riskCard.getByText('판단 근거',{exact:false}).click();await riskCard.getByText('등기부 2쪽 · 가압류',{exact:true}).waitFor();check('후보 요약·새로고침에 최소 근거 보존·소유자 원문 제외');
    await page.screenshot({path:path.join(output,'property-evidence-browser.png'),fullPage:true});await page.setViewportSize({width:390,height:844});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);assert.deepEqual(errors,[]);check('좁은 화면 넘침·브라우저 실행 오류 없음');report.status='passed';
  }catch(error){report.status='failed';report.error=error.message;if(page)await page.screenshot({path:path.join(output,'property-evidence-browser-failure.png'),fullPage:true}).catch(()=>{});throw error;}
  finally{try{if(registered)assert.equal((await context.request.delete('/api/auth/me')).status(),200);}finally{report.finished_at=new Date().toISOString();fs.writeFileSync(path.join(output,'property-evidence-browser.json'),JSON.stringify(report,null,2));if(browser)await browser.close();if(server?.pid){if(process.platform==='win32')spawnSync('taskkill',['/PID',String(server.pid),'/T','/F'],{windowsHide:true,stdio:'ignore'});else server.kill('SIGTERM');}if(log!==undefined)fs.closeSync(log);}}
})().catch(error=>{console.error(error.message);process.exitCode=1;});
