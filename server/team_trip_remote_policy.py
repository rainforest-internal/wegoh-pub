from fastapi import HTTPException, Request, Response
import psycopg

from private_records import PrivateRecordError


ACTION_IDS = frozenset(('hvac.temperature', 'hvac.fan', 'hvac.power', 'hvac.ac', 'hvac.air_cleaner',
    'light.cabin', 'light.reading', 'light.ambient', 'window.position', 'seat.heat', 'seat.ventilation'))


def policy_fields(value):
    if (not isinstance(value, dict) or not {'enabled', 'actions'} <= value.keys()
            or value.keys() - {'enabled', 'actions', 'deviceId'}
            or type(value['enabled']) is not bool or not isinstance(value['actions'], list)
            or any(not isinstance(action, str) or action not in ACTION_IDS for action in value['actions'])
            or len(set(value['actions'])) != len(value['actions'])
            or (value['enabled'] and not value['actions'])):
        raise HTTPException(400, 'Invalid remote policy')
    from team_trips import IDENT
    device = value.get('deviceId')
    if device is not None and (not isinstance(device, str) or not IDENT.fullmatch(device)):
        raise HTTPException(400, 'Invalid remote policy device')
    return dict(enabled=value['enabled'], actions=sorted(value['actions']), deviceId=device)


def saved_policy(car):
    value = car.get('remotePolicy', dict(enabled=False, actions=[], deviceId=None))
    try:
        result = policy_fields(value)
        revision = car.get('remotePolicyRevision', 0)
        from team_trips import IDENT
        binding = car.get('remotePolicyGrantId')
        if (type(revision) is not int or not 0 <= revision <= 2147483647
                or (binding is not None and (not isinstance(binding, str) or not IDENT.fullmatch(binding)))
                or (result['enabled'] and (revision == 0 or result['deviceId'] is None or binding is None))):
            raise HTTPException(400)
        return result
    except HTTPException:
        raise PrivateRecordError('Trip remote policy integrity failed') from None


def resolve_policy(trips, conn, owner, value):
    policy = policy_fields(value)
    controls = trips.auth.device_command_service.friend_controls
    available = {item['id'] for item in controls.options()}
    if any(action not in available for action in policy['actions']):
        raise HTTPException(400, 'Invalid remote policy actions')
    if policy['enabled']:
        if trips.category(conn, owner) != 'vehicle':
            raise HTTPException(409, 'Vehicle owner required')
        if not controls.commands.enabled:
            raise HTTPException(409, 'No vehicle ready for remote control')
        if policy['deviceId'] is None:
            devices = []
            for (device,) in conn.execute("SELECT DISTINCT device_id FROM native_v2_grants WHERE "
                    "account_id=%s AND state='TOKEN_ISSUED' ORDER BY device_id", (owner,)).fetchall():
                try:
                    controls.device(conn, owner, device, True)
                except HTTPException as error:
                    if error.status_code in (403, 404):
                        continue
                    raise
                devices.append(device)
            if len(devices) != 1:
                raise HTTPException(409, 'Choose a vehicle for remote control')
            policy['deviceId'] = devices[0]
    if policy['deviceId'] is not None:
        controls.device(conn, owner, policy['deviceId'], policy['enabled'])
    return policy


def policy_car(controls, conn, trip, peer):
    row = conn.execute('SELECT c.car_id,c.driver_id,c.protected FROM team_trip_riders r '
        'JOIN team_trip_cars c USING(trip_id,car_id) WHERE r.trip_id=%s AND r.account_id=%s FOR UPDATE OF c',
        (trip, peer)).fetchone()
    if not row:
        return None
    from team_trips import TeamTrips
    car, owner, raw = row
    trips = TeamTrips(controls.auth)
    if trips.category(conn, owner) != 'vehicle':
        return None
    payload = trips.car_payload(trip, car, owner, raw)
    return car, owner, saved_policy(payload), payload.get('remotePolicyRevision', 0), payload.get('remotePolicyGrantId')


def install(router, trips, actor, transaction, body):
    @router.get('/v1/iphone/trips/{id}/cars/{carId}/remote-policy', include_in_schema=False)
    @router.get('/v1/social/trips/{id}/cars/{carId}/remote-policy')
    def read_policy(id: str, carId: str, request: Request, response: Response):
        account = actor(request, response)
        with psycopg.connect(trips.dsn) as conn:
            transaction(request, conn)
            trips.access(conn, id, account)
            car = trips.car(conn, id, carId, account)
            if account != car['driverId'] and trips.riders(conn, id).get(account) != carId:
                raise HTTPException(404, 'Car unavailable')
            return dict(remotePolicy=car['remotePolicy'])

    @router.put('/v1/iphone/trips/{id}/cars/{carId}/remote-policy', include_in_schema=False)
    @router.put('/v1/social/trips/{id}/cars/{carId}/remote-policy')
    async def write_policy(id: str, carId: str, request: Request, response: Response):
        account = actor(request, response, mutate=True)
        value = await body(request, ('enabled', 'actions'), optional_fields=('deviceId',))
        with psycopg.connect(trips.dsn) as conn:
            transaction(request, conn, mutate=True)
            trips.access(conn, id, account, mutable=True)
            car = trips.car(conn, id, carId, account)
            if account != car['driverId']:
                raise HTTPException(403, 'Only the driver may manage remote policy')
            from team_trip_plan import TeamTripPlan
            payload = TeamTripPlan(trips).route_state(conn, id, carId)[1]
            policy = resolve_policy(trips, conn, account, value)
            binding = trips.auth.device_command_service.friend_controls.device(conn, account, policy['deviceId'], True).grant_id if policy['enabled'] else None
            if policy != saved_policy(payload) or binding != payload.get('remotePolicyGrantId'):
                revision = payload.get('remotePolicyRevision', 0)
                if revision >= 2147483647 and policy['enabled']:
                    raise HTTPException(409, 'Remote policy revision exhausted')
                trips.auth.device_command_service.friend_controls.withdraw_trip_grants(conn, trip=id, car=carId)
                payload.update(remotePolicy=policy, remotePolicyRevision=min(revision + 1, 2147483647), remotePolicyGrantId=binding)
                conn.execute('UPDATE team_trip_cars SET protected=%s WHERE trip_id=%s AND car_id=%s',
                    (trips.protect('car:' + carId + ':driver:' + account, id, payload), id, carId))
                trips.notify(conn, id, bump=False, invalidate=False, sections=('detail',))
            return dict(remotePolicy=policy)
