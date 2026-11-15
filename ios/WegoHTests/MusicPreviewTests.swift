import XCTest
@testable import WegoH

@MainActor
final class MusicPreviewStoreTests: XCTestCase {
    private func ready(_ docs: [AccountMusicPlaylist] = []) async throws -> (MusicPreviewStore, AccountMusicFake, SessionManager, AccountSession) {
        let api = AccountMusicFake(); api.values = docs
        let session = SessionManager(api: AccountMusicAuth(), credentials: AccountMusicCredentials())
        await session.restore()
        let account = try XCTUnwrap(session.current), store = MusicPreviewStore(api: api)
        await store.load(session: session, account: account)
        return (store, api, session, account)
    }
    private var doc: AccountMusicPlaylist {
        .init(id: String(repeating: "a", count: 32), name: "기존 목록", tracks: [
            .init(id: String(repeating: "b", count: 32), title: "첫 링크", url: "https://spotify.link/first"),
            .init(id: String(repeating: "c", count: 32), title: "둘째 링크", url: "https://spotify.link/second")], revision: 7)
    }
    func testFirstLoadAndExplicitRefreshUseServerWhileTabReentryUsesCache() async throws {
        let (store, api, session, account) = try await ready([doc])
        XCTAssertEqual(store.items.count, 2); XCTAssertTrue(store.hasLoaded)
        await store.load(session: session, account: account)
        XCTAssertEqual(api.reads, 1)
        await store.load(session: session, account: account, force: true)
        XCTAssertEqual(api.reads, 2)
    }
    func testCreateUsesServerIdentityAndSurvivesASeparateStoreReload() async throws {
        let (store, api, session, account) = try await ready()
        let error = await store.save(title: "추가 링크", platform: .spotify, rawURL: "https://spotify.link/new", session: session, account: account)
        XCTAssertNil(error); XCTAssertEqual(api.creates, 1)
        XCTAssertEqual(store.items.first?.id, String(repeating: "d", count: 32) + ":" + String(repeating: "e", count: 32))
        let second = MusicPreviewStore(api: api)
        await second.load(session: session, account: account)
        XCTAssertEqual(second.items.first?.url, store.items.first?.url)
    }
    func testEditingOneLinkPreservesOtherExistingLinksAndRevision() async throws {
        let (store, api, session, account) = try await ready([doc])
        let error = await store.save(id: store.items[0].id, title: "수정 링크", platform: .spotify, rawURL: "https://spotify.link/edited", session: session, account: account)
        XCTAssertNil(error)
        XCTAssertEqual(api.updated?.tracks[1], doc.tracks[1])
        XCTAssertEqual(api.updated?.name, doc.name); XCTAssertEqual(api.updated?.revision, 7)
        XCTAssertEqual(store.documents[0].revision, 8)
    }
    func testRemovingOneOfManyLinksPreservesThePlaylistAndItsOtherLink() async throws {
        let (store, api, session, account) = try await ready([doc])
        let error = await store.remove(id: store.items[0].id, session: session, account: account)
        XCTAssertNil(error); XCTAssertEqual(api.deletes, 0)
        XCTAssertEqual(store.documents[0].tracks, [doc.tracks[1]])
        let secondError = await store.remove(id: store.items[0].id, session: session, account: account)
        XCTAssertNil(secondError); XCTAssertEqual(api.deletes, 1); XCTAssertTrue(store.items.isEmpty)
    }
    func testUncertainWriteDoesNotPublishOrAutomaticallyResend() async throws {
        let (store, api, session, account) = try await ready()
        api.failure = URLError(.networkConnectionLost)
        let error = await store.save(title: "실패 링크", platform: .spotify, rawURL: "https://spotify.link/new", session: session, account: account)
        XCTAssertNotNil(error); XCTAssertTrue(store.items.isEmpty); XCTAssertTrue(store.needsReload)
        _ = await store.save(title: "실패 링크", platform: .spotify, rawURL: "https://spotify.link/new", session: session, account: account)
        XCTAssertEqual(api.creates, 1)
        api.failure = nil
        await store.load(session: session, account: account, force: true)
        XCTAssertFalse(store.needsReload)
    }
    func testValidationRejectsUnsafeURLsMismatchedPlatformAndDuplicatesBeforeWriting() async throws {
        let (store, api, session, account) = try await ready([doc])
        for value in ["http://example.invalid/a", "https://user@example.invalid/a", "https://example.invalid/a b", "https://example.invalid:8443/a"] {
            let error = await store.save(title: "링크", platform: .other, rawURL: value, session: session, account: account)
            XCTAssertNotNil(error)
        }
        let mismatch = await store.save(title: "링크", platform: .melon, rawURL: "https://spotify.link/new", session: session, account: account)
        let duplicate = await store.save(title: "링크", platform: .spotify, rawURL: doc.tracks[0].url, session: session, account: account)
        XCTAssertNotNil(mismatch); XCTAssertNotNil(duplicate); XCTAssertEqual(api.creates, 0)
    }
    func testSignedOutAccountCannotWriteOrPublish() async throws {
        let (store, api, session, account) = try await ready()
        await session.signOut()
        let error = await store.save(title: "링크", platform: .spotify, rawURL: "https://spotify.link/new", session: session, account: account)
        XCTAssertNotNil(error); XCTAssertEqual(api.creates, 0); XCTAssertTrue(store.items.isEmpty)
    }
}

@MainActor
private final class AccountMusicFake: IPhoneMusicServing {
    var values: [AccountMusicPlaylist] = []
    var updated: AccountMusicPlaylist?
    var reads = 0, creates = 0, deletes = 0
    var failure: Error?
    func list(token: String) async throws -> [AccountMusicPlaylist] { reads += 1; return values }
    func create(title: String, url: String, token: String) async throws -> AccountMusicPlaylist {
        creates += 1
        if let failure { throw failure }
        let value = AccountMusicPlaylist(id: String(repeating: "d", count: 32), name: title,
            tracks: [.init(id: String(repeating: "e", count: 32), title: title, url: url)], revision: 1)
        values.insert(value, at: 0); return value
    }
    func update(_ value: AccountMusicPlaylist, token: String) async throws -> AccountMusicPlaylist {
        updated = value
        if let failure { throw failure }
        let saved = AccountMusicPlaylist(id: value.id, name: value.name, tracks: value.tracks, revision: value.revision + 1)
        values.removeAll { $0.id == value.id }; values.insert(saved, at: 0); return saved
    }
    func delete(_ value: AccountMusicPlaylist, token: String) async throws { deletes += 1; if let failure { throw failure }; values.removeAll { $0.id == value.id } }
}
private final class AccountMusicAuth: IPhoneSessionServing {
    func restore(token: String) async throws -> AccountSession {
        .init(accountID: "team-" + String(repeating: "1", count: 40), displayName: "샘플", expiresAt: .now.addingTimeInterval(3600), scopes: ["account:read", "account:write"])
    }
    func logout(token: String) async throws { }
    func beginLogin() async throws -> IPhoneLoginAttempt { throw IPhoneSessionError.unavailable }
    func exchange(_ attempt: IPhoneLoginAttempt, callbackURL: URL) async throws -> IPhoneSessionReceipt { throw IPhoneSessionError.unavailable }
    func cancel(_ attempt: IPhoneLoginAttempt) async throws { }
}
@MainActor
private final class AccountMusicCredentials: IPhoneCredentialStoring {
    var value: StoredIPhoneCredential? = .init(token: String(repeating: "F", count: 43), logoutPending: false)
    func load() throws -> StoredIPhoneCredential? { value }
    func saveToken(_ token: String) throws { value = .init(token: token, logoutPending: false) }
    func markLogoutPending() throws { value = nil }
    func clearToken() throws { value = nil }
}
