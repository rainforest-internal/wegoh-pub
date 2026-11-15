import Foundation
import Network
import XCTest
@testable import WegoH

@MainActor
final class TripRouteFixtureTests: XCTestCase {
    func testFactoryKeepsSessionAndDetailAfterSignalsAndBlocksDefaultSessionBeforeTransport() async throws {
        let unchanged = URLSessionConfiguration.ephemeral
        let protocols = unchanged.protocolClasses?.map { ObjectIdentifier($0) }
        TripRouteUIFixture.configureDefaultTransport(unchanged, requested: false)
        XCTAssertEqual(unchanged.protocolClasses?.map { ObjectIdentifier($0) }, protocols)
        let connections = FixtureConnectionCount()
        let listener = try NWListener(using: .tcp, on: .any)
        let ready = expectation(description: "loopback sentinel ready")
        let received = expectation(description: "no default request reaches transport")
        received.isInverted = true
        listener.stateUpdateHandler = { state in if case .ready = state { ready.fulfill() } }
        listener.newConnectionHandler = { connection in
            connections.increment()
            received.fulfill()
            connection.cancel()
        }
        listener.start(queue: DispatchQueue(label: "wegoh.trip-route-fixture-sentinel"))
        defer { listener.cancel() }
        await fulfillment(of: [ready], timeout: 2)
        let port = try XCTUnwrap(listener.port)
        let sentinel = try XCTUnwrap(URL(string: "http://127.0.0.1:\(port.rawValue)/trip-route-fixture-sentinel"))
        TripRouteUIFixture.resetOutboundGuardObservations()
        defer { TripRouteUIFixture.resetOutboundGuardObservations() }
        TripRouteUIFixture.resetRequestObservations()
        let session = SessionManager(api: IPhoneSessionAPI(configuration: TripRouteUIFixture.configuration()),
                                     credentials: FriendsUIFixture.Credential())
        await session.restore()
        XCTAssertEqual(session.phase, .signedIn)
        let store = TripRouteUIFixture.makeStore(session: session)
        await store.refreshVisibleState()
        XCTAssertEqual(session.phase, .signedIn)
        XCTAssertNotNil(store.detail)
        XCTAssertNil(store.errorMessage)
        XCTAssertTrue(TripRouteUIFixture.observedRequestPaths.contains("/v1/iphone/session"))
        XCTAssertTrue(TripRouteUIFixture.observedRequestPaths.contains("/v1/iphone/trips/" + String(repeating: "a", count: 32)))
        XCTAssertTrue(TripRouteUIFixture.observedRequestPaths.contains("/v1/iphone/trips/" + String(repeating: "a", count: 32) + "/signals"))
        XCTAssertEqual(TripRouteUIFixture.blockedDefaultRequestCount, 0)
        let defaultConfiguration = URLSessionConfiguration.ephemeral
        TripRouteUIFixture.configureDefaultTransport(defaultConfiguration, requested: true, sentinel: sentinel)
        let transport = URLSession(configuration: defaultConfiguration)
        defer { transport.invalidateAndCancel() }
        do {
            _ = try await transport.data(from: sentinel)
            XCTFail("Default session must be blocked")
        } catch {
            XCTAssertEqual((error as? URLError)?.code, .notConnectedToInternet)
        }
        XCTAssertEqual(TripRouteUIFixture.blockedDefaultRequestCount, 1)
        await fulfillment(of: [received], timeout: 0.1)
        XCTAssertEqual(connections.value, 0)
    }
}

private final class FixtureConnectionCount: @unchecked Sendable {
    private let lock = NSLock()
    private var count = 0
    var value: Int { lock.withLock { count } }
    func increment() { lock.withLock { count += 1 } }
}
