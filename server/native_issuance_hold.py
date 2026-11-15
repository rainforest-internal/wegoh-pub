"""Private issuance containment. Public API/version and caller roles grant no bypass."""
import hashlib,json,os,re
from dataclasses import dataclass,field
from cryptography import x509
from cryptography.hazmat.primitives import hashes,serialization
from enrollment_crypto import validate_csr,public_bytes,digest

class HoldError(ValueError):
    """Fixed internal class; no row, key, marker or provider input in errors."""
    def __init__(self,code):
        self.code=code
        super().__init__(code)

@dataclass(frozen=True)
class HoldExpectation:
    count:int
    digest:str

    def __post_init__(self):
        if type(self.count) is not int or not 0<=self.count<=1000 or type(self.digest) is not str or re.fullmatch('[a-f0-9]{64}',self.digest) is None:
            raise HoldError('HOLD_CONFIGURATION_REQUIRED')

    @classmethod
    def environment(cls,environ=None):
        env=os.environ if environ is None else environ
        count=env.get('WEGOH_RETIRED_ISSUANCE_EXPECTED_COUNT','')
        value=env.get('WEGOH_RETIRED_ISSUANCE_EXPECTED_DIGEST','')
        if type(count) is not str or re.fullmatch('0|[1-9][0-9]{0,3}',count) is None:raise HoldError('HOLD_CONFIGURATION_REQUIRED')
        return cls(int(count),value)

@dataclass(frozen=True)
class HoldState:
    count:int
    digest:str
    keys:frozenset=field(repr=False)

MARKER_FIELDS=frozenset(('enrollmentId','originalCipherSha256','caInventorySha256'))

def validate_marker(value):
    if type(value) is not dict or set(value)!=MARKER_FIELDS:raise HoldError('HOLD_COHORT_MISMATCH')
    for name,length in (('enrollmentId',32),('originalCipherSha256',64),('caInventorySha256',64)):
        if type(value[name]) is not str or re.fullmatch('[a-f0-9]{'+str(length)+'}',value[name]) is None:raise HoldError('HOLD_COHORT_MISMATCH')
    return dict(value)

def manifest_digest(descriptors):
    ordered=sorted(descriptors,key=lambda row:(row['installationKeyId'],row['enrollmentId']))
    return hashlib.sha256(json.dumps(ordered,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode('ascii')).hexdigest()

def _inspect_holds(conn,cipher,expectation):
    if not isinstance(expectation,HoldExpectation):raise HoldError('HOLD_CONFIGURATION_REQUIRED')
    # Only the retired enrollment store is involved; it conveys no personal grant.
    rows=conn.execute("SELECT enrollment_id,state,protected FROM vehicle_enrollments WHERE state IN ('issuing','uncertain') ORDER BY enrollment_id").fetchall()
    if len(rows)>1000:raise HoldError('HOLD_COHORT_MISMATCH')
    descriptors=[];keys=set()
    for row in rows:
        # Main service uses dict rows; the operator/restore path can use tuples.
        enrollment,state,protected=(row['enrollment_id'],row['state'],row['protected']) if isinstance(row,dict) else row
        if state!='uncertain':raise HoldError('HOLD_COHORT_MISMATCH')
        original=cipher.restore('enrollment',enrollment,protected)
        csr=validate_csr(original['csrPem']);key=digest(public_bytes(csr.public_key()))
        cert=conn.execute("SELECT installation_key_id,generation,current_generation,certificate_sha256,expires_at,protected_receipt,revoked_at FROM native_v2_certificate_recovery WHERE installation_key_id=%s AND generation=current_generation",(key,)).fetchone()
        if cert is None:raise HoldError('HOLD_COHORT_MISMATCH')
        if not isinstance(cert,dict):
            cert=dict(zip(('installation_key_id','generation','current_generation','certificate_sha256','expires_at','protected_receipt','revoked_at'),cert))
        outcome=cipher.restore('native-v2:generation',key+':'+str(cert['generation']),cert['protected_receipt'])
        marker=validate_marker(outcome.get('quarantinedEnrollment'))
        if marker['enrollmentId']!=enrollment or marker['originalCipherSha256']!=hashlib.sha256(bytes(protected)).hexdigest():raise HoldError('HOLD_COHORT_MISMATCH')
        receipt=outcome['receipt'];provenance=outcome['provenance']
        leaf=x509.load_pem_x509_certificate(receipt['certificatePem'].encode('ascii'))
        fingerprint=leaf.fingerprint(hashes.SHA256()).hex()
        if (leaf.subject!=csr.subject or public_bytes(leaf.public_key())!=public_bytes(csr.public_key())
            or fingerprint!=cert['certificate_sha256'] or fingerprint!=receipt['certificateSha256']
            or receipt['installationKeyId']!=key or receipt['generation']!=cert['generation']
            or int(leaf.not_valid_after_utc.timestamp())!=cert['expires_at'] or receipt['expiresAt']!=cert['expires_at']
            or provenance.get('source')!='authenticated-cloudflare-api' or provenance.get('certificateSha256')!=fingerprint
            or provenance.get('installationKeyId')!=key or not provenance.get('issuerId') or not provenance.get('certificateId')):
            raise HoldError('HOLD_COHORT_MISMATCH')
        descriptors.append(dict(marker,installationKeyId=key,certificateSha256=fingerprint));keys.add(key)
    result=HoldState(len(descriptors),manifest_digest(descriptors),frozenset(keys))
    if result.count!=expectation.count or result.digest!=expectation.digest:raise HoldError('HOLD_COHORT_MISMATCH')
    return result


def inspect_holds(conn,cipher,expectation):
    try:
        return _inspect_holds(conn,cipher,expectation)
    except HoldError:
        raise
    except Exception:
        raise HoldError('HOLD_COHORT_MISMATCH') from None

def require_new_issuance(conn,cipher,expectation,csr_pem):
    state=inspect_holds(conn,cipher,expectation)
    key=digest(public_bytes(validate_csr(csr_pem).public_key()))
    if key in state.keys:raise HoldError('HELD_ISSUANCE_KEY')
    return state
