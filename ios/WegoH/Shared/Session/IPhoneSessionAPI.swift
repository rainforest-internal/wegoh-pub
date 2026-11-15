import CryptoKit
import Foundation
import OSLog

protocol IPhoneSessionServing {
    func beginLogin() async throws -> IPhoneLoginAttempt
    func exchange(_ attempt: IPhoneLoginAttempt, callbackURL: URL) async throws -> IPhoneSessionReceipt
    func cancel(_ attempt: IPhoneLoginAttempt) async throws
    func restore(token: String) async throws -> AccountSession
    func logout(token: String) async throws
}

struct IPhoneLoginAttempt {
    let requestID: String
    let verifier: String
    let state: String
    let authorizationURL: URL
    let expiresAt: Date

    func approvalCode(from callback: URL) throws -> String {
        guard expiresAt > .now else { throw IPhoneSessionError.expired }
        guard let parts = URLComponents(url: callback, resolvingAgainstBaseURL: false),
              parts.scheme == "io.wegoh.iphone", parts.host == "login",
              parts.user == nil, parts.password == nil, parts.port == nil,
              parts.percentEncodedPath == "/callback", parts.fragment == nil,
              let items = parts.queryItems, items.count == 2,
              items.contains(URLQueryItem(name: "state", value: state)) else {
            throw IPhoneSessionError.invalidCallback
        }
        if items.contains(URLQueryItem(name: "error", value: "access_denied")) {
            throw IPhoneSessionError.denied
        }
        guard let code = items.first(where: { $0.name == "code" })?.value,
              isIPhoneNonce(code) else { throw IPhoneSessionError.invalidCallback }
        return code
    }
}

struct IPhoneSessionReceipt {
    let account: AccountSession
    let accessToken: String
}

enum IPhoneSessionError: Error, LocalizedError, Equatable {
    case invalidSession, denied, expired, invalidCallback, invalidResponse, invalidProof, used, pending, forbidden, unavailable
    case rateLimited(seconds: Int?)

    var errorDescription: String? {
        switch self {
        case .invalidSession: "로그인이 만료됐어요. 다시 로그인해 주세요."
        case .denied: "계정 연결이 승인되지 않았어요."
        case .expired: "로그인 요청 시간이 지났어요. 다시 시작해 주세요."
        case .invalidCallback, .invalidProof: "이 로그인 요청의 인증 결과를 확인할 수 없어요. 다시 시작해 주세요."
        case .used: "이미 처리한 로그인 요청이에요. 다시 시작해 주세요."
        case .pending: "계정 연결 승인이 아직 완료되지 않았어요."
        case .forbidden: "이 기능을 사용할 권한이 없어요."
        case .invalidResponse: "서버의 로그인 응답을 확인할 수 없어요."
        case .unavailable: "로그인 서버에 연결할 수 없어요. 잠시 후 다시 시도해 주세요."
        case .rateLimited(let seconds):
            if let seconds { "\(seconds)초 후에 다시 시도해 주세요." }
            else { "요청이 많아요. 잠시 후 다시 시도해 주세요." }
        }
    }
}

enum IPhoneResourceError: Error {
    case invalidInput, conflict, missing, unavailable, vehicleLimit
    case tripConflict(String)
}

private func isIPhoneNonce(_ value: String) -> Bool {
    value.utf8.count == 43 && value.range(of: #"\A[A-Za-z0-9_-]{43}\z"#, options: .regularExpression) != nil
}

/// 여행 리모컨 전송(`POST trips/{trip}/vehicle-remotes/{device}/commands`)에서 서버가 대상 차량을 확인하다 실패한 사유.
/// 서버는 차량의 명령 수신 목적이 없으면 403 `FUNCTIONAL_PURPOSE_REQUIRED`, 차량 연결이 유효하지 않으면
/// 404 `DEVICE_UNAVAILABLE`을 돌려준다(friend_vehicle_controls.trip_grant → resolve_current_device).
/// 이 경로의 두 detail은 요청자의 권한이 아니라 차량 상태이므로 권한 상실과 구분한다.
func tripRemoteReceiverReason(path: String, method: String, status: Int, data: Data) -> String? {
    struct Failure: Decodable { let detail: String }
    let parts = path.split(separator: "/", omittingEmptySubsequences: false)
    guard method == "POST", parts.count == 5, parts[0] == "trips", parts[2] == "vehicle-remotes", parts[4] == "commands",
          let detail = (try? JSONDecoder().decode(Failure.self, from: data))?.detail else { return nil }
    switch (status, detail) {
    case (403, "FUNCTIONAL_PURPOSE_REQUIRED"): return "VEHICLE_REMOTE_RECEIVER_OFF"
    case (404, "DEVICE_UNAVAILABLE"): return "VEHICLE_REMOTE_DISCONNECTED"
    default: return nil
    }
}

private final class IPhoneSessionDelegate: NSObject, URLSessionTaskDelegate {
    func urlSession(_ session: URLSession, task: URLSessionTask,
                    willPerformHTTPRedirection response: HTTPURLResponse, newRequest request: URLRequest,
                    completionHandler: @escaping (URLRequest?) -> Void) {
        completionHandler(nil)
    }
}

final class IPhoneSessionAPI: IPhoneSessionServing {
    private static let baseURL = URL(string: "https://ios-api-wegoh.devforest.io/v1/iphone")!
    /// 기본 앱 요청이 함께 쓰는 전송 계층. 같은 API 호스트로 가는 요청이 TCP/TLS 연결을 재사용한다.
    static let sharedSession = makeSession(.ephemeral)
    let session: URLSession
    private let ownsSession: Bool

    /// `configuration`을 주지 않으면 앱 공용 세션을 쓴다. 디버그 픽스처·테스트처럼 별도 전송이 필요할 때만 주입한다.
    init(configuration: URLSessionConfiguration? = nil) {
        if let configuration {
            session = Self.makeSession(configuration)
            ownsSession = true
        } else {
            session = Self.sharedSession
            ownsSession = false
        }
    }

    deinit { if ownsSession { session.invalidateAndCancel() } }

    private static func makeSession(_ configuration: URLSessionConfiguration) -> URLSession {
        #if DEBUG
        LocalServerUIFixture.configure(configuration)
        #endif
        configuration.httpShouldSetCookies = false
        configuration.httpCookieStorage = nil
        configuration.urlCredentialStorage = nil
        configuration.urlCache = nil
        configuration.timeoutIntervalForResource = 15
        return URLSession(configuration: configuration, delegate: IPhoneSessionDelegate(), delegateQueue: nil)
    }

    func beginLogin() async throws -> IPhoneLoginAttempt {
        func nonce() -> String {
            SymmetricKey(size: .bits256).withUnsafeBytes { base64URL(Data($0)) }
        }
        let verifier = nonce()
        let state = nonce()
        let challenge = base64URL(Data(SHA256.hash(data: Data(verifier.utf8))))
        let data = try await request("login/requests", method: "POST", fields: ["codeChallenge": challenge, "state": state], status: 201)
        let start = try decode(LoginRequest.self, from: data)
        guard start.requestId.range(of: #"\A[0-9a-f]{32}\z"#, options: .regularExpression) != nil,
              start.authorizationUrl == "https://wegoh.devforest.io/iphone-login?request_id=\(start.requestId)",
              let url = URL(string: start.authorizationUrl) else { throw IPhoneSessionError.invalidResponse }
        let expiry = Date(timeIntervalSince1970: TimeInterval(start.expiresAt))
        guard expiry > .now else { throw IPhoneSessionError.expired }
        return IPhoneLoginAttempt(requestID: start.requestId, verifier: verifier, state: state, authorizationURL: url, expiresAt: expiry)
    }

    func exchange(_ attempt: IPhoneLoginAttempt, callbackURL: URL) async throws -> IPhoneSessionReceipt {
        let code = try attempt.approvalCode(from: callbackURL)
        let fields = ["requestId": attempt.requestID, "codeVerifier": attempt.verifier, "code": code]
        let data = try await request("login/exchange", method: "POST", fields: fields, status: 200)
        let view = try decode(SessionView.self, from: data)
        guard view.tokenType == "Bearer", let token = view.accessToken, isIPhoneNonce(token) else {
            throw IPhoneSessionError.invalidResponse
        }
        return IPhoneSessionReceipt(account: try view.account(), accessToken: token)
    }

    func cancel(_ attempt: IPhoneLoginAttempt) async throws {
        _ = try await request("login/cancel", method: "POST", fields: ["requestId": attempt.requestID, "codeVerifier": attempt.verifier], status: 204)
    }

    func restore(token: String) async throws -> AccountSession {
        let data = try await request("session", method: "GET", token: token, status: 200)
        return try decode(SessionView.self, from: data).account()
    }

    func logout(token: String) async throws {
        _ = try await request("session", method: "DELETE", token: token, status: 204)
    }

    func resource(_ path: String, method: String = "GET", payload: Data? = nil,
                  token: String, status: Int = 200, alternateStatus: Int? = nil) async throws -> Data {
        try await request(path, method: method, token: token, status: status,
                          payload: payload, alternateStatus: alternateStatus, resource: true)
    }

    func courseCover(_ id: String, version: Int, token: String) async throws -> Data {
        guard validCourseID(id), (1...Int(Int32.max)).contains(version) else { throw IPhoneResourceError.invalidInput }
        return try await request("courses/public/\(id)/versions/\(version)/cover", method: "GET", token: token,
                                 status: 200, resource: true, image: true)
    }

    private func request(_ path: String, method: String, fields: [String: String]? = nil,
                         token: String? = nil, status: Int, payload: Data? = nil,
                         alternateStatus: Int? = nil, resource: Bool = false, image: Bool = false) async throws -> Data {
        guard let url = URL(string: Self.baseURL.absoluteString + "/" + path),
              url.scheme == Self.baseURL.scheme, url.host == Self.baseURL.host,
              url.port == nil, url.user == nil, url.password == nil,
              url.fragment == nil, url.path.hasPrefix("/v1/iphone/") else { throw IPhoneSessionError.invalidResponse }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.setValue(image ? "image/jpeg" : "application/json", forHTTPHeaderField: "Accept")
        if let fields {
            request.httpBody = try JSONEncoder().encode(fields)
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        if let payload {
            request.httpBody = payload
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        if let token {
            guard isIPhoneNonce(token) else { throw IPhoneSessionError.invalidSession }
            request.setValue("Bearer " + token, forHTTPHeaderField: "Authorization")
        }
        let trace = IPhoneNetworkTrace(method: method, path: path)
        trace.apply(to: &request)
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: request)
        } catch {
            IPhoneNetworkLog.transportFailed(trace, error: error)
            try Task.checkCancellation()
            throw IPhoneSessionError.unavailable
        }
        guard let http = response as? HTTPURLResponse, http.url == url else {
            IPhoneNetworkLog.finish(trace, result: .invalidResponse, reason: "response_url", decodePath: "$", decodeRule: "unknown")
            throw IPhoneSessionError.invalidResponse
        }
        trace.status = http.statusCode
        let library = resource && method == "GET" && path.split(separator: "?", maxSplits: 1).first == "courses/library"
        guard data.count <= (image ? 524_288 : library ? 16_777_216 : 2_097_152) else {
            IPhoneNetworkLog.finish(trace, result: .invalidResponse, reason: "too_large", decodePath: "$", decodeRule: "length")
            throw IPhoneSessionError.invalidResponse
        }
        guard http.statusCode == status || http.statusCode == alternateStatus else {
            IPhoneNetworkLog.finish(trace, result: .httpError, reason: IPhoneNetworkLog.errorCode(http, data: data))
            if resource {
                switch http.statusCode {
                case 400: throw IPhoneResourceError.invalidInput
                case 403:
                    // 여행 리모컨 전송에서 차량의 '리모컨 받기'(명령 수신 목적)가 꺼진 상태. 동승자의 권한 상실이 아니다.
                    if let reason = tripRemoteReceiverReason(path: path, method: method, status: 403, data: data) {
                        throw IPhoneResourceError.tripConflict(reason)
                    }
                    throw IPhoneSessionError.forbidden
                case 404:
                    struct Failure: Decodable { let detail: String }
                    // 여행 리모컨 전송 대상 차량의 연결(차량 앱 로그인)이 현재 유효하지 않은 상태.
                    if let reason = tripRemoteReceiverReason(path: path, method: method, status: 404, data: data) {
                        throw IPhoneResourceError.tripConflict(reason)
                    }
                    let parts = path.split(separator: "/")
                    if method == "POST", parts.count == 3, parts[0] == "trips", validTripID(String(parts[1])), parts[2] == "members",
                       let failure = try? JSONDecoder().decode(Failure.self, from: data), failure.detail == "Account unavailable" {
                        throw IPhoneResourceError.tripConflict(failure.detail)
                    }
                    throw IPhoneResourceError.missing
                case 409:
                    struct Failure: Decodable { let detail: String }
                    let failure = try? JSONDecoder().decode(Failure.self, from: data)
                    if failure?.detail == "VEHICLE_CONNECTION_LIMIT" { throw IPhoneResourceError.vehicleLimit }
                    let tripCodes = ["TRIP_ROUTE_PLAN_LOCKED", "TRIP_PLACE_SELECTION_CHANGED", "TRIP_REVISION_CONFLICT",
                        "TRIP_ROUTE_PROGRESS_CHANGED", "TRIP_ROUTE_CONTRACT_REQUIRED",
                        "TRIP_SIGNAL_JOIN_PENDING", "TRIP_SIGNAL_SHARED_FINISHED", "TRIP_SIGNAL_ROUTE_FINISHED", "TRIP_SIGNAL_CAR_REQUIRED", "DRIVING_SCORE_PHASE_CONFLICT",
                        "TRIP_STATE_CONFLICT", "TRIP_CONTEXT_NOT_READY", "TRIP_MEMBERSHIP_INCONSISTENT", "TRIP_MEMBERSHIP_CONFLICT",
                        "Vehicle owner required", "Already driving", "Seats taken", "Car is full", "Trip is full",
                        "Trip limit reached", "Trip course limit", "Route revision conflict",
                        "Choose a vehicle for remote control", "No vehicle ready for remote control"]
                    let isTrip = path == "trips" || path.hasPrefix("trips/")
                    let tripReason = failure.flatMap { isTrip && tripCodes.contains($0.detail) ? $0.detail : nil }
                    #if DEBUG
                    let reason = tripReason?.replacingOccurrences(of: " ", with: "_").uppercased() ?? "UNCLASSIFIED_CONFLICT"
                    let operation = path.hasSuffix("/respond") ? "trip.respond" : isTrip ? "trip.resource" : "resource.request"
                    Logger(subsystem: "io.wegoh.iphone", category: "api-request")
                        .error("iphone.request: failed operation=\(operation, privacy: .public) method=\(method, privacy: .public) status=409 reason=\(reason, privacy: .public)")
                    #endif
                    if let tripReason { throw IPhoneResourceError.tripConflict(tripReason) }
                    throw IPhoneResourceError.conflict
                case 422:
                    struct Failure: Decodable { let detail: String }
                    let supportedReasons = ["VEHICLE_CONTROL_UNSUPPORTED", "VEHICLE_CONTROL_AREA_UNSUPPORTED", "VEHICLE_CONTROL_VALUE_UNSUPPORTED"]
                    if method == "POST", path.hasPrefix("trips/"), path.contains("/vehicle-remotes/"), path.hasSuffix("/commands"),
                       let failure = try? JSONDecoder().decode(Failure.self, from: data), supportedReasons.contains(failure.detail) {
                        throw IPhoneResourceError.tripConflict(failure.detail)
                    }
                case 410: throw IPhoneSessionError.expired
                case 500...599: throw IPhoneResourceError.unavailable
                default: break
                }
            }
            throw error(for: http, data: data)
        }
        let declaredType = http.value(forHTTPHeaderField: "Content-Type")?
            .split(separator: ";", maxSplits: 1).first?.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        guard status == 204 || (http.mimeType == (image ? "image/jpeg" : "application/json")
                                && (!image || declaredType == "image/jpeg")) else {
            IPhoneNetworkLog.finish(trace, result: .invalidResponse, reason: "content_type", decodePath: "$", decodeRule: "format")
            throw IPhoneSessionError.invalidResponse
        }
        IPhoneNetworkLog.finish(trace, result: .ok, reason: "none")
        // 이 요청이 통한 토큰으로 밀린 실패 보고를 보낸다. 로그아웃·보고 자체와 주입한 시험·픽스처 전송에는 붙이지 않는다.
        if !ownsSession, let token, path != "diagnostics", !(path == "session" && method == "DELETE") {
            IPhoneClientDiagnostics.shared.sendIfDue(using: self, token: token)
        }
        return data
    }

    private func error(for http: HTTPURLResponse, data: Data) -> IPhoneSessionError {
        struct ErrorBody: Decodable { let detail: String }
        let detail = http.mimeType == "application/json" ? (try? JSONDecoder().decode(ErrorBody.self, from: data))?.detail : nil
        switch (http.statusCode, detail) {
        case (401, "IPHONE_SESSION_REQUIRED"), (401, "IPHONE_SESSION_EXPIRED"), (401, "IPHONE_SESSION_REVOKED"): return .invalidSession
        case (401, "IPHONE_INVALID_PROOF"): return .invalidProof
        case (403, "IPHONE_LOGIN_DENIED"): return .denied
        case (403, "IPHONE_SCOPE_DENIED"): return .forbidden
        case (404, "IPHONE_LOGIN_NOT_FOUND"), (410, "IPHONE_LOGIN_EXPIRED"): return .expired
        case (409, "IPHONE_LOGIN_USED"): return .used
        case (409, "IPHONE_LOGIN_PENDING"): return .pending
        case (429, _):
            let seconds = http.value(forHTTPHeaderField: "Retry-After").flatMap(Int.init)
            return .rateLimited(seconds: seconds.flatMap { $0 >= 0 ? $0 : nil })
        case (408, _), (500...599, _): return .unavailable
        default: return .invalidResponse
        }
    }

    private func decode<T: Decodable>(_ type: T.Type, from data: Data) throws -> T {
        do { return try JSONDecoder().decode(type, from: data) }
        catch { throw IPhoneSessionError.invalidResponse }
    }

    private func base64URL(_ data: Data) -> String {
        data.base64EncodedString().replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_").replacingOccurrences(of: "=", with: "")
    }

    private struct LoginRequest: Decodable {
        let requestId: String
        let authorizationUrl: String
        let expiresAt: Int64
    }

    private struct SessionView: Decodable {
        struct User: Decodable {
            let id: String
            let displayName: String
        }
        let user: User
        let scopes: [String]
        let expiresAt: Int64
        let tokenType: String?
        let accessToken: String?

        func account() throws -> AccountSession {
            let expiry = Date(timeIntervalSince1970: TimeInterval(expiresAt))
            guard user.id.range(of: #"\Ateam-[0-9a-f]{40}\z"#, options: .regularExpression) != nil,
                  !user.displayName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
                  scopes.contains("account:read"), expiry > .now else {
                throw IPhoneSessionError.invalidResponse
            }
            return AccountSession(accountID: user.id, displayName: user.displayName, expiresAt: expiry, scopes: Set(scopes))
        }
    }
}
