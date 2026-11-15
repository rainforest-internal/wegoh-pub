"""CSR validation and server-only Cloudflare managed-CA issuance.

Client issuer provenance comes from the authenticated Cloudflare API response,
not Android's server trust store or a fabricated Origin CA certificate chain.
"""
import base64
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import ssl
import stat
from datetime import datetime, timezone

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID, SignatureAlgorithmOID

ID = re.compile(r'[a-f0-9]{32}')
CODE = re.compile(r'[A-HJ-NP-Z2-9]{8}')
B64 = re.compile(r'[A-Za-z0-9_-]{43}')
VERIFIER = re.compile(r'[A-Za-z0-9._~-]{43,128}')
CF_ID = re.compile(r'[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}')
MAX_PEM = 8192


class EnrollmentError(ValueError):
    """Fixed code only: never reflect crypto input, PEM, credentials or upstream errors."""


class IssuanceUncertain(RuntimeError):
    """The upstream may have issued a certificate. Never automatically POST again."""


def digest(value):
    return hashlib.sha256(value).hexdigest()


def challenge(verifier):
    if not isinstance(verifier, str) or not VERIFIER.fullmatch(verifier):
        raise EnrollmentError('INVALID_PROOF')
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode('ascii')).digest()).decode().rstrip('=')


def public_bytes(key):
    return key.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)


def validate_csr(pem):
    try:
        if (not isinstance(pem, str) or len(pem.encode()) > MAX_PEM
                or pem.count('-----BEGIN CERTIFICATE REQUEST-----') != 1
                or not re.fullmatch(r'-----BEGIN CERTIFICATE REQUEST-----[A-Za-z0-9+/=\r\n]+-----END CERTIFICATE REQUEST-----\s*', pem)):
            raise ValueError()
        csr = x509.load_pem_x509_csr(pem.encode('ascii'))
        key = csr.public_key()
        cn = csr.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
        if (not csr.is_signature_valid or csr.signature_algorithm_oid != SignatureAlgorithmOID.RSA_WITH_SHA256
                or not isinstance(key, rsa.RSAPublicKey) or key.key_size != 2048
                or key.public_numbers().e != 65537 or len(csr.subject) != 1 or len(cn) != 1
                or not re.fullmatch(r'WegoH-[a-f0-9]{32}', cn[0].value)
                or len(csr.extensions) or len(csr.attributes)):
            raise ValueError()
        return csr
    except (ValueError, TypeError, UnicodeError, x509.DuplicateExtension):
        raise EnrollmentError('INVALID_CSR') from None


def proof_message(enrollment_id, nonce, code_challenge):
    if not ID.fullmatch(enrollment_id) or not B64.fullmatch(nonce) or not B64.fullmatch(code_challenge):
        raise EnrollmentError('INVALID_PROOF')
    return f'WegoH enrollment v1\n{enrollment_id}\n{nonce}\n{code_challenge}'.encode('ascii')


def verify_proof(csr, message, signature):
    try:
        if not isinstance(signature, str) or not re.fullmatch(r'[A-Za-z0-9_-]{342}', signature):
            raise ValueError()
        raw = base64.urlsafe_b64decode(signature + '==')
        if len(raw) != 256 or base64.urlsafe_b64encode(raw).decode().rstrip('=') != signature:
            raise ValueError()
        csr.public_key().verify(raw, message, padding.PKCS1v15(), hashes.SHA256())
    except Exception:
        raise EnrollmentError('INVALID_PROOF') from None


def validate_issued(csr, result, expected_ca, now=None):
    """Validate an authenticated managed-CA response; this is not PKIX server trust."""
    try:
        pem = result['certificate']
        ca = result['certificate_authority']
        if (not isinstance(pem, str) or len(pem.encode()) > MAX_PEM
                or pem.count('-----BEGIN CERTIFICATE-----') != 1
                or not re.fullmatch(r'-----BEGIN CERTIFICATE-----[A-Za-z0-9+/=\r\n]+-----END CERTIFICATE-----\s*', pem)
                or result['status'] != 'active' or ca['id'] != expected_ca
                or not CF_ID.fullmatch(result['id'])):
            raise ValueError()
        cert = x509.load_pem_x509_certificate(pem.encode('ascii'))
        now = now or datetime.now(timezone.utc)
        constraints = cert.extensions.get_extension_for_class(x509.BasicConstraints).value
        try:
            usage = cert.extensions.get_extension_for_class(x509.KeyUsage).value
        except x509.ExtensionNotFound:
            usage = None  # RFC5280/9846: leaf KU may be absent; present restrictions remain.
        extended = cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
        fingerprint = cert.fingerprint(hashes.SHA256()).hex()
        if (constraints.ca or usage is not None and (not usage.digital_signature or usage.key_cert_sign or usage.crl_sign)
                or ExtendedKeyUsageOID.CLIENT_AUTH not in extended
                or cert.not_valid_before_utc > now or cert.not_valid_after_utc <= now
                or cert.subject != csr.subject or cert.issuer == cert.subject
                or public_bytes(cert.public_key()) != public_bytes(csr.public_key())
                or result.get('fingerprint_sha256') != fingerprint
                or cert.signature_hash_algorithm.name not in ('sha256', 'sha384', 'sha512')):
            raise ValueError()
        return dict(certificatePem=cert.public_bytes(serialization.Encoding.PEM).decode('ascii'),
            certificateSha256=fingerprint, issuerId=expected_ca,
            expiresAt=cert.not_valid_after_utc.isoformat(), certificateId=result['id'])
    except Exception:
        raise EnrollmentError('INVALID_ISSUANCE_RECEIPT') from None


def read_cf_token(path):
    try:
        fd = os.open(Path(path), os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, 'r', encoding='ascii') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) not in (0o400, 0o600) or info.st_uid != os.geteuid() or info.st_size > 1025:
                raise ValueError()
            token = stream.read(1025).strip()
        if not re.fullmatch(r'[A-Za-z0-9_-]{20,1024}', token):
            raise ValueError()
        return token
    except (OSError, ValueError, UnicodeError):
        raise EnrollmentError('ISSUER_CREDENTIAL_UNAVAILABLE') from None

class CloudflareIssuer:
    """No redirects, retries, client-supplied URLs or client-visible API credentials."""
    def __init__(self, zone, ca_id, token_file):
        if not ID.fullmatch(zone) or not CF_ID.fullmatch(ca_id):
            raise EnrollmentError('INVALID_ISSUER_CONFIGURATION')
        self.zone, self.ca_id, self.token_file = zone, ca_id, Path(token_file)
        self._token()

    @classmethod
    def configured(cls):
        values = [os.environ.get(n, '') for n in ('WEGOH_ENROLLMENT_ZONE_ID',
            'WEGOH_ENROLLMENT_CA_ID', 'WEGOH_ENROLLMENT_CF_TOKEN_FILE')]
        if not all(values):
            return None
        return cls(*values)

    def _token(self):
        return read_cf_token(self.token_file)

    def issue(self, csr_pem):
        csr = validate_csr(csr_pem)
        conn = None
        try:
            context = ssl.create_default_context()
            context.minimum_version = context.maximum_version = ssl.TLSVersion.TLSv1_3
            conn = http.client.HTTPSConnection('api.cloudflare.com', timeout=15, context=context)
            payload = json.dumps(dict(csr=csr_pem, validity_days=90)).encode('utf-8')
            conn.request('POST', f'/client/v4/zones/{self.zone}/client_certificates', body=payload,
                headers={'Authorization': 'Bearer ' + self._token(), 'Content-Type': 'application/json'})
            response = conn.getresponse()
            raw = response.read(262145)
            if response.status != 200 or len(raw) > 262144:
                raise ValueError()
            value = json.loads(raw)
            if value.get('success') is not True:
                raise ValueError()
            return validate_issued(csr, value['result'], self.ca_id)
        except Exception:
            raise IssuanceUncertain('ISSUANCE_UNCERTAIN') from None
        finally:
            if conn is not None:
                conn.close()


    def reconcile(self, csr_pem, excluded_fingerprints=()):
        """Authenticated read-only CA reconciliation; never issues or retries POST."""
        csr = validate_csr(csr_pem)
        if (not isinstance(excluded_fingerprints, (set, frozenset, tuple, list))
                or any(not isinstance(x, str) or not re.fullmatch(r'[a-f0-9]{64}', x) for x in excluded_fingerprints)):
            raise EnrollmentError('INVALID_ISSUANCE_RECEIPT')
        matches = {}
        try:
            context = ssl.create_default_context()
            context.minimum_version = context.maximum_version = ssl.TLSVersion.TLSv1_3
            for page in range(1, 6):
                connection = http.client.HTTPSConnection('api.cloudflare.com', timeout=15, context=context)
                try:
                    connection.request('GET', f'/client/v4/zones/{self.zone}/client_certificates?status=active&per_page=50&page={page}',
                        headers={'Authorization': 'Bearer ' + self._token(), 'Accept': 'application/json'})
                    response = connection.getresponse()
                    raw = response.read(1048577)
                    if response.status != 200 or len(raw) > 1048576:
                        raise ValueError()
                    value = json.loads(raw)
                finally:
                    connection.close()
                if value.get('success') is not True or not isinstance(value.get('result'), list):
                    raise ValueError()
                info = value.get('result_info', {})
                if (type(info.get('total_pages')) is not int or not 0 <= info['total_pages'] <= 5
                        or info.get('page') != page):
                    raise ValueError()
                for item in value['result']:
                    if not isinstance(item, dict):
                        raise ValueError()
                    if (item.get('status') != 'active' or not isinstance(item.get('certificate_authority'), dict)
                            or item['certificate_authority'].get('id') != self.ca_id):
                        continue
                    try:
                        result = validate_issued(csr, item, self.ca_id)
                    except EnrollmentError:
                        continue
                    if result['certificateSha256'] not in excluded_fingerprints:
                        matches[result['certificateSha256']] = result
                if page >= info['total_pages']:
                    break
            if len(matches) > 1:
                raise ValueError()
            return next(iter(matches.values()), None)
        except Exception:
            raise IssuanceUncertain('ISSUANCE_UNCERTAIN') from None


    def require_active_certificate(self, provenance, installation_key_id, fingerprint):
        """Authenticated exact CA status, allowing normal expiry but never revocation.

        Primary contract: Cloudflare Client Certificate Details GET. An HTTP or
        network failure is unknown, not a revoked-state assertion.
        """
        try:
            certificate_id=provenance['certificateId']
            if (not isinstance(certificate_id,str) or not CF_ID.fullmatch(certificate_id)
                or provenance.get('issuerId')!=self.ca_id
                or not isinstance(installation_key_id,str) or not re.fullmatch(r'[a-f0-9]{64}',installation_key_id)
                or not isinstance(fingerprint,str) or not re.fullmatch(r'[a-f0-9]{64}',fingerprint)):
                raise EnrollmentError('INVALID_ISSUANCE_RECEIPT')
            context=ssl.create_default_context()
            context.minimum_version=context.maximum_version=ssl.TLSVersion.TLSv1_3
            connection=http.client.HTTPSConnection('api.cloudflare.com',timeout=15,context=context)
            try:
                connection.request('GET',f'/client/v4/zones/{self.zone}/client_certificates/{certificate_id}',
                    headers={'Authorization':'Bearer '+self._token(),'Accept':'application/json'})
                response=connection.getresponse();raw=response.read(262145)
                if response.status!=200 or len(raw)>262144:raise ValueError()
                payload=json.loads(raw)
            finally:connection.close()
            if payload.get('success') is not True or not isinstance(payload.get('result'),dict):raise ValueError()
            result=payload['result']
            cert=x509.load_pem_x509_certificate(result['certificate'].encode('ascii'))
            if (result.get('id')!=certificate_id or result.get('certificate_authority',{}).get('id')!=self.ca_id
                or cert.fingerprint(hashes.SHA256()).hex()!=fingerprint
                or digest(public_bytes(cert.public_key()))!=installation_key_id
                or result.get('fingerprint_sha256')!=fingerprint):
                raise EnrollmentError('INVALID_ISSUANCE_RECEIPT')
            status=result.get('status')
            if status in ('pending_reactivation','pending_revocation','revoked'):
                raise EnrollmentError('INSTALLATION_REVOKED')
            if status!='active':raise ValueError()
            return True
        except EnrollmentError:
            raise
        except Exception:
            raise IssuanceUncertain('ISSUANCE_UNCERTAIN') from None
