"""격리 Spring의 외부 공급자 HTTP 대역. 운영 서비스 이미지에서 실행하지 않는다."""
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from xml.sax.saxutils import escape

app = FastAPI()
state = {}

@app.get('/health')
def health(): return {'status':'ok'}

@app.post('/configure')
async def configure(request:Request):
    state.clear(); state.update(await request.json())
    return {'configured':True}

@app.get('/local/{kind}.json')
def kakao(kind:str,query:str):
    if state.get('failure'):
        return JSONResponse({'message':'secret-key-must-not-leak'},status_code=500)
    docs = state.get('documents',[])
    if kind=='keyword': docs = state.get('places',[])
    elif state.get('empty_query')==query: docs=[]
    return {'documents':docs}

@app.get('/buildings')
def buildings():
    records=state.get('building_records')
    if records is None:
        records=[{'sigunguCd':'11680','bjdongCd':'10100','bun':'0123','ji':'0000','bldNm':name} for name in state.get('names',[])]
    items=''.join('<item>'+''.join(f'<{key}>{escape(str(value))}</{key}>' for key,value in record.items())+'</item>' for record in records)
    return Response(f'<response><resultCode>00</resultCode><totalCount>{len(records)}</totalCount><items>{items}</items></response>',media_type='application/xml')

@app.post('/oauth/token')
async def token(request:Request):
    body=(await request.body()).decode()
    if 'code_verifier=' not in body or 'code=' not in body:
        return JSONResponse({'error':'invalid_request'},status_code=400)
    if state.get('oauth_failure'): return JSONResponse({'error':'invalid_grant'},status_code=400)
    return {'access_token':'isolated-access-token','token_type':'Bearer'}

@app.get('/oauth/userinfo')
def userinfo():
    return state.get('google_user',{'id':'isolated-google-user','email':'google@example.com','verified_email':True,'name':'OAuth 검증','picture':''})
