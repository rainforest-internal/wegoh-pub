"""Exact functional-purpose contracts; this policy never authenticates an actor."""
import hashlib,json,re
from pathlib import Path
from native_access_codec import decode_json,CodecError
WIRE=json.loads((Path(__file__).parent/'native_access_wire.json').read_text())['functional']
PURPOSES=frozenset(row['id'] for row in WIRE['purposeRegistry'])
MAX_REVISION=WIRE['revisionMaximum']
ID=re.compile(r'[a-f0-9]{32}')
class FunctionalError(ValueError):
 def __init__(self,status,code):self.status,self.code=status,code;super().__init__(code)
def fail(status=400,code='INVALID_FUNCTIONAL_REQUEST'):raise FunctionalError(status,code)
def revision(value,zero=True):
 if type(value)is not int or not (0 if zero else 1)<=value<=MAX_REVISION:fail()
 return value
def identifier(value):
 if type(value)is not str or not ID.fullmatch(value):fail()
 return value
def purposes(value):
 if type(value)is not list or len(value)>len(PURPOSES)or any(type(x)is not str for x in value)or value!=sorted(set(value))or not set(value)<=PURPOSES:fail()
 return value
def decode_consent(value):
 if type(value)is bytes:
  try:value=decode_json(value,maximum_bytes=12288)
  except CodecError:fail()
 expected=set(WIRE['apis']['ownerPut']['requestFields'])
 if type(value)is not dict or set(value)!=expected:fail()
 if type(value['authorizationVersion'])is not int or value['authorizationVersion']!=1:fail()
 identifier(value['grantId']);revision(value['revision']);purposes(value['approvedPurposes'])
 if type(value['functionalDisclosureVersion'])is not int or value['functionalDisclosureVersion']!=WIRE['disclosureVersion']or value['functionalDisclosureSha256']!=WIRE['disclosureSha256']:fail(409,'FUNCTIONAL_DISCLOSURE_CHANGED')
 return dict(value)
def decode_stored_consent(value):
 if type(value)is not dict:fail(503,'FUNCTIONAL_STATE_INVALID')
 stored=dict(value)
 if type(stored.get('functionalDisclosureVersion'))is int and any(stored.get('functionalDisclosureVersion')==old['version']and stored.get('functionalDisclosureSha256')==old['sha256']for old in WIRE.get('previousDisclosures',[])):
  stored.update(functionalDisclosureVersion=WIRE['disclosureVersion'],functionalDisclosureSha256=WIRE['disclosureSha256'])
 return decode_consent(stored)

def stored_functional_payload(row):
 from private_records import VisitCipher
 value=VisitCipher().restore('native-functional',row['grant_id'],row['protected'])
 if type(value)is not dict:fail(503,'FUNCTIONAL_STATE_INVALID')
 consent=dict(value)
 try:
  revision(consent.pop('receiverRevision',1),zero=False)
  if 'receiverSupport' in consent:
   from vehicle_control_support import stored_support
   try:stored_support(consent.pop('receiverSupport'))
   except FunctionalError:
    # A receiver report is a 90-second input hint that never grants authority.
    # One that no longer parses (e.g. stored before a format change) counts as
    # no report rather than failing every read of the grant's consent.
    value=dict(value);del value['receiverSupport']
  decode_stored_consent(dict(consent,authorizationVersion=1,grantId=row['grant_id'],revision=row['revision']))
  if set(consent)!={'approvedPurposes','functionalDisclosureVersion','functionalDisclosureSha256'}:fail()
 except FunctionalError:fail(503,'FUNCTIONAL_STATE_INVALID')
 return value
def validate_snapshot(value):
 expected=set(WIRE['apis']['nativeGet']['responseFields'])
 if type(value)is not dict or set(value)!=expected:fail(503,'FUNCTIONAL_STATE_INVALID')
 decode_consent({k:v for k,v in value.items()if k not in ['deviceId','expiresAt']})
 identifier(value['deviceId'])
 if type(value['expiresAt'])is not int or value['expiresAt']<0:fail(503,'FUNCTIONAL_STATE_INVALID')
 return dict(value)
def _pattern(template):
 # Domain identifiers retain their actual public type, not a uniform token size.
 types={'accountId':r'team-[a-f0-9]{40}','packId':r'[a-z0-9][a-z0-9_-]{0,79}','target':r'team-[a-f0-9]{40}','code':r'[A-HJ-NP-Z2-9]{8}'}
 types.update({key:r'[a-f0-9]{32}'for key in ('room','identifier','item','visit','photo','vid','mission','device','id','trip','signal','carId','placeId','inviteId')})
 parts=re.split(r'(\{[a-zA-Z_]+\})',template)
 return ''.join(types[part[1:-1]]if part.startswith('{')and part.endswith('}')else re.escape(part)for part in parts)
RULES=tuple((r['method'],re.compile(_pattern(r['path'])),frozenset(r['all']),frozenset(r['any']))for r in WIRE['nativeRoutes'])
def authorize(method,path,approved):
 if not isinstance(approved,frozenset)or not approved<=PURPOSES:fail(403,'FUNCTIONAL_PURPOSE_REQUIRED')
 for verb,pattern,all_of,any_of in RULES:
  if verb==method and pattern.fullmatch(path):
   if not all_of<=approved or any_of and not any_of&approved:fail(403,'FUNCTIONAL_PURPOSE_REQUIRED')
   return True
 fail(404,'ROUTE_NOT_FOUND')

def is_functional_route(method,path):
 return type(method)is str and type(path)is str and any(verb==method and pattern.fullmatch(path) for verb,pattern,_,_ in RULES)


def authorize_socket(path, approved):
 if not isinstance(approved,frozenset)or not approved<=PURPOSES:fail(403,'FUNCTIONAL_PURPOSE_REQUIRED')
 for rule in WIRE.get('nativeWebSockets',[]):
  if re.fullmatch(_pattern(rule['path']),path):
   if not set(rule['all'])<=approved or rule['any']and not set(rule['any'])&approved:fail(403,'FUNCTIONAL_PURPOSE_REQUIRED')
   return rule
 fail(404,'ROUTE_NOT_FOUND')
