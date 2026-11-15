import Foundation
import XCTest
@testable import WegoH

private final class ProfileHTTPStub: URLProtocol {
    static var respond: ((URLRequest) throws -> (Int, [String: Any]))?
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func stopLoading() { }
    override func startLoading() {
        do {
            let (status, body) = try Self.respond!(request)
            let response = HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: nil,
                                           headerFields: ["Content-Type": "application/json"])!
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: try JSONSerialization.data(withJSONObject: body))
            client?.urlProtocolDidFinishLoading(self)
        } catch { client?.urlProtocol(self, didFailWithError: error) }
    }
}

final class IPhoneProfileTests: XCTestCase {
    override func tearDown() { ProfileHTTPStub.respond = nil; super.tearDown() }
    private var api: IPhoneProfileAPI {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [ProfileHTTPStub.self]
        return IPhoneProfileAPI(configuration: config)
    }
    private let token = String(repeating: "T", count: 43)
    private let device = String(repeating: "b", count: 32)

    func testValidationMatchesNameHandleAndPlateRules() {
        XCTAssertTrue(ProfileField.name.valid("나무"))
        for name in ["", " bad ", "hi\u{200B}", String(repeating: "가", count: 31)] { XCTAssertFalse(ProfileField.name.valid(name)) }
        XCTAssertEqual(ProfileField.handle.normalized(" @Hana_1 "), "hana_1")
        XCTAssertTrue(ProfileField.handle.valid("hana_1"))
        for handle in ["ab", "_abc", "한글123", "ABC", "a b"] { XCTAssertFalse(ProfileField.handle.valid(handle)) }
        XCTAssertTrue(ProfileField.plate.valid("123가4567"))
        XCTAssertTrue(ProfileField.plate.valid(""))
        for plate in ["가나다", "123가 4567", "AB123", "123가4567\n"] { XCTAssertFalse(ProfileField.plate.valid(plate)) }
        for name in ["", "출근 차", "주말 🚗 차", String(repeating: "가", count: 20)] { XCTAssertTrue(ProfileField.vehicleName.valid(name)) }
        for name in [" 출근 차", "출근 차 ", "출근\u{200B}차", "출근\u{2028}차", "출근\n차", String(repeating: "가", count: 21)] {
            XCTAssertFalse(ProfileField.vehicleName.valid(name))
        }
    }

    func testHandleInputAllowsSupportedCharactersAndPreservesOtherFields() {
        XCTAssertEqual(ProfileField.handle.filteredInput(" @Hana_한글.12 🐋\n"), "hana_.12")
        XCTAssertEqual(ProfileField.handle.filteredInput("ＡＢＣ１２３K"), "")
        XCTAssertTrue(ProfileField.handle.valid("hana123"))
        XCTAssertTrue(ProfileField.handle.valid(String(repeating: "a", count: 20)))
        for value in ["ab", "Hana123", "_hana", ".hana", "한글123", String(repeating: "a", count: 21)] {
            XCTAssertFalse(ProfileField.handle.valid(value))
        }
        XCTAssertTrue(ProfileField.handle.valid("hana_123"))
        XCTAssertTrue(ProfileField.handle.valid("hana.123"))
        XCTAssertEqual(ProfileField.name.filteredInput("하나 이름"), "하나 이름")
        XCTAssertEqual(ProfileField.plate.filteredInput("123가4567"), "123가4567")
    }

    func testWritesReuseBearerExpectedValuesAndNeverRestoreSession() async throws {
        let expectedDevice = device, expectedToken = token
        var paths: [String] = []
        ProfileHTTPStub.respond = { request in
            paths.append(request.url!.path)
            XCTAssertEqual(request.httpMethod, "PUT")
            XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer " + expectedToken)
            XCTAssertNil(request.value(forHTTPHeaderField: "Cookie"))
            let body = try Self.body(request)
            switch request.url!.path {
            case "/v1/iphone/profile":
                XCTAssertEqual(body["expectedDisplayName"] as? String, "이전 이름")
                return (200, ["user": ["displayName": "새 이름"]])
            case "/v1/iphone/profile/handle":
                XCTAssertEqual(body["expectedHandle"] as? String, "old_code")
                return (200, ["handle": "new_code"])
            default:
                XCTAssertEqual(request.url!.path, "/v1/iphone/vehicles/\(expectedDevice)/profile")
                let revision = body["expectedRevision"] as! Int
                return (200, ["deviceId": expectedDevice, "plateNumber": body["plateNumber"] as! String, "name": body["name"] as! String,
                              "defaultName": "새 이름의 차", "revision": revision + 1])
            }
        }
        let service = api
        let name = try await service.name("새 이름", expected: "이전 이름", token: token)
        let handle = try await service.handle("new_code", expected: "old_code", token: token)
        let vehicle = IPhoneVehicleProfile(deviceId: device, plateNumber: "", name: "출근 차", defaultName: "새 이름의 차", revision: 4)
        let plate = try await service.plate("123가4567", vehicle: vehicle, token: token)
        XCTAssertEqual(name, "새 이름"); XCTAssertEqual(handle, "new_code"); XCTAssertEqual(plate.revision, 5)
        XCTAssertEqual(plate.name, "출근 차", "A plate edit keeps the chosen vehicle name")
        let renamed = try await service.vehicleName("", vehicle: plate, token: token)
        XCTAssertEqual(renamed, IPhoneVehicleProfile(deviceId: device, plateNumber: "123가4567", name: "", defaultName: "새 이름의 차", revision: 6))
        XCTAssertEqual(renamed.displayName, "새 이름의 차")
        XCTAssertEqual(paths.count, 4)
    }

    func testConflictDoesNotRetryAndWrongVehicleResponseIsRejected() async throws {
        var calls = 0
        ProfileHTTPStub.respond = { _ in calls += 1; return (409, ["detail": "HANDLE_UNAVAILABLE"]) }
        do { _ = try await api.handle("new_code", expected: "old_code", token: token); XCTFail() }
        catch { if case IPhoneResourceError.conflict = error {} else { XCTFail("Expected conflict") } }
        XCTAssertEqual(calls, 1)
        ProfileHTTPStub.respond = { _ in (200, ["deviceId": String(repeating: "c", count: 32), "plateNumber": "123가4567", "name": "",
                                                "defaultName": "사용자F의 차", "revision": 1]) }
        let vehicle = IPhoneVehicleProfile(deviceId: device, plateNumber: "", name: "", defaultName: "사용자F의 차", revision: 0)
        do { _ = try await api.plate("123가4567", vehicle: vehicle, token: token); XCTFail() }
        catch { XCTAssertEqual(error as? IPhoneSessionError, .invalidResponse) }
    }

    private static func body(_ request: URLRequest) throws -> [String: Any] {
        var data = request.httpBody ?? Data()
        if let stream = request.httpBodyStream {
            stream.open(); defer { stream.close() }
            var bytes = [UInt8](repeating: 0, count: 1024)
            while stream.hasBytesAvailable {
                let count = stream.read(&bytes, maxLength: bytes.count)
                guard count > 0 else { break }
                data.append(contentsOf: bytes.prefix(count))
            }
        }
        return try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
    }
}
