import XCTest
@testable import WegoH

final class TripInvitationStoreTests: XCTestCase {
    func testAcceptanceRemovesPendingInviteWithoutInventingTripDetails() {
        let store = TripsPreviewStore()
        let invitation = store.invitations[0]
        store.accept(invitation, locationConsent: false)
        XCTAssertTrue(store.invitations.isEmpty)
        XCTAssertEqual(store.accepted.count, 1)
        XCTAssertEqual(store.accepted[0].invitation, invitation)
        XCTAssertTrue(store.accepted[0].locationConsent)
        store.accept(invitation, locationConsent: true)
        XCTAssertEqual(store.accepted.count, 1)
        XCTAssertTrue(store.accepted[0].locationConsent)
    }

    func testDeclineDoesNotJoinTheTripAndCannotLaterAcceptTheSameInvite() {
        let store = TripsPreviewStore()
        let invitation = store.invitations[0]
        store.decline(invitation)
        store.accept(invitation, locationConsent: true)
        XCTAssertTrue(store.invitations.isEmpty)
        XCTAssertTrue(store.accepted.isEmpty)
    }
}
