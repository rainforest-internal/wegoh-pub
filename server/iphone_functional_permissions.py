from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from iphone_sessions import body
from native_command_receiver import RECEIVE
from native_functional_defaults import ACCOUNT_PURPOSES
from native_functional_policy import FunctionalError, WIRE, decode_consent


def register_iphone_functional_routes(router, service):
    def actor(request, *, connection=None, lock=False):
        if request.url.query:
            raise HTTPException(400, 'IPHONE_INVALID_REQUEST')
        sessions = getattr(service.auth, 'iphone_sessions', None)
        if not sessions or not sessions.origin:
            raise HTTPException(404, 'IPHONE_ROUTE_NOT_FOUND')
        return sessions.authenticate(request, 'vehicles:manage', connection=connection, lock=lock)

    def permissions(conn, grant):
        return dict(authorization=service.snapshot(conn, grant),
            approvedDisclosureVersion=service.approved_disclosure_version(conn, grant),
            disclosure=dict(version=WIRE['disclosureVersion'], sha256=WIRE['disclosureSha256'], purposes=WIRE['purposeRegistry']),
            readOnlyPurposes=sorted(ACCOUNT_PURPOSES | {RECEIVE}))

    def read(request, device):
        try:
            service.require_enabled()
            with service.base.db() as conn:
                owner = actor(request, connection=conn)
                grant, _ = service.owner_grant(conn, owner['id'], device)
                return JSONResponse(permissions(conn, grant), headers={'Cache-Control': 'private, no-store'})
        except FunctionalError as error:
            raise HTTPException(error.status, error.code) from None

    def save(request, device, raw):
        try:
            service.require_enabled()
            with service.base.db() as conn:
                owner = actor(request, connection=conn, lock=True)
                value = decode_consent(raw)
                grant, _ = service.owner_grant(conn, owner['id'], device)
                service.write(conn, grant, value)
                return JSONResponse(permissions(conn, grant), headers={'Cache-Control': 'private, no-store'})
        except FunctionalError as error:
            raise HTTPException(error.status, error.code) from None

    @router.get('/v1/iphone/vehicles/{device}/functional-permissions', include_in_schema=False)
    def get_permissions(device: str, request: Request):
        return read(request, device)

    @router.put('/v1/iphone/vehicles/{device}/functional-permissions', include_in_schema=False)
    async def put_permissions(device: str, request: Request):
        owner = await run_in_threadpool(actor, request)
        service.auth.rate('iphone-functional-permissions:' + owner['id'], limit=60)
        raw = await body(request, 'application/json', maximum_bytes=12288)
        return await run_in_threadpool(save, request, device, raw)
