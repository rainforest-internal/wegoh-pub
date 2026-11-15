"""Protected OpenAPI and a same-origin, session/CSRF API explorer.

Metadata protection reuses signed Access/admin identity. Real API execution still
passes the original personal-session/Origin/CSRF/owner checks; no proxy or token UI.
"""
import copy
from pathlib import Path
from urllib.parse import urlsplit
from fastapi import APIRouter, HTTPException, Request
from fastapi.openapi.utils import get_openapi, _get_api_route_for_openapi
from fastapi.responses import FileResponse, JSONResponse
from fastapi.routing import APIRoute, iter_route_contexts
from starlette.routing import Mount
from api_doc_native_functional import RECEIVER_PATH, RECEIVER_UPDATE
from api_doc_control_support import PATH as SUPPORT_PATH, BODY as SUPPORT_BODY
from api_doc_client_reports import PATH as REPORT_PATH, BODY as REPORT_BODY
from api_doc_client_diagnostics import BODY as CLIENT_DIAGNOSTICS_BODY
from client_diagnostics import NATIVE_PATH as CLIENT_DIAGNOSTICS_PATH

def text(maximum=None, **extra):
    value={'type':'string'}
    if maximum is not None:value['maxLength']=maximum
    value.update(extra);return value
def obj(properties, required=None):
    return {'type':'object','properties':properties,'required':list(properties)if required is None else required,'additionalProperties':False}
ID=text(45,pattern='^team-[a-f0-9]{40}$')
TRACK=obj({'id':text(32,pattern='^[a-f0-9]{32}$'),'title':text(120,minLength=1),'url':text(2048,minLength=1,pattern=r'^https://[^\s]+$',description='HTTPS host required; credentials, whitespace and a non443 port are rejected.')},['title','url'])
PLAYLIST=obj({'name':text(80,minLength=1),'tracks':{'type':'array','maxItems':100,'items':TRACK}})
PLAYLIST_UPDATE=obj({**PLAYLIST['properties'],'revision':{'type':'integer','minimum':1,'maximum':2147483647}})
PLACE=obj({'name':text(80,minLength=1),'latitude':{'type':'number','minimum':-90,'maximum':90},'longitude':{'type':'number','minimum':-180,'maximum':180}})
CONSENTS=obj({k:{'type':'boolean'}for k in ('status','location','visits','music','voice','control')})
PACK_STOP=obj({'id':text(80,pattern='^[a-z0-9][a-z0-9_-]{0,79}$'),'name':text(80,minLength=1),'latitude':{'type':'number','minimum':-90,'maximum':90},'longitude':{'type':'number','minimum':-180,'maximum':180},'radiusMeters':{'type':'number','minimum':25,'maximum':500},'action':obj({'type':{'const':'chime'},'message':text(240,minLength=1)}),'poiId':text(100),'address':text(200),'place':obj({'id':text(240,minLength=1),'provider':text(40,minLength=1),'name':text(80,minLength=1),'address':text(200)})},['id','name','latitude','longitude','radiusMeters','action'])
PACK=obj({'schemaVersion':{'const':1},'id':text(80,pattern='^[a-z0-9][a-z0-9_-]{0,79}$'),'version':{'type':'integer','minimum':1,'maximum':2147483647},'title':text(100,minLength=1),'author':text(80,minLength=1),'description':text(500,minLength=1),'stops':{'type':'array','minItems':1,'maxItems':3,'items':PACK_STOP}})
PACK['description']='Text limits are also enforced in UTF16 code units by the actual pack validator; stop IDs must be unique. Coordinates belong to developer JSON contracts, not the consumer place chooser.'
PROFILE_NAME=text(30,minLength=1,description='1..30 Unicode scalars; no leading/trailing whitespace or Unicode control/format/private/surrogate/unassigned characters.')
PROFILE_UPDATE=obj({'displayName':PROFILE_NAME,'expectedDisplayName':text(64,minLength=1)})
VEHICLE_PROFILE_UPDATE=obj({'plateNumber':text(16,pattern='^$|^[0-9가-힣]{2,16}$',description='공백 없는 수동 입력 번호판. 빈 문자열은 등록 해제.'),
 'name':text(20,description='소유자가 정한 차량 이름. 0~20 Unicode scalar이며 앞뒤 공백·제어/형식 문자·줄 구분 문자는 거절합니다. 빈 문자열은 기본 이름("{계정 이름}의 차")을 따릅니다.'),
 'expectedRevision':{'type':'integer','minimum':0,'maximum':2147483647}})
BODY={
 ('put',SUPPORT_PATH):SUPPORT_BODY,
 ('post',REPORT_PATH):REPORT_BODY,
 ('post',CLIENT_DIAGNOSTICS_PATH):CLIENT_DIAGNOSTICS_BODY,
 ('put',RECEIVER_PATH):RECEIVER_UPDATE,
 ('put','/v1/profile/handle'):obj({'handle':text(21,minLength=3,pattern='^@?[A-Za-z0-9][A-Za-z0-9_.]{2,19}$'),'expectedHandle':text(21,minLength=3,pattern='^@?[A-Za-z0-9][A-Za-z0-9_.]{2,19}$')}),
 ('put','/v1/device/vehicle-profile'):VEHICLE_PROFILE_UPDATE,
 ('put','/v1/devices/{device}/vehicle-profile'):VEHICLE_PROFILE_UPDATE,
 ('put','/v1/profile'):PROFILE_UPDATE,('put','/v1/account'):PROFILE_UPDATE,
 ('post','/v1/playlists'):PLAYLIST,('put','/v1/playlists/{playlist_id}'):PLAYLIST_UPDATE,
 ('post','/v1/social/friends/requests'):obj({'targetId':ID}),
 ('post','/v1/social/friends/requests/{target}/respond'):obj({'accept':{'type':'boolean'}}),
 ('post','/v1/social/blocks'):obj({'targetId':ID}),
 ('post','/v1/packs'):obj({'pack':PACK,'rightsConfirmed':{'const':True}}),
 ('post','/v1/packs/{pack_id}/versions/{version}/reports'):obj({'reason':{'enum':['harmful','privacy','rights','other']}}),
 ('post','/v1/moderation/packs/{pack_id}/versions/{version}'):obj({'checksum':text(64,pattern='^[a-f0-9]{64}$'),'decision':{'enum':['approved','rejected']},'reviewer':text(80,minLength=1),'reviewNote':text(1000,minLength=1)}),
 ('post','/v1/devices/pairings'):obj({'name':text(64,minLength=1),'codeChallenge':text(43,pattern='^[A-Za-z0-9_-]{43}$'),'codeChallengeMethod':{'const':'S256'}}),
 ('post','/v1/devices/token'):obj({'deviceCode':text(43),'codeVerifier':text(128,minLength=43,pattern='^[A-Za-z0-9._~-]{43,128}$')}),
 ('post','/v1/devices/token/refresh'):obj({'refreshToken':text(43,pattern='^[A-Za-z0-9_-]{43}$')}),
 ('post','/v1/social/rooms'):obj({'name':text(80,minLength=1),'courseId':{'type':['string','null']},'courseVersion':{'type':['integer','null'],'minimum':1},'expiresInHours':{'type':'integer','minimum':1,'maximum':168},'preference':{'enum':['balanced','country-roads','short-distance','short-time']}},['name','courseId','courseVersion','expiresInHours']),
 ('post','/v1/social/rooms/join'):obj({'code':text(8,pattern='^[A-HJ-NP-Z2-9]{8}$'),'consents':CONSENTS}),
 ('patch','/v1/social/rooms/{room}/consents'):obj({'consents':CONSENTS}),
 ('patch','/v1/social/rooms/{room}/role'):obj({'accountId':ID,'role':{'enum':['member','dj','rest','food']}}),
 ('post','/v1/social/rooms/{room}/signals'):obj({'kind':{'enum':['restroom','smoking','nursing','drowsy','rest','hungry','cafe','ev_charge','fuel','arrived','join']},'destination':{'anyOf':[PLACE,{'type':'null'}]}},['kind']),
 ('post','/v1/social/rooms/{room}/signals/{identifier}/vote'):obj({'choice':{'enum':['agree','pass']}})
}
from api_doc_voice import BODY as VOICE_BODY
BODY.update(VOICE_BODY)
from api_doc_trips import BODY as TRIP_BODY, NO_BODY as TRIP_NO_BODY, OPTIONAL_BODY
BODY.update(TRIP_BODY)
from api_doc_trip_plan import BODY as TRIP_PLAN_BODY, NO_BODY as TRIP_PLAN_NO_BODY
BODY.update(TRIP_PLAN_BODY)
from api_doc_trip_hand_raise import BODY as TRIP_HAND_RAISE_BODY, NO_BODY as TRIP_HAND_RAISE_NO_BODY
BODY.update(TRIP_HAND_RAISE_BODY)
from api_doc_trip_merge import BODY as TRIP_MERGE_BODY, NO_BODY as TRIP_MERGE_NO_BODY
BODY.update(TRIP_MERGE_BODY)
from api_doc_recommendations import BODY as RECOMMENDATION_BODY
BODY.update(RECOMMENDATION_BODY)
from api_doc_recommendation_learning import BODY as LEARNING_BODY
BODY.update(LEARNING_BODY)
from api_doc_missions import BODY as MISSION_BODY
BODY.update(MISSION_BODY)
from api_doc_vehicle import BODY as VEHICLE_BODY
BODY.update(VEHICLE_BODY)
from api_doc_device_commands import BODY as DEVICE_COMMAND_BODY
BODY.update(DEVICE_COMMAND_BODY)
from api_doc_history_remix import BODY as HISTORY_REMIX_BODY
BODY.update(HISTORY_REMIX_BODY)
BODY[('post','/v1/packs')]['properties']['remixDraftId']=dict(type='string',pattern='^[a-f0-9]{32}$',description='서버발급 재창작 코스의 본인32hex receipt. 일반게시에는생략하지만예약된재창작ID는생략으로권리검사를우회할수없습니다.')
BODY[('post','/v1/packs')]['properties']['tags']=dict(type='array',maxItems=8,
    items=text(description='태그당 1~24자. 맨 앞 #은 생략할 수 있습니다.'),
    description='선택 사항. 이 게시 버전의 공개 태그로, 차량 원문 JSON에는 포함하지 않습니다.')
COURSE_PUBLICATION_BODY=BODY[('post','/v1/packs')]
COURSE_PUBLICATION_BODY['properties'].update(
    coverImage=text(163840,minLength=1,contentEncoding='base64',contentMediaType='image/jpeg',
        description='선택 사항. data URL 접두어가 없는 Base64 JPEG. 디코딩한 입력은 최대 120 KiB이며 처리 후 긴 변은 최대 960픽셀입니다.'),
    copyCoverFromVersion={'type':'integer','minimum':1,'maximum':2147483646,
        'description':'선택 사항. 같은 코스에 속한 본인의 이전 게시 버전 번호. 새 버전 번호보다 작아야 하며 해당 버전에 대표 이미지가 있어야 합니다.'})
COURSE_PUBLICATION_BODY['not']={'required':['coverImage','copyCoverFromVersion']}

from api_doc_cautions import BODY as CAUTION_BODY
BODY.update(CAUTION_BODY)
from api_doc_manual_deployment import REQUEST as MANUAL_DEPLOYMENT_REQUEST
BODY[('post','/v1/operations/deployments')]=MANUAL_DEPLOYMENT_REQUEST


# Explicit history contracts; caller-supplied vehicle/GPS proof is never accepted.
REVISION={'type':'integer','minimum':1,'maximum':2147483647}
TIME=text(40,format='date-time',description='Explicit timezone required; actual server rejects a future time beyond its permitted skew.')
HISTORY=obj({'title':text(100,minLength=1),'startedAt':TIME,'endedAt':{'anyOf':[TIME,{'type':'null'}]},'courseId':{'type':['string','null'],'maxLength':80,'pattern':'^[a-z0-9][a-z0-9_-]{0,79}$'},'courseVersion':{'type':['integer','null'],'minimum':1,'maximum':2147483647}})
VISIT=obj({'revision':REVISION,'place':PLACE,'visitedAt':TIME,'review':text(1000),'rating':{'type':['integer','null'],'minimum':1,'maximum':5}})
POINT=obj({'latitude':PLACE['properties']['latitude'],'longitude':PLACE['properties']['longitude'],'capturedAt':TIME,'accuracyMeters':{'type':['number','null'],'minimum':0,'maximum':10000}})
BODY.update({
 ('post','/v1/social/history'):HISTORY,
 ('put','/v1/social/history/{item}'):obj({**HISTORY['properties'],'revision':REVISION}),
 ('post','/v1/social/rooms/{room}/history'):obj({'title':text(100,minLength=1)}),
 ('patch','/v1/social/history/{item}/permissions'):obj({'permissionRevision':REVISION,'collectTrace':{'type':'boolean'}}),
 ('put','/v1/social/history/{item}/shares/{target}'):obj({'permissionRevision':REVISION,'visits':{'type':'boolean'},'trace':{'type':'boolean'}}),
 ('post','/v1/social/history/{item}/visits'):VISIT,
 ('put','/v1/social/history/{item}/visits/{vid}'):VISIT,
 ('delete','/v1/social/history/{item}/visits/{vid}'):obj({'revision':REVISION}),
 ('post','/v1/social/history/{item}/trace-batches'):obj({'revision':REVISION,'batchId':text(32,pattern='^[a-f0-9]{32}$'),'streamId':text(32,pattern='^[a-f0-9]{32}$'),'label':text(64,minLength=1),'points':{'type':'array','minItems':1,'maxItems':200,'items':POINT,'description':'Strict increasing timestamps; browser-reported provenance only, not a native vehicle/GPS attestation. Actual consent and revision checks remain authoritative.'}})
})
BODY[('put','/v1/devices/{device}/permissions')]=obj({'revision':{'type':'integer','minimum':1},'permissions':obj({name:{'type':'boolean','default':False}for name in ('friends','rooms','history')})})
BODY[('put','/v1/social/history/{item}/shares/{target}')]['properties']['photos']={'type':'boolean','default':False,'description':'Separate explicit photo purpose; requires visits=true, omission is false.'}
BODY[('delete','/v1/social/history/{item}/visits/{visit}/photos/{photo}')]=obj({'revision':REVISION})
CONTENT_REPORT=obj({'reason':{'enum':['harmful','privacy','rights','other']}})
CONTENT_DECISION=obj({'checksum':text(64,pattern='^[a-f0-9]{64}$'),'decision':{'enum':['approved','rejected']},'reviewer':text(80,minLength=1),'reviewNote':text(1000,minLength=1)})
BODY.update({
 ('post','/v1/moderation/content/{kind}/{key}'):CONTENT_DECISION,
 ('patch','/v1/social/history/{item}/review-request'):obj({'revision':REVISION,'consent':{'type':'boolean','default':False}}),
 ('patch','/v1/social/rooms/{room}/review-request'):obj({'consent':{'type':'boolean','default':False}}),
 ('patch','/v1/social/rooms/{room}/signals/{identifier}/review-request'):obj({'consent':{'type':'boolean','default':False}}),
 ('patch','/v1/social/history/{item}/visits/{visit}/photos/{photo}/review-request'):obj({'revision':REVISION,'consent':{'type':'boolean','default':False}}),
 ('post','/v1/social/history/{item}/reports'):CONTENT_REPORT,
 ('post','/v1/social/rooms/{room}/reports'):obj({'reason':CONTENT_REPORT['properties']['reason'],'code':text(8,pattern='^[A-HJ-NP-Z2-9]{8}$')},['reason']),
 ('post','/v1/social/rooms/{room}/signals/{identifier}/reports'):CONTENT_REPORT,
 ('post','/v1/social/history/{item}/visits/{visit}/photos/{photo}/reports'):CONTENT_REPORT
})
# External-file consent is a distinct purpose; internal grants never imply it.
BODY.update({
 ('put','/v1/social/history/{item}/export-permissions/{target}'):obj({'revision':{'type':'integer','minimum':0,'maximum':2147483646},'historyRevision':REVISION,'consent':{'type':'boolean','default':False,'description':'Explicit permission to create an externally shared file; already saved copies cannot be recalled.'},'visits':{'type':'boolean','default':False},'trace':{'type':'boolean','default':False},'photos':{'type':'boolean','default':False,'description':'Requires visits; still intersects current approved photo/internal-photo permission.'},'expiresAt':text(40,format='date-time',description='Future expiry at most 24 hours. Data/permission/review changes invalidate this exact consent.')}),
 ('post','/v1/social/story-manifests'):obj({'historyIds':{'type':'array','minItems':1,'maxItems':5,'uniqueItems':True,'items':text(32,pattern='^[a-f0-9]{32}$')}})
})
BODY[('put','/v1/social/history/{item}/export-permissions/{target}')]['properties']['consent']={'const':True,'description':'Explicit owner consent is required; revoke through DELETE, never false PUT.'}
BODY[('post','/v1/social/rooms')]['properties']['preference']['default']='balanced'
from api_doc_discovery import BODY as DISCOVERY_QUERY
BODY[('post','/v1/discovery/rest-stops/query')]=DISCOVERY_QUERY
from api_doc_discovery_local import BODY as LOCAL_DISCOVERY_BODY
BODY.update(LOCAL_DISCOVERY_BODY)
from api_doc_fuel import BODY as FUEL_BODY
BODY.update(FUEL_BODY)
# Local compatibility contracts remain documented but never executable here.
BODY[('post','/v1/local/packs/{pack_id}/versions/{version}/reports')]=obj({'reason':CONTENT_REPORT['properties']['reason'],'checksum':text(64,pattern='^[a-f0-9]{64}$')})
LEGACY_PLACE=obj({'id':text(240,minLength=1),'provider':text(40,minLength=1),'name':text(80,minLength=1),'address':text(200),'latitude':PLACE['properties']['latitude'],'longitude':PLACE['properties']['longitude']})
BODY[('post','/v1/local/visits')]=obj({'consent':{'const':True},'visits':{'type':'array','maxItems':100,'items':obj({'id':text(80,pattern='^[a-zA-Z0-9_-]{1,80}$'),'place':LEGACY_PLACE,'visitedAt':{'type':'integer','minimum':1,'maximum':253402300799999}})}})
BODY.update({
 ('put','/v1/social/rooms/{room}/voice/filters/{speaker}'):obj({'muted':{'type':'boolean'}}),
 ('post','/v1/social/rooms/{room}/voice/reports'):obj({'speakerId':ID,'leaseId':text(32,pattern='^[a-f0-9]{32}$'),'reason':{'enum':['harmful','privacy','rights','other']}}),
 ('post','/v1/moderation/voice-reports/{identifier}/resolve'):obj({'decision':{'enum':['restore','retain'],'description':'restore는 이 신고를 해결하며 다른 미해결 신고가 없을 때만 새 발화를 허용합니다. retain은 미해결 제한을 유지/재개방합니다. 음성 원본 검수나 자동 송신을 뜻하지 않습니다.'}})
})
MUSIC_REV={'type':'integer','minimum':0,'maximum':2147483647,'description':'현재 GET room music의 선택 revision. 최초 빈 상태0.'}
MUSIC_ID=text(32,pattern='^[a-f0-9]{32}$')
BODY.update({
 ('put','/v1/social/rooms/{room}/music'):obj({'revision':MUSIC_REV,'playlistId':dict(MUSIC_ID,description='본인 GET playlists의 선택 목록ID.'),'playlistRevision':dict(REVISION,description='선택 목록의 현재 revision.'),'trackId':dict(MUSIC_ID,description='그 목록 안의 곡ID.'),'rightsConfirmed':{'const':True,'description':'목록/곡 metadata·링크 공유권리를 별도로 확인합니다. 검토 동의와 다릅니다.'}}),
 ('delete','/v1/social/rooms/{room}/music'):obj({'revision':MUSIC_REV}),
 ('patch','/v1/social/rooms/{room}/music/review-request'):obj({'revision':MUSIC_REV,'consent':{'type':'boolean','default':False,'description':'운영자에게 음악 metadata를 검토 제출할 별도 명시동의. false는철회.'}}),
 ('post','/v1/social/rooms/{room}/music/reports'):obj({'selectionId':dict(MUSIC_ID,description='현재 수신한 music.selection.id.'),'reason':CONTENT_REPORT['properties']['reason']}),
 ('post','/v1/social/rooms/{room}/music/playlist'):obj({'title':text(120,minLength=1),'artist':text(80,minLength=1,description='공유할 곡의 아티스트 이름. 제목·원곡 링크와 함께 검토합니다.'),'url':TRACK['properties']['url'],'rightsConfirmed':{'const':True}}),
 ('patch','/v1/social/rooms/{room}/music/playlist/{track}/review-request'):obj({'consent':{'type':'boolean','default':False}}),
 ('post','/v1/social/rooms/{room}/music/playlist/{track}/reports'):obj({'reason':CONTENT_REPORT['properties']['reason']}),
 ('put','/v1/devices/{device}/music-permission'):obj({'revision':dict(REVISION,description='이 기기의 별도 음악 목적 revision, 최초1.'),'enabled':{'const':True,'description':'이 기기에 동의한 방 음악metadata를 보여줄 명시동의. 기본false, 철회는DELETE.'}})
})
from route_preview import ROUTE_REQUEST_SCHEMA
BODY[('post','/v1/routes/preview')]=ROUTE_REQUEST_SCHEMA
from api_doc_course_discovery import BODY as COURSE_DISCOVERY_BODY
BODY.update(COURSE_DISCOVERY_BODY)
from api_doc_core import NO_BODY as CORE_NO_BODY

NO_BODY={('post','/v1/auth/session'),('delete','/v1/auth/session')} | CORE_NO_BODY | TRIP_NO_BODY | TRIP_MERGE_NO_BODY | TRIP_PLAN_NO_BODY | TRIP_HAND_RAISE_NO_BODY
ERROR={'description':'The actual server enforces identity, owner, Origin/CSRF, consent, availability and bounds.','content':{'application/json':{'schema':obj({'detail':{'type':'string'}})}}}

from native_access_policy import is_authorization_path, is_retired_authorization_path, ROUTES, RESOURCE_SCOPES, MANDATORY_SCOPES
BODY={key:value for key,value in BODY.items() if not is_retired_authorization_path(key[1])}

def build_schema(app,auth):
    from api_doc_trip_merge import FEATURE_OPS
    from api_doc_catalog import OPERATIONS
    features = getattr(auth, 'trip_feature_routes', {})
    for feature, operations in FEATURE_OPS.items():
        for key in operations:
            OPERATIONS.pop(key, None)
        if features.get(feature):
            OPERATIONS.update(operations)
    routes=[];seen=set()
    # Pinned FastAPI includes lazy _IncludedRouter objects; use its own effective-route adapter.
    for context in iter_route_contexts(app.routes):
        route=_get_api_route_for_openapi(context)
        if route is None:continue
        if route.path.startswith('/v2/'):raise RuntimeError('Retired public v2 route remains registered')
        if not route.path.startswith('/v1/'):continue
        methods=set(route.methods)-{'HEAD','OPTIONS'};fresh={m for m in methods if (route.path,m)not in seen}
        if not fresh:continue
        if fresh!=methods:raise RuntimeError('Partially duplicated route methods need an explicit schema decision')
        routes.append(context);seen.update((route.path,m)for m in fresh)
    # The isolated issuer contributes only the single current authorization contract.
    authorization=getattr(auth,'native_authorization',None)
    if authorization and authorization.enabled:
        routes.extend(iter_route_contexts(authorization.issuer_router().routes))
    schema=get_openapi(title='WegoH API',version=app.version,openapi_version='3.1.0',routes=routes)
    native_paths={path:operations for path,operations in schema['paths'].items() if is_authorization_path(path)}
    schema['paths']={path:operations for path,operations in schema['paths'].items() if not is_authorization_path(path)}
    if any(is_retired_authorization_path(path) for path in schema['paths']):raise RuntimeError('Retired authorization route remains registered')
    schema['servers']=[{'url':auth.public_origin}]
    schema['info']['description']='Protected team API contracts. Browser requests use Access plus personal session/Origin/CSRF. Native device requests use their separate hostname and personal PKCE grant. Secrets are never embedded. Real API responses are authoritative.'
    schema.setdefault('components',{})['securitySchemes']={
      'CloudflareAccess':{'type':'apiKey','in':'cookie','name':'CF_Authorization','description':'Browser Access sign-in; edge assertion is verified against exact issuer/audience and active team allowlist.'},
      'TeamSession':{'type':'apiKey','in':'cookie','name':'__Host-wegoh_team','description':'Secure HttpOnly personal four-hour session; mutation also requires exact Origin and X-WegoH-CSRF from current session status.'},
      'CurrentSessionCSRF':{'type':'apiKey','in':'header','name':'X-WegoH-CSRF','description':'Swagger UI supplies the fresh personal-session value automatically in memory for unsafe browser requests. Server validation remains required.'},
      'NativeMTLS':{'type':'mutualTLS','description':'TLS1.3 personal per-device client certificate. The exact native host edge requires verified, non-revoked mTLS and Managed Transform Add TLS client auth headers. Origin matches its trusted SHA256 to pairing/device encrypted state; client must not set CF certificate headers. Certificate ownership requires fresh explicit account consent; no manual pairing token is supported.'},
      'DeviceBearer':{'type':'http','scheme':'bearer','description':'Opaque personal device credential bound to the same per-device mTLS certificate used for the explicit browser-approved connection. Access15min, refresh rotates within the original grant lifetime; missing/changed certificate or revoked token denies. Not a server key.'}}
    for path,operations in schema['paths'].items():
        for method,operation in operations.items():
            if method not in ('get','post','put','patch','delete'):continue
            native=path.startswith('/v1/device/requests/')or path in ('/v1/device/command-inbox',RECEIVER_PATH,SUPPORT_PATH,REPORT_PATH)or path in ('/v1/account','/v1/device','/v1/device/vehicle-profile','/v1/device/permissions','/v1/device/music-permission','/v1/device/vehicle-domain','/v1/devices/pairings','/v1/devices/token','/v1/devices/token/refresh')or path.startswith('/v1/native/')
            legacy=path.startswith('/v1/local/')or path.startswith('/v1/studio/session')or path.startswith('/v1/assets')or path.startswith('/v1/app/')
            executable=not native and not legacy
            operation['x-wegoh-executable']=bool(executable and (not path.startswith('/v1/devices/pairings/') or auth.native_origin))
            operation['x-wegoh-surface']='native'if native else 'operator-or-local'if legacy else 'browser'
            operation['security']=[{'NativeMTLS':[],'DeviceBearer':[]}]if native else [{'CloudflareAccess':[],'TeamSession':[]}]
            if path=='/v1/auth/session'and method in ('get','post'):operation['security']=[{'CloudflareAccess':[]}]
            if native:
                operation['servers']=[{'url':auth.native_origin,'description':'Separate device host; external availability requires operator verification.'}] if auth.native_origin else []
                operation['x-wegoh-configured']=bool(auth.native_origin)
                if path in ('/v1/devices/pairings','/v1/devices/token','/v1/devices/token/refresh'):operation['security']=[{'NativeMTLS':[]}]
            if (method,path)in BODY:operation['requestBody']={'required':(method,path)not in OPTIONAL_BODY,'content':{'application/json':{'schema':copy.deepcopy(BODY[(method,path)])}}}
            elif method in ('post','put','patch')and (method,path)not in NO_BODY and not path.endswith('/approve')and not path.endswith('/leave'):
                operation['x-wegoh-executable']=False
                operation['x-wegoh-body-contract']='No inferred body; explicit schema review is required before explorer execution.'
            photo_upload=path=='/v1/social/history/{item}/visits/{visit}/photos'and method=='post'
            photo_content=path=='/v1/social/history/{item}/visits/{visit}/photos/{photo}'and method=='get'
            if photo_upload:
                operation['requestBody']={'required':True,'content':{kind:{'schema':{'type':'string','format':'binary','maxLength':3145728}}for kind in ('image/jpeg','image/png')}}
                operation.setdefault('parameters',[]).extend([{'name':'X-WegoH-Rights-Confirmed','in':'header','required':True,'schema':{'const':'true'},'description':'Explicit user confirmation of rights, not a marketplace/legal review.'},{'name':'X-WegoH-History-Revision','in':'header','required':True,'schema':{'type':'integer','minimum':1,'maximum':2147483647},'description':'Current parent history revision. Rechecked after bounded image processing.'}])
            if photo_upload:
                operation['parameters'].append({'name':'X-WegoH-Review-Requested','in':'header','required':False,'schema':{'type':'string','enum':['true','false'],'default':'false'},'description':'Separate explicit operator photo-review purpose. Missing/false stays private; rights confirmation is not this consent.'})
            if method=='get' and path in ('/v1/social/trips/{id}', '/v1/native/trips/{id}'):
                from api_doc_trip_sections import apply_sections
                apply_sections(operation, native=path.startswith('/v1/native/'))
            if photo_content:
                operation['responses']['200']={'description':'Current separately authorized photograph; private,no-store, sanitized JPEG.','content':{'image/jpeg':{'schema':{'type':'string','format':'binary'}}}}
            content_media=path=='/v1/moderation/content/{kind}/{key}/media'and method=='get'
            if content_media:
                operation['responses']['200']={'description':'Only the currently submitted photo projection image, never an unrequested private photo.','content':{'image/jpeg':{'schema':{'type':'string','format':'binary'}}}}
            story_media=path=='/v1/social/story-manifests/{key}/photos/{item}/{visit}/{photo}'and method=='get'
            if story_media:
                operation['responses']['200']={'description':'Current manifest-owned and separately export-authorized sanitized JPEG. No-store.','content':{'image/jpeg':{'schema':{'type':'string','format':'binary'}}}}
            if path=='/v1/social/history/{item}/export-permissions'and method=='get':
                operation['responses']['200']={'description':'Current account-scoped external-export permissions and authoritative server time.','content':{'application/json':{'schema':{'type':'object','required':['historyId','historyRevision','permissions','serverNow'],'properties':{'historyId':text(32,pattern='^[a-f0-9]{32}$'),'historyRevision':{'type':'integer','minimum':1},'permissions':{'type':'array','items':{'type':'object','properties':{'exporterId':copy.deepcopy(ID),'revision':{'type':'integer','minimum':1},'consent':{'type':'boolean'},'visits':{'type':'boolean'},'trace':{'type':'boolean'},'photos':{'type':'boolean'},'expiresAt':{'type':'string','format':'date-time'},'historyRevision':{'type':'integer','minimum':1},'active':{'type':'boolean'}}}},'serverNow':{'type':'string','format':'date-time'}}}}}}
            if '/voice/' in path or path.startswith('/v1/moderation/voice-reports'):
                operation['x-wegoh-native-access']=False
                operation['description']=operation.get('description','')+' Live voice is browser-only and requires current individual room voice consent. Filters affect only this receiver. Reports retain no audio/transcript; delivered-lease metadata can stop a speaker but does not classify speech or prove prior content safety. Administrator resolution uses the original personal admin session and CSRF.'
            if path.startswith('/v1/recommendations/'):
                operation['x-wegoh-native-access']=False
            if '/remix' in path or '/reuse-permission' in path:
                operation['x-wegoh-native-access']=False
            if '/export-permissions' in path or path.startswith('/v1/social/story-manifests'):
                operation['x-wegoh-native-access']=False
                operation['description']=operation.get('description','')+' Separate explicit external-file consent, current participants/internal grants/content approval and expiry are required. A manifest is not a completed media file. Revalidate before sharing; saved copies cannot be recalled. First/last 200m are excluded and discontinuities retain segment identifiers.'
            if photo_upload or photo_content or content_media or story_media:
                operation['x-wegoh-executable']=False
                operation['x-wegoh-body-contract']='Raw image transfer uses the actual photograph UI. The JSON explorer does not convert, upload or text-dump binary images.'
                operation['x-wegoh-native-access']=False
            if path=='/v1/moderation/content'and method=='get':
                operation.setdefault('parameters',[]).append({'name':'cursor','in':'query','required':False,'schema':text(256),'description':'Use preceding nextCursor;100 metadata subjects at most, inspect one projection on demand.'})
            if path.startswith('/v1/moderation/content/'):
                for parameter in operation.get('parameters',[]):
                    if parameter.get('name')=='kind':parameter['schema']={'type':'string','enum':['history','room','room-place','photo','room-music']}
            if path=='/v1/social/history'and method=='get':
                operation.setdefault('parameters',[]).append({'name':'cursor','in':'query','required':False,'schema':text(256,pattern='^[A-Za-z0-9_-]+$'),'description':'Use the actual preceding nextCursor;50-record keyset page.'})
            if method in ('post','put','patch','delete')and executable and not(path=='/v1/auth/session'and method=='post'):
                for requirement in operation['security']:
                    if 'CloudflareAccess'in requirement:requirement['CurrentSessionCSRF']=[]
            for code in ('400','401','403','404','409','413','429','503'):operation['responses'].setdefault(code,copy.deepcopy(ERROR))
    from team_event_versions import CHAT_PROTOCOL, PROTOCOL as EVENTS_PROTOCOL
    schema['x-wegoh-events']={'versionedProtocol':{'subprotocol':EVENTS_PROTOCOL,'messages':{'snapshot':['type','epoch','seq','versions'],'invalidate':['type','epoch','seq','versions'],'heartbeat':['type','epoch','seq']},'versionValue':'opaque 32hex; null removes a key in invalidate only','authorityResource':'devices','tripSections':['detail','route','signals','music','location','voice'],'withoutSubprotocol':'Without Sec-WebSocket-Protocol the same feed sends sorted resource names (resources) instead of opaque versions.'},'path':'/v1/events','transport':'WSS','messages':['snapshot','invalidate','heartbeat'],'authority':'Re-read currently scoped REST; notifications never contain personal data or credentials.','hosts':{'browser':'Exact public host, same Origin, signed Access and personal session cookie.','native':'Separate native host, same-certificate mTLS and Authorization Bearer; Origin header and the chat subprotocol are denied.','other':'Any other host closes 1008 before accept.'},'credentialsInUrlOrSubprotocol':False,'clientMessages':[],'limits':{'concurrentConnectionsPerAccount':16,'opensPerAccountPerMinute':30,'revalidationSeconds':1,'heartbeatSeconds':20,'nativeReconnectSeconds':getattr(auth,'native_socket_seconds',60)},'closeCodes':{'1008':'Rejected before accept (host, Origin, credentials, rate or connection limit), any client message after accept, or a native connection reaching nativeReconnectSeconds (reconnect through the edge).','4003':'Account, role, grant, credential epoch, slot or visible resources changed, connection lease expired, or authorization denied after accept.','1011':'Database/storage failure or send timeout after accept.'},'nativePurposes':{'requiredScopes':sorted(MANDATORY_SCOPES),'resourceScopes':dict(RESOURCE_SCOPES),'authority':'Same-certificate mTLS AND current opaque Bearer, exact grant/slot/epoch. Scope reduction or revocation closes the channel; optional unapproved resources are absent.'}}
    schema['x-wegoh-events']['chatBrowserProtocol'] = dict(subprotocol=CHAT_PROTOCOL, additionalTripSection='chat',
        authority='Same browser authentication and version frames. Only accepted participants receive an opaque chat version.')
    from team_voice import FORMAT,LEASE_SECONDS,RELAY_QUEUE_LIMIT,FRAME_RATE_PER_SECOND,FRAME_RATE_BURST,FRAME_RATE_WINDOW_LIMIT,FRAME_INTERVAL_SECONDS
    schema['x-wegoh-voice']={'path':'/v1/social/rooms/{room}/voice','transport':'WSS','available':bool(getattr(auth,'voice_service',None)and auth.voice_service.enabled),'nativeAccess':False,'singleWorkerRequired':True,'pcm':dict(FORMAT),'leaseSeconds':LEASE_SECONDS,'automaticTransmit':False,'clientMessages':['floor-request','floor-release','stop','ping'],'serverMessages':['ready','floor-granted','floor-started','floor-busy','floor-ended','pong'],'limits':{'recipientQueueFrames':RELAY_QUEUE_LIMIT,'framesPerSecond':int(FRAME_RATE_PER_SECOND),'burstCapacityFrames':int(FRAME_RATE_BURST),'burstRefillFramesPerSecond':int(FRAME_RATE_PER_SECOND),'framesPerRollingSecond':FRAME_RATE_WINDOW_LIMIT,'deliveryIntervalMilliseconds':int(FRAME_INTERVAL_SECONDS*1000),'controlBytes':1024,'controlMessagesPerSecond':10,'idleAuthorizationMilliseconds':250,'connectionsPerAccount':2,'connectionsPerRoom':10,'connectionsPerTrip':40,'opensPerAccountPerMinute':20},'closeCodes':{'1000':'Client stop message.','1008':'Authorization, consent, membership, frame/control format, sequence, size or rate rejection.','1013':'Recipient queue full or delivery timeout; reconnect after the network recovers.'},'authority':'Browser: exact public browser host/Origin, signed Access and personal session. iPhone (/v1/iphone/trips/{trip}/voice): iPhone session with trips:read. Native: see native. Every transport then requires current membership/expiry/block and separate voice consent (room) or trip voice participation (trip). Binary frames belong only to the current floor-started lease/speaker; each new lease starts sequence0. Stop/revoke/mute discard owned unsent/replay queues; already handed-off network audio cannot be recalled. Native AudioFocus/Suspend/driving and physical audibility are not verified by browser transport success. No raw audio or transcript is stored.'}
    from api_doc_catalog import apply_documentation
    schema=apply_documentation(schema, BODY)
    # Only the two already allowlisted public course GETs have this dual host contract.
    # Apply after catalogue descriptions so the Native/Try conditions remain visible.
    for path in ('/v1/packs','/v1/packs/{pack_id}/versions/{version}'):
        operation=schema['paths'][path]['get']
        operation['security']=[{'CloudflareAccess':[]}]
        operation['servers']=[{'url':auth.public_origin,'description':'Browser Access edge. This GET handler does not itself require a WegoH session.'}]
        operation['x-wegoh-native-configured']=bool(auth.native_origin)
        operation['x-wegoh-native-read-only']=True
        if auth.native_origin:
            operation['security'].append({'NativeMTLS':[],'DeviceBearer':[]})
            operation['servers'].append({'url':auth.native_origin,'description':'TLS1.3 personal mTLS AND same-certificate opaque device Bearer; no browser Access cookie, shared service token, or client-supplied CF certificate headers.'})
        operation['description']+=' Native 앱은 설정된 별도 호스트에서 같은 개인 인증서에 결합된 opaque 기기 Bearer를 함께 사용합니다. Native origin이 미설정이면 이 대안은 닫힙니다. Swagger Try it out은 현재 웹 호스트와 로그인한 개인 세션에서만 실행되며 Native 호스트 요청은 차단됩니다. 개발용 /v1/assets는 Native에서 지원하지 않으며 서버 API_KEY는 개인 기기 token이 아닙니다. 운영 key를 앱이나 Swagger에 입력하지 마세요. 코스 JSON은 chime만 포함하며 미디어 첨부 URI를 생성하지 않습니다.'
    import re
    canonical=lambda path:re.sub(r'\{[^}]+\}','{}',path)
    allowed={(rule.method.lower(),canonical(rule.template)):rule.scope for rule in ROUTES}
    for path,operations in schema['paths'].items():
        for method,operation in operations.items():
            if method not in ('get','post','put','patch','delete'):continue
            scope=allowed.get((method,canonical(path)))
            operation['x-wegoh-native-access']=scope is not None
            if scope is None:continue
            operation['x-wegoh-native-required-scope']=scope
            if path.startswith('/v1/native/courses/'):
                operation['security']=[{'NativeMTLS':[],'DeviceBearer':[]}]
                operation['servers']=[{'url':auth.native_origin}] if auth.native_origin else []
                operation['x-wegoh-native-configured']=bool(auth.native_origin)
                operation['x-wegoh-native-read-only']=True
                operation['x-wegoh-executable']=False
                continue
            if path in ('/v1/account','/v1/device','/v1/device/permissions'):continue
            operation['x-wegoh-native-configured']=bool(auth.native_origin)
            if auth.native_origin:
                requirement={'NativeMTLS':[],'DeviceBearer':[]}
                if requirement not in operation.get('security',[]):operation.setdefault('security',[]).append(requirement)
                servers=operation.setdefault('servers',[{'url':auth.public_origin}])
                if not any(server['url']==auth.native_origin for server in servers):servers.append({'url':auth.native_origin,'description':'Current explicitly approved native scope; same-certificate mTLS AND Bearer.'})
    schema['paths'].update(native_paths)
    from api_doc_native_access import apply_native_access_documentation
    from api_doc_native_functional import apply_native_functional_documentation
    from api_doc_native_room_music import apply_room_music_documentation
    from api_doc_native_domains import apply_native_domain_documentation
    from api_doc_social import apply_native_social_documentation
    from api_doc_native_room_voice import apply_room_voice_documentation
    from api_doc_finalization import finalize_documentation
    from api_doc_iphone import apply_iphone_documentation
    from api_doc_reviewer import apply_reviewer_documentation
    return apply_reviewer_documentation(apply_iphone_documentation(finalize_documentation(apply_room_voice_documentation(apply_native_social_documentation(apply_native_domain_documentation(apply_room_music_documentation(apply_native_functional_documentation(apply_native_access_documentation(schema,auth),auth),auth),auth),auth),auth)),auth,app),auth,app)

def install_api_docs(app,auth,web):
    router=APIRouter();web=Path(web)
    def gate(request):
        if not auth.enabled or request.url.hostname!=urlsplit(auth.public_origin).hostname:raise HTTPException(404)
        identity=getattr(request.state,'team_identity',None)
        if not identity:raise HTTPException(401,'Authentication required')
        if identity['role']!='admin':raise HTTPException(403,'Action not permitted')
    @router.get('/openapi.json',include_in_schema=False)
    @router.get('/developer/openapi.json',include_in_schema=False)
    def specification(request:Request):
        gate(request);return JSONResponse(build_schema(app,auth),headers={'Cache-Control':'private, no-store'})
    @router.get('/api-docs',include_in_schema=False)
    @router.get('/api-docs.html',include_in_schema=False)
    @router.get('/developer/docs',include_in_schema=False)
    def explorer(request:Request):
        gate(request);return FileResponse(web/'api-docs.html',headers={'Cache-Control':'private, no-store'})
    # Base app's final '/' StaticFiles mount otherwise shadows newly added routes.
    index=next((i for i,route in enumerate(app.router.routes)if isinstance(route,Mount)and route.path in ('','/')),len(app.router.routes))
    app.router.routes[index:index]=router.routes
