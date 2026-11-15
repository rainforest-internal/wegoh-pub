import Foundation
import OSLog

/// 서버가 마운트한 iPhone 경로 템플릿(FastAPI 경로). 진단 보고는 이 템플릿만 보낼 수 있다.
/// 서버는 마운트하지 않은 `METHOD 템플릿` 보고를 거절하므로 서버 매개변수 이름과 정확히 같아야 한다.
enum IPhoneRouteTemplates {
    static let all: [String] = [
        "POST /v1/iphone/blocks",
        "DELETE /v1/iphone/blocks/{target}",
        "POST /v1/iphone/browser/login/decision",
        "DELETE /v1/iphone/browser/sessions",
        "GET /v1/iphone/courses",
        "POST /v1/iphone/courses",
        "GET /v1/iphone/courses/creators/{creator_id}",
        "DELETE /v1/iphone/courses/follows/{follow_id}",
        "PUT /v1/iphone/courses/follows/{pack_id}/versions/{version}",
        "DELETE /v1/iphone/courses/hidden/{pack_id}/versions/{version}",
        "PUT /v1/iphone/courses/hidden/{pack_id}/versions/{version}",
        "GET /v1/iphone/courses/library",
        "PUT /v1/iphone/courses/news/{event_id}/read",
        "GET /v1/iphone/courses/public/{pack_id}/versions/{version}",
        "POST /v1/iphone/courses/public/{pack_id}/versions/{version}/copy",
        "GET /v1/iphone/courses/public/{pack_id}/versions/{version}/cover",
        "POST /v1/iphone/courses/public/{pack_id}/versions/{version}/reports",
        "DELETE /v1/iphone/courses/stars/{pack_id}/versions/{version}",
        "PUT /v1/iphone/courses/stars/{pack_id}/versions/{version}",
        "DELETE /v1/iphone/courses/tag-follows/{tag}",
        "PUT /v1/iphone/courses/tag-follows/{tag}",
        "GET /v1/iphone/courses/{pack_id}/versions/{version}",
        "POST /v1/iphone/diagnostics",
        "GET /v1/iphone/friends",
        "POST /v1/iphone/friends/requests",
        "POST /v1/iphone/friends/requests/{target}/respond",
        "GET /v1/iphone/friends/search",
        "GET /v1/iphone/friends/{peer}/profile",
        "DELETE /v1/iphone/friends/{target}",
        "POST /v1/iphone/login/cancel",
        "POST /v1/iphone/login/exchange",
        "POST /v1/iphone/login/requests",
        "GET /v1/iphone/places/search",
        "GET /v1/iphone/playlists",
        "POST /v1/iphone/playlists",
        "DELETE /v1/iphone/playlists/{playlist_id}",
        "GET /v1/iphone/playlists/{playlist_id}",
        "PUT /v1/iphone/playlists/{playlist_id}",
        "GET /v1/iphone/profile",
        "PUT /v1/iphone/profile",
        "PUT /v1/iphone/profile/handle",
        "DELETE /v1/iphone/push/installation",
        "PUT /v1/iphone/push/installation",
        "POST /v1/iphone/routes/preview",
        "DELETE /v1/iphone/session",
        "GET /v1/iphone/session",
        "GET /v1/iphone/trips",
        "POST /v1/iphone/trips",
        "DELETE /v1/iphone/trips/{id}",
        "GET /v1/iphone/trips/{id}",
        "PATCH /v1/iphone/trips/{id}",
        "POST /v1/iphone/trips/{id}/cancel",
        "POST /v1/iphone/trips/{id}/cars",
        "DELETE /v1/iphone/trips/{id}/cars/{carId}",
        "PATCH /v1/iphone/trips/{id}/cars/{carId}",
        "PUT /v1/iphone/trips/{id}/cars/{carId}/my-places",
        "GET /v1/iphone/trips/{id}/cars/{carId}/places",
        "POST /v1/iphone/trips/{id}/cars/{carId}/places",
        "DELETE /v1/iphone/trips/{id}/cars/{carId}/places/{placeId}",
        "DELETE /v1/iphone/trips/{id}/cars/{carId}/places/{placeId}/select",
        "PUT /v1/iphone/trips/{id}/cars/{carId}/places/{placeId}/select",
        "GET /v1/iphone/trips/{id}/cars/{carId}/remote-policy",
        "PUT /v1/iphone/trips/{id}/cars/{carId}/remote-policy",
        "PUT /v1/iphone/trips/{id}/cars/{carId}/ride",
        "POST /v1/iphone/trips/{id}/cars/{carId}/ride-invites/{inviteId}/respond",
        "POST /v1/iphone/trips/{id}/courses",
        "PUT /v1/iphone/trips/{id}/courses/priority",
        "DELETE /v1/iphone/trips/{id}/courses/{packId}",
        "GET /v1/iphone/trips/{id}/driving-score",
        "GET /v1/iphone/trips/{id}/driving-versus",
        "POST /v1/iphone/trips/{id}/finish",
        "GET /v1/iphone/trips/{id}/friends",
        "GET /v1/iphone/trips/{id}/location-sharing",
        "PATCH /v1/iphone/trips/{id}/location-sharing",
        "POST /v1/iphone/trips/{id}/members",
        "DELETE /v1/iphone/trips/{id}/members/{accountId}",
        "PUT /v1/iphone/trips/{id}/members/{accountId}/role",
        "POST /v1/iphone/trips/{id}/respond",
        "DELETE /v1/iphone/trips/{id}/ride",
        "GET /v1/iphone/trips/{id}/signals",
        "POST /v1/iphone/trips/{id}/signals",
        "POST /v1/iphone/trips/{id}/signals/candidates",
        "POST /v1/iphone/trips/{id}/signals/{signal}/finish",
        "DELETE /v1/iphone/trips/{id}/signals/{signal}/vote",
        "POST /v1/iphone/trips/{id}/signals/{signal}/vote",
        "POST /v1/iphone/trips/{id}/start",
        "GET /v1/iphone/trips/{id}/voice-participation",
        "PATCH /v1/iphone/trips/{id}/voice-participation",
        "GET /v1/iphone/trips/{room}/voice/filters",
        "PUT /v1/iphone/trips/{room}/voice/filters/{speaker}",
        "POST /v1/iphone/trips/{room}/voice/reports",
        "GET /v1/iphone/trips/{trip}/course-draft-options",
        "POST /v1/iphone/trips/{trip}/course-drafts",
        "GET /v1/iphone/trips/{trip}/history",
        "POST /v1/iphone/trips/{trip}/history",
        "GET /v1/iphone/trips/{trip}/locations",
        "GET /v1/iphone/trips/{trip}/music",
        "POST /v1/iphone/trips/{trip}/music/playlist",
        "PATCH /v1/iphone/trips/{trip}/music/playlist/{item}/position",
        "POST /v1/iphone/trips/{trip}/music/saved-playlists",
        "PATCH /v1/iphone/trips/{trip}/music/sharing",
        "GET /v1/iphone/trips/{trip}/results",
        "GET /v1/iphone/trips/{trip}/vehicle-remotes",
        "POST /v1/iphone/trips/{trip}/vehicle-remotes/{device}/commands",
        "GET /v1/iphone/trips/{trip}/voice-clips",
        "POST /v1/iphone/trips/{trip}/voice-clips",
        "GET /v1/iphone/trips/{trip}/voice-clips/{identifier}",
        "GET /v1/iphone/vehicles/{device}/functional-permissions",
        "PUT /v1/iphone/vehicles/{device}/functional-permissions",
        "GET /v1/iphone/vehicles/{device}/profile",
        "PUT /v1/iphone/vehicles/{device}/profile",
    ]

    private struct Row {
        let method: String
        let template: String
        let segments: [String?]
        let literals: Int
    }

    // 고정 구간이 많은 템플릿을 먼저 맞춰, 고정 경로가 매개변수 템플릿으로 풀리지 않게 한다.
    private static let rows: [Row] = all.map { entry in
        let parts = entry.split(separator: " ", maxSplits: 1).map(String.init)
        let segments: [String?] = parts[1].split(separator: "/", omittingEmptySubsequences: false).map { part in
            part.hasPrefix("{") && part.hasSuffix("}") ? nil : String(part)
        }
        return Row(method: parts[0], template: parts[1], segments: segments, literals: segments.compactMap { $0 }.count)
    }.sorted { $0.literals > $1.literals }

    /// 쿼리를 뺀 실제 경로의 템플릿. 서버가 마운트하지 않은 경로면 nil.
    static func match(method: String, path: String) -> String? {
        let route = path.split(separator: "?", maxSplits: 1, omittingEmptySubsequences: false).first.map(String.init) ?? path
        let parts = route.split(separator: "/", omittingEmptySubsequences: false).map(String.init)
        return rows.first { row in
            row.method == method && row.segments.count == parts.count &&
                zip(row.segments, parts).allSatisfy { expected, actual in expected.map { $0 == actual } ?? !actual.isEmpty }
        }?.template
    }
}

enum IPhoneNetResult: String {
    case ok, httpError = "http_error", networkError = "network_error", timeout, cancelled, invalidResponse = "invalid_response"
}

/// 요청 하나의 상관 ID. 같은 값이 X-Request-Id·traceparent와 서버 wegoh_access_v1 줄에 들어가 req_id로 이어진다.
final class IPhoneNetworkTrace {
    let method: String
    let route: String
    let reportable: Bool
    let requestID: String
    let traceID: String
    private let spanID: String
    private let started = DispatchTime.now().uptimeNanoseconds
    var status: Int?

    init(method: String, path: String) {
        self.method = method
        let full = "/v1/iphone/" + path
        if let template = IPhoneRouteTemplates.match(method: method, path: full) {
            route = template
            reportable = template != IPhoneClientDiagnostics.route
        } else {
            route = IPhoneNetworkLog.masked(full)
            reportable = false
        }
        requestID = IPhoneNetworkLog.randomHex(bytes: 16)
        traceID = IPhoneNetworkLog.randomHex(bytes: 16)
        spanID = IPhoneNetworkLog.randomHex(bytes: 8)
    }

    var traceparent: String { "00-\(traceID)-\(spanID)-00" }
    var elapsedMs: Int { Int(min((DispatchTime.now().uptimeNanoseconds - started) / 1_000_000, 600_000)) }

    /// ID는 요청마다 새로 만든 난수이며 계정·기기·토큰과 무관하다.
    var headers: [(String, String)] {
        [("X-Request-Id", requestID), ("traceparent", traceparent)] + (IPhoneNetworkLog.clientVersion.map { [("X-WegoH-Client", $0)] } ?? [])
    }

    func apply(to request: inout URLRequest) {
        for (name, value) in headers { request.setValue(value, forHTTPHeaderField: name) }
    }
}

enum IPhoneNetworkLog {
    private static let logger = Logger(subsystem: "io.wegoh.iphone", category: "network")
    private static let versionPattern = #"\A[0-9][0-9A-Za-z.+-]{0,31}\z"#

    /// 서버 X-WegoH-Client 형식 `ios/<CFBundleShortVersionString>+<CFBundleVersion>`. 괄호는 서버 형식에 없어 `+`로 잇는다.
    static let clientVersion: String? = clientValue(
        short: Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String,
        build: Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String)

    static func clientValue(short: String?, build: String?) -> String? {
        guard let short, let build else { return nil }
        let value = short + "+" + build
        return value.range(of: versionPattern, options: .regularExpression) == nil ? nil : "ios/" + value
    }

    static func randomHex(bytes: Int) -> String {
        while true {
            var generator = SystemRandomNumberGenerator()
            let value = (0..<bytes).map { _ in String(format: "%02x", UInt8.random(in: 0...255, using: &generator)) }.joined()
            if value.contains(where: { $0 != "0" }) { return value }
        }
    }

    /// 템플릿 표에 없는 경로: ID처럼 보이는 구간을 가린다.
    static func masked(_ path: String) -> String {
        let route = path.split(separator: "?", maxSplits: 1, omittingEmptySubsequences: false).first.map(String.init) ?? path
        return route.split(separator: "/", omittingEmptySubsequences: false).map { part in
            part.isEmpty || part == "v1" || part.range(of: #"\A[a-z]+(-[a-z]+)*\z"#, options: .regularExpression) != nil && part.count <= 40 ? String(part) : "{id}"
        }.joined(separator: "/")
    }

    static func line(_ trace: IPhoneNetworkTrace, result: IPhoneNetResult, reason: String,
                     decodePath: String? = nil, decodeRule: String? = nil) -> String {
        "net: req_id=\(trace.requestID) trace_id=\(trace.traceID) method=\(trace.method) route=\(trace.route) " +
            "status=\(trace.status ?? 0) dur_ms=\(trace.elapsedMs) result=\(result.rawValue) reason=\(reason)" +
            (decodePath.map { " decode_path=\($0) decode_rule=\(decodeRule ?? "unknown")" } ?? "")
    }

    /// 요청 하나에 한 줄. 서버가 이미 기록한 HTTP 오류는 다시 보고하지 않는다.
    static func finish(_ trace: IPhoneNetworkTrace, result: IPhoneNetResult, reason: String,
                       decodePath: String? = nil, decodeRule: String? = nil) {
        let text = line(trace, result: result, reason: reason, decodePath: decodePath, decodeRule: decodeRule)
        if result == .ok { logger.info("\(text, privacy: .public)") } else { logger.error("\(text, privacy: .public)") }
        guard trace.reportable, [IPhoneNetResult.networkError, .timeout, .invalidResponse].contains(result) else { return }
        IPhoneClientDiagnostics.shared.report(IPhoneClientDiagnosticEvent(
            kind: result.rawValue, method: trace.method, route: trace.route, requestId: trace.requestID,
            traceId: trace.traceID, status: trace.status, decodePath: decodePath, decodeRule: decodeRule,
            elapsedMs: trace.elapsedMs))
    }

    /// 오류 응답의 대문자 기계 코드만. 자유 문장 detail은 남기지 않는다.
    static func errorCode(_ http: HTTPURLResponse, data: Data) -> String {
        struct Failure: Decodable { let detail: String }
        guard http.mimeType == "application/json", data.count <= 4096,
              let detail = (try? JSONDecoder().decode(Failure.self, from: data))?.detail,
              detail.range(of: #"\A[A-Z][A-Z0-9_]{1,63}\z"#, options: .regularExpression) != nil else { return "status" }
        return detail
    }

    /// 응답을 받기 전에 실패한 요청.
    static func transportFailed(_ trace: IPhoneNetworkTrace, error: Error) {
        let code = (error as? URLError)?.code
        if code == .cancelled || error is CancellationError || Task.isCancelled {
            finish(trace, result: .cancelled, reason: "cancelled")
        } else if code == .timedOut {
            finish(trace, result: .timeout, reason: "URLError.timedOut")
        } else {
            finish(trace, result: .networkError, reason: code.map { "URLError.\($0.rawValue)" } ?? String(describing: type(of: error)))
        }
    }
}

/// 서버 POST /v1/iphone/diagnostics 형식의 보고 하나. 값·ID·본문은 담지 않는다.
struct IPhoneClientDiagnosticEvent: Encodable, Sendable {
    let kind: String
    let method: String
    let route: String
    let requestId: String
    let traceId: String
    let status: Int?
    let decodePath: String?
    let decodeRule: String?
    let elapsedMs: Int

    var key: String { "\(kind) \(method) \(route) \(status ?? 0) \(decodePath ?? "") \(decodeRule ?? "")" }
}

/// 보고를 모아 두었다가, 다음에 인증된 요청이 성공했을 때 그 토큰으로 묶어 보낸다.
/// 토큰을 보관하지 않고, 보내기 실패는 화면에 드러내지 않는다. 전달하지 못한 묶음만 다시 넣는다.
final class IPhoneClientDiagnostics: @unchecked Sendable {
    static let shared = IPhoneClientDiagnostics()
    static let route = "/v1/iphone/diagnostics"
    static let maxEvents = 20
    static let maxBytes = 8192
    private static let capacity = 40
    /// 서버 한도(계정당 분당 30회)보다 훨씬 낮게 30초에 한 번까지만 보낸다.
    private static let interval: TimeInterval = 30

    private let lock = NSLock()
    private var pending: [IPhoneClientDiagnosticEvent] = []
    private var keys: Set<String> = []
    private var sending = false
    private var lastSent = Date.distantPast
    private(set) var dropped = 0

    func report(_ event: IPhoneClientDiagnosticEvent) {
        lock.lock(); defer { lock.unlock() }
        guard !keys.contains(event.key), pending.count < Self.capacity else { dropped += 1; return }
        pending.append(event); keys.insert(event.key)
    }

    /// 보낼 묶음. 간격이 지나지 않았거나 다른 전송 중이면 nil.
    func takeDue(now: Date = Date()) -> [IPhoneClientDiagnosticEvent]? {
        lock.lock(); defer { lock.unlock() }
        guard !sending, !pending.isEmpty, now.timeIntervalSince(lastSent) >= Self.interval else { return nil }
        var batch: [IPhoneClientDiagnosticEvent] = []
        for event in pending {
            guard batch.count < Self.maxEvents, Self.body(batch + [event]).count <= Self.maxBytes else { break }
            batch.append(event)
        }
        pending.removeFirst(batch.count)
        batch.forEach { keys.remove($0.key) }
        sending = !batch.isEmpty
        lastSent = now
        return batch.isEmpty ? nil : batch
    }

    func finished(_ batch: [IPhoneClientDiagnosticEvent], delivered: Bool) {
        lock.lock(); defer { lock.unlock() }
        sending = false
        guard !delivered else { return }
        let kept = Array(batch.filter { !keys.contains($0.key) }.prefix(Self.capacity - pending.count))
        dropped += batch.count - kept.count
        pending.insert(contentsOf: kept, at: 0)
        kept.forEach { keys.insert($0.key) }
    }

    static func body(_ batch: [IPhoneClientDiagnosticEvent]) -> Data {
        struct Body: Encodable { let events: [IPhoneClientDiagnosticEvent] }
        return (try? JSONEncoder().encode(Body(events: batch))) ?? Data()
    }

    /// 인증된 요청이 성공한 직후 호출한다. 토큰은 이 전송에만 쓰고 보관하지 않는다.
    func sendIfDue(using api: IPhoneSessionAPI, token: String) {
        guard let batch = takeDue() else { return }
        Task.detached(priority: .utility) {
            do {
                _ = try await api.resource("diagnostics", method: "POST", payload: IPhoneClientDiagnostics.body(batch), token: token, status: 202)
                self.finished(batch, delivered: true)
            } catch IPhoneSessionError.unavailable {
                // 서버에 닿지 못한 묶음만 다음 기회에 다시 보낸다.
                self.finished(batch, delivered: false)
            } catch {
                self.finished(batch, delivered: true)
            }
        }
    }
}
