import Foundation
import XCTest
@testable import WegoH

private final class TripInvitationHTTPStub: URLProtocol {
    static var respond: ((URLRequest) throws -> (Int, Data))?
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func stopLoading() { }
    override func startLoading() {
        do {
            let (status, body) = try XCTUnwrap(Self.respond)(request)
            let response = HTTPURLResponse(url: try XCTUnwrap(request.url), statusCode: status, httpVersion: nil,
                                           headerFields: ["Content-Type": "application/json"])!
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: body)
            client?.urlProtocolDidFinishLoading(self)
        } catch { client?.urlProtocol(self, didFailWithError: error) }
    }
}

@MainActor
final class TripInvitationTransportTests: XCTestCase {
    private let trip = String(repeating: "a", count: 32)
    private let token = String(repeating: "T", count: 43)
    private func configuration() -> URLSessionConfiguration {
        let value = URLSessionConfiguration.ephemeral
        value.protocolClasses = [TripInvitationHTTPStub.self]
        return value
    }

    func testUnavailableInviteeIsSeparatedFromMissingTrip() async throws {
        TripInvitationHTTPStub.respond = { _ in (404, try JSONSerialization.data(withJSONObject: ["detail": "Account unavailable"])) }
        defer { TripInvitationHTTPStub.respond = nil }
        do {
            try await IPhoneTripAPI(configuration: configuration()).addMember(trip, accountID: "team-" + String(repeating: "2", count: 40), token: token)
            XCTFail("Unavailable invitee accepted")
        } catch IPhoneTripRequestError.routeConflict(let code) {
            XCTAssertEqual(code, "Account unavailable")
            XCTAssertTrue(IPhoneTripRequestError.routeConflict(code).errorDescription?.contains("친구 관계") == true)
        }
        let http = IPhoneSessionAPI(configuration: configuration())
        for (path, method) in [("trips/" + trip, "GET"), ("trips/" + trip + "/members", "GET"),
                               ("trips/" + trip + "/members", "PUT"), ("trips/" + trip + "/respond", "POST"),
                               ("trips/not-a-trip/members", "POST"), ("friends/requests", "POST")] {
            do { _ = try await http.resource(path, method: method, payload: method == "GET" ? nil : Data("{}".utf8), token: token); XCTFail("Non-invitation 404 changed: " + path) }
            catch IPhoneResourceError.missing { }
        }
    }

    func testOtherOrMissingErrorDetailsKeepMissingBehavior() async throws {
        let http = IPhoneSessionAPI(configuration: configuration())
        defer { TripInvitationHTTPStub.respond = nil }
        for body in [["detail": "Trip unavailable"], [:], ["detail": "account unavailable"]] {
            TripInvitationHTTPStub.respond = { _ in (404, try JSONSerialization.data(withJSONObject: body)) }
            do { _ = try await http.resource("trips/" + trip + "/members", method: "POST", payload: Data("{}".utf8), token: token); XCTFail("Unclassified 404 changed") }
            catch IPhoneResourceError.missing { }
        }
    }

    func testMissingInviteeKeepsLoadedTripWhileMissingTripClearsIt() async throws {
        let preview = TripPreview(id: "invite-protection", title: "초대 확인", state: .planned, dateLabel: "날짜 미정",
                                  ownerName: "사용자E", members: ["사용자E"], cars: [], summary: "샘플", stops: [])
        let source = TripPreparationPreviewAPI(preview: preview)
        let detail = try await source.detail(source.tripID, token: "")
        let actor = try XCTUnwrap(detail.me).id
        var missingDetail = "Account unavailable"
        TripInvitationHTTPStub.respond = { request in
            if request.url?.path.hasSuffix("/session") == true {
                return (200, try JSONSerialization.data(withJSONObject: ["user": ["id": actor, "displayName": "사용자E"],
                    "scopes": ["account:read", "trips:read", "trips:manage"], "expiresAt": Int(Date.now.timeIntervalSince1970) + 3600]))
            }
            if request.httpMethod == "POST" { return (404, try JSONSerialization.data(withJSONObject: ["detail": missingDetail])) }
            return (200, try JSONEncoder().encode(detail))
        }
        defer { TripInvitationHTTPStub.respond = nil }
        let session = SessionManager(api: IPhoneSessionAPI(configuration: configuration()), credentials: TripInvitationCredential())
        await session.restore()
        let store = TripPreparationStore(tripID: detail.id, session: session, api: IPhoneTripAPI(configuration: configuration()))
        await store.load()
        XCTAssertNotNil(store.detail)
        do { try await store.invite(accountID: "team-" + String(repeating: "2", count: 40)); XCTFail("Unavailable invitee accepted") }
        catch IPhoneTripRequestError.routeConflict { }
        XCTAssertEqual(store.detail, detail)
        XCTAssertFalse(store.needsRefresh)
        missingDetail = "Trip unavailable"
        do { try await store.invite(accountID: "team-" + String(repeating: "2", count: 40)); XCTFail("Missing trip accepted") }
        catch IPhoneTripRequestError.missing { }
        XCTAssertNil(store.detail)
        XCTAssertTrue(store.needsRefresh)
    }
}

@MainActor
private final class TripInvitationCredential: IPhoneCredentialStoring {
    func load() throws -> StoredIPhoneCredential? { .init(token: String(repeating: "T", count: 43), logoutPending: false) }
    func saveToken(_ token: String) throws { }
    func markLogoutPending() throws { }
    func clearToken() throws { }
}
