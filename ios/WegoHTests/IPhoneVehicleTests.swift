import Foundation
import XCTest
@testable import WegoH

private final class VehicleHTTPStub: URLProtocol {
    static var respond: ((URLRequest) throws -> (Int, [String: Any]))?
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        do {
            let (status, object) = try XCTUnwrap(Self.respond)(request)
            let response = try XCTUnwrap(HTTPURLResponse(url: XCTUnwrap(request.url), statusCode: status,
                httpVersion: "HTTP/1.1", headerFields: ["Content-Type": "application/json"]))
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: try JSONSerialization.data(withJSONObject: object))
            client?.urlProtocolDidFinishLoading(self)
        } catch { client?.urlProtocol(self, didFailWithError: error) }
    }
    override func stopLoading() {}
}

final class IPhoneVehicleTests: XCTestCase {
    private let token = String(repeating: "a", count: 43)
    private let code = "DEMA2345"

    override func tearDown() {
        VehicleHTTPStub.respond = nil
        super.tearDown()
    }

    private func api() -> IPhoneVehicleAPI {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [VehicleHTTPStub.self]
        return IPhoneVehicleAPI(transport: IPhoneSessionAPI(configuration: config))
    }

    private func fixture() throws -> [String: Any] {
        let url = try XCTUnwrap(Bundle(for: Self.self).url(forResource: "vehicle-connection", withExtension: "json"))
        var object = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(contentsOf: url)) as? [String: Any])
        object["expiresAt"] = Int(Date.now.timeIntervalSince1970) + 300
        return object
    }

    private func body(_ request: URLRequest) throws -> [String: Any] {
        var data = request.httpBody ?? Data()
        if data.isEmpty, let stream = request.httpBodyStream {
            stream.open()
            defer { stream.close() }
            var bytes = [UInt8](repeating: 0, count: 1024)
            while stream.hasBytesAvailable {
                let count = stream.read(&bytes, maxLength: bytes.count)
                guard count > 0 else { break }
                data.append(contentsOf: bytes.prefix(count))
            }
        }
        return try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
    }

    func testCodeAndQRCodeUseSameStrictComparisonCode() {
        XCTAssertEqual(VehicleQR.inputCode(" dema-2345\n"), code)
        XCTAssertEqual(VehicleQR.comparisonCode(in: "https://wegoh.devforest.io/enroll.html?user_code=DEMA2345"), code)
        for value in ["", "DEMA234", "DEMA23456", "DEMA2340", "ＤＥＭＡ2345", "DEMA/2345"] {
            XCTAssertNil(VehicleQR.inputCode(value), value)
        }
        for value in ["https://evil.invalid/enroll.html?user_code=DEMA2345",
                      "https://wegoh.devforest.io/enroll.html?user_code=DEMA2345&x=1",
                      "https://wegoh.devforest.io/enroll.html?user_code=DEMA2345#x"] {
            XCTAssertNil(VehicleQR.comparisonCode(in: value))
        }
    }

    func testLinkFinishesOnlyWhenANewVehicleAppearsAfterApproval() {
        let old = LinkedVehicle(id: String(repeating: "a", count: 32), name: "기존 차", expiresAt: "2026-12-01T00:00:00Z", authorizationVersion: 1)
        let new = LinkedVehicle(id: String(repeating: "b", count: 32), name: "새 차", expiresAt: "2026-12-01T00:00:00Z", authorizationVersion: 1)
        XCTAssertFalse(VehicleLinkView.vehicleFinishedLink([], known: []))
        XCTAssertFalse(VehicleLinkView.vehicleFinishedLink([old], known: [old.id]))
        XCTAssertTrue(VehicleLinkView.vehicleFinishedLink([new], known: [old.id]))
        XCTAssertTrue(VehicleLinkView.vehicleFinishedLink([new], known: []))
    }

    func testBothInputMethodsOnlyReadSameAuthenticatedConnection() async throws {
        let object = try fixture()
        var requests = 0
        VehicleHTTPStub.respond = { [self] request in
            requests += 1
            XCTAssertEqual(request.httpMethod, "GET")
            XCTAssertEqual(request.url?.absoluteString, "https://ios-api-wegoh.devforest.io/v1/iphone/connections/DEMA2345")
            XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer " + token)
            XCTAssertNil(request.value(forHTTPHeaderField: "Cookie"))
            return (200, object)
        }
        for value in [VehicleQR.inputCode("dema 2345"), VehicleQR.comparisonCode(in: "https://wegoh.devforest.io/enroll.html?user_code=DEMA2345")] {
            let detail = try await api().connection(code: XCTUnwrap(value), token: token)
            XCTAssertEqual(detail.deviceName, "코드 연동 시험 차량")
            XCTAssertEqual(detail.initialScopes, ["account:read", "device:self:manage", "courses:read", "playlists:read"])
            XCTAssertFalse(detail.keepSignedInDefault)
        }
        XCTAssertEqual(requests, 2)
    }

    func testApprovalSendsOnlyExplicitChoicesAndReviewedDisclosure() async throws {
        let object = try fixture()
        var posts = 0
        VehicleHTTPStub.respond = { [self] request in
            if request.httpMethod == "GET" { return (200, object) }
            posts += 1
            XCTAssertEqual(request.httpMethod, "POST")
            let payload = try body(request)
            XCTAssertEqual(Set(payload.keys), ["authorizationVersion", "consentVersion", "approvedScopes", "keepSignedIn", "disclosureVersion", "disclosureSha256"])
            XCTAssertEqual(payload["approvedScopes"] as? [String], ["account:read", "courses:read", "device:self:manage"])
            XCTAssertEqual(payload["keepSignedIn"] as? Bool, false)
            XCTAssertEqual(payload["disclosureSha256"] as? String, (object["disclosureSnapshot"] as? [String: Any])?["disclosureSha256"] as? String)
            return (200, ["authorizationVersion": 1, "state": "APPROVED", "userCode": code, "expiresAt": object["expiresAt"]!])
        }
        let client = api()
        let detail = try await client.connection(code: code, token: token)
        try await client.approve(detail, scopes: ["account:read", "device:self:manage", "courses:read"], keepSignedIn: false, token: token)
        XCTAssertEqual(posts, 1)
    }

    func testChangedDisclosureAndMismatchedCodeCannotReachApproval() async throws {
        for mutation in ["hash", "code", "version"] {
            var object = try fixture()
            if mutation == "hash" {
                var snapshot = try XCTUnwrap(object["disclosureSnapshot"] as? [String: Any])
                snapshot["keepSignedInDisclosure"] = "changed"
                object["disclosureSnapshot"] = snapshot
            } else if mutation == "code" { object["userCode"] = "AAAA2345" }
            else { object["authorizationVersion"] = 2 }
            VehicleHTTPStub.respond = { request in
                XCTAssertEqual(request.httpMethod, "GET")
                return (200, object)
            }
            do { _ = try await api().connection(code: code, token: token); XCTFail(mutation) }
            catch is VehicleLinkError {}
        }
    }

    func testExpiredAndUnknownCodesHaveRecoverableErrors() async throws {
        for status in [404, 410] {
            VehicleHTTPStub.respond = { _ in (status, ["detail": status == 410 ? "AUTHORIZATION_EXPIRED" : "OPERATION_NOT_FOUND"]) }
            do { _ = try await api().connection(code: code, token: token); XCTFail() }
            catch VehicleLinkError.unavailableCode {}
        }
    }

    func testApprovalConflictIsNotAutomaticallyRetried() async throws {
        let object = try fixture()
        var posts = 0
        VehicleHTTPStub.respond = { request in
            if request.httpMethod == "GET" { return (200, object) }
            posts += 1
            return (409, ["detail": "OPERATION_CONFLICT"])
        }
        let client = api()
        let detail = try await client.connection(code: code, token: token)
        do { try await client.approve(detail, scopes: detail.initialScopes, keepSignedIn: false, token: token); XCTFail() }
        catch VehicleLinkError.changed {}
        XCTAssertEqual(posts, 1)
    }

    func testSecondVehicleLimitHasSpecificGuidanceAndDoesNotRetry() async throws {
        let object = try fixture()
        var posts = 0
        VehicleHTTPStub.respond = { request in
            if request.httpMethod == "GET" { return (200, object) }
            posts += 1
            return (409, ["detail": "VEHICLE_CONNECTION_LIMIT"])
        }
        let client = api()
        let detail = try await client.connection(code: code, token: token)
        do { try await client.approve(detail, scopes: detail.initialScopes, keepSignedIn: false, token: token); XCTFail() }
        catch VehicleLinkError.limit {}
        XCTAssertEqual(posts, 1)
    }

    func testListingAndRevocationTargetOnlySelectedDevice() async throws {
        let first = String(repeating: "1", count: 32), second = String(repeating: "2", count: 32)
        VehicleHTTPStub.respond = { request in
            if request.httpMethod == "GET" {
                return (200, ["devices": [first, second].map { ["id": $0, "name": "시험 차량", "expiresAt": "2026-11-19T10:00:00Z", "authorizationVersion": 1] }])
            }
            XCTAssertEqual(request.httpMethod, "DELETE")
            XCTAssertEqual(request.url?.path, "/v1/iphone/vehicles/" + second)
            return (200, ["status": "revoked"])
        }
        let client = api()
        let devices = try await client.vehicles(token: token)
        XCTAssertEqual(devices.count, 2)
        try await client.revoke(devices[1], token: token)
    }
}
