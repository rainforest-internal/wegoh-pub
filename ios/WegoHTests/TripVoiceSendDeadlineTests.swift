import XCTest
@testable import WegoH

final class TripVoiceSendDeadlineTests: XCTestCase {
    func testCompletedSendPreventsTimeoutBeforeParentResumes() {
        let deadline = TripVoiceSendDeadline()
        XCTAssertTrue(deadline.complete())
        XCTAssertFalse(deadline.timeout())
        XCTAssertFalse(deadline.complete())
    }

    func testTimeoutCannotCancelTwiceOrBeReplacedByLateCompletion() {
        let deadline = TripVoiceSendDeadline()
        XCTAssertTrue(deadline.timeout())
        XCTAssertFalse(deadline.complete())
        XCTAssertFalse(deadline.timeout())
    }

    func testConcurrentTimeoutsAuthorizeOneCancellation() {
        let deadline = TripVoiceSendDeadline()
        let cancellations = LockedCount()
        DispatchQueue.concurrentPerform(iterations: 64) { _ in
            if deadline.timeout() { cancellations.increment() }
        }
        XCTAssertEqual(cancellations.value, 1)
        XCTAssertFalse(deadline.complete())
    }

    func testConcurrentSendAndTimeoutChooseExactlyOneWinner() {
        for _ in 0..<128 {
            let deadline = TripVoiceSendDeadline()
            let winners = LockedCount()
            DispatchQueue.concurrentPerform(iterations: 2) { index in
                let won = index == 0 ? deadline.complete() : deadline.timeout()
                if won { winners.increment() }
            }
            XCTAssertEqual(winners.value, 1)
            XCTAssertFalse(deadline.complete())
            XCTAssertFalse(deadline.timeout())
        }
    }

    private final class LockedCount: @unchecked Sendable {
        private let lock = NSLock()
        private var count = 0
        func increment() { lock.lock(); count += 1; lock.unlock() }
        var value: Int { lock.lock(); defer { lock.unlock() }; return count }
    }
}
