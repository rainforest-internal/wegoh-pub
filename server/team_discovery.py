"""Explicit selected-place/GPS-consent proximity query over fixed public data.

No coordinate persistence, account-history join, downstream fetch or navigation.
Rate metadata uses the existing auth limiter; it contains no query/body/location.
"""
import asyncio,json,math
from datetime import datetime,timezone
from fastapi import APIRouter,HTTPException,Request,Response
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from rest_stop_data import DATASET
FACILITIES=('toilet','nursing','evCharger','gasStation','lpg','restSpace')
def fail(detail):raise HTTPException(400,detail)
def coordinates(value):
 for name,low,high in(('latitude',-90,90),('longitude',-180,180)):
  if type(value.get(name))not in(int,float)or not low<=value[name]<=high or not math.isfinite(value[name]):fail('Choose a valid place or location')
 return value['latitude'],value['longitude']
def anchor(value,now):
 if not isinstance(value,dict):fail('Choose a place or explicitly allow current location')
 if value.get('kind')=='selected-place'and set(value)=={'kind','place'}:
  place=value['place']
  if not isinstance(place,dict)or set(place)!={'id','provider','name','address','latitude','longitude'}:fail('Choose a place from the place picker')
  for name,maximum in(('id',240),('provider',40),('name',80),('address',200)):
   text=place[name]
   if not isinstance(text,str)or len(text)>maximum or(name!='address'and not text.strip())or any(ord(c)<32 for c in text):fail('Invalid selected place')
  lat,lon=coordinates(place);return lat,lon,dict(kind='selected-place',capturedAt=None,accuracyMeters=None)
 if value.get('kind')=='browser-location'and set(value)=={'kind','position','consent'}:
  if value['consent']is not True:fail('Explicit current-location query consent required')
  point=value['position']
  if not isinstance(point,dict)or set(point)!={'latitude','longitude','accuracyMeters','capturedAt'}:fail('Invalid browser location')
  lat,lon=coordinates(point);accuracy=point['accuracyMeters']
  if type(accuracy)not in(int,float)or not 0<=accuracy<=10000 or not math.isfinite(accuracy):fail('Invalid reported location accuracy')
  raw=point['capturedAt']
  if not isinstance(raw,str)or len(raw)>40:fail('Refresh current location')
  try:
   captured=datetime.fromisoformat(raw.replace('Z','+00:00'))
   if captured.tzinfo is None:raise ValueError()
   age=(now-captured.astimezone(timezone.utc)).total_seconds()
   if not-30<=age<=300:raise ValueError()
  except(ValueError,OverflowError):fail('Refresh current location')
  return lat,lon,dict(kind='browser-reported',capturedAt=captured.isoformat(),accuracyMeters=accuracy)
 fail('Choose a supported place or explicit browser location')
def distance(lat,lon,item):
 a,b=math.radians(lat),math.radians(item['latitude']);x=math.sin((b-a)/2)**2+math.cos(a)*math.cos(b)*math.sin(math.radians(item['longitude']-lon)/2)**2
 return 6371000*2*math.asin(min(1,math.sqrt(max(0,x))))
def query(value,now=None):
 now=now or datetime.now(timezone.utc)
 if not isinstance(value,dict)or not{'anchor'}<=set(value)or set(value)-{'anchor','requiredFacilities','radiusMeters','limit','roadFilter'}:fail('Invalid discovery fields')
 lat,lon,reported=anchor(value['anchor'],now);required=value.get('requiredFacilities',[]);radius=value.get('radiusMeters',50000);limit=value.get('limit',10);road=value.get('roadFilter',{})
 if not isinstance(required,list)or any(not isinstance(k,str)or k not in FACILITIES for k in required)or len(set(required))!=len(required):fail('Choose supported facilities')
 if type(radius)is not int or not 1<=radius<=200000 or type(limit)is not int or not 1<=limit<=20:fail('Choose a supported query radius and limit')
 if not isinstance(road,dict)or set(road)-{'routeNumber','direction'}:fail('Invalid reported road-label filter')
 if'routeNumber'in road and(not isinstance(road['routeNumber'],str)or not 1<=len(road['routeNumber'])<=20):fail('Choose a reported route number')
 if'direction'in road and road['direction']not in('up','down','both'):fail('Choose a reported road direction')
 result=[]
 for item in DATASET['items']:
  if any(item['facilities'][key]is not True for key in required):continue
  if'routeNumber'in road and item['routeNumber']!=road['routeNumber']:continue
  if'direction'in road:
   allowed={road['direction'],'both'}if road['direction']in('up','down')else{'both'}
   if item['direction']not in allowed:continue
  meters=distance(lat,lon,item)
  if meters>radius:continue
  result.append((meters,item['id'],dict(id=item['id'],place=dict(id=item['id'],provider='official-rest-snapshot',name=item['name'],address='',latitude=item['latitude'],longitude=item['longitude']),road=dict(kind=item['roadKind'],routeNumber=item['routeNumber'],routeName=item['routeName'],direction=item['direction'],reportedDirection=item['reportedDirection']),facilities=dict(item['facilities']),dataAsOf=item['dataAsOf'],foodNames=list(item['foodNames']),straightLineDistanceMeters=round(meters),routeDistanceMeters=None,travelSeconds=None,roadAccessVerified=False,currentOpen=None,chargerAvailable=None,price=None,coordinateVerifiedAt=None,ingestionNotes=list(item['ingestionNotes']))))
 result.sort(key=lambda x:(x[0],x[1]));selected=[x[2]for x in result[:limit]]
 return dict(items=selected,source={k:DATASET['source'][k]for k in('datasetId','name','publisher','catalogUrl','license','catalogModifiedAt','downloadObservedAt','csvSha256','dataAsOf','rowCount','unknownDirectionCount','foodNameCount')},basis='great-circle-straight-line',queriedAt=now.isoformat(),anchor=reported,applied=dict(requiredFacilities=required,radiusMeters=radius,limit=limit,roadFilter=road),matchedCount=len(result),hasMore=len(result)>limit,unsupported=dict(roadRouting=True,routeTime=True,countryRoadPriority=True,personalTaste=True,namedFood=True,liveAvailability=True),directionPolicy='Reported up/down filters also match both; unknown labels are excluded when a direction is selected. Labels never prove driving heading or road entry.')
def create_router(auth):
 router=APIRouter()
 if not auth.enabled:return router
 async def perform(request,response,kind):
  identity=await run_in_threadpool(auth.browser,request,mutate=True)
  await run_in_threadpool(auth.rate,'discovery-query:'+identity['id'],limit=60)
  raw=bytearray()
  try:
   async with asyncio.timeout(5):
    async for chunk in request.stream():
     raw.extend(chunk)
     if len(raw)>4096:raise HTTPException(413,'Discovery request too large')
  except TimeoutError:raise HTTPException(408,'Discovery request timed out')from None
  try:value=json.loads(raw,parse_constant=lambda _:(_ for _ in()).throw(ValueError()))
  except(ValueError,UnicodeError,RecursionError):fail('Invalid discovery JSON')
  response.headers['Cache-Control']='private, no-store'
  if kind=='rest' and isinstance(value,dict) and 'roadSearch' not in value:
   return query(value)
  from discovery_local import DiscoveryError,decode,prepare
  try:
   value=decode(raw)
   # Denials occur before engine dispatch even when local data is not configured.
   prepare(value,kind)
   local=getattr(auth,'local_discovery',None)
   if local is None:return JSONResponse(status_code=503,content={'code':'PREPARATION'},headers={'Cache-Control':'private, no-store'})
   # Body receipt may take up to five seconds. Recheck current session/account
   # immediately before transmitting the explicit anchor to the owned engine.
   current=await run_in_threadpool(auth.browser,request,mutate=True)
   if current['id']!=identity['id']:raise HTTPException(401,'Authentication changed')
   await run_in_threadpool(auth.current_account,identity['id'])
   result=await run_in_threadpool(local.query,value,kind)
   current=await run_in_threadpool(auth.browser,request,mutate=True)
   if current['id']!=identity['id']:raise HTTPException(401,'Authentication changed')
   await run_in_threadpool(auth.current_account,identity['id'])
   return result
  except DiscoveryError as error:
   raise HTTPException(error.status,error.code)from None
 @router.post('/v1/discovery/rest-stops/query')
 async def rest_stops(request:Request,response:Response):
  return await perform(request,response,'rest')
 @router.post('/v1/discovery/places/query')
 async def places(request:Request,response:Response):
  return await perform(request,response,'places')
 return router
