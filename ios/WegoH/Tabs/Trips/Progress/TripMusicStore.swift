import Foundation
import Observation

@MainActor @Observable
final class TripMusicStore {
    let preparation: TripPreparationStore
    private let api: any IPhoneTripMusicServing
    private(set) var page: IPhoneTripMusicPage?
    private(set) var busy = false
    private(set) var resultUnknown = false
    private(set) var message: String?
    var draft = TripMusicDraft()
    private(set) var library: [AccountMusicPlaylist]?
    private(set) var libraryLoading = false
    private(set) var libraryFailed = false
    var savedSelection: TripMusicSavedSelection?
    var savedRightsConfirmed = false
    private var libraryOperation = UUID()
    private var operation = UUID()
    private var activeContext: String?
    private var pageContext: String?
    init(preparation: TripPreparationStore, api: any IPhoneTripMusicServing = IPhoneTripMusicAPI()) {
        self.preparation = preparation; self.api = api
    }
    var contextID: String {
        "\(preparation.detail?.id ?? ""):\(preparation.detail?.me?.id ?? ""):\(preparation.detail?.me?.state.rawValue ?? ""):\(preparation.detail?.state.rawValue ?? ""):\(preparation.accountIsCurrent)"
    }
    private var hasAccess: Bool {
        preparation.accountIsCurrent && preparation.detail?.me?.state == .accepted
            && preparation.detail.map { $0.state == .planned || $0.state == .active } == true
    }
    var visiblePage: IPhoneTripMusicPage? { hasAccess && pageContext == contextID ? page : nil }
    var canAdd: Bool { !busy && !resultUnknown && visiblePage?.musicSharing == true && visiblePage?.canAdd == true && draft.isValid }
    var savedChoices: [TripMusicSavedChoice] {
        let added = Set((visiblePage?.items ?? []).filter { $0.addedBy.id == preparation.detail?.me?.id }.map(\.url))
        return (library ?? []).flatMap { list in list.tracks.compactMap { track -> TripMusicSavedChoice? in
            guard let url = MusicPreviewStore.validatedURL(track.url) else { return nil }
            return TripMusicSavedChoice(selection: .init(playlistId: list.id, playlistRevision: list.revision, trackId: track.id),
                                        title: track.title, playlistName: list.name, platform: MusicPlatform.detected(for: url),
                                        alreadyAdded: added.contains(track.url))
        } }
    }
    var canAddSaved: Bool {
        guard !busy, !resultUnknown, visiblePage?.musicSharing == true, visiblePage?.canAdd == true, savedRightsConfirmed,
              let savedSelection else { return false }
        return savedChoices.contains { $0.selection == savedSelection && !$0.alreadyAdded }
    }

    func load() async {
        synchronizeContext()
        guard !busy, hasAccess, let tripID = preparation.detail?.id else { return }
        let context = contextID, stamp = UUID(); operation = stamp; busy = true
        let wasUnknown = resultUnknown
        defer { if operation == stamp { busy = false } }
        do {
            let value = try await preparation.activityRequest { try await api.load(tripID, token: $0) }
            guard isCurrent(stamp, context) else { return }
            try validate(value)
            page = value; pageContext = context; resultUnknown = false
            message = wasUnknown ? "현재 공유 설정과 목록을 확인한 뒤 다시 추가해 주세요." : nil
        } catch {
            guard isCurrent(stamp, context) else { return }
            clearIfAccessLost(error)
            message = "목록을 불러오지 못했어요. 다시 불러와 주세요."
        }
    }

    func setSharing(_ enabled: Bool) async {
        synchronizeContext()
        guard !busy, !resultUnknown, hasAccess, let tripID = preparation.detail?.id else { return }
        let context = contextID, stamp = UUID(); operation = stamp; busy = true
        defer { if operation == stamp { busy = false } }
        do {
            let value = try await preparation.activityRequest { try await api.sharing(tripID, enabled: enabled, token: $0) }
            guard isCurrent(stamp, context) else { return }
            try validate(value)
            page = value; pageContext = context
            message = enabled ? "음악 공유를 켰어요." : "음악 공유를 껐어요."
        } catch {
            guard isCurrent(stamp, context) else { return }
            clearIfAccessLost(error)
            if tripMusicFailureIsDefinitive(error) {
                message = "공유 설정이 거절됐어요. 참여 권한을 확인해 주세요."
            } else {
                resultUnknown = true
                message = "공유 설정 결과를 확인하지 못했어요. 목록을 다시 불러와 현재 설정을 확인해 주세요."
            }
        }
    }

    func add() async {
        synchronizeContext()
        guard canAdd, let tripID = preparation.detail?.id else { return }
        let context = contextID, stamp = UUID(); operation = stamp; busy = true; message = nil
        defer { if operation == stamp { busy = false } }
        let submitted = draft
        do {
            let value = try await preparation.activityRequest { try await api.add(tripID, draft: submitted, token: $0) }
            guard isCurrent(stamp, context) else { return }
            try validate(value)
            page = value; pageContext = context; draft = .init()
            message = submitted.reviewConsent ? "추가했어요. 공유 검토가 끝나면 일행에게 보여요." : "추가했어요. 아직 나에게만 보여요."
        } catch {
            guard isCurrent(stamp, context) else { return }
            clearIfAccessLost(error)
            if tripMusicFailureIsDefinitive(error) {
                message = "추가하지 못했어요. 입력과 공유 권한을 확인해 주세요."
            } else {
                resultUnknown = true
                message = "추가 결과를 확인하지 못했어요. 중복 추가를 막기 위해 목록을 새로 불러온 뒤 확인해 주세요."
            }
        }
    }

    enum MoveDirection { case top, up, down }

    func move(_ item: IPhoneTripMusicPage.Item, _ direction: MoveDirection) async {
        synchronizeContext()
        guard !busy, !resultUnknown, let current = visiblePage, current.canReorder,
              let index = current.items.firstIndex(where: { $0.id == item.id }),
              let tripID = preparation.detail?.id else { return }
        let ids = current.items.map(\.id)
        let after: String?
        switch direction {
        case .top: guard index > 0 else { return }; after = nil
        case .up: guard index > 0 else { return }; after = index >= 2 ? ids[index - 2] : nil
        case .down: guard index + 1 < ids.count else { return }; after = ids[index + 1]
        }
        let context = contextID, stamp = UUID(); operation = stamp; busy = true; message = nil
        defer { if operation == stamp { busy = false } }
        do {
            let value = try await preparation.activityRequest { try await api.move(tripID, itemID: item.id, after: after, token: $0) }
            guard isCurrent(stamp, context) else { return }
            try validate(value)
            page = value; pageContext = context
        } catch {
            guard isCurrent(stamp, context) else { return }
            // 403 here means this member is no longer DJ or owner, not that the trip became unreadable.
            let forbidden = (error as? IPhoneSessionError) == .forbidden
            if !forbidden { clearIfAccessLost(error) }
            busy = false; operation = UUID()
            // A position move is idempotent, so reading the list again shows whichever order the server kept.
            if visiblePage != nil { await load() }
            guard contextID == context, hasAccess else { return }
            message = forbidden ? "DJ나 여행 만든 사람만 순서를 바꿀 수 있어요." : "순서를 바꾸지 못했어요. 지금 순서를 확인해 주세요."
        }
    }

    func loadLibrary() async {
        synchronizeContext()
        guard !libraryLoading, hasAccess else { return }
        let context = contextID, stamp = UUID(); libraryOperation = stamp; libraryLoading = true; libraryFailed = false
        defer { if libraryOperation == stamp { libraryLoading = false } }
        do {
            let value = try await preparation.activityRequest { try await api.library(token: $0) }
            guard libraryOperation == stamp, contextID == context, hasAccess else { return }
            library = value
            if let savedSelection, !savedChoices.contains(where: { $0.selection == savedSelection }) { self.savedSelection = nil }
        } catch {
            guard libraryOperation == stamp, contextID == context else { return }
            libraryFailed = true
        }
    }

    /// 저장한 곡 추가는 서버에서 같은 곡을 한 항목으로 유지하므로, 결과를 잃어도 추가를 잠그지 않고 다시 시도할 수 있다.
    func addSaved() async {
        synchronizeContext()
        guard canAddSaved, let selection = savedSelection, let tripID = preparation.detail?.id else { return }
        let context = contextID, stamp = UUID(); operation = stamp; busy = true; message = nil
        defer { if operation == stamp { busy = false } }
        do {
            let value = try await preparation.activityRequest {
                try await api.addSaved(tripID, selection: selection, rightsConfirmed: true, token: $0)
            }
            guard isCurrent(stamp, context) else { return }
            try validate(value)
            page = value; pageContext = context; savedSelection = nil; savedRightsConfirmed = false
            message = "추가했어요. 공유 검토가 끝나면 일행에게 보여요."
        } catch {
            guard isCurrent(stamp, context) else { return }
            clearIfAccessLost(error)
            if case .conflict? = error as? IPhoneResourceError {
                savedSelection = nil
                message = "내 플레이리스트나 여행 목록이 바뀌었어요. 새로 불러온 목록에서 다시 골라 주세요."
                await loadLibrary()
            } else if tripMusicFailureIsDefinitive(error) {
                message = "추가하지 못했어요. 공유 권한과 여행 목록을 확인해 주세요."
            } else {
                message = "추가 결과를 확인하지 못했어요. 같은 곡은 한 번만 추가되니 다시 시도해도 돼요."
            }
        }
    }

    private func synchronizeContext() {
        guard activeContext != contextID else { return }
        if activeContext != nil { draft = .init(); savedSelection = nil; savedRightsConfirmed = false }
        library = nil; libraryFailed = false; libraryOperation = UUID(); libraryLoading = false
        activeContext = contextID; operation = UUID(); busy = false
        page = nil; pageContext = nil; message = nil; resultUnknown = false
    }
    private func isCurrent(_ stamp: UUID, _ context: String) -> Bool {
        operation == stamp && contextID == context && hasAccess
    }
    private func validate(_ value: IPhoneTripMusicPage) throws {
        guard let accountID = preparation.detail?.me?.id, value.permitsDisplay(to: accountID) else {
            throw IPhoneSessionError.invalidResponse
        }
    }
    private func clearIfAccessLost(_ error: Error) {
        if let error = error as? IPhoneSessionError, [.forbidden, .invalidSession, .expired].contains(error) { page = nil }
        if case .missing? = error as? IPhoneResourceError { page = nil }
    }
}

struct TripMusicSavedChoice: Identifiable, Equatable {
    var selection: TripMusicSavedSelection
    var title: String
    var playlistName: String
    var platform: MusicPlatform
    var alreadyAdded: Bool
    var id: String { selection.playlistId + ":" + selection.trackId }
}
