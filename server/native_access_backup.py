"""Personal-auth-free v2 backup projection; no source mutation or key deletion.

The caller holds the same exported readonly snapshot used by pg_dump. All v2
TABLE DATA is excluded from that dump; only this encrypted-manifest projection
is restored. Public CA ambiguity survives, personal authority never does.
"""
import base64
import copy
import json
import re
import os
from psycopg import sql
from private_records import VisitCipher
from native_issuance_hold import validate_marker,HoldError,HoldExpectation,inspect_holds

FORMAT = 'wegoh-native-v2-public-backup-v1'
MAX_BYTES = 3 * 1024 * 1024
# Never restore functional personal consent. The credential-free reference
# index remains ordinary dump data so existing business foreign keys survive.
FUNCTIONAL_PRIVATE = ('native_functional_authorizations','native_room_music_authorizations','native_room_voice_authorizations')
FUNCTIONAL_COLUMNS = ('grant_id','device_id','installation_key_id','revision','state','protected','expires_at')
ROOM_MUSIC_COLUMNS = ('grant_id','room_id','device_id','revision','state','protected','member_joined_at','expires_at')
ROOM_VOICE_COLUMNS = ROOM_MUSIC_COLUMNS # Exact same eight storage columns; separate private authority.
PRIVATE_COLUMNS = dict(zip(FUNCTIONAL_PRIVATE, (FUNCTIONAL_COLUMNS, ROOM_MUSIC_COLUMNS, ROOM_VOICE_COLUMNS)))
TABLES = ('native_v2_installations','native_v2_connections','native_v2_approvals',
          'native_v2_grants','native_v2_certificates','native_v2_credentials',
          'native_v2_operations','native_v2_legacy_certificates','native_v2_renewals')
COLUMNS = {
'installations':'installation_key_id revision current_generation slot_revision active_grant_id revoked_at created_at',
'connections':'connection_id operation_id installation_key_id kind user_code original_begin_hash code_challenge proof_nonce state expires_at next_poll created_at protected_request protected_certificate restart_hash restart_expires_at restart_consumed_at previous_connection_id',
'approvals':'connection_id grant_id state protected_owner approved_at exchange_expires_at',
'grants':'grant_id connection_id installation_key_id account_id device_id state credential_epoch consent_version expires_at revoked_at recovery_hash revoke_hash protected_consent device_revision',
'certificates':'installation_key_id generation generation_operation_id certificate_sha256 code_challenge proof_nonce expires_at protected_receipt',
'credentials':'grant_id device_id access_hash refresh_hash certificate_sha256 generation slot_revision credential_epoch access_expires_at',
'operations':'operation_id action request_hash grant_id installation_key_id credential_epoch slot_revision expires_at protected_receipt',
'legacy_certificates':'certificate_sha256 installation_key_id expires_at protected_provenance',
'renewals':'connection_id installation_key_id grant_id device_id installation_revision expected_generation slot_revision credential_epoch consent_version consent_hash protected_owner grant_expires_at expires_at',
}
COLUMNS = {'native_v2_'+name: tuple(columns.split()) for name,columns in COLUMNS.items()}
EMPTY = ('native_v2_approvals','native_v2_credentials','native_v2_operations','native_v2_renewals')
ORDER = ('native_v2_installations','native_v2_connections','native_v2_grants',
         'native_v2_certificates','native_v2_legacy_certificates')
PUBLIC_REQUEST = frozenset(('authorizationVersion','operationId','csrPem','codeChallenge','expectedGeneration','_revocationGrantHash'))
ACCOUNT_REQUEST = frozenset(('authorizationVersion','operationId','certificatePem','codeChallenge'))
RECEIPT = frozenset(('certificatePem','certificateSha256','installationKeyId','generation','generationOperationId','expiresAt'))
PROVENANCE = frozenset(('source','certificatePem','certificateSha256','installationKeyId','issuerId','expiresAt','certificateId'))

class BackupProjectionError(ValueError):
    def __init__(self): super().__init__('Native authentication backup policy mismatch; original preserved')

def _restore(purpose,key,value):
    return VisitCipher().restore('native-v2:'+purpose,key,value)

def _protect(purpose,key,value):
    return VisitCipher().protect('native-v2:'+purpose,key,value)

def _validate_revoke_link(value):
    if '_revocationGrantHash' in value and (type(value['_revocationGrantHash']) is not str
        or re.fullmatch('[a-f0-9]{64}',value['_revocationGrantHash']) is None):raise BackupProjectionError()

def _public_request(value,kind,*,strict=False):
    allowed=ACCOUNT_REQUEST if kind=='ACCOUNT' else PUBLIC_REQUEST
    public_key='certificatePem' if kind=='ACCOUNT' else 'csrPem'
    other='csrPem' if kind=='ACCOUNT' else 'certificatePem'
    if (kind not in ('INSTALL','ACCOUNT','RENEW') or type(value) is not dict
        or type(value.get(public_key)) is not str or other in value
        or strict and not set(value)<=allowed):raise BackupProjectionError()
    _validate_revoke_link(value)
    return {key:item for key,item in value.items() if key in allowed}

def _public_outcome(value):
    if type(value) is not dict or type(value.get('receipt')) is not dict:
        raise BackupProjectionError()
    receipt=value['receipt']
    if (set(receipt)!=RECEIPT or any(type(receipt[name]) is not str for name in RECEIPT-{'generation','expiresAt'})
        or any(type(receipt[name]) is not int for name in ('generation','expiresAt'))): raise BackupProjectionError()
    provenance=value.get('provenance')
    if type(provenance) is not dict or any(type(value) not in (str,int) for name,value in provenance.items() if name in PROVENANCE): raise BackupProjectionError()
    result={'receipt':copy.deepcopy(receipt),'provenance':{k:v for k,v in provenance.items() if k in PROVENANCE}}
    if 'legacy' in value:
        if type(value['legacy']) is not bool: raise BackupProjectionError()
        result['legacy']=value['legacy']
    if 'quarantinedEnrollment' in value:
        try:result['quarantinedEnrollment']=validate_marker(value['quarantinedEnrollment'])
        except HoldError:raise BackupProjectionError() from None
    return result

def _sanitize(table,row):
    row=dict(row)
    if table=='native_v2_connections':
        key=row['connection_id'];value=_restore('connection',key,row['protected_request'])
        row['protected_request']=_protect('connection',key,_public_request(value,row['kind']))
        # Restart tickets are purpose secrets, so a restored request must obtain
        # a fresh proof-checked ticket rather than resurrect an old capability.
        row['restart_hash']=row['restart_expires_at']=row['restart_consumed_at']=None
        if row['protected_certificate'] is not None:
            value=_restore('certificate',key,row['protected_certificate'])
            row['protected_certificate']=_protect('certificate',key,_public_outcome(value))
    elif table=='native_v2_certificates':
        key=row['installation_key_id']+':'+str(row['generation'])
        row['protected_receipt']=_protect('generation',key,_public_outcome(_restore('generation',key,row['protected_receipt'])))
    elif table=='native_v2_legacy_certificates':
        key=row['certificate_sha256'];value=_restore('legacy-certificate',key,row['protected_provenance'])
        if (type(value) is not dict or value.get('source')!='authenticated-cloudflare-api'
            or any(type(item) not in (str,int) for name,item in value.items() if name in PROVENANCE)): raise BackupProjectionError()
        row['protected_provenance']=_protect('legacy-certificate',key,{k:v for k,v in value.items() if k in PROVENANCE})
    return row

def _encode(value):
    if isinstance(value,(bytes,memoryview)):return {'bytea':base64.b64encode(bytes(value)).decode('ascii')}
    if value is None or type(value) in (str,int):return value
    raise BackupProjectionError()

def _decode(value):
    if type(value) is dict and set(value)=={'bytea'} and type(value['bytea']) is str:
        try:return base64.b64decode(value['bytea'],validate=True)
        except ValueError:raise BackupProjectionError() from None
    if value is None or type(value) in (str,int):return value
    raise BackupProjectionError()

def _rows(conn,table):
    with conn.cursor() as cursor:
        cursor.execute(sql.SQL('SELECT * FROM {} ORDER BY 1,2').format(sql.Identifier(table)))
        columns=[column.name for column in cursor.description]
        if tuple(columns)!=COLUMNS[table]:raise BackupProjectionError()
        return [dict(zip(columns,row)) if not isinstance(row,dict) else dict(row) for row in cursor.fetchall()]

def _functional_inventory(conn, *, require_empty=False):
    names={row[0] if not isinstance(row,dict) else row['tablename'] for row in conn.execute(
        "SELECT tablename FROM pg_tables WHERE schemaname='public' AND (tablename LIKE 'native_functional_%' OR tablename LIKE 'native_room_music_%')").fetchall()}
    if not names:return False
    # Older auth-free backups may predate room consent. Missing rows/tables never
    # authorize anything; unknown private schemas are still rejected closed.
    if not names<=set(FUNCTIONAL_PRIVATE) or ('native_room_music_authorizations' in names and 'native_functional_authorizations' not in names):raise BackupProjectionError()
    for name in sorted(names):
        cursor=conn.execute(sql.SQL('SELECT * FROM {} LIMIT 0').format(sql.Identifier(name)))
        if tuple(column.name for column in cursor.description)!=PRIVATE_COLUMNS[name]:raise BackupProjectionError()
        if require_empty and conn.execute(sql.SQL('SELECT 1 FROM {} LIMIT 1').format(sql.Identifier(name))).fetchone():raise BackupProjectionError()
    return True


def _inventory(conn):
    names={row[0] if not isinstance(row,dict) else row['tablename'] for row in conn.execute(
        "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename LIKE 'native_v2_%'").fetchall()}
    if not names:return False
    if names!=set(TABLES):raise BackupProjectionError()
    return True

def _hold_expectation():
    names=('WEGOH_RETIRED_ISSUANCE_EXPECTED_COUNT','WEGOH_RETIRED_ISSUANCE_EXPECTED_DIGEST')
    if any(name in os.environ for name in names) or os.environ.get('WEGOH_NATIVE_ACCESS_ENABLED','').lower() in ('1','true','yes'):
        try:return HoldExpectation.environment()
        except HoldError:raise BackupProjectionError() from None
    return None

def hold_manifest(payload):
    """Cross-check the archive against the independently configured root policy."""
    expected=_hold_expectation()
    value=payload.get('issuanceHold') if type(payload) is dict else None
    if value is None:
        if expected is not None:raise BackupProjectionError()
        return None
    if (type(value) is not dict or set(value)!={'count','digest'} or type(value['count']) is not int
        or not 0<=value['count']<=1000 or type(value['digest']) is not str
        or re.fullmatch('[a-f0-9]{64}',value['digest']) is None or expected is None
        or value!={'count':expected.count,'digest':expected.digest}):raise BackupProjectionError()
    return dict(value)

def _check_restored_holds(conn,payload):
    manifest=hold_manifest(payload)
    if manifest is not None:
        try:inspect_holds(conn,VisitCipher(),_hold_expectation())
        except HoldError:raise BackupProjectionError() from None

def capture_projection(conn):
    """Capture public crypto/terminal hashes only in the caller's snapshot.

    Returns None for a pre-v2 schema. A changed v2 inventory fails closed rather
    than silently dumping a future personal table or losing issuance evidence.
    """
    if not _inventory(conn):return None
    _functional_inventory(conn)
    source={table:_rows(conn,table) for table in TABLES}
    meaningful={row['installation_key_id'] for row in source['native_v2_connections']
                if row['state'] in ('ISSUED','ISSUING','UNCERTAIN')}
    keep={row['installation_key_id'] for row in source['native_v2_installations']
          if row['current_generation']>0 or row['revoked_at'] is not None or row['installation_key_id'] in meaningful}
    rows={table:[] for table in TABLES}
    for original in source['native_v2_installations']:
        if original['installation_key_id'] not in keep:continue
        row=dict(original);row['active_grant_id']=None
        # Slot/epoch separation is needed only if there was personal authority.
        if original['active_grant_id'] is not None:
            if row['slot_revision']>=9007199254740991:raise BackupProjectionError()
            row['slot_revision']+=1
        rows['native_v2_installations'].append(row)
    terminal=[]
    for original in source['native_v2_grants']:
        if original['installation_key_id'] not in keep or original['device_id'] is None or original['revoke_hash'] is None:continue
        row=dict(original);row['account_id']=row['protected_consent']=row['recovery_hash']=None
        row['state']='REVOKED'
        # 0 is an explicit restore-time marker, not a historical withdrawal claim.
        if original['state']!='REVOKED':row['revoked_at']=0;terminal.append(row['grant_id'])
        rows['native_v2_grants'].append(row)
    connections={row['connection_id']:row for row in source['native_v2_connections']}
    selected={row['connection_id'] for row in connections.values() if row['installation_key_id'] in keep
              and row['state'] in ('ISSUING','UNCERTAIN','ISSUED')}
    selected.update(row['connection_id'] for row in rows['native_v2_grants'])
    pending=list(selected)
    while pending:
        previous=connections[pending.pop()]['previous_connection_id']
        if previous is not None and previous not in selected:selected.add(previous);pending.append(previous)
    for key in selected:rows['native_v2_connections'].append(_sanitize('native_v2_connections',connections[key]))
    for table in ('native_v2_certificates','native_v2_legacy_certificates'):
        for row in source[table]:
            if table.endswith('legacy_certificates') or row['installation_key_id'] in keep:
                rows[table].append(_sanitize(table,row))
    encoded={table:[{key:_encode(row[key]) for key in COLUMNS[table]} for row in sorted(rows[table],key=lambda row:str(tuple(row[c] for c in COLUMNS[table][:2])))] for table in TABLES}
    payload={'format':FORMAT,'tables':encoded,'lockOnRestore':sorted(terminal)}
    expectation=_hold_expectation()
    if expectation is not None:
        try:state=inspect_holds(conn,VisitCipher(),expectation)
        except HoldError:raise BackupProjectionError() from None
        payload['issuanceHold']={'count':state.count,'digest':state.digest}
    if len(json.dumps(payload,separators=(',',':')).encode())>MAX_BYTES:raise BackupProjectionError()
    validate_projection(payload)
    return payload

def dump_exclusion_args():
    return ['--exclude-table-data=public.'+name for name in TABLES+FUNCTIONAL_PRIVATE]

def validate_projection(payload):
    if type(payload) is not dict or set(payload) not in ({'format','tables','lockOnRestore'},{'format','tables','lockOnRestore','issuanceHold'}) or payload['format']!=FORMAT:
        raise BackupProjectionError()
    manifest=hold_manifest(payload)
    if type(payload['tables']) is not dict or set(payload['tables'])!=set(TABLES):raise BackupProjectionError()
    if type(payload['lockOnRestore']) is not list or any(type(v) is not str for v in payload['lockOnRestore']):raise BackupProjectionError()
    if payload['lockOnRestore']!=sorted(set(payload['lockOnRestore'])):raise BackupProjectionError()
    decoded={}
    for table,values in payload['tables'].items():
        if type(values) is not list or (table in EMPTY and values):raise BackupProjectionError()
        decoded[table]=[]
        for value in values:
            if type(value) is not dict or set(value)!=set(COLUMNS[table]):raise BackupProjectionError()
            row={key:_decode(value[key]) for key in COLUMNS[table]}
            if table=='native_v2_installations' and row['active_grant_id'] is not None:raise BackupProjectionError()
            if table=='native_v2_grants' and (row['state']!='REVOKED' or row['account_id'] is not None
                or row['protected_consent'] is not None or row['recovery_hash'] is not None):raise BackupProjectionError()
            if table=='native_v2_connections':
                private=_restore('connection',row['connection_id'],row['protected_request'])
                _public_request(private,row['kind'],strict=True)
                if any(row[name] is not None for name in ('restart_hash','restart_expires_at','restart_consumed_at')):raise BackupProjectionError()
                if row['protected_certificate'] is not None:
                    value=_restore('certificate',row['connection_id'],row['protected_certificate'])
                    if value!=_public_outcome(value):raise BackupProjectionError()
            if table=='native_v2_certificates':
                key=row['installation_key_id']+':'+str(row['generation']);value=_restore('generation',key,row['protected_receipt'])
                if value!=_public_outcome(value):raise BackupProjectionError()
                if 'quarantinedEnrollment' in value and manifest is None:raise BackupProjectionError()
            if table=='native_v2_legacy_certificates':
                value=_restore('legacy-certificate',row['certificate_sha256'],row['protected_provenance'])
                if type(value) is not dict or not set(value)<=PROVENANCE or value.get('source')!='authenticated-cloudflare-api':raise BackupProjectionError()
            decoded[table].append(row)
    grant_ids={row['grant_id'] for row in decoded['native_v2_grants']}
    if not set(payload['lockOnRestore'])<=grant_ids:raise BackupProjectionError()
    return decoded

def restore_projection(conn,payload,*,restored_at):
    """Restore into an empty scratch/dedicated database, never a live mutation.

    All personal sessions remain terminal. The exact old revoke hash can only
    acknowledge logout, never restore account access; fresh phone consent is
    required. No CA request or personal authority is recreated here.
    """
    if type(restored_at) is not int or not 0<restored_at<=253402300799 or conn.autocommit:raise BackupProjectionError()
    rows=validate_projection(payload)
    if not _inventory(conn):raise BackupProjectionError()
    _functional_inventory(conn,require_empty=True)
    if any(_rows(conn,table) for table in TABLES):raise BackupProjectionError()
    for row in rows['native_v2_grants']:
        if row['grant_id'] in payload['lockOnRestore']:row['revoked_at']=restored_at
    # Self-referencing restart chains are inserted in dependency order.
    waiting=rows['native_v2_connections'];ordered=[];seen=set()
    while waiting:
        ready=[row for row in waiting if row['previous_connection_id'] is None or row['previous_connection_id'] in seen]
        if not ready:raise BackupProjectionError()
        for row in ready:ordered.append(row);seen.add(row['connection_id']);waiting.remove(row)
    rows['native_v2_connections']=ordered
    for table in ORDER:
        names=COLUMNS[table]
        statement=sql.SQL('INSERT INTO {} ({}) VALUES ({})').format(sql.Identifier(table),
            sql.SQL(',').join(map(sql.Identifier,names)),sql.SQL(',').join(sql.Placeholder() for _ in names))
        for row in rows[table]:conn.execute(statement,[row[name] for name in names])
    validate_restored_projection(conn,payload,restored_at=restored_at)
    return {'personalSessionsRestored':0,'publicCertificates':len(rows['native_v2_certificates']),
            'terminalAcknowledgements':len(rows['native_v2_grants'])}

def validate_restored_projection(conn,payload,*,restored_at):
    _functional_inventory(conn,require_empty=True)
    expected=validate_projection(payload)
    for row in expected['native_v2_grants']:
        if row['grant_id'] in payload['lockOnRestore']:row['revoked_at']=restored_at
    for table in TABLES:
        actual=_rows(conn,table)
        key=lambda row:repr(tuple(row[name] for name in COLUMNS[table]))
        if sorted(actual,key=key)!=sorted(expected[table],key=key):raise BackupProjectionError()
    _check_restored_holds(conn,payload)
    return True
