#if DEBUG
import AuthenticationServices
import Darwin
import Foundation

enum LocalServerUIFixture {
    static let firstRunRequested = ProcessInfo.processInfo.arguments.contains("-wegoh-first-run-testing")
    static let requested = firstRunRequested || ProcessInfo.processInfo.arguments.contains("-wegoh-local-api-testing")
    static let firstRunSuite = "io.wegoh.iphone.uitesting.first-run"
    @MainActor static let firstRunStorage = makeFirstRunStorage(arguments: ProcessInfo.processInfo.arguments)
    private static let settings = loadSettings()

    @MainActor
    static func makeFirstRunStorage(arguments: [String]) -> UserDefaults? {
        guard arguments.contains("-wegoh-first-run-testing"), let storage = UserDefaults(suiteName: firstRunSuite)
        else { return nil }
        if arguments.contains("-wegoh-first-run-reset") { storage.removePersistentDomain(forName: firstRunSuite) }
        return storage
    }

    static func configure(_ configuration: URLSessionConfiguration) {
        if TripRouteUIFixture.requested {
            TripRouteUIFixture.configureDefaultTransport(configuration)
            return
        }
        guard requested else { return }
        configuration.protocolClasses = [LocalServerFixtureProtocol.self]
        configuration.httpShouldSetCookies = false
        configuration.httpCookieStorage = nil
        configuration.urlCredentialStorage = nil
        configuration.urlCache = nil
        configuration.requestCachePolicy = .reloadIgnoringLocalCacheData
    }

    @MainActor
    static func sessionIfRequested() -> SessionManager? {
        guard requested else { return nil }
        return makeSession(settings: firstRunRequested ? nil : settings)
    }

    @MainActor
    static func makeSession(settings: Settings?) -> SessionManager {
        return SessionManager(api: IPhoneSessionAPI(), browser: LocalBrowser(),
                              credentials: MemoryCredential(token: settings?.token))
    }

    static func forwarded(_ request: URLRequest) -> URLRequest? {
        guard requested, !firstRunRequested, let settings else { return nil }
        return forwarded(request, settings: settings)
    }

    static func forwarded(_ request: URLRequest, settings: Settings) -> URLRequest? {
        guard !firstRunRequested, let url = request.url, let original = URLComponents(url: url, resolvingAgainstBaseURL: false),
              original.scheme == "https", original.host == "ios-api-wegoh.devforest.io",
              original.port == nil, original.user == nil, original.password == nil, original.fragment == nil,
              original.path.hasPrefix("/v1/iphone/"),
              let authorization = request.value(forHTTPHeaderField: "Authorization"),
              authorization == "Bearer " + settings.token,
              request.value(forHTTPHeaderField: "Cookie") == nil,
              request.value(forHTTPHeaderField: "Cf-Access-Jwt-Assertion") == nil,
              var target = URLComponents(url: settings.origin, resolvingAgainstBaseURL: false),
              target.scheme == "http", target.host == "127.0.0.1",
              let port = target.port, (1024...65_535).contains(port),
              target.user == nil, target.password == nil, target.path.isEmpty,
              target.query == nil, target.fragment == nil
        else { return nil }
        target.percentEncodedPath = original.percentEncodedPath
        target.percentEncodedQuery = original.percentEncodedQuery
        guard let localURL = target.url else { return nil }
        var forwarded = request
        forwarded.url = localURL
        forwarded.httpShouldHandleCookies = false
        forwarded.cachePolicy = .reloadIgnoringLocalCacheData
        forwarded.setValue("ios-api-wegoh.devforest.io", forHTTPHeaderField: "Host")
        return forwarded
    }

    static let voiceProbeRequested = requested && ProcessInfo.processInfo.arguments.contains("-wegoh-voice-synthetic-input")

    static func forwardedVoice(_ request: URLRequest) -> URLRequest? {
        guard voiceProbeRequested, let settings, let url = request.url,
              var parts = URLComponents(url: url, resolvingAgainstBaseURL: false), parts.scheme == "wss",
              parts.path.hasSuffix("/voice"), parts.path.hasPrefix("/v1/iphone/trips/") else { return nil }
        parts.scheme = "https"
        var http = request; http.url = parts.url
        guard var forwarded = forwarded(http, settings: settings), let target = forwarded.url,
              var local = URLComponents(url: target, resolvingAgainstBaseURL: false) else { return nil }
        local.scheme = "ws"; forwarded.url = local.url
        return forwarded
    }

    static func voicePCM(_ captured: Data) -> Data {
        guard voiceProbeRequested else { return captured }
        var result = Data(capacity: 640)
        for index in 0..<320 {
            var value = Int16(sin(Double(index) * 2 * .pi * 600 / 16_000) * 3000).littleEndian
            withUnsafeBytes(of: &value) { result.append(contentsOf: $0) }
        }
        return result
    }

    static func voiceProbe(_ counters: [String: Int]) {
        guard voiceProbeRequested, let documents = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first,
              let data = try? JSONEncoder().encode(counters) else { return }
        let file = documents.appendingPathComponent("WegoHLocalQA/voice-result.json")
        try? data.write(to: file, options: .atomic)
        try? FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: file.path)
    }

    static func responseByteLimit(for request: URLRequest) -> Int {
        let path = request.url?.path ?? ""
        guard request.httpMethod == "GET" else { return 2_097_152 }
        if path == "/v1/iphone/courses/library" { return 16_777_216 }
        let segments = path.split(separator: "/")
        if segments.count == 8, segments[0...3].elementsEqual(["v1", "iphone", "courses", "public"]),
           segments[5] == "versions", segments[7] == "cover" { return 524_288 }
        return 2_097_152
    }

    struct Settings: Sendable {
        let origin: URL
        let token: String
    }

    static func validatedSettings(data: Data, actor: String? = nil) -> Settings? {
        struct Bootstrap: Decodable {
            struct Account: Decodable { let accessToken: String }
            let format: Int
            let synthetic: Bool
            let origin: String
            let localBaseURL: String
            let defaultActor: String
            let accounts: [String: Account]
        }
        guard data.count <= 65_536, let value = try? JSONDecoder().decode(Bootstrap.self, from: data),
              value.format == 1, value.synthetic,
              value.origin == "https://ios-api-wegoh.devforest.io",
              let parts = URLComponents(string: value.localBaseURL), parts.scheme == "http",
              parts.host == "127.0.0.1", let port = parts.port, (1024...65_535).contains(port),
              parts.path.isEmpty, parts.query == nil, parts.fragment == nil,
              parts.user == nil, parts.password == nil, let url = parts.url,
              let account = value.accounts[actor ?? value.defaultActor],
              account.accessToken.range(of: #"\A[A-Za-z0-9_-]{43}\z"#, options: .regularExpression) != nil
        else { return nil }
        return Settings(origin: url, token: account.accessToken)
    }

    private static func loadSettings() -> Settings? {
        guard requested, !firstRunRequested,
              let documents = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first
        else { return nil }
        let directory = documents.appendingPathComponent("WegoHLocalQA", isDirectory: true)
        let arguments = ProcessInfo.processInfo.arguments
        var actor: String?
        if let index = arguments.firstIndex(of: "-wegoh-local-api-actor") {
            guard arguments.indices.contains(index + 1) else { return nil }
            actor = arguments[index + 1]
        }
        return privateSettings(directory: directory, actor: actor)
    }

    static func privateSettings(directory: URL, actor: String? = nil) -> Settings? {
        let file = directory.appendingPathComponent("private-bootstrap.json", isDirectory: false)
        let manager = FileManager.default
        guard let directoryAttributes = try? manager.attributesOfItem(atPath: directory.path),
              directoryAttributes[.type] as? FileAttributeType == .typeDirectory,
              (directoryAttributes[.posixPermissions] as? NSNumber)?.intValue == 0o700,
              (directoryAttributes[.ownerAccountID] as? NSNumber)?.uint32Value == getuid(),
              let attributes = try? manager.attributesOfItem(atPath: file.path),
              attributes[.type] as? FileAttributeType == .typeRegular,
              (attributes[.posixPermissions] as? NSNumber)?.intValue == 0o600,
              (attributes[.ownerAccountID] as? NSNumber)?.uint32Value == getuid(),
              (attributes[.referenceCount] as? NSNumber)?.intValue == 1,
              let size = attributes[.size] as? NSNumber, size.intValue <= 65_536,
              let data = try? Data(contentsOf: file)
        else { return nil }
        return validatedSettings(data: data, actor: actor)
    }

    @MainActor
    private final class MemoryCredential: IPhoneCredentialStoring {
        private var value: StoredIPhoneCredential?
        private let allowedToken: String?

        init(token: String?) {
            allowedToken = token
            value = token.map { .init(token: $0, logoutPending: false) }
        }
        func load() throws -> StoredIPhoneCredential? { value }
        func saveToken(_ token: String) throws {
            guard token == allowedToken else { throw IPhoneSessionError.invalidSession }
            value = .init(token: token, logoutPending: false)
        }
        func markLogoutPending() throws { value = value.map { .init(token: $0.token, logoutPending: true) } }
        func clearToken() throws { value = nil }
    }

    @MainActor
    private final class LocalBrowser: IPhoneLoginBrowsing {
        func authenticate(url: URL, expiresAt: Date, state: String, anchor: ASPresentationAnchor) async throws -> URL {
            throw IPhoneSessionError.unavailable
        }
        func acceptIncomingURL(_ url: URL) { }
        func cancel() { }
    }
}

private final class LocalServerFixtureProtocol: URLProtocol, URLSessionDataDelegate, @unchecked Sendable {
    private let lock = NSLock()
    private var session: URLSession?
    private var pendingTask: URLSessionDataTask?
    private var stopped = false
    private var receivedBytes = 0

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        guard let forwarded = LocalServerUIFixture.forwarded(request) else {
            client?.urlProtocol(self, didFailWithError: URLError(.userAuthenticationRequired))
            return
        }
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = []
        configuration.httpShouldSetCookies = false
        configuration.httpCookieStorage = nil
        configuration.urlCredentialStorage = nil
        configuration.urlCache = nil
        configuration.requestCachePolicy = .reloadIgnoringLocalCacheData
        configuration.timeoutIntervalForRequest = 15
        configuration.timeoutIntervalForResource = 15
        let local = URLSession(configuration: configuration, delegate: self, delegateQueue: nil)
        let pending = local.dataTask(with: forwarded)
        let shouldStart = lock.withLock {
            guard !stopped else { return false }
            session = local
            pendingTask = pending
            return true
        }
        if shouldStart { pending.resume() }
        else { local.invalidateAndCancel() }
    }

    override func stopLoading() {
        let current = lock.withLock {
            stopped = true
            let value = session
            session = nil
            pendingTask = nil
            return value
        }
        current?.invalidateAndCancel()
    }

    func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive response: URLResponse,
                    completionHandler: @escaping (URLSession.ResponseDisposition) -> Void) {
        guard !lock.withLock({ stopped }), let http = response as? HTTPURLResponse,
              http.url?.host == "127.0.0.1", let original = request.url,
              let result = HTTPURLResponse(url: original, statusCode: http.statusCode, httpVersion: "HTTP/1.1",
                headerFields: http.allHeaderFields.reduce(into: [String: String]()) { headers, field in
                    guard let key = field.key as? String, key.lowercased() != "set-cookie" else { return }
                    headers[key] = String(describing: field.value)
                })
        else { completionHandler(.cancel); return }
        client?.urlProtocol(self, didReceive: result, cacheStoragePolicy: .notAllowed)
        completionHandler(.allow)
    }

    func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive data: Data) {
        let allowed = lock.withLock {
            guard !stopped else { return false }
            receivedBytes += data.count
            return receivedBytes <= LocalServerUIFixture.responseByteLimit(for: request)
        }
        guard allowed else { dataTask.cancel(); return }
        client?.urlProtocol(self, didLoad: data)
    }

    func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) {
        completionHandler(nil)
    }

    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        let deliver = lock.withLock {
            let value = !stopped
            stopped = true
            self.session = nil
            self.pendingTask = nil
            return value
        }
        defer { session.finishTasksAndInvalidate() }
        guard deliver else { return }
        if let error { client?.urlProtocol(self, didFailWithError: error) }
        else { client?.urlProtocolDidFinishLoading(self) }
    }
}
#endif
