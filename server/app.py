from native_access_policy import is_authorization_path
"""Local development and explicitly configured private team-demo API."""
from contextlib import asynccontextmanager
import hashlib
import hmac
import os
import re
import tempfile
from pathlib import Path
from typing import Annotated

import psycopg
from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from team_fuel import TeamFuel
from place_map_config import studio_csp
from starlette.middleware.trustedhost import TrustedHostMiddleware
from studio import create_router
from team_course_library import create_course_library_router
from music_link_preview import create_router as create_music_link_preview_router
from app_release import router as app_release_router
from team_discovery import create_router as create_discovery_router
from team_recommendations import TeamRecommendations
from private_records import VisitCipher,PrivateRecordError
from team_auth import TeamAuth
from iphone_push import IPhonePush, push_lifespan
from iphone_sessions import API_PREFIX as IPHONE_API_PREFIX, CALLBACK as IPHONE_CALLBACK, LOGIN_PAGE as IPHONE_LOGIN_PAGE, IPhoneSessions
from native_authorization_runtime import NativeAuthorizationRuntime
from native_authorization import NativeAuthorizationError, error_response, http_error_response
from native_access_codec import CodecError
from team_friends import create_router as create_friends_router
from team_rooms import TeamRooms
from team_trips import TeamTrips
from team_missions import TeamMissions
from team_vehicle import TeamVehicle
from team_device_commands import TeamDeviceCommands
from team_room_music import TeamRoomMusic
from team_history import TeamHistory
from team_history_remix import TeamHistoryRemix
from team_cautions import TeamCautions
from team_photos import TeamPhotos
from team_story import TeamStory
from team_content import TeamContent
from native_access import NativeAccess
from team_voice import TeamVoice
from team_data import create_router as create_team_data_router
from starlette.concurrency import run_in_threadpool

DSN = os.environ.get("WEGOH_DATABASE_DSN", "dbname=wegoh user=wegoh host=/var/run/postgresql connect_timeout=3")
CONTENT = Path(os.environ.get("WEGOH_CONTENT_DIR", "/srv/wegoh/content"))
WEB = Path(os.environ.get('WEGOH_WEB_DIR', str(Path(__file__).parent / 'web')))
API_KEY = os.environ.get("WEGOH_API_KEY", "")
if len(API_KEY) < 32:
    raise RuntimeError("WEGOH_API_KEY must contain at least 32 characters")
TEAM_AUTH = TeamAuth(DSN, API_KEY)
TEAM_NATIVE_AUTHORIZATION = NativeAuthorizationRuntime(TEAM_AUTH)
TEAM_AUTH.native_authorization = TEAM_NATIVE_AUTHORIZATION
TEAM_AUTH.iphone_sessions = IPhoneSessions(TEAM_AUTH)
from native_functional_access import NativeFunctionalAccess
TEAM_FUNCTIONAL = NativeFunctionalAccess(TEAM_NATIVE_AUTHORIZATION)
TEAM_AUTH.functional_access = TEAM_FUNCTIONAL
TEAM_ROOMS = TeamRooms(TEAM_AUTH)
TEAM_AUTH.room_service = TEAM_ROOMS
TEAM_TRIPS = TeamTrips(TEAM_AUTH)
TEAM_AUTH.trip_service = TEAM_TRIPS
TEAM_MISSIONS = TeamMissions(TEAM_AUTH, TEAM_ROOMS, CONTENT)
TEAM_AUTH.mission_service = TEAM_MISSIONS
TEAM_DEVICE_COMMANDS = TeamDeviceCommands(TEAM_AUTH, TEAM_ROOMS)
TEAM_AUTH.device_command_service = TEAM_DEVICE_COMMANDS
from friend_vehicle_controls import FriendVehicleControls
TEAM_FRIEND_CONTROLS = FriendVehicleControls(TEAM_DEVICE_COMMANDS)
TEAM_DEVICE_COMMANDS.friend_controls = TEAM_FRIEND_CONTROLS
TEAM_ROOM_MUSIC = TeamRoomMusic(TEAM_AUTH, TEAM_ROOMS)
TEAM_AUTH.room_music_service = TEAM_ROOM_MUSIC
from native_room_music_authority import NativeRoomMusicAuthority
TEAM_ROOM_MUSIC_ACCESS = NativeRoomMusicAuthority(TEAM_FUNCTIONAL, TEAM_ROOMS)
TEAM_AUTH.room_music_access = TEAM_ROOM_MUSIC_ACCESS
from native_room_voice_authority import NativeRoomVoiceAuthority
TEAM_ROOM_VOICE_ACCESS = NativeRoomVoiceAuthority(TEAM_FUNCTIONAL, TEAM_ROOMS)
TEAM_AUTH.room_voice_access = TEAM_ROOM_VOICE_ACCESS
TEAM_VOICE = TeamVoice(TEAM_AUTH, TEAM_ROOMS)
TEAM_AUTH.voice_service = TEAM_VOICE
from team_voice_clips import TeamVoiceClips
TEAM_VOICE_CLIPS = TeamVoiceClips(TEAM_VOICE)
TEAM_VOICE.clip_service = TEAM_VOICE_CLIPS
TEAM_HISTORY = TeamHistory(TEAM_AUTH, TEAM_ROOMS)
TEAM_AUTH.history_service = TEAM_HISTORY
TEAM_HISTORY_REMIX = TeamHistoryRemix(TEAM_AUTH, TEAM_HISTORY, CONTENT)
TEAM_AUTH.history_remix_service = TEAM_HISTORY_REMIX
TEAM_CAUTIONS = TeamCautions(TEAM_AUTH, TEAM_HISTORY)
TEAM_AUTH.cautions_service = TEAM_CAUTIONS
TEAM_FUEL = TeamFuel(TEAM_AUTH)
TEAM_RECOMMENDATIONS = TeamRecommendations(TEAM_AUTH, TEAM_HISTORY, CONTENT)
TEAM_AUTH.recommendation_service = TEAM_RECOMMENDATIONS
TEAM_PHOTOS = TeamPhotos(TEAM_AUTH, TEAM_HISTORY)
TEAM_AUTH.photos_service = TEAM_PHOTOS
TEAM_HISTORY.photos_service = TEAM_PHOTOS
TEAM_CONTENT = TeamContent(TEAM_AUTH)
TEAM_AUTH.content_service = TEAM_CONTENT
TEAM_CONTENT.register('history', TEAM_HISTORY.projection, lambda conn,key,owner: TEAM_HISTORY.notify(conn,key,owner))
TEAM_CONTENT.register('caution', TEAM_CAUTIONS.projection, TEAM_CAUTIONS.notify)
TEAM_CONTENT.register('room', TEAM_ROOMS.projection, lambda conn,key,owner: TEAM_ROOMS.notify(conn,key))
TEAM_CONTENT.register('room-music', TEAM_ROOM_MUSIC.projection, TEAM_ROOM_MUSIC.notify)
TEAM_CONTENT.register('room-place', TEAM_ROOMS.place_projection, lambda conn,key,owner: TEAM_ROOMS.notify(conn,key.split(':')[0]))
TEAM_CONTENT.register('photo', TEAM_PHOTOS.projection, TEAM_PHOTOS.notify_content, media=TEAM_PHOTOS.media)
TEAM_STORY = TeamStory(TEAM_AUTH, TEAM_HISTORY, TEAM_PHOTOS)
TEAM_AUTH.story_service = TEAM_STORY
TEAM_NATIVE_ACCESS = NativeAccess(TEAM_AUTH)
TEAM_AUTH.native_access = TEAM_NATIVE_ACCESS
TEAM_VEHICLE = TeamVehicle(TEAM_AUTH, TEAM_ROOMS)
MAX_BYTES = 25 * 1024 * 1024
MEDIA_TYPES = {"application/json", "image/png", "image/jpeg", "audio/wav", "audio/mpeg", "audio/ogg"}
@asynccontextmanager
async def application_lifespan(application):
    try:
        async with push_lifespan(TEAM_AUTH, lambda: SERVER_RELEASE_REVISION)(application):
            yield
    finally:
        TEAM_VOICE_CLIPS.memory.clear()


app = FastAPI(title="WegoH private development API", version="0.1.0", docs_url=None, redoc_url=None, openapi_url=None,
              lifespan=application_lifespan)
bearer = HTTPBearer(auto_error=False)
app.include_router(app_release_router)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=TEAM_AUTH.hosts)


@app.middleware('http')
async def security_headers(request, call_next):
    try:
        await run_in_threadpool(TEAM_AUTH.boundary, request)
    except NativeAuthorizationError as error:
        response = error_response(error)
    except HTTPException as error:
        response = http_error_response(error) if is_authorization_path(request.url.path) else JSONResponse({'detail': error.detail}, status_code=error.status_code, headers=error.headers)
    except (RuntimeError, psycopg.Error, OSError):
        response = error_response(NativeAuthorizationError(503,'SERVICE_UNAVAILABLE')) if is_authorization_path(request.url.path) else JSONResponse({'detail': 'Team authentication unavailable'}, status_code=503)
    else:
        response = await call_next(request)
    if TEAM_AUTH.enabled:
        no_transform = 'no-transform' in {directive.strip().lower() for directive in response.headers.get('Cache-Control', '').split(',')}
        response.headers['Cache-Control'] = 'private, no-store' + (', no-transform' if no_transform else '')
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
    connect_sources = "'self'" + (' wss://' + TEAM_AUTH.public_origin.removeprefix('https://') if TEAM_AUTH.enabled else '')
    policy = studio_csp(connect_sources)
    if request.method == 'GET' and request.url.path == IPHONE_LOGIN_PAGE and response.status_code == 200:
        policy += ' ' + IPHONE_CALLBACK
    response.headers['Content-Security-Policy'] = policy
    return response


@app.exception_handler(psycopg.Error)
async def database_error(request, error):
    if is_authorization_path(request.url.path):return error_response(NativeAuthorizationError(503,'SERVICE_UNAVAILABLE'))
    if request.url.path.startswith(IPHONE_API_PREFIX):
        return JSONResponse({'detail': 'IPHONE_SERVICE_UNAVAILABLE'}, status_code=503)
    return JSONResponse({'detail': 'Database unavailable'}, status_code=503)


@app.exception_handler(OSError)
async def storage_error(request, error):
    if is_authorization_path(request.url.path):return error_response(NativeAuthorizationError(503,'SERVICE_UNAVAILABLE'))
    if request.url.path.startswith(IPHONE_API_PREFIX):
        return JSONResponse({'detail': 'IPHONE_SERVICE_UNAVAILABLE'}, status_code=503)
    return JSONResponse({'detail': 'Content storage unavailable'}, status_code=503)

@app.exception_handler(PrivateRecordError)
async def private_record_error(request,error):
    if is_authorization_path(request.url.path):return error_response(NativeAuthorizationError(503,'SERVICE_UNAVAILABLE'))
    if request.url.path.startswith(IPHONE_API_PREFIX):
        return JSONResponse({'detail': 'IPHONE_SERVICE_UNAVAILABLE'}, status_code=503)
    return JSONResponse({'detail':'Private records unavailable'},status_code=503)


@app.exception_handler(CodecError)
async def v2_wire_error(request,error):
    # An internal response-shape defect is never emitted as a loose DTO.
    return error_response(NativeAuthorizationError(503,'SERVICE_UNAVAILABLE'))


def authorize(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
    if credentials is None or not hmac.compare_digest(credentials.credentials.encode(), API_KEY.encode()):
        raise HTTPException(401, "Authentication required", headers={"WWW-Authenticate": "Bearer"})


@app.get("/health/live")
def live():
    return {"status": "alive"}


# This immutable identity belongs to the imported process, not the mutable current symlink.
import json as _release_json
import re as _release_re
_release_manifest=Path(__file__).resolve().parents[1]/'RELEASE.json'
_server_revision=_release_json.loads(_release_manifest.read_text()).get('commit','') if _release_manifest.is_file() else ''
SERVER_RELEASE_REVISION=_server_revision if _release_re.fullmatch(r'[a-f0-9]{40}',_server_revision) else None

@app.get("/health/ready")
def ready(response: Response):
    if SERVER_RELEASE_REVISION:response.headers['X-WegoH-Release']=SERVER_RELEASE_REVISION
    try:
        with psycopg.connect(DSN) as conn:
            conn.execute("SELECT checksum FROM dev_assets LIMIT 1")
            if TEAM_AUTH.enabled:
                conn.execute("SELECT account_a FROM team_friend_pairs LIMIT 1")
                conn.execute("SELECT room_id FROM team_rooms LIMIT 1")
                conn.execute("SELECT history_id FROM team_histories LIMIT 1")
            if TEAM_AUTH.iphone_sessions.origin:
                conn.execute("SELECT token_hash FROM iphone_sessions LIMIT 1")
                conn.execute("SELECT request_id FROM iphone_login_requests LIMIT 1")
            if conn.execute('SELECT count(*) FROM visited_places WHERE place IS NOT NULL OR protected IS NULL').fetchone()[0]:
                return JSONResponse({'status':'private-migration-required'},status_code=503)
            sample=conn.execute('SELECT creator_id,visit_id,protected FROM visited_places LIMIT 1').fetchone()
        cipher=VisitCipher()
        if sample:cipher.restore(*sample)
        with tempfile.TemporaryFile(dir=CONTENT) as probe:
            probe.write(b"ready")
        return {"status": "ready"}
    except (psycopg.Error, OSError, PrivateRecordError):
        return JSONResponse({"status": "unavailable"}, status_code=503)


@app.get("/v1/dev/status", dependencies=[Depends(authorize)])
def status():
    return {"stage": "pack-studio", "pack_publishing": True, "trip_rooms": False,
            "asset_limit_bytes": MAX_BYTES, "allowed_media_types": sorted(MEDIA_TYPES)}


@app.post("/v1/assets", dependencies=[Depends(authorize)], status_code=201)
async def upload(request: Request, content_type: Annotated[str | None, Header()] = None):
    media_type = (content_type or "").split(";", 1)[0].lower().strip()
    if media_type not in MEDIA_TYPES:
        raise HTTPException(415, "Unsupported media type")
    length = request.headers.get("content-length")
    if length is not None:
        try:
            declared = int(length)
        except ValueError:
            raise HTTPException(400, "Invalid content length")
        if declared < 0 or declared > MAX_BYTES:
            raise HTTPException(413, "Asset exceeds size limit")
    temporary = None
    try:
        digest = hashlib.sha256()
        size = 0
        with tempfile.NamedTemporaryFile(dir=CONTENT, prefix=".upload-", delete=False) as stream:
            temporary = Path(stream.name)
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_BYTES:
                    raise HTTPException(413, "Asset exceeds size limit")
                digest.update(chunk)
                stream.write(chunk)
            stream.flush()
            os.fsync(stream.fileno())
        if size == 0:
            raise HTTPException(400, "Empty asset")
        checksum = digest.hexdigest()
        # Hard-link publishes a complete file atomically, without replacing existing content.
        try:
            os.link(temporary, CONTENT / checksum)
        except FileExistsError:
            pass
        with psycopg.connect(DSN) as conn:
            row = conn.execute(
                "INSERT INTO dev_assets (checksum, media_type, byte_size) VALUES (%s,%s,%s) "
                "ON CONFLICT (checksum) DO UPDATE SET checksum=EXCLUDED.checksum "
                "RETURNING media_type, byte_size", (checksum, media_type, size)).fetchone()
        return {"id": checksum, "media_type": row[0], "byte_size": row[1]}
    except (psycopg.Error, OSError):
        raise HTTPException(503, "Asset storage unavailable")
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


@app.get("/v1/assets/{checksum}", dependencies=[Depends(authorize)])
def download(checksum: str):
    if len(checksum) != 64 or any(c not in "0123456789abcdef" for c in checksum):
        raise HTTPException(404, "Asset not found")
    try:
        with psycopg.connect(DSN) as conn:
            row = conn.execute("SELECT media_type FROM dev_assets WHERE checksum=%s", (checksum,)).fetchone()
        path = CONTENT / checksum
        if row is None or not path.is_file():
            raise HTTPException(404, "Asset not found")
        return FileResponse(path, media_type=row[0], filename=checksum,
                            headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"})
    except psycopg.Error:
        raise HTTPException(503, "Asset storage unavailable")


app.include_router(TEAM_AUTH.router())
app.include_router(TEAM_AUTH.iphone_sessions.router())
app.include_router(IPhonePush(TEAM_AUTH.iphone_sessions).router())
from manual_deployment import create_router as create_manual_deployment_router
app.include_router(create_manual_deployment_router(TEAM_AUTH))
app.include_router(TEAM_FUNCTIONAL.router())
app.include_router(TEAM_ROOM_MUSIC_ACCESS.router())
app.include_router(TEAM_ROOM_VOICE_ACCESS.router())
if TEAM_AUTH.enabled and TEAM_NATIVE_AUTHORIZATION.enabled:
    TEAM_NATIVE_AUTHORIZATION.verify_issuance_holds()
    app.include_router(TEAM_NATIVE_AUTHORIZATION.browser_router())
    app.include_router(TEAM_NATIVE_AUTHORIZATION.native_router())
from discovery_local_config import load as load_local_discovery
TEAM_AUTH.local_discovery=load_local_discovery(os.environ.get('WEGOH_DISCOVERY_LOCAL_CONFIG'))
app.include_router(create_discovery_router(TEAM_AUTH))
app.include_router(TEAM_FUEL.router())
app.include_router(TEAM_RECOMMENDATIONS.router())
app.include_router(TEAM_NATIVE_ACCESS.router())
app.include_router(create_friends_router(TEAM_AUTH, rooms=TEAM_ROOMS))
app.include_router(TEAM_ROOMS.router())
app.include_router(TEAM_TRIPS.router())
app.include_router(TEAM_MISSIONS.router())
app.include_router(TEAM_VEHICLE.router())
app.include_router(TEAM_DEVICE_COMMANDS.router())
app.include_router(TEAM_ROOM_MUSIC.router())
app.include_router(TEAM_VOICE.router())
app.include_router(TEAM_VOICE_CLIPS.router())
app.include_router(TEAM_HISTORY.router())
app.include_router(TEAM_HISTORY_REMIX.router())
app.include_router(TEAM_CAUTIONS.router())
app.include_router(TEAM_PHOTOS.router())
app.include_router(TEAM_STORY.router())
app.include_router(TEAM_CONTENT.router())
app.include_router(create_team_data_router(TEAM_AUTH))
app.include_router(create_router(DSN, CONTENT, TEAM_AUTH))
app.include_router(create_course_library_router(TEAM_AUTH))
app.include_router(create_music_link_preview_router(TEAM_AUTH))
from client_diagnostics import create_router as create_client_diagnostics_router
app.include_router(create_client_diagnostics_router(TEAM_AUTH, app))
@app.get('/')
def platform_home():
    return FileResponse(WEB/('studio.html' if TEAM_AUTH.enabled else 'platform.html'),media_type='text/html',headers={'Cache-Control':'no-store'})

app.mount('/', StaticFiles(directory=WEB, html=True), name='studio')

# Configured operational barrier is outside route/auth middleware; dev is unchanged.
from deployment_gate import install as install_deployment_gate
install_deployment_gate(app, SERVER_RELEASE_REVISION)
