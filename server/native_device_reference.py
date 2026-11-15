"""Credential-free relational references; never an authentication source."""
from native_functional_policy import identifier,FunctionalError
def register_native(conn,grant):
 device=identifier(grant['device_id'])
 if grant['state']!='TOKEN_ISSUED':raise FunctionalError(401,'INVALID_CREDENTIAL')
 if conn.execute('SELECT 1 FROM team_devices WHERE device_id=%s',(device,)).fetchone():raise FunctionalError(503,'DEVICE_REFERENCE_COLLISION')
 conn.execute("INSERT INTO native_device_refs(device_id,kind)VALUES(%s,'native')ON CONFLICT DO NOTHING",(device,))
 row=conn.execute('SELECT kind FROM native_device_refs WHERE device_id=%s',(device,)).fetchone()
 kind=row['kind'] if isinstance(row,dict)else row[0]
 if kind!='native':raise FunctionalError(503,'DEVICE_REFERENCE_COLLISION')
def require_native_reference(conn,device):
 row=conn.execute("SELECT 1 FROM native_device_refs WHERE device_id=%s AND kind='native'",(identifier(device),)).fetchone()
 if not row:raise FunctionalError(503,'DEVICE_REFERENCE_MISSING')
