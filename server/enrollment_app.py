"""Run only on 127.0.0.1:18083 behind the dedicated enrollment Tunnel route.

This process has no content/native routes and requires no client certificate.
It can issue only an authenticated owner's approved CSR with private-key proof.
"""
import os
from pathlib import Path

import psycopg
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from starlette.middleware.trustedhost import TrustedHostMiddleware

from native_authorization_runtime import NativeAuthorizationRuntime
from native_authorization import NativeAuthorizationError, error_response, http_error_response
from native_access_codec import CodecError
from native_access_issuer_status import PATH as STATUS_PATH, internal_route_boundary, router as status_router
from enrollment_crypto import CloudflareIssuer, EnrollmentError
from private_records import PrivateRecordError
from team_auth import TeamAuth


def create_app(auth=None, issuer=None):
    if auth is None:
        dsn = os.environ.get('WEGOH_DATABASE_DSN', '')
        secret = os.environ.get('WEGOH_API_KEY', '')
        if not dsn or len(secret) < 32:
            raise RuntimeError('Enrollment configuration unavailable')
        auth = TeamAuth(dsn, secret, enrollment_only=True)
        issuer = CloudflareIssuer.configured()
    authorization = NativeAuthorizationRuntime(auth, issuer=issuer)
    configured_origin = os.environ.get("WEGOH_ENROLLMENT_ORIGIN", authorization.origin)
    if configured_origin != authorization.origin:
        raise RuntimeError("Enrollment origin must match the single authorization contract")
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.native_authorization = authorization
    host = authorization.origin.split('://')[-1]
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=[host,'127.0.0.1'] if host else ['enrollment-disabled.invalid'])

    @app.middleware('http')
    async def boundary(request: Request, call_next):
        try:
            if request.url.path==STATUS_PATH:
                if not authorization.enabled or issuer is None:raise NativeAuthorizationError(404,'ROUTE_NOT_FOUND')
                internal_route_boundary(request)
            else:
                await run_in_threadpool(authorization.public_boundary, request)
            response = await call_next(request)
        except NativeAuthorizationError as error:
            response = error_response(error)
        except HTTPException as error:
            response = http_error_response(error)
        except (CodecError, psycopg.Error, PrivateRecordError, EnrollmentError, OSError):
            response = error_response(NativeAuthorizationError(503,'SERVICE_UNAVAILABLE'))
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Content-Security-Policy'] = "default-src 'none'; frame-ancestors 'none'"
        return response

    if authorization.enabled:
        authorization.verify_issuance_holds()
        app.include_router(authorization.issuer_router())
        if issuer is not None:app.include_router(status_router(auth,issuer))
    return app


def apply_schema(dsn):
    # Explicit additive installation only; never reads another service database.
    with psycopg.connect(dsn) as conn:
        conn.execute(Path(__file__).with_name('enrollment_schema.sql').read_text(encoding='utf-8'))
        conn.execute(Path(__file__).with_name('native_access_schema.sql').read_text(encoding='utf-8'))
