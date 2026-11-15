import Foundation
import XCTest
@testable import WegoH

private final class TripHTTPStub: URLProtocol {
    static var respond: ((URLRequest) throws -> (Int, Data))?
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func stopLoading() { }
    override func startLoading() {
        do {
            let handler = try XCTUnwrap(Self.respond)
            let (status, body) = try handler(request)
            let response = HTTPURLResponse(url: try XCTUnwrap(request.url), statusCode: status,
                                           httpVersion: nil, headerFields: ["Content-Type": "application/json"])!
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: body)
            client?.urlProtocolDidFinishLoading(self)
        } catch {
            client?.urlProtocol(self, didFailWithError: error)
        }
    }
}

final class TripAPITests: XCTestCase {
    private let trip = String(repeating: "a", count: 32)
    private let car = String(repeating: "b", count: 32)
    private let place = String(repeating: "c", count: 32)
    private let token = String(repeating: "T", count: 43)
    private let owner = "team-" + String(repeating: "1", count: 40)
    private let rider = "team-" + String(repeating: "2", count: 40)
    private let other = "team-" + String(repeating: "3", count: 40)

    override func tearDown() {
        TripHTTPStub.respond = nil
        super.tearDown()
    }

    private func api() -> IPhoneTripAPI {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [TripHTTPStub.self]
        return IPhoneTripAPI(configuration: config)
    }

    private func mock(_ method: String, _ path: String, status: Int = 200, json: [String: Any],
                      check: ((URLRequest) throws -> Void)? = nil) {
        let bearer = "Bearer " + token
        TripHTTPStub.respond = { request in
            XCTAssertEqual(request.httpMethod, method)
            XCTAssertEqual(request.url?.scheme, "https")
            XCTAssertEqual(request.url?.host, "ios-api-wegoh.devforest.io")
            XCTAssertEqual(request.url?.path, "/v1/iphone/" + path)
            XCTAssertNil(request.url?.query)
            XCTAssertTrue(request.value(forHTTPHeaderField: "Authorization") == bearer)
            XCTAssertNil(request.value(forHTTPHeaderField: "Cookie"))
            try check?(request)
            return (status, try JSONSerialization.data(withJSONObject: json))
        }
    }

    private func requestBody(_ request: URLRequest) throws -> [String: Any] {
        XCTAssertEqual(request.value(forHTTPHeaderField: "Content-Type"), "application/json")
        var data = request.httpBody ?? Data()
        if data.isEmpty {
            let stream = try XCTUnwrap(request.httpBodyStream)
            stream.open()
            defer { stream.close() }
            var buffer = [UInt8](repeating: 0, count: 1024)
            while true {
                let count = stream.read(&buffer, maxLength: buffer.count)
                if count < 0 { throw stream.streamError ?? URLError(.cannotDecodeRawData) }
                if count == 0 { break }
                data.append(contentsOf: buffer.prefix(count))
            }
        }
        return try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
    }

    private func detailJSON(id: String? = nil, seats: Int = 1) -> [String: Any] {
        let otherCar = String(repeating: "d", count: 32)
        let members: [[String: Any]] = [
            ["id": owner, "name": "방장", "state": "accepted", "isOwner": true, "isMe": false, "hasVehicle": true, "carId": car, "readiness": "ready"],
            ["id": rider, "name": "동승자", "state": "accepted", "isOwner": false, "isMe": true, "hasVehicle": false, "carId": car, "readiness": "needsPlaces"],
            ["id": other, "name": "두 번째 운전자", "state": "accepted", "isOwner": false, "isMe": false, "hasVehicle": true, "carId": otherCar, "readiness": "ready"]
        ]
        let fullStops: [[String: Any]] = [
            ["kind": "pickup", "name": "서울역", "id": place, "lat": 37.55, "lng": 126.97, "addedBy": rider,
             "createdAt": "2026-11-13T02:01:00+00:00", "selectedBy": [rider]],
            ["kind": "signal", "name": "휴게소", "id": String(repeating: "e", count: 32), "lat": 37.42, "lng": 127.1]
        ]
        let cars: [[String: Any]] = [
            ["id": car, "name": "첫 차", "seats": seats, "driverId": owner, "driverName": "방장",
             "isMine": false, "iRide": true, "driverVehicleReady": true, "places": fullStops,
             "passengers": [["id": rider, "name": "동승자", "isMe": true]]],
            ["id": otherCar, "name": "둘째 차", "seats": 4, "driverId": other, "driverName": "두 번째 운전자",
             "isMine": false, "iRide": false, "driverVehicleReady": true, "passengers": [],
             "places": [["name": "다른 차의 장소", "selectedBy": 1], ["kind": "signal", "name": "정차 요청", "selectedBy": 0]]]
        ]
        return ["id": id ?? trip, "title": "준비 여행", "description": "", "state": "planned", "revision": 2,
                "isOwner": false, "ownerId": owner, "myPermissions": ["edit": false, "invite": false],
                "members": members, "unassigned": [], "cars": cars, "courses": [], "locationConsent": false]
    }

    func testDetailReadsCurrentCarAndBothPlaceProjections() async throws {
        mock("GET", "trips/" + trip, json: detailJSON())
        let value = try await api().detail(trip, token: token)
        let mine = try XCTUnwrap(value.myCar)
        XCTAssertEqual(mine.id, car)
        XCTAssertTrue(mine.iRide)
        XCTAssertFalse(mine.isMine)
        XCTAssertEqual(value.me?.id, rider)
        XCTAssertEqual(mine.passengers.map(\.id), [rider])
        XCTAssertEqual(mine.places.first?.id, place)
        XCTAssertEqual(mine.places.first?.kind, .pickup)
        XCTAssertEqual(mine.places.first?.selectedBy, [rider])
        XCTAssertEqual(mine.places.last?.kind, .signal)
        let hidden = try XCTUnwrap(value.cars.last?.places.first)
        XCTAssertEqual(hidden.name, "다른 차의 장소")
        XCTAssertEqual(hidden.selectionCount, 1)
        XCTAssertNil(hidden.id)
        XCTAssertNil(hidden.kind)
        XCTAssertNil(hidden.lat)
        XCTAssertNil(hidden.selectedBy)
    }

    func testRoleMembersUseAccountIDsWhenNamesMatch() async throws {
        var json = detailJSON()
        var members = try XCTUnwrap(json["members"] as? [[String: Any]])
        for i in members.indices {
            members[i]["name"] = "같은 이름"
            members[i]["role"] = ["dj", "food", "rest"][i]
        }
        json["members"] = members
        mock("GET", "trips/" + trip, json: json)
        let detail = try await api().detail(trip, token: token)
        XCTAssertEqual(detail.roleMembers(in: try XCTUnwrap(detail.cars.first)).map(\.id), [owner, rider])
        XCTAssertEqual(detail.roleMembers(in: try XCTUnwrap(detail.cars.last)).map(\.id), [other])
    }

    func testRidersListDriverFirstWithMeAndRolesByAccountID() async throws {
        var json = detailJSON()
        var members = try XCTUnwrap(json["members"] as? [[String: Any]])
        for i in members.indices {
            members[i]["name"] = "같은 이름"
            members[i]["role"] = ["dj", "member", "rest"][i]
        }
        json["members"] = members
        mock("GET", "trips/" + trip, json: json)
        let detail = try await api().detail(trip, token: token)
        let riders = detail.riders(in: try XCTUnwrap(detail.cars.first))
        XCTAssertEqual(riders.map(\.id), [owner, rider])
        XCTAssertEqual(riders.map(\.name), ["방장", "동승자"])
        XCTAssertEqual(riders.map(\.isDriver), [true, false])
        XCTAssertEqual(riders.map(\.isMe), [false, true])
        XCTAssertEqual(riders.map(\.role), [.dj, .member])
        let empty = detail.riders(in: try XCTUnwrap(detail.cars.last))
        XCTAssertEqual(empty.map(\.id), [other])
        XCTAssertEqual(empty.first?.role, .rest)
    }

    func testDetailReadsMemberReadinessAndRejectsReadinessThatContradictsInvitation() async throws {
        mock("GET", "trips/" + trip, json: detailJSON())
        let value = try await api().detail(trip, token: token)
        XCTAssertEqual(value.members.map(\.readiness), [.ready, .needsPlaces, .ready])
        var json = detailJSON()
        var members = try XCTUnwrap(json["members"] as? [[String: Any]])
        members[2]["readiness"] = "invited"
        json["members"] = members
        mock("GET", "trips/" + trip, json: json)
        do { _ = try await api().detail(trip, token: token); XCTFail("Accepted member reported as invited") }
        catch IPhoneSessionError.invalidResponse { }
    }

    func testPreparedTripCanHaveOneMemberAndNoCars() async throws {
        let single: [String: Any] = ["id": owner, "name": "방장", "state": "accepted", "isOwner": true,
                                     "isMe": true, "hasVehicle": false, "carId": NSNull(), "readiness": "needsCar"]
        var minimal = detailJSON()
        minimal["isOwner"] = true
        minimal["myPermissions"] = ["invite": true, "edit": true]
        minimal["members"] = [single]
        minimal["cars"] = []
        minimal["unassigned"] = [["id": owner, "name": "방장"]]
        mock("GET", "trips/" + trip, json: minimal)
        let value = try await api().detail(trip, token: token)
        XCTAssertNil(value.myCar)
        XCTAssertEqual(value.unassigned.map(\.id), [owner])
        XCTAssertEqual(value.me?.id, owner)
    }

    func testStartConflictIsOwnerOnlyAndNamesAcceptedBusyMembers() async throws {
        let running = String(repeating: "9", count: 32)
        var owned = detailJSON()
        var members = try XCTUnwrap(owned["members"] as? [[String: Any]])
        members[0]["isMe"] = true
        members[1]["isMe"] = false
        owned["members"] = members
        owned["isOwner"] = true
        owned["myPermissions"] = ["invite": true, "edit": true]
        var cars = try XCTUnwrap(owned["cars"] as? [[String: Any]])
        cars[0]["isMine"] = true
        cars[0]["iRide"] = false
        cars[0]["passengers"] = [["id": rider, "name": "동승자", "isMe": false]]
        owned["cars"] = cars
        owned["startConflict"] = ["activeTrips": [["tripId": running, "title": "지난 여행", "isOwner": true]],
                                  "busyMemberIds": [other]]
        mock("GET", "trips/" + trip, json: owned)
        let value = try await api().detail(trip, token: token)
        XCTAssertEqual(value.startConflict?.activeTrips.map(\.tripId), [running])
        XCTAssertEqual(value.busyMemberNames, ["두 번째 운전자"])

        var asRider = detailJSON()
        asRider["startConflict"] = owned["startConflict"]
        var selfBusy = owned
        selfBusy["startConflict"] = ["activeTrips": [], "busyMemberIds": [owner]]
        var sameTrip = owned
        sameTrip["startConflict"] = ["activeTrips": [["tripId": trip, "title": "준비 여행", "isOwner": true]], "busyMemberIds": []]
        for invalid in [asRider, selfBusy, sameTrip] {
            mock("GET", "trips/" + trip, json: invalid)
            do {
                _ = try await api().detail(trip, token: token)
                XCTFail("Invalid start conflict was accepted")
            } catch IPhoneSessionError.invalidResponse { }
        }
    }

    func testDetailRejectsWrongTripImpossibleSeatCapacityAndPrivatePlacesOnAnotherCar() async throws {
        let api = api()
        var unrelatedCarDetail = detailJSON()
        var cars = try XCTUnwrap(unrelatedCarDetail["cars"] as? [[String: Any]])
        cars[1]["places"] = cars[0]["places"]
        unrelatedCarDetail["cars"] = cars
        for invalid in [detailJSON(id: String(repeating: "f", count: 32)), detailJSON(seats: 0),
                        detailJSON(seats: 9), unrelatedCarDetail] {
            mock("GET", "trips/" + trip, json: invalid)
            do {
                _ = try await api.detail(trip, token: token)
                XCTFail("Invalid trip detail was accepted")
            } catch IPhoneSessionError.invalidResponse { }
        }
    }

    func testCreateTrimsInputAndChecksReceipt() async throws {
        let draft = IPhoneTripDraft(title: "  강릉 여행  ", description: "  첫날\n둘째 날 ", startDate: "2028-02-29",
                                    endDate: "2028-03-30", memberIds: [rider], locationConsent: false)
        let api = api()
        mock("POST", "trips", status: 201, json: ["id": trip]) { request in
            let body = try self.requestBody(request)
            XCTAssertEqual(Set(body.keys), Set(["title", "description", "startDate", "endDate", "memberIds", "locationConsent"]))
            XCTAssertEqual(body["title"] as? String, "강릉 여행")
            XCTAssertEqual(body["description"] as? String, "첫날\n둘째 날")
            XCTAssertEqual(body["endDate"] as? String, "2028-03-30")
            XCTAssertEqual(body["memberIds"] as? [String], [self.rider])
            XCTAssertEqual(body["locationConsent"] as? Bool, true)
        }
        let id = try await api.create(draft, token: token)
        XCTAssertEqual(id, trip)
        mock("POST", "trips", status: 201, json: ["id": "../foreign"])
        do { _ = try await api.create(draft, token: token); XCTFail("Invalid receipt was accepted") }
        catch IPhoneSessionError.invalidResponse { }
    }

    func testDraftDateAndTextRulesMatchServerBoundaries() {
        var draft = IPhoneTripDraft(title: "여행")
        for date in ["2026-02-29", "2026-2-03", "2026-02-31", "0000-01-01"] {
            draft.startDate = date
            XCTAssertFalse(draft.isValid, date)
        }
        draft.startDate = "2028-02-29"
        draft.endDate = "2028-03-30"
        XCTAssertTrue(draft.isValid)
        draft.endDate = "2028-03-31"
        XCTAssertFalse(draft.isValid)
        draft.endDate = "2028-02-28"
        XCTAssertFalse(draft.isValid)
        draft.startDate = nil
        XCTAssertTrue(draft.isValid)
        draft.title = String(repeating: "가", count: 40)
        draft.description = String(repeating: "나", count: 300)
        XCTAssertTrue(draft.isValid)
        draft.description.append("가")
        XCTAssertFalse(draft.isValid)
        draft.description = ""
        draft.title = String(repeating: "e\u{301}", count: 21)
        XCTAssertFalse(draft.isValid)
        draft.title = "여행\n제목"
        XCTAssertFalse(draft.isValid)
        draft.title = "여행"
        draft.memberIds = [rider, rider]
        XCTAssertFalse(draft.isValid)
    }

    func testRideLeaveAndPlaceMutationsUseIPhoneRouteAndJSONBody() async throws {
        let api = api(), base = "trips/" + trip, places = "trips/" + trip + "/cars/" + car + "/places"
        let empty: (URLRequest) throws -> Void = { request in
            let body = try self.requestBody(request)
            XCTAssertTrue(body.isEmpty)
        }
        mock("PUT", base + "/cars/" + car + "/ride", json: ["status": "riding"], check: empty)
        try await api.ride(trip, carID: car, token: token)
        mock("DELETE", base + "/ride", json: ["status": "left"], check: empty)
        try await api.leaveCar(trip, token: token)
        mock("POST", places, status: 201, json: ["id": place]) { request in
            let body = try self.requestBody(request)
            XCTAssertEqual(Set(body.keys), Set(["kind", "name", "lat", "lng"]))
            XCTAssertEqual(body["kind"] as? String, "drop")
            XCTAssertEqual(body["name"] as? String, "강릉역")
            XCTAssertEqual(body["lat"] as? Double, 37.76)
            XCTAssertEqual(body["lng"] as? Double, 128.9)
        }
        let result = try await api.addCarPlace(trip, carID: car, kind: .drop, name: "강릉역",
                                               lat: 37.76, lng: 128.9, token: token)
        XCTAssertEqual(result, place)
        mock("DELETE", places + "/" + place, json: ["status": "deleted"], check: empty)
        try await api.removeCarPlace(trip, carID: car, placeID: place, token: token)
    }

    func testInvitationAcceptanceAlwaysSharesAndDeclineNeverShares() async throws {
        for accept in [true, false] {
            mock("POST", "trips/" + trip + "/respond", json: ["status": accept ? "accepted" : "declined"]) { request in
                let body = try self.requestBody(request)
                XCTAssertEqual(body["accept"] as? Bool, accept)
                XCTAssertEqual(body["locationConsent"] as? Bool, accept)
            }
            try await api().respond(trip, accept: accept, locationConsent: !accept, token: token)
        }
    }

    func testInvitationConflictsKeepTheirServerReasonWithoutRepeatingTheWrite() async throws {
        for code in ["TRIP_STATE_CONFLICT", "TRIP_CONTEXT_NOT_READY", "TRIP_MEMBERSHIP_INCONSISTENT"] {
            var writes = 0
            mock("POST", "trips/" + trip + "/respond", status: 409, json: ["detail": code]) { _ in writes += 1 }
            do {
                try await api().respond(trip, accept: true, locationConsent: false, token: token)
                XCTFail("Unavailable invitation accepted")
            } catch IPhoneTripRequestError.routeConflict(let actual) {
                XCTAssertEqual(actual, code)
            } catch { XCTFail("Invitation reason was discarded: \(code)") }
            XCTAssertEqual(writes, 1)
        }
    }

    func testKnownSaveConstraintsStaySpecificAndUnknownDetailStaysPrivate() async throws {
        for code in ["Vehicle owner required", "Already driving", "Seats taken", "Car is full", "Trip is full"] {
            mock("POST", "trips/" + trip + "/cars", status: 409, json: ["detail": code])
            do {
                _ = try await api().createCar(trip, name: "테스트 차", seats: 3, token: token)
                XCTFail("Save constraint ignored")
            } catch IPhoneTripRequestError.routeConflict(let actual) {
                XCTAssertEqual(actual, code)
            } catch { XCTFail("Save constraint was discarded: \(code)") }
        }
        mock("POST", "trips/" + trip + "/cars", status: 409, json: ["detail": "unknown private backend detail"])
        do {
            _ = try await api().createCar(trip, name: "테스트 차", seats: 3, token: token)
            XCTFail("Unknown failure accepted")
        } catch IPhoneTripRequestError.conflict { }
    }

    func testRemotePolicyWithoutReceivingVehicleExplainsTheVehicleSetting() async throws {
        let car = String(repeating: "c", count: 32)
        let policy = IPhoneTripRemotePolicy(enabled: true, actions: TripRemoteGroup.climate.actionIDs.sorted(), deviceId: nil)
        for code in ["Choose a vehicle for remote control", "No vehicle ready for remote control"] {
            mock("PUT", "trips/" + trip + "/cars/" + car + "/remote-policy", status: 409, json: ["detail": code])
            do {
                try await api().setRemotePolicy(trip, carID: car, policy: policy, token: token)
                XCTFail("Remote policy saved without a receiving vehicle")
            } catch IPhoneTripRequestError.routeConflict(let actual) {
                XCTAssertEqual(actual, code)
            } catch { XCTFail("Remote policy reason was discarded: \(code)") }
        }
        XCTAssertTrue(IPhoneTripRequestError.routeConflict("Choose a vehicle for remote control").errorDescription?.contains("리모컨 받기") == true)
    }

    func testErrorsDistinguishTripFailuresFromAuthenticationFailures() async throws {
        let api = api()
        for status in [400, 404, 409, 503] {
            mock("GET", "trips", status: status, json: ["detail": "Unavailable"])
            do { _ = try await api.list(token: token); XCTFail("HTTP failure accepted") }
            catch let error as IPhoneTripRequestError {
                switch (status, error) {
                case (400, .invalidInput), (404, .missing), (409, .conflict), (503, .unavailable): break
                default: XCTFail("Unexpected trip error for HTTP \(status)")
                }
            }
        }
        for (status, code, expected) in [(401, "IPHONE_SESSION_REVOKED", IPhoneSessionError.invalidSession),
                                          (403, "IPHONE_SCOPE_DENIED", .forbidden)] {
            mock("GET", "trips", status: status, json: ["detail": code])
            do { _ = try await api.list(token: token); XCTFail("Authentication failure accepted") }
            catch let error as IPhoneSessionError { XCTAssertEqual(error, expected) }
        }
    }
    func testPreauthorizedRemotePolicyAndRoleUseExplicitIPhoneMutations() async throws {
        let api = api()
        let policy = IPhoneTripRemotePolicy(enabled: true, actions: ["hvac.temperature", "hvac.fan"], deviceId: nil)
        mock("POST", "trips/" + trip + "/cars", status: 201, json: ["id": car]) { request in
            let body = try self.requestBody(request)
            XCTAssertEqual(Set(body.keys), ["name", "seats", "remotePolicy"])
            let saved = try XCTUnwrap(body["remotePolicy"] as? [String: Any])
            XCTAssertEqual(saved["enabled"] as? Bool, true)
            XCTAssertEqual(saved["actions"] as? [String], policy.actions)
            XCTAssertNil(saved["deviceId"])
        }
        _ = try await api.createCar(trip, name: "사용자A의 차", seats: 3, remotePolicy: policy, token: token)
        mock("PUT", "trips/" + trip + "/cars/" + car + "/remote-policy", json: ["remotePolicy": ["enabled": false, "actions": [], "deviceId": NSNull()]]) { request in
            let body = try self.requestBody(request)
            XCTAssertEqual(body["enabled"] as? Bool, false)
            XCTAssertEqual(body["actions"] as? [String], [])
        }
        try await api.setRemotePolicy(trip, carID: car, policy: .off, token: token)
        mock("PUT", "trips/" + trip + "/members/" + rider + "/role", json: ["status": "updated", "revision": 3]) { request in
            let body = try self.requestBody(request)
            XCTAssertEqual(Set(body.keys), ["role", "revision"])
            XCTAssertEqual(body["role"] as? String, "food")
            XCTAssertEqual(body["revision"] as? Int, 2)
        }
        try await api.setRole(trip, accountID: rider, role: .food, revision: 2, token: token)
    }

    func testSignalCandidatesUseNineKindsAndCanonicalFacilitiesAndVoteKeepsFirstAnswer() async throws {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [TripHTTPStub.self]
        let activity = IPhoneTripActivityAPI(configuration: config)
        mock("POST", "trips/" + trip + "/signals/candidates", json: ["basis": "heading", "partial": false, "candidates": [
            ["name": "방향 기준 후보", "lat": 36.42, "lng": 126.5, "verdict": "heading", "label": "진행 방향 약 2km",
             "fromRequesterMeters": 2000, "fromLeadMeters": NSNull(), "detourSeconds": NSNull()]
        ]]) { request in
            let body = try self.requestBody(request)
            XCTAssertEqual(Set(body.keys), ["kind", "location", "requiredFacilities"])
            XCTAssertEqual(body["kind"] as? String, "ev_charge")
            XCTAssertEqual(body["requiredFacilities"] as? [String], ["evCharger", "toilet"])
            let location = try XCTUnwrap(body["location"] as? [String: Any])
            XCTAssertEqual(location["heading"] as? Double, 180)
        }
        let page = try await activity.candidates(trip, reason: .charging, facilities: [.charging, .restroom],
            location: .init(lat: 36.4, lng: 126.5, heading: 180), destination: nil, token: token)
        XCTAssertEqual(page.basis, "heading")
        XCTAssertEqual(page.candidates.map(\.verdict), ["heading"])
        XCTAssertTrue(page.candidates.allSatisfy(\.isValid))
        XCTAssertTrue(page.candidates.filter { $0.verdict == "ahead" }.isEmpty)
        XCTAssertEqual(Set(TripSignalReason.allCases.map(\.serverKind)).count, 9)
        XCTAssertEqual(Set(TripSignalFacility.allCases.map(\.serverID)), ["toilet", "nursing", "evCharger", "gasStation", "lpg", "restSpace"])
        mock("POST", "trips/" + trip + "/signals/" + place + "/vote", json: ["status": "saved", "already": true, "choice": "pass", "responderAccountId": rider]) { request in
            XCTAssertEqual(try self.requestBody(request)["choice"] as? String, "agree")
        }
        let already = try await activity.vote(trip, signalID: place, agree: true, token: token)
        XCTAssertTrue(already)
    }

    func testRemoteCommandsCarryOneExplicitActionAndDoNotClaimPhysicalExecution() async throws {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [TripHTTPStub.self]
        let activity = IPhoneTripActivityAPI(configuration: config)
        let action = IPhoneTripRemote.Action(id: "hvac.temperature", revision: 1, label: "설정 온도", argumentKind: "hvac-celsius")
        let remote = IPhoneTripRemote(deviceId: car, ownerName: "사용자A", deviceName: "사용자A의 차", grantRevision: 3, actions: [action])
        mock("POST", "trips/" + trip + "/vehicle-remotes/" + car + "/commands", status: 201,
             json: ["id": place, "stage": "queued", "physicalExecutionVerified": false]) { request in
            let body = try self.requestBody(request)
            XCTAssertEqual(Set(body.keys), ["eventId", "grantRevision", "capabilityId", "capabilityRevision", "arguments"])
            XCTAssertEqual(body["capabilityId"] as? String, "hvac.temperature")
            XCTAssertEqual(body["grantRevision"] as? Int, 3)
            let arguments = try XCTUnwrap(body["arguments"] as? [String: Any])
            XCTAssertEqual(Set(arguments.keys), ["seat", "value"])
            XCTAssertEqual(arguments["value"] as? Double, 22.5)
        }
        let receipt = try await activity.command(trip, remote: remote, action: action, seat: "ROW_2_LEFT", value: 22.5, token: token)
        XCTAssertEqual(receipt.stage, "queued")
        XCTAssertFalse(receipt.physicalExecutionVerified)
    }

}

extension TripAPITests {
    func testStartExplicitlyOptsIntoV2UsingCapturedRevision() async throws {
        mock("POST", "trips/" + trip + "/start", json: ["tripId": trip, "state": "active", "revision": 4]) { request in
            let body = try self.requestBody(request)
            XCTAssertEqual(Set(body.keys), ["revision", "routeContractVersion"])
            XCTAssertEqual(body["revision"] as? Int, 3)
            XCTAssertEqual(body["routeContractVersion"] as? Int, 2)
        }
        try await api().start(trip, revision: 3, endActiveTrip: false, token: token)
    }

    func testStartCanEndTheCurrentRunningTripFirst() async throws {
        mock("POST", "trips/" + trip + "/start", json: ["tripId": trip, "state": "active", "revision": 4]) { request in
            let body = try self.requestBody(request)
            XCTAssertEqual(Set(body.keys), ["revision", "routeContractVersion", "endActiveTrip"])
            XCTAssertEqual(body["endActiveTrip"] as? Bool, true)
        }
        try await api().start(trip, revision: 3, endActiveTrip: true, token: token)
    }

    func testMyPlacesUsesOneClosedAtomicBodyIncludingNullAndValidatesReceipt() async throws {
        let draft = IPhoneTripMyPlacesDraft(revision: 2, pickup: .new(name: "  서울역  ", lat: 37.55, lng: 126.97),
                                           drop: nil, dropAtPickup: true)
        let dropID = String(repeating: "e", count: 32)
        var receipt: [String: Any] = ["revision": 3, "routeRevision": 1, "pickupPlaceId": place,
                                     "dropPlaceId": dropID, "dropAtPickup": true, "status": "updated"]
        mock("PUT", "trips/" + trip + "/cars/" + car + "/my-places", json: receipt) { request in
            let body = try self.requestBody(request)
            XCTAssertEqual(Set(body.keys), ["revision", "pickup", "drop", "dropAtPickup"])
            XCTAssertTrue(body["drop"] is NSNull)
            let pickup = try XCTUnwrap(body["pickup"] as? [String: Any])
            XCTAssertEqual(Set(pickup.keys), ["name", "lat", "lng"])
            XCTAssertEqual(pickup["name"] as? String, "서울역")
            XCTAssertEqual(body["revision"] as? Int, 2)
        }
        try await api().saveMyPlaces(trip, carID: car, draft: draft, token: token)
        for key in ["pickupPlaceId", "dropPlaceId"] {
            var missing = receipt; missing.removeValue(forKey: key)
            mock("PUT", "trips/" + trip + "/cars/" + car + "/my-places", json: missing)
            do { try await api().saveMyPlaces(trip, carID: car, draft: draft, token: token); XCTFail("Missing receipt ID accepted") }
            catch IPhoneSessionError.invalidResponse { }
        }
        receipt["dropAtPickup"] = false
        mock("PUT", "trips/" + trip + "/cars/" + car + "/my-places", json: receipt)
        do { try await api().saveMyPlaces(trip, carID: car, draft: draft, token: token); XCTFail("Contradictory receipt accepted") }
        catch IPhoneSessionError.invalidResponse { }
        let clear = IPhoneTripMyPlacesDraft(revision: 3, pickup: nil, drop: nil, dropAtPickup: false)
        mock("PUT", "trips/" + trip + "/cars/" + car + "/my-places",
             json: ["revision": 3, "routeRevision": 1, "pickupPlaceId": NSNull(), "dropPlaceId": NSNull(), "dropAtPickup": false, "status": "unchanged"]) { request in
            let body = try self.requestBody(request)
            XCTAssertTrue(body["pickup"] is NSNull)
            XCTAssertTrue(body["drop"] is NSNull)
        }
        try await api().saveMyPlaces(trip, carID: car, draft: clear, token: token)
    }

    func testCoursePriorityBodyAndSpecificConflictsStayVisibleWithoutRetry() async throws {
        mock("PUT", "trips/" + trip + "/courses/priority", json: ["status": "updated", "revision": 3]) { request in
            let body = try self.requestBody(request)
            XCTAssertEqual(Set(body.keys), ["packIds", "revision"])
            XCTAssertEqual(body["packIds"] as? [String], ["coast", "forest"])
            XCTAssertEqual(body["revision"] as? Int, 2)
        }
        try await api().prioritizeCourses(trip, packIDs: ["coast", "forest"], revision: 2, token: token)
        for code in ["TRIP_PLACE_SELECTION_CHANGED", "TRIP_ROUTE_PLAN_LOCKED", "TRIP_SIGNAL_JOIN_PENDING", "TRIP_SIGNAL_SHARED_FINISHED"] {
            var calls = 0
            mock("PUT", "trips/" + trip + "/cars/" + car + "/my-places", status: 409, json: ["detail": code]) { _ in calls += 1 }
            do {
                try await api().saveMyPlaces(trip, carID: car,
                    draft: .init(revision: 2, pickup: .existing(place), drop: nil, dropAtPickup: false), token: token)
                XCTFail("Conflict accepted")
            } catch IPhoneTripRequestError.routeConflict(let actual) { XCTAssertEqual(actual, code) }
            XCTAssertEqual(calls, 1)
        }
    }

    func testV2OtherCarPrivateDataFailsClosedWhileNullOwnPlanStaysNull() async throws {
        var json = detailJSON()
        json["routeContractVersion"] = 2
        json["state"] = "active"
        var cars = try XCTUnwrap(json["cars"] as? [[String: Any]])
        cars[0]["routePlan"] = NSNull()
        cars[0]["routeStatus"] = ["phase": "waiting", "joinEtaSeconds": NSNull()]
        cars[1]["places"] = []
        cars[1]["routePlan"] = NSNull()
        cars[1]["routeOrder"] = NSNull()
        cars[1]["routeStatus"] = ["phase": "pickup", "joinEtaSeconds": NSNull()]
        json["cars"] = cars
        mock("GET", "trips/" + trip, json: json)
        let value = try await api().detail(trip, token: token)
        XCTAssertNil(value.myCar?.routePlan)
        XCTAssertEqual(value.myCar?.routeStatus?.phase, .waiting)
        XCTAssertEqual(value.cars.last?.routeStatus?.phase, .pickup)
        for key in ["places", "routeOrder", "routeNext", "routeRevision"] {
            var hidden = cars
            switch key {
            case "places": hidden[1][key] = [["name": "노출되면 안 됨", "selectedBy": 1]]
            case "routeOrder": hidden[1][key] = [["type": "pickup", "ref": place]]
            case "routeNext": hidden[1][key] = ["type": "pickup", "ref": place]
            default: hidden[1][key] = 1
            }
            json["cars"] = hidden
            mock("GET", "trips/" + trip, json: json)
            do { _ = try await api().detail(trip, token: token); XCTFail("Other car private field accepted: \(key)") }
            catch IPhoneSessionError.invalidResponse { }
        }
    }
}

extension TripAPITests {
    func testOwnRoutePlanRequiresCurrentCarAndResolvableReferencesEvenForOwner() async throws {
        var json = detailJSON()
        json["state"] = "active"
        json["routeContractVersion"] = 2
        json["courses"] = [["packId": "coast", "title": "해안", "version": 1, "stopCount": 1,
                             "stops": [["id": "join", "name": "합류", "lat": 37.5, "lng": 127]]]]
        let plan: [String: Any] = ["contractVersion": 2, "phase": "pickup", "segments": [
            ["segment": "pickup", "items": [["type": "pickup", "ref": place]]],
            ["segment": "shared", "items": [["type": "course", "courseId": "coast", "ref": "join"]]],
            ["segment": "drop", "items": []]],
            "joinPoint": ["courseId": "coast", "ref": "join", "name": "합류", "lat": 37.5, "lng": 127],
            "joinEtaSeconds": NSNull(), "progressRevision": 0, "next": ["type": "pickup", "ref": place],
            "joinBarrier": ["arrivedCarIds": [], "totalCarCount": 2, "released": false]]
        var cars = try XCTUnwrap(json["cars"] as? [[String: Any]])
        cars[0]["routePlan"] = plan
        cars[0]["routeStatus"] = ["phase": "pickup", "joinEtaSeconds": NSNull()]
        cars[1]["places"] = []
        cars[1]["routePlan"] = NSNull()
        cars[1]["routeStatus"] = ["phase": "waiting", "joinEtaSeconds": NSNull()]
        json["cars"] = cars
        mock("GET", "trips/" + trip, json: json)
        let valid = try await api().detail(trip, token: token)
        XCTAssertEqual(valid.myCar?.routePlan?.joinPoint.ref, "join")
        XCTAssertEqual(valid.myCar?.routePlan?.progressRevision, 0)
        var missingReference = cars
        missingReference[0]["places"] = []
        json["cars"] = missingReference
        mock("GET", "trips/" + trip, json: json)
        do { _ = try await api().detail(trip, token: token); XCTFail("Unresolvable private reference accepted") }
        catch IPhoneSessionError.invalidResponse { }
        cars[1]["routePlan"] = plan
        json["cars"] = cars
        json["isOwner"] = true
        json["ownerId"] = rider
        var members = try XCTUnwrap(json["members"] as? [[String: Any]])
        members[0]["isOwner"] = false
        members[1]["isOwner"] = true
        json["members"] = members
        mock("GET", "trips/" + trip, json: json)
        do { _ = try await api().detail(trip, token: token); XCTFail("Owner received another car plan") }
        catch IPhoneSessionError.invalidResponse { }
    }
}

extension TripAPITests {
    func testExistingPlaceSelectionUsesOnlyPlaceIDAndRejectsChangedIDOrBadRevisionReceipt() async throws {
        let draft = IPhoneTripMyPlacesDraft(revision: 2, pickup: .existing(place), drop: nil, dropAtPickup: false)
        let valid: [String: Any] = ["revision": 2, "routeRevision": 0, "pickupPlaceId": place,
                                  "dropPlaceId": NSNull(), "dropAtPickup": false, "status": "unchanged"]
        mock("PUT", "trips/" + trip + "/cars/" + car + "/my-places", json: valid) { request in
            let body = try self.requestBody(request)
            let pickup = try XCTUnwrap(body["pickup"] as? [String: Any])
            XCTAssertEqual(Set(pickup.keys), ["placeId"])
            XCTAssertEqual(pickup["placeId"] as? String, self.place)
            XCTAssertTrue(body["drop"] is NSNull)
        }
        try await api().saveMyPlaces(trip, carID: car, draft: draft, token: token)
        for (key, wrong) in [("pickupPlaceId", String(repeating: "d", count: 32) as Any),
                             ("routeRevision", -1 as Any), ("routeRevision", true as Any),
                             ("revision", Int(Int32.max) + 1 as Any), ("status", "saved" as Any)] {
            var invalid = valid
            invalid[key] = wrong
            mock("PUT", "trips/" + trip + "/cars/" + car + "/my-places", json: invalid)
            do { try await api().saveMyPlaces(trip, carID: car, draft: draft, token: token); XCTFail("Invalid receipt accepted: \(key)") }
            catch IPhoneSessionError.invalidResponse { }
        }
    }
}
