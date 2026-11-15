import Foundation
import Observation

@MainActor @Observable
final class TripSignalInbox {
    static let responseChanged = Notification.Name("WegoH.tripSignalResponseChanged")
    struct Prompt: Identifiable {
        let trip: IPhoneTripDetail
        let carID: String
        let signal: IPhoneTripSignal
        var id: String { trip.id + ":" + carID + ":" + signal.id }
    }

    private(set) var prompt: Prompt?
    private(set) var checking = false
    private(set) var responding = false
    private(set) var message: String?
    private(set) var needsVerification = false
    private let session: SessionManager
    private let accountID: String?
    private let api: any IPhoneTripServing
    private let activity: any IPhoneTripActivityServing
    private var tripIDs: Set<String> = []
    private var queuedTripIDs: Set<String> = []
    private var lastDiscovery: Date?
    private var generation = UUID()

    var isCurrent: Bool {
        session.phase == .signedIn && accountID != nil && session.current?.accountID == accountID
            && session.current?.scopes.isSuperset(of: ["trips:read", "trips:manage"]) == true
    }
    var canRespond: Bool { isCurrent && prompt != nil && !responding && !needsVerification }

    init(session: SessionManager, api: any IPhoneTripServing = IPhoneTripAPI(),
         activity: any IPhoneTripActivityServing = IPhoneTripActivityAPI()) {
        self.session = session
        accountID = session.current?.accountID
        self.api = api
        self.activity = activity
    }

    func refresh(tripID: String? = nil, discover: Bool = false) async {
        guard isCurrent else { clear(); return }
        if let tripID, validTripID(tripID) { tripIDs.insert(tripID); queuedTripIDs.insert(tripID) }
        guard !checking, !responding else { return }
        checking = true
        let stamp = generation
        defer { checking = false }
        do {
            let discoveryDue = lastDiscovery.map { Date.now.timeIntervalSince($0) >= 60 } ?? true
            if tripID == nil, prompt == nil, discover || discoveryDue {
                let page = try await request { try await self.api.list(token: $0) }
                guard stamp == generation else { throw CancellationError() }
                tripIDs = Set(page.trips.filter { $0.state == .active }.map(\.id)).union(queuedTripIDs)
                lastDiscovery = .now
                if let prompt, !tripIDs.contains(prompt.trip.id) { self.prompt = nil }
            }
            var remaining = tripIDs
            if let prompt {
                try await read(prompt.trip.id, stamp: stamp)
                remaining.remove(prompt.trip.id)
                queuedTripIDs.remove(prompt.trip.id)
            }
            for id in remaining.sorted() where prompt == nil {
                try await read(id, stamp: stamp)
                queuedTripIDs.remove(id)
            }
            while let id = queuedTripIDs.first {
                queuedTripIDs.remove(id)
                if prompt == nil || prompt?.trip.id == id { try await read(id, stamp: stamp) }
            }
        } catch is CancellationError { }
        catch {
            if !isCurrent { clear() }
            else if prompt != nil { needsVerification = true; message = "요청 상태를 확인하지 못했어요. 다시 확인해 주세요." }
        }
    }

    func respond(agree: Bool) async {
        guard canRespond, let target = prompt else { return }
        responding = true
        generation = UUID()
        let stamp = generation
        var sendError: Error?
        message = nil
        defer { responding = false }
        do {
            try await read(target.trip.id, stamp: stamp)
            guard prompt?.id == target.id else { return }
        } catch {
            if !isCurrent { clear() }
            else { needsVerification = true; message = "요청 상태를 확인하지 못했어요. 다시 확인해 주세요." }
            return
        }
        do {
            _ = try await request { try await self.activity.vote(target.trip.id, signalID: target.signal.id, agree: agree, token: $0) }
        } catch is CancellationError { needsVerification = true; return }
        catch {
            guard isCurrent else { clear(); return }
            sendError = error
        }
        do {
            try await read(target.trip.id, stamp: stamp)
            if prompt?.id == target.id {
                needsVerification = sendError == nil
                message = sendError.map(tripPreparationErrorMessage) ?? "응답을 확인하고 있어요. 잠시 기다려 주세요."
            }
        } catch {
            if !isCurrent { clear() }
            else { needsVerification = true; message = "응답 결과를 확인하지 못했어요. 다시 확인해 주세요." }
        }
    }

    func clear() {
        generation = UUID()
        prompt = nil
        tripIDs = []
        queuedTripIDs = []
        message = nil
        needsVerification = false
    }

    func suspend() { generation = UUID(); needsVerification = prompt != nil }

    private func read(_ tripID: String, stamp: UUID) async throws {
        let signals: [IPhoneTripSignal]
        do { signals = try await request { try await self.activity.signals(tripID, token: $0) } }
        catch {
            guard stamp == generation else { throw CancellationError() }
            if tripActivityAccessLost(error) {
                tripIDs.remove(tripID)
                if prompt?.trip.id == tripID { prompt = nil }
                return
            }
            throw error
        }
        guard stamp == generation else { throw CancellationError() }
        guard let signal = signals.first(where: {
            $0.inProgress && $0.resolution == "pending" && $0.canRespond == true && $0.myGroupChoice == nil && $0.accountId != accountID
        }) else {
            if prompt?.trip.id == tripID {
                prompt = nil; message = nil; needsVerification = false
                NotificationCenter.default.post(name: Self.responseChanged, object: tripID)
            }
            return
        }
        let detail: IPhoneTripDetail
        do { detail = try await request { try await self.api.detail(tripID, token: $0) } }
        catch {
            guard stamp == generation else { throw CancellationError() }
            if tripActivityAccessLost(error) {
                tripIDs.remove(tripID)
                if prompt?.trip.id == tripID { prompt = nil }
                return
            }
            throw error
        }
        guard stamp == generation else { throw CancellationError() }
        guard detail.state == .active, detail.me?.state == .accepted, let car = detail.myCar,
              signal.requesterCarId != car.id else {
            if prompt?.trip.id == tripID { prompt = nil }
            return
        }
        prompt = Prompt(trip: detail, carID: car.id, signal: signal)
        needsVerification = false
        message = nil
    }

    private func request<T>(_ operation: (String) async throws -> T) async throws -> T {
        try Task.checkCancellation()
        guard isCurrent, let account = session.current else { throw IPhoneSessionError.invalidSession }
        let value = try await session.withToken(for: account, operation)
        try Task.checkCancellation()
        guard isCurrent else { throw IPhoneSessionError.invalidSession }
        return value
    }
}
