"""Dedicated shared API entry point; the normal local app remains unchanged."""
import os
from urllib.parse import urlsplit

from runtime_credentials import apply_runtime_credentials
apply_runtime_credentials()
from app import app, API_KEY, TEAM_AUTH, WEB
from team_api_docs import install_api_docs
install_api_docs(app, TEAM_AUTH, WEB)

# Deployed services always observe requests; a local run opts in with WEGOH_ACCESS_LOG=1.
if os.environ.get('CREDENTIALS_DIRECTORY') or os.environ.get('WEGOH_ACCESS_LOG') == '1':
    import psycopg
    from api_observability import HostSurfaces, install, record_boundary_errors
    from api_quality_metrics import ApiQualityMetrics
    from api_tracing import instrument_iphone_dependencies, tracing_from_environment

    tracing = tracing_from_environment()
    if tracing is not None and TEAM_AUTH.iphone_sessions.host:
        instrument_iphone_dependencies(TEAM_AUTH)
    # The security middleware turns boundary failures into a bare 503; record the cause first.
    record_boundary_errors(TEAM_AUTH, 'boundary')
    authorization = getattr(TEAM_AUTH, 'native_authorization', None)
    public_host = urlsplit(TEAM_AUTH.public_origin).hostname if TEAM_AUTH.public_origin else None
    surfaces = HostSurfaces(
        iphone=(TEAM_AUTH.iphone_sessions.host,),
        native=(urlsplit(TEAM_AUTH.native_origin).hostname if TEAM_AUTH.native_origin else None,
                urlsplit(authorization.origin).hostname if authorization and authorization.enabled else None),
        web=(public_host,))
    serve = app
    if TEAM_AUTH.iphone_sessions.host:
        serve = ApiQualityMetrics(app, iphone_host=TEAM_AUTH.iphone_sessions.host, web_host=public_host)
    app = install(app, application='api', secret=API_KEY, surfaces=surfaces, tracing=tracing, auth=TEAM_AUTH,
                  error_classes=(psycopg.Error, OSError), serve=serve)
