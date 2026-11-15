"""Authenticated encryption for private visit content, separate from public packs."""
import json
import os
from pathlib import Path
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag

class PrivateRecordError(RuntimeError):
    pass


class VisitCipher:
    def __init__(self, path=None):
        try:
            file=Path(path or os.environ['WEGOH_VISIT_KEY_FILE'])
            if file.stat().st_mode & 0o007:raise ValueError('Unsafe key permissions')
            key=file.read_bytes()
            if len(key)!=32:raise ValueError('Invalid key length')
            self.cipher=AESGCM(key)
        except (KeyError,OSError,ValueError) as error:raise PrivateRecordError('Private record key unavailable') from error

    def protect(self, owner, visit_id, record):
        aad=f'wegoh.visit.v1:{owner}:{visit_id}'.encode()
        nonce=os.urandom(12)
        raw=json.dumps(record,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
        return b'WV01'+nonce+self.cipher.encrypt(nonce,raw,aad)

    def restore(self, owner, visit_id, protected):
        try:
            protected=bytes(protected)
            if len(protected)<32 or protected[:4]!=b'WV01':raise ValueError('Invalid private record')
            return json.loads(self.cipher.decrypt(protected[4:16],protected[16:],f'wegoh.visit.v1:{owner}:{visit_id}'.encode()))
        except (ValueError,TypeError,InvalidTag) as error:raise PrivateRecordError('Private record integrity check failed') from error


def migrate_private_visits(dsn):
    """Verify exact restoration before removing legacy plaintext in one DB transaction."""
    import psycopg
    cipher=VisitCipher()
    with psycopg.connect(dsn) as conn:
        conn.execute('LOCK TABLE visited_places IN SHARE ROW EXCLUSIVE MODE')
        rows=conn.execute('SELECT visit_id,creator_id,place,visited_at FROM visited_places WHERE place IS NOT NULL FOR UPDATE').fetchall()
        for visit_id,owner,place,visited_at in rows:
            original=dict(place=place,visitedAt=visited_at)
            encrypted=cipher.protect(owner,visit_id,original)
            if cipher.restore(owner,visit_id,encrypted)!=original:raise ValueError('Private record migration verification failed')
            conn.execute('UPDATE visited_places SET place=NULL,visited_at=1,protected=%s WHERE visit_id=%s',(encrypted,visit_id))
    return len(rows)


if __name__=='__main__':
    print('Verified and encrypted legacy visits:',migrate_private_visits(os.environ['WEGOH_DATABASE_DSN']))
