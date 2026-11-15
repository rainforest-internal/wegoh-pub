"""Vendor-profile regression: absent leaf KU is distinct from invalid present KU.
Synthetic CA/keys only; no provider issuance, DB, HTTP or user data.
"""
import hashlib
import unittest
from datetime import datetime, timedelta, timezone
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, ExtensionOID, NameOID
from enrollment_crypto import EnrollmentError, validate_issued
import native_access_codec as codec


class VendorKeyUsageTests(unittest.TestCase):
    def test_optional_ku_does_not_disable_present_ku_eku_or_ca_constraints(self):
        now = datetime.now(timezone.utc).replace(microsecond=0)
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        authority = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "WegoH-" + "a" * 32)])
        csr = x509.CertificateSigningRequestBuilder().subject_name(subject).sign(key, hashes.SHA256())
        key_id = hashlib.sha256(key.public_key().public_bytes(serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo)).hexdigest()
        ca_id = "11111111-1111-1111-1111-111111111111"
        cases = [("absent", None, True, False, True), ("present-valid", (True, False, False), True, False, True),
            ("no-signature", (False, False, False), True, False, False),
            ("cert-sign", (True, True, False), True, False, False),
            ("crl-sign", (True, False, True), True, False, False),
            ("no-eku", None, None, False, False), ("server-eku-only", None, False, False, False),
            ("ca", None, True, True, False), ("malformed-present-ku", "malformed", True, False, False)]
        for label, usage, client_auth, ca, accepted in cases:
            with self.subTest(profile=label):
                builder = (x509.CertificateBuilder().subject_name(subject)
                    .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Synthetic Vendor Profile CA")]))
                    .public_key(key.public_key()).serial_number(x509.random_serial_number())
                    .not_valid_before(now - timedelta(seconds=60)).not_valid_after(now + timedelta(hours=1))
                    .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True))
                if usage == "malformed":
                    builder = builder.add_extension(x509.UnrecognizedExtension(ExtensionOID.KEY_USAGE, b"\x05\x00"), critical=True)
                elif usage is not None:
                    signature, cert_sign, crl_sign = usage
                    builder = builder.add_extension(x509.KeyUsage(signature, False, False, False, False,
                        cert_sign, crl_sign, None, None), critical=True)
                if client_auth is not None:
                    builder = builder.add_extension(x509.ExtendedKeyUsage([
                        ExtendedKeyUsageOID.CLIENT_AUTH if client_auth else ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
                cert = builder.sign(authority, hashes.SHA256())
                pem = cert.public_bytes(serialization.Encoding.PEM).decode("ascii")
                fingerprint = cert.fingerprint(hashes.SHA256()).hex()
                provider = dict(certificate=pem, status="active", certificate_authority={"id": ca_id},
                    id="22222222-2222-2222-2222-222222222222", fingerprint_sha256=fingerprint)
                response = dict(authorizationVersion=1, operation="CERTIFICATE_RECOVER", operationId="b" * 32,
                    state="ISSUED", disposition="CERTIFICATE_RECEIPT", serverTime=int(now.timestamp()),
                    certificateReceipt=dict(certificatePem=pem, certificateSha256=fingerprint,
                        installationKeyId=key_id, generation=1, generationOperationId="c" * 32,
                        expiresAt=int((now + timedelta(hours=1)).timestamp())))
                if accepted:
                    self.assertEqual(validate_issued(csr, provider, ca_id, now=now)["certificateSha256"], fingerprint)
                    record = codec.decode_response("CERTIFICATE_RECOVER", 200, response,
                        expected_operation_id="b" * 32, expected_installation_key_id=key_id)
                    self.assertEqual(record.for_transport()["certificateReceipt"]["certificateSha256"], fingerprint)
                else:
                    with self.assertRaises(EnrollmentError):
                        validate_issued(csr, provider, ca_id, now=now)
                    with self.assertRaises(codec.CodecError):
                        codec.decode_response("CERTIFICATE_RECOVER", 200, response,
                            expected_operation_id="b" * 32, expected_installation_key_id=key_id)
