"""단일 QR v1의 엄격 wire codec. 권한·원자성·Cloudflare 발급은 서비스 계층이 집행한다."""
from __future__ import annotations

import base64
import json
import re
from enum import Enum
from types import MappingProxyType
from typing import Any, Callable, Mapping
from urllib.parse import urlsplit


class CodecError(ValueError):
    """입력 값/공격자 key/비밀/원래 parser 오류를 출력하지 않는 내부 오류."""
    def __init__(self) -> None:
        super().__init__("INVALID_REQUEST")


class Scope(str, Enum):
    ACCOUNT_READ = "account:read"
    ACCOUNT_WRITE = "account:write"
    COURSES_READ = "courses:read"
    PLAYLISTS_READ = "playlists:read"
    DEVICE_SELF_MANAGE = "device:self:manage"


REQUIRED_SCOPES = frozenset((Scope.ACCOUNT_READ, Scope.DEVICE_SELF_MANAGE))


class Visibility(Enum):
    PUBLIC = "public"
    PRIVATE = "private"


class PrivateValue:
    """사고성 repr/str 노출 방지. Python 호출자 자체의 접근을 격리하는 기능은 아니다."""
    __slots__ = ("__value",)

    def __init__(self, value: Any) -> None:
        self.__value = value

    def __repr__(self) -> str:
        return "<PrivateValue redacted>"

    __str__ = __repr__

    def for_transport(self) -> Any:
        """신뢰하는 서버/클라이언트 전송층 전용. UI/로그로 보내지 않는다."""
        return self.__value


class Field:
    __slots__ = ("validator", "visibility")

    def __init__(self, validator: Callable[[Any], Any], visibility: Visibility) -> None:
        self.validator = validator
        self.visibility = visibility


class TypedRecord:
    __slots__ = ("__values", "__public")

    def __init__(self, values: Mapping[str, Any], public: frozenset[str]) -> None:
        self.__values = MappingProxyType(dict(values))
        self.__public = public

    def __repr__(self) -> str:
        return "<TypedRecord redacted>"

    __str__ = __repr__

    def public_view(self) -> dict[str, Any]:
        return {key: _public(self.__values[key]) for key in self.__public}

    def for_transport(self) -> dict[str, Any]:
        return _transport(self)


def strict_record(value: Any, fields: Mapping[str, Field]) -> TypedRecord:
    if type(value) is not dict or set(value) != set(fields):
        raise CodecError()
    result: dict[str, Any] = {}
    public: set[str] = set()
    try:
        for name, field in fields.items():
            parsed = field.validator(value[name])
            if field.visibility is Visibility.PRIVATE:
                result[name] = PrivateValue(parsed)
            elif field.visibility is Visibility.PUBLIC:
                result[name] = parsed
                public.add(name)
            else:
                raise CodecError()
    except (ValueError, TypeError, KeyError, OverflowError):
        raise CodecError() from None
    return TypedRecord(result, frozenset(public))


def decode_json(raw: bytes, *, maximum_bytes: int = 65536) -> dict[str, Any]:
    if type(raw) is not bytes or type(maximum_bytes) is not int or not 1 <= maximum_bytes <= 65536:
        raise CodecError()
    if not 1 <= len(raw) <= maximum_bytes:
        raise CodecError()

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise CodecError()
            result[key] = value
        return result

    def nonfinite(_: str) -> None:
        raise CodecError()

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=nonfinite)
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise CodecError() from None
    if type(value) is not dict:
        raise CodecError()
    return value


def text(value: Any, *, minimum: int = 1, maximum: int = 128) -> str:
    if type(value) is not str or not minimum <= len(value) <= maximum:
        raise CodecError()
    if any(ord(character) < 32 or 0xD800 <= ord(character) <= 0xDFFF for character in value):
        raise CodecError()
    return value


def integer(value: Any, *, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise CodecError()
    return value


def boolean(value: Any) -> bool:
    if type(value) is not bool:
        raise CodecError()
    return value


def scope_set(value: Any, *, require_connection: bool = False) -> tuple[Scope, ...]:
    if type(value) is not list or len(value) > len(Scope):
        raise CodecError()
    if any(type(item) is not str for item in value) or len(set(value)) != len(value):
        raise CodecError()
    try:
        scopes = tuple(Scope(item) for item in value)
    except ValueError:
        raise CodecError() from None
    if require_connection and not REQUIRED_SCOPES.issubset(scopes):
        raise CodecError()
    # 입력 순서를 유지한다. proof canonical 순서는 미동결이므로 추측하지 않는다.
    return scopes


def public_code(value: Any) -> str:
    if type(value) is not str or re.fullmatch(r"[A-HJ-NP-Z2-9]{8}", value) is None:
        raise CodecError()
    return value


def verification_uri(value: Any, code: str) -> str:
    code = public_code(code)
    if type(value) is not str or value != "https://wegoh.devforest.io/enroll.html?user_code=" + code:
        raise CodecError()
    try:
        uri = urlsplit(value)
        if (uri.scheme != "https" or uri.netloc != "wegoh.devforest.io"
                or uri.path != "/enroll.html" or uri.query != "user_code=" + code or uri.fragment):
            raise CodecError()
    except (ValueError, TypeError):
        raise CodecError() from None
    return value


def lower_hex(value: Any, *, byte_length: int) -> str:
    if type(byte_length) is not int or not 1 <= byte_length <= 512:
        raise CodecError()
    if type(value) is not str or len(value) != byte_length * 2 or re.fullmatch(r"[0-9a-f]+", value) is None:
        raise CodecError()
    return value


def canonical_base64url(value: Any, *, byte_length: int) -> str:
    if type(byte_length) is not int or not 1 <= byte_length <= 512:
        raise CodecError()
    if (type(value) is not str or len(value) != (byte_length * 8 + 5) // 6
            or re.fullmatch(r"[A-Za-z0-9_-]+", value) is None):
        raise CodecError()
    try:
        decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, TypeError):
        raise CodecError() from None
    if len(decoded) != byte_length or base64.urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii") != value:
        raise CodecError()
    return value


def scalar_utf8_text(value: Any, *, maximum_scalars: int, maximum_bytes: int) -> str:
    value = text(value, maximum=maximum_scalars)
    if value != value.strip() or any(127 <= ord(character) <= 159 for character in value):
        raise CodecError()
    try:
        if len(value.encode("utf-8")) > maximum_bytes:
            raise CodecError()
    except UnicodeError:
        raise CodecError() from None
    return value


# 이 파일의 동일 정의를 서버·CLI가 사용한다. UI 표시값은 public_view만 사용한다.
import copy
import hashlib
import hmac
from pathlib import Path
from datetime import datetime, timezone
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from enrollment_crypto import challenge, validate_csr

_WIRE = json.loads(Path(__file__).with_name("native_access_wire.json").read_text(encoding="utf-8"))
_OPERATIONS = {item["action"]: item for item in _WIRE["operations"]}
_PHONE_OPERATIONS = {item["action"]: item for item in _WIRE["phoneOperations"]}
_BODY_LIMIT = _WIRE["envelope"]["bodyLimitBytes"]
_PUBLIC_FIELDS = frozenset({
    "authorizationVersion", "operation", "operationId", "state", "disposition", "serverTime",
    "userCode", "verificationUri", "expiresAt", "interval", "retryAfter", "revokedAt", "expiredAt",
    "deviceName", "requestedScopes", "requiredScopes", "consentVersion", "keepSignedInDefault",
    "currentAccountDisplayName", "disclosureSnapshot", "approvedScopes", "keepSignedIn",
    "disclosureVersion", "disclosureSha256", "error",
})


def wire_contract() -> dict[str, Any]:
    """호출자는 복사본만 얻으며 프로세스의 decoder 정본을 변경할 수 없다."""
    return copy.deepcopy(_WIRE)


def _transport(value: Any) -> Any:
    if isinstance(value, PrivateValue):
        return _transport(value.for_transport())
    if isinstance(value, TypedRecord):
        return {name: _transport(item) for name, item in value._TypedRecord__values.items()}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple):
        return [_transport(item) for item in value]
    if isinstance(value, dict):
        return {name: _transport(item) for name, item in value.items()}
    if isinstance(value, list):
        return [_transport(item) for item in value]
    return value


def _public(value: Any) -> Any:
    if isinstance(value, PrivateValue):
        raise CodecError()
    if isinstance(value, TypedRecord):
        return value.public_view()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (tuple, list)):
        return [_public(item) for item in value]
    if isinstance(value, dict):
        return {name: _public(item) for name, item in value.items()}
    return value



def _literal(value: Any, expected: Any) -> Any:
    if type(value) is not type(expected):
        raise CodecError()
    if isinstance(value, dict):
        if set(value) != set(expected):
            raise CodecError()
        for name in value:
            _literal(value[name], expected[name])
    elif isinstance(value, list):
        if len(value) != len(expected):
            raise CodecError()
        for item, target in zip(value, expected):
            _literal(item, target)
    elif value != expected:
        raise CodecError()
    return value


def _wire_scopes(value: Any, *, required: bool = True, allow_empty: bool = False) -> tuple[Scope, ...]:
    parsed = scope_set(value, require_connection=required)
    if (not allow_empty and not parsed) or value != sorted(value):
        raise CodecError()
    return parsed


def _pkce(value: Any) -> str:
    if type(value) is not str or re.fullmatch(r"[A-Za-z0-9._~-]{43,128}", value) is None:
        raise CodecError()
    challenge(value)
    return value


def _pem(value: Any, *, csr: bool) -> str:
    if type(value) is not str:
        raise CodecError()
    try:
        if len(value.encode("ascii")) > 8192:
            raise CodecError()
        if csr:
            validate_csr(value)
        else:
            if re.fullmatch(r"-----BEGIN CERTIFICATE-----[A-Za-z0-9+/=\r\n]+-----END CERTIFICATE-----\s*", value) is None:
                raise CodecError()
            cert = x509.load_pem_x509_certificate(value.encode("ascii"))
            key = cert.public_key()
            if not isinstance(key, rsa.RSAPublicKey) or key.key_size != 2048 or key.public_numbers().e != 65537:
                raise CodecError()
    except Exception:
        raise CodecError() from None
    return value


def _account_id(value: Any) -> str:
    if type(value) is not str or re.fullmatch(r"team-[a-f0-9]{40}", value) is None:
        raise CodecError()
    return value


def _type(type_name: str, value: Any) -> Any:
    if type_name == "Version":
        return _literal(value, 1)
    if type_name == "Id":
        return lower_hex(value, byte_length=16)
    if type_name in ("InstallationKeyId", "CertificateSha256"):
        return lower_hex(value, byte_length=32)
    if type_name in ("Secret", "ServerNonce", "S25643"):
        return canonical_base64url(value, byte_length=32)
    if type_name == "RSA2048Signature342":
        return canonical_base64url(value, byte_length=256)
    if type_name == "PkceVerifier":
        return _pkce(value)
    if type_name == "Timestamp":
        return integer(value, minimum=0, maximum=253402300799)
    if type_name == "Counter":
        return integer(value, minimum=0, maximum=9007199254740991)
    if type_name in ("Generation", "ConsentVersion"):
        return integer(value, minimum=1, maximum=2147483647)
    if type_name == "Epoch":
        return integer(value, minimum=1, maximum=9007199254740991)
    if type_name == "PollInterval":
        return integer(value, minimum=5, maximum=60)
    if type_name == "RetryAfter":
        return integer(value, minimum=5, maximum=86400)
    if type_name == "UserCode":
        return public_code(value)
    if type_name == "DeviceName":
        return scalar_utf8_text(value, maximum_scalars=80, maximum_bytes=240)
    if type_name == "AccountId":
        return _account_id(value)
    if type_name == "ScopeSet":
        return _wire_scopes(value)
    if type_name == "ApprovedScopeSet":
        return _wire_scopes(value, required=False, allow_empty=True)
    if type_name == "RequiredScopes":
        return _literal(value, sorted(item.value for item in REQUIRED_SCOPES))
    if type_name == "KeepSignedIn":
        return boolean(value)
    if type_name in ("literal Bearer", "CredentialKind"):
        return _literal(value, "Bearer")
    if type_name in ("literal false", "integer literal1", "integer literal2"):
        return _literal(value, False if type_name == "literal false" else (2 if type_name == "integer literal2" else 1))
    if type_name == "State":
        if type(value) is not str or value not in _WIRE["states"]:
            raise CodecError()
        return value
    if type_name == "Disposition":
        if type(value) is not str or value not in _WIRE["dispositions"]:
            raise CodecError()
        return value
    if type_name == "AuthorizationOperation":
        if type(value) is not str or value not in _OPERATIONS:
            raise CodecError()
        return value
    if type_name == "APPROVED or DENIED":
        if type(value) is not str or value not in ("APPROVED", "DENIED"):
            raise CodecError()
        return value
    if type_name == "literal DENIED":
        return _literal(value, "DENIED")
    raise CodecError()


def _input(raw: Any) -> dict[str, Any]:
    if type(raw) is bytes:
        return decode_json(raw, maximum_bytes=_BODY_LIMIT)
    if type(raw) is not dict:
        raise CodecError()
    # dict 입력도 JSON 값의 정확 타입을 유지하며 tuple/비문자 키를 강제 변환하지 않는다.
    def json_value(item: Any, depth: int = 0) -> None:
        if depth > 32:
            raise CodecError()
        if type(item) is dict:
            if any(type(key) is not str for key in item):
                raise CodecError()
            for child in item.values():
                json_value(child, depth + 1)
        elif type(item) is list:
            for child in item:
                json_value(child, depth + 1)
        elif item is not None and type(item) not in (str, int, float, bool):
            raise CodecError()
    json_value(raw)
    try:
        serialized = json.dumps(raw, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise CodecError() from None
    return decode_json(serialized, maximum_bytes=_BODY_LIMIT)


def _record(value: dict[str, Any], required: Mapping[str, str], optional: Mapping[str, str] | None = None,
            special: Mapping[str, Callable[[Any], Any]] | None = None) -> TypedRecord:
    optional = optional or {}
    special = special or {}
    if not set(required).issubset(value) or not set(value).issubset(set(required) | set(optional)):
        raise CodecError()
    fields: dict[str, Field] = {}
    for name in value:
        kind = required.get(name, optional.get(name))
        validator = special.get(name) or (lambda item, k=kind: _type(k, item))
        fields[name] = Field(validator, Visibility.PUBLIC if name in _PUBLIC_FIELDS else Visibility.PRIVATE)
    return strict_record(value, fields)


def _operation(action: str) -> dict[str, Any]:
    if type(action) is not str or action not in _OPERATIONS:
        raise CodecError()
    return _OPERATIONS[action]


def decode_request(action: str, raw: bytes | dict[str, Any]) -> TypedRecord:
    """명시 action의 정확 필드만 해석한다. HTTP path/host/mTLS/CSRF는 handler가 확인한다."""
    operation = _operation(action)
    value = _input(raw)
    types = _WIRE["requestFieldTypes"]
    required = {name: types[name] for name in operation["requestRequired"]}
    optional = {name: types[name] for name in operation["requestOptional"]}
    special: dict[str, Callable[[Any], Any]] = {}
    for name in ("csrPem", "certificatePem"):
        if name in value:
            special[name] = lambda item, is_csr=name == "csrPem": _pem(item, csr=is_csr)
    if "proofNonce" in value:
        fixed = operation.get("fixedRequestValues", {}).get("proofNonce")
        special["proofNonce"] = (lambda item: _literal(item, fixed)) if fixed is not None else (lambda item: _type("ServerNonce", item))
    return _record(value, required, optional, special)


def _certificate_receipt(value: Any, *, server_time: int) -> TypedRecord:
    if type(value) is not dict:
        raise CodecError()
    schema = _WIRE["receipts"]["certificateReceipt"]
    result = _record(value, schema["required"], schema["optional"],
                     {"certificatePem": lambda item: _pem(item, csr=False)})
    data = result.for_transport()
    try:
        cert = x509.load_pem_x509_certificate(data["certificatePem"].encode("ascii"))
        key_der = cert.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
        cn = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
        constraints = cert.extensions.get_extension_for_class(x509.BasicConstraints).value
        try:
            usage = cert.extensions.get_extension_for_class(x509.KeyUsage).value
        except x509.ExtensionNotFound:
            usage = None  # RFC5280/9846: leaf KU may be absent; present restrictions remain.
        extended = cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
        if (len(cert.subject) != 1 or len(cn) != 1 or re.fullmatch(r"WegoH-[a-f0-9]{32}", cn[0].value) is None
                or constraints.ca or usage is not None and (not usage.digital_signature or usage.key_cert_sign or usage.crl_sign)
                or ExtendedKeyUsageOID.CLIENT_AUTH not in extended or cert.issuer == cert.subject
                or cert.signature_hash_algorithm.name not in ("sha256", "sha384", "sha512")
                or int(cert.not_valid_before_utc.timestamp()) > server_time
                or int(cert.not_valid_after_utc.timestamp()) <= server_time
                or int(cert.not_valid_after_utc.timestamp()) != data["expiresAt"]
                or cert.fingerprint(hashes.SHA256()).hex() != data["certificateSha256"]
                or hashlib.sha256(key_der).hexdigest() != data["installationKeyId"]):
            raise CodecError()
    except Exception:
        raise CodecError() from None
    return result


def _credential_receipt(value: Any, *, server_time: int) -> TypedRecord:
    if type(value) is not dict:
        raise CodecError()
    schema = _WIRE["receipts"]["credentialReceipt"]
    result = _record(value, schema["required"], schema["optional"])
    data = result.for_transport()
    if not server_time < data["expiresAt"] <= min(server_time + 900, data["grantExpiresAt"]):
        raise CodecError()
    return result


def decode_response(action: str, http_status: int, raw: bytes | dict[str, Any], *,
                    expected_operation_id: str, expected_installation_key_id: str | None = None) -> TypedRecord:
    """wire 형태와 응답 결합 검증. 신뢰된 TLS 수신층만 호출하며 발급자 검증을 대신하지 않는다."""
    operation = _operation(action)
    integer(http_status, minimum=100, maximum=599)
    expected_operation_id = _type("Id", expected_operation_id)
    if expected_installation_key_id is not None:
        expected_installation_key_id = _type("InstallationKeyId", expected_installation_key_id)
    value = _input(raw)
    if value.get("operation") != action or value.get("operationId") != expected_operation_id:
        raise CodecError()
    variants = [item for item in operation["responseVariants"]
                if item["httpStatus"] == http_status and item["state"] == value.get("state")
                and item["disposition"] == value.get("disposition")]
    for variant in variants:
        required = dict(_WIRE["responseCommonFields"], **variant["required"])
        optional = variant["optional"]
        if set(required).issubset(value) and set(value).issubset(set(required) | set(optional)):
            server_time = _type("Timestamp", value.get("serverTime"))
            special: dict[str, Callable[[Any], Any]] = {}
            if "verificationUri" in value:
                special["verificationUri"] = lambda item: verification_uri(item, value.get("userCode"))
            for name in ("certificateReceipt", "credentialReceipt"):
                if name in value:
                    validator = _certificate_receipt if name == "certificateReceipt" else _credential_receipt
                    special[name] = lambda item, v=validator: v(item, server_time=server_time)
            result = _record(value, required, optional, special)
            if expected_installation_key_id is not None:
                data = result.for_transport()
                for name in ("certificateReceipt", "credentialReceipt"):
                    if name in data and data[name]["installationKeyId"] != expected_installation_key_id:
                        raise CodecError()
            return result
    raise CodecError()




def disclosure_snapshot(scopes: list[str] | tuple[Scope, ...]) -> dict[str, Any]:
    strings = [item.value if isinstance(item, Scope) else item for item in scopes]
    selected = _wire_scopes(strings)
    registry = _WIRE["disclosureRegistry"]
    value = {"disclosureVersion": registry["version"],
             "scopeDisclosures": [copy.deepcopy(item) for item in registry["scopePolicies"]
                                  if Scope(item["scope"]) in selected],
             "bindingMaxSeconds": _WIRE["lifetimes"]["bindingSeconds"],
             "keepSignedInDisclosure": registry["keepSignedInDisclosure"]}
    value["disclosureSha256"] = hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                                          separators=(",", ":")).encode("utf-8")).hexdigest()
    return value


def decode_phone_request(action: str, raw: bytes | dict[str, Any], *, requested_scopes: list[str] | None = None) -> TypedRecord:
    if type(action) is not str or action not in _PHONE_OPERATIONS or action == "PHONE_STATUS":
        raise CodecError()
    value = _input(raw)
    result = _record(value, _PHONE_OPERATIONS[action]["requestRequired"])
    if action == "PHONE_APPROVE":
        if requested_scopes is None:
            raise CodecError()
        _wire_scopes(requested_scopes)
        if not set(value["approvedScopes"]).issubset(requested_scopes):
            raise CodecError()
        snapshot = disclosure_snapshot(requested_scopes)
        if (value["disclosureVersion"] != snapshot["disclosureVersion"]
                or value["disclosureSha256"] != snapshot["disclosureSha256"]):
            raise CodecError()
    return result


def decode_phone_response(action: str, raw: bytes | dict[str, Any], *, expected_user_code: str) -> TypedRecord:
    if type(action) is not str or action not in _PHONE_OPERATIONS:
        raise CodecError()
    expected_user_code = public_code(expected_user_code)
    value = _input(raw)
    special: dict[str, Callable[[Any], Any]] = {}
    if action == "PHONE_STATUS":
        expected_snapshot = disclosure_snapshot(value.get("requestedScopes", []))
        special["disclosureSnapshot"] = lambda item: _literal(item, expected_snapshot)
    result = _record(value, _PHONE_OPERATIONS[action]["responseRequired"], special=special)
    if value["userCode"] != expected_user_code:
        raise CodecError()
    return result


def decode_error(http_status: int, raw: bytes | dict[str, Any]) -> TypedRecord:
    integer(http_status, minimum=400, maximum=599)
    value = _input(raw)
    allowed = _WIRE["errors"].get(str(http_status), [])
    if type(value.get("error")) is not str or value["error"] not in allowed:
        raise CodecError()
    return _record(value, {"authorizationVersion": "Version", "error": "Unused"}, {"retryAfter": "RetryAfter"},
                   {"error": lambda item: _literal(item, value["error"])})


def canonical_request(record: TypedRecord, *, exclude_proof: bool = False) -> bytes:
    if type(record) is not TypedRecord or type(exclude_proof) is not bool:
        raise CodecError()
    value = record.for_transport()
    if exclude_proof:
        value.pop("proof", None)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def derive_capability(verifier: str, grant_id: str, purpose: str) -> str:
    verifier = _pkce(verifier)
    grant_id = _type("Id", grant_id)
    if type(purpose) is not str or purpose not in ("recovery", "revoke"):
        raise CodecError()
    message = ("WegoH native access v2 " + purpose + "\n" + grant_id).encode("ascii")
    return base64.urlsafe_b64encode(hmac.new(verifier.encode("ascii"), message, hashlib.sha256).digest()).rstrip(b"=").decode("ascii")


def derive_revoke_capability(verifier: str, installation_key_id: str, begin_operation_id: str) -> str:
    """Pre-exchange revoke-only authority, distinct from grant recovery/legacy revoke."""
    verifier = _pkce(verifier)
    key = _type("InstallationKeyId", installation_key_id)
    operation = _type("Id", begin_operation_id)
    message = ("WegoH native access v2 revoke-before-exchange\n" + key + "\n" + operation).encode("ascii")
    return base64.urlsafe_b64encode(hmac.new(verifier.encode("ascii"), message, hashlib.sha256).digest()).rstrip(b"=").decode("ascii")


def revoke_commitment(capability: str) -> str:
    """Canonical wire commitment; no FastAPI/service dependency in clients."""
    capability = _type("Secret", capability)
    return hashlib.sha256(("WegoH native v2 revoke\n" + capability).encode("ascii")).hexdigest()


def proof_transcript(action: str, record: TypedRecord, *, installation_key_id: str,
                     code_challenge: str, connection_id: str | None = None) -> bytes:
    operation = _operation(action)
    if not operation["keyProofRequired"] or type(record) is not TypedRecord:
        raise CodecError()
    value = record.for_transport()
    # 다른 action으로 만든 request를 모호하게 서명하지 않는다.
    decode_request(action, value)
    installation_key_id = _type("InstallationKeyId", installation_key_id)
    code_challenge = _type("S25643", code_challenge)
    if action in {"CONNECTION_RECOVER", "CONNECTION_CANCEL", "CERTIFICATE_RENEW_BEGIN", "CONNECTION_REAUTHORIZE"}:
        if action in {"CERTIFICATE_RENEW_BEGIN", "CONNECTION_REAUTHORIZE"} and value["codeChallenge"] != code_challenge:
            raise CodecError()
        if connection_id is not None:
            raise CodecError()
        connection = "-"
    elif action == "CONNECTION_RESTART":
        connection = value["previousConnectionId"]
        if connection_id is not None and connection_id != connection:
            raise CodecError()
        if value["codeChallenge"] != code_challenge:
            raise CodecError()
    elif action in {"CONNECTION_CLAIM", "CERTIFICATE_RENEW_CLAIM"}:
        connection = _type("Id", connection_id)
    else:
        # Certificate recovery is generation-scoped and carries no connection identifier.
        if connection_id is not None:
            raise CodecError()
        connection = "-"
    path = operation["path"].replace("{connectionId}", connection)
    values = ["WegoH native access v2", action, _WIRE["origins"][operation["host"]], operation["method"],
              path, value["operationId"], connection, installation_key_id, code_challenge,
              value["proofNonce"], hashlib.sha256(canonical_request(record, exclude_proof=True)).hexdigest()]
    return "\n".join(values).encode("ascii")
