import Foundation
import XCTest
@testable import WegoH

private final class FunctionalPermissionsHTTPStub: URLProtocol {
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

final class VehicleFunctionalPermissionsTests: XCTestCase {
    private let device = String(repeating: "b", count: 32)
    private let scorePurpose = "driving-score:report"
    private let token = String(repeating: "a", count: 43)
    private let bodyKeys: Set<String> = ["authorizationVersion", "grantId", "revision", "approvedPurposes", "functionalDisclosureVersion", "functionalDisclosureSha256"]

    override func tearDown() {
        FunctionalPermissionsHTTPStub.respond = nil
        super.tearDown()
    }
    private func snapshot(_ name: String = "functional-permissions") throws -> VehicleFunctionalSnapshot {
        let url = try XCTUnwrap(Bundle(for: Self.self).url(forResource: name, withExtension: "json"))
        return try JSONDecoder().decode(VehicleFunctionalSnapshot.self, from: Data(contentsOf: url))
    }
    private func object(_ value: VehicleFunctionalSnapshot) throws -> [String: Any] {
        try XCTUnwrap(JSONSerialization.jsonObject(with: JSONEncoder().encode(value)) as? [String: Any])
    }
    private func api() -> IPhoneVehicleFunctionalAPI {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [FunctionalPermissionsHTTPStub.self]
        return IPhoneVehicleFunctionalAPI(configuration: configuration)
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
    func testNewScorePurposeRemainsOffUntilExplicitSelectionAndUsesClosedBody() throws {
        let snapshot = try snapshot()
        try snapshot.validate(deviceID: device)
        let original = Set(snapshot.authorization.approvedPurposes)
        XCTAssertFalse(original.contains("driving-score:report"))
        let retained = try XCTUnwrap(JSONSerialization.jsonObject(with: snapshot.payload(approved: original)) as? [String: Any])
        XCTAssertEqual(retained["approvedPurposes"] as? [String], original.sorted())
        let selected = original.union(["driving-score:report"])
        let body = try XCTUnwrap(JSONSerialization.jsonObject(with: snapshot.payload(approved: selected)) as? [String: Any])
        XCTAssertEqual(Set(body.keys), ["authorizationVersion", "grantId", "revision", "approvedPurposes", "functionalDisclosureVersion", "functionalDisclosureSha256"])
        XCTAssertEqual(body["functionalDisclosureVersion"] as? Int, 3)
        XCTAssertEqual(body["revision"] as? Int, 2)
        XCTAssertEqual(body["approvedPurposes"] as? [String], selected.sorted())
    }
    func testChangedDisclosureHashAndReadOnlyPurposesCannotBeSaved() throws {
        var snapshot = try snapshot()
        snapshot.disclosure.purposes[0].purpose += "변경"
        XCTAssertThrowsError(try snapshot.validate(deviceID: device))
        snapshot = try self.snapshot()
        let removed = Set(snapshot.authorization.approvedPurposes).subtracting(["rooms:read"])
        XCTAssertThrowsError(try snapshot.payload(approved: removed))
        let unexpected = Set(snapshot.authorization.approvedPurposes).union(["unknown:purpose"])
        XCTAssertThrowsError(try snapshot.payload(approved: unexpected))
    }

    func testFrozenV4StillLoadsWithoutAuthorizingTheNewTripScoreScope() throws {
        var value = try snapshot("functional-permissions-v4")
        value.approvedDisclosureVersion = 4
        value.authorization.approvedPurposes.append(scorePurpose)
        value.authorization.approvedPurposes.sort()
        try value.validate(deviceID: device)
        XCTAssertFalse(value.hasApprovedCurrentScoreSharing)
    }

    func testFrozenV3StillLoadsWithoutAnApprovalMarker() throws {
        let snapshot = try snapshot()
        try snapshot.validate(deviceID: device)
        XCTAssertEqual(snapshot.disclosure.version, 3)
        XCTAssertEqual(snapshot.disclosure.sha256, "74e93e6fb3b374e627b572fe0a49de390fd276074a004f00a9ffac470964fe92")
        XCTAssertNil(snapshot.approvedDisclosureVersion)
        XCTAssertFalse(snapshot.hasApprovedCurrentScoreSharing)
    }

    func testCurrentSharingRequiresOriginalV5ApprovalAndApprovedScorePurpose() throws {
        var snapshot = try snapshot("functional-permissions-v5")
        snapshot.authorization.approvedPurposes.append(scorePurpose)
        snapshot.authorization.approvedPurposes.sort()
        for marker in [nil, 1, 2, 3, 4] as [Int?] {
            snapshot.approvedDisclosureVersion = marker
            try snapshot.validate(deviceID: device)
            XCTAssertFalse(snapshot.hasApprovedCurrentScoreSharing)
            XCTAssertEqual(snapshot.authorization.functionalDisclosureVersion, 5)
        }
        snapshot.approvedDisclosureVersion = 5
        try snapshot.validate(deviceID: device)
        XCTAssertTrue(snapshot.hasApprovedCurrentScoreSharing)
        snapshot.authorization.approvedPurposes.removeAll { $0 == scorePurpose }
        XCTAssertFalse(snapshot.hasApprovedCurrentScoreSharing)
    }

    func testV5CanonicalDisclosurePreservesOffAndReadOnlyChoicesInClosedBody() throws {
        let snapshot = try snapshot("functional-permissions-v5")
        try snapshot.validate(deviceID: device)
        XCTAssertEqual(snapshot.disclosure.purposes.count, 20)
        let score = try XCTUnwrap(snapshot.disclosure.purposes.first { $0.id == scorePurpose })
        XCTAssertFalse(score.defaultEnabled)
        XCTAssertTrue(score.purpose.contains("참가 차 현재 운전자·동승자"))
        XCTAssertFalse(snapshot.authorization.approvedPurposes.contains(scorePurpose))
        let selected = Set(snapshot.authorization.approvedPurposes)
        let body = try XCTUnwrap(JSONSerialization.jsonObject(with: snapshot.payload(approved: selected)) as? [String: Any])
        XCTAssertEqual(Set(body.keys), bodyKeys)
        XCTAssertEqual(body["functionalDisclosureVersion"] as? Int, 5)
        XCTAssertEqual(body["functionalDisclosureSha256"] as? String, "e7ab946a1a2c6642cf0993a472ba8963521766e5761e1d10fed950e4b630ecd6")
        XCTAssertEqual(body["approvedPurposes"] as? [String], selected.sorted())
        XCTAssertNil(body["approvedDisclosureVersion"])
        XCTAssertThrowsError(try snapshot.payload(approved: selected.subtracting(["rooms:read"])))
        XCTAssertThrowsError(try snapshot.payload(approved: selected.union(["device-commands:receive"])))
    }

    func testMalformedApprovalMarkersAndChangedV5DisclosureCannotBeUsed() throws {
        for marker in [-1, 0, 6] {
            var snapshot = try snapshot("functional-permissions-v5")
            snapshot.approvedDisclosureVersion = marker
            XCTAssertThrowsError(try snapshot.validate(deviceID: device))
            XCTAssertThrowsError(try snapshot.payload(approved: Set(snapshot.authorization.approvedPurposes)))
        }
        for marker in ["4", true] as [Any] {
            var value = try object(self.snapshot("functional-permissions-v5"))
            value["approvedDisclosureVersion"] = marker
            XCTAssertThrowsError(try JSONDecoder().decode(VehicleFunctionalSnapshot.self, from: JSONSerialization.data(withJSONObject: value)))
        }
        var snapshot = try snapshot("functional-permissions-v5")
        snapshot.disclosure.purposes[0].purpose += "변경"
        XCTAssertThrowsError(try snapshot.validate(deviceID: device))
        snapshot = try self.snapshot("functional-permissions-v5")
        snapshot.disclosure.sha256 = String(repeating: "0", count: 64)
        snapshot.authorization.functionalDisclosureSha256 = snapshot.disclosure.sha256
        XCTAssertThrowsError(try snapshot.validate(deviceID: device))
        snapshot = try self.snapshot("functional-permissions-v5")
        snapshot.authorization.functionalDisclosureSha256 = String(repeating: "0", count: 64)
        XCTAssertThrowsError(try snapshot.validate(deviceID: device))
    }

    func testOnlyExplicitSaveUpgradesUnchangedPurposesFromOriginalV3ToV5() async throws {
        var before = try snapshot("functional-permissions-v5")
        before.authorization.approvedPurposes.append(scorePurpose)
        before.authorization.approvedPurposes.sort()
        let beforeObject = try object(before)
        var after = before
        after.approvedDisclosureVersion = 5
        after.authorization.revision += 1
        let afterObject = try object(after)
        var reads = 0, writes = 0
        FunctionalPermissionsHTTPStub.respond = { [self] request in
            XCTAssertEqual(request.url?.path, "/v1/iphone/vehicles/" + device + "/functional-permissions")
            XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer " + token)
            if request.httpMethod == "GET" { reads += 1; return (200, beforeObject) }
            writes += 1
            XCTAssertEqual(request.httpMethod, "PUT")
            let payload = try body(request)
            XCTAssertEqual(Set(payload.keys), bodyKeys)
            XCTAssertEqual(payload["approvedPurposes"] as? [String], before.authorization.approvedPurposes)
            XCTAssertEqual(payload["revision"] as? Int, before.authorization.revision)
            XCTAssertEqual(payload["functionalDisclosureVersion"] as? Int, 5)
            return (200, afterObject)
        }
        let client = api()
        let loaded = try await client.load(device, token: token)
        XCTAssertEqual(reads, 1)
        XCTAssertEqual(writes, 0)
        XCTAssertFalse(loaded.hasApprovedCurrentScoreSharing)
        let saved = try await client.save(loaded, approved: Set(loaded.authorization.approvedPurposes), token: token)
        XCTAssertEqual(writes, 1)
        XCTAssertEqual(saved.authorization.revision, before.authorization.revision + 1)
        XCTAssertEqual(saved.authorization.approvedPurposes, before.authorization.approvedPurposes)
        XCTAssertTrue(saved.hasApprovedCurrentScoreSharing)
    }

    func testExplicitV5SaveKeepsOffPurposeAndExistingReadOnlyChoices() async throws {
        var before = try snapshot("functional-permissions-v5")
        before.approvedDisclosureVersion = 5
        let result = try object(before)
        var writes = 0
        FunctionalPermissionsHTTPStub.respond = { [self] request in
            writes += 1
            let payload = try body(request)
            XCTAssertEqual(payload["approvedPurposes"] as? [String], before.authorization.approvedPurposes)
            return (200, result)
        }
        let saved = try await api().save(before, approved: Set(before.authorization.approvedPurposes), token: token)
        XCTAssertEqual(writes, 1)
        XCTAssertEqual(saved.authorization.revision, before.authorization.revision)
        XCTAssertFalse(saved.hasApprovedCurrentScoreSharing)
        XCTAssertFalse(saved.authorization.approvedPurposes.contains(scorePurpose))
        XCTAssertEqual(saved.readOnlyPurposes, before.readOnlyPurposes)
    }

    func testSaveRejectsDisplayOnlyApprovalAndUnchangedUpgradeRevision() async throws {
        let before = try snapshot("functional-permissions-v5")
        var writes = 0
        for mutation in ["old-marker", "missing-marker", "null-marker", "revision"] {
            var after = before
            after.approvedDisclosureVersion = 5
            after.authorization.revision += 1
            var response = try object(after)
            if mutation == "old-marker" { response["approvedDisclosureVersion"] = 3 }
            if mutation == "missing-marker" { response.removeValue(forKey: "approvedDisclosureVersion") }
            if mutation == "null-marker" { response["approvedDisclosureVersion"] = NSNull() }
            if mutation == "revision" { response = try object(before); response["approvedDisclosureVersion"] = 5 }
            FunctionalPermissionsHTTPStub.respond = { _ in writes += 1; return (200, response) }
            do {
                _ = try await api().save(before, approved: Set(before.authorization.approvedPurposes), token: token)
                XCTFail(mutation)
            } catch VehicleLinkError.invalidResponse { }
        }
        XCTAssertEqual(writes, 4)
    }

    func testSavePreservesAPIErrorAndDoesNotRetry() async throws {
        let snapshot = try snapshot("functional-permissions-v5")
        var writes = 0
        for status in [403, 409] {
            FunctionalPermissionsHTTPStub.respond = { request in
                writes += 1
                XCTAssertEqual(request.httpMethod, "PUT")
                return (status, ["detail": status == 403 ? "RECEIVER_VEHICLE_ONLY" : "FUNCTIONAL_REVISION_CHANGED"])
            }
            do {
                _ = try await api().save(snapshot, approved: Set(snapshot.authorization.approvedPurposes), token: token)
                XCTFail()
            } catch IPhoneSessionError.forbidden { XCTAssertEqual(status, 403) }
            catch IPhoneResourceError.conflict { XCTAssertEqual(status, 409) }
        }
        XCTAssertEqual(writes, 2)
    }
}
