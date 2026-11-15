import re
import psycopg
from fastapi import HTTPException
from psycopg.rows import dict_row
from private_records import VisitCipher
from team_data import changed
from vehicle_names import default_vehicle_name,valid_vehicle_name

MAX_REVISION=2147483647

def valid_plate(value):
    return type(value) is str and (value=='' or
        re.fullmatch(r'[0-9가-힣]{2,16}',value) is not None and any(c in '0123456789' for c in value))

def register_vehicle_profile(router,auth):
    from fastapi import Request,Response
    from native_access_codec import decode_json,CodecError
    from native_authorization import read_body,NativeAuthorizationError
    from team_friends import ACCOUNT, linked

    @router.get('/v1/iphone/friends/{peer}/profile', include_in_schema=False)
    @router.get('/v1/social/friends/{peer}/profile')
    def friend_profile(peer: str, request: Request, response: Response):
        response.headers['Cache-Control'] = 'private, no-store'
        iphone = request.url.path.startswith('/v1/iphone/')
        if iphone:
            auth.iphone_sessions.authenticate(request, 'friends:read')
        with psycopg.connect(auth.dsn) as conn:
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ' + ('' if iphone else ', READ ONLY'))
            if iphone:
                if request.url.query:raise HTTPException(400,'IPHONE_INVALID_REQUEST')
                viewer = auth.iphone_sessions.authenticate(request,'friends:read',connection=conn)['id']
            else:
                viewer = auth.browser(request, connection=conn)['id']
            if peer == viewer or not ACCOUNT.fullmatch(peer) or not linked(conn, viewer, peer):
                raise HTTPException(404, 'Friend profile unavailable')
            row = conn.execute("SELECT protected FROM team_accounts WHERE account_id=%s AND account_status='active'",
                               (peer,)).fetchone()
            if not row:
                raise HTTPException(404, 'Friend profile unavailable')
            saved = VisitCipher().restore('team-account:' + peer, 'identity', row[0])
            member = auth.stored_member(saved)
            if not member:
                raise HTTPException(404, 'Friend profile unavailable')
            profiles = saved.get('vehicleProfiles', {})
            plates = set()
            if profiles:
                keys = conn.execute('SELECT g.installation_key_id FROM native_v2_grants g '
                    'JOIN native_v2_installations i USING (installation_key_id) '
                    "WHERE g.account_id=%s AND g.state='TOKEN_ISSUED' AND g.revoked_at IS NULL "
                    'AND g.expires_at>extract(epoch FROM clock_timestamp()) '
                    'AND i.revoked_at IS NULL AND i.active_grant_id=g.grant_id', (peer,))
                for key, in keys:
                    plate = profiles.get(key, {}).get('plateNumber')
                    if plate and valid_plate(plate):
                        plates.add(plate)
            return dict(name=saved.get('displayName') or member['name'], plateNumbers=sorted(plates))

    def access(request,actor,data=None,device=None):
        with psycopg.connect(auth.dsn,row_factory=dict_row) as conn:
            service=auth.native_authorization
            if device is None:
                initial=conn.execute('SELECT installation_key_id FROM native_v2_grants WHERE grant_id=%s',(actor['grantId'],)).fetchone()
                if not initial:raise HTTPException(401,'INVALID_CREDENTIAL')
                service.lock(conn,initial['installation_key_id'])
                try:current=service.authenticate(request,connection=conn)
                except NativeAuthorizationError as error:raise HTTPException(error.status,error.code) from None
                if current['grantId']!=actor['grantId'] or current['credentialEpoch']!=actor['credentialEpoch']:raise HTTPException(401,'INVALID_CREDENTIAL')
                device_id=actor['deviceId'];key=initial['installation_key_id']
            else:
                if request.url.path.startswith('/v1/iphone/'):
                    current=auth.iphone_sessions.authenticate(request,'account:write',connection=conn,lock=data is not None)
                    if current['id']!=actor['id']:raise HTTPException(401,'Account changed')
                else:auth.browser(request,mutate=data is not None,connection=conn)
                grant=service._owned_lock(conn,actor['id'],device)
                if not grant:raise HTTPException(404,'DEVICE_UNAVAILABLE')
                try:service._live(grant)
                except NativeAuthorizationError as error:raise HTTPException(error.status,error.code) from None
                key=grant['installation_key_id'];device_id=grant['device_id']
            row=conn.execute('SELECT protected FROM team_accounts WHERE account_id=%s FOR UPDATE',(actor['id'],)).fetchone()
            if not row:raise HTTPException(401,'INVALID_CREDENTIAL')
            saved=VisitCipher().restore('team-account:'+actor['id'],'identity',row['protected'])
            profiles=saved.get('vehicleProfiles',{})
            profile=dict(dict(plateNumber='',name='',revision=0),**profiles.get(key,{}))
            try:default=default_vehicle_name(auth,saved)
            except ValueError:raise HTTPException(403,'Team access denied') from None
            if data is not None:
                if data['expectedRevision']!=profile['revision']:raise HTTPException(409,'VEHICLE_PROFILE_CHANGED')
                if profile['revision']>=MAX_REVISION:raise HTTPException(409,'VEHICLE_PROFILE_CHANGED')
                if key not in profiles and len(profiles)>=100:raise HTTPException(409,'VEHICLE_PROFILE_LIMIT')
                profile=dict(plateNumber=data['plateNumber'],name=data['name'],revision=profile['revision']+1)
                profiles[key]=profile;saved['vehicleProfiles']=profiles
                protected=VisitCipher().protect('team-account:'+actor['id'],'identity',saved)
                conn.execute('UPDATE team_accounts SET protected=%s WHERE account_id=%s',(protected,actor['id']))
                changed(conn,actor['id'],'devices')
                # The owner's connected vehicle apps show this profile; wake their device feeds.
                changed(conn,'profile-account:'+actor['id'],'devices')
            return dict(deviceId=device_id,plateNumber=profile['plateNumber'],name=profile['name'],
                        defaultName=default,revision=profile['revision'])

    @router.get('/v1/device/vehicle-profile')
    def get_vehicle_profile(request:Request,response:Response):
        response.headers['Cache-Control']='private, no-store'
        return access(request,auth.device(request))

    async def body(request):
        try:data=decode_json(await read_body(request),maximum_bytes=1024)
        except CodecError:raise HTTPException(400,'INVALID_VEHICLE_PROFILE') from None
        except NativeAuthorizationError as error:raise HTTPException(error.status,error.code) from None
        if (type(data) is not dict or set(data)!={'plateNumber','name','expectedRevision'} or not valid_plate(data['plateNumber'])
            or not valid_vehicle_name(data['name'])
            or type(data['expectedRevision']) is not int or not 0<=data['expectedRevision']<=MAX_REVISION):
            raise HTTPException(400,'INVALID_VEHICLE_PROFILE')
        return data

    @router.put('/v1/device/vehicle-profile')
    async def put_vehicle_profile(request:Request,response:Response):
        data=await body(request);actor=auth.device(request)
        auth.rate('vehicle-profile:'+actor['id'],limit=30)
        response.headers['Cache-Control']='private, no-store'
        return access(request,actor,data)

    @router.get('/v1/iphone/vehicles/{device}/profile',include_in_schema=False)
    @router.get('/v1/devices/{device}/vehicle-profile')
    def browser_get_vehicle_profile(device:str,request:Request,response:Response):
        actor=auth.iphone(request,'account:write') if request.url.path.startswith('/v1/iphone/') else auth.browser(request)
        if request.url.query:raise HTTPException(400,'Invalid request')
        auth.rate('vehicle-profile-read:'+actor['id'],limit=60)
        response.headers['Cache-Control']='private, no-store'
        return access(request,actor,device=device)

    @router.put('/v1/iphone/vehicles/{device}/profile',include_in_schema=False)
    @router.put('/v1/devices/{device}/vehicle-profile')
    async def browser_put_vehicle_profile(device:str,request:Request,response:Response):
        actor=auth.iphone(request,'account:write') if request.url.path.startswith('/v1/iphone/') else auth.browser(request,mutate=True)
        if request.url.query:raise HTTPException(400,'Invalid request')
        data=await body(request)
        auth.rate('vehicle-profile:'+actor['id'],limit=30)
        response.headers['Cache-Control']='private, no-store'
        return access(request,actor,data,device=device)
