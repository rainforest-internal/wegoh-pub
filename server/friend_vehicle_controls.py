"""Vehicle controls explicitly granted to a passenger for one trip."""
import datetime as dt
import secrets
import psycopg
from fastapi import APIRouter,Request,HTTPException
from team_device_commands import body,revision,event,fail,iso,ID,TERMINAL
from team_friends import linked
from team_data import changed
from native_functional_identity import resolve_current_device
from native_functional_policy import FunctionalError
from native_principal import is_native_principal

class FriendVehicleControls:
 def __init__(self,commands):self.commands=commands;self.auth=commands.auth;self.dsn=commands.dsn
 def actor(self,conn,request,mutate=False):
  from native_functional_identity import request_actor,transaction_actor
  if request.url.path.startswith('/v1/iphone/'):
   if request.url.query:fail(400,'IPHONE_INVALID_REQUEST')
   self.auth.iphone_sessions.authenticate(request,'trips:manage'if mutate else'trips:read')
   return self.auth.iphone_sessions.authenticate(request,'trips:manage'if mutate else'trips:read',connection=conn,lock=mutate)
  request_actor(self.auth,request,mutate=mutate)
  return transaction_actor(self.auth,request,conn,mutate=mutate)
 def friendship(self,conn,owner,peer):
  if owner==peer or not linked(conn,owner,peer):fail(403,'Current friendship required')
  self.auth.current_account(owner);self.auth.current_account(peer)
 def device(self,conn,owner,device,required=False):
  try:return resolve_current_device(self.auth,conn,owner,device,required=frozenset({'device-commands:receive'})if required else frozenset())
  except FunctionalError as error:fail(error.status,error.code)
 def trip_grant(self, conn, trip, device, peer):
  from team_trip_remote_policy import policy_car
  found = policy_car(self, conn, trip, peer)
  if found is None:
   return None, None
  car, owner, policy, revision, binding = found
  if not policy['enabled'] or policy['deviceId'] != device:
   return None, None
  reference = self.device(conn, owner, device, True)
  if reference.grant_id != binding:
   return None, None
  actions = [dict(id=item['id'], revision=item['revision']) for item in self.options() if item['id'] in policy['actions']]
  if not actions:
   return None, None
  return owner, dict(carId=car, deviceId=device, grantId=reference.grant_id, actions=actions, revision=revision)

 def context(self, conn, device, peer, owner, expected=None, action=None, *, trip=None, states=('active',)):
  trip = trip or (expected.get('tripId') if expected else None)
  if not trip:
   fail(403, 'Current trip remote permission required')
  trip_snapshot = self.trip_context(conn, trip, peer, owner, states=states)
  self.friendship(conn, owner, peer)
  saved_owner, grant = self.trip_grant(conn, trip, device, peer)
  if saved_owner != owner or grant is None or grant['carId'] != trip_snapshot['carId']:
   fail(403, 'Current trip remote permission required')
  reference = self.device(conn, owner, device, True)
  if grant['grantId'] != reference.grant_id:
   fail(403, 'Current trip remote permission required')
  if action and action not in grant['actions']:
   fail(403, 'Control not permitted')
  snapshot = dict(tripRemote=True, grantRevision=grant['revision'], grantId=reference.grant_id,
                  functionalRevision=reference.functional_revision, **trip_snapshot)
  if expected is not None and expected != snapshot:
   fail(409, 'Remote permission changed')
  return snapshot, reference.expires_at

 def trip_context(self,conn,trip,peer,owner,*,states=('active',)):
  from team_trip_context import resolve_trip_context
  context=resolve_trip_context(self.auth,conn,trip,peer,states=states)
  resolve_trip_context(self.auth,conn,trip,owner,states=states)
  row=conn.execute('SELECT c.car_id FROM team_trip_riders r JOIN team_trip_cars c USING(trip_id,car_id) '
   'WHERE r.trip_id=%s AND r.account_id=%s AND c.driver_id=%s',(trip,peer,owner)).fetchone()
  if not row:fail(403,'Current trip car assignment required')
  joined=dict(conn.execute('SELECT account_id,joined_at FROM team_room_members WHERE room_id=%s '
   'AND account_id=ANY(%s) AND left_at IS NULL',(context['roomId'],[peer,owner])).fetchall())
  if peer not in joined or owner not in joined:fail()
  return dict(tripId=trip,carId=row[0],requesterJoinedAt=iso(joined[peer]),ownerJoinedAt=iso(joined[owner]))

 def withdraw_trip_grants(self, conn, *, trip=None, car=None, peer=None, owner=None, device=None):
  conditions, args = [], []
  for column, value in (('trip_id', trip), ('car_id', car), ('requester_id', peer), ('driver_id', owner), ('device_id', device)):
   if value is not None:
    conditions.append(column + '=%s')
    args.append(value)
  if not conditions:
   raise ValueError('A trip grant selector is required')
  filters, query_args = [], []
  for column, value in (('requester_id', peer), ('owner_id', owner), ('device_id', device)):
   if value is not None:
    filters.append(column + '=%s');query_args.append(value)
  if trip is not None:
   filters.append('owner_id IN (SELECT driver_id FROM team_trip_cars WHERE trip_id=%s' + (' AND car_id=%s)' if car is not None else ')'))
   query_args.append(trip)
   if car is not None:query_args.append(car)
  rows = conn.execute('SELECT request_id,protected FROM friend_vehicle_commands' +
      (' WHERE ' + ' AND '.join(filters) if filters else '') + ' FOR UPDATE', query_args).fetchall()
  cancelled = 0
  for identifier, raw in rows:
   saved = self.commands.restore('request', identifier, raw)
   context = saved.get('context', {})
   if (not context.get('tripRemote') or (trip is not None and context.get('tripId') != trip)
       or (car is not None and context.get('carId') != car)):
    continue
   if saved['stage'] in ('queued', 'delivered', 'received', 'sdk-accepted'):
    self.commands.terminalize(saved, 'trip-context-withdrawn')
    self.commands.save_request(conn, identifier, saved)
    self.commands.invalidate_receiver(conn, saved['targetDeviceId'])
    self.commands.notify(conn, saved['requesterId'], saved['ownerId'])
    cancelled += 1
  grants = conn.execute('DELETE FROM team_trip_remote_grants WHERE ' + ' AND '.join(conditions) +
      ' RETURNING trip_id,requester_id,driver_id,device_id', args).fetchall()
  for trip_id, requester, driver, device_id in grants:
   rows = conn.execute('SELECT request_id,protected FROM friend_vehicle_commands WHERE '
       'device_id=%s AND requester_id=%s AND owner_id=%s FOR UPDATE', (device_id, requester, driver))
   self.cancel_trip_commands(conn, trip_id, rows.fetchall())
   self.notify(conn, driver, requester, device_id)
  return len(grants) + cancelled

 def cancel_trip_commands(self, conn, trip, rows):
  for identifier, raw in rows:
   value = self.commands.restore('request', identifier, raw)
   if value.get('context', {}).get('tripId') != trip or value['stage'] not in ('queued', 'delivered', 'received', 'sdk-accepted'):
    continue
   self.commands.terminalize(value, 'trip-context-withdrawn')
   self.commands.save_request(conn, identifier, value)
   self.commands.invalidate_receiver(conn, value['targetDeviceId'])
   self.commands.notify(conn, value['requesterId'], value['ownerId'])
 def withdraw_trip_context(self,conn,trip,room,account=None):
  query='SELECT request_id,protected FROM friend_vehicle_commands WHERE requester_id IN (SELECT account_id FROM team_room_members WHERE room_id=%s)'
  args=[room]
  if account is not None:
   query+=' AND (requester_id=%s OR owner_id=%s)';args.extend([account,account])
  self.cancel_trip_commands(conn, trip, conn.execute(query+' FOR UPDATE',args).fetchall())
  deletion = 'DELETE FROM team_trip_remote_grants WHERE trip_id=%s'
  bound = [trip]
  if account is not None:
   deletion += ' AND (requester_id=%s OR driver_id=%s)'
   bound.extend((account, account))
  conn.execute(deletion, bound)
 def notify(self,conn,owner,peer,device):
  changed(conn,owner,'friends');changed(conn,peer,'friends');self.commands.invalidate_receiver(conn,device)
 def cancel(self,conn,where,args,reason):
  for identifier,raw in conn.execute('SELECT request_id,protected FROM friend_vehicle_commands WHERE '+where+' FOR UPDATE',args).fetchall():
   value=self.commands.restore('request',identifier,raw)
   if value['stage'] in TERMINAL:continue
   self.commands.terminalize(value,reason);self.commands.save_request(conn,identifier,value)
   self.commands.invalidate_receiver(conn,value['targetDeviceId'])
 def revoke_pair(self,conn,a,b):
  self.withdraw_trip_grants(conn, owner=a, peer=b)
  self.withdraw_trip_grants(conn, owner=b, peer=a)
  rows=conn.execute('SELECT device_id,requester_id,owner_id,protected FROM friend_vehicle_controls WHERE (owner_id=%s AND requester_id=%s) OR (owner_id=%s AND requester_id=%s) FOR UPDATE',(a,b,b,a)).fetchall()
  for device,peer,owner,raw in rows:
   grant=self.commands.restore('friend-grant',device+':'+peer,raw);grant.update(revision=grant['revision']+1,consent=False)
   conn.execute('UPDATE friend_vehicle_controls SET protected=%s WHERE device_id=%s AND requester_id=%s',(self.commands.protect('friend-grant',device+':'+peer,grant),device,peer))
   self.cancel(conn,'device_id=%s AND requester_id=%s',(device,peer),'friendship-ended');self.notify(conn,owner,peer,device)
 def revoke_device(self,conn,device,owner):
  from team_trips import TeamTrips
  trips = TeamTrips(self.auth)
  for trip, car, raw in conn.execute('SELECT trip_id,car_id,protected FROM team_trip_cars WHERE driver_id=%s FOR UPDATE', (owner,)).fetchall():
   payload = trips.car_payload(trip, car, owner, raw)
   policy = payload.get('remotePolicy')
   if policy and policy['enabled'] and policy['deviceId'] == device:
    payload.update(remotePolicy=dict(policy, enabled=False, deviceId=None), remotePolicyGrantId=None,
        remotePolicyRevision=min(payload['remotePolicyRevision'] + 1, 2147483647))
    conn.execute('UPDATE team_trip_cars SET protected=%s WHERE trip_id=%s AND car_id=%s',
        (trips.protect('car:' + car + ':driver:' + owner, trip, payload), trip, car))
    trips.notify(conn, trip, bump=False, invalidate=False, sections=('detail',))
  self.withdraw_trip_grants(conn, device=device, owner=owner)
  self.cancel(conn,'device_id=%s AND owner_id=%s',(device,owner),'device-revoked')
  for peer,raw in conn.execute('SELECT requester_id,protected FROM friend_vehicle_controls WHERE device_id=%s AND owner_id=%s FOR UPDATE',(device,owner)).fetchall():
   grant=self.commands.restore('friend-grant',device+':'+peer,raw);grant.update(revision=grant['revision']+1,consent=False)
   conn.execute('UPDATE friend_vehicle_controls SET protected=%s WHERE device_id=%s AND requester_id=%s',(self.commands.protect('friend-grant',device+':'+peer,grant),device,peer))
   self.notify(conn,owner,peer,device)
 def options(self):return self.commands.display_actions()
 def public_command(self,identifier,value,trip=None):
  result=self.commands.public(identifier,value)
  if trip:
   result.pop('roomId',None);result['tripId']=trip
  return result
 async def create_command(self,device,request,*,trip=None):
  if not trip:fail(403,'Current trip remote permission required')
  c=self.commands
  if request.url.path.startswith('/v1/iphone/'):
   from iphone_sessions import body as iphone_body
   from native_access_codec import decode_json, CodecError
   try:data=decode_json(await iphone_body(request,'application/json',maximum_bytes=4096),maximum_bytes=4096)
   except CodecError:fail(400,'IPHONE_INVALID_REQUEST')
   if not isinstance(data,dict) or set(data)!={'eventId','grantRevision','capabilityId','capabilityRevision','arguments'}:fail(400,'IPHONE_INVALID_REQUEST')
  else:data=await body(request,('eventId','grantRevision','capabilityId','capabilityRevision','arguments'))
  event(data['eventId']);revision(data['grantRevision']);revision(data['capabilityRevision'])
  if not ID.fullmatch(device)or type(data['capabilityId'])is not str:fail(400)
  selected=dict(id=data['capabilityId'],revision=data['capabilityRevision'])
  if selected not in [dict(id=a['id'],revision=a['revision'])for a in self.options()]:fail(400)
  action=c.registry.lookup(data['capabilityId'],data['capabilityRevision'])
  if action is None or not action.validate_arguments(data['arguments']):fail(400,'Invalid control value')
  with psycopg.connect(self.dsn)as conn:
   c.rooms.graph_lock(conn);actor=self.actor(conn,request,True);peer=actor['id'];owner,grant=self.trip_grant(conn,trip,device,peer)
   if owner is None:fail(403)
   context,expiry=self.context(conn,device,peer,owner,action=selected,trip=trip)
   if data['grantRevision']!=grant['revision']:fail(409)
   origin=dict(deviceId=actor['deviceId'],grantId=actor['grantId'],functionalRevision=request.state.functional_snapshot['revision'])if is_native_principal(actor)else None
   digest=c.digest('friend-request-body',[device,data,trip,origin]if origin else[device,data,trip])
   event_hash=c.digest('friend-request-event',[peer,origin['deviceId'],origin['grantId'],data['eventId']]if origin else[peer,data['eventId']])
   old=conn.execute('SELECT request_id,protected FROM friend_vehicle_commands WHERE requester_id=%s AND event_hash=%s FOR UPDATE',(peer,event_hash)).fetchone()
   if old:
    value=c.load_request(conn,old[0])
    if value['bodyHash']!=digest:fail(409)
    return self.public_command(old[0],value,trip)
   from vehicle_control_support import current_support, command_problem
   reference=self.device(conn,owner,device,True)
   problem=command_problem(current_support(conn,self.auth,reference),selected,data['arguments'])
   if problem:fail(422,problem)
   if conn.execute('SELECT count(*) FROM friend_vehicle_commands WHERE requester_id=%s',(peer,)).fetchone()[0]>=1000:fail(409,'Control history limit reached')
   for prior_id,raw in conn.execute('SELECT request_id,protected FROM friend_vehicle_commands WHERE device_id=%s ORDER BY created_at DESC LIMIT 100 FOR UPDATE',(device,)).fetchall():
    prior=c.restore('request',prior_id,raw)
    if (prior['stage']=='queued'and prior.get('context',{}).get('tripId')==trip and prior['capabilityId']==selected['id']
     and all(prior['arguments'].get(area)==data['arguments'].get(area)for area in ('seat','window'))):
     c.terminalize(prior,'superseded');c.save_request(conn,prior_id,prior);c.notify_request_progress(conn,prior)
   identifier=secrets.token_hex(16);now=c.now(conn)
   value=dict(roomId=None,targetDeviceId=device,requesterId=peer,ownerId=owner,capabilityId=selected['id'],capabilityRevision=selected['revision'],arguments=data['arguments'],bodyHash=digest,context=context,createdAt=iso(now),expiresAt=iso(min(expiry,now+dt.timedelta(seconds=30))),stage='queued',lastAcknowledgedStage=None,mayHaveExecuted=False,reason=None,leaseHash=None,leaseExpiresAt=None,claimIdHash=None,leaseId=None,acks={})
   if origin is not None:value['nativeOrigin']=origin
   conn.execute('INSERT INTO friend_vehicle_commands(request_id,device_id,requester_id,owner_id,event_hash,protected) VALUES(%s,%s,%s,%s,%s,%s)',(identifier,device,peer,owner,event_hash,c.protect('request',identifier,value)))
   c.notify_request_progress(conn,value)
   return self.public_command(identifier,value,trip)
 def trip_router(self):
  from team_trip_context import resolve_trip_context
  from fastapi import Response
  router=APIRouter();c=self.commands
  if not c.enabled:return router
  @router.get('/v1/social/trips/{id}/cars/{carId}/remote-devices')
  def remote_devices(id: str, carId: str, request: Request, response: Response):
   response.headers['Cache-Control'] = 'private, no-store'
   with psycopg.connect(self.dsn) as conn:
    c.rooms.graph_lock(conn)
    owner = self.auth.browser(request, connection=conn)['id']
    resolve_trip_context(self.auth, conn, id, owner)
    if not conn.execute('SELECT 1 FROM team_trip_cars WHERE trip_id=%s AND car_id=%s AND driver_id=%s',
                        (id, carId, owner)).fetchone():
     fail(404, 'Car unavailable')
    devices = []
    rows = conn.execute("SELECT DISTINCT device_id FROM native_v2_grants WHERE account_id=%s "
                        "AND state='TOKEN_ISSUED' ORDER BY device_id", (owner,))
    for (device,) in rows.fetchall():
     try:
      reference = self.device(conn, owner, device, True)
     except HTTPException as error:
      if error.status_code in (403, 404):
       continue
      raise
     devices.append(dict(id=device, name=reference.name, receiveEnabled=True))
    return dict(devices=devices)
  @router.get('/v1/iphone/trips/{trip}/vehicle-remotes',include_in_schema=False)
  @router.get('/v1/social/trips/{trip}/vehicle-remotes')
  def remotes(trip:str,request:Request,response:Response):
   with psycopg.connect(self.dsn)as conn:
    c.rooms.graph_lock(conn);peer=self.actor(conn,request)['id'];items=[]
    resolve_trip_context(self.auth,conn,trip,peer,states=('active',))
    from team_trip_remote_policy import policy_car
    found=policy_car(self,conn,trip,peer)
    targets=[(found[2]['deviceId'],found[1])]if found and found[2]['enabled']else[]
    for device,owner in targets:
     try:
      context,expiry=self.context(conn,device,peer,owner,trip=trip);_,grant=self.trip_grant(conn,trip,device,peer);reference=self.device(conn,owner,device,True)
     except HTTPException as error:
      if error.status_code in(401,403,404,409,410):continue
      raise
     person=c.rooms.person(owner)
     if person is None:continue
     actions=[a for a in self.options()if dict(id=a['id'],revision=a['revision'])in grant['actions']]
     if actions:
      from vehicle_control_support import current_support, public_support
      support=current_support(conn,self.auth,reference)
      actions=[dict(a,support=public_support(support,a))for a in actions]
      recent=[]
      for identifier, raw in conn.execute('SELECT request_id,protected FROM friend_vehicle_commands '
          'WHERE device_id=%s AND requester_id=%s AND owner_id=%s ORDER BY created_at DESC,request_id DESC LIMIT 100',
          (device,peer,owner)):
       saved=c.restore('request',identifier,raw)
       if saved.get('context')!=context or dict(id=saved['capabilityId'],revision=saved['capabilityRevision']) not in grant['actions']:
        continue
       recent.append(self.public_command(identifier,c.load_request(conn,identifier),trip))
       if len(recent)==5:break
      items.append(dict(deviceId=device,ownerName=person['name'],deviceName=reference.name,grantRevision=grant['revision'],
                        expiresAt=iso(expiry),actions=actions,requests=recent))
    server_now=iso(c.now(conn))
   response.headers['Cache-Control']='private, no-store'
   return dict(tripId=trip,remotes=items,serverNow=server_now)
  @router.post('/v1/iphone/trips/{trip}/vehicle-remotes/{device}/commands',status_code=201,include_in_schema=False)
  @router.post('/v1/social/trips/{trip}/vehicle-remotes/{device}/commands',status_code=201)
  async def command(trip:str,device:str,request:Request,response:Response):
   response.headers['Cache-Control']='private, no-store'
   return await self.create_command(device,request,trip=trip)
  return router
