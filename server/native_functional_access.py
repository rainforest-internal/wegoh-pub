"""Explicit functional consent bound to the one current native identity."""
import os
from fastapi import APIRouter,HTTPException,Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from private_records import VisitCipher
from psycopg.rows import dict_row
from native_principal import is_native_principal
from native_functional_policy import FunctionalError,WIRE,PURPOSES,MAX_REVISION,identifier,decode_consent,stored_functional_payload,validate_snapshot
from native_functional_defaults import ACCOUNT_PURPOSES, account_purposes, ensure_receive_default
from native_command_receiver import RECEIVE, command_receiver
from native_device_reference import register_native,require_native_reference
from team_data import changed

def fail(status,code):raise FunctionalError(status,code)
class NativeFunctionalAccess:
 def __init__(self,base,enabled=None):
  self.base,self.auth=base,base.auth
  self.enabled=os.environ.get('WEGOH_NATIVE_FUNCTIONAL_ENABLED','0')=='1'if enabled is None else enabled
 def require_enabled(self):
  if not self.enabled or not self.base.enabled:fail(404,'ROUTE_NOT_FOUND')
 def owner_grant(self,conn,owner,device):
  identifier(device);grant=self.base._owned_lock(conn,owner,device)
  if not grant:fail(404,'DEVICE_UNAVAILABLE')
  from native_authorization import NativeAuthorizationError
  try:self.base._live(grant,connection=conn)
  except NativeAuthorizationError:fail(404,'DEVICE_UNAVAILABLE')
  with conn.cursor(row_factory=dict_row)as cursor:
   install=cursor.execute('SELECT * FROM native_v2_installations WHERE installation_key_id=%s',(grant['installation_key_id'],)).fetchone()
  if grant['state']!='TOKEN_ISSUED'or not install or install['revoked_at']is not None or install['active_grant_id']!=grant['grant_id']:fail(404,'DEVICE_UNAVAILABLE')
  require_native_reference(conn,device)
  return grant,install
 def row(self,conn,grant,lock=False):
  return conn.execute('SELECT * FROM native_functional_authorizations WHERE grant_id=%s'+(' FOR UPDATE'if lock else''),(grant['grant_id'],)).fetchone()
 payload=staticmethod(stored_functional_payload)
 def approved_disclosure_version(self,conn,grant):
  row=self.row(conn,grant)
  if not row or row['state']!='ACTIVE'or min(row['expires_at'],grant['expires_at'])<=self.base.now():return None
  return self.payload(row)['functionalDisclosureVersion']
 def snapshot(self,conn,grant):
  ensure_receive_default(conn,grant)
  row=self.row(conn,grant);approved=[];revision=0;expiry=grant['expires_at']
  if row:
   if row['installation_key_id']!=grant['installation_key_id']or row['device_id']!=grant['device_id']:fail(503,'FUNCTIONAL_STATE_INVALID')
   revision=row['revision'];expiry=min(expiry,row['expires_at'])
   if row['state']=='ACTIVE'and expiry>self.base.now():approved=sorted(account_purposes(self.payload(row)['approvedPurposes']))
  return validate_snapshot(dict(authorizationVersion=1,deviceId=grant['device_id'],grantId=grant['grant_id'],revision=revision,expiresAt=expiry,approvedPurposes=approved,functionalDisclosureVersion=WIRE['disclosureVersion'],functionalDisclosureSha256=WIRE['disclosureSha256']))
 def write(self,conn,grant,value,*,explicit_disclosure=True):
  ensure_receive_default(conn,grant)
  row=self.row(conn,grant,True);revision=row['revision']if row else 0
  if value['grantId']!=grant['grant_id']:fail(409,'DEVICE_BINDING_CHANGED')
  if value['revision']!=revision:fail(409,'FUNCTIONAL_REVISION_CHANGED')
  register_native(conn,grant)
  payload={k:value[k]for k in ['approvedPurposes','functionalDisclosureVersion','functionalDisclosureSha256']}
  stored=self.payload(row) if row['protected'] is not None else {}
  if not explicit_disclosure:
   for key in ('functionalDisclosureVersion','functionalDisclosureSha256'):payload[key]=stored[key]
  previous=frozenset(stored.get('approvedPurposes',[]))
  active=row['state']=='ACTIVE' and row['expires_at']>self.base.now()
  requested=frozenset(value['approvedPurposes'])
  if (active and RECEIVE in previous)!=(RECEIVE in requested):fail(403,'RECEIVER_VEHICLE_ONLY')
  saved=(requested-ACCOUNT_PURPOSES)|(previous&ACCOUNT_PURPOSES)
  if active and saved==previous and all(payload[key]==stored.get(key) for key in ('functionalDisclosureVersion','functionalDisclosureSha256')):return self.snapshot(conn,grant)
  if revision>=MAX_REVISION:fail(409,'FUNCTIONAL_REVISION_EXHAUSTED')
  payload['approvedPurposes']=sorted(saved)
  if 'receiverRevision' in stored:payload['receiverRevision']=stored['receiverRevision']
  removed=previous-saved
  # Explicit fresh consent cannot revive expired room shares or retained cache.
  if row and(row['state']!='ACTIVE'or row['expires_at']<=self.base.now()):removed|=previous
  if removed:
   from native_functional_withdrawal import withdraw_report_effects
   withdraw_report_effects(conn,self.auth,grant['account_id'],grant['device_id'],removed)
  protected=VisitCipher().protect('native-functional',grant['grant_id'],payload)
  conn.execute("INSERT INTO native_functional_authorizations(grant_id,device_id,installation_key_id,revision,state,protected,expires_at)VALUES(%s,%s,%s,%s,'ACTIVE',%s,%s)ON CONFLICT(grant_id)DO UPDATE SET revision=excluded.revision,state=excluded.state,protected=excluded.protected,expires_at=excluded.expires_at",(grant['grant_id'],grant['device_id'],grant['installation_key_id'],revision+1,protected,grant['expires_at']))
  voice=getattr(self.auth,'voice_service',None)
  if voice:voice.invalidate_native(grant['account_id'],grant['device_id'])
  changed(conn,grant['account_id'],'devices')
  return self.snapshot(conn,grant)
 def owned_get(self,owner,device):
  self.require_enabled()
  with self.base.db()as conn:grant,_=self.owner_grant(conn,owner,device);return self.snapshot(conn,grant)
 def owned_put(self,owner,device,raw,request=None):
  self.require_enabled()
  with self.base.db()as conn:
   if request is not None and self.auth.browser(request,mutate=True,connection=conn)['id']!=owner:fail(401,'AUTHENTICATION_CHANGED')
   value=decode_consent(raw);grant,_=self.owner_grant(conn,owner,device);return self.write(conn,grant,value)
 def owned_delete(self,owner,device,purpose,request=None):
  self.require_enabled()
  if purpose not in PURPOSES:fail(404,'FUNCTIONAL_PURPOSE_UNAVAILABLE')
  with self.base.db()as conn:
   if request is not None and self.auth.browser(request,mutate=True,connection=conn)['id']!=owner:fail(401,'AUTHENTICATION_CHANGED')
   grant,_=self.owner_grant(conn,owner,device);snapshot=self.snapshot(conn,grant)
   if purpose==RECEIVE:fail(403,'RECEIVER_VEHICLE_ONLY')
   if purpose in ACCOUNT_PURPOSES or purpose not in snapshot['approvedPurposes']:return snapshot
   value={k:v for k,v in snapshot.items()if k not in ['deviceId','expiresAt']};value['approvedPurposes']=[p for p in value['approvedPurposes']if p!=purpose]
   return self.write(conn,grant,value,explicit_disclosure=False)
 def native_get(self,request,*,include_approval=False):
  self.require_enabled();identity=self.auth.device(request)
  if not is_native_principal(identity):fail(401,'INVALID_CREDENTIAL')
  with self.base.db()as conn:
   grant,install=self.owner_grant(conn,identity['id'],identity['deviceId'])
   if identity['grantId']!=grant['grant_id']or identity['credentialEpoch']!=grant['credential_epoch']or identity['slotRevision']!=install['slot_revision']:fail(401,'INVALID_CREDENTIAL')
   snapshot=self.snapshot(conn,grant)
   return (snapshot,self.approved_disclosure_version(conn,grant)) if include_approval else snapshot
 def native_get_response(self,request):
  from native_functional_presentation import presentation_version,present_snapshot
  version=presentation_version(request)
  if version>=4:
   snapshot,approved=self.native_get(request,include_approval=True)
   return present_snapshot(snapshot,version,approved_disclosure_version=approved)
  return present_snapshot(self.native_get(request),version)
 def router(self):
  router=APIRouter();service=self
  async def request_body(request):
   from native_authorization import NativeAuthorizationError,read_body
   try:return await read_body(request)
   except NativeAuthorizationError as error:raise HTTPException(error.status,error.code) from None
  def output(call):
   try:return JSONResponse(call(),headers={'Cache-Control':'private, no-store'})
   except FunctionalError as error:return JSONResponse(dict(authorizationVersion=1,error=error.code),status_code=error.status,headers={'Cache-Control':'no-store'})
  @router.get('/v1/device/functional-permissions')
  def native_get(request:Request):return output(lambda:service.native_get_response(request))
  @router.get('/v1/device/command-receiver')
  def receiver_get(request:Request):return output(lambda:command_receiver(service,request))
  @router.put('/v1/device/command-receiver')
  async def receiver_put(request:Request):
   raw=await request_body(request)
   return await run_in_threadpool(output,lambda:command_receiver(service,request,raw))
  @router.put('/v1/device/control-support')
  async def support_put(request:Request):
   from vehicle_control_support import report_support
   raw=await request_body(request)
   return await run_in_threadpool(output,lambda:report_support(service,request,raw))
  @router.get('/v1/devices/{device}/functional-permissions')
  def owner_get(device:str,request:Request):return output(lambda:service.owned_get(service.auth.browser(request)['id'],device))
  @router.put('/v1/devices/{device}/functional-permissions')
  async def owner_put(device:str,request:Request):
   owner=service.auth.browser(request,mutate=True)['id'];raw=await request_body(request)
   return await run_in_threadpool(output,lambda:service.owned_put(owner,device,raw,request))
  @router.delete('/v1/devices/{device}/functional-permissions/{purpose}')
  def owner_delete(device:str,purpose:str,request:Request):return output(lambda:service.owned_delete(service.auth.browser(request,mutate=True)['id'],device,purpose,request))
  from iphone_functional_permissions import register_iphone_functional_routes
  register_iphone_functional_routes(router,service)
  return router
