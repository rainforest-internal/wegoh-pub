import CryptoKit
import SwiftUI

struct VehicleFunctionalSnapshot: Codable {
    struct Authorization: Codable {
        var authorizationVersion: Int
        var deviceId: String
        var grantId: String
        var revision: Int
        var expiresAt: Int
        var approvedPurposes: [String]
        var functionalDisclosureVersion: Int
        var functionalDisclosureSha256: String
    }
    struct Disclosure: Codable {
        struct Purpose: Codable, Identifiable {
            var id: String
            var label: String
            var dataCategories: [String]
            var purpose: String
            var retention: String
            var withdrawal: String
            var refusal: String
            var defaultEnabled: Bool
            enum CodingKeys: String, CodingKey { case id, label, dataCategories, purpose, retention, withdrawal, refusal; case defaultEnabled = "default" }
        }
        var version: Int
        var sha256: String
        var purposes: [Purpose]
    }
    var authorization: Authorization
    var approvedDisclosureVersion: Int? = nil
    var disclosure: Disclosure
    var readOnlyPurposes: [String]

    private static let currentDisclosureHash = "e7ab946a1a2c6642cf0993a472ba8963521766e5761e1d10fed950e4b630ecd6"
    var hasApprovedCurrentScoreSharing: Bool {
        disclosure.version == 5 && disclosure.sha256 == Self.currentDisclosureHash &&
            approvedDisclosureVersion == 5 && authorization.approvedPurposes.contains("driving-score:report")
    }

    func validate(deviceID: String) throws {
        let ids = disclosure.purposes.map(\.id)
        guard authorization.authorizationVersion == 1, authorization.deviceId == deviceID, validTripID(deviceID), validTripID(authorization.grantId),
              (0...Int(Int32.max)).contains(authorization.revision), authorization.expiresAt > Int(Date.now.timeIntervalSince1970),
              [3, 4, 5].contains(disclosure.version), authorization.functionalDisclosureVersion == disclosure.version,
              approvedDisclosureVersion.map({ (1...disclosure.version).contains($0) }) ?? true,
              authorization.functionalDisclosureSha256 == disclosure.sha256,
              (disclosure.version != 5 || disclosure.sha256 == Self.currentDisclosureHash),
              (disclosure.version != 4 || disclosure.sha256 == "71562cdc23bc16f0872290ae45bbcf6965aab1c3aef381ae878be8c25d2ddbe6"),
              ids.count <= 32, ids == ids.sorted(), Set(ids).count == ids.count,
              Set(authorization.approvedPurposes).isSubset(of: Set(ids)),
              authorization.approvedPurposes == Array(Set(authorization.approvedPurposes)).sorted(),
              Set(readOnlyPurposes).isSubset(of: Set(ids)),
              disclosure.purposes.allSatisfy({ !$0.label.isEmpty && !$0.purpose.isEmpty && !$0.retention.isEmpty && !$0.withdrawal.isEmpty && !$0.refusal.isEmpty && !$0.dataCategories.isEmpty })
        else { throw VehicleLinkError.invalidResponse }
        struct Canonical: Encodable { var version: Int; var purposes: [Disclosure.Purpose] }
        let data = try JSONEncoder().encode(Canonical(version: disclosure.version, purposes: disclosure.purposes))
        let object = try JSONSerialization.jsonObject(with: data)
        let canonical = try JSONSerialization.data(withJSONObject: object, options: [.sortedKeys, .withoutEscapingSlashes])
        let digest = SHA256.hash(data: canonical).map { String(format: "%02x", $0) }.joined()
        guard digest == disclosure.sha256 else { throw VehicleLinkError.invalidResponse }
    }
    func payload(approved: Set<String>) throws -> Data {
        try validate(deviceID: authorization.deviceId)
        let known = Set(disclosure.purposes.map(\.id))
        guard approved.isSubset(of: known),
              approved.intersection(readOnlyPurposes) == Set(authorization.approvedPurposes).intersection(readOnlyPurposes)
        else { throw VehicleLinkError.invalidResponse }
        struct Body: Encodable {
            var authorizationVersion: Int
            var grantId: String
            var revision: Int
            var approvedPurposes: [String]
            var functionalDisclosureVersion: Int
            var functionalDisclosureSha256: String
        }
        return try JSONEncoder().encode(Body(authorizationVersion: authorization.authorizationVersion, grantId: authorization.grantId,
            revision: authorization.revision, approvedPurposes: approved.sorted(), functionalDisclosureVersion: disclosure.version,
            functionalDisclosureSha256: disclosure.sha256))
    }
}

struct IPhoneVehicleFunctionalAPI {
    private let transport: IPhoneSessionAPI
    init(configuration: URLSessionConfiguration? = nil) { transport = IPhoneSessionAPI(configuration: configuration) }
    func load(_ deviceID: String, token: String) async throws -> VehicleFunctionalSnapshot {
        guard validTripID(deviceID) else { throw VehicleLinkError.invalidResponse }
        return try decode(await transport.resource("vehicles/" + deviceID + "/functional-permissions", token: token), deviceID: deviceID)
    }
    func save(_ snapshot: VehicleFunctionalSnapshot, approved: Set<String>, token: String) async throws -> VehicleFunctionalSnapshot {
        try snapshot.validate(deviceID: snapshot.authorization.deviceId)
        let data = try await transport.resource("vehicles/" + snapshot.authorization.deviceId + "/functional-permissions", method: "PUT",
            payload: snapshot.payload(approved: approved), token: token)
        let value = try decode(data, deviceID: snapshot.authorization.deviceId)
        guard value.authorization.grantId == snapshot.authorization.grantId,
              Set(value.authorization.approvedPurposes) == approved else { throw VehicleLinkError.invalidResponse }
        if snapshot.disclosure.version >= 4 {
            let changed = approved != Set(snapshot.authorization.approvedPurposes) || snapshot.approvedDisclosureVersion != snapshot.disclosure.version
            guard value.disclosure.version == snapshot.disclosure.version, value.approvedDisclosureVersion == snapshot.disclosure.version,
                  value.authorization.revision == snapshot.authorization.revision + (changed ? 1 : 0)
            else { throw VehicleLinkError.invalidResponse }
        }
        return value
    }
    private func decode(_ data: Data, deviceID: String) throws -> VehicleFunctionalSnapshot {
        let result: VehicleFunctionalSnapshot
        do { result = try JSONDecoder().decode(VehicleFunctionalSnapshot.self, from: data) }
        catch { throw VehicleLinkError.invalidResponse }
        try result.validate(deviceID: deviceID)
        return result
    }
}

struct VehicleFunctionalPermissionsView: View {
    let vehicle: LinkedVehicle
    @Environment(SessionManager.self) private var session
    @State private var snapshot: VehicleFunctionalSnapshot?
    @State private var approved: Set<String> = []
    @State private var busy = false
    @State private var saving = false
    @State private var needsReload = true
    @State private var message: String?
    private let api: IPhoneVehicleFunctionalAPI
    init(vehicle: LinkedVehicle, api: IPhoneVehicleFunctionalAPI = .init()) { self.vehicle = vehicle; self.api = api }
    var body: some View {
        List {
            Section {
                Text(vehicle.name).font(WegoTokens.Typography.section)
                Text("이 차량에서 사용할 기능을 선택해 주세요.")
                    .font(WegoTokens.Typography.label)
            }.wegoListRows()
            if let snapshot {
                ForEach(snapshot.disclosure.purposes.filter { $0.id != "driving-score:report" }) { item in
                    Section {
                        Toggle(item.label, isOn: Binding(get: { approved.contains(item.id) }, set: { value in
                            if value { approved.insert(item.id) } else { approved.remove(item.id) }
                        }))
                        .disabled(busy || needsReload || snapshot.readOnlyPurposes.contains(item.id))
                        .accessibilityIdentifier("vehiclePurpose-" + item.id)
                        Text(item.purpose).font(WegoTokens.Typography.label)
                        DisclosureGroup("사용 정보 보기") {
                            Text("정보: " + item.dataCategories.joined(separator: ", "))
                            Text("보관: " + item.retention)
                            Text("거부 시: " + item.refusal)
                            Text("철회 시: " + item.withdrawal)
                        }.font(WegoTokens.Typography.caption)
                        if snapshot.readOnlyPurposes.contains(item.id) {
                            Text(item.id == "device-commands:receive" ? "명령 수신은 차량 화면에서 바꿀 수 있어요." : "기본 연결에 포함된 기능이에요.")
                                .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
                        }
                    }.wegoListRows()
                }
                Section {
                    Button { Task { await save() } } label: {
                        if saving { WegoButtonLoadingLabel("기능 저장 중…") }
                        else { Text("선택한 기능 저장") }
                    }.disabled(busy || needsReload)
                        .accessibilityIdentifier("vehiclePurposesSave")
                }.wegoListRows()
            }
            Section {
                if (busy && !saving) || (snapshot == nil && message == nil) { WegoLoadingView("차량 기능 확인 중", layout: snapshot == nil ? .detail : .row) }
                if let message {
                    if snapshot == nil && !busy { WegoLoadingFailureView(message: message) { Task { await load() } } }
                    else { Text(message).font(WegoTokens.Typography.label) }
                }
                Button("기능 설명 다시 불러오기") { Task { await load() } }.disabled(busy)
            }.wegoListRows()
        }
        .wegoSettingsList().navigationTitle("차량 기능 허용").navigationBarTitleDisplayMode(.inline)
        .task(id: session.current?.accountID) { snapshot = nil; approved = []; await load() }
    }
    @MainActor private func load() async {
        guard !busy, let account = session.current else { return }
        busy = true; message = nil; needsReload = true
        defer { busy = false }
        do {
            let value = try await session.withToken(for: account) { try await api.load(vehicle.id, token: $0) }
            guard session.current == account else { return }
            snapshot = value; approved = Set(value.authorization.approvedPurposes); needsReload = false
        } catch is CancellationError { }
        catch { message = error.localizedDescription }
    }
    @MainActor private func save() async {
        guard !busy, !needsReload, let snapshot, let account = session.current else { return }
        busy = true; saving = true; message = nil
        defer { busy = false; saving = false }
        do {
            let value = try await session.withToken(for: account) { try await api.save(snapshot, approved: approved, token: $0) }
            guard session.current == account else { self.snapshot = nil; approved = []; return }
            self.snapshot = value; approved = Set(value.authorization.approvedPurposes); message = "선택한 기능을 저장했어요."
        } catch is CancellationError { self.snapshot = nil; approved = [] }
        catch { self.snapshot = nil; approved = []; message = error.localizedDescription + " 현재 기능 설명을 다시 불러온 뒤 선택해 주세요." }
    }
}
