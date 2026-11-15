"""iPhone account access to the existing vehicle approval and device ownership."""
from fastapi import HTTPException, Request
from starlette.concurrency import run_in_threadpool

from native_authorization import NativeAuthorizationError, VehicleConnectionLimit, read_body
from team_auth import CODE


def register_iphone_vehicle_routes(router, service):
    def owner(request):
        actor = service.auth.iphone(request, 'vehicles:manage')
        try:
            service.auth.rate('iphone-vehicles:' + actor['id'], limit=60)
        except HTTPException as error:
            if error.status_code != 429:
                raise
            raise HTTPException(429, 'RATE_LIMITED', headers=error.headers) from None
        return actor

    def require_code(user_code):
        if not CODE.fullmatch(user_code):
            raise HTTPException(400, 'INVALID_COMPARISON_CODE')

    def authorization_error(error):
        if isinstance(error, VehicleConnectionLimit):
            return HTTPException(409, 'VEHICLE_CONNECTION_LIMIT')
        headers = {'Retry-After': str(error.retry)} if error.retry is not None else None
        return HTTPException(error.status, error.code, headers=headers)

    @router.get('/v1/iphone/connections/{user_code}', include_in_schema=False)
    def connection(user_code: str, request: Request):
        actor = owner(request)
        require_code(user_code)
        try:
            return service.detail(user_code, actor, account_decision=True)
        except NativeAuthorizationError as error:
            raise authorization_error(error) from None

    async def decide(user_code, request, *, deny):
        actor = await run_in_threadpool(owner, request)
        require_code(user_code)
        try:
            return await run_in_threadpool(service.approve, user_code, await read_body(request), actor,
                                           deny=deny, account_decision=True)
        except NativeAuthorizationError as error:
            raise authorization_error(error) from None

    @router.post('/v1/iphone/connections/{user_code}', include_in_schema=False)
    async def approve(user_code: str, request: Request):
        return await decide(user_code, request, deny=False)

    @router.delete('/v1/iphone/connections/{user_code}', include_in_schema=False)
    async def decline(user_code: str, request: Request):
        return await decide(user_code, request, deny=True)

    @router.get('/v1/iphone/vehicles', include_in_schema=False)
    def vehicles(request: Request):
        actor = owner(request)
        return {'devices': service.list_owned_devices(actor['id'])}

    @router.delete('/v1/iphone/vehicles/{device_id}', include_in_schema=False)
    def revoke(device_id: str, request: Request):
        actor = owner(request)
        try:
            revoked = service.revoke_owned_device(actor['id'], device_id)
        except NativeAuthorizationError as error:
            raise authorization_error(error) from None
        if not revoked:
            raise HTTPException(404, 'DEVICE_UNAVAILABLE')
        return {'status': 'revoked'}
