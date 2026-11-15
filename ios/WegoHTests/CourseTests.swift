import AuthenticationServices
import Foundation
import XCTest
@testable import WegoH

private final class CourseHTTPStub: URLProtocol {
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

final class CourseTests: XCTestCase {
    private var place: CoursePlace {
        CoursePlace(id: "kakao-1", name: "경포해변", address: "강원 강릉시 안현동", roadAddress: "",
                    lat: 37.8, lng: 128.9, source: "kakao")
    }
    private var pack: OwnedCourse {
        OwnedCourse(id: "course-fixture", version: 1, title: "바다 드라이브", author: "테스트 계정",
                    description: "강릉 바다 코스", stops: [CourseStop(place: place)])
    }
    private func summary(_ pack: OwnedCourse) -> CourseSummary {
        CourseSummary(id: pack.id, version: pack.version, title: pack.title, author: pack.author,
                      description: pack.description, stopCount: pack.stops.count, stopNames: pack.stops.map(\.name),
                      checksum: String(repeating: "a", count: 64), state: "approved",
                      stops: pack.stops.map(CourseCardStop.init))
    }
    override func tearDown() { CourseHTTPStub.respond = nil; super.tearDown() }

    func testDraftPreservesOriginalPlaceMetadataAndRequiresAnExplicitPublicationChoice() {
        let original = pack
        var draft = CourseDraft(detail: CourseDetail(pack: original, remixDraftId: String(repeating: "b", count: 32), tags: ["바다"], hasCover: true))
        XCTAssertEqual(draft.tags, ["바다"])
        XCTAssertEqual(draft.copyCoverFromVersion, 1)
        XCTAssertEqual(draft.pack.version, 2)
        XCTAssertEqual(draft.pack.stops, original.stops)
        XCTAssertFalse(draft.hasChanges)
        XCTAssertFalse(draft.canSave)
        draft.pack.title = "바꾼 이름"
        XCTAssertTrue(draft.hasChanges)
        XCTAssertFalse(draft.canSave)
        draft.rightsConfirmed = true
        XCTAssertTrue(draft.canSave)
        XCTAssertEqual(original.title, "바다 드라이브")
        draft.pack.stops = []
        XCTAssertFalse(draft.canSave)
    }

    func testSummaryCarriesOneServerStopNamePerStop() {
        let valid = summary(pack)
        XCTAssertTrue(valid.isValid)
        XCTAssertEqual(valid.stopNames, ["경포해변"])
        for names in [[String](), ["경포해변", "안목해변"], [" "], [String(repeating: "가", count: 81)]] {
            let invalid = CourseSummary(id: valid.id, version: valid.version, title: valid.title, author: valid.author,
                                        description: valid.description, stopCount: 1, stopNames: names,
                                        checksum: valid.checksum, state: valid.state, stops: valid.stops)
            XCTAssertFalse(invalid.isValid, "\(names)")
        }
    }

    func testCardStopNamesReadEveryPlaceAndNameTheDestination() {
        XCTAssertEqual(CourseCardStopNames.accessibilityLabel(["경포해변"]), "장소 경포해변")
        XCTAssertEqual(CourseCardStopNames.accessibilityLabel(["강릉역", "안목해변", "경포대"]),
                       "경로 강릉역, 안목해변, 목적지 경포대")
    }

    func testRegistrationRequirementsCoverUnicodeLimitsAndExplicitPublication() {
        var draft = CourseDraft(author: "사용자F")
        XCTAssertNotNil(draft.saveRequirement)
        draft.pack.title = String(repeating: "가", count: 100)
        draft.pack.description = String(repeating: "나", count: 500)
        draft.pack.stops = [CourseStop(place: place)]
        XCTAssertFalse(draft.canSave)
        draft.rightsConfirmed = true
        XCTAssertTrue(draft.canSave)
        XCTAssertNil(draft.saveRequirement)
        draft.pack.title += "🙂"
        XCTAssertFalse(draft.canSave)
        XCTAssertNotNil(draft.saveRequirement)
        draft.pack.title = "코스"
        draft.pack.description += "🙂"
        XCTAssertFalse(draft.canSave)
        XCTAssertNotNil(draft.saveRequirement)
        draft.pack.description = "설명"
        draft.pack.stops = []
        XCTAssertFalse(draft.canSave)
        XCTAssertNotNil(draft.saveRequirement)
    }

    func testPlaceSearchFailureKeepsAnExplicitRetryAndUsesPlaceSpecificFeedback() async throws {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [CourseHTTPStub.self]
        let api = IPhoneCourseAPI(configuration: config), item = place
        var calls = 0
        CourseHTTPStub.respond = { request in
            calls += 1
            XCTAssertEqual(request.url?.path, "/v1/iphone/places/search")
            let items = URLComponents(url: request.url!, resolvingAgainstBaseURL: false)?.queryItems
            XCTAssertEqual(items, [URLQueryItem(name: "q", value: "경포해변")])
            if calls == 1 { return (503, Data("{\"detail\":\"PLACE_SEARCH_UNAVAILABLE\"}".utf8)) }
            return (200, try JSONEncoder().encode(["places": [item]]))
        }
        do {
            _ = try await api.search(" 경포해변 ", token: String(repeating: "F", count: 43))
            XCTFail("Unavailable provider accepted")
        } catch {
            XCTAssertTrue(placeSearchErrorMessage(error).contains("장소 검색"))
        }
        XCTAssertEqual(calls, 1)
        let found = try await api.search(" 경포해변 ", token: String(repeating: "F", count: 43))
        XCTAssertEqual(found, [item])
        XCTAssertEqual(calls, 2)
    }

    func testAPIUsesTheExistingBearerAndRejectsMixedOwnerOrVersionResponses() async throws {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [CourseHTTPStub.self]
        let api = IPhoneCourseAPI(configuration: config), original = pack, row = summary(pack)
        CourseHTTPStub.respond = { request in
            XCTAssertEqual(request.url?.host, "ios-api-wegoh.devforest.io")
            XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer " + String(repeating: "F", count: 43))
            XCTAssertNil(request.value(forHTTPHeaderField: "Cookie"))
            return (200, try JSONEncoder().encode(CourseDetail(pack: original, remixDraftId: nil)))
        }
        let received = try await api.detail(row, token: String(repeating: "F", count: 43))
        XCTAssertEqual(received.pack, original)
        var changed = original
        changed.id = "someone-else"
        CourseHTTPStub.respond = { _ in (200, try JSONEncoder().encode(CourseDetail(pack: changed, remixDraftId: nil))) }
        do { _ = try await api.detail(row, token: String(repeating: "F", count: 43)); XCTFail("Mismatched detail accepted") }
        catch IPhoneSessionError.invalidResponse { }
        CourseHTTPStub.respond = { _ in (409, Data("{\"detail\":\"Published versions are immutable\"}".utf8)) }
        var draft = CourseDraft(detail: received)
        draft.pack.title = "수정 이름"; draft.rightsConfirmed = true
        do { _ = try await api.save(draft, token: String(repeating: "F", count: 43)); XCTFail("Stale write accepted") }
        catch IPhoneResourceError.conflict { }
    }

    @MainActor
    func testResourceRequestsDoNotRestoreTheSessionAndLateResultsAfterLogoutAreDiscarded() async throws {
        let auth = CourseTestSession(), credential = CourseTestCredential()
        let session = SessionManager(api: auth, credentials: credential)
        await session.restore()
        let account = try XCTUnwrap(session.current)
        let token1 = try await session.withToken(for: account) { $0 }
        let token2 = try await session.withToken(for: account) { $0 }
        XCTAssertEqual(token1, token2)
        XCTAssertEqual(auth.restoreCount, 1)
        var continuation: CheckedContinuation<String, Never>?
        let pending = Task {
            try await session.withToken(for: account) { _ in
                await withCheckedContinuation { continuation = $0 }
            }
        }
        while continuation == nil { await Task.yield() }
        await session.signOut()
        continuation?.resume(returning: "old private result")
        do { _ = try await pending.value; XCTFail("Old account result accepted") }
        catch is CancellationError { }
        XCTAssertNil(session.current)
    }

    func testRoutePostsTheOrderedPlacesAndRejectsMalformedGeometry() async throws {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [CourseHTTPStub.self]
        let api = IPhoneCourseAPI(configuration: config)
        let points = [CourseCoordinate(lat: 37.8068, lng: 128.9087), CourseCoordinate(lat: 37.7725, lng: 128.9478)]
        CourseHTTPStub.respond = { request in
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertEqual(request.url?.path, "/v1/iphone/routes/preview")
            XCTAssertNil(request.url?.query)
            return (200, Data("{\"distanceMeters\":6100,\"durationSeconds\":780,\"path\":[[37.8068,128.9087],[37.79,128.92],[37.7725,128.9478]]}".utf8))
        }
        let route = try await api.route(points, token: String(repeating: "F", count: 43))
        XCTAssertEqual(route.path.count, 3)
        XCTAssertEqual(route.path.first, points.first)
        XCTAssertEqual(route.path.last, points.last)
        CourseHTTPStub.respond = { _ in
            (200, Data("{\"distanceMeters\":1,\"durationSeconds\":1,\"path\":[[37.8],[37.7,128.9]]}".utf8))
        }
        do { _ = try await api.route(points, token: String(repeating: "F", count: 43)); XCTFail("Malformed route accepted") }
        catch IPhoneSessionError.invalidResponse { }
    }
}

@MainActor
private final class CourseTestCredential: IPhoneCredentialStoring {
    var value: StoredIPhoneCredential? = .init(token: String(repeating: "F", count: 43), logoutPending: false)
    func load() throws -> StoredIPhoneCredential? { value }
    func saveToken(_ token: String) throws { value = .init(token: token, logoutPending: false) }
    func markLogoutPending() throws { value = value.map { .init(token: $0.token, logoutPending: true) } }
    func clearToken() throws { value = nil }
}

private final class CourseTestSession: IPhoneSessionServing {
    var restoreCount = 0
    func restore(token: String) async throws -> AccountSession {
        restoreCount += 1
        return .init(accountID: "team-" + String(repeating: "a", count: 40), displayName: "테스트 계정", expiresAt: .now.addingTimeInterval(3600))
    }
    func beginLogin() async throws -> IPhoneLoginAttempt { throw IPhoneSessionError.unavailable }
    func exchange(_ attempt: IPhoneLoginAttempt, callbackURL: URL) async throws -> IPhoneSessionReceipt { throw IPhoneSessionError.unavailable }
    func cancel(_ attempt: IPhoneLoginAttempt) async throws { }
    func logout(token: String) async throws { }
}
