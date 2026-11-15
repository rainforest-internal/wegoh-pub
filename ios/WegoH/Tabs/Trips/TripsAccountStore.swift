import Foundation
import Observation

@MainActor @Observable
final class TripsAccountStore {
    private var snapshot: IPhoneTripList?
    private(set) var loading = false
    private(set) var busy = false
    private(set) var errorMessage: String?
    private(set) var needsRefresh = false
    private let session: SessionManager
    private let account: AccountSession?
    private let api: any IPhoneTripServing
    private var read: UUID?
    private var refreshPending = false
    private var lastForegroundInvitationID: String?
    private var lastForegroundReturn: UUID?

    init(session: SessionManager, api: any IPhoneTripServing = IPhoneTripAPI()) {
        self.session = session; account = session.current; self.api = api
    }
    func belongsToAccount(_ current: AccountSession) -> Bool {
        account?.accountID == current.accountID && account?.expiresAt == current.expiresAt && account?.scopes == current.scopes
    }
    var isCurrent: Bool {
        guard let current = session.current, session.phase == .signedIn else { return false }
        return belongsToAccount(current)
    }
    var value: IPhoneTripList? { isCurrent ? snapshot : nil }

    func noteInvalidation(invitation event: IPhonePushNotification?, foregroundReturn: UUID?) -> Bool {
        guard isCurrent else { return false }
        let resumed = lastForegroundReturn != foregroundReturn
        lastForegroundReturn = foregroundReturn
        if let event, event.kind == .tripInvitation, event.accountID == account?.accountID,
           event.eventID != lastForegroundInvitationID {
            lastForegroundInvitationID = event.eventID
            return true
        }
        return resumed
    }

    func refreshAfterInvalidation() async {
        guard isCurrent else { return }
        if loading || busy { refreshPending = true; return }
        await load()
    }

    /// 여행 탭에 들어올 때마다 부른다. 계정 이벤트 스트림이 없어 이미 보여 준 목록은 다시 읽어야
    /// 초대 수신·여행 종료 같은 서버 변화가 보인다. 오류로 비어 있는 목록은 다시 시도 버튼에 맡긴다.
    func reloadOnSelection(invalidated: Bool) async {
        if invalidated || value != nil { await refreshAfterInvalidation() }
        else if errorMessage == nil { await load() }
    }

    @discardableResult
    func load() async -> IPhoneTripList? {
        guard isCurrent, !loading, !busy, let account = session.current else { return nil }
        let stamp = UUID(); read = stamp; loading = true; errorMessage = nil
        defer { if read == stamp { read = nil; loading = false } }
        repeat {
            refreshPending = false
            do {
                let result = try await session.withToken(for: account) { try await api.list(token: $0) }
                guard read == stamp, isCurrent, !Task.isCancelled else { return nil }
                if !refreshPending {
                    snapshot = result; needsRefresh = false
                    return result
                }
            } catch is CancellationError { return nil }
            catch {
                guard read == stamp, !Task.isCancelled else { return nil }
                if tripActivityAccessLost(error) || !isCurrent { snapshot = nil; refreshPending = false }
                if !refreshPending { errorMessage = tripPreparationErrorMessage(error) }
            }
        } while refreshPending && isCurrent && !Task.isCancelled
        return nil
    }

    enum InvitationDestination: Equatable {
        case review(IPhoneTripInvitation), member(String), unavailable
    }

    func invitationDestination(for tripID: String) async -> InvitationDestination? {
        guard let latest = await load() else { return nil }
        if let invitation = latest.invitations.first(where: { $0.id == tripID }) { return .review(invitation) }
        if latest.trips.contains(where: { $0.id == tripID }) { return .member(tripID) }
        return .unavailable
    }

    func respond(_ invitation: IPhoneTripInvitation, accept: Bool, locationConsent: Bool) async throws {
        guard isCurrent, let account = session.current else { throw IPhoneSessionError.invalidSession }
        guard !busy else { throw TripPreparationError.busy }
        guard !needsRefresh else { throw TripPreparationError.refreshRequired }
        guard value?.invitations.contains(where: { $0.id == invitation.id }) == true else { throw IPhoneTripRequestError.missing }
        busy = true; read = nil; loading = false; errorMessage = nil
        defer {
            busy = false
            if refreshPending && isCurrent {
                Task { if refreshPending { await load() } }
            }
        }
        do {
            try await session.withToken(for: account) {
                try await api.respond(invitation.id, accept: accept, locationConsent: accept, token: $0)
            }
            guard isCurrent else { throw CancellationError() }
            snapshot?.invitations.removeAll { $0.id == invitation.id }
            needsRefresh = true
            refreshPending = false
            do {
                let result = try await session.withToken(for: account) { try await api.list(token: $0) }
                guard isCurrent else { throw CancellationError() }
                snapshot = result; needsRefresh = false
            } catch is CancellationError { throw CancellationError() }
            catch {
                if tripActivityAccessLost(error) { snapshot = nil }
                errorMessage = "응답은 저장했지만 최신 여행을 불러오지 못했어요. 다시 불러와 주세요."
            }
        } catch is CancellationError { throw CancellationError() }
        catch {
            if tripActivityAccessLost(error) { snapshot = nil }
            switch error {
            case IPhoneTripRequestError.conflict, IPhoneTripRequestError.routeConflict(_):
                needsRefresh = true
                refreshPending = false
                do {
                    let result = try await session.withToken(for: account) { try await api.list(token: $0) }
                    guard isCurrent else { throw CancellationError() }
                    snapshot = result
                    needsRefresh = false
                } catch {
                    if tripActivityAccessLost(error) || !isCurrent { snapshot = nil }
                }
            default: break
            }
            errorMessage = tripPreparationErrorMessage(error)
            throw error
        }
    }
}
