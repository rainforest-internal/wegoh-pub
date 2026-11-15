#if DEBUG
import Foundation

@MainActor
enum CourseDiscoveryUIFixture {
    static var configuration: URLSessionConfiguration? {
        guard ProcessInfo.processInfo.arguments.contains("-course-discovery-live-ui") else { return nil }
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [CourseDiscoveryFixtureProtocol.self]
        return configuration
    }

    static func sessionIfRequested() -> SessionManager? {
        guard let configuration else { return nil }
        let signedOut = ProcessInfo.processInfo.arguments.contains("-courses-ui-signed-out")
        return SessionManager(api: IPhoneSessionAPI(configuration: configuration),
                              credentials: CourseUIFixture.Credential(signedOut: signedOut))
    }
}

private final class CourseDiscoveryFixtureProtocol: URLProtocol {
    private typealias JSON = [String: Any]
    private static let lock = NSLock()
    private static let actor = "team-" + String(repeating: "a", count: 40)
    private static let creator = "team-" + String(repeating: "b", count: 40)
    private static let followID = "00000000-0000-4000-8000-000000000001"
    private static let tripID = String(repeating: "c", count: 32)
    private static let checksum = String(repeating: "d", count: 64)
    private static var saved = Set<String>()
    private static var followed = false
    private static var tags = Set<String>()
    private static var read = false
    private static var muted = Set<String>()
    private static var failedOnce = false
    private static var tripReads = 0
    private static var libraryReads = 0
    private static var invitationClosed = false

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    private var pendingResponse: DispatchWorkItem?

    override func stopLoading() { pendingResponse?.cancel() }

    override func startLoading() {
        if request.url?.path == "/v1/iphone/courses/library",
           ProcessInfo.processInfo.arguments.contains("-course-discovery-delayed-library") {
            let pending = DispatchWorkItem { [weak self] in self?.respond() }
            pendingResponse = pending
            DispatchQueue.global().asyncAfter(deadline: .now() + 3, execute: pending)
        } else {
            respond()
        }
    }

    private func respond() {
        do {
            let (status, payload) = try Self.lock.withLock { try response() }
            guard let url = request.url,
                  let http = HTTPURLResponse(url: url, statusCode: status, httpVersion: "HTTP/1.1",
                                             headerFields: ["Content-Type": "application/json"]) else {
                throw URLError(.badURL)
            }
            client?.urlProtocol(self, didReceive: http, cacheStoragePolicy: .notAllowed)
            if status != 204 {
                client?.urlProtocol(self, didLoad: try JSONSerialization.data(withJSONObject: payload))
            }
            client?.urlProtocolDidFinishLoading(self)
        } catch { client?.urlProtocol(self, didFailWithError: error) }
    }

    private struct Course {
        let id: String
        let title: String
        let tags: [String]
        var item: JSON {
            ["id": id, "version": 1, "title": title, "description": "테스트 공개 코스", "author": "사용자G",
             "tags": tags, "stopCount": 1, "stopNames": ["해변 산책로"], "starred": saved.contains(id), "starCount": saved.contains(id) ? 2 : 1,
             "canFollow": true, "checksum": checksum, "creatorId": creator, "followId": followed ? followID as Any : NSNull(), "hasCover": false,
             "stops": [["id": "test-stop", "name": "해변 산책로", "lat": 37.77, "lng": 128.94]]]
        }
        var detail: JSON {
            let stop: JSON = ["id": "test-stop", "name": "해변 산책로", "latitude": 37.77, "longitude": 128.94,
                              "radiusMeters": 100, "action": ["type": "chime", "message": "도착했어요."]]
            let pack: JSON = ["schemaVersion": 1, "id": id, "version": 1, "title": title,
                              "description": "테스트 공개 코스", "author": "사용자G", "stops": [stop]]
            return item.merging(["pack": pack]) { _, new in new }
        }
    }
    private static let courses = [Course(id: "test-coast", title: "해안 커피길", tags: ["바다", "커피"]),
                                  Course(id: "test-beach", title: "해변 산책", tags: ["바다"])]

    private func response() throws -> (Int, JSON) {
        guard let url = request.url, url.host == "ios-api-wegoh.devforest.io",
              url.path.hasPrefix("/v1/iphone/"),
              request.value(forHTTPHeaderField: "Authorization") == "Bearer " + String(repeating: "F", count: 43) else {
            return (401, ["detail": "IPHONE_SESSION_REQUIRED"])
        }
        let path = String(url.path.dropFirst("/v1/iphone/".count))
        let method = request.httpMethod ?? "GET"
        if let response = try TripPushUIFixture.response(path: path, method: method, request: request) { return response }
        if path == "session" {
            if method == "DELETE" { return (204, [:]) }
            return (200, ["user": ["id": Self.actor, "displayName": "테스트 사용자"],
                          "expiresAt": Int(Date.now.timeIntervalSince1970) + 3_600,
                          "scopes": ["account:read", "courses:read", "courses:write", "trips:read", "trips:manage"]])
        }
        if method == "GET", path == "profile" {
            return (200, ["user": ["id": Self.actor, "displayName": "테스트 사용자", "handle": "fixture.drive"]])
        }
        if method == "GET", path == "courses" { return (200, ["packs": []]) }
        if method == "POST", path == "trips/" + Self.tripID + "/respond",
           ProcessInfo.processInfo.arguments.contains("-trip-invitation-closed-ui") {
            Self.invitationClosed = true
            return (409, ["detail": "TRIP_STATE_CONFLICT"])
        }
        if method == "GET", path == "trips" {
            if ProcessInfo.processInfo.arguments.contains("-trip-invitation-closed-ui") {
                Self.tripReads += 1
                if Self.invitationClosed && Self.tripReads == 2 && ProcessInfo.processInfo.arguments.contains("-trip-invitation-reload-offline") {
                    return (503, ["detail": "UNAVAILABLE"])
                }
                let invitation: JSON = ["tripId": Self.tripID, "title": "닫힌 여행", "ownerName": "테스트 방장"]
                return (200, ["trips": [], "invitations": Self.invitationClosed ? [] : [invitation]])
            }
            if ProcessInfo.processInfo.arguments.contains("-tab-cache-fail-refresh") {
                Self.tripReads += 1
                if Self.tripReads > 1 { return (503, ["detail": "UNAVAILABLE"]) }
            }
            let trip: JSON = ["id": Self.tripID, "title": "함께 갈 여행", "state": "planned", "isOwner": true,
                              "ownerName": "테스트 사용자", "memberCount": 1, "carCount": 0]
            return (200, ["trips": [trip], "invitations": []])
        }
        return try discoveryResponse(path: path, method: method, url: url)
    }

    private func discoveryResponse(path: String, method: String, url: URL) throws -> (Int, JSON) {
        if path == "courses/library", method == "GET" {
            if ProcessInfo.processInfo.arguments.contains("-tab-cache-fail-refresh") {
                Self.libraryReads += 1
                if Self.libraryReads > 1 { return (503, ["detail": "UNAVAILABLE"]) }
            }
            if ProcessInfo.processInfo.arguments.contains("-course-discovery-fail-once"), !Self.failedOnce {
                Self.failedOnce = true
                return (503, ["detail": "UNAVAILABLE"])
            }
            let parameters = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems ?? []
            let query = parameters.first { $0.name == "q" }?.value ?? ""
            let filters = Set(parameters.filter { $0.name == "tag" }.compactMap(\.value))
            let visible = Self.courses.filter {
                !Self.muted.contains($0.id) && filters.isSubset(of: $0.tags)
                    && (query.isEmpty || $0.title.contains(query) || $0.tags.contains(query))
            }
            let source = Self.courses[0]
            var news = [JSON]()
            if Self.followed || !Self.tags.isDisjoint(with: source.tags) {
                news.append(source.item.merging(["eventId": "12", "approvedAt": "2026-11-12T00:00:00Z", "read": Self.read]) { _, value in value })
            }
            let following: [JSON] = Self.followed ? [["id": Self.followID, "creatorId": Self.creator, "name": "사용자G"]] : []
            return (200, ["public": visible.map(\.item), "saved": Self.courses.filter { Self.saved.contains($0.id) }.map(\.item),
                          "news": news, "following": following, "popularTags": ["바다", "커피"],
                          "followedTags": Self.tags.sorted(), "unreadCount": Self.read ? 0 : news.count])
        }
        if path == "courses/creators/" + Self.creator, method == "GET" {
            let creator: JSON = ["id": Self.creator, "name": "사용자G", "courseCount": 2, "starCount": 2,
                                 "followerCount": Self.followed ? 1 : 0, "following": Self.followed,
                                 "followId": Self.followed ? Self.followID as Any : NSNull()]
            return (200, ["creator": creator, "courses": Self.courses.map(\.item)])
        }
        if path == "courses/follows/" + Self.followID, method == "DELETE" {
            Self.followed = false
            return (200, ["following": false])
        }
        if path.hasPrefix("courses/tag-follows/"), ["PUT", "DELETE"].contains(method) {
            let tag = String(path.dropFirst("courses/tag-follows/".count))
            if method == "PUT" { Self.tags.insert(tag) } else { Self.tags.remove(tag) }
            return (200, ["tag": tag, "following": Self.tags.contains(tag)])
        }
        if path == "courses/news/12/read", method == "PUT" {
            Self.read = true
            return (200, ["read": true])
        }
        for course in Self.courses {
            let version = "/\(course.id)/versions/1"
            switch (method, path) {
            case ("GET", "courses/public" + version):
                return (200, course.detail)
            case ("PUT", "courses/stars" + version), ("DELETE", "courses/stars" + version):
                if ProcessInfo.processInfo.arguments.contains("-course-discovery-expired") {
                    return (401, ["detail": "IPHONE_SESSION_REVOKED"])
                }
                if method == "PUT" { Self.saved.insert(course.id) } else { Self.saved.remove(course.id) }
                return (200, ["starred": method == "PUT"])
            case ("PUT", "courses/follows" + version):
                Self.followed = true
                return (200, ["followId": Self.followID])
            case ("PUT", "courses/hidden" + version):
                Self.muted.insert(course.id)
                return (200, ["hidden": true])
            case ("POST", "courses/public" + version + "/reports"):
                Self.muted.insert(course.id)
                return (202, ["reportId": String(repeating: "1", count: 32), "state": "quarantined"])
            case ("POST", "courses/public" + version + "/copy"):
                guard var pack = course.detail["pack"] as? JSON else { throw URLError(.cannotDecodeContentData) }
                pack["id"] = "test-copy"
                pack["author"] = "테스트 사용자"
                return (201, ["pack": pack, "tags": course.tags, "remixDraftId": String(repeating: "2", count: 32), "hasCover": false])
            default:
                continue
            }
        }
        if path == "trips/" + Self.tripID + "/courses", method == "POST" {
            guard try requestFields()["packId"] == Self.courses[0].id else { return (400, ["detail": "INVALID_PACK"]) }
            return (201, ["status": "added"])
        }
        return (404, ["detail": "FIXTURE_ROUTE_UNAVAILABLE"])
    }

    private func requestFields() throws -> [String: String] {
        if let data = request.httpBody {
            return try JSONDecoder().decode([String: String].self, from: data)
        }
        guard let stream = request.httpBodyStream else { return [:] }
        stream.open()
        defer { stream.close() }
        return try JSONSerialization.jsonObject(with: stream) as? [String: String] ?? [:]
    }
}
#endif
