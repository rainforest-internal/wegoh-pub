import Foundation
import XCTest
@testable import WegoH

private final class FriendHTTPStub: URLProtocol {
    static var respond: ((URLRequest) throws -> (Int, Data))?
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func stopLoading() { }
    override func startLoading() {
        do {
            let (status, data) = try Self.respond!(request)
            let response = HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: nil,
                                            headerFields: ["Content-Type": "application/json"])!
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: data)
            client?.urlProtocolDidFinishLoading(self)
        } catch { client?.urlProtocol(self, didFailWithError: error) }
    }
}

@MainActor
final class IPhoneFriendsTests: XCTestCase {
    private var person: FriendPerson { .init(id: "team-" + String(repeating: "b", count: 40), name: "친구", handle: "friend_code") }
    override func tearDown() { FriendHTTPStub.respond = nil; super.tearDown() }

    func testFriendCodeNormalizationAndExactBearerSearch() async throws {
        XCTAssertEqual(normalizedFriendCode(" @FRIEND_Code "), "friend_code")
        for code in ["ab", "한글코드", "Kkk", "a/b", "a b", String(repeating: "a", count: 21)] { XCTAssertNil(normalizedFriendCode(code)) }
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [FriendHTTPStub.self]
        let api = IPhoneFriendsAPI(configuration: config)
        var calls = 0
        FriendHTTPStub.respond = { request in
            calls += 1
            XCTAssertEqual(request.url?.host, "ios-api-wegoh.devforest.io")
            XCTAssertEqual(request.url?.path, "/v1/iphone/friends/search")
            XCTAssertEqual(URLComponents(url: request.url!, resolvingAgainstBaseURL: false)?.queryItems,
                           [URLQueryItem(name: "handle", value: "friend_code")])
            XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer " + String(repeating: "F", count: 43))
            XCTAssertNil(request.value(forHTTPHeaderField: "Cookie"))
            return (200, Data("{\"person\":null}".utf8))
        }
        let missing = try await api.search(code: " @FRIEND_Code ", token: String(repeating: "F", count: 43))
        XCTAssertNil(missing)
        XCTAssertEqual(calls, 1)
        FriendHTTPStub.respond = { _ in calls += 1; return (503, Data("{}".utf8)) }
        do { _ = try await api.search(code: "friend_code", token: String(repeating: "F", count: 43)); XCTFail("Unavailable search accepted") }
        catch { XCTAssertTrue(friendErrorMessage(error).contains("친구 서버")) }
        XCTAssertEqual(calls, 2)
    }

    func testMalformedOrMismatchedPeopleAndReceiptsAreRejected() async throws {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [FriendHTTPStub.self]
        let api = IPhoneFriendsAPI(configuration: config), id = person.id
        FriendHTTPStub.respond = { _ in
            (200, Data("{\"person\":{\"id\":\"\(id)\",\"name\":\"다른 계정\",\"handle\":\"different\",\"relationship\":\"none\"}}".utf8))
        }
        do { _ = try await api.search(code: "friend_code", token: String(repeating: "F", count: 43)); XCTFail("Mismatched search accepted") }
        catch IPhoneSessionError.invalidResponse { }
        FriendHTTPStub.respond = { _ in (200, Data("{\"status\":\"blocked\"}".utf8)) }
        do { _ = try await api.perform(.request, person: person, token: String(repeating: "F", count: 43)); XCTFail("Wrong mutation receipt accepted") }
        catch IPhoneSessionError.invalidResponse { }
    }

    func testConfirmedMutationUpdatesOnlyItsPersonAndDoesNotRefetchOrRestoreSession() async throws {
        let auth = FriendAuth(), session = SessionManager(api: auth, credentials: FriendCredential())
        await session.restore()
        let account = try XCTUnwrap(session.current)
        let api = FriendTestAPI(), store = FriendsStore(api: api), person = person
        await store.load(session: session, account: account)
        let found = try await store.search(code: "friend_code", session: session, account: account)
        XCTAssertEqual(found?.id, person.id)
        XCTAssertEqual(store.relationship(to: person), .none)
        let sent = await store.perform(.request, person: person, session: session, account: account)
        XCTAssertTrue(sent)
        XCTAssertEqual(store.outgoing.map(\.id), [person.id])
        XCTAssertEqual(store.relationship(to: person), .outgoing)
        XCTAssertEqual(api.overviewCalls, 1)
        XCTAssertEqual(auth.restores, 1)
        api.failure = IPhoneResourceError.conflict
        let cancelled = await store.perform(.cancel, person: person, session: session, account: account)
        XCTAssertFalse(cancelled)
        XCTAssertEqual(store.outgoing.map(\.id), [person.id])
        XCTAssertNotNil(store.error)
    }

    func testExplicitRefreshMovesRemotelyAcceptedRequestIntoFriendsWhileRetainingCachedList() async throws {
        let auth = FriendAuth(), session = SessionManager(api: auth, credentials: FriendCredential())
        await session.restore()
        let account = try XCTUnwrap(session.current)
        let api = FriendTestAPI(), store = FriendsStore(api: api), person = person
        await store.load(session: session, account: account)
        let sent = await store.perform(.request, person: person, session: session, account: account)
        XCTAssertTrue(sent)
        XCTAssertEqual(store.outgoing.map(\.id), [person.id])
        api.pauseRead = true
        let refresh = Task { await store.load(session: session, account: account) }
        while api.readContinuation == nil { await Task.yield() }
        XCTAssertTrue(store.isLoading)
        XCTAssertEqual(store.outgoing.map(\.id), [person.id])
        XCTAssertTrue(store.friends.isEmpty)
        api.readContinuation?.resume(returning: .init(friends: [person], requests: [], blocks: []))
        await refresh.value
        XCTAssertFalse(store.isLoading)
        XCTAssertTrue(store.outgoing.isEmpty)
        XCTAssertEqual(store.friends.map(\.id), [person.id])
        XCTAssertEqual(store.relationship(to: person), .friend)
        XCTAssertEqual(api.overviewCalls, 2)
        XCTAssertEqual(auth.restores, 1)
    }

    func testOlderReadAndMutationResultsAfterLogoutCannotOverwriteCurrentState() async throws {
        let session = SessionManager(api: FriendAuth(), credentials: FriendCredential())
        await session.restore()
        let account = try XCTUnwrap(session.current)
        let api = FriendTestAPI(), store = FriendsStore(api: api), person = person
        api.pauseRead = true
        let read = Task { await store.load(session: session, account: account) }
        while api.readContinuation == nil { await Task.yield() }
        let sent = await store.perform(.request, person: person, session: session, account: account)
        XCTAssertTrue(sent)
        api.readContinuation?.resume(returning: .init(friends: [], requests: [], blocks: []))
        await read.value
        XCTAssertEqual(store.outgoing.map(\.id), [person.id])
        api.pauseWrite = true
        let pending = Task { await store.perform(.cancel, person: person, session: session, account: account) }
        while api.writeContinuation == nil { await Task.yield() }
        await session.signOut()
        api.writeContinuation?.resume(returning: .none)
        let applied = await pending.value
        XCTAssertFalse(applied)
        XCTAssertEqual(store.outgoing.map(\.id), [person.id])
    }
}

@MainActor
private final class FriendTestAPI: IPhoneFriendsServing {
    var overviewCalls = 0
    var failure: Error?
    var pauseRead = false, pauseWrite = false
    var readContinuation: CheckedContinuation<FriendsOverview, Never>?
    var writeContinuation: CheckedContinuation<FriendRelationship, Never>?
    func overview(token: String) async throws -> FriendsOverview {
        overviewCalls += 1
        if pauseRead { return await withCheckedContinuation { readContinuation = $0 } }
        return .init(friends: [], requests: [], blocks: [])
    }
    func search(code: String, token: String) async throws -> FriendPerson? {
        .init(id: "team-" + String(repeating: "b", count: 40), name: "친구", handle: "friend_code", relationship: FriendRelationship.none)
    }
    func perform(_ action: FriendAction, person: FriendPerson, token: String) async throws -> FriendRelationship {
        if let failure { throw failure }
        if pauseWrite { return await withCheckedContinuation { writeContinuation = $0 } }
        return action == .request ? .outgoing : .none
    }
    func profile(_ person: FriendPerson, token: String) async throws -> FriendProfile { .init(name: person.displayName, plateNumbers: []) }
}

private final class FriendAuth: IPhoneSessionServing {
    var restores = 0
    func restore(token: String) async throws -> AccountSession {
        restores += 1
        return .init(accountID: "team-" + String(repeating: "a", count: 40), displayName: "나", expiresAt: .now.addingTimeInterval(3600), scopes: ["account:read", "friends:read", "friends:manage"])
    }
    func logout(token: String) async throws { }
    func beginLogin() async throws -> IPhoneLoginAttempt { throw IPhoneSessionError.unavailable }
    func exchange(_ attempt: IPhoneLoginAttempt, callbackURL: URL) async throws -> IPhoneSessionReceipt { throw IPhoneSessionError.unavailable }
    func cancel(_ attempt: IPhoneLoginAttempt) async throws { }
}

@MainActor
private final class FriendCredential: IPhoneCredentialStoring {
    var value: StoredIPhoneCredential? = .init(token: String(repeating: "F", count: 43), logoutPending: false)
    func load() throws -> StoredIPhoneCredential? { value }
    func saveToken(_ token: String) throws { value = .init(token: token, logoutPending: false) }
    func markLogoutPending() throws { }
    func clearToken() throws { value = nil }
}
