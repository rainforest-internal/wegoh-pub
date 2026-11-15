"""Owner-filtered browser projection for native devices; no authority mutation.

Access/session/CSRF/current-member checks stay in TeamAuth. The core obtains the
existing installation advisory lock BEFORE lookup_owned_locked; it then calls
its _revoke/purge in the same tx. Neither helper grants whole-installation ban.
"""
from datetime import datetime,timezone
import re
import time
from psycopg.rows import dict_row
from native_access_policy import AUTHORIZATION_VERSION

class ManagementError(ValueError):
    def __init__(self):super().__init__('Invalid private device management boundary')

def _owner(owner):
    if type(owner) is not str or re.fullmatch(r'team-[a-f0-9]{40}',owner) is None:raise ManagementError()
    return owner

def list_owned(conn,owner,*,vehicle_name,now=None,limit=100):
    """Existing browser device shape, plus explicit the current public authorization version.

    Only this owner's live current personal slot is visible. Last-used time is
    not collected by this protocol and is honestly None, never invented. No key,
    certificate, grant ID, token, other owner or old personal receipt is exposed.
    The name is the owner's vehicle name for the installation (vehicle_name(key)),
    not the connection request label kept in the consent.
    """
    owner=_owner(owner);now=int(time.time()) if now is None else now
    if type(now) is not int or not 0<=now<=253402300799 or type(limit) is not int or not 1<=limit<=100:raise ManagementError()
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute("SELECT g.device_id,g.installation_key_id,g.expires_at,c.created_at "
            "FROM native_v2_grants g JOIN native_v2_connections c ON c.connection_id=g.connection_id "
            "JOIN native_v2_installations i ON i.installation_key_id=g.installation_key_id "
            "WHERE g.account_id=%s AND g.state='TOKEN_ISSUED' AND g.expires_at>%s "
            "AND i.revoked_at IS NULL AND i.active_grant_id=g.grant_id "
            "ORDER BY c.created_at DESC,g.device_id LIMIT %s",(owner,now,limit))
        rows=cursor.fetchall()
    result=[]
    for row in rows:
        name=vehicle_name(row['installation_key_id'])
        if type(name) is not str or not name:raise ManagementError()
        result.append(dict(id=row['device_id'],name=name,
            createdAt=datetime.fromtimestamp(row['created_at'],timezone.utc),lastUsedAt=None,
            expiresAt=datetime.fromtimestamp(row['expires_at'],timezone.utc),authorizationVersion=AUTHORIZATION_VERSION))
    return result

def lookup_owned_locked(conn,owner,device):
    """Exact owner+device row after the caller's installation lock, or None.

    Must be in a transaction. The owner is independently authenticated by the
    browser route; device/key/certificate possession cannot choose an account.
    No lookup by a caller-provided grantId or installation-wide delete exists.
    """
    owner=_owner(owner)
    if conn.autocommit:raise ManagementError()
    if type(device) is not str or re.fullmatch('[a-f0-9]{32}',device) is None:return None
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute('SELECT * FROM native_v2_grants WHERE account_id=%s AND device_id=%s '
            "AND state IN ('APPROVED','TOKEN_ISSUED','EXPIRED') FOR UPDATE",(owner,device))
        return cursor.fetchone()
