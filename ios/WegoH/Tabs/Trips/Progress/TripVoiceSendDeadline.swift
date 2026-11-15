import Foundation

final class TripVoiceSendDeadline: @unchecked Sendable {
    private enum State { case pending, completed, timedOut }
    private let lock = NSLock()
    private var state = State.pending

    @discardableResult
    func complete() -> Bool {
        lock.lock()
        defer { lock.unlock() }
        guard case .pending = state else { return false }
        state = .completed
        return true
    }

    func timeout() -> Bool {
        lock.lock()
        defer { lock.unlock() }
        guard case .pending = state else { return false }
        state = .timedOut
        return true
    }
}
