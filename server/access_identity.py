"""Cloudflare Access origin verification without database/web-framework imports."""
import hashlib
import json
from pathlib import Path
import re
import stat
from urllib.parse import urlsplit


class AccessIdentityError(Exception):
    def __init__(self, status_code, detail):
        self.status_code, self.detail = status_code, detail
        super().__init__(detail)


EMAIL = re.compile(r'[^\s@]{1,64}@[^\s@]{1,190}')


def origin_url(value, *, issuer=False):
    parsed = urlsplit(value)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.path or parsed.query or parsed.fragment or parsed.port not in (None, 443)):
        raise RuntimeError('An exact HTTPS origin is required')
    if issuer and not re.fullmatch(r'[a-z0-9-]+\.cloudflareaccess\.com', parsed.hostname):
        raise RuntimeError('An exact Cloudflare Access team issuer is required')
    if value != 'https://' + parsed.hostname:
        raise RuntimeError('Use the canonical HTTPS origin without path or port')
    return value


class AccessVerifier:
    def __init__(self, issuer, audience, members_file):
        self.issuer = origin_url(issuer, issuer=True)
        self.audience = audience
        if not re.fullmatch(r'[A-Za-z0-9_.-]{16,256}', audience):
            raise RuntimeError('An exact Access application audience is required')
        self.members_file = Path(members_file)
        self.members()
        from jwt import PyJWKClient
        # Bounded key-set TTL. Expired cache/network failure is not a pass.
        self.jwks = PyJWKClient(self.issuer + '/cdn-cgi/access/certs',
                              cache_jwk_set=True, lifespan=300, timeout=5)

    def members(self):
        try:
            info = self.members_file.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o007 or info.st_mode & 0o022:
                raise ValueError('Unsafe member file')
            raw = self.members_file.read_bytes()
            if len(raw) > 65536:
                raise ValueError('Member file too large')
            rows = json.loads(raw)
            if not isinstance(rows, list) or not 1 <= len(rows) <= 50:
                raise ValueError('Invalid team member list')
            members = {}
            for row in rows:
                if (not isinstance(row, dict) or set(row) != {'email', 'name', 'role'}
                        or row['role'] not in ('viewer', 'creator', 'admin')
                        or not isinstance(row['email'], str)
                        or not EMAIL.fullmatch(row['email'])
                        or not isinstance(row['name'], str) or not 1 <= len(row['name'].strip()) <= 64
                        or any(ord(c) < 32 for c in row['name'])):
                    raise ValueError('Invalid team member')
                email = row['email'].casefold()
                if email in members:
                    raise ValueError('Duplicate member')
                members[email] = dict(name=row['name'].strip(), role=row['role'])
            return members
        except (OSError, ValueError, TypeError) as error:
            raise RuntimeError('Team member configuration unavailable') from error

    def identity(self, headers, *, unlisted_member=None):
        import jwt
        # HTTPMessage and Starlette Headers both implement case-insensitive get.
        token = headers.get('cf-access-jwt-assertion', '')
        if not token or len(token) > 16384:
            raise AccessIdentityError(401, 'Access authentication required')
        try:
            key = self.jwks.get_signing_key_from_jwt(token)
            claims = jwt.decode(token, key.key, algorithms=['RS256'], issuer=self.issuer,
                audience=self.audience, options={'require': ['iss', 'aud', 'sub', 'exp', 'iat', 'email']})
            if (not isinstance(claims['sub'], str) or not 1 <= len(claims['sub']) <= 255
                    or not isinstance(claims['email'], str)
                    or type(claims['exp']) not in (int, float) or type(claims['iat']) not in (int, float)):
                raise jwt.InvalidTokenError('Invalid identity')
        except jwt.PyJWKClientConnectionError:
            raise AccessIdentityError(503, 'Access verification unavailable') from None
        except jwt.PyJWTError:
            raise AccessIdentityError(401, 'Access authentication invalid') from None
        email = claims['email'].casefold()
        subject = claims['sub']
        account = 'team-' + hashlib.sha256((self.issuer + '\0' + subject).encode()).hexdigest()[:40]
        member = self.members().get(email)
        unlisted = member is None
        if unlisted:
            if (unlisted_member is None or claims.get('type') != 'app' or 'common_name' in claims
                    or not EMAIL.fullmatch(email) or not email.isprintable()):
                raise AccessIdentityError(403, 'Team access denied')
            member = unlisted_member(account, email, subject)
        identity = dict(id=account, displayName=member['name'], role=member['role'],
                        email=email, subject=subject)
        if unlisted:
            identity['accessSelfEnrolled'] = True
        return identity
