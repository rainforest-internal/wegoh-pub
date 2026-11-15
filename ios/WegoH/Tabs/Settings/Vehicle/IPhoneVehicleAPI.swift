import CryptoKit
import Foundation

enum VehicleLinkError: LocalizedError {
    case invalidCode, unavailableCode, changed, invalidResponse, unavailable, limit

    var errorDescription: String? {
        switch self {
        case .limit: "차량은 1대만 연결할 수 있어요. 설정의 연결 차량에서 기존 연결을 먼저 해제해 주세요."
        case .invalidCode: "차량에 표시된 영문·숫자 8자리 코드를 입력해 주세요."
        case .unavailableCode: "코드가 만료되었거나 올바르지 않아요. 차량에서 새 코드를 확인해 주세요."
        case .changed: "연결 정보가 변경되었어요. 코드를 다시 확인해 주세요."
        case .invalidResponse: "차량 연결 정보를 확인할 수 없어요. 다시 시도해 주세요."
        case .unavailable: "차량 연결을 확인할 수 없어요. 잠시 후 다시 시도해 주세요."
        }
    }
}

struct VehicleScopeDisclosure: Codable, Identifiable {
    let scope: String
    let required: Bool
    let dataCategories: [String]
    let purpose: String
    let retentionPolicyId: String
    let retention: String
    let refusalEffect: String
    let withdrawalEffect: String
    var id: String { scope }

    var title: String {
        switch scope {
        case "account:read": "계정 확인"
        case "account:write": "계정 이름 변경"
        case "device:self:manage": "연결 관리"
        case "courses:read": "경로"
        case "playlists:read": "플레이리스트"
        default: scope
        }
    }
}

struct VehicleDisclosure: Codable {
    let disclosureVersion: Int
    let disclosureSha256: String
    let scopeDisclosures: [VehicleScopeDisclosure]
    let bindingMaxSeconds: Int
    let keepSignedInDisclosure: String

    func validate(scopes: [String]) throws {
        let mandatory: Set<String> = ["account:read", "device:self:manage"]
        let known = mandatory.union(["account:write", "courses:read", "playlists:read"])
        guard disclosureVersion == 2, bindingMaxSeconds == 604_800,
              !keepSignedInDisclosure.isEmpty, Set(scopes).isSubset(of: known),
              scopes == scopes.sorted(), scopes.count == Set(scopes).count,
              mandatory.isSubset(of: Set(scopes)),
              scopeDisclosures.map(\.scope) == scopes,
              Set(scopeDisclosures.filter(\.required).map(\.scope)) == mandatory,
              scopeDisclosures.allSatisfy({ !$0.purpose.isEmpty && !$0.dataCategories.isEmpty &&
                  !$0.retention.isEmpty && !$0.refusalEffect.isEmpty && !$0.withdrawalEffect.isEmpty }) else {
            throw VehicleLinkError.invalidResponse
        }
        let encoder = JSONEncoder()
        let data = try encoder.encode(self)
        guard var object = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw VehicleLinkError.invalidResponse
        }
        object.removeValue(forKey: "disclosureSha256")
        let canonical = try JSONSerialization.data(withJSONObject: object, options: [.sortedKeys, .withoutEscapingSlashes])
        let digest = SHA256.hash(data: canonical).map { String(format: "%02x", $0) }.joined()
        guard digest == disclosureSha256 else { throw VehicleLinkError.invalidResponse }
    }
}

struct VehicleConnectionDetail: Decodable {
    let authorizationVersion: Int
    let userCode: String
    let deviceName: String
    let state: String
    let expiresAt: Int
    let requestedScopes: [String]
    let requiredScopes: [String]
    let consentVersion: Int
    let keepSignedInDefault: Bool
    let currentAccountDisplayName: String
    let disclosureSnapshot: VehicleDisclosure

    var expiry: Date { Date(timeIntervalSince1970: TimeInterval(expiresAt)) }
    var initialScopes: Set<String> {
        Set(requiredScopes).union(Set(requestedScopes).intersection(["courses:read", "playlists:read"]))
    }

    func validate(code: String) throws {
        guard authorizationVersion == 1, userCode == code, consentVersion == 1,
              !keepSignedInDefault, !deviceName.isEmpty, !currentAccountDisplayName.isEmpty,
              ["PENDING", "APPROVED", "DENIED"].contains(state),
              requiredScopes == ["account:read", "device:self:manage"] else {
            throw VehicleLinkError.invalidResponse
        }
        try disclosureSnapshot.validate(scopes: requestedScopes)
        guard expiry > .now else { throw VehicleLinkError.unavailableCode }
    }
}

struct LinkedVehicle: Decodable, Identifiable {
    let id: String
    let name: String
    let expiresAt: String
    let authorizationVersion: Int
}

struct IPhoneVehicleAPI {
    private let transport: IPhoneSessionAPI

    init(transport: IPhoneSessionAPI = IPhoneSessionAPI()) {
        self.transport = transport
    }

    func connection(code: String, token: String) async throws -> VehicleConnectionDetail {
        guard VehicleQR.inputCode(code) == code else { throw VehicleLinkError.invalidCode }
        let data = try await call("connections/" + code, token: token)
        let detail: VehicleConnectionDetail = try decode(data)
        try detail.validate(code: code)
        return detail
    }

    func approve(_ detail: VehicleConnectionDetail, scopes: Set<String>, keepSignedIn: Bool, token: String) async throws {
        try detail.validate(code: detail.userCode)
        guard detail.state == "PENDING", Set(detail.requiredScopes).isSubset(of: scopes),
              scopes.isSubset(of: Set(detail.requestedScopes)) else { throw VehicleLinkError.changed }
        struct Approval: Encodable {
            let authorizationVersion = 1
            let consentVersion: Int
            let approvedScopes: [String]
            let keepSignedIn: Bool
            let disclosureVersion: Int
            let disclosureSha256: String
        }
        let payload = try JSONEncoder().encode(Approval(consentVersion: detail.consentVersion,
            approvedScopes: scopes.sorted(), keepSignedIn: keepSignedIn,
            disclosureVersion: detail.disclosureSnapshot.disclosureVersion,
            disclosureSha256: detail.disclosureSnapshot.disclosureSha256))
        struct Result: Decodable { let authorizationVersion: Int; let state: String; let userCode: String }
        let result: Result = try decode(await call("connections/" + detail.userCode, method: "POST", payload: payload, token: token))
        guard result.authorizationVersion == 1, result.state == "APPROVED", result.userCode == detail.userCode else {
            throw VehicleLinkError.invalidResponse
        }
    }

    func vehicles(token: String) async throws -> [LinkedVehicle] {
        struct Listing: Decodable { let devices: [LinkedVehicle] }
        let listing: Listing = try decode(await call("vehicles", token: token))
        guard listing.devices.count <= 100,
              listing.devices.allSatisfy({ $0.authorizationVersion == 1 &&
                  $0.id.range(of: #"\A[a-f0-9]{32}\z"#, options: .regularExpression) != nil && !$0.name.isEmpty }),
              Set(listing.devices.map(\.id)).count == listing.devices.count else { throw VehicleLinkError.invalidResponse }
        return listing.devices
    }

    func revoke(_ device: LinkedVehicle, token: String) async throws {
        guard device.id.range(of: #"\A[a-f0-9]{32}\z"#, options: .regularExpression) != nil else {
            throw VehicleLinkError.invalidResponse
        }
        struct Result: Decodable { let status: String }
        let result: Result = try decode(await call("vehicles/" + device.id, method: "DELETE", token: token))
        guard result.status == "revoked" else { throw VehicleLinkError.invalidResponse }
    }

    private func decode<T: Decodable>(_ data: Data) throws -> T {
        do { return try JSONDecoder().decode(T.self, from: data) }
        catch { throw VehicleLinkError.invalidResponse }
    }

    private func call(_ path: String, method: String = "GET", payload: Data? = nil, token: String) async throws -> Data {
        do { return try await transport.resource(path, method: method, payload: payload, token: token) }
        catch IPhoneResourceError.missing { throw VehicleLinkError.unavailableCode }
        catch IPhoneResourceError.invalidInput { throw VehicleLinkError.invalidCode }
        catch IPhoneResourceError.vehicleLimit { throw VehicleLinkError.limit }
        catch IPhoneResourceError.conflict { throw VehicleLinkError.changed }
        catch IPhoneSessionError.expired { throw VehicleLinkError.unavailableCode }
        catch IPhoneResourceError.unavailable { throw VehicleLinkError.unavailable }
    }
}
