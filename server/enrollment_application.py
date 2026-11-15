"""Systemd entrypoint: dedicated credentials, DB role, and only bootstrap routes."""
import json,os,re
from pathlib import Path
from enrollment_runtime import configure_runtime,verify_database_scope,EnrollmentRuntimeAuth

verify_database_scope(os.environ['WEGOH_DATABASE_DSN'])
configure_runtime()
from enrollment_app import create_app
from enrollment_crypto import CloudflareIssuer
app=create_app(auth=EnrollmentRuntimeAuth(os.environ['WEGOH_DATABASE_DSN'],os.environ['WEGOH_API_KEY']),issuer=CloudflareIssuer.configured())
manifest=Path(__file__).resolve().parents[1]/'RELEASE.json'
revision=''
if manifest.is_file():
    candidate=json.loads(manifest.read_text()).get('commit','')
    if not re.fullmatch('[a-f0-9]{40}',candidate)or manifest.parent.name!=candidate:raise RuntimeError('Enrollment release identity invalid')
    revision=candidate
if revision:
    @app.middleware('http')
    async def immutable_release_header(request,call_next):
        response=await call_next(request)
        response.headers['X-WegoH-Release']=revision
        return response

import sys
from deployment_gate import install as install_deployment_gate, enrollment_readiness
install_deployment_gate(app, revision or None, enrollment_readiness(sys.modules[__name__]))

import psycopg
from api_observability import HostSurfaces, install as install_observability, record_boundary_errors
from api_tracing import tracing_from_environment
from enrollment_crypto import EnrollmentError
from native_access_codec import CodecError
from private_records import PrivateRecordError
# Outermost: every enrollment request gets an access line; the boundary middleware hides causes behind 503.
record_boundary_errors(app.state.native_authorization,'public_boundary')
app=install_observability(app,application='enroll',secret=os.environ['WEGOH_API_KEY'],
    surfaces=HostSurfaces(default='enroll'),tracing=tracing_from_environment(),
    error_classes=(CodecError,psycopg.Error,PrivateRecordError,EnrollmentError,OSError))
