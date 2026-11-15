"""v2 codec의 모호한 JSON·형태·비밀 노출·서명 목적분리 회귀."""
import traceback
import unittest
from native_access_codec import (
    CodecError, Field, PrivateValue, Scope, Visibility, boolean, decode_json,
    integer, public_code, scope_set, strict_record, text, verification_uri,
)


class CodecCoreTest(unittest.TestCase):
    def test_scope_exact_subset_required_and_no_silent_expansion(self):
        raw = ["account:read", "device:self:manage"]
        self.assertEqual(scope_set(raw, require_connection=True),
                         (Scope.ACCOUNT_READ, Scope.DEVICE_SELF_MANAGE))
        self.assertEqual(scope_set([], require_connection=False), ())
        for bad in [["account:read"], ["courses:read"], ["admin:*"], ["account:read"] * 2,
                    "account:read", [True], [None]]:
            with self.assertRaises(CodecError):
                scope_set(bad, require_connection=True)

    def test_json_duplicate_nonfinite_shape_and_boundaries(self):
        self.assertEqual(decode_json(b'{"value":0}'), {"value": 0})
        for raw in [b'{"a":1,"a":2}', b'{"n":NaN}', b'{"n":Infinity}', b'[]',
                    b'null', b'', b'\xff', b'\xef\xbb\xbf{}', b'[' * 10000]:
            with self.assertRaises(CodecError):
                decode_json(raw)
        with self.assertRaises(CodecError):
            decode_json(b'{}', maximum_bytes=1)

    def test_typed_exact_fields_private_not_public_or_represented(self):
        secret = "pkce-private-DO-NOT-PRINT"
        schema = {
            "code": Field(public_code, Visibility.PUBLIC),
            "proof": Field(lambda value: text(value, maximum=128), Visibility.PRIVATE),
        }
        record = strict_record({"code": "ABCD2345", "proof": secret}, schema)
        self.assertEqual(record.public_view(), {"code": "ABCD2345"})
        self.assertEqual(record.for_transport()["proof"], secret)
        self.assertNotIn(secret, repr(record))
        self.assertNotIn(secret, repr(PrivateValue(secret)))
        for value in [{"code": "ABCD2345"}, {"code": "ABCD2345", "proof": secret, secret: secret}]:
            with self.assertRaises(CodecError) as caught:
                strict_record(value, schema)
            self.assertEqual(str(caught.exception), "INVALID_REQUEST")
            self.assertNotIn(secret, repr(caught.exception))

    def test_malformed_secret_errors_do_not_reflect_input(self):
        secret = "refresh-private-DO-NOT-PRINT"
        for raw in [('{"' + secret + '":').encode(), ('{"a":"' + secret + '","a":2}').encode()]:
            try:
                decode_json(raw)
            except CodecError as error:
                rendered = "".join(traceback.format_exception(error))
                self.assertNotIn(secret, rendered)
                self.assertEqual(error.args, ("INVALID_REQUEST",))
            else:
                self.fail("invalid input accepted")
        with self.assertRaises(CodecError) as caught:
            strict_record({"proof": secret},
                          {"proof": Field(lambda _: int(secret), Visibility.PRIVATE)})
        self.assertNotIn(secret, "".join(traceback.format_exception(caught.exception)))

    def test_scalar_types_do_not_coerce_bool_float_or_controls(self):
        self.assertTrue(boolean(True))
        self.assertEqual(integer(0, minimum=0, maximum=4), 0)
        for value in [True, 1.0, "1", None]:
            with self.assertRaises(CodecError):
                integer(value, minimum=0, maximum=4)
        for value in ["a\nb", "\ud800", 4, ""]:
            with self.assertRaises(CodecError):
                text(value)
        for value in ["ABCD234I", "abcd2345", "ABCD2345extra", True]:
            with self.assertRaises(CodecError):
                public_code(value)

    def test_verification_uri_exact_origin_code_no_secret_or_redirect(self):
        code = "ABCD2345"
        good = "https://wegoh.devforest.io/enroll.html?user_code=" + code
        self.assertEqual(verification_uri(good, code), good)
        for value in [
            " " + good, "\n" + good, good + "\n", "\x00" + good,
            good + "&token=secret", good + "#secret", good.replace("https:", "http:"),
            good.replace("wegoh.devforest.io", "wegoh.devforest.io.evil.invalid"),
            good.replace("wegoh.devforest.io", "user@wegoh.devforest.io"),
            good.replace("wegoh.devforest.io", "wegoh.devforest.io:443"),
            good.replace("ABCD2345", "ABCD2346"),
            good.replace("/enroll.html", "/enroll.html/../studio.html"),
        ]:
            with self.assertRaises(CodecError):
                verification_uri(value, code)




class CodecPrimitivesTest(unittest.TestCase):
    def test_canonical_base64url_rejects_alias_padding_and_other_alphabet(self):
        import base64
        from native_access_codec import canonical_base64url
        good = base64.urlsafe_b64encode(bytes(32)).rstrip(b"=").decode("ascii")
        self.assertEqual(canonical_base64url(good, byte_length=32), good)
        # 서로 다른 텍스트가 같은 bytes로 느슨하게 decode되는 pad-bit 별칭을 거절한다.
        alias = good[:-1] + "B"
        self.assertEqual(base64.urlsafe_b64decode(good + "="), base64.urlsafe_b64decode(alias + "="))
        for bad in [alias, good + "=", good + "\n", "+" + good[1:], good[:-1], 1]:
            with self.assertRaises(CodecError):
                canonical_base64url(bad, byte_length=32)

    def test_lower_hex_and_utf8_scalar_byte_boundaries(self):
        from native_access_codec import lower_hex, scalar_utf8_text
        self.assertEqual(lower_hex("ab" * 16, byte_length=16), "ab" * 16)
        for bad in ["AB" * 16, "ab" * 15, " ab" * 16, True]:
            with self.assertRaises(CodecError):
                lower_hex(bad, byte_length=16)
        self.assertEqual(scalar_utf8_text("가" * 80, maximum_scalars=80, maximum_bytes=240), "가" * 80)
        for bad in ["가" * 81, "😀" * 61, " name", "name ", "a\x7fb", "a\x85b", "\udfff"]:
            with self.assertRaises(CodecError):
                scalar_utf8_text(bad, maximum_scalars=80, maximum_bytes=240)




import base64
import copy
import hashlib
import json
from datetime import datetime, timedelta, timezone
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
import native_access_codec as codec


class WireCodecTest(unittest.TestCase):
    def test_single_public_version_rejects_old_envelope_and_manual_adoption(self):
        op=self.contract["operations"][0];body=self.request(op)
        codec.decode_request(op["action"],body)
        for version in (2, True, "1", 1.0):
            with self.subTest(version=version), self.assertRaises(CodecError):
                codec.decode_request(op["action"],{**body,"authorizationVersion":version})
        with self.assertRaises(CodecError):
            codec.verification_uri("https://wegoh.devforest.io/enroll.html?authorization_version=2&user_code=ABCD2345","ABCD2345")
        account=next(x for x in self.contract["operations"] if x["action"]=="ACCOUNT_AUTHORIZE")
        with self.assertRaises(CodecError):
            codec.decode_request("ACCOUNT_AUTHORIZE",{**self.request(account),"legacyDeviceId":"a"*32})

    @classmethod
    def setUpClass(cls):
        cls.now = int(datetime.now(timezone.utc).timestamp())
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "WegoH-" + "a" * 32)])
        cls.csr = x509.CertificateSigningRequestBuilder().subject_name(cls.name).sign(cls.key, hashes.SHA256())
        cls.csr_pem = cls.csr.public_bytes(serialization.Encoding.PEM).decode("ascii")
        cls.ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.cert = (x509.CertificateBuilder().subject_name(cls.name)
                    .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Synthetic Test CA")]))
                    .public_key(cls.key.public_key()).serial_number(1)
                    .not_valid_before(datetime.fromtimestamp(cls.now - 60, timezone.utc))
                    .not_valid_after(datetime.fromtimestamp(cls.now + 86400, timezone.utc))
                    .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                    .add_extension(x509.KeyUsage(True, False, False, False, False, False, False, None, None), critical=True)
                    .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH]), critical=False)
                    .sign(cls.ca_key, hashes.SHA256()))
        cls.cert_pem = cls.cert.public_bytes(serialization.Encoding.PEM).decode("ascii")
        cls.key_id = hashlib.sha256(cls.key.public_key().public_bytes(serialization.Encoding.DER,
                                                                    serialization.PublicFormat.SubjectPublicKeyInfo)).hexdigest()
        cls.cert_sha = cls.cert.fingerprint(hashes.SHA256()).hex()
        cls.contract = codec.wire_contract()
        cls.scopes = sorted([item.value for item in codec.Scope])
        cls.secret = base64.urlsafe_b64encode(bytes(range(32))).rstrip(b"=").decode("ascii")
        cls.signature = base64.urlsafe_b64encode(bytes(256)).rstrip(b"=").decode("ascii")
        cls.operation_id = "b" * 32

    def sample(self, kind):
        values = {
            "Version": 1, "Id": self.operation_id, "State": "PENDING",
            "InstallationKeyId": self.key_id, "CertificateSha256": self.cert_sha,
            "Secret": self.secret, "ServerNonce": self.secret, "S25643": self.secret,
            "RSA2048Signature342": self.signature, "PkceVerifier": "V" * 43,
            "Timestamp": self.now + 300, "Counter": 1, "Epoch": 1,
            "Generation": 1, "ConsentVersion": 1, "PollInterval": 5, "RetryAfter": 5,
            "UserCode": "ABCD2345", "DeviceName": "내 차량", "AccountId": "team-" + "d" * 40,
            "ScopeSet": self.scopes, "ApprovedScopeSet": self.scopes,
            "RequiredScopes": sorted(item.value for item in codec.REQUIRED_SCOPES),
            "KeepSignedIn": False, "literal false": False, "literal Bearer": "Bearer",
            "APPROVED or DENIED": "APPROVED", "literal DENIED": "DENIED", "integer literal1": 1, "integer literal2": 2,
            "FixedPhoneUri": self.contract["phone"]["current"].replace("<UserCode>", "ABCD2345"),
            "DisclosureSnapshot": codec.disclosure_snapshot(self.scopes),
        }
        if kind == "certificateReceipt":
            return dict(certificatePem=self.cert_pem, certificateSha256=self.cert_sha,
                        installationKeyId=self.key_id, generation=1, generationOperationId="c" * 32,
                        expiresAt=self.now + 86400)
        if kind == "credentialReceipt":
            return dict(accessToken=self.secret, refreshToken=self.secret, tokenType="Bearer",
                        accountId="team-" + "d" * 40, grantId="a" * 32, deviceId="e" * 32,
                        installationKeyId=self.key_id, certificateSha256=self.cert_sha,
                        generation=1, slotRevision=1, credentialEpoch=1, consentVersion=1,
                        scopes=self.scopes, expiresAt=self.now + 900, grantExpiresAt=self.now + 86400,
                        recoveryCapability=self.secret, revokeCapability=self.secret)
        if kind == "SingleValidatedPem":
            return self.csr_pem
        return copy.deepcopy(values[kind])

    def request(self, op):
        value = {}
        for name in op["requestRequired"]:
            kind = self.contract["requestFieldTypes"][name]
            value[name] = self.sample("ServerNonce" if name == "proofNonce" else kind)
        value.update(op.get("fixedRequestValues", {}))
        if "certificatePem" in value:
            value["certificatePem"] = self.cert_pem
        return value

    def response(self, op, variant):
        value = dict(authorizationVersion=1, operation=op["action"], operationId=self.operation_id,
                     state=variant["state"], disposition=variant["disposition"], serverTime=self.now)
        value.update({name: self.sample(kind) for name, kind in variant["required"].items()})
        return value

    def test_every_declared_operation_request_and_response_variant_is_reachable(self):
        count = 0
        for op in self.contract["operations"]:
            request = self.request(op)
            self.assertEqual(codec.decode_request(op["action"], request).for_transport(), request)
            for variant in op["responseVariants"]:
                value = self.response(op, variant)
                result = codec.decode_response(op["action"], variant["httpStatus"], value,
                                               expected_operation_id=self.operation_id,
                                               expected_installation_key_id=self.key_id)
                self.assertEqual(result.for_transport(), value)
                self.assertNotIn(self.secret, repr(result))
                self.assertNotIn("certificateReceipt", result.public_view())
                self.assertNotIn("credentialReceipt", result.public_view())
                count += 1
        self.assertGreaterEqual(count, 25)

    def test_closed_requests_no_extra_missing_version_or_scope_coercion(self):
        op = self.contract["operations"][0]
        good = self.request(op)
        for field in good:
            bad = dict(good);bad.pop(field)
            with self.assertRaises(codec.CodecError):codec.decode_request(op["action"], bad)
        for bad in [dict(good, extra=True), dict(good, authorizationVersion=True),
                    dict(good, authorizationVersion=1.0), dict(good, requestedScopes=list(reversed(self.scopes))),
                    dict(good, requestedScopes=tuple(self.scopes)), dict(good, requestedScopes=["account:read"]),
                    dict(good, csrPem=self.cert_pem), dict(good, name="a\x85b")]:
            with self.assertRaises(codec.CodecError):codec.decode_request(op["action"], bad)
        raw = json.dumps(good).encode()
        with self.assertRaises(codec.CodecError):codec.decode_request(op["action"], raw[:-1] + b',"authorizationVersion":1}')
        with self.assertRaises(codec.CodecError):codec.decode_request(op["action"], b' ' * 12289)

    def test_response_variant_binding_closed_nested_receipt_and_strict_types(self):
        op = next(x for x in self.contract["operations"] if x["action"] == "SESSION_EXCHANGE")
        good = self.response(op, op["responseVariants"][0])
        mutations = [dict(good, operation="SESSION_REFRESH"), dict(good, operationId="a" * 32),
                     dict(good, state="APPROVED"), dict(good, disposition="WAIT"), dict(good, extra="hidden")]
        for field, value in [("scopes", []), ("credentialEpoch", True), ("tokenType", "JWT"),
                             ("accountId", "a" * 32), ("expiresAt", self.now + 901),
                             ("revokeCapability", self.secret[:-1] + "=")]:
            bad = copy.deepcopy(good);bad["credentialReceipt"][field] = value;mutations.append(bad)
        bad = copy.deepcopy(good);bad["credentialReceipt"]["otherSecret"] = "secret";mutations.append(bad)
        for bad in mutations:
            with self.assertRaises(codec.CodecError):
                codec.decode_response(op["action"], 200, bad, expected_operation_id=self.operation_id)
        with self.assertRaises(codec.CodecError):
            codec.decode_response(op["action"], 200, good, expected_operation_id=self.operation_id,
                                  expected_installation_key_id="0" * 64)

    def test_certificate_receipt_der_spki_eku_validity_and_metadata_bound(self):
        op = next(x for x in self.contract["operations"] if x["action"] == "CERTIFICATE_RECOVER")
        good = self.response(op, op["responseVariants"][0])
        for field, value in [("certificateSha256", "0" * 64), ("installationKeyId", "0" * 64),
                             ("expiresAt", self.now + 86401), ("generation", 0),
                             ("certificatePem", self.csr_pem), ("certificatePem", self.cert_pem * 2)]:
            bad = copy.deepcopy(good);bad["certificateReceipt"][field] = value
            with self.assertRaises(codec.CodecError):
                codec.decode_response(op["action"], 200, bad, expected_operation_id=self.operation_id)
        for stamp in [self.now - 100, self.now + 86400]:
            bad = copy.deepcopy(good);bad["serverTime"] = stamp
            with self.assertRaises(codec.CodecError):
                codec.decode_response(op["action"], 200, bad, expected_operation_id=self.operation_id)

    def test_renewal_proof_has_new_context_and_claim_action_separation(self):
        begin=next(x for x in self.contract["operations"] if x["action"]=="CERTIFICATE_RENEW_BEGIN")
        body=self.request(begin);record=codec.decode_request(begin["action"],body)
        challenge=body["codeChallenge"]
        raw=codec.proof_transcript(begin["action"],record,installation_key_id=self.key_id,code_challenge=challenge).decode().split("\n")
        self.assertEqual(raw[4],"/v1/installations/certificate-renew")
        self.assertEqual(raw[6],"-");self.assertEqual(raw[9],"certificate-renewal")
        with self.assertRaises(codec.CodecError):
            codec.proof_transcript(begin["action"],record,installation_key_id=self.key_id,code_challenge=challenge,connection_id="a"*32)
        other=codec.canonical_base64url("AQ"+"A"*41,byte_length=32)
        if other!=challenge:
            with self.assertRaises(codec.CodecError):
                codec.proof_transcript(begin["action"],record,installation_key_id=self.key_id,code_challenge=other)
        bad=dict(body,proofNonce=self.secret)
        with self.assertRaises(codec.CodecError):codec.decode_request(begin["action"],bad)
        claim=next(x for x in self.contract["operations"] if x["action"]=="CERTIFICATE_RENEW_CLAIM")
        claimrecord=codec.decode_request(claim["action"],self.request(claim))
        renew=codec.proof_transcript(claim["action"],claimrecord,installation_key_id=self.key_id,code_challenge=challenge,connection_id="a"*32)
        regular=codec.proof_transcript("CONNECTION_CLAIM",claimrecord,installation_key_id=self.key_id,code_challenge=challenge,connection_id="a"*32)
        self.assertNotEqual(renew,regular);self.assertIn(b"/v1/connections/"+b"a"*32+b"/claim",renew)

    def test_preexchange_revoke_fixed_vector_and_purpose_binding(self):
        good=codec.derive_revoke_capability("v"*43,"a"*64,"b"*32)
        self.assertEqual(good,"odVhwXd0ypx3ma_0UQ30GGbsemFmhSBXff4g8vEon7U")
        self.assertEqual(codec.revoke_commitment(good),"c87a5ddb69cbf1d9d920dd6a2ea159bbe02af312002e716c3d0c0bc5b2db93d3")
        for bad in [good+"=",True,"not-a-capability"]:
            with self.assertRaises(codec.CodecError):codec.revoke_commitment(bad)
        self.assertNotEqual(good,codec.derive_revoke_capability("v"*43,"c"*64,"b"*32))
        self.assertNotEqual(good,codec.derive_revoke_capability("v"*43,"a"*64,"c"*32))
        self.assertNotEqual(good,codec.derive_capability("v"*43,"b"*32,"revoke"))
        self.assertNotEqual(good,codec.derive_capability("v"*43,"b"*32,"recovery"))
        for verifier,key,op in [(True,"a"*64,"b"*32),("v"*43,"A"*64,"b"*32),("v"*43,"a"*64,None)]:
            with self.assertRaises(codec.CodecError):codec.derive_revoke_capability(verifier,key,op)

    def test_phone_consent_exact_snapshot_partial_denial_and_no_boolean_integer_alias(self):
        snapshot = codec.disclosure_snapshot(self.scopes)
        request = dict(authorizationVersion=1, consentVersion=1, approvedScopes=[], keepSignedIn=False,
                       disclosureVersion=snapshot["disclosureVersion"], disclosureSha256=snapshot["disclosureSha256"])
        self.assertEqual(codec.decode_phone_request("PHONE_APPROVE", request, requested_scopes=self.scopes).for_transport(), request)
        for bad in [dict(request, approvedScopes=["friends:read"]), dict(request, keepSignedIn=1),
                    dict(request, disclosureVersion=True), dict(request, disclosureVersion=1), dict(request, disclosureSha256="0" * 64)]:
            with self.assertRaises(codec.CodecError):
                codec.decode_phone_request("PHONE_APPROVE", bad, requested_scopes=self.scopes)
        with self.assertRaises(codec.CodecError):codec.decode_phone_request("PHONE_APPROVE", request)
        status = self.contract["phoneOperations"][0]
        value = {name: self.sample(kind) for name, kind in status["responseRequired"].items()}
        value['state'] = 'PENDING'
        self.assertEqual(codec.decode_phone_response("PHONE_STATUS", value, expected_user_code="ABCD2345").for_transport(), value)
        bad = copy.deepcopy(value);bad["disclosureSnapshot"]["bindingMaxSeconds"] = True
        with self.assertRaises(codec.CodecError):codec.decode_phone_response("PHONE_STATUS", bad, expected_user_code="ABCD2345")
        bad = copy.deepcopy(value);bad["disclosureSnapshot"]["scopeDisclosures"][0]["required"] = 1
        with self.assertRaises(codec.CodecError):codec.decode_phone_response("PHONE_STATUS", bad, expected_user_code="ABCD2345")

    def test_fixed_error_enum_and_retry_after_never_reflects_detail(self):
        for status, errors in self.contract["errors"].items():
            for error in errors:
                value = dict(authorizationVersion=1, error=error)
                self.assertEqual(codec.decode_error(int(status), value).public_view(), value)
        for status, value in [(200, dict(authorizationVersion=1, error="INVALID_REQUEST")),
                              (400, dict(authorizationVersion=1, error="arbitrary secret detail")),
                              (429, dict(authorizationVersion=1, error="RATE_LIMITED", retryAfter=True)),
                              (503, dict(authorizationVersion=1, error="SERVICE_UNAVAILABLE", detail=self.secret))]:
            with self.assertRaises(codec.CodecError) as error:codec.decode_error(status, value)
            self.assertNotIn(self.secret, str(error.exception))

    def test_canonical_transcript_purpose_origin_body_and_capability_separation(self):
        op = next(x for x in self.contract["operations"] if x["action"] == "CONNECTION_RECOVER")
        value = self.request(op);record = codec.decode_request(op["action"], value)
        canonical = codec.canonical_request(record, exclude_proof=True)
        self.assertNotIn(b'"proof":', canonical)
        transcript = codec.proof_transcript(op["action"], record, installation_key_id=self.key_id,
                                            code_challenge=self.secret)
        expected = "\n".join(["WegoH native access v2", "CONNECTION_RECOVER", "https://enroll-wegoh.devforest.io",
                               "POST", "/v1/connections/recover", self.operation_id, "-", self.key_id,
                               self.secret, "begin-recovery", hashlib.sha256(canonical).hexdigest()]).encode("ascii")
        self.assertEqual(transcript, expected)
        signature = self.key.sign(transcript, padding.PKCS1v15(), hashes.SHA256())
        self.key.public_key().verify(signature, expected, padding.PKCS1v15(), hashes.SHA256())
        self.assertFalse(transcript.endswith(b"\n"))
        self.assertEqual(codec.canonical_request(codec.decode_request(op["action"], dict(reversed(list(value.items()))))),
                         codec.canonical_request(record))
        recovery = codec.derive_capability("V" * 43, "a" * 32, "recovery")
        revoke = codec.derive_capability("V" * 43, "a" * 32, "revoke")
        self.assertNotEqual(recovery, revoke)
        self.assertNotEqual(recovery, codec.derive_capability("V" * 43, "b" * 32, "recovery"))
        with self.assertRaises(codec.CodecError):codec.derive_capability("V" * 43, "a" * 32, "read")
        with self.assertRaises(codec.CodecError):
            codec.proof_transcript("SESSION_REFRESH", record, installation_key_id=self.key_id, code_challenge=self.secret)

    def test_wire_and_dto_views_are_copies_and_secret_fields_stay_private(self):
        op = self.contract["operations"][0];request = self.request(op)
        record = codec.decode_request(op["action"], request)
        copy_request = record.for_transport();copy_request["requestedScopes"].clear()
        self.assertEqual(record.for_transport()["requestedScopes"], self.scopes)
        self.assertNotIn("csrPem", record.public_view())
        self.assertNotIn("codeChallenge", record.public_view())
        copied = codec.wire_contract();copied["scopes"]["mandatory"].clear()
        self.assertEqual(len(codec.wire_contract()["scopes"]["mandatory"]), 2)


if __name__ == "__main__":
    unittest.main()
