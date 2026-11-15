#if DEBUG
import Foundation
import XCTest
@testable import WegoH

final class LocalServerUIFixtureTests: XCTestCase {
    private let token = String(repeating: "L", count: 43)

    private func bootstrap(_ overrides: [String: Any] = [:]) throws -> Data {
        var value: [String: Any] = ["format": 1, "synthetic": true,
            "origin": "https://ios-api-wegoh.devforest.io", "localBaseURL": "http://127.0.0.1:54321",
            "defaultActor": "eve", "accounts": ["eve": ["accessToken": token]]]
        value.merge(overrides) { _, new in new }
        return try JSONSerialization.data(withJSONObject: value)
    }

    func testBootstrapRequiresSyntheticLoopbackAndExactActorCredential() throws {
        let value = try XCTUnwrap(LocalServerUIFixture.validatedSettings(data: bootstrap()))
        XCTAssertEqual(value.origin.absoluteString, "http://127.0.0.1:54321")
        XCTAssertEqual(value.token, token)
        let invalid: [[String: Any]] = [
            ["format": 2], ["synthetic": false], ["origin": "https://other.invalid"],
            ["localBaseURL": "https://127.0.0.1:54321"], ["localBaseURL": "http://localhost:54321"],
            ["localBaseURL": "http://192.168.0.2:54321"], ["localBaseURL": "http://127.0.0.1:80"],
            ["localBaseURL": "http://127.0.0.1"], ["localBaseURL": "http://127.0.0.1:54321/route"],
            ["localBaseURL": "http://name@127.0.0.1:54321"], ["localBaseURL": "http://127.0.0.1:54321?x=1"],
            ["localBaseURL": "http://127.0.0.1:54321#x"], ["defaultActor": "missing"],
            ["accounts": ["eve": ["accessToken": "bad-token"]]]
        ]
        for input in invalid {
            XCTAssertNil(LocalServerUIFixture.validatedSettings(data: try bootstrap(input)))
        }
        XCTAssertNil(LocalServerUIFixture.validatedSettings(data: try bootstrap(), actor: "unknown"))
        XCTAssertNil(LocalServerUIFixture.validatedSettings(data: Data(repeating: 0, count: 65_537)))
    }

    func testForwardingPreservesOriginalHostPathBodyAndQueryButRejectsUnknownBearer() throws {
        let settings = try XCTUnwrap(LocalServerUIFixture.validatedSettings(data: bootstrap()))
        var request = URLRequest(url: URL(string: "https://ios-api-wegoh.devforest.io/v1/iphone/courses/library?q=a%2Bb&tag=%EB%B0%94%EB%8B%A4")!)
        request.httpMethod = "POST"
        request.httpBody = Data("{}".utf8)
        request.setValue("Bearer " + token, forHTTPHeaderField: "Authorization")
        request.setValue("image/jpeg", forHTTPHeaderField: "Accept")
        let forwarded = try XCTUnwrap(LocalServerUIFixture.forwarded(request, settings: settings))
        XCTAssertEqual(forwarded.url?.absoluteString, "http://127.0.0.1:54321/v1/iphone/courses/library?q=a%2Bb&tag=%EB%B0%94%EB%8B%A4")
        XCTAssertEqual(forwarded.value(forHTTPHeaderField: "Host"), "ios-api-wegoh.devforest.io")
        XCTAssertEqual(forwarded.value(forHTTPHeaderField: "Accept"), "image/jpeg")
        XCTAssertEqual(forwarded.httpBody, request.httpBody)
        XCTAssertEqual(forwarded.httpMethod, "POST")
        XCTAssertFalse(forwarded.httpShouldHandleCookies)
        var unknown = request
        unknown.setValue("Bearer " + String(repeating: "R", count: 43), forHTTPHeaderField: "Authorization")
        XCTAssertNil(LocalServerUIFixture.forwarded(unknown, settings: settings))
        unknown.setValue(nil, forHTTPHeaderField: "Authorization")
        XCTAssertNil(LocalServerUIFixture.forwarded(unknown, settings: settings))
        var cookie = request
        cookie.setValue("existing=credential", forHTTPHeaderField: "Cookie")
        XCTAssertNil(LocalServerUIFixture.forwarded(cookie, settings: settings))
        for url in ["https://other.invalid/v1/iphone/session", "https://ios-api-wegoh.devforest.io/v1/account",
                    "https://ios-api-wegoh.devforest.io:443/v1/iphone/session"] {
            var invalid = request
            invalid.url = URL(string: url)
            XCTAssertNil(LocalServerUIFixture.forwarded(invalid, settings: settings))
        }
        let remote = LocalServerUIFixture.Settings(origin: URL(string: "http://other.invalid:54321")!, token: token)
        XCTAssertNil(LocalServerUIFixture.forwarded(request, settings: remote))
    }

    func testResponseByteLimitIsScopedToLibraryAndVersionedCoverGET() {
        let cases: [(String, String, Int)] = [
            ("courses/library", "GET", 16_777_216),
            ("courses/library?tag=sea", "GET", 16_777_216),
            ("courses/library", "POST", 2_097_152),
            ("courses/library/extra", "GET", 2_097_152),
            ("courses/public/coast/versions/1/cover", "GET", 524_288),
            ("courses/public/coast/versions/1/cover", "PUT", 2_097_152),
            ("courses/public/coast/versions/1/cover/extra", "GET", 2_097_152),
            ("session", "GET", 2_097_152)
        ]
        for (path, method, expected) in cases {
            var request = URLRequest(url: URL(string: "https://ios-api-wegoh.devforest.io/v1/iphone/" + path)!)
            request.httpMethod = method
            XCTAssertEqual(LocalServerUIFixture.responseByteLimit(for: request), expected)
        }
    }

    func testPrivateBootstrapRejectsPermissionsAndSymbolicLinks() throws {
        let manager = FileManager.default
        let directory = manager.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
        try manager.createDirectory(at: directory, withIntermediateDirectories: false,
                                    attributes: [.posixPermissions: 0o700])
        defer { try? manager.removeItem(at: directory) }
        let file = directory.appendingPathComponent("private-bootstrap.json")
        XCTAssertNil(LocalServerUIFixture.privateSettings(directory: directory))
        try bootstrap().write(to: file)
        try manager.setAttributes([.posixPermissions: 0o600], ofItemAtPath: file.path)
        XCTAssertNotNil(LocalServerUIFixture.privateSettings(directory: directory))
        try manager.setAttributes([.posixPermissions: 0o644], ofItemAtPath: file.path)
        XCTAssertNil(LocalServerUIFixture.privateSettings(directory: directory))
        try manager.setAttributes([.posixPermissions: 0o600], ofItemAtPath: file.path)
        try manager.setAttributes([.posixPermissions: 0o755], ofItemAtPath: directory.path)
        XCTAssertNil(LocalServerUIFixture.privateSettings(directory: directory))
        try manager.setAttributes([.posixPermissions: 0o700], ofItemAtPath: directory.path)
        let target = directory.appendingPathComponent("other.json")
        try manager.moveItem(at: file, to: target)
        try manager.createSymbolicLink(at: file, withDestinationURL: target)
        XCTAssertNil(LocalServerUIFixture.privateSettings(directory: directory))
    }

    @MainActor
    func testFirstRunStorageResetsOnlyWithExplicitTestingAndResetFlags() throws {
        let name = LocalServerUIFixture.firstRunSuite
        let storage = try XCTUnwrap(UserDefaults(suiteName: name))
        let previous = storage.persistentDomain(forName: name)
        defer {
            storage.removePersistentDomain(forName: name)
            if let previous { storage.setPersistentDomain(previous, forName: name) }
        }
        storage.set("preserved", forKey: "first-run.test-marker")
        XCTAssertNil(LocalServerUIFixture.makeFirstRunStorage(arguments: ["-wegoh-first-run-reset"]))
        XCTAssertEqual(storage.string(forKey: "first-run.test-marker"), "preserved")
        let resumed = try XCTUnwrap(LocalServerUIFixture.makeFirstRunStorage(arguments: ["-wegoh-first-run-testing"]))
        XCTAssertEqual(resumed.string(forKey: "first-run.test-marker"), "preserved")
        let reset = try XCTUnwrap(LocalServerUIFixture.makeFirstRunStorage(arguments: ["-wegoh-first-run-testing", "-wegoh-first-run-reset"]))
        XCTAssertNil(reset.string(forKey: "first-run.test-marker"))
    }

    @MainActor
    func testInvalidBootstrapSessionRestoresSignedOutWithoutKeychainFallback() async {
        let session = LocalServerUIFixture.makeSession(settings: nil)
        await session.restore()
        XCTAssertEqual(session.phase, .signedOut)
        XCTAssertNil(session.current)
    }
}
#endif
