"""Explicit v1 creation cutoff; existing absolute grants are never changed."""
import math
import os
import re
import time
from dataclasses import dataclass
from email.utils import formatdate
from fastapi import HTTPException
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID
from enrollment_crypto import digest,public_bytes
from private_records import VisitCipher

CUTOFF='WEGOH_LEGACY_NEW_DEVICE_CUTOFF'
SUNSET='WEGOH_LEGACY_ABSOLUTE_SUNSET'

@dataclass(frozen=True)
class LegacyTransition:
    cutoff:int
    sunset:int

    def __post_init__(self):
        if (type(self.cutoff) is not int or type(self.sunset) is not int
            or not 0<self.cutoff<=self.sunset<=253402300799):
            raise RuntimeError('Explicit legacy transition timestamps required')

    @classmethod
    def environment(cls,env=None,*,required=False):
        env=os.environ if env is None else env
        values=[env.get(CUTOFF,''),env.get(SUNSET,'')]
        if not any(values) and not required:return None
        if any(not isinstance(value,str) or re.fullmatch('[1-9][0-9]{0,11}',value) is None for value in values):
            raise RuntimeError('Explicit legacy transition timestamps required')
        return cls(*(int(value) for value in values))

    def creation_open(self,now=None):
        return (time.time() if now is None else now)<self.cutoff

    def require_creation(self,now=None):
        if not self.creation_open(now):
            raise HTTPException(410,'LEGACY_CONNECTION_UPGRADE_REQUIRED',headers={
                'Sunset':formatdate(self.sunset,usegmt=True),'Cache-Control':'no-store'})

    def verify_cohort(self,conn,*,cipher=None,now=None):
        now=time.time() if now is None else now
        if now<self.cutoff:raise RuntimeError('Legacy cutoff has not taken effect')
        cipher=cipher or VisitCipher()
        rows=conn.execute('SELECT device_id,account_id,protected,expires_at FROM team_devices '
            'WHERE revoked_at IS NULL AND expires_at>to_timestamp(%s)',(now,)).fetchall()
        maximum=max((math.ceil(row[3].timestamp()) for row in rows),default=self.cutoff)
        if maximum>self.sunset:raise RuntimeError('Legacy sunset precedes an existing absolute grant expiry')
        for device,owner,protected,expiry in rows:
            value=cipher.restore('team-device:'+owner,device,protected)
            fingerprint=value.get('nativeCertificateSha256')
            if not isinstance(fingerprint,str) or re.fullmatch('[a-f0-9]{64}',fingerprint) is None:
                raise RuntimeError('Legacy cohort certificate mapping incomplete')
            mapped=conn.execute('SELECT installation_key_id,expires_at,protected_provenance FROM native_v2_legacy_certificates '
                'WHERE certificate_sha256=%s',(fingerprint,)).fetchone()
            if not mapped or mapped[1]<=now:raise RuntimeError('Legacy cohort certificate mapping incomplete')
            provenance=cipher.restore('native-v2:legacy-certificate',fingerprint,mapped[2])
            identity=legacy_certificate(provenance.get('certificatePem'),now=now)
            if (provenance.get('source')!='authenticated-cloudflare-api' or not provenance.get('issuerId')
                or not provenance.get('certificateId') or identity['certificateSha256']!=fingerprint
                or identity['installationKeyId']!=mapped[0] or provenance.get('installationKeyId')!=mapped[0]
                or provenance.get('certificateSha256')!=fingerprint or identity['expiresAt']!=mapped[1]):
                raise RuntimeError('Legacy cohort certificate provenance mismatch')
        return {'activeLegacyDevices':len(rows),'mappedLegacyDevices':len(rows),'absoluteSunset':self.sunset,'maximumLegacyExpiry':maximum}

def legacy_certificate(pem,*,now=None):
    now=time.time() if now is None else now
    try:
        cert=x509.load_pem_x509_certificate(pem.encode('ascii'));key=cert.public_key()
        try:usage=cert.extensions.get_extension_for_class(x509.KeyUsage).value
        except x509.ExtensionNotFound:usage=None  # RFC5280: absent KU imposes no KU restriction.
        eku=cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
        basic=cert.extensions.get_extension_for_class(x509.BasicConstraints).value
        if (not isinstance(key,rsa.RSAPublicKey) or key.key_size!=2048 or key.public_numbers().e!=65537
            or basic.ca or usage is not None and (not usage.digital_signature or usage.key_cert_sign or usage.crl_sign)
            or ExtendedKeyUsageOID.CLIENT_AUTH not in eku or cert.subject==cert.issuer
            or cert.signature_hash_algorithm.name not in ('sha256','sha384','sha512')
            or cert.not_valid_before_utc.timestamp()>now or cert.not_valid_after_utc.timestamp()<=now):raise ValueError()
        return dict(certificatePem=pem,certificateSha256=cert.fingerprint(hashes.SHA256()).hex(),
            installationKeyId=digest(public_bytes(key)),expiresAt=int(cert.not_valid_after_utc.timestamp()))
    except Exception:raise RuntimeError('Legacy certificate identity unavailable') from None

def verify_activation(dsn,policy):
    if policy is None:raise RuntimeError('V2 activation requires explicit legacy transition policy')
    import psycopg
    with psycopg.connect(dsn) as conn:return policy.verify_cohort(conn)
