import Foundation
import XCTest
@testable import WegoH

private final class TripManagementHTTPStub: URLProtocol {
    static var respond: ((URLRequest) throws -> (Int, Data))?
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func stopLoading() { }
    override func startLoading() {
        do {
            let result = try XCTUnwrap(Self.respond)(request)
            let response = HTTPURLResponse(url: request.url!, statusCode: result.0, httpVersion: nil, headerFields: ["Content-Type": "application/json"])!
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: result.1)
            client?.urlProtocolDidFinishLoading(self)
        } catch { client?.urlProtocol(self, didFailWithError: error) }
    }
}

final class TripManagementAPITests: XCTestCase {
    private let trip = String(repeating: "a", count: 32)
    private let car = String(repeating: "b", count: 32)
    private let invitation = String(repeating: "c", count: 32)
    private let account = "team-" + String(repeating: "d", count: 40)
    private let token = String(repeating: "T", count: 43)
    override func tearDown() { TripManagementHTTPStub.respond = nil; super.tearDown() }
    private var configuration: URLSessionConfiguration {
        let value = URLSessionConfiguration.ephemeral; value.protocolClasses = [TripManagementHTTPStub.self]; return value
    }
    private func response(_ method: String, _ path: String, json: [String: Any], status: Int = 200,
                          inspect: (([String: Any]) throws -> Void)? = nil) {
        let bearer = "Bearer " + token
        TripManagementHTTPStub.respond = { request in
            XCTAssertEqual(request.httpMethod, method)
            XCTAssertEqual(request.url?.path, "/v1/iphone/trips/" + path)
            XCTAssertEqual(request.url?.host, "ios-api-wegoh.devforest.io")
            XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), bearer)
            XCTAssertNil(request.value(forHTTPHeaderField: "Cookie"))
            if let inspect { try inspect(Self.body(request)) }
            return (status, try JSONSerialization.data(withJSONObject: json))
        }
    }
    private static func body(_ request: URLRequest) throws -> [String: Any] {
        var data = request.httpBody ?? Data()
        if data.isEmpty, let stream = request.httpBodyStream {
            stream.open(); defer { stream.close() }
            var buffer = [UInt8](repeating: 0, count: 1024)
            while true {
                let n = stream.read(&buffer, maxLength: buffer.count)
                if n < 0 { throw stream.streamError ?? URLError(.cannotDecodeContentData) }
                if n == 0 { break }
                data.append(contentsOf: buffer.prefix(n))
            }
        }
        return try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
    }

    func testTripEditClearsDatesExplicitlyAndTrimsText() async throws {
        let api = IPhoneTripAPI(configuration: configuration)
        response("PATCH", trip, json: ["status": "updated"]) { body in
            XCTAssertEqual(Set(body.keys), ["title", "description", "startDate", "endDate"])
            XCTAssertEqual(body["title"] as? String, "새 이름")
            XCTAssertEqual(body["description"] as? String, "설명")
            XCTAssertTrue(body["startDate"] is NSNull)
            XCTAssertTrue(body["endDate"] is NSNull)
        }
        try await api.update(trip, draft: .init(title: " 새 이름 ", description: " 설명 "), token: token)
    }

    func testOwnerCompletionAndCancellationSendCurrentRevisionAndValidateTrip() async throws {
        let api = IPhoneTripAPI(configuration: configuration)
        response("POST", trip + "/finish", json: ["tripId": trip, "state": "completed", "revision": 9]) {
            XCTAssertEqual($0["revision"] as? Int, 8)
        }
        try await api.finish(trip, revision: 8, token: token)
        response("POST", trip + "/cancel", json: ["tripId": trip, "state": "cancelled", "revision": 9]) {
            XCTAssertEqual($0["revision"] as? Int, 8)
        }
        try await api.cancel(trip, revision: 8, token: token)
        response("POST", trip + "/finish", json: ["tripId": car, "state": "completed", "revision": 9])
        do { try await api.finish(trip, revision: 8, token: token); XCTFail("Different trip accepted") }
        catch IPhoneSessionError.invalidResponse { }
    }

    func testMemberCarCourseAndRideInviteRoutesUseExpectedReceipts() async throws {
        let api = IPhoneTripAPI(configuration: configuration)
        response("DELETE", trip + "/members/" + account, json: ["status": "removed"])
        try await api.removeMember(trip, accountID: account, token: token)
        response("PATCH", trip + "/cars/" + car, json: ["status": "updated"]) {
            XCTAssertEqual($0["name"] as? String, "차 이름"); XCTAssertEqual($0["seats"] as? Int, 3)
        }
        try await api.updateCar(trip, carID: car, name: " 차 이름 ", seats: 3, token: token)
        response("DELETE", trip + "/cars/" + car, json: ["status": "deleted"])
        try await api.deleteCar(trip, carID: car, token: token)
        response("DELETE", trip + "/courses/route-one", json: ["status": "removed"])
        try await api.removeCourse(trip, packID: "route-one", token: token)
        response("POST", trip + "/cars/" + car + "/ride-invites/" + invitation + "/respond", json: ["status": "declined"]) {
            XCTAssertEqual($0["accept"] as? Bool, false)
        }
        try await api.respondToRideInvitation(trip, carID: car, invitationID: invitation, accept: false, token: token)
    }

    func testOfflineAndRouteLockRemainErrorsAndInvalidIDsNeverDispatch() async throws {
        let api = IPhoneTripAPI(configuration: configuration)
        response("DELETE", trip + "/courses/route-one", json: ["detail": "TRIP_ROUTE_PLAN_LOCKED"], status: 409)
        do { try await api.removeCourse(trip, packID: "route-one", token: token); XCTFail("Locked mutation succeeded") }
        catch IPhoneTripRequestError.routeConflict(let code) { XCTAssertEqual(code, "TRIP_ROUTE_PLAN_LOCKED") }
        TripManagementHTTPStub.respond = { _ in throw URLError(.notConnectedToInternet) }
        do { try await api.finish(trip, revision: 8, token: token); XCTFail("Offline completion succeeded") }
        catch IPhoneTripRequestError.unavailable { }
        TripManagementHTTPStub.respond = { _ in XCTFail("Invalid ID dispatched"); return (500, Data()) }
        do { try await api.deleteCar(trip, carID: "../other", token: token); XCTFail("Invalid ID accepted") }
        catch IPhoneTripRequestError.invalidInput { }
    }

    func testLocationsRejectForeignTripDuplicatePeopleAndInvalidCoordinates() async throws {
        let api = IPhoneTripAPI(configuration: configuration)
        let point: [String: Any] = ["accountId": account, "name": "일행", "source": "vehicle", "latitude": 37.5,
            "longitude": 127, "accuracyMeters": NSNull(), "capturedAt": "2026-11-13T01:00:00Z"]
        response("GET", trip + "/locations", json: ["tripId": trip, "serverNow": "2026-11-13T01:00:01Z", "shareId": NSNull(), "locations": [point], "cars": []])
        let locations = try await api.locations(trip, token: token)
        XCTAssertEqual(locations.locations.map(\.name), ["일행"])
        response("GET", trip + "/locations", json: ["tripId": car, "serverNow": "now", "shareId": NSNull(), "locations": [], "cars": []])
        do { _ = try await api.locations(trip, token: token); XCTFail("Foreign locations accepted") }
        catch IPhoneSessionError.invalidResponse { }
        response("GET", trip + "/locations", json: ["tripId": trip, "serverNow": "now", "shareId": NSNull(), "locations": [point, point], "cars": []])
        do { _ = try await api.locations(trip, token: token); XCTFail("Duplicate locations accepted") }
        catch IPhoneSessionError.invalidResponse { }
        var invalid = point; invalid["latitude"] = 91
        response("GET", trip + "/locations", json: ["tripId": trip, "serverNow": "now", "shareId": NSNull(), "locations": [invalid], "cars": []])
        do { _ = try await api.locations(trip, token: token); XCTFail("Invalid location accepted") }
        catch IPhoneSessionError.invalidResponse { }
    }

    func testCarLocationsCarryServerAgeAndRejectDuplicatesOrInvalidCars() async throws {
        let api = IPhoneTripAPI(configuration: configuration)
        let position: [String: Any] = ["carId": car, "source": "vehicle", "latitude": 37.5, "longitude": 127.25,
            "accuracyMeters": NSNull(), "capturedAt": "2026-11-13T01:00:00.250000+00:00"]
        func page(_ cars: [[String: Any]]) -> [String: Any] {
            ["tripId": trip, "serverNow": "2026-11-13T01:00:40.250000+00:00", "shareId": NSNull(), "locations": [], "cars": cars]
        }
        response("GET", trip + "/locations", json: page([position]))
        let value = try await api.locations(trip, token: token)
        XCTAssertEqual(value.cars.map(\.carId), [car])
        XCTAssertEqual(value.age(of: value.cars[0]) ?? -1, 40, accuracy: 0.01)
        response("GET", trip + "/locations", json: page([position, position]))
        do { _ = try await api.locations(trip, token: token); XCTFail("Duplicate car accepted") }
        catch IPhoneSessionError.invalidResponse { }
        var invalid = position; invalid["source"] = "watch"
        response("GET", trip + "/locations", json: page([invalid]))
        do { _ = try await api.locations(trip, token: token); XCTFail("Unknown source accepted") }
        catch IPhoneSessionError.invalidResponse { }
    }

    func testCandidateReceiptAndResponseSourceAreRealServerValues() async throws {
        let api = IPhoneTripActivityAPI(configuration: configuration)
        response("POST", trip + "/signals", json: ["id": invitation, "status": "sent"], status: 201) {
            XCTAssertEqual($0["candidateReceipt"] as? String, "signed_candidate_receipt")
        }
        _ = try await api.send(trip, reason: .restroom, destination: .init(name: "휴게소", latitude: 37.5, longitude: 127),
            candidateReceipt: "signed_candidate_receipt", token: token)
        let raw: [String: Any] = ["id": invitation, "accountId": account, "kind": "restroom", "destination": NSNull(),
            "contextState": "valid", "inProgress": true, "resolution": "pending", "agreed": false,
            "groupResponses": [["carId": car, "carName": "차", "choice": "agree", "responderAccountId": account,
                                  "responderName": "일행", "responseSource": "iphone"]],
            "candidateDetails": ["routeName": "고속도로", "direction": "서울 방향", "fromLeadMeters": 1200, "detourSeconds": 90]]
        response("GET", trip + "/signals", json: ["signals": [raw]])
        let signals = try await api.signals(trip, token: token)
        let signal = try XCTUnwrap(signals.first)
        XCTAssertEqual(signal.groupResponses?.first?.responseSource, "iphone")
        XCTAssertEqual(signal.candidateDetails?.fromLeadMeters, 1200)
        var malformed = raw; malformed["candidateDetails"] = ["routeName": NSNull(), "direction": NSNull(), "fromLeadMeters": -1, "detourSeconds": 90]
        response("GET", trip + "/signals", json: ["signals": [malformed]])
        do { _ = try await api.signals(trip, token: token); XCTFail("Negative distance accepted") }
        catch IPhoneSessionError.invalidResponse { }
    }

    func testCompletedSharedDraftRequiresExplicitSelectionKeepsServerOrderAndRightsOff() async throws {
        let api = IPhoneTripHistoryAPI(configuration: configuration)
        let first = String(repeating: "1", count: 32), second = String(repeating: "2", count: 32)
        let optionsJSON: [String: Any] = ["title": "완료한 여행", "selectionFingerprint": String(repeating: "a", count: 64), "places": [
            ["id": first, "courseId": "shared-course", "version": 1, "name": "공유 장소 하나", "latitude": 37.5, "longitude": 127, "canReuse": true],
            ["id": second, "courseId": "shared-course", "version": 1, "name": "공유 장소 둘", "latitude": 37.6, "longitude": 127.1, "canReuse": true]
        ]]
        response("GET", trip + "/course-draft-options", json: optionsJSON)
        let options = try await api.draftOptions(trip, token: token)
        let stops = options.places.map { place in
            ["id": "shared-" + place.id, "name": place.name, "latitude": place.latitude, "longitude": place.longitude,
             "radiusMeters": 100, "action": ["type": "chime", "message": "공유 장소에 도착했어요"]] as [String: Any]
        }
        let pack: [String: Any] = ["schemaVersion": 1, "id": "new-trip-copy", "version": 1, "title": "완료한 여행",
            "author": "나", "description": "공유 코스로 만든 새 코스", "stops": stops]
        response("POST", trip + "/course-drafts", json: ["pack": pack, "tags": [], "hasCover": false, "remixDraftId": invitation], status: 201) {
            XCTAssertEqual($0["selectionIds"] as? [String], [first, second])
            XCTAssertEqual($0["selectionFingerprint"] as? String, String(repeating: "a", count: 64))
            XCTAssertEqual(Set($0.keys), ["selectionIds", "selectionFingerprint"])
        }
        let copy = try await api.createDraft(trip, options: options, selection: [second, first], token: token)
        let draft = CourseDraft(copy: copy, author: "나")
        XCTAssertFalse(draft.rightsConfirmed)
        XCTAssertEqual(draft.pack.version, 1)
        XCTAssertNil(draft.original)
        XCTAssertEqual(draft.pack.stops.map(\.name), ["공유 장소 하나", "공유 장소 둘"])
        XCTAssertEqual(draft.remixDraftId, invitation)
        TripManagementHTTPStub.respond = { _ in XCTFail("Unselected or foreign place dispatched"); return (500, Data()) }
        for selection: Set<String> in [[], [first, "personal-pickup"]] {
            do { _ = try await api.createDraft(trip, options: options, selection: selection, token: token); XCTFail("Invalid selection accepted") }
            catch IPhoneTripRequestError.invalidInput { }
        }
    }

    func testCompletedHistoryUsesActualPeriodAndExplicitSaveAndRejectsForeignSource() async throws {
        let api = IPhoneTripHistoryAPI(configuration: configuration)
        response("GET", trip + "/results", json: ["tripId": trip, "state": "completed", "readOnly": true,
            "ownPeriod": ["startedAt": "2026-11-13T01:00:00Z", "endedAt": "2026-11-13T02:00:00Z"], "history": NSNull(),
            "sourceKind": "trip", "startTimeEstimated": false, "summary": ["title": "여행", "courses": []]])
        let results = try await api.results(trip, token: token)
        XCTAssertEqual(results.ownPeriod.endedAt, "2026-11-13T02:00:00Z")
        XCTAssertNil(results.history)
        let receipt: [String: Any] = ["id": invitation, "revision": 1, "permissionRevision": 1]
        response("POST", trip + "/history", json: receipt, status: 201) { XCTAssertEqual($0["title"] as? String, "함께한 여행") }
        let first = try await api.saveHistory(trip, title: "함께한 여행", token: token)
        XCTAssertEqual(first.id, invitation)
        response("POST", trip + "/history", json: receipt)
        let repeated = try await api.saveHistory(trip, title: "중복 요청", token: token)
        XCTAssertEqual(repeated.id, first.id)
        var record: [String: Any] = ["id": invitation, "title": "함께한 여행", "ownerId": account, "own": true, "revision": 1,
            "startedAt": "2026-11-13T01:00:00Z", "endedAt": "2026-11-13T02:00:00Z", "visits": [], "source": ["tripId": trip]]
        response("GET", trip + "/history", json: record)
        let stored = try await api.history(trip, token: token)
        XCTAssertTrue(stored.visits.isEmpty)
        record["source"] = ["tripId": car]
        response("GET", trip + "/history", json: record)
        do { _ = try await api.history(trip, token: token); XCTFail("Foreign trip history accepted") }
        catch IPhoneSessionError.invalidResponse { }
    }
}
