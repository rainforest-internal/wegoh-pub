"""Single public v1 native scope policy.

A policy match is not authentication, ownership, membership or purpose consent.
Handlers must intersect all those checks with this exact deny-default policy.
Unknown credentials never select an older authentication branch.
"""
from dataclasses import dataclass
import re

AUTHORIZATION_VERSION = 1
MANDATORY_SCOPES = frozenset({'account:read', 'device:self:manage'})
OPTIONAL_SCOPES = frozenset({'account:write', 'courses:read', 'playlists:read'})
KNOWN_SCOPES = MANDATORY_SCOPES | OPTIONAL_SCOPES
RESOURCE_SCOPES = {'courses': 'courses:read', 'playlists': 'playlists:read',
                   'devices': 'device:self:manage'}
MAX_COUNTER = 9007199254740991


class ScopeDenied(ValueError):
    def __init__(self):
        super().__init__('SCOPE_DENIED')


class RouteDenied(ValueError):
    def __init__(self):
        super().__init__('ROUTE_NOT_FOUND')


def valid_grant_scopes(scopes):
    # Runtime sets come from a validated grant snapshot, never body/role inference.
    if (not isinstance(scopes, frozenset) or not MANDATORY_SCOPES <= scopes
            or not scopes <= KNOWN_SCOPES):
        raise ScopeDenied()
    return scopes


@dataclass(frozen=True)
class RouteRule:
    method: str
    template: str
    pattern: str
    scope: str


# Full matching only; no prefix/path normalization, arbitrary version or action.
ROUTES = (
    RouteRule('GET', '/v1/device/vehicle-profile', r'/v1/device/vehicle-profile', 'device:self:manage'),
    RouteRule('PUT', '/v1/device/vehicle-profile', r'/v1/device/vehicle-profile', 'device:self:manage'),
    RouteRule('GET', '/v1/device/command-receiver', r'/v1/device/command-receiver', 'device:self:manage'),
    RouteRule('PUT', '/v1/device/command-receiver', r'/v1/device/command-receiver', 'device:self:manage'),
    RouteRule('POST', '/v1/device/client-reports', r'/v1/device/client-reports', 'device:self:manage'),
    RouteRule('GET', '/v1/account', r'/v1/account', 'account:read'),
    RouteRule('PUT', '/v1/account', r'/v1/account', 'account:read'),
    RouteRule('GET', '/v1/packs', r'/v1/packs', 'courses:read'),
    RouteRule('GET', '/v1/native/courses/library', r'/v1/native/courses/library', 'courses:read'),
    RouteRule('POST', '/v1/native/courses/{pack_id}/versions/{version}/route-preview',
              r'/v1/native/courses/[a-z0-9][a-z0-9_-]{0,79}/versions/[1-9][0-9]{0,9}/route-preview', 'courses:read'),
    RouteRule('GET', '/v1/native/courses/public/{pack_id}/versions/{version}',
              r'/v1/native/courses/public/[a-z0-9][a-z0-9_-]{0,79}/versions/[1-9][0-9]{0,9}', 'courses:read'),
    RouteRule('GET', '/v1/native/courses/creators/{creator_id}', r'/v1/native/courses/creators/team-[a-f0-9]{40}', 'courses:read'),
    RouteRule('GET', '/v1/studio/packs', r'/v1/studio/packs', 'courses:read'),
    RouteRule('GET', '/v1/studio/packs/{pack_id}/versions/{version}',
              r'/v1/studio/packs/[a-z0-9][a-z0-9_-]{0,79}/versions/[1-9][0-9]{0,9}', 'courses:read'),
    RouteRule('GET', '/v1/packs/{pack_id}/versions/{version}',
              r'/v1/packs/[a-z0-9][a-z0-9_-]{0,79}/versions/[1-9][0-9]{0,9}', 'courses:read'),
    RouteRule('GET', '/v1/playlists', r'/v1/playlists', 'playlists:read'),
    RouteRule('GET', '/v1/playlists/{playlist_id}', r'/v1/playlists/[a-f0-9]{32}', 'playlists:read'),
    RouteRule('GET', '/v1/device/permissions', r'/v1/device/permissions', 'device:self:manage'),
    RouteRule('GET', '/v1/device/functional-permissions', r'/v1/device/functional-permissions', 'device:self:manage'),
    RouteRule('DELETE', '/v1/device', r'/v1/device', 'device:self:manage'),
    # Client failure reports carry route templates and decode rules only, never values.
    RouteRule('POST', '/v1/native/diagnostics', r'/v1/native/diagnostics', 'device:self:manage'),
)


def required_scope(method, path):
    if not isinstance(method, str) or not isinstance(path, str):
        raise RouteDenied()
    for rule in ROUTES:
        if method == rule.method and re.fullmatch(rule.pattern, path):
            if '/versions/' in path and int(path.split('/versions/', 1)[1].split('/', 1)[0]) > 2147483647:
                raise RouteDenied()
            return rule.scope
    raise RouteDenied()


def authorize_route(version, method, path, scopes):
    if type(version) is not int or version != AUTHORIZATION_VERSION:
        raise ScopeDenied()
    valid_grant_scopes(scopes)
    scope = required_scope(method, path)
    if scope not in scopes:
        raise ScopeDenied()
    return scope


def event_resources(version, method, path, scopes):
    if (type(version) is not int or version != AUTHORIZATION_VERSION
            or method != 'GET' or path != '/v1/events'):
        raise ScopeDenied()
    valid_grant_scopes(scopes)
    return tuple(sorted(name for name, scope in RESOURCE_SCOPES.items() if scope in scopes))


class EventProjection:
    """Construct invalidations, never forward arbitrary source-event dictionaries.

    Caller must authenticate/revalidate grant+epoch before every send and query
    changes only for the authorized account. Device changes also require an
    exact device id here; account-wide device revisions are not sufficient.
    """
    def __init__(self, scopes, epoch, device_id):
        self.resources = event_resources(AUTHORIZATION_VERSION, 'GET', '/v1/events', scopes)
        if (not isinstance(epoch, str) or not re.fullmatch(r'[a-f0-9]{16}', epoch)
                or not isinstance(device_id, str) or not re.fullmatch(r'[a-f0-9]{32}', device_id)):
            raise ValueError('INVALID_EVENT_BINDING')
        self.epoch, self.device_id, self.seq = epoch, device_id, 0

    def snapshot(self):
        return dict(type='snapshot', epoch=self.epoch, seq=self.seq, resources=list(self.resources))

    def heartbeat(self):
        return dict(type='heartbeat', epoch=self.epoch, seq=self.seq)

    def changed(self, resources, *, device_id=None):
        if not isinstance(resources, frozenset) or not resources <= RESOURCE_SCOPES.keys():
            raise ValueError('INVALID_EVENT_RESOURCE')
        allowed = resources & frozenset(self.resources)
        if device_id != self.device_id:
            allowed -= {'devices'}
        if not allowed:
            return None  # Hidden resources must not alter visible sequence numbers.
        if self.seq >= MAX_COUNTER:
            raise ValueError('EVENT_RECONNECT_REQUIRED')
        self.seq += 1
        return dict(type='invalidate', epoch=self.epoch, seq=self.seq, resources=sorted(allowed))


AUTHORIZATION_PATHS = (
    '/v1/connections', '/v1/device-authorizations', '/v1/device-sessions',
    '/v1/installations/certificate-recover', '/v1/installations/certificate-renew',
)

def is_authorization_path(path):
    return isinstance(path, str) and any(path == root or path.startswith(root + '/') for root in AUTHORIZATION_PATHS)


def is_retired_authorization_path(path):
    if not isinstance(path,str):return False
    return path == '/v2' or path.startswith('/v2/') or any(
        path == root or path.startswith(root + '/')
        for root in ('/v1/enrollments','/v1/devices/pairings','/v1/devices/token'))
