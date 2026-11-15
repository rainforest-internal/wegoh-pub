"""Browser-admin bridge to the dedicated VM's fixed deployment socket.
Ordinary Linux/macOS development has no broker and reports unavailable.
"""
import asyncio
import json
import os
import ipaddress
import re
import socket
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

SOCKET_PATH = '/run/wegoh-live-control.sock'
REQUEST_ID = re.compile(r'[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}')


def exchange(value):
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(3)
            connection.connect(SOCKET_PATH)
            connection.sendall(json.dumps(value, separators=(',', ':')).encode() + b'\n')
            raw = bytearray()
            while not raw.endswith(b'\n'):
                part = connection.recv(8193-len(raw))
                if not part or len(raw) + len(part) > 8192:
                    raise ValueError('Invalid broker response')
                raw.extend(part)
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise ValueError('Invalid broker response')
            return result
    except (OSError, ValueError, TypeError):
        # A lost response is not evidence that POST had no effect.
        raise HTTPException(503, 'Deployment status unavailable; refresh before another explicit request') from None


def management_origin(auth):
    raw=os.environ.get('WEGOH_MANAGEMENT_ORIGIN','')
    if not raw:return None
    try:
        value=urlsplit(raw)
        if (value.scheme!='https' or not value.hostname or value.netloc!=value.hostname
                or value.path or value.query or value.fragment or value.username or value.password
                or raw!='https://'+value.hostname or not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?',value.hostname)):
            raise ValueError()
        if not all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?',label)for label in value.hostname.split('.')):
            raise ValueError()
        try:ipaddress.ip_address(value.hostname)
        except ValueError:pass
        else:raise ValueError()
        forbidden={getattr(auth,'public_origin',None),getattr(auth,'native_origin',None),
                   getattr(getattr(auth,'native_authorization',None),'origin',None),getattr(auth,'issuer',None)}
        if raw in forbidden or value.hostname in ('localhost',) or value.hostname.endswith('.localhost'):
            raise ValueError()
        return raw
    except (ValueError,TypeError):
        raise HTTPException(503,'Management service configuration invalid')from None


def create_router(auth):
    router = APIRouter()
    if not auth.enabled:
        return router

    def gate(request, mutate=False):
        if request.url.hostname != urlsplit(auth.public_origin).hostname:
            raise HTTPException(404, 'Not found')
        identity=auth.browser(request, mutate=mutate, roles=('admin',))
        if auth.current_account(identity['id'], require_roster=True)['role'] != 'admin':
            raise HTTPException(403, 'Action not permitted')

    def response(result, status=200, unsupported=False):
        error = result.get('error')
        if error == 'UNSUPPORTED_OPERATION' or unsupported and error == 'INVALID_REQUEST':
            return JSONResponse({'detail':'Deployment controller update required', 'diagnostic':{'code':'CONTROLLER_UNSUPPORTED','phase':'prepare','operatorAction':'BOOTSTRAP_CONTROLLER','operatorNeeded':True}}, status_code=503, headers={'Cache-Control':'private, no-store'})
        if error in ('INVALID_TARGET','INVALID_REQUEST'):
            raise HTTPException(400,'Selected release is unavailable; refresh the release list')
        if error == 'BUSY':
            return JSONResponse(result, status_code=409, headers={'Cache-Control':'private, no-store'})
        if error:
            raise HTTPException(503, 'Deployment control unavailable')
        return JSONResponse(result, status_code=status, headers={'Cache-Control':'private, no-store'})

    def moved():
        origin=management_origin(auth)
        if origin:
            return JSONResponse({'detail':'Use the independent management service','code':'MANAGEMENT_SERVICE_REQUIRED',
                'managementOrigin':origin},status_code=503,headers={'Cache-Control':'private, no-store'})
        return None

    @router.get('/v1/operations/management-location',tags=['운영 설정'],summary='독립 관리 서비스의 설정된 주소 조회')
    def management_location(request: Request):
        gate(request)
        if request.url.query:raise HTTPException(400,'Query fields are not accepted')
        origin=management_origin(auth)
        return JSONResponse({'configured':origin is not None,'origin':origin},headers={'Cache-Control':'private, no-store'})

    @router.get('/v1/operations/releases',tags=['운영 설정'],summary='전환할 수 있는 저장된 서버 버전 목록')
    def releases(request: Request):
        gate(request)
        if request.url.query:raise HTTPException(400,'Query fields are not accepted')
        transition=moved()
        if transition is not None:return transition
        return response(exchange({'action':'releases'}))

    @router.get('/v1/operations/deployment', openapi_extra={'parameters':[{'name':'requestId','in':'query','required':False,'schema':{'type':'string','format':'uuid'},'description':'보존된 요청의 UUID4 조회. 전역 job과 별도로 requestedJob에 반환하며 배포를 시작하지 않습니다.'}]}, tags=['운영 설정'], summary='수동 배포 상태와 현재 서버 버전')
    def status(request: Request):
        gate(request)
        fields=list(request.query_params.multi_items())
        if fields and (len(fields)!=1 or fields[0][0]!='requestId' or not REQUEST_ID.fullmatch(fields[0][1])):
            raise HTTPException(400, 'Only one UUID4 requestId lookup is accepted')
        transition=moved()
        if transition is not None:return transition
        return response(exchange({'action':'status',**({'requestId':fields[0][1]} if fields else {})}))

    @router.get('/v1/operations/deployment-plan', openapi_extra={'parameters':[{'name':'targetRevision','in':'query','required':True,'schema':{'type':'string','pattern':'^[a-f0-9]{40}$'},'description':'검증된 설치 대상 전체 revision 하나. 조회는 fetch나 DB 검사를 하지 않습니다.'}]}, tags=['운영 설정'], summary='설치된 서버 버전의 변경 계획 조회')
    def plan(request: Request):
        gate(request)
        fields = list(request.query_params.multi_items())
        if (len(fields) != 1 or fields[0][0] != 'targetRevision'
                or not re.fullmatch(r'[a-f0-9]{40}', fields[0][1])):
            raise HTTPException(400, 'One full installed targetRevision is required')
        transition=moved()
        if transition is not None:return transition
        # A plan never fetches a ref, writes migration history, or starts a job.
        return response(exchange({'action':'plan','targetRevision':fields[0][1]}), unsupported=True)

    @router.post('/v1/operations/deployments', status_code=202, tags=['운영 설정'], summary='최신 main 또는 저장된 호환 버전 적용')
    async def start(request: Request):
        gate(request, True)
        if request.url.query:
            raise HTTPException(400, 'Query fields are not accepted')
        transition=moved()
        if transition is not None:return transition
        auth.rate('manual-deployment:' + request.state.team_identity['id'], limit=10)
        raw = bytearray()
        try:
            async with asyncio.timeout(5):
                async for chunk in request.stream():
                    raw.extend(chunk)
                    if len(raw) > 1024:
                        raise HTTPException(413, 'Request too large')
        except TimeoutError:
            raise HTTPException(408, 'Request body timeout') from None
        try:
            value = json.loads(raw)
        except (ValueError, UnicodeError):
            raise HTTPException(400, 'Invalid JSON') from None
        if (not isinstance(value,dict) or set(value)-{'requestId','retryOf','targetRevision','operation'} or 'requestId'not in value
                or not isinstance(value['requestId'],str)or not REQUEST_ID.fullmatch(value['requestId'])):
            raise HTTPException(400,'A UUID4 requestId is required')
        if 'operation' in value and value['operation'] not in ('deploy', 'engine-update'):
            raise HTTPException(400, 'Operation must be deploy or engine-update')
        if value.get('operation') == 'engine-update' and 'targetRevision' not in value:
            raise HTTPException(400, 'Engine update requires an explicit full targetRevision')
        if 'targetRevision'in value and (not isinstance(value['targetRevision'],str)or not re.fullmatch(r'[a-f0-9]{40}',value['targetRevision'])):
            raise HTTPException(400,'A full target revision is required')
        if 'retryOf' in value and (not isinstance(value['retryOf'], str) or not REQUEST_ID.fullmatch(value['retryOf'])):
            raise HTTPException(400, 'retryOf must be a UUID4')
        # Body receipt can await: revalidate session and current allowlist role now.
        gate(request, True)
        # Synchronous fixed socket I/O does not run a deployment in this API worker.
        from starlette.concurrency import run_in_threadpool
        return response(await run_in_threadpool(exchange, {'action':'start',**value}), 202, unsupported='operation' in value)

    return router
