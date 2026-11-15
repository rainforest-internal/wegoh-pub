import AuthenticationServices
import CryptoKit
import Foundation
import XCTest
@testable import WegoH

private final class SessionHTTPStub: URLProtocol {
    static var response: ((URLRequest) throws -> (status: Int, body: [String: Any]))?

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        do {
            let respond = try XCTUnwrap(Self.response)
            let (status, body) = try respond(request)
            let url = try XCTUnwrap(request.url)
            let response = try XCTUnwrap(HTTPURLResponse(
                url: url, statusCode: status, httpVersion: "HTTP/1.1",
                headerFields: ["Content-Type": "application/json"]
            ))
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            if status != 204 {
                client?.urlProtocol(self, didLoad: try JSONSerialization.data(withJSONObject: body))
            }
            client?.urlProtocolDidFinishLoading(self)
        } catch {
            client?.urlProtocol(self, didFailWithError: error)
        }
    }

    override func stopLoading() {}
}

final class IPhoneSessionTests: XCTestCase {
    private let requestID = String(repeating: "1", count: 32)
    private let accountID = "team-" + String(repeating: "a", count: 40)
    private let token = Data(repeating: 0x5A, count: 32).base64urlForTest
    private let code = Data(repeating: 0x3A, count: 32).base64urlForTest

    private func api() -> IPhoneSessionAPI {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [SessionHTTPStub.self]
        return IPhoneSessionAPI(configuration: configuration)
    }

    override func tearDown() {
        SessionHTTPStub.response = nil
        super.tearDown()
    }

    func testDefaultClientsReuseOneHardenedTransport() {
        let shared = IPhoneSessionAPI.sharedSession
        XCTAssertTrue(IPhoneSessionAPI().session === shared)
        XCTAssertTrue(IPhoneSessionAPI().session === IPhoneSessionAPI().session)
        XCTAssertFalse(shared.configuration.httpShouldSetCookies)
        XCTAssertNil(shared.configuration.httpCookieStorage)
        XCTAssertNil(shared.configuration.urlCredentialStorage)
        XCTAssertNil(shared.configuration.urlCache)
        XCTAssertEqual(shared.configuration.timeoutIntervalForResource, 15)

        let injected = api()
        XCTAssertFalse(injected.session === shared)
        XCTAssertFalse(api().session === injected.session)
    }

    func testReleasingDefaultClientKeepsSharedTransportUsable() throws {
        do { _ = IPhoneSessionAPI() }
        // 공용 세션이 무효화됐다면 새 작업 생성이 예외로 실패한다.
        let task = IPhoneSessionAPI.sharedSession.dataTask(with: try XCTUnwrap(URL(string: "https://ios-api-wegoh.devforest.io/v1/iphone/session")))
        XCTAssertEqual(task.state, .suspended)
        task.cancel()
    }

    @MainActor
    func testApprovedLoginPersistsOnlyTheVerifiedAccountAndToken() async throws {
        let authorization = "https://wegoh.devforest.io/iphone-login?request_id=\(requestID)"
        let requestExpiry = Int(Date.now.timeIntervalSince1970) + 300
        let sessionExpiry = Int(Date.now.timeIntervalSince1970) + 86_400
        var sentChallenge = ""
        var sentState = ""
        SessionHTTPStub.response = { [self] request in
            XCTAssertEqual(request.url?.host, "ios-api-wegoh.devforest.io")
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertNil(request.value(forHTTPHeaderField: "Authorization"))
            XCTAssertNil(request.value(forHTTPHeaderField: "Cookie"))
            let body = try decodeBody(request)
            switch request.url?.path {
            case "/v1/iphone/login/requests":
                XCTAssertEqual(Set(body.keys), ["state", "codeChallenge"])
                sentChallenge = try XCTUnwrap(body["codeChallenge"])
                sentState = try XCTUnwrap(body["state"])
                return (201, ["requestId": requestID, "authorizationUrl": authorization, "expiresAt": requestExpiry])
            case "/v1/iphone/login/exchange":
                XCTAssertEqual(Set(body.keys), ["requestId", "code", "codeVerifier"])
                XCTAssertEqual(body["requestId"], requestID)
                XCTAssertEqual(body["code"], code)
                let verifier = try XCTUnwrap(body["codeVerifier"])
                XCTAssertEqual(verifier.count, 43)
                XCTAssertNotEqual(verifier, sentState)
                XCTAssertEqual(Data(SHA256.hash(data: Data(verifier.utf8))).base64urlForTest, sentChallenge)
                return (200, ["accessToken": token, "tokenType": "Bearer",
                              "user": ["id": accountID, "displayName": "테스트 사용자"],
                              "scopes": ["account:read", "maps:read", "vehicles:manage"],
                              "expiresAt": sessionExpiry])
            default:
                XCTFail("Unexpected request")
                return (404, [:])
            }
        }

        let store = MemoryCredentials()
        let browser = TestBrowser { [code] url in
            XCTAssertEqual(url.absoluteString, authorization)
            XCTAssertEqual(sentState.count, 43)
            XCTAssertNil(store.token)
            return try XCTUnwrap(URL(string: "io.wegoh.iphone://login/callback?state=\(sentState)&code=\(code)"))
        }
        let manager = SessionManager(api: api(), browser: browser, credentials: store)
        await manager.restore()
        await manager.signIn(anchor: ASPresentationAnchor())
        XCTAssertEqual(manager.phase, .signedIn)
        let account = try XCTUnwrap(manager.current)
        XCTAssertEqual(account.accountID, accountID)
        XCTAssertEqual(account.displayName, "테스트 사용자")
        XCTAssertEqual(account.expiresAt.timeIntervalSince1970, Double(sessionExpiry))
        XCTAssertEqual(store.token, token)
    }

    @MainActor
    func testAppRedirectCompletesPendingLoginAfterBrowserHandoff() async throws {
        let requestID = self.requestID
        let code = self.code
        let token = self.token
        let accountID = self.accountID
        let browser = RedirectBrowser()
        SessionHTTPStub.response = { request in
            switch request.url?.path {
            case "/v1/iphone/login/requests":
                return (201, ["requestId": requestID,
                              "authorizationUrl": "https://wegoh.devforest.io/iphone-login?request_id=\(requestID)",
                              "expiresAt": Int(Date.now.timeIntervalSince1970) + 300])
            case "/v1/iphone/login/exchange":
                return (200, ["accessToken": token, "tokenType": "Bearer",
                              "user": ["id": accountID, "displayName": "테스트 사용자"],
                              "scopes": ["account:read"],
                              "expiresAt": Int(Date.now.timeIntervalSince1970) + 86_400])
            default:
                XCTFail("Unexpected request")
                return (404, [:])
            }
        }

        let store = MemoryCredentials()
        let manager = SessionManager(api: api(), browser: browser, credentials: store)
        await manager.restore()
        let login = Task { await manager.signIn(anchor: ASPresentationAnchor()) }
        await browser.waitUntilPresented()
        let state = try XCTUnwrap(browser.expectedState)
        let callback = try XCTUnwrap(URL(string: "io.wegoh.iphone://login/callback?state=\(state)&code=\(code)"))
        let deadline = Task {
            try? await Task.sleep(for: .seconds(2))
            browser.cancel()
        }
        manager.handleIncomingURL(callback)
        await login.value
        deadline.cancel()

        XCTAssertEqual(manager.phase, .signedIn)
        XCTAssertEqual(manager.current?.accountID, accountID)
        XCTAssertEqual(store.token, token)
    }

    func testUnexpectedCallbackAndDenialNeverSendAnExchange() async throws {
        let auth = "https://wegoh.devforest.io/iphone-login?request_id=\(requestID)"
        SessionHTTPStub.response = { [self] request in
            XCTAssertEqual(request.url?.path, "/v1/iphone/login/requests")
            return (201, ["requestId": requestID, "authorizationUrl": auth, "expiresAt": Int(Date.now.timeIntervalSince1970) + 300])
        }
        let service = api()
        let attempt = try await service.beginLogin()
        let callback = "io.wegoh.iphone://login/callback"
        let incorrectCallbacks = [
            "\(callback)?state=wrong&code=\(code)",
            "\(callback)?state=\(attempt.state)&state=\(attempt.state)&code=\(code)",
            "io.wegoh.iphone://other/callback?state=\(attempt.state)&code=\(code)"
        ]
        for raw in incorrectCallbacks {
            do {
                _ = try await service.exchange(attempt, callbackURL: try XCTUnwrap(URL(string: raw)))
                XCTFail("The callback must be rejected")
            } catch IPhoneSessionError.invalidCallback {}
        }
        do {
            let denied = try XCTUnwrap(URL(string: "\(callback)?state=\(attempt.state)&error=access_denied"))
            _ = try await service.exchange(attempt, callbackURL: denied)
            XCTFail("The user denied consent")
        } catch IPhoneSessionError.denied {}
    }

    @MainActor
    func testCancelFromBrowserDiscardsAttemptWithoutCreatingASession() async {
        let store = MemoryCredentials()
        let requestID = self.requestID
        let cancelled = expectation(description: "Cancel this server request")
        SessionHTTPStub.response = { [self] request in
            switch request.url?.path {
            case "/v1/iphone/login/requests":
                return (201, ["requestId": requestID,
                              "authorizationUrl": "https://wegoh.devforest.io/iphone-login?request_id=\(requestID)",
                              "expiresAt": Int(Date.now.timeIntervalSince1970) + 300])
            case "/v1/iphone/login/cancel":
                let body = try decodeBody(request)
                XCTAssertEqual(body["requestId"], requestID)
                XCTAssertEqual(body["codeVerifier"]?.count, 43)
                cancelled.fulfill()
                return (204, [:])
            default:
                XCTFail("Cancellation must not exchange the code")
                return (404, [:])
            }
        }
        let manager = SessionManager(api: api(), browser: TestBrowser(), credentials: store)
        await manager.restore()
        await manager.signIn(anchor: ASPresentationAnchor())
        await fulfillment(of: [cancelled], timeout: 3)
        XCTAssertEqual(manager.phase, .signedOut)
        XCTAssertNil(manager.current)
        XCTAssertNil(store.token)
    }

    @MainActor
    func testColdLaunchWaitsForSuccessfulSessionVerificationAcrossDuplicateRestore() async {
        let account = AccountSession(accountID: accountID, displayName: "저장된 계정",
                                     expiresAt: Date.now.addingTimeInterval(86_400))
        let started = expectation(description: "Saved token sent for verification")
        let suspended = SuspendedSessionAPI(started: started)
        let manager = SessionManager(api: suspended, credentials: MemoryCredentials(token: token))
        XCTAssertEqual(manager.phase, .checkingSession)
        let initial = Task { await manager.restore() }
        await fulfillment(of: [started], timeout: 3)
        await manager.restore()
        XCTAssertEqual(manager.phase, .checkingSession)
        XCTAssertNil(manager.current)

        await suspended.resolve(.success(account))
        await initial.value
        XCTAssertEqual(manager.phase, .signedIn)
        XCTAssertEqual(manager.current, account)
    }

    @MainActor
    func testColdLaunchDistinguishesServerFailureFromRevocationAfterVerification() async {
        for error in [IPhoneSessionError.unavailable, .invalidSession] {
            let started = expectation(description: "Pending session verification")
            let suspended = SuspendedSessionAPI(started: started)
            let store = MemoryCredentials(token: token)
            let manager = SessionManager(api: suspended, credentials: store)
            XCTAssertEqual(manager.phase, .checkingSession)
            let initial = Task { await manager.restore() }
            await fulfillment(of: [started], timeout: 3)
            XCTAssertEqual(manager.phase, .checkingSession)
            XCTAssertFalse(manager.needsReauthentication)
            await suspended.resolve(.failure(error))
            await initial.value

            let revoked = error == .invalidSession
            XCTAssertNil(manager.current)
            XCTAssertEqual(manager.phase, revoked ? .signedOut : .restoreFailed)
            XCTAssertEqual(manager.needsReauthentication, revoked)
            XCTAssertEqual(store.token, revoked ? nil : token)
        }
    }

    @MainActor
    func testValidSessionResumeKeepsAccountVisibleWithoutAnotherServerRequest() async {
        let store = MemoryCredentials(token: token)
        let manager = SessionManager(api: api(), browser: TestBrowser(), credentials: store)
        var requests = 0
        SessionHTTPStub.response = { [self] request in
            requests += 1
            return try sessionResponse(method: "GET", status: 200, body: profile)(request)
        }
        await manager.restore()
        let account = manager.current
        XCTAssertEqual(requests, 1)
        SessionHTTPStub.response = { _ in requests += 1; return (503, [:]) }
        await manager.restore()
        XCTAssertEqual(requests, 1, "Foreground resume must use the verified session instead of requesting again")
        XCTAssertEqual(manager.phase, .signedIn)
        XCTAssertEqual(manager.current, account)
        XCTAssertEqual(store.token, token)
    }

    @MainActor
    func testRestoreRetriesTemporaryFailureAndAuthenticatedRequestClearsRevokedSession() async throws {
        let store = MemoryCredentials(token: token)
        let manager = SessionManager(api: api(), browser: TestBrowser(), credentials: store)
        SessionHTTPStub.response = sessionResponse(method: "GET", status: 503, body: [:])
        await manager.restore()
        XCTAssertEqual(manager.phase, .restoreFailed)
        XCTAssertFalse(manager.needsReauthentication)
        XCTAssertNil(manager.current)
        XCTAssertEqual(store.token, token)

        SessionHTTPStub.response = sessionResponse(method: "GET", status: 200, body: profile)
        await manager.restore()
        XCTAssertEqual(manager.current?.accountID, accountID)
        XCTAssertEqual(manager.phase, .signedIn)

        SessionHTTPStub.response = sessionResponse(method: "GET", status: 401, body: ["detail": "IPHONE_SESSION_REVOKED"])
        let account = try XCTUnwrap(manager.current)
        do {
            _ = try await manager.withToken(for: account) { try await self.api().restore(token: $0) }
            XCTFail("A revoked authenticated request must fail")
        } catch IPhoneSessionError.invalidSession { }
        XCTAssertEqual(manager.phase, .signedOut)
        XCTAssertNil(manager.current)
        XCTAssertNil(store.token)
        XCTAssertTrue(manager.needsReauthentication)
        manager.acknowledgeReauthentication()
        await manager.restore()
        XCTAssertFalse(manager.needsReauthentication)
    }

    @MainActor
    func testInterruptedLogoutStaysLockedUntilRetryOnNextLaunch() async throws {
        let service = "io.wegoh.iphone.tests." + UUID().uuidString
        let store = IPhoneCredentialStore(service: service, account: "session-fixture")
        defer { try? store.clearToken() }
        XCTAssertNil(try store.load())
        try store.saveToken(token)
        XCTAssertEqual(try store.load(), StoredIPhoneCredential(token: token, logoutPending: false))
        let manager = SessionManager(api: api(), browser: TestBrowser(), credentials: store)
        SessionHTTPStub.response = sessionResponse(method: "GET", status: 200, body: profile)
        await manager.restore()
        XCTAssertEqual(manager.phase, .signedIn)

        SessionHTTPStub.response = sessionResponse(method: "DELETE", status: 503, body: [:])
        await manager.signOut()
        XCTAssertEqual(manager.phase, .logoutPending)
        XCTAssertNil(manager.current)
        let reopenedStore = IPhoneCredentialStore(service: service, account: "session-fixture")
        XCTAssertEqual(try reopenedStore.load(), StoredIPhoneCredential(token: token, logoutPending: true))

        let relaunched = SessionManager(api: api(), browser: TestBrowser(), credentials: reopenedStore)
        SessionHTTPStub.response = sessionResponse(method: "DELETE", status: 204, body: [:])
        await relaunched.restore()
        XCTAssertEqual(relaunched.phase, .logoutPending)
        XCTAssertNil(relaunched.current)
        await relaunched.signOut()
        XCTAssertEqual(relaunched.phase, .signedOut)
        XCTAssertNil(try store.load())
        XCTAssertFalse(relaunched.needsReauthentication)
    }

    private var profile: [String: Any] {
        ["user": ["id": accountID, "displayName": "테스트 사용자"],
         "scopes": ["account:read", "maps:read", "vehicles:manage"],
         "expiresAt": Int(Date.now.timeIntervalSince1970) + 86_400]
    }

    private func sessionResponse(method: String, status: Int, body: [String: Any])
        -> (URLRequest) throws -> (status: Int, body: [String: Any]) {
        { [token] request in
            XCTAssertEqual(request.url?.absoluteString, "https://ios-api-wegoh.devforest.io/v1/iphone/session")
            XCTAssertEqual(request.httpMethod, method)
            XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer \(token)")
            XCTAssertNil(request.value(forHTTPHeaderField: "Cookie"))
            return (status, body)
        }
    }

    private func decodeBody(_ request: URLRequest) throws -> [String: String] {
        if let body = request.httpBody {
            return try XCTUnwrap(JSONSerialization.jsonObject(with: body) as? [String: String])
        }
        let stream = try XCTUnwrap(request.httpBodyStream)
        stream.open()
        defer { stream.close() }
        return try XCTUnwrap(JSONSerialization.jsonObject(with: stream) as? [String: String])
    }
}

private actor SuspendedSessionAPI: IPhoneSessionServing {
    let started: XCTestExpectation
    private var pending: CheckedContinuation<AccountSession, Error>?

    init(started: XCTestExpectation) { self.started = started }

    func restore(token: String) async throws -> AccountSession {
        try await withCheckedThrowingContinuation {
            pending = $0
            started.fulfill()
        }
    }

    func resolve(_ result: Result<AccountSession, Error>) {
        pending?.resume(with: result)
        pending = nil
    }

    func beginLogin() async throws -> IPhoneLoginAttempt { throw IPhoneSessionError.invalidResponse }
    func exchange(_ attempt: IPhoneLoginAttempt, callbackURL: URL) async throws -> IPhoneSessionReceipt {
        throw IPhoneSessionError.invalidResponse
    }
    func cancel(_ attempt: IPhoneLoginAttempt) async throws { throw IPhoneSessionError.invalidResponse }
    func logout(token: String) async throws { throw IPhoneSessionError.invalidResponse }
}

private extension Data {
    var base64urlForTest: String {
        base64EncodedString().replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_").replacingOccurrences(of: "=", with: "")
    }
}

@MainActor
private final class MemoryCredentials: IPhoneCredentialStoring {
    private var credential: StoredIPhoneCredential?
    var token: String? { credential?.token }

    init(token: String? = nil) {
        credential = token.map { StoredIPhoneCredential(token: $0, logoutPending: false) }
    }
    func load() throws -> StoredIPhoneCredential? { credential }
    func saveToken(_ token: String) throws {
        credential = StoredIPhoneCredential(token: token, logoutPending: false)
    }
    func markLogoutPending() throws {
        if let token { credential = StoredIPhoneCredential(token: token, logoutPending: true) }
    }
    func clearToken() throws { credential = nil }
}

@MainActor
private struct TestBrowser: IPhoneLoginBrowsing {
    var callback: (URL) throws -> URL = { _ in throw CancellationError() }

    func authenticate(url: URL, expiresAt: Date, state: String, anchor: ASPresentationAnchor) async throws -> URL {
        try callback(url)
    }
    func acceptIncomingURL(_ url: URL) {}
    func cancel() {}
}

@MainActor
private final class RedirectBrowser: IPhoneLoginBrowsing {
    private var callback: CheckedContinuation<URL, Error>?
    private var presented: CheckedContinuation<Void, Never>?
    private(set) var expectedState: String?

    func authenticate(url: URL, expiresAt: Date, state: String, anchor: ASPresentationAnchor) async throws -> URL {
        expectedState = state
        return try await withCheckedThrowingContinuation { continuation in
            callback = continuation
            presented?.resume()
            presented = nil
        }
    }

    func waitUntilPresented() async {
        if callback != nil { return }
        await withCheckedContinuation { presented = $0 }
    }

    func acceptIncomingURL(_ url: URL) {
        guard let callback else { return }
        self.callback = nil
        callback.resume(returning: url)
    }

    func cancel() {
        guard let callback else { return }
        self.callback = nil
        callback.resume(throwing: CancellationError())
    }
}
