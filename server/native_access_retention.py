"""Targeted v2 personal-auth erasure and downward-only scope changes.

Caller authenticates the owner, validates current lifetime and holds the same
installation advisory lock + grant row lock in one transaction. No commits,
travel-record/key deletion, new grants, CA calls or public wire are performed.
"""
from dataclasses import dataclass
import copy
import re
from private_records import VisitCipher
from native_access_codec import canonical_base64url
from native_access_policy import KNOWN_SCOPES, MANDATORY_SCOPES, MAX_COUNTER


class RetentionError(ValueError):
    """Fixed existing wire code only; no personal or cryptographic input text."""
    def __init__(self, code):
        if code not in ('OPERATION_CONFLICT', 'CONSENT_CHANGED', 'SCOPE_DENIED'):
            raise ValueError('Internal retention error code')
        super().__init__(code)


def _restore(purpose, key, value):
    return VisitCipher().restore('native-v2:' + purpose, key, value)


def _protect(purpose, key, value):
    return VisitCipher().protect('native-v2:' + purpose, key, value)


def _current(conn, grant):
    if (conn.autocommit or type(grant) is not dict or type(grant.get('grant_id')) is not str
            or re.fullmatch('[a-f0-9]{32}', grant['grant_id']) is None):
        raise RetentionError('OPERATION_CONFLICT')
    current = conn.execute('SELECT * FROM native_v2_grants WHERE grant_id=%s FOR UPDATE',
                           (grant['grant_id'],)).fetchone()
    if not current or any(current[key] != grant.get(key) for key in ('grant_id', 'connection_id', 'installation_key_id')):
        raise RetentionError('OPERATION_CONFLICT')
    return current


def purge_grant_personal(conn, grant, *, revoked_at):
    """Erase the exact already-terminal grant's identifying/private auth content.

    Revoke capability hash, target/key, original expiry and terminal ack remain.
    Public CSR/proof/CA outcome/lease and all travel content are untouched. This
    live transaction is not proof of erasure from an existing backup/replica.
    """
    current = _current(conn, grant)
    if (current['state'] != 'REVOKED' or type(revoked_at) is not int
            or current['revoked_at'] != revoked_at):
        raise RetentionError('OPERATION_CONFLICT')
    connection = conn.execute('SELECT connection_id,installation_key_id,protected_request '
        'FROM native_v2_connections WHERE connection_id=%s FOR UPDATE', (current['connection_id'],)).fetchone()
    if not connection or connection['installation_key_id'] != current['installation_key_id']:
        raise RetentionError('OPERATION_CONFLICT')
    original = _restore('connection', connection['connection_id'], connection['protected_request'])
    if type(original) is not dict:
        raise RetentionError('OPERATION_CONFLICT')
    sanitized = {name:value for name,value in original.items()
                 if name not in ('name', 'legacyDeviceId', 'legacySource', '_legacySource', 'sourceLegacyDeviceId')}
    if sanitized != original:
        conn.execute('UPDATE native_v2_connections SET protected_request=%s WHERE connection_id=%s',
            (_protect('connection', connection['connection_id'], sanitized), connection['connection_id']))
    # Terminal base authority also erases the separately encrypted function consent.
    functional_table=conn.execute("SELECT to_regclass('public.native_functional_authorizations') AS name").fetchone()
    if (functional_table['name'] if isinstance(functional_table,dict) else functional_table[0]) is not None:
        conn.execute("UPDATE native_functional_authorizations SET state='REVOKED',protected=NULL WHERE grant_id=%s",(current['grant_id'],))
    conn.execute('DELETE FROM native_v2_credentials WHERE grant_id=%s', (current['grant_id'],))
    conn.execute('DELETE FROM native_v2_operations WHERE grant_id=%s', (current['grant_id'],))
    conn.execute("UPDATE native_v2_approvals SET state='REVOKED',protected_owner=NULL WHERE grant_id=%s",
                 (current['grant_id'],))
    conn.execute('UPDATE native_v2_grants SET account_id=NULL,protected_consent=NULL,recovery_hash=NULL '
                 "WHERE grant_id=%s AND state='REVOKED'", (current['grant_id'],))
    return dict(grantId=current['grant_id'], deviceId=current['device_id'],
                revokedAt=current['revoked_at'], expiresAt=current['expires_at'])


def active_capabilities(payload):
    """Read the existing full receipt or the new encrypted, noncredential carrier.

    Does not return an access/refresh token, account identity, name or old scopes.
    The caller must not return this internal dictionary as a public API receipt.
    """
    if type(payload) is not dict:
        raise RetentionError('OPERATION_CONFLICT')
    if set(payload) == {'capabilities'}:
        value = payload['capabilities']
    else:
        value = payload.get('credentialReceipt')
    if type(value) is not dict:
        raise RetentionError('OPERATION_CONFLICT')
    try:
        return {name:canonical_base64url(value[name], byte_length=32)
                for name in ('recoveryCapability', 'revokeCapability')}
    except (ValueError, TypeError, KeyError):
        raise RetentionError('OPERATION_CONFLICT') from None


def reduce_grant_scopes(conn, grant, scopes, *, expected_consent_version):
    """Apply only a current, downward scope change; return an internal decision.

    A terminal=True decision makes NO partial optional change. The core MUST
    call its _revoke + purge_grant_personal before committing the same tx. This
    keeps installation-slot/epoch authority in the owning core implementation.
    """
    current = _current(conn, grant)
    if (current['state'] not in ('APPROVED', 'TOKEN_ISSUED')
            or type(expected_consent_version) is not int
            or current['consent_version'] != expected_consent_version):
        raise RetentionError('CONSENT_CHANGED')
    if (type(scopes) is not list or any(type(scope) is not str for scope in scopes)
            or scopes != sorted(set(scopes)) or not set(scopes) <= KNOWN_SCOPES):
        raise RetentionError('SCOPE_DENIED')
    consent = _restore('consent', current['grant_id'], current['protected_consent'])
    existing = consent.get('scopes') if type(consent) is dict else None
    if (type(existing) is not list or any(type(scope) is not str for scope in existing)
            or existing != sorted(set(existing)) or not MANDATORY_SCOPES <= set(existing)
            or not set(existing) <= KNOWN_SCOPES):
        return dict(terminal=True, changed=False, reason='INVALID_EXISTING_CONSENT')
    if not set(scopes) <= set(existing):
        raise RetentionError('SCOPE_DENIED')
    if not MANDATORY_SCOPES <= set(scopes):
        return dict(terminal=True, changed=False, reason='REQUIRED_SCOPE_WITHDRAWN')
    if scopes == existing:
        return dict(terminal=False, changed=False, consentVersion=current['consent_version'],
                    credentialEpoch=current['credential_epoch'], scopes=scopes)
    if (current['consent_version'] >= 2147483647 or current['credential_epoch'] >= MAX_COUNTER
            or current['device_revision'] >= MAX_COUNTER):
        raise RetentionError('OPERATION_CONFLICT')
    operations = conn.execute('SELECT operation_id,action,protected_receipt FROM native_v2_operations '
        'WHERE grant_id=%s FOR UPDATE', (current['grant_id'],)).fetchall()
    originals = [row for row in operations if row['action'] == 'SESSION_EXCHANGE']
    if current['state'] == 'TOKEN_ISSUED' and len(originals) != 1:
        return dict(terminal=True, changed=False, reason='RECOVERY_STATE_UNAVAILABLE')
    carrier = None
    if originals:
        try:
            payload = _restore('operation', originals[0]['operation_id'], originals[0]['protected_receipt'])
            carrier = {'capabilities':active_capabilities(payload)}
        except RetentionError:
            return dict(terminal=True, changed=False, reason='RECOVERY_STATE_UNAVAILABLE')
    revised = copy.deepcopy(consent)
    revised['scopes'] = list(scopes)
    # Keep the original disclosure version/hash as the immutable notice the owner
    # read. Downward withdrawal is not a new consent or an expiry extension.
    updated = conn.execute('UPDATE native_v2_grants SET protected_consent=%s,consent_version=consent_version+1,'
        'credential_epoch=credential_epoch+1,device_revision=device_revision+1 WHERE grant_id=%s '
        'AND consent_version=%s RETURNING consent_version,credential_epoch,device_revision,expires_at',
        (_protect('consent', current['grant_id'], revised), current['grant_id'], expected_consent_version)).fetchone()
    if not updated or updated['expires_at'] != current['expires_at']:
        raise RetentionError('CONSENT_CHANGED')
    # Immediate data-path denial is the epoch bump, not token expiry. Purge old
    # access/refresh receipt bodies; retain only encrypted stable purpose secrets
    # needed by same-grant recovery and exact-device logout.
    conn.execute('DELETE FROM native_v2_credentials WHERE grant_id=%s', (current['grant_id'],))
    if originals:
        original = originals[0]
        conn.execute('UPDATE native_v2_operations SET protected_receipt=%s WHERE operation_id=%s',
            (_protect('operation', original['operation_id'], carrier), original['operation_id']))
        conn.execute('DELETE FROM native_v2_operations WHERE grant_id=%s AND operation_id<>%s',
                     (current['grant_id'], original['operation_id']))
    else:
        conn.execute('DELETE FROM native_v2_operations WHERE grant_id=%s', (current['grant_id'],))
    return dict(terminal=False, changed=True, consentVersion=updated['consent_version'],
                credentialEpoch=updated['credential_epoch'], scopes=list(scopes),
                expiresAt=current['expires_at'])
