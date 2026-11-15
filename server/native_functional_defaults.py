from private_records import VisitCipher
from native_functional_policy import WIRE

INITIAL_PURPOSES = ('device-commands:receive', 'friends:read', 'history:read', 'room-music:read', 'room-voice:receive', 'room-voice:transmit', 'rooms:interact', 'rooms:read')

ACCOUNT_PURPOSES = frozenset({
    'friends:read', 'friends:manage', 'rooms:read', 'rooms:interact',
    'history:read', 'missions:read', 'recommendations:use', 'cautions:read',
})


def account_purposes(approved):
    return ACCOUNT_PURPOSES.union(approved)


def ensure_receive_default(cursor,grant):
 if cursor.execute('SELECT 1 FROM native_functional_authorizations WHERE grant_id=%s',(grant['grant_id'],)).fetchone():return
 payload=dict(approvedPurposes=list(INITIAL_PURPOSES),functionalDisclosureVersion=WIRE['disclosureVersion'],functionalDisclosureSha256=WIRE['disclosureSha256'])
 protected=VisitCipher().protect('native-functional',grant['grant_id'],payload)
 cursor.execute("INSERT INTO native_functional_authorizations(grant_id,device_id,installation_key_id,revision,state,protected,expires_at)VALUES(%s,%s,%s,1,'ACTIVE',%s,%s)ON CONFLICT(grant_id)DO NOTHING",(grant['grant_id'],grant['device_id'],grant['installation_key_id'],protected,grant['expires_at']))
