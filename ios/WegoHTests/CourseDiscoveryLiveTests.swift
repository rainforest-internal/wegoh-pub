import Foundation
import UIKit
import XCTest
@testable import WegoH

private final class CourseDiscoveryHTTPStub: URLProtocol {
    static var handler: ((URLRequest) throws -> (Int, [String: Any]))?
    static var binaryHandler: ((URLRequest) throws -> (Int, String, Data))?
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func stopLoading() { }
    override func startLoading() {
        do {
            if let binary = Self.binaryHandler {
                let (status, mime, bytes) = try binary(request)
                let response = HTTPURLResponse(url: try XCTUnwrap(request.url), statusCode: status,
                    httpVersion: nil, headerFields: ["Content-Type": mime])!
                client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
                client?.urlProtocol(self, didLoad: bytes)
                client?.urlProtocolDidFinishLoading(self)
                return
            }
            let (status, json) = try XCTUnwrap(Self.handler)(request)
            let response = HTTPURLResponse(url: try XCTUnwrap(request.url), statusCode: status,
                httpVersion: nil, headerFields: ["Content-Type": "application/json"])!
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: try JSONSerialization.data(withJSONObject: json))
            client?.urlProtocolDidFinishLoading(self)
        } catch { client?.urlProtocol(self, didFailWithError: error) }
    }
}

final class CourseDiscoveryLiveTests: XCTestCase {
    private let token = String(repeating: "L", count: 43)
    private let creatorID = "team-" + String(repeating: "a", count: 40)
    private let followID = "11111111-2222-3333-4444-555555555555"
    private let checksum = String(repeating: "a", count: 64)

    override func tearDown() { CourseDiscoveryHTTPStub.handler = nil; CourseDiscoveryHTTPStub.binaryHandler = nil; super.tearDown() }

    private func api() -> CourseDiscoveryAPI {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [CourseDiscoveryHTTPStub.self]
        return CourseDiscoveryAPI(configuration: config)
    }
    private func itemJSON(starred: Bool = false) -> [String: Any] {
        ["id": "coast", "version": 2, "title": "해안 코스", "author": "창작자", "description": "해안과 카페",
         "stopCount": 1, "stopNames": ["합류 카페"], "starred": starred, "starCount": 4, "tags": ["바다", "카페"], "canFollow": true,
         "followId": NSNull(), "creatorRank": NSNull(), "creatorId": creatorID, "hasCover": false, "checksum": checksum,
         "stops": [["id": "stop-join", "name": "합류 카페", "lat": 37.5, "lng": 127]]]
    }
    private func item() throws -> CourseDiscoveryItem { try decode(itemJSON()) }
    private func libraryJSON() -> [String: Any] {
        var news = itemJSON()
        news["eventId"] = "123"; news["approvedAt"] = "2026-11-13T05:00:00+00:00"; news["read"] = false
        return ["public": [itemJSON()], "saved": [itemJSON(starred: true)], "news": [news],
                "following": [["id": followID, "name": "창작자", "creatorId": creatorID]],
                "popularTags": ["바다", "카페"], "followedTags": ["바다"], "unreadCount": 1]
    }
    private func packJSON(id: String = "coast", version: Int = 2) -> [String: Any] {
        ["schemaVersion": 1, "id": id, "version": version, "title": "해안 코스", "author": "창작자", "description": "해안과 카페",
         "stops": [["id": "stop-join", "name": "합류 카페", "latitude": 37.5, "longitude": 127,
                    "radiusMeters": 100, "action": ["type": "chime", "message": "도착했어요."]]]]
    }
    private func detailJSON() -> [String: Any] {
        ["pack": packJSON(), "checksum": checksum, "tags": ["바다", "카페"], "hasCover": false,
         "creatorId": creatorID, "starred": false, "starCount": 4, "canFollow": true, "followId": NSNull()]
    }
    private func decode<T: Decodable>(_ json: [String: Any]) throws -> T {
        try JSONDecoder().decode(T.self, from: JSONSerialization.data(withJSONObject: json))
    }
    private func body(_ request: URLRequest) throws -> [String: Any] {
        XCTAssertEqual(request.value(forHTTPHeaderField: "Content-Type"), "application/json")
        var data = request.httpBody ?? Data()
        if data.isEmpty, let stream = request.httpBodyStream {
            stream.open(); defer { stream.close() }
            var buffer = [UInt8](repeating: 0, count: 1024)
            while true {
                let count = stream.read(&buffer, maxLength: buffer.count)
                if count == 0 { break }
                if count < 0 { throw stream.streamError ?? URLError(.cannotDecodeRawData) }
                data.append(contentsOf: buffer.prefix(count))
            }
        }
        return try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
    }
    private func stub(_ method: String, _ path: String, status: Int = 200, json: [String: Any],
                      check: ((URLRequest) throws -> Void)? = nil) {
        CourseDiscoveryHTTPStub.handler = { request in
            XCTAssertEqual(request.httpMethod, method)
            XCTAssertEqual(request.url?.scheme, "https")
            XCTAssertEqual(request.url?.host, "ios-api-wegoh.devforest.io")
            XCTAssertEqual(request.url?.path, "/v1/iphone/" + path)
            XCTAssertTrue(request.value(forHTTPHeaderField: "Authorization") == "Bearer " + self.token)
            XCTAssertNil(request.value(forHTTPHeaderField: "Cookie"))
            try check?(request)
            return (status, json)
        }
    }

    func testLibrarySearchSendsRepeatedAndTagsAndReadsActualPersonalState() async throws {
        stub("GET", "courses/library", json: libraryJSON()) { request in
            let query = try XCTUnwrap(URLComponents(url: try XCTUnwrap(request.url), resolvingAgainstBaseURL: false)?.queryItems)
            XCTAssertEqual(query.filter { $0.name == "q" }.map(\.value), ["해안 카페"])
            XCTAssertEqual(query.filter { $0.name == "tag" }.map(\.value), ["바다", "카페"])
        }
        let value = try await api().library(query: "  해안 카페  ", tags: ["바다", "카페"], token: token)
        XCTAssertEqual(value.recommended.map(\.id), ["coast"])
        XCTAssertTrue(value.saved[0].starred)
        XCTAssertEqual(value.following[0].creatorId, creatorID)
        XCTAssertFalse(value.news[0].read)
        XCTAssertEqual(value.unreadCount, 1)
    }

    func testSearchPreservesLiteralPlusInRawQuery() async throws {
        stub("GET", "courses/library", json: libraryJSON()) { request in
            let raw = try XCTUnwrap(URLComponents(url: try XCTUnwrap(request.url), resolvingAgainstBaseURL: false)?.percentEncodedQuery)
            XCTAssertEqual(raw, "q=C%2B%2B%20%EC%BD%94%EC%8A%A4")
            XCTAssertFalse(raw.contains("+"))
        }
        _ = try await api().library(query: "C++ 코스", tags: [], token: token)
    }

    func testLibraryRejectsBadCountsDuplicateReferencesAndUnknownPublicationMetadata() async throws {
        let valid = libraryJSON()
        var malformed: [[String: Any]] = []
        var bad = valid; var summary = itemJSON(); summary["starCount"] = -1; bad["public"] = [summary]; malformed.append(bad)
        bad = valid; summary = itemJSON(); summary["starCount"] = true; bad["public"] = [summary]; malformed.append(bad)
        bad = valid; summary = itemJSON(); summary["checksum"] = "missing"; bad["public"] = [summary]; malformed.append(bad)
        bad = valid; summary = itemJSON(); summary["stopNames"] = ["합류 카페", "추가 장소"]; bad["public"] = [summary]; malformed.append(bad)
        bad = valid; summary = itemJSON(); summary["stopNames"] = [" "]; bad["public"] = [summary]; malformed.append(bad)
        bad = valid; bad["public"] = [itemJSON(), itemJSON()]; malformed.append(bad)
        bad = valid; bad["saved"] = [itemJSON(starred: false)]; malformed.append(bad)
        bad = valid; bad["followedTags"] = ["바다", "#바다"]; malformed.append(bad)
        bad = valid; bad["unreadCount"] = -1; malformed.append(bad)
        for json in malformed {
            stub("GET", "courses/library", json: json)
            do { _ = try await api().library(query: "", tags: [], token: token); XCTFail("Invalid library accepted") }
            catch IPhoneSessionError.invalidResponse { }
        }
    }

    func testPublicDetailAndCreatorValidateExactReferences() async throws {
        let item = try item()
        stub("GET", "courses/public/coast/versions/2", json: detailJSON())
        let detail = try await api().detail(item, token: token)
        XCTAssertEqual(detail.pack.id, "coast")
        var mismatch = detailJSON(); mismatch["checksum"] = String(repeating: "b", count: 64)
        stub("GET", "courses/public/coast/versions/2", json: mismatch)
        do { _ = try await api().detail(item, token: token); XCTFail("Wrong checksum accepted") }
        catch IPhoneSessionError.invalidResponse { }
        let profile: [String: Any] = ["id": creatorID, "name": "창작자", "courseCount": 1, "starCount": 4,
                                      "followerCount": 2, "following": false, "followId": NSNull()]
        stub("GET", "courses/creators/" + creatorID, json: ["creator": profile, "courses": [itemJSON()]])
        let creator = try await api().creator(creatorID, token: token)
        XCTAssertEqual(creator.creator.courseCount, 1)
        XCTAssertEqual(creator.creator.followerCount, 2)
    }

    func testStarsCreatorTagFollowsAndNewsReadUseClosedIPhoneWrites() async throws {
        let item = try item(), api = api()
        let empty: (URLRequest) throws -> Void = { request in XCTAssertTrue(try self.body(request).isEmpty) }
        stub("PUT", "courses/stars/coast/versions/2", json: ["starred": true], check: empty)
        try await api.setStarred(item, starred: true, token: token)
        stub("DELETE", "courses/stars/coast/versions/2", json: ["starred": false], check: empty)
        try await api.setStarred(item, starred: false, token: token)
        stub("PUT", "courses/follows/coast/versions/2", json: ["followId": followID], check: empty)
        try await api.followCreator(item, token: token)
        stub("DELETE", "courses/follows/" + followID, json: ["following": false], check: empty)
        try await api.unfollowCreator(followID, token: token)
        stub("PUT", "courses/tag-follows/바다", json: ["following": true, "tag": "바다"], check: empty)
        try await api.setTagFollowed("바다", followed: true, token: token)
        stub("PUT", "courses/tag-follows/CAFE", json: ["following": true, "tag": "Cafe"], check: empty)
        try await api.setTagFollowed("CAFE", followed: true, token: token)
        stub("PUT", "courses/news/123/read", json: ["read": true], check: empty)
        try await api.markRead("123", token: token)
        stub("PUT", "courses/news/123/read", json: ["read": false])
        do { try await api.markRead("123", token: token); XCTFail("False read receipt accepted") }
        catch IPhoneSessionError.invalidResponse { }
    }

    func testReportAndHiddenAreExplicitAndDoNotCallLearningConsent() async throws {
        let item = try item(), api = api()
        stub("PUT", "courses/hidden/coast/versions/2", json: ["hidden": true]) { request in
            XCTAssertTrue(try self.body(request).isEmpty)
        }
        try await api.notInterested(item, token: token)
        stub("POST", "courses/public/coast/versions/2/reports", status: 202,
             json: ["reportId": String(repeating: "a", count: 32), "state": "quarantined"]) { request in
            let value = try self.body(request)
            XCTAssertEqual(Set(value.keys), ["reason"])
            XCTAssertEqual(value["reason"] as? String, "privacy")
        }
        try await api.report(item, reason: "privacy", token: token)
        var requests = 0
        CourseDiscoveryHTTPStub.handler = { _ in requests += 1; return (200, [:]) }
        do { try await api.report(item, reason: "invented", token: token); XCTFail("Unknown report reason accepted") }
        catch CourseRequestError.invalidInput { }
        XCTAssertEqual(requests, 0)
    }

    func testCopyRequiresServerIssuedNewIDVersionOneAndProvenanceReceipt() async throws {
        let item = try item()
        let valid: [String: Any] = ["pack": packJSON(id: "course-copy", version: 1),
                                   "remixDraftId": String(repeating: "b", count: 32), "tags": ["바다", "카페"], "hasCover": false]
        stub("POST", "courses/public/coast/versions/2/copy", status: 201, json: valid) { request in
            XCTAssertTrue(try self.body(request).isEmpty)
        }
        let copy = try await api().copy(item, token: token)
        XCTAssertEqual(copy.pack.id, "course-copy")
        XCTAssertEqual(copy.pack.version, 1)
        XCTAssertNotNil(copy.remixDraftId)
        for key in ["pack", "remixDraftId", "tags", "hasCover"] {
            var bad = valid
            switch key {
            case "pack": bad[key] = packJSON()
            case "remixDraftId": bad[key] = NSNull()
            case "tags": bad[key] = ["임의태그"]
            default: bad[key] = true
            }
            stub("POST", "courses/public/coast/versions/2/copy", status: 201, json: bad)
            do { _ = try await api().copy(item, token: token); XCTFail("Invalid copy receipt accepted") }
            catch IPhoneSessionError.invalidResponse { }
        }
    }

    func testCopyPermissionDenialHasOperationMessageAndKeepsAuthenticationErrorsDistinct() async throws {
        let item = try item()
        stub("POST", "courses/public/coast/versions/2/copy", status: 403,
             json: ["detail": "Source course re-use permission required"])
        do { _ = try await api().copy(item, token: token); XCTFail("Copy permission denial accepted") }
        catch CourseDiscoveryCopyError.permissionRequired {
            let message = try XCTUnwrap(CourseDiscoveryCopyError.permissionRequired.errorDescription)
            XCTAssertTrue(message.contains("재사용 허용"))
            XCTAssertTrue(message.contains("내 경로 만들기 권한"))
            XCTAssertFalse(message.contains("다시 로그인"))
        }
        stub("POST", "courses/public/coast/versions/2/copy", status: 401, json: ["detail": "IPHONE_SESSION_REVOKED"])
        do { _ = try await api().copy(item, token: token); XCTFail("Revoked copy session accepted") }
        catch IPhoneSessionError.invalidSession { }
        stub("GET", "courses/library", status: 403, json: ["detail": "Forbidden"])
        do { _ = try await api().library(query: "", tags: [], token: token); XCTFail("Read scope denial accepted") }
        catch IPhoneSessionError.forbidden { }
    }

    func testHTTPAccessFailureIsNotRetriedOnPublicHost() async throws {
        var count = 0
        stub("GET", "courses/library", status: 403, json: ["detail": "Forbidden"]) { _ in count += 1 }
        do { _ = try await api().library(query: "", tags: [], token: token); XCTFail("Forbidden accepted") }
        catch IPhoneSessionError.forbidden { }
        XCTAssertEqual(count, 1)
    }

    @MainActor
    func testCoverUsesOnlyAuthenticatedIPhoneJPEGPathWithoutCookies() async throws {
        let jpeg = try XCTUnwrap(UIGraphicsImageRenderer(size: CGSize(width: 1, height: 1)).image { _ in }.jpegData(compressionQuality: 1))
        var json = itemJSON(); json["hasCover"] = true
        let item: CourseDiscoveryItem = try decode(json)
        var requests = 0
        CourseDiscoveryHTTPStub.binaryHandler = { request in
            requests += 1
            XCTAssertEqual(request.httpMethod, "GET")
            XCTAssertEqual(request.url?.absoluteString, "https://ios-api-wegoh.devforest.io/v1/iphone/courses/public/coast/versions/2/cover")
            XCTAssertEqual(request.value(forHTTPHeaderField: "Accept"), "image/jpeg")
            XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer " + self.token)
            XCTAssertNil(request.value(forHTTPHeaderField: "Cookie"))
            return (200, "image/jpeg", jpeg)
        }
        let loaded = try await api().cover(item, token: token)
        XCTAssertEqual(loaded, jpeg)
        XCTAssertEqual(requests, 1)
        do { _ = try await api().cover(try self.item(), token: token); XCTFail("Requested absent cover") }
        catch CourseRequestError.invalidInput { }
        XCTAssertEqual(requests, 1)
    }

    @MainActor
    func testCoverRejectsWrongMIMEInvalidJPEGAndServerSizeBounds() async throws {
        let jpeg = try XCTUnwrap(UIGraphicsImageRenderer(size: CGSize(width: 1, height: 1)).image { _ in }.jpegData(compressionQuality: 1))
        let huge = try XCTUnwrap(UIGraphicsImageRenderer(size: CGSize(width: 961, height: 1)).image { _ in }.jpegData(compressionQuality: 1))
        var json = itemJSON(); json["hasCover"] = true
        let item: CourseDiscoveryItem = try decode(json)
        for (mime, bytes) in [("application/json", jpeg), ("image/png", jpeg), ("image/jpeg", Data([0xFF, 0xD8, 0xFF])),
                              ("image/jpeg", Data(repeating: 0, count: 524_289)), ("image/jpeg", huge)] {
            CourseDiscoveryHTTPStub.binaryHandler = { _ in (200, mime, bytes) }
            do { _ = try await api().cover(item, token: token); XCTFail("Accepted malformed cover: " + mime) }
            catch IPhoneSessionError.invalidResponse { }
        }
    }

    func testTagInsightsCountOnlyReturnedCoursesAndKeepCreatorIdentity() throws {
        var first = itemJSON()
        first["creatorRank"] = 1
        var second = first; second["id"] = "second"; second["tags"] = ["바다", "시장"]; second["starCount"] = 9
        var third = first; third["id"] = "third"; third["creatorId"] = "team-" + String(repeating: "b", count: 40)
        third["author"] = "같은 이름"; third["tags"] = ["바다", "카페"]
        let courses: [CourseDiscoveryItem] = try [first, second, third].map(decode)
        let value = CourseTagInsights(courses: courses, selectedTags: ["바다"])
        XCTAssertEqual(value.relatedTags, [.init(tag: "카페", count: 2), .init(tag: "시장", count: 1)])
        XCTAssertEqual(value.creators.map(\.count), [2, 1])
        XCTAssertEqual(Set(value.creators.map(\.id)).count, 2)
        XCTAssertEqual(CourseDiscoverySort.stars.courses(courses).first?.id, "second")
        XCTAssertEqual(courses.first?.creatorRank, 1)
    }

    func testVisibleTagsKeepPopularityOrderBoundChipsAndRetainSelectedTag() {
        let popular = (0..<1000).map { "태그\($0)" }
        let tags = courseVisibleFilterTags(popular: popular, selected: ["태그999", "태그0"])
        XCTAssertEqual(tags, Array(popular.prefix(8)) + ["태그999"])
        XCTAssertEqual(courseVisibleFilterTags(popular: ["Cafe", "바다"], selected: ["CAFE"]), ["Cafe", "바다"])
    }

    func testFullUnicodeLibraryFitsCatalogueContractBeyondOrdinaryJSONLimit() async throws {
        let items = (0..<1000).map { index in
            var item = itemJSON()
            item["id"] = "course-\(index)"
            item["description"] = String(repeating: "가", count: 500)
            return item
        }
        let saved = items.map { item in var value = item; value["starred"] = true; return value }
        var library = libraryJSON(); library["public"] = items; library["saved"] = saved
        let size = try JSONSerialization.data(withJSONObject: library).count
        XCTAssertGreaterThan(size, 2_097_152)
        XCTAssertLessThan(size, 16_777_216)
        stub("GET", "courses/library", json: library)
        let value = try await api().library(query: "", tags: [], token: token)
        XCTAssertEqual(value.recommended.count, 1000)
        XCTAssertEqual(value.saved.count, 1000)
    }

    func testLargeCatalogueAllowanceDoesNotExpandOtherJSONEndpoints() async throws {
        let profile: [String: Any] = ["id": creatorID, "name": "창작자", "courseCount": 0, "starCount": 0,
                                     "followerCount": 0, "following": false, "followId": NSNull()]
        stub("GET", "courses/creators/" + creatorID,
             json: ["creator": profile, "courses": [], "padding": String(repeating: "x", count: 2_097_153)])
        do { _ = try await api().creator(creatorID, token: token); XCTFail("Expanded ordinary JSON limit") }
        catch IPhoneSessionError.invalidResponse { }
    }

    func testCoverAccessFailureDoesNotRetryOrUsePublicWebHost() async throws {
        var json = itemJSON(); json["hasCover"] = true
        let item: CourseDiscoveryItem = try decode(json)
        for (status, expected) in [(401, IPhoneSessionError.invalidSession), (403, IPhoneSessionError.forbidden)] {
            var count = 0
            CourseDiscoveryHTTPStub.binaryHandler = { request in
                count += 1
                XCTAssertEqual(request.url?.host, "ios-api-wegoh.devforest.io")
                return (status, "application/json", Data("{\"detail\":\"IPHONE_SESSION_REQUIRED\"}".utf8))
            }
            do { _ = try await api().cover(item, token: token); XCTFail("Accepted access failure") }
            catch { XCTAssertEqual(error as? IPhoneSessionError, expected) }
            XCTAssertEqual(count, 1)
        }
        CourseDiscoveryHTTPStub.binaryHandler = { _ in (404, "application/json", Data("{}".utf8)) }
        do { _ = try await api().cover(item, token: token); XCTFail("Accepted absent cover") }
        catch IPhoneResourceError.missing { }
    }
}

extension CourseDiscoveryLiveTests {
    @MainActor
    private func storeHarness(courseAPI: (any IPhoneCourseServing)? = nil) async throws -> (CourseDiscoveryStore, DiscoveryTestAPI, SessionManager) {
        let account = AccountSession(accountID: "team-" + String(repeating: "c", count: 40),
            displayName: "실제 세션 시험", expiresAt: .now.addingTimeInterval(3600), scopes: ["account:read", "courses:read", "courses:write"])
        let session = SessionManager(api: DiscoveryTestAuth(account: account), credentials: DiscoveryTestCredentials())
        await session.restore()
        let api = DiscoveryTestAPI(library: try decode(libraryJSON()), detail: try decode(detailJSON()))
        return (CourseDiscoveryStore(session: session, api: api, courseAPI: courseAPI), api, session)
    }

    @MainActor
    func testCardMapUsesListPlacesWithoutReadingDetail() async throws {
        let (store, api, _) = try await storeHarness()
        let course = try item()
        XCTAssertTrue(course.isValid)
        XCTAssertEqual(course.stops, [CourseCardStop(id: "stop-join", name: "합류 카페", lat: 37.5, lng: 127)])
        XCTAssertEqual(course.stops, api.detailValue.pack.stops.map(CourseCardStop.init))
        await store.load()
        XCTAssertEqual(api.detailReads, 0)
        XCTAssertNil(store.detail)
    }

    func testListItemMustCarryEveryCardPlace() throws {
        var missing = itemJSON()
        missing.removeValue(forKey: "stops")
        XCTAssertThrowsError(try decode(missing) as CourseDiscoveryItem)
        var short = itemJSON()
        short["stops"] = [Any]()
        XCTAssertFalse((try decode(short) as CourseDiscoveryItem).isValid)
        var duplicated = itemJSON()
        duplicated["stopCount"] = 2
        duplicated["stops"] = [["id": "stop-join", "name": "합류 카페", "lat": 37.5, "lng": 127],
                               ["id": "stop-join", "name": "합류 카페", "lat": 37.5, "lng": 127]]
        XCTAssertFalse((try decode(duplicated) as CourseDiscoveryItem).isValid)
    }

    @MainActor
    func testCardRoadPreviewReusesOnlyMatchingCourseVersionAndOrderedCoordinatesUntilLogout() async throws {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [CourseDiscoveryHTTPStub.self]
        let (store, _, session) = try await storeHarness(courseAPI: IPhoneCourseAPI(configuration: config))
        let original = try item()
        var nextJSON = itemJSON()
        nextJSON["version"] = original.version + 1
        let next: CourseDiscoveryItem = try decode(nextJSON)
        let a = CourseCoordinate(lat: 37.8068, lng: 128.9087)
        let b = CourseCoordinate(lat: 37.7725, lng: 128.9478)
        let bend = CourseCoordinate(lat: 37.79, lng: 128.92)
        var routeCalls = 0
        CourseDiscoveryHTTPStub.handler = { request in
            XCTAssertEqual(request.url?.path, "/v1/iphone/routes/preview")
            routeCalls += 1
            let body = try self.body(request)
            let coordinates = try XCTUnwrap(body["points"] as? [[String: Double]])
            let path = [coordinates[0], ["lat": bend.lat, "lng": bend.lng], coordinates[1]]
            return (200, ["distanceMeters": 6100, "durationSeconds": 780,
                          "path": try path.map { [try XCTUnwrap($0["lat"]), try XCTUnwrap($0["lng"])] }])
        }
        let first = try await store.previewRoute(for: original, points: [a, b])
        let second = try await store.previewRoute(for: original, points: [a, b])
        XCTAssertEqual(first.path, [a, bend, b])
        XCTAssertEqual(second.path, first.path)
        XCTAssertEqual(routeCalls, 1)
        let reversed = try await store.previewRoute(for: original, points: [b, a])
        XCTAssertEqual(reversed.path, [b, bend, a])
        _ = try await store.previewRoute(for: next, points: [a, b])
        XCTAssertEqual(routeCalls, 3)
        await session.signOut()
        do {
            _ = try await store.previewRoute(for: next, points: [a, b])
            XCTFail("A signed-out user must not receive a cached road path")
        } catch is CancellationError { }
        XCTAssertEqual(routeCalls, 3)
    }

    @MainActor
    func testSameDetailStaysVisibleDuringReloadAndOfflineFailure() async throws {
        let (store, api, _) = try await storeHarness()
        let item = try item()
        await store.loadDetail(item)
        let original = try XCTUnwrap(store.detail)
        api.holdDetail = true
        let reload = Task { await store.loadDetail(item) }
        while api.pendingDetail == nil { await Task.yield() }
        XCTAssertTrue(store.detailLoading)
        XCTAssertEqual(store.detail, original)
        api.pendingDetail?.resume(throwing: URLError(.notConnectedToInternet))
        api.pendingDetail = nil
        await reload.value
        XCTAssertEqual(store.detail, original)
        XCTAssertNotNil(store.errorMessage)
        XCTAssertFalse(store.detailLoading)
        api.holdDetail = false
        api.detailFailure = IPhoneSessionError.unavailable
        await store.loadDetail(item)
        XCTAssertEqual(store.detail, original)
    }

    @MainActor
    func testDifferentDetailClearsImmediatelyAndUnavailableResourcesNeverKeepOldData() async throws {
        let (store, api, _) = try await storeHarness()
        await store.loadDetail(try item())
        var changed = itemJSON(); changed["version"] = 3
        let other: CourseDiscoveryItem = try decode(changed)
        api.holdDetail = true
        let reload = Task { await store.loadDetail(other) }
        while api.pendingDetail == nil { await Task.yield() }
        XCTAssertNil(store.detail)
        api.pendingDetail?.resume(throwing: URLError(.timedOut))
        api.pendingDetail = nil
        await reload.value
        XCTAssertNil(store.detail)
        for failure in [IPhoneResourceError.missing as Error, IPhoneSessionError.forbidden,
                        IPhoneSessionError.invalidResponse, IPhoneResourceError.unavailable] {
            let (isolated, fixture, _) = try await storeHarness()
            await isolated.loadDetail(try item())
            fixture.detailFailure = failure
            await isolated.loadDetail(try item())
            XCTAssertNil(isolated.detail)
        }
    }

    @MainActor
    func testCreatorReloadRetainsOnlySameIdentityOnTransportAndClearsPrivacyFailure() async throws {
        let (store, api, session) = try await storeHarness()
        let profile: [String: Any] = ["id": creatorID, "name": "창작자", "courseCount": 1, "starCount": 4,
                                      "followerCount": 2, "following": false, "followId": NSNull()]
        api.creatorValue = try decode(["creator": profile, "courses": [itemJSON()]])
        await store.loadCreator(id: creatorID)
        let original = try XCTUnwrap(store.creator)
        api.holdCreator = true
        let reload = Task { await store.loadCreator(id: creatorID) }
        while api.pendingCreator == nil { await Task.yield() }
        XCTAssertTrue(store.creatorLoading)
        XCTAssertEqual(store.creator, original)
        api.pendingCreator?.resume(throwing: URLError(.networkConnectionLost))
        api.pendingCreator = nil
        await reload.value
        XCTAssertEqual(store.creator, original)
        let other = Task { await store.loadCreator(id: "team-" + String(repeating: "b", count: 40)) }
        while api.pendingCreator == nil { await Task.yield() }
        XCTAssertNil(store.creator)
        api.pendingCreator?.resume(throwing: URLError(.timedOut))
        api.pendingCreator = nil
        await other.value
        XCTAssertNil(store.creator)
        api.holdCreator = false
        await store.loadCreator(id: creatorID)
        api.creatorFailure = IPhoneSessionError.forbidden
        await store.loadCreator(id: creatorID)
        XCTAssertNil(store.creator)
        XCTAssertNil(store.detail)
        XCTAssertEqual(session.phase, .signedIn)
    }

    @MainActor
    func testCoverArrivingAfterLogoutIsDiscardedWithProtectedLibrary() async throws {
        let (store, api, session) = try await storeHarness()
        await store.load()
        var json = itemJSON(); json["hasCover"] = true
        let item: CourseDiscoveryItem = try decode(json)
        let pending = Task { try await store.cover(item) }
        while api.pendingCover == nil { await Task.yield() }
        await session.signOut()
        api.pendingCover?.resume(returning: Data([1, 2, 3]))
        api.pendingCover = nil
        do { _ = try await pending.value; XCTFail("Returned old account cover") }
        catch is CancellationError { }
        XCTAssertNil(store.library)
        XCTAssertTrue(store.needsRefresh)
    }

    @MainActor
    func testStoreDiscardsSupersededReadAndLogoutResponse() async throws {
        let (store, api, session) = try await storeHarness()
        api.holdRead = true
        let old = Task { await store.load(query: "이전", tags: ["바다"]) }
        while api.pendingReads.count < 1 { await Task.yield() }
        let newer = Task { await store.load(query: "최신", tags: ["카페"]) }
        while api.pendingReads.count < 2 { await Task.yield() }
        var json = libraryJSON(); var newItem = itemJSON(); newItem["title"] = "최신 결과"; json["public"] = [newItem]
        let latest: CourseDiscoveryLibrary = try decode(json)
        api.pendingReads[1].resume(returning: latest)
        await newer.value
        api.pendingReads[0].resume(returning: api.value)
        await old.value
        XCTAssertEqual(store.library?.recommended.first?.title, "최신 결과")
        XCTAssertFalse(store.loading)
        let afterLogout = Task { await store.load() }
        while api.pendingReads.count < 3 { await Task.yield() }
        await session.signOut()
        api.pendingReads[2].resume(returning: latest)
        await afterLogout.value
        XCTAssertNil(store.library)
        XCTAssertNil(store.detail)
        XCTAssertTrue(store.needsRefresh)
    }

    @MainActor
    func testSavedWriteRefetchFailureBlocksResubmissionAndRefreshPreservesFilter() async throws {
        let (store, api, _) = try await storeHarness()
        await store.load(query: "해안", tags: ["바다", "카페"])
        let original = try XCTUnwrap(store.library)
        api.readFailure = IPhoneSessionError.unavailable
        try await store.setStarred(try item(), true)
        XCTAssertEqual(api.writeCount, 1)
        XCTAssertEqual(api.readCount, 2)
        XCTAssertEqual(store.library, original)
        XCTAssertTrue(store.needsRefresh)
        do { try await store.markRead(eventID: "123"); XCTFail("Saved mutation resubmitted") }
        catch { XCTAssertEqual(error as? TripPreparationError, .refreshRequired) }
        XCTAssertEqual(api.writeCount, 1)
        api.readFailure = nil
        await store.refresh()
        XCTAssertEqual(api.lastQuery, "해안")
        XCTAssertEqual(api.lastTags, ["바다", "카페"])
        XCTAssertFalse(store.needsRefresh)
        XCTAssertEqual(api.writeCount, 1)
    }

    @MainActor
    func testFailedMutationRetainsDataWithoutRetryAndForbiddenClearsProtectedState() async throws {
        let (store, api, _) = try await storeHarness()
        await store.load()
        let original = try XCTUnwrap(store.library)
        api.writeFailure = IPhoneResourceError.conflict
        do { try await store.followCreator(try item()); XCTFail("Conflict accepted") }
        catch IPhoneResourceError.conflict { }
        XCTAssertEqual(store.library, original)
        XCTAssertEqual(api.writeCount, 1)
        XCTAssertEqual(api.readCount, 1)
        api.writeFailure = IPhoneSessionError.forbidden
        do { try await store.followCreator(try item()); XCTFail("Forbidden accepted") }
        catch IPhoneSessionError.forbidden { }
        XCTAssertNil(store.library)
        XCTAssertNil(store.detail)
        XCTAssertNil(store.creator)
        XCTAssertTrue(store.trips.isEmpty)
    }

    @MainActor
    func testStoreRejectsConcurrentWriteAndDropsLogoutDuringWrite() async throws {
        let (store, api, session) = try await storeHarness()
        await store.load()
        api.holdWrite = true
        let item = try item()
        let write = Task { try await store.setStarred(item, true) }
        while api.pendingWrite == nil { await Task.yield() }
        XCTAssertTrue(store.busy)
        do { try await store.markRead(eventID: "123"); XCTFail("Concurrent write accepted") }
        catch { XCTAssertEqual(error as? TripPreparationError, .busy) }
        await session.signOut()
        api.pendingWrite?.resume()
        api.pendingWrite = nil
        do { try await write.value; XCTFail("Logout write result retained") }
        catch is CancellationError { }
        XCTAssertEqual(api.writeCount, 1)
        XCTAssertEqual(api.readCount, 1)
        XCTAssertNil(store.library)
        XCTAssertFalse(store.busy)
    }

    @MainActor
    func testCopyPermissionDenialKeepsLoadedLibrary() async throws {
        let (store, api, session) = try await storeHarness()
        await store.load()
        let original = try XCTUnwrap(store.library)
        api.copyFailure = CourseDiscoveryCopyError.permissionRequired
        do { _ = try await store.copy(try item()); XCTFail("Copy permission denial accepted") }
        catch CourseDiscoveryCopyError.permissionRequired { }
        XCTAssertEqual(store.library, original)
        XCTAssertEqual(session.phase, .signedIn)
        XCTAssertFalse(store.needsRefresh)
        XCTAssertTrue(store.errorMessage?.contains("재사용 허용") == true)
    }

    func testTagsOnlyEditRequiresConsentAndValidNormalizedTags() throws {
        let value: CourseDetail = try decode(["pack": packJSON(), "remixDraftId": NSNull(), "tags": ["바다"], "hasCover": false])
        var draft = CourseDraft(detail: value)
        XCTAssertFalse(draft.hasChanges)
        draft.tags = ["바다", "카페"]
        XCTAssertTrue(draft.hasChanges)
        XCTAssertFalse(draft.canSave)
        draft.rightsConfirmed = true
        XCTAssertTrue(draft.canSave)
        draft.tags = Array(0...8).map { "태그\($0)" }
        XCTAssertFalse(draft.canSave)
        draft.tags = [String(repeating: "가", count: 25)]
        XCTAssertFalse(draft.canSave)
        draft.tags = ["Cafe", "CAFE"]
        XCTAssertFalse(draft.canSave)
        XCTAssertEqual(normalizedDiscoveryTag(" #가 "), "가")
        XCTAssertEqual(normalizedDiscoveryTag("Ⅷ코스"), "Ⅷ코스")
        XCTAssertNil(normalizedDiscoveryTag("_바다"))
    }

    func testCopyDraftRetainsServerIdentitySourceAndTagsWithoutConsent() throws {
        let value: CourseDetail = try decode(["pack": packJSON(id: "course-server-copy", version: 1),
            "remixDraftId": String(repeating: "d", count: 32), "tags": ["바다"], "hasCover": true])
        let draft = CourseDraft(copy: value, author: "현재 계정")
        XCTAssertEqual(draft.pack.id, "course-server-copy")
        XCTAssertEqual(draft.pack.version, 1)
        XCTAssertEqual(draft.remixDraftId, value.remixDraftId)
        XCTAssertEqual(draft.tags, ["바다"])
        XCTAssertNil(draft.original)
        XCTAssertNil(draft.copyCoverFromVersion)
        XCTAssertFalse(draft.rightsConfirmed)
        XCTAssertFalse(draft.canSave)
    }
}

@MainActor
private final class DiscoveryTestAPI: CourseDiscoveryServing, CourseDiscoveryCoverServing {
    var value: CourseDiscoveryLibrary
    var detailValue: CourseDiscoveryDetail
    var readCount = 0
    var writeCount = 0
    var lastQuery = ""
    var lastTags: [String] = []
    var holdRead = false
    var holdWrite = false
    var readFailure: Error?
    var writeFailure: Error?
    var copyFailure: Error?
    var pendingReads: [CheckedContinuation<CourseDiscoveryLibrary, Error>] = []
    var pendingWrite: CheckedContinuation<Void, Never>?
    var pendingCover: CheckedContinuation<Data, Error>?
    var holdDetail = false
    var detailReads = 0
    var holdCreator = false
    var detailFailure: Error?
    var creatorFailure: Error?
    var creatorValue: CourseDiscoveryPublicCreator?
    var pendingDetail: CheckedContinuation<CourseDiscoveryDetail, Error>?
    var pendingCreator: CheckedContinuation<CourseDiscoveryPublicCreator, Error>?
    init(library: CourseDiscoveryLibrary, detail: CourseDiscoveryDetail) { value = library; detailValue = detail }
    func library(query: String, tags: [String], token: String) async throws -> CourseDiscoveryLibrary {
        readCount += 1; lastQuery = query; lastTags = tags
        if let readFailure { throw readFailure }
        if holdRead { return try await withCheckedThrowingContinuation { pendingReads.append($0) } }
        return value
    }
    private func write() async throws {
        writeCount += 1
        if let writeFailure { throw writeFailure }
        if holdWrite { await withCheckedContinuation { pendingWrite = $0 } }
    }
    func detail(_ item: CourseDiscoveryItem, token: String) async throws -> CourseDiscoveryDetail {
        detailReads += 1
        if let detailFailure { throw detailFailure }
        if holdDetail { return try await withCheckedThrowingContinuation { pendingDetail = $0 } }
        return detailValue
    }
    func creator(_ creatorID: String, token: String) async throws -> CourseDiscoveryPublicCreator {
        if let creatorFailure { throw creatorFailure }
        if holdCreator { return try await withCheckedThrowingContinuation { pendingCreator = $0 } }
        guard let creatorValue else { throw CourseRequestError.missing }
        return creatorValue
    }
    func cover(_ item: CourseDiscoveryItem, token: String) async throws -> Data {
        try await withCheckedThrowingContinuation { pendingCover = $0 }
    }
    func setStarred(_ item: CourseDiscoveryItem, starred: Bool, token: String) async throws { try await write() }
    func followCreator(_ item: CourseDiscoveryItem, token: String) async throws { try await write() }
    func unfollowCreator(_ followID: String, token: String) async throws { try await write() }
    func setTagFollowed(_ tag: String, followed: Bool, token: String) async throws { try await write() }
    func markRead(_ eventID: String, token: String) async throws { try await write() }
    func notInterested(_ item: CourseDiscoveryItem, token: String) async throws { try await write() }
    func report(_ item: CourseDiscoveryItem, reason: String, token: String) async throws { try await write() }
    func copy(_ item: CourseDiscoveryItem, token: String) async throws -> CourseDetail {
        if let copyFailure { throw copyFailure }
        throw CourseRequestError.unavailable
    }
}

private final class DiscoveryTestAuth: IPhoneSessionServing {
    let account: AccountSession
    init(account: AccountSession) { self.account = account }
    func restore(token: String) async throws -> AccountSession { account }
    func logout(token: String) async throws { }
    func beginLogin() async throws -> IPhoneLoginAttempt { throw IPhoneSessionError.unavailable }
    func exchange(_ attempt: IPhoneLoginAttempt, callbackURL: URL) async throws -> IPhoneSessionReceipt { throw IPhoneSessionError.unavailable }
    func cancel(_ attempt: IPhoneLoginAttempt) async throws { }
}

@MainActor
private final class DiscoveryTestCredentials: IPhoneCredentialStoring {
    var value: StoredIPhoneCredential? = .init(token: String(repeating: "L", count: 43), logoutPending: false)
    func load() throws -> StoredIPhoneCredential? { value }
    func saveToken(_ token: String) throws { value = .init(token: token, logoutPending: false) }
    func markLogoutPending() throws { value = value.map { .init(token: $0.token, logoutPending: true) } }
    func clearToken() throws { value = nil }
}
