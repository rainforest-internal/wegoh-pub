#if DEBUG
import CryptoKit
import SwiftUI

struct TripActivityUIFixture: View {
    nonisolated static var requested: Bool { ProcessInfo.processInfo.arguments.contains("-trip-activity-ui-testing") }
    nonisolated static var mode: String {
        let arguments = ProcessInfo.processInfo.arguments
        guard let index = arguments.firstIndex(of: "-trip-activity-ui-testing"), arguments.indices.contains(index + 1) else { return "reason" }
        return arguments[index + 1]
    }
    static func configuration() -> URLSessionConfiguration {
        let value = URLSessionConfiguration.ephemeral; value.protocolClasses = [TripActivityFixtureProtocol.self]; return value
    }
    @MainActor static func sessionIfRequested() -> SessionManager? {
        guard requested else { return nil }
        return SessionManager(api: IPhoneSessionAPI(configuration: configuration()), credentials: FriendsUIFixture.Credential())
    }
    @Environment(SessionManager.self) private var session
    @State private var preparation: TripPreparationStore?
    @State private var remoteSheet = false
    @State private var mapPath: [CourseCoordinate] = []
    var body: some View {
        Group {
            if Self.mode.hasPrefix("remote"), Self.mode != "remote-resume-sheet" { fixtureContent }
            else { NavigationStack { fixtureContent } }
        }.task(id: session.current?.accountID) {
            guard session.current != nil else { return }
            let value = TripPreparationStore(tripID: TripActivityFixtureProtocol.tripID, session: session, api: IPhoneTripAPI(configuration: Self.configuration()))
            preparation = value; await value.load()
        }
    }
    private var fixtureContent: some View {
            Group {
                if let preparation, preparation.detail != nil {
                    switch Self.mode {
                    case "map-layering":
                        WegoMapPreview(markers: [
                            .init(id: "first", name: "1번 장소", latitude: 37.5, longitude: 127),
                            .init(id: "middle", name: "2번 장소", latitude: 37.5, longitude: 127.01),
                            .init(id: "last", name: "3번 장소", latitude: 37.5, longitude: 127.02)
                        ], path: mapPath, isThumbnail: true)
                        .frame(height: WegoTokens.Metrics.courseDetailMapHeight)
                        .clipShape(RoundedRectangle(cornerRadius: WegoTokens.Radius.control))
                        .padding(WegoTokens.Space.screen)
                        .accessibilityIdentifier("mapLayeringPreview")
                        .task {
                            do {
                                try await Task.sleep(for: .seconds(2))
                                mapPath = [127, 127.01, 127.02].map { .init(lat: 37.5, lng: $0) }
                            } catch { }
                        }
                    case "roles": TripRolesView(store: preparation)
                    case "policy": TripRemotePolicyView(store: preparation)
                    case "remote-resume-sheet":
                        Button("리모컨 열기") { remoteSheet = true }
                            .buttonStyle(.wego(.primary))
                            .sheet(isPresented: $remoteSheet) {
                                Group {
                                    TripLiveRemoteView(preparation: preparation, api: IPhoneTripActivityAPI(configuration: Self.configuration()))
                                        .safeAreaInset(edge: .bottom) {
                                            TimelineView(.periodic(from: .now, by: 0.2)) { _ in
                                                VStack(spacing: WegoTokens.Space.small) {
                                                    Text("연동 테스트 샘플 · 실제 계정·차량에 요청하지 않아요")
                                                    Text("명령 전송 \(TripActivityFixtureProtocol.remoteCommandCount)").accessibilityIdentifier("remoteFixtureCommandCount")
                                                    Text("리모컨 조회 \(TripActivityFixtureProtocol.remotePageCount)").accessibilityIdentifier("remoteFixtureReadCount")
                                                }.font(WegoTokens.Typography.caption).padding(WegoTokens.Space.small)
                                                    .frame(maxWidth: .infinity).background(WegoTokens.Palette.accentSoft)
                                            }
                                        }
                                }
                            }
                    case "remote", "remote-feedback", "remote-resume", "remote-resume-retry", "remote-unknown", "remote-rejected", "remote-uncertain", "remote-timeout": TripLiveRemoteView(preparation: preparation, api: IPhoneTripActivityAPI(configuration: Self.configuration()))
                    case "functional": VehicleFunctionalPermissionsView(vehicle: LinkedVehicle(id: TripActivityFixtureProtocol.deviceID, name: "사용자A의 차", expiresAt: "2027-01-01T00:00:00Z", authorizationVersion: 1), api: IPhoneVehicleFunctionalAPI(configuration: Self.configuration()))
                    default: TripLiveSignalView(preparation: preparation, api: IPhoneTripActivityAPI(configuration: Self.configuration()))
                    }
                } else { WegoLoadingView("연동 테스트 샘플 준비 중") }
            }.safeAreaInset(edge: Self.mode.hasPrefix("remote") ? .bottom : .top) {
                if Self.mode != "remote-resume-sheet" {
                VStack(spacing: WegoTokens.Space.xSmall) {
                    Text("연동 테스트 샘플 · 실제 계정·차량에 요청하지 않아요")
                    if Self.mode.hasPrefix("remote") {
                        TimelineView(.periodic(from: .now, by: 0.2)) { _ in
                            VStack(spacing: WegoTokens.Space.xSmall) {
                                Text("명령 전송 \(TripActivityFixtureProtocol.remoteCommandCount)")
                                    .accessibilityIdentifier("remoteFixtureCommandCount")
                                Text(TripActivityFixtureProtocol.remoteLastTarget).accessibilityIdentifier("remoteFixtureLastTarget")
                                if Self.mode.hasPrefix("remote-resume") {
                                    Text("리모컨 조회 \(TripActivityFixtureProtocol.remotePageCount)").accessibilityIdentifier("remoteFixtureReadCount")
                                }
                            }
                        }
                    }
                }.font(WegoTokens.Typography.caption).padding(WegoTokens.Space.small)
                    .frame(maxWidth: .infinity).background(WegoTokens.Palette.accentSoft)
                }
            }
    }
}

private final class TripActivityFixtureProtocol: URLProtocol {
    static let tripID = String(repeating: "a", count: 32)
    static let carID = String(repeating: "b", count: 32)
    static let deviceID = String(repeating: "d", count: 32)
    private static let lock = NSLock()
    private static var sent = false
    private static var remoteCommands: [[String: Any]] = []
    private static var remoteReads: [String: Int] = [:]
    private static var remoteArguments: [String: Any] = [:]
    private static var pageCount = 0
    static var remotePageCount: Int { lock.withLock { pageCount } }
    static var remoteLastTarget: String {
        lock.lock(); defer { lock.unlock() }
        return "요청 좌석 " + (remoteArguments["seat"] as? String ?? "없음")
    }
    static var remoteCommandCount: Int {
        lock.lock(); defer { lock.unlock() }
        return remoteCommands.count
    }
    private static var voted: String?
    private static var terminal: String?
    private static var approved: [String] = []
    private static var policy: [String: Any] = ["enabled": true, "actions": TripRemoteGroup.allCases.flatMap(\.actionIDs).sorted(), "deviceId": deviceID]
    private static var roles = ["member", "dj", "food", "member", "rest"]
    private static var isOwner: Bool { ["roles", "policy"].contains(TripActivityUIFixture.mode) }
    private static var actorID: String { account(isOwner ? 1 : 3) }
    private static func account(_ n: Int) -> String { "team-" + String(repeating: String(n), count: 40) }
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func stopLoading() { }
    override func startLoading() {
        Self.lock.lock(); defer { Self.lock.unlock() }
        do {
            let (status, value) = try response()
            let response = HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: nil, headerFields: ["Content-Type": "application/json"])!
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: try JSONSerialization.data(withJSONObject: value))
            client?.urlProtocolDidFinishLoading(self)
        } catch { client?.urlProtocol(self, didFailWithError: error) }
    }
    private func response() throws -> (Int, [String: Any]) {
        let path = request.url!.path, method = request.httpMethod ?? "GET"
        if path.hasSuffix("/session") {
            return (200, ["user": ["id": Self.actorID, "displayName": Self.isOwner ? "사용자A" : "사용자D"], "scopes": ["account:read", "vehicles:manage", "trips:read", "trips:manage", "maps:read"], "expiresAt": Int(Date.now.timeIntervalSince1970) + 3600])
        }
        if path.hasSuffix("/functional-permissions") { return try functional(method: method) }
        if path.hasSuffix("/remote-policy") {
            if method == "PUT" { Self.policy = try body() }
            return (200, ["remotePolicy": Self.policy])
        }
        if path.hasSuffix("/role") {
            let payload = try body()
            if let index = (1...5).first(where: { path.contains(Self.account($0)) }), let role = payload["role"] as? String { Self.roles[index - 1] = role }
            return (200, ["status": "updated", "revision": 2])
        }
        if path.hasSuffix("/vehicle-remotes") {
            if TripActivityUIFixture.mode == "remote-resume-retry", Self.pageCount == 1 {
                Self.pageCount += 1
                return (503, ["detail": "FIXTURE_TEMPORARY_UNAVAILABLE"])
            }
            return (200, Self.remotePage())
        }
        if path.hasSuffix("/commands") {
            let payload = try body()
            guard method == "POST", ["remote", "remote-feedback", "remote-rejected", "remote-uncertain", "remote-timeout"].contains(TripActivityUIFixture.mode),
                  let action = payload["capabilityId"] as? String,
                  let arguments = payload["arguments"] as? [String: Any],
                  ["hvac.temperature", "hvac.fan", "hvac.power"].contains(action),
                  ["ROW_1_RIGHT", "ROW_2_LEFT"].contains(arguments["seat"] as? String ?? "") else {
                return (422, ["detail": "VEHICLE_CONTROL_AREA_UNSUPPORTED"])
            }
            let formatter = ISO8601DateFormatter(), now = Date()
            let id = String(format: "%032x", Self.remoteCommands.count + 1)
            let value: [String: Any] = ["id": id, "tripId": Self.tripID, "targetDeviceId": Self.deviceID,
                "requesterId": Self.actorID, "ownerId": Self.account(1), "capabilityId": action,
                "capabilityRevision": 1, "stage": "queued", "lastAcknowledgedStage": NSNull(),
                "reason": NSNull(), "mayHaveExecuted": false, "physicalExecutionVerified": false,
                "createdAt": formatter.string(from: now), "expiresAt": formatter.string(from: now.addingTimeInterval(30))]
            Self.remoteCommands.append(value)
            Self.remoteArguments = arguments
            if TripActivityUIFixture.mode == "remote-timeout" { throw URLError(.timedOut) }
            return (201, value)
        }
        if path.hasSuffix("/signals") {
            if method == "POST" { Self.sent = true; return (201, ["id": String(repeating: "e", count: 32), "status": "sent"]) }
            return (200, ["signals": Self.signal().map { [$0] } ?? [], "nextCursor": NSNull()])
        }
        if path.hasSuffix("/vote") { let old = Self.voted; if old == nil { Self.voted = try body()["choice"] as? String }; return (200, ["status": "saved", "choice": Self.voted ?? "agree", "already": old != nil, "responderAccountId": Self.actorID]) }
        if path.hasSuffix("/finish") { Self.terminal = try body()["result"] as? String; return (200, ["status": Self.terminal ?? "completed", "revision": 2]) }
        if path.hasSuffix("/trips/" + Self.tripID) { return (200, Self.detail()) }
        return (404, ["detail": "FIXTURE_ROUTE_UNAVAILABLE"])
    }
    private static func remotePage() -> [String: Any] {
        pageCount += 1
        let formatter = ISO8601DateFormatter(), now = Date()
        let lifetime: TimeInterval = TripActivityUIFixture.mode.hasPrefix("remote-resume") && pageCount == 1 ? 8 : 90
        func support(_ min: Any, _ max: Any, _ step: Any) -> [String: Any] {
            ["status": "known", "available": true,
             "areas": ["ROW_1_RIGHT", "ROW_2_LEFT"].map { ["id": $0, "min": min, "max": max, "step": step] }, "zones": [[String]](),
             "observedAt": formatter.string(from: now), "expiresAt": formatter.string(from: now.addingTimeInterval(lifetime))]
        }
        var actions: [[String: Any]] = [
            ["id": "hvac.temperature", "revision": 1, "label": "설정 온도", "argumentKind": "hvac-celsius"],
            ["id": "hvac.fan", "revision": 1, "label": "풍량", "argumentKind": "hvac-fan"],
            ["id": "hvac.power", "revision": 1, "label": "공조 전원", "argumentKind": "seat-switch"]]
        if TripActivityUIFixture.mode != "remote-unknown" {
            actions[0]["support"] = support(15, 30, 0.5)
            actions[1]["support"] = support(1, 8, 1)
            actions[2]["support"] = support(NSNull(), NSNull(), NSNull())
        }
        let requests: [[String: Any]] = remoteCommands.suffix(5).reversed().map { saved in
            var value = saved
            let id = saved["id"] as! String
            let reads = remoteReads[id, default: 0]
            remoteReads[id] = reads + 1
            if reads >= (TripActivityUIFixture.mode == "remote-feedback" ? 3 : 1) {
                let stage = TripActivityUIFixture.mode == "remote-rejected" ? "rejected"
                    : TripActivityUIFixture.mode == "remote-uncertain" ? "unknown" : "state-confirmed"
                value["stage"] = stage; value["lastAcknowledgedStage"] = stage
                value["mayHaveExecuted"] = stage != "rejected"
            }
            return value
        }
        return ["tripId": tripID, "serverNow": formatter.string(from: now), "remotes": [[
            "deviceId": deviceID, "ownerName": "사용자A", "deviceName": "사용자A의 차", "grantRevision": 2,
            "expiresAt": formatter.string(from: now.addingTimeInterval(3600)), "actions": actions, "requests": requests]]]
    }

    private static func detail() -> [String: Any] {
        let names = ["사용자A", "사용자C", "사용자D", "사용자B", "사용자E"], otherCar = String(repeating: "c", count: 32)
        let members: [[String: Any]] = names.enumerated().map { index, name in
            let n = index + 1
            return ["id": account(n), "name": name, "state": "accepted", "isMe": account(n) == actorID, "isOwner": n == 1, "hasVehicle": n == 1 || n == 4, "carId": n < 4 ? carID : otherCar, "readiness": "ready", "role": roles[index]]
        }
        let cars: [[String: Any]] = [["id": carID, "name": "사용자A의 차", "seats": 4, "driverId": account(1), "driverName": "사용자A", "isMine": isOwner, "iRide": !isOwner, "driverVehicleReady": true, "passengers": [["id": account(2), "name": "사용자C", "isMe": false], ["id": account(3), "name": "사용자D", "isMe": !isOwner]], "places": [], "remotePolicy": policy], ["id": otherCar, "name": "사용자B의 차", "seats": 1, "driverId": account(4), "driverName": "사용자B", "isMine": false, "iRide": false, "driverVehicleReady": true, "passengers": [["id": account(5), "name": "사용자E", "isMe": false]], "places": [], "remotePolicy": NSNull()]]
        return ["id": tripID, "title": "서해안 드라이브", "description": "서해안에서 함께 달려요.", "state": isOwner ? "planned" : "active", "revision": 2, "isOwner": isOwner, "ownerId": account(1), "myPermissions": ["invite": isOwner, "edit": isOwner], "members": members, "cars": cars, "unassigned": [], "courses": [["packId": "coast", "title": "서해안 해안도로 코스", "version": 1, "stopCount": 3, "stops": [["id": "ganwol", "name": "간월암", "lat": 36.617, "lng": 126.339], ["id": "kkoji", "name": "꽃지해수욕장", "lat": 36.5, "lng": 126.33], ["id": "daecheon", "name": "대천해수욕장", "lat": 36.3, "lng": 126.5]], "drivingScores": [["carId": carID, "score": 90, "accelerations": 1, "brakings": 1, "measurable": true, "final": false]]]], "locationConsent": false]
    }
    private static func signal() -> [String: Any]? {
        let mode = TripActivityUIFixture.mode
        if mode == "reason" && !sent { return nil }
        let received = mode == "received"
        let resolution = terminal ?? (voted == "agree" || mode == "agreed" ? "agreed" : voted == "pass" || mode == "passed" ? "passed" : "pending")
        return ["id": String(repeating: "e", count: 32), "accountId": received ? account(5) : actorID, "kind": "restroom", "destination": ["name": "서산휴게소", "latitude": 36.7, "longitude": 126.5], "contextState": "valid", "inProgress": resolution == "pending" || resolution == "agreed", "resolution": resolution, "agreed": resolution == "agreed", "canRespond": received && voted == nil, "myGroupChoice": voted as Any? ?? NSNull(), "requesterCarId": received ? String(repeating: "c", count: 32) : carID, "groupVotes": ["agree": resolution == "agreed" ? 1 : 0, "pass": resolution == "passed" ? 1 : 0, "required": 1], "groupResponses": [["carId": received ? carID : String(repeating: "c", count: 32), "carName": received ? "사용자A의 차" : "사용자B의 차", "choice": voted as Any? ?? NSNull(), "responderName": voted == nil ? NSNull() : "사용자D"]]]
    }
    private func functional(method: String) throws -> (Int, [String: Any]) {
        let purpose: [String: Any] = ["id": "driving-score:report", "label": "코스 안전운전 점수 공유", "dataCategories": ["코스별 안전운전 점수", "급가속·급감속 횟수"], "purpose": "점수와 횟수만 같은 차 일행에게 공유해요.", "retention": "현재 차량 연결 기한 안에서 사용해요.", "withdrawal": "이 화면에서 끄면 이후 전송을 막아요.", "refusal": "점수 공유 없이 여행할 수 있어요.", "default": false]
        let bytes = try JSONSerialization.data(withJSONObject: ["version": 3, "purposes": [purpose]], options: [.sortedKeys, .withoutEscapingSlashes])
        let hash = SHA256.hash(data: bytes).map { String(format: "%02x", $0) }.joined()
        if method == "PUT" { Self.approved = try body()["approvedPurposes"] as? [String] ?? [] }
        return (200, ["authorization": ["authorizationVersion": 1, "deviceId": Self.deviceID, "grantId": String(repeating: "c", count: 32), "revision": 2, "expiresAt": 2000000000, "approvedPurposes": Self.approved, "functionalDisclosureVersion": 3, "functionalDisclosureSha256": hash], "disclosure": ["version": 3, "sha256": hash, "purposes": [purpose]], "readOnlyPurposes": []])
    }
    private func body() throws -> [String: Any] {
        var data = request.httpBody ?? Data()
        if data.isEmpty, let stream = request.httpBodyStream {
            stream.open(); defer { stream.close() }
            var bytes = [UInt8](repeating: 0, count: 2048)
            while stream.hasBytesAvailable { let count = stream.read(&bytes, maxLength: bytes.count); if count <= 0 { break }; data.append(contentsOf: bytes.prefix(count)) }
        }
        return data.isEmpty ? [:] : try JSONSerialization.jsonObject(with: data) as! [String: Any]
    }
}
#endif
