import XCTest
@testable import WegoH

private final class PushHTTPStub: URLProtocol {
    static var requests: [URLRequest] = []
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func stopLoading() { }
    override func startLoading() {
        Self.requests.append(request)
        let response = HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil, headerFields: ["Content-Type": "application/json"])!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: Data((request.httpMethod == "DELETE" ? #"{"registered":false}"# : #"{"registered":true}"#).utf8))
        client?.urlProtocolDidFinishLoading(self)
    }
}

@MainActor final class IPhonePushNotificationTests: XCTestCase {
    private let account = "team-" + String(repeating: "a", count: 40)
    private let event = String(repeating: "b", count: 32)
    private let trip = String(repeating: "c", count: 32)

    func testFriendNotificationRoutesWithoutTripAndUnknownKindsAreRejected() {
        let info: [String: Any] = ["eventId": event, "accountId": account, "kind": "friend_request"]
        XCTAssertEqual(IPhonePushNotification(userInfo: ["wegoh": info])?.isFriendEvent, true)
        XCTAssertNil(IPhonePushNotification(userInfo: ["wegoh": info.merging(["kind": "remote_execute"], uniquingKeysWith: { _, new in new })]))
        XCTAssertNil(IPhonePushNotification(userInfo: ["wegoh": info.merging(["tripId": trip], uniquingKeysWith: { _, new in new })]))
    }

    func testTripPushRequiresValidTripEventAndRecipientAndNeverAcceptsAURL() {
        let info: [String: Any] = ["eventId": event, "accountId": account, "kind": "hand_raise_reaction", "tripId": trip]
        XCTAssertEqual(IPhonePushNotification(userInfo: ["wegoh": info])?.tripID, trip)
        for invalid in [["tripId": "https://example.com"], ["eventId": "../other"], ["accountId": "another-account"], ["tripId": ""]] {
            XCTAssertNil(IPhonePushNotification(userInfo: ["wegoh": info.merging(invalid, uniquingKeysWith: { _, new in new })]))
        }
        XCTAssertNil(IPhonePushNotification(userInfo: ["wegoh": info.filter { $0.key != "tripId" }]))
    }

    func testPushInstallAndDeleteUseAuthenticatedExactEndpointWithoutQueryTokens() async throws {
        PushHTTPStub.requests = []
        let config = URLSessionConfiguration.ephemeral; config.protocolClasses = [PushHTTPStub.self]
        let api = IPhonePushAPI(configuration: config)
        let installation = UUID().uuidString.lowercased()
        let token = String(repeating: "x", count: 43)
        try await api.register(installationID: installation, deviceToken: Data(repeating: 0xab, count: 32), environment: "sandbox", token: token)
        try await api.unregister(installationID: installation, token: token)
        XCTAssertEqual(PushHTTPStub.requests.map(\.httpMethod), ["PUT", "DELETE"])
        for request in PushHTTPStub.requests {
            XCTAssertEqual(request.url?.absoluteString, "https://ios-api-wegoh.devforest.io/v1/iphone/push/installation")
            XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer " + token)
        }
        let request = PushHTTPStub.requests[0]
        var data = request.httpBody
        if data == nil, let stream = request.httpBodyStream {
            stream.open(); defer { stream.close() }
            var bytes = [UInt8](repeating: 0, count: 2048)
            let count = stream.read(&bytes, maxLength: bytes.count)
            if count > 0 { data = Data(bytes.prefix(count)) }
        }
        let body = try XCTUnwrap(data).withUnsafeBytes { Data($0) }
        let fields = try XCTUnwrap(JSONSerialization.jsonObject(with: body) as? [String: String])
        XCTAssertEqual(fields["deviceToken"], String(repeating: "ab", count: 32))
        XCTAssertEqual(fields["environment"], "sandbox")
        XCTAssertEqual(fields["installationId"], installation)
    }

    func testInvalidInstallationOrTokenCannotReachTransport() async {
        PushHTTPStub.requests = []
        let config = URLSessionConfiguration.ephemeral; config.protocolClasses = [PushHTTPStub.self]
        let api = IPhonePushAPI(configuration: config)
        do {
            try await api.register(installationID: "not-a-uuid", deviceToken: Data(), environment: "production", token: String(repeating: "x", count: 43))
            XCTFail("Invalid registration must fail")
        } catch { }
        XCTAssertTrue(PushHTTPStub.requests.isEmpty)
    }
}
