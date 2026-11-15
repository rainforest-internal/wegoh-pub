import Foundation
import XCTest
@testable import WegoH

@MainActor
final class ProfileLoadStoreTests: XCTestCase {
    func testBothReadsStartBeforeEitherReplyAndGlobalNameWaitsForVehicles() async throws {
        let (store, api, session, _, account) = try await context()
        defer { api.cancelPending() }
        let load = Task { await store.load(session: session, account: account, api: api) }
        try await waitForReads(api)
        api.finishProfile(0, .success(profile(account, name: "새 이름")))
        try await waitUntil { !store.profileLoading }
        XCTAssertEqual(store.profile?.displayName, "새 이름")
        XCTAssertEqual(session.current, account)
        XCTAssertTrue(store.vehiclesLoading)
        XCTAssertTrue(store.isLoading)
        api.finishVehicles(0, .success([vehicle()]))
        await load.value
        XCTAssertEqual(store.vehicles, [vehicle()])
        XCTAssertEqual(session.current?.displayName, "새 이름")
        XCTAssertFalse(store.isLoading)
    }

    func testProfileFailureDoesNotBlockVehicleSuccess() async throws {
        for items in [[], [vehicle()]] {
            let (store, api, session, _, account) = try await context()
            defer { api.cancelPending() }
            let load = Task { await store.load(session: session, account: account, api: api) }
            try await waitForReads(api)
            api.finishProfile(0, .failure(IPhoneSessionError.unavailable))
            api.finishVehicles(0, .success(items))
            await load.value
            XCTAssertNil(store.profile)
            XCTAssertNotNil(store.error)
            XCTAssertNil(store.vehicleError)
            XCTAssertEqual(store.vehicles, items)
            XCTAssertTrue(store.hasLoadedVehicles)
            XCTAssertEqual(session.current, account)
        }
    }

    func testVehicleFailureDoesNotBlockProfileOrGlobalName() async throws {
        let (store, api, session, _, account) = try await context()
        defer { api.cancelPending() }
        let load = Task { await store.load(session: session, account: account, api: api) }
        try await waitForReads(api)
        api.finishVehicles(0, .failure(IPhoneSessionError.unavailable))
        try await waitUntil { !store.vehiclesLoading }
        XCTAssertTrue(store.profileLoading)
        api.finishProfile(0, .success(profile(account, name: "새 이름")))
        await load.value
        XCTAssertEqual(store.profile?.displayName, "새 이름")
        XCTAssertNil(store.error)
        XCTAssertNotNil(store.vehicleError)
        XCTAssertEqual(session.current?.displayName, "새 이름")
    }

    func testLogoutDiscardsBothLateReplies() async throws {
        let (store, api, session, _, account) = try await context()
        defer { api.cancelPending() }
        let load = Task { await store.load(session: session, account: account, api: api) }
        try await waitForReads(api)
        await session.signOut()
        api.finishProfile(0, .success(profile(account, name: "늦은 이름")))
        api.finishVehicles(0, .success([vehicle()]))
        await load.value
        XCTAssertNil(session.current)
        XCTAssertNil(store.profile)
        XCTAssertTrue(store.vehicles.isEmpty)
        XCTAssertNil(store.error)
        XCTAssertNil(store.vehicleError)
    }

    func testAnyChangedAccountSessionDiscardsBothLateReplies() async throws {
        for changedField in ["accountID", "displayName", "expiresAt", "scopes"] {
            let (store, api, session, auth, account) = try await context()
            defer { api.cancelPending() }
            let load = Task { await store.load(session: session, account: account, api: api) }
            try await waitForReads(api)
            auth.account = AccountSession(
                accountID: changedField == "accountID" ? "team-" + String(repeating: "b", count: 40) : account.accountID,
                displayName: changedField == "displayName" ? "다른 이름" : account.displayName,
                expiresAt: changedField == "expiresAt" ? account.expiresAt.addingTimeInterval(60) : account.expiresAt,
                scopes: changedField == "scopes" ? ["account:read"] : account.scopes)
            await session.restore()
            api.finishProfile(0, .success(profile(account, name: "늦은 이름")))
            api.finishVehicles(0, .success([vehicle()]))
            await load.value
            XCTAssertNil(store.profile, changedField)
            XCTAssertTrue(store.vehicles.isEmpty, changedField)
            XCTAssertEqual(session.current, auth.account, changedField)
        }
    }

    func testNewerRefreshWinsOverOlderReplies() async throws {
        let (store, api, session, _, account) = try await context()
        defer { api.cancelPending() }
        let old = Task { await store.load(session: session, account: account, api: api) }
        try await waitForReads(api)
        let newer = Task { await store.load(session: session, account: account, api: api) }
        try await waitForReads(api, count: 2)
        api.finishProfile(1, .success(profile(account, name: "최신 이름")))
        api.finishVehicles(1, .success([vehicle(plate: "12가3456")]))
        await newer.value
        api.finishProfile(0, .success(profile(account, name: "오래된 이름")))
        api.finishVehicles(0, .success([vehicle()]))
        await old.value
        XCTAssertEqual(store.profile?.displayName, "최신 이름")
        XCTAssertEqual(store.vehicles, [vehicle(plate: "12가3456")])
        XCTAssertEqual(session.current?.displayName, "최신 이름")
        XCTAssertFalse(store.isLoading)
    }

    func testConfirmedEditsSurvivePendingReadAndFutureRefreshUsesActualCurrentSession() async throws {
        let (store, api, session, _, account) = try await context()
        defer { api.cancelPending() }
        store.vehicles = [vehicle(plate: "99가9999")]
        let load = Task { await store.load(session: session, account: account, api: api) }
        try await waitForReads(api)
        api.finishProfile(0, .success(profile(account)))
        try await waitUntil { !store.profileLoading }
        store.profile?.displayName = "직접 변경"
        store.profile?.handle = "edited.code"
        store.vehicles[0].profile.plateNumber = "88가8888"
        session.updateDisplayName("직접 변경", for: account)
        api.finishVehicles(0, .success([vehicle()]))
        await load.value
        XCTAssertEqual(store.profile?.displayName, "직접 변경")
        XCTAssertEqual(store.profile?.handle, "edited.code")
        XCTAssertEqual(store.vehicles[0].profile.plateNumber, "88가8888")
        let current = try XCTUnwrap(session.current)
        let refresh = Task { await store.load(session: session, account: current, api: api) }
        try await waitForReads(api, count: 2)
        api.finishProfile(1, .success(.init(id: current.accountID, displayName: current.displayName, handle: "edited.code")))
        api.finishVehicles(1, .success([vehicle(plate: "88가8888")]))
        await refresh.value
        XCTAssertEqual(store.profile?.handle, "edited.code")
        XCTAssertEqual(session.current, current)
    }

    func testRefreshFailuresPreservePreviouslyLoadedValues() async throws {
        let (store, api, session, _, account) = try await context()
        defer { api.cancelPending() }
        store.profile = profile(account)
        store.vehicles = [vehicle()]
        let load = Task { await store.load(session: session, account: account, api: api) }
        try await waitForReads(api)
        api.finishProfile(0, .failure(IPhoneSessionError.unavailable))
        api.finishVehicles(0, .failure(IPhoneSessionError.unavailable))
        await load.value
        XCTAssertEqual(store.profile, profile(account))
        XCTAssertEqual(store.vehicles, [vehicle()])
        XCTAssertNotNil(store.error)
        XCTAssertNotNil(store.vehicleError)
    }

    func testWrongProfileIdentityCannotReplaceCachedProfile() async throws {
        let (store, api, session, _, account) = try await context()
        defer { api.cancelPending() }
        store.profile = profile(account)
        let load = Task { await store.load(session: session, account: account, api: api) }
        try await waitForReads(api)
        api.finishProfile(0, .success(.init(id: "team-" + String(repeating: "b", count: 40), displayName: "다른 계정", handle: "other.code")))
        api.finishVehicles(0, .success([vehicle()]))
        await load.value
        XCTAssertEqual(store.profile, profile(account))
        XCTAssertEqual(session.current, account)
        XCTAssertEqual(store.vehicles, [vehicle()])
    }

    func testInvalidSessionDropsSiblingResponseAndNeverPublishesItsError() async throws {
        for revokedRead in ["profile", "vehicles"] {
            let (store, api, session, _, account) = try await context()
            defer { api.cancelPending() }
            let load = Task { await store.load(session: session, account: account, api: api) }
            try await waitForReads(api)
            if revokedRead == "profile" {
                api.finishProfile(0, .failure(IPhoneSessionError.invalidSession))
                try await waitUntil { session.current == nil }
                api.finishVehicles(0, .success([vehicle()]))
            } else {
                api.finishVehicles(0, .failure(IPhoneSessionError.invalidSession))
                try await waitUntil { session.current == nil }
                api.finishProfile(0, .success(profile(account)))
            }
            await load.value
            XCTAssertEqual(session.phase, .signedOut)
            XCTAssertNil(store.profile)
            XCTAssertTrue(store.vehicles.isEmpty)
            XCTAssertNil(store.error)
            XCTAssertNil(store.vehicleError)
        }
    }

    private func context() async throws -> (ProfileLoadStore, ControlledProfileAPI, SessionManager, ProfileLoadAuth, AccountSession) {
        let auth = ProfileLoadAuth()
        let session = SessionManager(api: auth, credentials: ProfileLoadCredential())
        await session.restore()
        return (ProfileLoadStore(), ControlledProfileAPI(), session, auth, try XCTUnwrap(session.current))
    }

    private func profile(_ account: AccountSession, name: String? = nil) -> IPhoneProfile {
        .init(id: account.accountID, displayName: name ?? account.displayName, handle: "sample.code")
    }

    private func vehicle(plate: String = "12가1234") -> ProfileVehicle {
        .init(profile: .init(deviceId: String(repeating: "c", count: 32), plateNumber: plate, name: "합성 차량", defaultName: "합성의 차", revision: 1))
    }

    private func waitForReads(_ api: ControlledProfileAPI, count: Int = 1) async throws {
        try await waitUntil { api.profileReads.count >= count && api.vehicleReads.count >= count }
    }

    private func waitUntil(_ predicate: () -> Bool, file: StaticString = #filePath, line: UInt = #line) async throws {
        for _ in 0..<1000 where !predicate() { await Task.yield() }
        XCTAssertTrue(predicate(), "Controlled request did not reach the expected state", file: file, line: line)
        if !predicate() { throw CancellationError() }
    }
}

@MainActor
private final class ControlledProfileAPI: IPhoneProfileServing {
    var profileReads: [CheckedContinuation<IPhoneProfile, Error>?] = []
    var vehicleReads: [CheckedContinuation<[ProfileVehicle], Error>?] = []
    func profile(token: String) async throws -> IPhoneProfile {
        try await withCheckedThrowingContinuation { profileReads.append($0) }
    }
    func vehicles(token: String) async throws -> [ProfileVehicle] {
        try await withCheckedThrowingContinuation { vehicleReads.append($0) }
    }
    func finishProfile(_ index: Int, _ result: Result<IPhoneProfile, Error>) {
        let pending = profileReads[index]; profileReads[index] = nil; pending?.resume(with: result)
    }
    func finishVehicles(_ index: Int, _ result: Result<[ProfileVehicle], Error>) {
        let pending = vehicleReads[index]; vehicleReads[index] = nil; pending?.resume(with: result)
    }
    func cancelPending() {
        for index in profileReads.indices { finishProfile(index, .failure(CancellationError())) }
        for index in vehicleReads.indices { finishVehicles(index, .failure(CancellationError())) }
    }
    func name(_ name: String, expected: String, token: String) async throws -> String { throw IPhoneSessionError.unavailable }
    func handle(_ handle: String, expected: String, token: String) async throws -> String { throw IPhoneSessionError.unavailable }
    func vehicle(_ id: String, token: String) async throws -> IPhoneVehicleProfile { throw IPhoneSessionError.unavailable }
    func plate(_ plate: String, vehicle: IPhoneVehicleProfile, token: String) async throws -> IPhoneVehicleProfile { throw IPhoneSessionError.unavailable }
    func vehicleName(_ name: String, vehicle: IPhoneVehicleProfile, token: String) async throws -> IPhoneVehicleProfile { throw IPhoneSessionError.unavailable }
}

private final class ProfileLoadAuth: IPhoneSessionServing {
    var account = AccountSession(accountID: "team-" + String(repeating: "a", count: 40), displayName: "기존 이름",
                                 expiresAt: .now.addingTimeInterval(3600), scopes: ["account:read", "account:write", "vehicles:manage"])
    func restore(token: String) async throws -> AccountSession { account }
    func logout(token: String) async throws { }
    func beginLogin() async throws -> IPhoneLoginAttempt { throw IPhoneSessionError.unavailable }
    func exchange(_ attempt: IPhoneLoginAttempt, callbackURL: URL) async throws -> IPhoneSessionReceipt { throw IPhoneSessionError.unavailable }
    func cancel(_ attempt: IPhoneLoginAttempt) async throws { }
}

@MainActor
private final class ProfileLoadCredential: IPhoneCredentialStoring {
    var value: StoredIPhoneCredential? = .init(token: String(repeating: "F", count: 43), logoutPending: false)
    func load() throws -> StoredIPhoneCredential? { value }
    func saveToken(_ token: String) throws { value = .init(token: token, logoutPending: false) }
    func markLogoutPending() throws { value = value.map { .init(token: $0.token, logoutPending: true) } }
    func clearToken() throws { value = nil }
}
