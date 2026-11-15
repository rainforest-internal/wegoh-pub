"""Revalidate current native authority inside the actual business transaction.

No credentials are minted here. A reference row, role or request body is never
an identity. Callers keep this transaction through the domain read/write; room
and bilateral domain checks remain mandatory after this exact purpose gate.
"""
from native_functional_query import native_query_allowed
import re
from dataclasses import dataclass
from datetime import datetime,timezone
from psycopg.rows import dict_row
from private_records import VisitCipher
from native_principal import NativePrincipal,is_native_principal
from native_authorization import hash_secret
from native_access_policy import valid_grant_scopes
from native_functional_policy import FunctionalError,authorize,decode_consent,stored_functional_payload,revision,identifier
from vehicle_names import vehicle_name


def fail(status,code):raise FunctionalError(status,code)


class VoiceDefaultRequired(Exception):
 """Retry under the exclusive graph lock before creating a default."""

def _account_member(auth,owner,protected):
 saved=VisitCipher().restore('team-account:'+owner,'identity',protected)
 # Same rule as vehicle connection: the explicit roster plus self-enrolled reviewer domains.
 member=auth.vehicle_member(saved)
 if not member:fail(403,'CONSENT_REVOKED')
 return saved,member


def _current_account(auth,cursor,owner):
 row=cursor.execute('SELECT protected FROM team_accounts WHERE account_id=%s FOR SHARE',(owner,)).fetchone()
 if not row:fail(401,'INVALID_CREDENTIAL')
 saved,_=_account_member(auth,owner,row['protected'])
 return saved


_FUNCTIONAL_COLUMNS=('grant_id','device_id','installation_key_id','state','revision','protected','expires_at')


def _voice_account_and_functional_row(auth,grant):
 owner=grant['account_id']
 saved,member=_account_member(auth,owner,grant.pop('account_protected'))
 account=dict(id=owner,displayName=saved.get('displayName',member['name']),role=member['role'],
              handle=grant.pop('account_handle'))
 row={field:grant.pop('functional_'+field) for field in _FUNCTIONAL_COLUMNS}
 return account,row if row['grant_id'] is not None else None

def _scope_check(grant):
 consent=VisitCipher().restore('native-v2:consent',grant['grant_id'],grant['protected_consent'])
 try:valid_grant_scopes(frozenset(consent['scopes']))
 except (ValueError,KeyError,TypeError):fail(403,'SCOPE_DENIED')
 return consent


def _functional_snapshot(cursor,grant,now,*,row=None):
 from native_functional_defaults import account_purposes, ensure_receive_default
 if not row:
  row=cursor.execute('SELECT * FROM native_functional_authorizations WHERE grant_id=%s FOR SHARE',(grant['grant_id'],)).fetchone()
 if not row:
  ensure_receive_default(cursor,grant)
  row=cursor.execute('SELECT * FROM native_functional_authorizations WHERE grant_id=%s FOR SHARE',(grant['grant_id'],)).fetchone()
 if not row:return dict(revision=0,approvedPurposes=frozenset(),expiresAt=grant['expires_at'])
 if (row['device_id']!=grant['device_id'] or row['installation_key_id']!=grant['installation_key_id']
     or row['expires_at']>grant['expires_at']):fail(503,'FUNCTIONAL_STATE_INVALID')
 if row['state']!='ACTIVE'or row['expires_at']<=now:return dict(revision=row['revision'],approvedPurposes=frozenset(),expiresAt=min(row['expires_at'],grant['expires_at']))
 value=stored_functional_payload(row)
 return dict(revision=row['revision'],approvedPurposes=account_purposes(value['approvedPurposes']),expiresAt=row['expires_at'])


def _revalidate_principal(auth,request,conn,*,include_grant=False,voice_socket=False,graph_locked=False,read_only=False):
 """No authority may outlive this transaction's row locks and live rechecks."""
 if conn.autocommit:fail(503,'FUNCTIONAL_TRANSACTION_REQUIRED')
 service=getattr(auth,'functional_access',None)
 if service is None:fail(404,'ROUTE_NOT_FOUND')
 service.require_enabled()
 principal=getattr(request.state,'device_identity',None)
 if not voice_socket and not is_native_principal(principal):fail(401,'INVALID_CREDENTIAL')
 fingerprint=auth.native_certificate(request)
 header=request.headers.get('authorization','')
 if len(request.headers.getlist('authorization'))!=1 or re.fullmatch(r'Bearer [A-Za-z0-9_-]{43}',header)is None or not native_query_allowed(request) or any(key in request.headers for key in ('origin','cookie')):fail(401,'INVALID_CREDENTIAL')
 # Shared graph ordering precedes the authority rows and domain pair/room rows.
 # Consent mutation/cleanup must use the same order before joining this module.
 rooms=getattr(auth,'room_service',None)
 if rooms and not graph_locked:rooms.graph_lock(conn)
 access_hash=hash_secret('access',header[7:])
 if voice_socket:
  handle='NULL' if auth.enrollment_only else 'a.handle'
  active='' if auth.enrollment_only else " AND a.account_status='active'"
  projection=',a.protected AS account_protected,'+handle+' AS account_handle,'+','.join(
   'f.'+column+' AS functional_'+column for column in _FUNCTIONAL_COLUMNS)
  authority_rows=('JOIN team_accounts a ON a.account_id=g.account_id'+active+' '
   'LEFT JOIN LATERAL (SELECT * FROM native_functional_authorizations '
   'WHERE grant_id=g.grant_id FOR SHARE) f ON true ')
  grant_lock='FOR SHARE OF g,i,c,x,a' if read_only else 'FOR UPDATE OF g FOR SHARE OF i,c,x,a'
  binding='WHERE c.access_hash=%s '+grant_lock
  args=(access_hash,)
 else:
  projection=authority_rows=''
  binding='WHERE g.grant_id=%s AND g.account_id=%s AND g.device_id=%s AND c.access_hash=%s FOR SHARE OF g,i,c,x'
  args=(principal['grantId'],principal['id'],principal['deviceId'],access_hash)
 with conn.cursor(row_factory=dict_row)as cursor:
  grant=cursor.execute("SELECT g.*,i.active_grant_id,i.slot_revision AS current_slot,i.revoked_at AS installation_revoked,"
   "i.current_generation,c.certificate_sha256 AS credential_certificate,c.generation AS credential_generation,"
   "c.slot_revision AS credential_slot,c.credential_epoch AS token_epoch,c.access_expires_at,"
   "x.certificate_sha256 AS current_certificate,x.expires_at AS certificate_expiry"+projection+" "
   "FROM native_v2_grants g JOIN native_v2_installations i USING(installation_key_id) "
   "JOIN native_v2_credentials c ON c.grant_id=g.grant_id "
   "JOIN native_v2_certificates x ON x.installation_key_id=i.installation_key_id AND x.generation=i.current_generation "
   "JOIN native_device_refs r ON r.device_id=g.device_id AND r.kind='native' "+authority_rows+binding,args).fetchone()
  now=service.base.now()
  if not grant or (grant['state']!='TOKEN_ISSUED' or grant['expires_at']<=now or grant['installation_revoked']is not None
   or grant['active_grant_id']!=grant['grant_id'] or grant['credential_certificate']!=fingerprint
   or grant['current_certificate']!=fingerprint or grant['certificate_expiry']<=now
   or grant['credential_generation']!=grant['current_generation'] or grant['token_epoch']!=grant['credential_epoch']
   or grant['credential_slot']!=grant['current_slot'] or grant['access_expires_at']<=now):fail(401,'INVALID_CREDENTIAL')
  if not voice_socket and (principal['credentialEpoch']!=grant['credential_epoch']
   or principal['slotRevision']!=grant['current_slot']):fail(401,'INVALID_CREDENTIAL')
  if voice_socket:
   account,functional_row=_voice_account_and_functional_row(auth,grant)
   consent=_scope_check(grant)
   if read_only and functional_row is None:raise VoiceDefaultRequired
   principal=NativePrincipal(account,deviceId=grant['device_id'],authorizationVersion=1,grantId=grant['grant_id'],
    scopes=consent['scopes'],keepSignedIn=consent['keepSignedIn'],consentVersion=grant['consent_version'],
    grantExpiresAt=grant['expires_at'],credentialEpoch=grant['credential_epoch'],slotRevision=grant['current_slot'])
  else:
   _current_account(auth,cursor,grant['account_id']);_scope_check(grant)
   functional_row=None
  snapshot=_functional_snapshot(cursor,grant,now,row=functional_row)
  return (principal,snapshot,grant) if include_grant else (principal,snapshot)


def revalidate_native(auth,request,conn,*,functional_revision=None):
 principal,snapshot=_revalidate_principal(auth,request,conn)
 if request.method not in ('GET','HEAD'):
  revision(functional_revision,zero=False)
  if functional_revision!=snapshot['revision']:fail(409,'FUNCTIONAL_REVISION_CHANGED')
 authorize(request.method,request.url.path,snapshot['approvedPurposes'])
 return principal,snapshot


def revalidate_socket(auth,socket,conn,*,functional_revision,include_grant=False,graph_locked=False,read_only=False):
 from native_functional_policy import authorize_socket
 if socket.scope.get('type')!='websocket' or socket.url.query or socket.headers.get('sec-websocket-protocol'):fail(403,'INVALID_VOICE_SOCKET')
 result=_revalidate_principal(auth,socket,conn,include_grant=include_grant,voice_socket=True,
                              graph_locked=graph_locked,read_only=read_only)
 principal,snapshot=result[:2]
 revision(functional_revision,zero=False)
 if functional_revision!=snapshot['revision']:fail(409,'FUNCTIONAL_REVISION_CHANGED')
 authorize_socket(socket.url.path,snapshot['approvedPurposes'])
 return result


def functional_body(value):
 """Remove only the required functional CAS field before the domain decoder.

 This does not validate the domain DTO or authenticate its owner. Unknown and
 duplicate fields must still be rejected by the original canonical decoder.
 """
 if type(value)is not dict or 'functionalRevision'not in value:fail(400,'INVALID_FUNCTIONAL_REQUEST')
 expected=revision(value['functionalRevision'],zero=False)
 return {key:item for key,item in value.items()if key!='functionalRevision'},expected


@dataclass(frozen=True)
class CurrentDeviceReference:
 """Internal current-device projection, not an identity or bearer credential."""
 owner:str
 device_id:str
 grant_id:str
 installation_key_id:str
 name:str
 expires_at:datetime
 functional_revision:int
 approved_purposes:frozenset


def resolve_current_device(auth,conn,owner,device,*,required=frozenset()):
 """Resolve an already authenticated owner's target; never infer legacy rights.

 Browser/native caller identity and bilateral room/command/mission consent are
 still checked by the caller. The seven reparented FK references alone prove
 neither ownership nor a current slot nor a functional purpose.
 """
 identifier(device)
 if conn.autocommit:fail(503,'FUNCTIONAL_TRANSACTION_REQUIRED')
 service=getattr(auth,'functional_access',None)
 if service is None:fail(404,'ROUTE_NOT_FOUND')
 service.require_enabled()
 with conn.cursor(row_factory=dict_row)as cursor:
  grant=cursor.execute("SELECT g.* FROM native_v2_grants g JOIN native_v2_installations i USING(installation_key_id) "
   "JOIN native_device_refs r ON r.device_id=g.device_id AND r.kind='native' "
   "WHERE g.account_id=%s AND g.device_id=%s AND g.state='TOKEN_ISSUED' AND i.active_grant_id=g.grant_id "
   "AND i.revoked_at IS NULL FOR SHARE OF g,i",(owner,device)).fetchone()
  now=service.base.now()
  if not grant or grant['expires_at']<=now:fail(404,'DEVICE_UNAVAILABLE')
  saved=_current_account(auth,cursor,owner);_scope_check(grant)
  row=cursor.execute('SELECT state FROM native_functional_authorizations WHERE grant_id=%s FOR SHARE',(grant['grant_id'],)).fetchone()
  snapshot=_functional_snapshot(cursor,grant,now)
  if not isinstance(required,frozenset)or not required<=snapshot['approvedPurposes']:fail(403,'FUNCTIONAL_PURPOSE_REQUIRED')
  return CurrentDeviceReference(owner=owner,device_id=device,grant_id=grant['grant_id'],installation_key_id=grant['installation_key_id'],name=vehicle_name(auth,saved,grant['installation_key_id']),expires_at=datetime.fromtimestamp(min(grant['expires_at'],snapshot['expiresAt']),timezone.utc),functional_revision=snapshot['revision'],approved_purposes=snapshot['approvedPurposes'])


# These helpers are for the following business slice, not mounted by foundation.
def request_actor(auth,request,*,mutate=False):
 from fastapi import HTTPException
 principal=getattr(request.state,'device_identity',None)
 if principal is not None:
  if not is_native_principal(principal):raise HTTPException(401,'INVALID_CREDENTIAL')
  identity=auth.device(request)
 else:identity=auth.browser(request,mutate=mutate)
 request.state.business_account_id=identity['id']
 return identity


def transaction_actor(auth,request,conn,*,mutate=False):
 from fastapi import HTTPException
 if is_native_principal(getattr(request.state,'device_identity',None)):
  try:principal,snapshot=revalidate_native(auth,request,conn,functional_revision=getattr(request.state,'functional_revision',None))
  except FunctionalError as error:raise HTTPException(error.status,error.code)from None
  # Projection-only, request-local snapshot. Never reused to authorize a later
  # request or commit; the authority rows stay locked through this transaction.
  request.state.functional_snapshot=snapshot
  return principal
 identity=auth.browser(request,mutate=mutate,connection=conn)
 if getattr(request.state,'business_account_id',identity['id'])!=identity['id']:raise HTTPException(401,'AUTHENTICATION_CHANGED')
 return identity


def business_json(request,raw,*,maximum):
 from fastapi import HTTPException
 import json,math
 # Authorization wire bodies stay capped at64KiB in their own codec. Business
 # DTOs retain their existing domain bound (history allows256KiB), with the
 # same duplicate-key/nonfinite rejection before the closed field decoder.
 def pairs(items):
  result={}
  for key,item in items:
   if key in result:raise ValueError()
   result[key]=item
  return result
 def invalid(_):raise ValueError()
 def finite(text):
  value=float(text)
  if not math.isfinite(value):raise ValueError()
  return value
 try:
  if type(raw)not in(bytes,bytearray)or type(maximum)is not int or not 1<=maximum<=262144 or not 1<=len(raw)<=maximum:raise ValueError()
  value=json.loads(bytes(raw).decode('utf-8'),object_pairs_hook=pairs,parse_constant=invalid,parse_float=finite)
  if type(value)is not dict:raise ValueError()
 except(ValueError,TypeError,UnicodeError,RecursionError):raise HTTPException(400,'Invalid JSON')from None
 if is_native_principal(getattr(request.state,'device_identity',None)):
  try:value,expected=functional_body(value)
  except FunctionalError as error:raise HTTPException(error.status,error.code)from None
  request.state.functional_revision=expected
 return value
