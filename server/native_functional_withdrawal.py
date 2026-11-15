"""Purpose-specific shared-report cleanup in the caller's consent/revoke transaction.
The authority caller holds graph -> installation -> grant locks first. Original
journey/photos/keys remain; only withdrawn-purpose shared derivatives are erased.
"""
from native_functional_policy import PURPOSES,identifier,FunctionalError
from team_data import changed
from private_records import PrivateRecordError
from psycopg.rows import tuple_row

REPORT_PURPOSES=frozenset({'vehicle-location:report','vehicle-visits:report','vehicle-reports:read'})
MUSIC_SOURCE_PURPOSES=frozenset({'rooms:read','room-music:control'})

def withdraw_report_effects(conn,auth,account,device,removed):
 """Caller supplies its locked current grant owner/device, never a public selector."""
 identifier(device)
 if conn.autocommit or type(removed)is not frozenset or not removed<=PURPOSES:
  raise FunctionalError(503,'FUNCTIONAL_TRANSACTION_REQUIRED')
 relevant=REPORT_PURPOSES if 'rooms:read'in removed else removed&REPORT_PURPOSES
 music_removed=removed&(MUSIC_SOURCE_PURPOSES|{'room-music:read'})
 command_removed=removed&{'device-commands:receive','device-commands:request'}
 voice_removed=removed&{'room-voice:receive','room-voice:transmit'}
 if not relevant and not music_removed and not command_removed and not voice_removed:return dict(latestDeleted=0,roomsInvalidated=0)
 # Domain helpers use tuple rows. Do not mutate the caller's dict-row connection.
 with conn.cursor(row_factory=tuple_row)as cursor:
  result=_withdraw_report_effects(cursor,auth,account,device,relevant)if relevant else dict(latestDeleted=0,roomsInvalidated=0)
  if music_removed:
   music=getattr(auth,'room_music_service',None)
   authority=getattr(auth,'room_music_access',None)
   if music is None or authority is None:raise FunctionalError(503,'FUNCTIONAL_CLEANUP_UNAVAILABLE')
   authority.withdraw(cursor,account,device,removed)
   if music_removed&MUSIC_SOURCE_PURPOSES:
    result['roomsInvalidated']+=len(music.withdraw_native_source(cursor,account,device))
  if voice_removed:
   voice=getattr(auth,'room_voice_access',None)
   if voice is None:raise FunctionalError(503,'FUNCTIONAL_CLEANUP_UNAVAILABLE')
   voice.withdraw(cursor,account,device,voice_removed)
  if command_removed:
   commands=getattr(auth,'device_command_service',None)
   if commands is None:raise FunctionalError(503,'FUNCTIONAL_CLEANUP_UNAVAILABLE')
   if 'device-commands:receive'in command_removed:commands.revoke_device(cursor,device,account)
   if 'device-commands:request'in command_removed:commands.revoke_native_requester(cursor,device,account)
  return result


def _withdraw_report_effects(conn,auth,account,device,relevant):
 vehicle=getattr(auth,'vehicle_service',None)
 if vehicle is None:raise FunctionalError(503,'FUNCTIONAL_CLEANUP_UNAVAILABLE')
 vehicle.rooms.graph_lock(conn) # Required already before authority row locks at integration.
 kinds=[kind for purpose,kind in [('vehicle-location:report','location'),('vehicle-visits:report','visits')]if purpose in relevant]
 affected=set();deleted=[]
 if kinds:
  deleted=conn.execute('DELETE FROM team_vehicle_latest_reports WHERE account_id=%s AND device_id=%s AND kind=ANY(%s) RETURNING room_id',(account,device,kinds)).fetchall()
  affected.update(row[0]for row in deleted)
 for room,raw,expiry in conn.execute('SELECT room_id,protected,expires_at FROM team_vehicle_room_grants WHERE account_id=%s ORDER BY room_id FOR UPDATE',(account,)).fetchall():
  value=vehicle.restore('room-grant',account,room,raw)
  devices=value.get('devices')
  if type(devices)is not dict:raise PrivateRecordError('Room report grant integrity failed')
  entry=devices.get(device);modified=False
  if entry is not None:
   if type(entry)is not dict:raise PrivateRecordError('Room report device integrity failed')
   for purpose,key in [('vehicle-location:report','shareLocation'),('vehicle-visits:report','shareVisits')]:
    if purpose in relevant and entry.get(key):entry[key]=False;modified=True
   if 'vehicle-reports:read'in relevant:
    for key in ['receiveLocation','receiveVisits']:
     if entry.get(key):entry[key]=False;modified=True
  if 'vehicle-reports:read'in relevant and value.get('receiverDeviceId')==device:
   value['receiverDeviceId']=None;modified=True
  if modified:
   vehicle.store_room(conn,room,account,value,expiry);affected.add(room)
 for room in sorted(affected):
  vehicle.rooms.notify(conn,room)
  for(peer,)in conn.execute('SELECT account_id FROM team_room_members WHERE room_id=%s AND left_at IS NULL',(room,)).fetchall():
   changed(conn,peer,'vehicle')
 # Existing digest/nonce receipts remain replay tombstones. They contain no raw
 # report coordinate/visit payload. No personal history/photo/key table is touched.
 return dict(latestDeleted=len(deleted),roomsInvalidated=len(affected))
