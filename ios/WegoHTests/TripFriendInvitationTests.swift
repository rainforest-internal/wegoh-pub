import XCTest
@testable import WegoH

@MainActor
final class TripFriendInvitationTests: XCTestCase {
    func testMultipleSelectionWaitsForSendAndKeepsExistingMembersDisabled() async {
        let model = TripFriendInvitationModel()
        let friends = choices()
        await model.reload { friends }
        for friend in friends { model.toggle(friend) }
        XCTAssertEqual(model.selected, ["one", "two"])
        var writes: [String] = []
        await model.send(canContinue: { true }) { writes.append($0) }
        XCTAssertEqual(writes, ["one", "two"])
        XCTAssertEqual(model.sent, ["one", "two"])
        XCTAssertTrue(model.selected.isEmpty)
        XCTAssertEqual(model.status(for: friends[2]), "초대 보냄")
        XCTAssertEqual(model.status(for: friends[3]), "참여 중")
    }

    func testPartialFailureKeepsFailedSelectionAndNeverResendsSuccess() async {
        let model = TripFriendInvitationModel()
        let friends = choices()
        await model.reload { friends }
        model.toggle(friends[0]); model.toggle(friends[1])
        var writes: [String] = []
        await model.send(canContinue: { true }) { id in
            writes.append(id)
            if id == "two" { throw IPhoneTripRequestError.routeConflict("Trip is full") }
        }
        XCTAssertEqual(model.sent, ["one"])
        XCTAssertEqual(model.selected, ["two"])
        XCTAssertEqual(model.failures["two"], IPhoneTripRequestError.routeConflict("Trip is full").errorDescription)
        await model.reload { friends }
        model.toggle(friends[0])
        XCTAssertEqual(model.selected, ["two"])
        await model.send(canContinue: { true }) { writes.append($0) }
        XCTAssertEqual(writes, ["one", "two", "two"])
        XCTAssertEqual(model.sent, ["one", "two"])
    }

    func testSavedInviteWithFailedDetailReloadPausesRemainingAndPreservesSuccess() async {
        let model = TripFriendInvitationModel()
        let friends = choices()
        await model.reload { friends }
        model.toggle(friends[0]); model.toggle(friends[1])
        var ready = true, writes: [String] = []
        await model.send(canContinue: { ready }) { id in writes.append(id); ready = false }
        XCTAssertEqual(writes, ["one"])
        XCTAssertEqual(model.sent, ["one"])
        XCTAssertEqual(model.selected, ["two"])
        XCTAssertNotNil(model.error)
        await model.send(canContinue: { ready }) { writes.append($0) }
        XCTAssertEqual(writes, ["one"])
        ready = true
        await model.reload { friends }
        await model.send(canContinue: { ready }) { writes.append($0) }
        XCTAssertEqual(writes, ["one", "two"])
    }

    func testEmptyFriendsAreConfirmedOnlyAfterSuccessfulRead() async {
        let model = TripFriendInvitationModel()
        XCTAssertFalse(model.hasLoaded)
        await model.reload { throw IPhoneTripRequestError.unavailable }
        XCTAssertNotNil(model.error)
        XCTAssertFalse(model.hasLoaded)
        await model.reload {
            XCTAssertTrue(model.loading)
            XCTAssertFalse(model.hasLoaded)
            return []
        }
        XCTAssertTrue(model.hasLoaded)
        XCTAssertTrue(model.friends.isEmpty)
        model.invalidate()
        XCTAssertFalse(model.hasLoaded)
    }

    func testAccountChangeDiscardsLateReadAndWriteResults() async {
        let model = TripFriendInvitationModel()
        let friends = choices()
        await model.reload { model.invalidate(); return friends }
        XCTAssertTrue(model.friends.isEmpty)
        await model.reload { friends }
        model.toggle(friends[0]); model.toggle(friends[1])
        var writes: [String] = []
        await model.send(canContinue: { true }) { id in writes.append(id); model.invalidate() }
        XCTAssertEqual(writes, ["one"])
        XCTAssertTrue(model.friends.isEmpty)
        XCTAssertTrue(model.sent.isEmpty)
        XCTAssertTrue(model.failures.isEmpty)
    }

    private func choices() -> [TripFriendInvitationChoice] {
        [.init(id: "one", name: "첫 친구", code: "@first"),
         .init(id: "two", name: "둘째 친구", code: "@second"),
         .init(id: "pending", name: "초대한 친구", code: "@pending", memberState: .pending),
         .init(id: "accepted", name: "참여한 친구", code: "@accepted", memberState: .accepted)]
    }
}
