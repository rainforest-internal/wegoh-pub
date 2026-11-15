"""Closed nonsecret selectors for declared Native reads, never query credentials."""
import base64,binascii,json,re
from datetime import datetime

HISTORY='/v1/social/history'
CAUTIONS='/v1/social/cautions'
VEHICLE='/v1/device/vehicle-domain'
VOICE_ROOMS='/v1/native/voice-rooms'
def history_cursor(value):
 if type(value)is not str or not 1<=len(value)<=256 or re.fullmatch(r'[A-Za-z0-9_-]+',value)is None:raise ValueError('Invalid record cursor')
 def pairs(items):
  out={}
  for key,item in items:
   if key in out:raise ValueError('Duplicate cursor field')
   out[key]=item
  return out
 try:
  raw=base64.b64decode(value+'='*((-len(value))%4),altchars=b'-_',validate=True)
  cursor=json.loads(raw.decode('utf-8'),object_pairs_hook=pairs)
  if type(cursor)is not dict or set(cursor)!={'updatedAt','id'} or type(cursor['id'])is not str or re.fullmatch(r'[a-f0-9]{32}',cursor['id'])is None:raise ValueError()
  if type(cursor['updatedAt'])is not str or not 1<=len(cursor['updatedAt'])<=40:raise ValueError()
  moment=datetime.fromisoformat(cursor['updatedAt'])
  if moment.tzinfo is None or moment.utcoffset()is None:raise ValueError()
 except(ValueError,TypeError,KeyError,UnicodeError,binascii.Error,RecursionError):raise ValueError('Invalid record cursor')from None
 return moment,cursor['id']

def native_query_allowed(request):
 if not request.url.query:return True
 if request.scope.get('type')!='http':return False
 if request.method!='GET':return False
 items=list(request.query_params.multi_items())
 if request.url.path=='/v1/native/courses/library':
  return (len(items)<=9 and all(key in ('q','tag') for key,_ in items)
   and sum(key=='q' for key,_ in items)<=1 and sum(key=='tag' for key,_ in items)<=8
   and all(len(value)<=100 if key=='q' else 1<=len(value)<=25 for key,value in items))
 if len(items)!=1:return False
 key,value=items[0]
 if re.fullmatch(r'/v1/native/trips/[a-f0-9]{32}',request.url.path):return key=='section'and value in ('route','location')
 if re.fullmatch(r'/v1/social/trips/[a-f0-9]{32}/voice-clips',request.url.path):return key=='cursor'and re.fullmatch(r'[a-f0-9]{32}:(0|[1-9][0-9]{0,15})',value)is not None
 if request.url.path==VOICE_ROOMS:return key=='cursor'and re.fullmatch(r'[a-f0-9]{32}',value)is not None
 if request.url.path==VEHICLE:return key=='roomId'and re.fullmatch(r'[a-f0-9]{32}',value)is not None
 if request.url.path=='/v1/device/command-inbox':return key=='view'and value in ('active','status')
 if request.url.path not in(HISTORY,CAUTIONS) or key!='cursor':return False
 try:history_cursor(items[0][1])
 except ValueError:return False
 return True
