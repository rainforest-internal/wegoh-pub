#if DEBUG
import SwiftUI

struct TripRouteUIFixture: View {
    nonisolated static var requested: Bool { ProcessInfo.processInfo.arguments.contains("-trip-route-ui-testing") }
    nonisolated static var mode: String {
        let a = ProcessInfo.processInfo.arguments
        guard let i = a.firstIndex(of: "-trip-route-ui-testing"), a.indices.contains(i + 1) else { return "pickup" }
        return a[i + 1]
    }
    static func configuration() -> URLSessionConfiguration {
        let c = URLSessionConfiguration.ephemeral
        c.protocolClasses = [TripRouteFixtureProtocol.self]
        return c
    }
    @MainActor static func sessionIfRequested() -> SessionManager? {
        guard requested else { return nil }
        return SessionManager(api: IPhoneSessionAPI(configuration: configuration()), credentials: FriendsUIFixture.Credential())
    }
    @MainActor static func makeStore(session: SessionManager) -> TripPreparationStore {
        TripPreparationStore(tripID: TripRouteFixtureProtocol.trip, session: session,
            api: IPhoneTripAPI(configuration: configuration()), activityAPI: IPhoneTripActivityAPI(configuration: configuration()))
    }
    static var observedRequestPaths: [String] { TripRouteFixtureProtocol.requestPaths }
    static var blockedDefaultRequestCount: Int { TripRouteOutboundBlockProtocol.blockedCount }
    static func resetRequestObservations() { TripRouteFixtureProtocol.resetRequestPaths() }
    nonisolated static func configureDefaultTransport(_ configuration: URLSessionConfiguration, requested: Bool = Self.requested, sentinel: URL? = nil) {
        guard requested else { return }
        if configuration.protocolClasses?.contains(where: { ObjectIdentifier($0) == ObjectIdentifier(TripRouteFixtureProtocol.self) }) == true { return }
        TripRouteOutboundBlockProtocol.configureSentinel(sentinel)
        configuration.protocolClasses = [TripRouteOutboundBlockProtocol.self]
    }
    static func resetOutboundGuardObservations() { TripRouteOutboundBlockProtocol.reset() }
    @Environment(SessionManager.self) private var session
    @State private var store: TripPreparationStore?
    @State private var places = false
    var body: some View {
        NavigationStack {
            Group {
                if let store, let detail = store.detail {
                    if TripRouteFixtureProtocol.successfulSaves > 0 { Text("샘플 저장 완료").font(WegoTokens.Typography.caption).accessibilityIdentifier("tripRouteFixtureSaved") }
                    if Self.mode.hasPrefix("full-") {
                        TripPreparationView(store: store, versusAPI: .init(configuration: Self.configuration()), placeSearchAPI: IPhoneCourseAPI(configuration: Self.configuration()))
                    } else if Self.mode == "functional-v4" {
                        VehicleFunctionalPermissionsView(vehicle: .init(id: String(repeating: "d", count: 32), name: "사용자A의 차", expiresAt: "2027-01-01T00:00:00Z", authorizationVersion: 1), api: .init(configuration: Self.configuration()))
                    } else if Self.mode == "places" || Self.mode == "places-stale" {
                        TripMyPlacesView(store: store, searchAPI: IPhoneCourseAPI(configuration: Self.configuration()))
                    } else if Self.mode.hasPrefix("versus") {
                        TripDrivingVersusView(preparation: store, api: .init(configuration: Self.configuration()))
                    } else if Self.mode == "preparation" || Self.mode == "priority" {
                        ScrollView { TripRouteOverviewView(store: store, editPlaces: { places = true }, addCourse: {}).padding(WegoTokens.Space.screen) }
                    } else {
                        ScrollView {
                            TripProgressView(detail: detail, isPreview: false, courseStops: [:], preparation: store,
                                versusAPI: .init(configuration: Self.configuration()), remotePreferences: .constant(.init()))
                                .padding(WegoTokens.Space.screen)
                        }
                    }
                } else { WegoLoadingView("구간 샘플 준비 중") }
            }.safeAreaInset(edge: .top) {
                VStack(spacing: WegoTokens.Space.xSmall) {
                    Text("구간 연동 테스트 샘플 · 실제 차량·계정에 요청하지 않아요")
                    TimelineView(.periodic(from: .now, by: 0.2)) { _ in
                        Text("기본 API 외부 차단 \(Self.blockedDefaultRequestCount)회")
                            .accessibilityIdentifier("tripRouteFixtureGuard")
                    }
                }
                .font(WegoTokens.Typography.caption).padding(WegoTokens.Space.small)
                .frame(maxWidth: .infinity).background(WegoTokens.Palette.accentSoft)
            }.sheet(isPresented: $places) { if let store { NavigationStack { TripMyPlacesView(store: store, searchAPI: IPhoneCourseAPI(configuration: Self.configuration())) } } }
        }.task(id: session.current?.accountID) {
            guard session.current != nil else { return }
            let s = Self.makeStore(session: session)
            store = s; await s.load()
        }
    }
}

private final class TripRouteFixtureProtocol: URLProtocol {
    static let trip = String(repeating: "a", count: 32), car = String(repeating: "b", count: 32), other = String(repeating: "c", count: 32)
    private static let lock = NSLock()
    private static var observedPaths: [String] = []
    static var requestPaths: [String] { lock.withLock { observedPaths } }
    static func resetRequestPaths() { lock.withLock { observedPaths = [] } }
    private static var revision = 2
    private static var joined = false
    static var successfulSaves = 0
    private static var pickup = String(repeating: "2", count: 32), drop = String(repeating: "3", count: 32)
    private static var customPickup: [String: Any]?, customDrop: [String: Any]?
    private static var order = ["coast", "boryeong"]
    private static var functionalApproval = 3
    private static var functionalRevision = 2
    private static var owner: Bool { ["priority", "full-preparation-owner"].contains(TripRouteUIFixture.mode) }
    private static var actor: String { account(owner ? 1 : TripRouteUIFixture.mode == "full-preparation-driver" ? 4 : 3) }
    private static var phase: String {
        let mode = TripRouteUIFixture.mode.replacingOccurrences(of: "full-", with: "")
        return mode == "result" ? "done" : ["pickup", "waiting", "shared", "drop", "done"].contains(mode) ? mode : "shared"
    }
    private static func account(_ n: Int) -> String { "team-" + String(repeating: String(n), count: 40) }
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func stopLoading() { }
    override func startLoading() {
        Self.lock.lock(); defer { Self.lock.unlock() }
        do {
            Self.observedPaths.append(request.url!.path)
            let (status, data) = try response()
            let r = HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: nil, headerFields: ["Content-Type": "application/json"])!
            client?.urlProtocol(self, didReceive: r, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: try JSONSerialization.data(withJSONObject: data)); client?.urlProtocolDidFinishLoading(self)
        } catch { client?.urlProtocol(self, didFailWithError: error) }
    }
    private func response() throws -> (Int, [String: Any]) {
        let path = request.url!.path
        if path.hasSuffix("/cars/" + Self.car + "/ride"), request.httpMethod == "PUT", TripRouteUIFixture.mode == "full-unassigned" {
            Self.joined = true
            Self.successfulSaves += 1
            return (200, ["status": "riding"])
        }
        if path.hasSuffix("/session") { return (200, ["user": ["id": Self.actor, "displayName": Self.owner ? "사용자A" : "사용자D"], "scopes": ["account:read", "vehicles:manage", "trips:read", "trips:manage", "maps:read"], "expiresAt": Int(Date.now.timeIntervalSince1970) + 3600]) }
        if path.hasSuffix("/functional-permissions") {
            var value = TripFunctionalV4Fixture.payload(), authorization = TripFunctionalV4Fixture.payload()["authorization"] as! [String: Any]
            authorization["deviceId"] = String(repeating: "d", count: 32)
            if request.httpMethod == "PUT" {
                let b = try body()
                guard Set(b.keys) == ["authorizationVersion", "grantId", "revision", "approvedPurposes", "functionalDisclosureVersion", "functionalDisclosureSha256"] else { return (400, ["detail": "INVALID_CONSENT"]) }
                authorization["approvedPurposes"] = b["approvedPurposes"]
                Self.functionalApproval = 4; Self.functionalRevision += 1
            }
            authorization["revision"] = Self.functionalRevision
            value["authorization"] = authorization; value["approvedDisclosureVersion"] = Self.functionalApproval
            return (200, value)
        }
        if path.hasSuffix("/places/search") { return (200, ["places": [["id": "sample-point", "name": "합정역 샘플 출구", "address": "합성 장소", "roadAddress": "", "lat": 36.4, "lng": 126.5, "source": "kakao"]]]) }
        if path.hasSuffix("/signals"), request.httpMethod == "GET" { return (200, ["signals": []]) }
        if path.hasSuffix("/driving-versus") { return (200, Self.versus()) }
        if path.hasSuffix("/my-places") {
            let b = try body()
            guard Set(b.keys) == ["revision", "pickup", "drop", "dropAtPickup"] else { return (400, ["detail": "TRIP_PLACE_SELECTION_INVALID"]) }
            if TripRouteUIFixture.mode == "places-stale" && Self.revision == 2 { Self.revision = 3; return (409, ["detail": "TRIP_PLACE_SELECTION_CHANGED"]) }
            let p = b["pickup"] as? [String: Any]
            if let id = p?["placeId"] as? String { Self.pickup = id }
            else if let p { Self.pickup = String(repeating: "5", count: 32); Self.customPickup = p }
            if b["dropAtPickup"] as? Bool == true {
                Self.drop = Self.pickup == String(repeating: "1", count: 32) ? String(repeating: "4", count: 32) : Self.pickup == String(repeating: "2", count: 32) ? String(repeating: "3", count: 32) : String(repeating: "6", count: 32)
                Self.customDrop = Self.customPickup
            } else if let d = b["drop"] as? [String: Any], let id = d["placeId"] as? String { Self.drop = id }
            Self.revision += 1
            Self.successfulSaves += 1
            return (200, ["revision": Self.revision, "routeRevision": 1, "pickupPlaceId": Self.pickup, "dropPlaceId": Self.drop, "dropAtPickup": b["dropAtPickup"] ?? false, "status": "updated"])
        }
        if path.hasSuffix("/courses/priority") {
            Self.order = try body()["packIds"] as? [String] ?? Self.order; Self.revision += 1
            Self.successfulSaves += 1
            return (200, ["status": "updated", "revision": Self.revision])
        }
        if path.hasSuffix("/trips/" + Self.trip) { return (200, Self.detail()) }
        return (404, ["detail": "FIXTURE_ROUTE_UNAVAILABLE"])
    }
    private static func places() -> [[String: Any]] {
        var rows: [[String: Any]] = [("1", "pickup", "합정역 2번 출구"), ("2", "pickup", "당산역 9번 출구"), ("3", "drop", "당산역 9번 출구"), ("4", "drop", "합정역 2번 출구")].map { n, kind, name in
            let id = String(repeating: n, count: 32)
            let chosen = id == pickup || id == drop
            return ["id": id, "kind": kind, "name": name, "lat": n == "1" || n == "4" ? 36.5 : 36.4, "lng": 126.5,
                    "addedBy": account(2), "createdAt": "2026-11-13T00:00:00Z", "selectedBy": (n == "1" || n == "4" ? [account(2)] : []) + (chosen ? [account(3)] : [])]
        }
        for (custom, kind, id) in [(customPickup, "pickup", String(repeating: "5", count: 32)), (customDrop, "drop", String(repeating: "6", count: 32))] {
            if let custom { rows.append(custom.merging(["id": id, "kind": kind, "addedBy": account(3), "createdAt": "2026-11-13T00:00:00Z", "selectedBy": [account(3)]]) { _, new in new }) }
        }
        return rows
    }
    private static var courses: [[String: Any]] {
        let values: [[String: Any]] = [
            ["packId": "coast", "title": "서해안 해안도로 코스", "version": 1, "stopCount": 3, "stops": [["id": "ganwol", "name": "간월암", "lat": 36.617, "lng": 126.339], ["id": "kkoji", "name": "꽃지해수욕장", "lat": 36.5, "lng": 126.33], ["id": "daecheon", "name": "대천해수욕장", "lat": 36.3, "lng": 126.5]]],
            ["packId": "boryeong", "title": "보령 해안도로", "version": 1, "stopCount": 1, "stops": [["id": "muchangpo", "name": "무창포", "lat": 36.2, "lng": 126.5]]]]
        if TripRouteUIFixture.mode == "full-single-shared" {
            var single = values[0]
            single["stops"] = Array((single["stops"] as! [[String: Any]]).prefix(1))
            single["stopCount"] = 1
            return [single]
        }
        return order.compactMap { id in values.first { $0["packId"] as? String == id } }.map { course in
            guard TripRouteUIFixture.mode == "full-result" else { return course }
            return course.merging(["completedCarIds": [car, other], "drivingScores": [["carId": car, "score": 90, "accelerations": 1, "brakings": 1, "measurable": true, "final": true]]]) { _, new in new }
        }
    }
    private static func detail() -> [String: Any] {
        let planned = ["preparation", "places", "places-stale", "priority", "full-preparation", "full-preparation-owner", "full-preparation-driver", "full-preparation-roles"].contains(TripRouteUIFixture.mode)
        let unassigned = TripRouteUIFixture.mode == "full-unassigned" && !joined
        let names = ["사용자A", "사용자C", "사용자D", "사용자B", "사용자E"]
        var members: [[String: Any]] = names.enumerated().map { i, name in ["id": account(i + 1), "name": name, "state": "accepted", "isMe": account(i + 1) == actor, "isOwner": i == 0, "hasVehicle": i == 0 || i == 3, "carId": i < 3 ? car : other, "readiness": "ready"] }
        if TripRouteUIFixture.mode.hasSuffix("-roles") {
            for i in members.indices { members[i]["role"] = ["dj", "food", "rest", "dj", "member"][i] }
        }
        var own: [String: Any] = ["id": car, "name": "사용자A의 차", "seats": 4, "driverId": account(1), "driverName": "사용자A", "isMine": owner, "iRide": actor == account(3), "driverVehicleReady": true,
            "passengers": [["id": account(2), "name": "사용자C", "isMe": false], ["id": account(3), "name": "사용자D", "isMe": actor == account(3)]], "places": actor == account(4) ? [] : places(), "routeRevision": 0, "routePlan": planned ? NSNull() : plan(), "routeStatus": planned ? NSNull() : ["phase": phase, "joinEtaSeconds": NSNull()]]
        let otherPhase = phase == "waiting" ? "pickup" : phase == "done" && TripRouteUIFixture.mode != "full-result" ? "drop" : phase
        let second: [String: Any] = ["id": other, "name": "사용자B의 차", "seats": 1, "driverId": account(4), "driverName": "사용자B", "isMine": actor == account(4), "iRide": false, "driverVehicleReady": true, "passengers": [["id": account(5), "name": "사용자E", "isMe": false]], "places": [], "routePlan": NSNull(), "routeStatus": planned ? NSNull() : ["phase": otherPhase, "joinEtaSeconds": NSNull()]]
        if unassigned {
            members[2]["carId"] = NSNull()
            members[2]["readiness"] = "needsCar"
            own["iRide"] = false
            own["passengers"] = [["id": account(2), "name": "사용자C", "isMe": false]]
            own["places"] = []
            own["routePlan"] = NSNull()
            own["routeRevision"] = NSNull()
        }
        return ["id": trip, "title": "서해안 드라이브", "description": "구간 연동 합성 샘플", "state": TripRouteUIFixture.mode == "full-result" ? "completed" : planned ? "planned" : "active", "routeContractVersion": planned ? 1 : 2, "revision": revision, "isOwner": owner, "ownerId": account(1), "myPermissions": ["invite": owner, "edit": owner], "members": members, "cars": [own, second], "unassigned": unassigned ? [["id": account(3), "name": "사용자D"]] : [], "courses": courses, "locationConsent": false]
    }
    private static func plan() -> [String: Any] {
        let first = courses[0], pack = first["packId"] as! String, stop = (first["stops"] as! [[String: Any]])[0]
        let shared: [[String: Any]] = courses.flatMap { course in (course["stops"] as! [[String: Any]]).map { ["type": "course", "courseId": course["packId"]!, "ref": $0["id"]!] } }
        let picks = [String(repeating: "1", count: 32), String(repeating: "2", count: 32)].map { ["type": "pickup", "ref": $0] }
        let drops = [String(repeating: "3", count: 32), String(repeating: "4", count: 32)].map { ["type": "drop", "ref": $0] }
        let next: Any = phase == "done" ? NSNull() : phase == "pickup" ? picks[0] : phase == "drop" ? drops[0] : shared[min(1, shared.count - 1)]
        return ["contractVersion": 2, "phase": phase, "segments": [["segment": "pickup", "items": picks], ["segment": "shared", "items": shared], ["segment": "drop", "items": drops]],
            "joinPoint": ["courseId": pack, "ref": stop["id"]!, "name": stop["name"]!, "lat": stop["lat"]!, "lng": stop["lng"]!], "joinEtaSeconds": NSNull(), "progressRevision": 1, "next": next,
            "joinBarrier": ["arrivedCarIds": phase == "pickup" ? [] : phase == "waiting" ? [car] : [car, other], "totalCarCount": 2, "released": ["shared", "drop", "done"].contains(phase)]]
    }
    private static func versus() -> [String: Any] {
        let mode = TripRouteUIFixture.mode, final = mode == "versus-final" || mode == "versus-tie" || mode == "full-result", hidden = mode == "versus-sharing", unavailable = mode == "versus-unavailable"
        let examples: [(String, String, Int)] = [(car, "사용자A의 차", 90), (other, "사용자B의 차", mode == "versus-tie" ? 90 : 85)]
        let cars: [[String: Any]] = examples.map { id, name, score in
            let shown: Any = final ? score as Any : NSNull()
            let reports: [[String: Any]] = courses.map { ["packId": $0["packId"]!, "version": 1, "state": hidden ? "sharing-unavailable" : unavailable ? "unavailable" : final ? "final" : "pending", "score": shown] }
            return ["carId": id, "name": name, "participating": true, "state": hidden ? "sharing-unavailable" : unavailable ? "unavailable" : final ? "ready" : "pending", "averageScore": shown, "measuredCourseCount": final ? courses.count : 0, "courses": reports]
        }
        let reason: Any = hidden ? "sharing-unavailable" : unavailable ? "insufficient-measurements" : final ? NSNull() as Any : "final-reports-pending"
        return ["kind": "safe-driving-versus", "automatic": true, "state": hidden || unavailable ? "unavailable" : final ? "final" : "pending", "reason": reason, "cars": cars, "winnerCarIds": final ? mode == "versus-tie" ? [car, other] : [car] : [], "tied": mode == "versus-tie"]
    }
    private func body() throws -> [String: Any] {
        var data = request.httpBody ?? Data()
        if data.isEmpty, let stream = request.httpBodyStream { stream.open(); defer { stream.close() }; var bytes = [UInt8](repeating: 0, count: 4096); while stream.hasBytesAvailable { let n = stream.read(&bytes, maxLength: bytes.count); if n <= 0 { break }; data.append(contentsOf: bytes.prefix(n)) } }
        return try JSONSerialization.jsonObject(with: data) as! [String: Any]
    }
}
private final class TripRouteOutboundBlockProtocol: URLProtocol {
    private static let lock = NSLock()
    private static var sentinelURL: URL?
    private static var blocked = 0
    static var blockedCount: Int { lock.withLock { blocked } }
    static func configureSentinel(_ url: URL?) { lock.withLock { sentinelURL = url } }
    static func reset() { lock.withLock { sentinelURL = nil; blocked = 0 } }
    override class func canInit(with request: URLRequest) -> Bool {
        lock.withLock {
            guard let url = request.url, ["http", "https"].contains(url.scheme) else { return false }
            return url.host == "ios-api-wegoh.devforest.io" || url == sentinelURL
        }
    }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func stopLoading() { }
    override func startLoading() {
        Self.lock.withLock { Self.blocked += 1 }
        client?.urlProtocol(self, didFailWithError: URLError(.notConnectedToInternet))
    }
}
#endif
