import hashlib
import re

from fastapi import HTTPException
from private_records import VisitCipher

HANDLE = re.compile(r'[a-z0-9][a-z0-9_.]{2,19}', re.ASCII)


def default_handle(account, attempt=0):
    digest = hashlib.md5(f'{account}:{attempt}'.encode(), usedforsecurity=False).hexdigest()
    return 'user_' + digest[:15]


def create_account(conn, account, protected):
    for attempt in range(100):
        handle = default_handle(account, attempt)
        row = conn.execute('INSERT INTO team_accounts(account_id,handle,protected) VALUES(%s,%s,%s) '
            'ON CONFLICT(lower(handle)) DO NOTHING RETURNING handle', (account, handle, protected)).fetchone()
        if row:
            return row[0]
    raise HTTPException(503, 'ACCOUNT_HANDLE_UNAVAILABLE')


def normalize_handle(value):
    if not isinstance(value, str) or not value.isascii():
        raise HTTPException(400, 'INVALID_HANDLE')
    value = value.removeprefix('@').lower()
    if not HANDLE.fullmatch(value):
        raise HTTPException(400, 'INVALID_HANDLE')
    return value


def account_person(conn, account, *, lock=False):
    row = conn.execute('SELECT handle,protected FROM team_accounts '
        "WHERE account_id=%s AND account_status='active'" + (' FOR SHARE' if lock else ''),
        (account,)).fetchone()
    if not row:
        return None
    saved = VisitCipher().restore('team-account:' + account, 'identity', row[1])
    return dict(id=account, name=saved.get('displayName') or '@' + row[0], handle=row[0])
