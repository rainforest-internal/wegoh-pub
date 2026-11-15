#if DEBUG
import Foundation

@MainActor
enum CourseUIFixture {
    static var requested: Bool { ProcessInfo.processInfo.arguments.contains("-courses-ui-testing") || ProcessInfo.processInfo.arguments.contains("-profile-ui-testing") }
    static func apiIfRequested() -> IPhoneCourseAPI? {
        requested ? IPhoneCourseAPI(configuration: configuration()) : nil
    }
    static func sessionIfRequested() -> SessionManager? {
        guard requested else { return nil }
        return SessionManager(api: IPhoneSessionAPI(configuration: configuration()),
                              credentials: Credential(signedOut: ProcessInfo.processInfo.arguments.contains("-courses-ui-signed-out")))
    }
    static func profileConfigurationIfRequested() -> URLSessionConfiguration? { requested ? configuration() : nil }
    static func configuration() -> URLSessionConfiguration {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [CourseFixtureProtocol.self]
        return config
    }
    final class Credential: IPhoneCredentialStoring {
        var value: StoredIPhoneCredential?
        init(signedOut: Bool = false) {
            value = signedOut ? nil : .init(token: String(repeating: "F", count: 43), logoutPending: false)
        }
        func load() throws -> StoredIPhoneCredential? { value }
        func saveToken(_ token: String) throws { value = .init(token: token, logoutPending: false) }
        func markLogoutPending() throws { value = value.map { .init(token: $0.token, logoutPending: true) } }
        func clearToken() throws { value = nil }
    }
}

private final class CourseFixtureProtocol: URLProtocol {
    private static let lock = NSLock()
    private static var searchFailedOnce = false
    private static var courseReads = 0
    private static var profileName = "사용자D"
    private static var profileHandle = "user-d.drive"
    private static var plate = ProcessInfo.processInfo.arguments.contains("-trip-car-ui-missing-plate") ? "" : "123가4567"
    private static var plateRevision = 0
    private static var vehicleName = ""
    private struct CourseMetadata {
        var tags: [String] = []
        var hasCover = false
    }
    private static var metadata = ["fixture-coast": CourseMetadata(hasCover: true)]
    private static var packs: [String: [String: Any]] = {
        guard !ProcessInfo.processInfo.arguments.contains("-courses-ui-empty") else { return [:] }
        let pack: [String: Any] = ["schemaVersion": 1, "id": "fixture-coast", "version": 1,
            "title": "태안 노을 드라이브", "author": "사용자D", "description": "경포해변에서 안목 커피거리까지, 바다를 따라 달리는 코스예요.",
            "stops": [stop(id: "gyeongpo", name: "경포해변", lat: 37.8068, lng: 128.9087, address: "강원 강릉시 안현동"),
                      stop(id: "anmok", name: "안목 커피거리", lat: 37.7725, lng: 128.9478, address: "강원 강릉시 창해로14번길")]]
        return ["fixture-coast": pack]
    }()
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func stopLoading() { }
    override func startLoading() {
        Self.lock.lock()
        defer { Self.lock.unlock() }
        do {
            let (status, value) = try response()
            let response = HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: "HTTP/1.1",
                headerFields: ["Content-Type": "application/json"])!
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            if status != 204 {
                client?.urlProtocol(self, didLoad: try JSONSerialization.data(withJSONObject: value))
            }
            client?.urlProtocolDidFinishLoading(self)
        } catch { client?.urlProtocol(self, didFailWithError: error) }
    }
    private func response() throws -> (Int, [String: Any]) {
        let path = request.url!.path
        if path.hasSuffix("/session") {
            if request.httpMethod == "DELETE" { return (204, [:]) }
            return (200, ["user": ["id": "team-" + String(repeating: "a", count: 40), "displayName": "사용자D"],
                "scopes": ["account:read", "account:write", "vehicles:manage", "courses:read", "courses:write", "maps:read"],
                "expiresAt": Int(Date.now.timeIntervalSince1970) + 3600])
        }
        if path.hasSuffix("/profile/handle") {
            let value = try payload()["handle"] as! String
            if value == "taken_code" { return (409, ["detail": "HANDLE_UNAVAILABLE"]) }
            Self.profileHandle = value
            return (200, ["handle": value])
        }
        if path.hasSuffix("/vehicles") {
            return (200, ["devices": [["id": String(repeating: "b", count: 32), "name": Self.vehicleName.isEmpty ? Self.profileName + "의 차" : Self.vehicleName,
                                       "expiresAt": "2026-11-19T00:00:00Z", "authorizationVersion": 1]]])
        }
        if path.contains("/vehicles/"), path.hasSuffix("/profile") {
            if request.httpMethod == "PUT" {
                let body = try payload()
                Self.plate = body["plateNumber"] as! String
                Self.vehicleName = body["name"] as! String
                Self.plateRevision += 1
            }
            return (200, ["deviceId": String(repeating: "b", count: 32), "plateNumber": Self.plate, "name": Self.vehicleName,
                          "defaultName": Self.profileName + "의 차", "revision": Self.plateRevision])
        }
        if path.hasSuffix("/profile") {
            if request.httpMethod == "PUT" { Self.profileName = try payload()["displayName"] as! String }
            return (200, ["user": ["id": "team-" + String(repeating: "a", count: 40), "displayName": Self.profileName, "handle": Self.profileHandle]])
        }
        if path.hasSuffix("/routes/preview") {
            if ProcessInfo.processInfo.arguments.contains("-courses-ui-route-failure") {
                return (503, ["detail": "ROUTE_UNAVAILABLE"])
            }
            return (200, ["distanceMeters": 6100, "durationSeconds": 780,
                "path": [[37.8068, 128.9087], [37.8000, 128.9050], [37.7900, 128.9180],
                         [37.7800, 128.9340], [37.7725, 128.9478]]])
        }
        if path.hasSuffix("/places/search") {
            if ProcessInfo.processInfo.arguments.contains("-courses-ui-search-retry"), !Self.searchFailedOnce {
                Self.searchFailedOnce = true
                return (503, ["detail": "PLACE_SEARCH_UNAVAILABLE"])
            }
            let query = URLComponents(url: request.url!, resolvingAgainstBaseURL: false)?.queryItems?.first?.value ?? ""
            let second = query.contains("안목")
            return (200, ["places": [["id": second ? "kakao-2" : "kakao-1", "name": second ? "안목 커피거리" : "경포해변",
                "address": second ? "강원 강릉시 창해로14번길" : "강원 강릉시 안현동", "roadAddress": "",
                "lat": second ? 37.7725 : 37.8068, "lng": second ? 128.9478 : 128.9087, "source": "kakao"]]])
        }
        if path.hasSuffix("/courses"), request.httpMethod == "POST" {
            let body = try payload()
            var pack = body["pack"] as! [String: Any]
            pack["author"] = "사용자D"
            let id = pack["id"] as! String
            let sourceVersion = body["copyCoverFromVersion"] as? Int
            let hasCover = sourceVersion != nil && sourceVersion == (Self.packs[id]?["version"] as? Int)
                && Self.metadata[id]?.hasCover == true
            Self.metadata[id] = CourseMetadata(tags: body["tags"] as? [String] ?? [], hasCover: hasCover)
            Self.packs[id] = pack
            return (201, ["id": id, "version": pack["version"]!, "checksum": String(repeating: "a", count: 64), "state": "approved", "pack": pack])
        }
        if path.hasSuffix("/courses") {
            if request.httpMethod == "GET" {
                let arguments = ProcessInfo.processInfo.arguments
                if arguments.contains("-tab-cache-fail-refresh") || arguments.contains("-tab-cache-fail-first") {
                    Self.courseReads += 1
                    if (arguments.contains("-tab-cache-fail-refresh") && Self.courseReads > 1)
                        || (arguments.contains("-tab-cache-fail-first") && Self.courseReads == 1) {
                        return (503, ["detail": "UNAVAILABLE"])
                    }
                }
            }
            if ProcessInfo.processInfo.arguments.contains("-courses-ui-list-failure") {
                return (503, ["detail": "UNAVAILABLE"])
            }
            let items: [[String: Any]] = Self.packs.values.map { pack in
                ["id": pack["id"]!, "version": pack["version"]!, "title": pack["title"]!, "author": pack["author"]!,
                 "description": pack["description"]!, "stopCount": (pack["stops"] as! [Any]).count,
                 "stopNames": (pack["stops"] as! [[String: Any]]).map { $0["name"]! },
                 "stops": (pack["stops"] as! [[String: Any]]).map {
                     ["id": $0["id"]!, "name": $0["name"]!, "lat": $0["latitude"]!, "lng": $0["longitude"]!]
                 },
                 "checksum": String(repeating: "a", count: 64), "state": "approved"]
            }
            return (200, ["packs": items.sorted { ($0["id"] as! String) < ($1["id"] as! String) }])
        }
        let parts = path.split(separator: "/")
        if parts.count == 6, parts[2] == "courses", parts[4] == "versions",
           let version = Int(parts[5]), let pack = Self.packs[String(parts[3])], pack["version"] as? Int == version {
            let metadata = Self.metadata[String(parts[3])] ?? CourseMetadata()
            return (200, ["pack": pack, "tags": metadata.tags, "hasCover": metadata.hasCover])
        }
        return (404, ["detail": "Course unavailable"])
    }
    private func payload() throws -> [String: Any] {
        var data = request.httpBody ?? Data()
        if data.isEmpty, let stream = request.httpBodyStream {
            stream.open(); defer { stream.close() }
            var bytes = [UInt8](repeating: 0, count: 4096)
            while stream.hasBytesAvailable {
                let count = stream.read(&bytes, maxLength: bytes.count)
                guard count > 0 else { break }
                data.append(contentsOf: bytes.prefix(count))
            }
        }
        return try JSONSerialization.jsonObject(with: data) as! [String: Any]
    }
    private static func stop(id: String, name: String, lat: Double, lng: Double, address: String) -> [String: Any] {
        ["id": id, "name": name, "latitude": lat, "longitude": lng, "radiusMeters": 100,
         "address": address, "action": ["type": "chime", "message": "\(name)에 도착했어요."]]
    }
}
#endif
