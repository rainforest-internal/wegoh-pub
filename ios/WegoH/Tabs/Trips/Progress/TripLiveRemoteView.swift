import SwiftUI
import Observation
import OSLog

struct TripRemoteDraftKey: Hashable {
    var accountID: String
    var carID: String
    var deviceID: String
    var grantRevision: Int
    var actionID: String
    var area: String?
}

/// 받침에 맞는 주제 조사("설정 온도는", "풍량은"). 한글이 아니면 "은(는)" 대신 "는"을 쓴다.
func tripTopicParticle(_ word: String) -> String {
    let name = word.trimmingCharacters(in: .whitespacesAndNewlines).precomposedStringWithCanonicalMapping
    guard let last = name.unicodeScalars.last?.value, (0xAC00...0xD7A3).contains(last) else { return name + "는" }
    return name + ((last - 0xAC00) % 28 == 0 ? "는" : "은")
}

struct TripRemoteFeedback: Identifiable {
    let id = UUID()
    let message: String
}

struct TripRemoteDraft {
    var temperature = 22.5
    var level = 0
    var enabled = false
    var confirmedTemperature = 22.5
    var confirmedLevel = 0
    var requestedEnabled: Bool?
    var previousEnabled: Bool?
    var pendingToken: UUID?
    var requestID: String?
    var posting = false
    var uncertain = false
    var notice: String?
    var toggleLocked: Bool { pendingToken != nil }
}

@MainActor @Observable
final class TripLiveRemoteStore {
    let preparation: TripPreparationStore
    private let api: any IPhoneTripActivityServing
    private var loadedRemotes: [IPhoneTripRemote] = []
    private var loadedCarID: String?
    private var trackedCommands: [TripRemoteCommandStatus] = []
    private var checkingStatus = false
    private var supportReadGeneration = 0
    private var supportMaintenanceID: UUID?
    var refreshingSupport: Bool { supportMaintenanceID != nil }
    private(set) var drafts: [TripRemoteDraftKey: TripRemoteDraft] = [:]
    private(set) var observationID = UUID()
    private(set) var statusNotice: String?
    var commandResults: [TripRemoteCommandStatus] {
        guard preparation.accountIsCurrent, preparation.detail?.state == .active,
              preparation.detail?.myCar?.id == loadedCarID else { return [] }
        return trackedCommands
    }
    var remotes: [IPhoneTripRemote] {
        guard preparation.accountIsCurrent, preparation.detail?.state == .active,
              preparation.detail?.myCar?.id == loadedCarID else { return [] }
        return loadedRemotes
    }
    private(set) var commandInFlight = false
    private(set) var feedback: TripRemoteFeedback?
    private var commandSubmissionActive = false
    private var feedbackRequestIDs: Set<String> = []
    private var feedbackFailed = false
    private var feedbackUnconfirmed = false
    /// 조작 결과와 함께 알릴 차량 상태 안내(리모컨 받기 꺼짐 등). 일반 실패 문구 대신 보여 준다.
    private var feedbackNotice: String?

    private func beginCommand() {
        commandInFlight = true; commandSubmissionActive = true; feedback = nil
        feedbackRequestIDs = []; feedbackFailed = false; feedbackUnconfirmed = false; feedbackNotice = nil
    }
    private func finishCommandIfReady() {
        guard commandInFlight, !commandSubmissionActive else { return }
        let results = trackedCommands.filter { feedbackRequestIDs.contains($0.id) }
        guard !results.contains(where: \.needsObservation) else { return }
        commandInFlight = false
        let summary = Self.feedbackMessage(results, failed: feedbackFailed, unconfirmed: feedbackUnconfirmed)
        feedback = TripRemoteFeedback(message: feedbackNotice.map { results.isEmpty ? $0 : summary + " " + $0 } ?? summary)
    }
    /// 차량이 리모컨을 받지 않는 상태(리모컨 받기 꺼짐·연결 끊김). 동승자의 권한 상실이 아니므로
    /// 시트와 리모컨 목록, 공조 입력값을 그대로 두고 그 조작의 결과로만 알린다.
    static func vehicleNotReceiving(_ error: Error) -> Bool {
        guard case IPhoneResourceError.tripConflict(let code) = error else { return false }
        return ["VEHICLE_REMOTE_RECEIVER_OFF", "VEHICLE_REMOTE_DISCONNECTED"].contains(code)
    }
    /// 명령 결과 토스트. 여러 조작을 함께 보냈으면 조작별로 알려, 적용된 조작이 다른 조작의 실패에 가려지지 않게 한다.
    static func feedbackMessage(_ results: [TripRemoteCommandStatus], failed: Bool, unconfirmed: Bool) -> String {
        func confirmed(_ result: TripRemoteCommandStatus) -> Bool { result.stage == "state-confirmed" && !result.confirmationUnavailable }
        func uncertain(_ result: TripRemoteCommandStatus) -> Bool {
            result.confirmationUnavailable || result.mayHaveExecuted && result.stage != "state-confirmed"
        }
        if results.count > 1 {
            return results.reversed().map { result in
                tripTopicParticle(result.label) + " " + (confirmed(result) ? "적용했어요" : uncertain(result) ? "확인하지 못했어요" : "적용하지 못했어요")
            }.joined(separator: " · ") + (results.allSatisfy(confirmed) ? "" : ". 차에서 확인해 주세요.")
        }
        if !failed && !unconfirmed && !results.isEmpty && results.allSatisfy(confirmed) { return "적용했어요." }
        return unconfirmed || results.contains(where: uncertain) ? "응답을 확인하지 못했어요. 차에서 확인해 주세요." : "적용하지 못했어요."
    }
    /// 확인된 값과 다른 공조 입력만 보낸다. 바꾸지 않은 조작을 함께 보내 실패가 섞이지 않게 한다.
    func climateValueChanged(_ key: TripRemoteDraftKey) -> Bool {
        let value = draft(key)
        return key.actionID == "hvac.fan" ? value.level != value.confirmedLevel : value.temperature != value.confirmedTemperature
    }
    func dismissFeedback(_ id: UUID) {
        if feedback?.id == id { feedback = nil }
    }

    private(set) var busy = false
    private(set) var message: String?
    init(preparation: TripPreparationStore, api: any IPhoneTripActivityServing = IPhoneTripActivityAPI()) { self.preparation = preparation; self.api = api }
    func draftKey(remote: IPhoneTripRemote, action: IPhoneTripRemote.Action, seat: String?) -> TripRemoteDraftKey {
        .init(accountID: preparation.detail?.me?.id ?? "", carID: preparation.detail?.myCar?.id ?? "",
              deviceID: remote.id, grantRevision: remote.grantRevision, actionID: action.id,
              area: action.argumentKind == "switch" ? nil : seat)
    }
    func draft(_ key: TripRemoteDraftKey) -> TripRemoteDraft {
        drafts[key] ?? TripRemoteDraft(level: key.actionID == "hvac.fan" ? 3 : 0,
                                      confirmedLevel: key.actionID == "hvac.fan" ? 3 : 0)
    }
    func setTemperature(_ value: Double, key: TripRemoteDraftKey) {
        var valueDraft = draft(key); valueDraft.temperature = value; valueDraft.notice = nil; drafts[key] = valueDraft
    }
    func setLevel(_ value: Int, key: TripRemoteDraftKey) {
        var valueDraft = draft(key); valueDraft.level = value; valueDraft.notice = nil; drafts[key] = valueDraft
    }
    func discardDrafts() { drafts = [:] }

    @discardableResult
    func toggle(remote: IPhoneTripRemote, action: IPhoneTripRemote.Action, seat: String?, enabled: Bool) -> Task<Void, Never>? {
        let key = draftKey(remote: remote, action: action, seat: seat)
        var value = draft(key)
        guard !busy, !commandInFlight, preparation.accountIsCurrent, preparation.detail?.state == .active,
              current(remote, action: action), ["switch", "seat-switch"].contains(action.argumentKind),
              action.supportMessage(seat) == nil, !value.toggleLocked, value.enabled != enabled else { return nil }
        let token = UUID()
        value.previousEnabled = value.enabled; value.requestedEnabled = enabled; value.pendingToken = token
        value.requestID = nil; value.posting = true; value.uncertain = false; value.notice = nil
        drafts[key] = value
        beginCommand()
        return Task { await self.submitToggle(remote: remote, action: action, seat: seat ?? "", key: key, token: token) }
    }

    private func submitToggle(remote: IPhoneTripRemote, action: IPhoneTripRemote.Action, seat: String,
                              key: TripRemoteDraftKey, token: UUID) async {
        guard !busy, preparation.accountIsCurrent, preparation.detail?.state == .active,
              current(remote, action: action), action.supportMessage(seat) == nil,
              drafts[key]?.pendingToken == token, let tripID = preparation.detail?.id else {
            rejectToggle(key, token: token, notice: "보내지 못했어요. 현재 허용 범위와 좌석을 확인해 주세요.")
            commandSubmissionActive = false; finishCommandIfReady()
            return
        }
        busy = true
        defer { busy = false; observationID = UUID(); commandSubmissionActive = false; finishCommandIfReady() }
        do {
            let enabled = draft(key).requestedEnabled ?? draft(key).enabled
            let receipt = try await preparation.activityRequest {
                try await api.command(tripID, remote: remote, action: action, seat: seat, value: enabled, token: $0)
            }
            let result = TripRemoteCommandStatus(id: receipt.id, deviceID: remote.id, actionID: action.id,
                label: action.label, stage: receipt.stage, reason: receipt.reason, mayHaveExecuted: receipt.mayHaveExecuted ?? true,
                area: key.area)
            feedbackRequestIDs.insert(receipt.id)
            trackedCommands.removeAll { $0.id == result.id }; trackedCommands.insert(result, at: 0)
            trackedCommands = Array(trackedCommands.prefix(5))
            guard drafts[key]?.pendingToken == token else { return }
            drafts[key]?.requestID = receipt.id
            resolveToggle(key, token: token, stage: receipt.stage, mayHaveExecuted: receipt.mayHaveExecuted)
            message = action.label + " · " + Self.stageTitle(receipt.stage) + ". 실제 작동 여부는 차에서 확인해 주세요."
        } catch {
            guard drafts[key]?.pendingToken == token else { return }
            if Self.vehicleNotReceiving(error) { feedbackNotice = tripPreparationErrorMessage(error) }
            if Self.definiteToggleRejection(error) {
                rejectToggle(key, token: token, notice: tripPreparationErrorMessage(error))
            } else {
                restoreDraft(key, token: token, uncertain: true,
                             notice: "응답을 확인하지 못했어요. 이전 표시로 되돌렸어요. 차량 상태를 확인해 주세요.")
            }
            if tripActivityAccessLost(error) { loadedRemotes = []; trackedCommands = []; await preparation.load() }
        }
    }

    private static func definiteToggleRejection(_ error: Error) -> Bool {
        switch error {
        case IPhoneResourceError.invalidInput, IPhoneResourceError.conflict, IPhoneResourceError.tripConflict(_),
             IPhoneResourceError.missing, IPhoneSessionError.forbidden, IPhoneSessionError.invalidSession,
             IPhoneSessionError.expired, IPhoneTripRequestError.invalidInput, IPhoneTripRequestError.conflict,
             IPhoneTripRequestError.routeConflict(_), IPhoneTripRequestError.missing: true
        default: false
        }
    }
    private func rejectToggle(_ key: TripRemoteDraftKey, token: UUID, notice: String) {
        restoreDraft(key, token: token, uncertain: false, notice: notice + " 이전 입력값으로 되돌렸어요.")
    }
    private func restoreDraft(_ key: TripRemoteDraftKey, token: UUID, uncertain: Bool, notice: String) {
        guard var value = drafts[key], value.pendingToken == token else { return }
        if let previous = value.previousEnabled { value.enabled = previous }
        value.temperature = value.confirmedTemperature; value.level = value.confirmedLevel
        value.pendingToken = nil; value.requestID = nil; value.previousEnabled = nil
        value.requestedEnabled = nil; value.posting = false; value.uncertain = uncertain
        value.notice = notice
        feedbackFailed = true; feedbackUnconfirmed = feedbackUnconfirmed || uncertain
        drafts[key] = value
    }
    private func resolveToggle(_ key: TripRemoteDraftKey, token: UUID, stage: String, mayHaveExecuted: Bool?) {
        guard var value = drafts[key], value.pendingToken == token else { return }
        value.posting = false
        if stage == "state-confirmed" {
            if let enabled = value.requestedEnabled { value.enabled = enabled }
            value.confirmedTemperature = value.temperature; value.confirmedLevel = value.level
            value.requestedEnabled = nil
            value.pendingToken = nil; value.previousEnabled = nil; value.requestID = nil; value.uncertain = false
            value.notice = "적용했어요."
            drafts[key] = value
        } else if ["rejected", "cancelled", "expired"].contains(stage), mayHaveExecuted == false {
            rejectToggle(key, token: token, notice: "차량이 요청을 처리하지 못했어요.")
        } else {
            if IPhoneTripRemoteRequest.terminal.contains(stage) {
                restoreDraft(key, token: token, uncertain: true,
                             notice: "응답을 확인하지 못했어요. 이전 표시로 되돌렸어요. 차량 상태를 확인해 주세요.")
            } else { drafts[key] = value }
        }
    }

    func load() async {
        guard !busy, !checkingStatus, preparation.accountIsCurrent else { return }
        busy = true; message = nil
        defer { busy = false; observationID = UUID() }
        do {
            guard let detail = preparation.detail, detail.state == .active else { throw IPhoneSessionError.forbidden }
            let carID = detail.myCar?.id
            let value = try await preparation.activityRequest { try await api.remotes(detail.id, token: $0) }
            guard preparation.detail?.myCar?.id == carID else { throw CancellationError() }
            if loadedCarID != carID { trackedCommands = []; discardDrafts() }
            loadedCarID = carID; loadedRemotes = value; supportReadGeneration += 1
            mergeStatuses(value, includeRecent: true)
        } catch is CancellationError { loadedRemotes = []; trackedCommands = [] }
        catch { loadedRemotes = []; trackedCommands = []; message = tripPreparationErrorMessage(error); if tripActivityAccessLost(error) { await preparation.load() } }
    }
    func send(remote: IPhoneTripRemote, action: IPhoneTripRemote.Action, seat: String, value: Any) async {
        await sendBundle(remote: remote, seat: seat, commands: [(action, value)])
    }

    func maintainSupport(refreshImmediately: Bool,
                         pause: (TimeInterval) async throws -> Void = { try await Task.sleep(for: .seconds($0)) }) async {
        let maintenanceID = UUID()
        supportMaintenanceID = maintenanceID
        defer { if supportMaintenanceID == maintenanceID { supportMaintenanceID = nil } }
        #if DEBUG
        let logger = Logger(subsystem: "io.wegoh.iphone", category: "remote-support")
        logger.info("remote.support: started immediate=\(refreshImmediately)")
        defer { logger.info("remote.support: stopped cancelled=\(Task.isCancelled)") }
        #endif
        func refresh() async throws -> Bool {
            while busy || checkingStatus { try await pause(1); try Task.checkCancellation() }
            try Task.checkCancellation()
            let previous = supportReadGeneration
            _ = await refreshCommandStatuses()
            #if DEBUG
            let actions = remotes.flatMap(\.actions)
            logger.info("remote.support: loaded applied=\(self.supportReadGeneration != previous) actions=\(actions.count) current=\(actions.filter { $0.support?.isCurrent == true }.count)")
            #endif
            return supportReadGeneration != previous
        }
        do {
            var shouldRefresh = refreshImmediately
            var retryIndex = 0
            let retryDelays: [TimeInterval] = [2, 5, 10, 30]
            while supportMaintenanceID == maintenanceID && preparation.accountIsCurrent && !remotes.isEmpty {
                try Task.checkCancellation()
                if shouldRefresh {
                    let loaded = try await refresh()
                    try Task.checkCancellation()
                    guard preparation.accountIsCurrent && !remotes.isEmpty else { return }
                    let actions = remotes.flatMap(\.actions)
                    let expirations = actions.compactMap { $0.support?.validUntil }
                    if !loaded || expirations.count != actions.count || expirations.isEmpty || expirations.contains(where: { $0 <= .now }) {
                        try await pause(retryDelays[min(retryIndex, retryDelays.count - 1)])
                        retryIndex = min(retryIndex + 1, retryDelays.count - 1)
                        continue
                    }
                    retryIndex = 0
                }
                shouldRefresh = true
                let actions = remotes.flatMap(\.actions)
                let expirations = actions.compactMap { $0.support?.validUntil }
                if expirations.count == actions.count, let expiration = expirations.min() {
                    let delay = expiration.timeIntervalSinceNow
                    if delay > 0 { try await pause(delay) }
                } else {
                    try await pause(retryDelays[retryIndex])
                }
            }
        } catch { }
    }
    func sendBundle(remote: IPhoneTripRemote, seat: String,
                    commands: [(action: IPhoneTripRemote.Action, value: Any)]) async {
        guard !busy, !commandInFlight, preparation.accountIsCurrent, preparation.detail?.state == .active,
              (1...11).contains(commands.count), Set(commands.map { $0.action.id }).count == commands.count,
              commands.allSatisfy({ current(remote, action: $0.action) }) else { return }
        beginCommand()
        busy = true; message = nil
        defer { busy = false; observationID = UUID(); commandSubmissionActive = false; finishCommandIfReady() }
        var stages: [(label: String, title: String)] = []
        var awaitingDraft: (key: TripRemoteDraftKey, token: UUID)?
        do {
            guard let id = preparation.detail?.id else { throw IPhoneSessionError.invalidSession }
            for command in commands {
                guard preparation.accountIsCurrent, preparation.detail?.state == .active,
                      current(remote, action: command.action) else { throw IPhoneSessionError.forbidden }
                if ["hvac.temperature", "hvac.fan"].contains(command.action.id) {
                    let key = draftKey(remote: remote, action: command.action, seat: seat)
                    var value = draft(key)
                    guard !value.toggleLocked else { return }
                    let token = UUID()
                    value.pendingToken = token; value.posting = true; value.uncertain = false; value.notice = nil
                    if let number = command.value as? Double, command.action.id == "hvac.temperature" { value.temperature = number }
                    if let number = command.value as? Int, command.action.id == "hvac.fan" { value.level = number }
                    drafts[key] = value; awaitingDraft = (key, token)
                }
                let receipt = try await preparation.activityRequest {
                    try await api.command(id, remote: remote, action: command.action, seat: seat, value: command.value, token: $0)
                }
                let result = TripRemoteCommandStatus(id: receipt.id, deviceID: remote.id, actionID: command.action.id,
                    label: command.action.label, stage: receipt.stage, reason: receipt.reason,
                    mayHaveExecuted: receipt.mayHaveExecuted ?? false,
                    area: command.action.argumentKind == "switch" ? nil : seat)
                feedbackRequestIDs.insert(receipt.id)
                trackedCommands.removeAll { $0.id == result.id }
                trackedCommands.insert(result, at: 0)
                trackedCommands = Array(trackedCommands.prefix(5))
                if let pending = awaitingDraft {
                    drafts[pending.key]?.requestID = receipt.id
                    resolveToggle(pending.key, token: pending.token, stage: receipt.stage, mayHaveExecuted: receipt.mayHaveExecuted)
                    awaitingDraft = nil
                }
                statusNotice = nil
                stages.append((command.action.label, Self.stageTitle(receipt.stage)))
                if commands.count > 1, ["rejected", "cancelled", "expired", "unknown"].contains(receipt.stage) {
                    restoreUnsubmittedClimateDrafts(remote: remote, seat: seat, commands: commands)
                    message = stages.map { $0.label + " · " + $0.title }.joined(separator: " / ")
                        + ". 나머지 명령은 보내지 않았어요. 실제 작동 여부는 차에서 확인해 주세요."
                    return
                }
            }
            if commands.count == 1 {
                message = "명령 상태: " + stages[0].title + ". 실제 작동 여부는 차에서 확인해 주세요."
            } else {
                message = stages.map { $0.label + " · " + $0.title }.joined(separator: " / ") + ". 실제 작동 여부는 차에서 확인해 주세요."
            }
        } catch is CancellationError {
            feedbackUnconfirmed = true
            if let pending = awaitingDraft {
                restoreDraft(pending.key, token: pending.token, uncertain: true,
                             notice: "응답을 확인하지 못했어요. 이전 표시로 되돌렸어요. 차량 상태를 확인해 주세요.")
            }
            restoreUnsubmittedClimateDrafts(remote: remote, seat: seat, commands: commands)
            if !stages.isEmpty && preparation.accountIsCurrent {
                message = "\(stages.count)개 명령을 전달했고 나머지는 중단했어요. 실제 작동 여부는 차에서 확인해 주세요."
            }
        } catch {
            let notReceiving = Self.vehicleNotReceiving(error)
            feedbackFailed = true; feedbackUnconfirmed = !Self.definiteToggleRejection(error)
            if notReceiving { feedbackNotice = tripPreparationErrorMessage(error) }
            if let pending = awaitingDraft {
                if notReceiving { keepUnsentDraft(pending.key, token: pending.token, notice: tripPreparationErrorMessage(error)) }
                else if Self.definiteToggleRejection(error) { rejectToggle(pending.key, token: pending.token, notice: tripPreparationErrorMessage(error)) }
                else { restoreDraft(pending.key, token: pending.token, uncertain: true,
                                    notice: "응답을 확인하지 못했어요. 이전 표시로 되돌렸어요. 차량 상태를 확인해 주세요.") }
            }
            // 차량이 받지 않아 보내지 못한 입력은 그대로 두어, 리모컨 받기가 켜지면 같은 값으로 다시 적용할 수 있게 한다.
            if !notReceiving { restoreUnsubmittedClimateDrafts(remote: remote, seat: seat, commands: commands) }
            let partial = stages.isEmpty ? "" : "\(stages.count)개 명령을 전달했고 나머지는 보내지 못했어요. "
            message = partial + tripPreparationErrorMessage(error) + (notReceiving ? "" : " 허용 범위를 다시 확인해 주세요.")
            if tripActivityAccessLost(error) { loadedRemotes = []; trackedCommands = []; statusNotice = nil; await preparation.load() }
        }
    }
    /// 보내지 못한 공조 입력을 확인된 값으로 되돌리지 않고 잠금만 푼다.
    private func keepUnsentDraft(_ key: TripRemoteDraftKey, token: UUID, notice: String) {
        guard var value = drafts[key], value.pendingToken == token else { return }
        value.pendingToken = nil; value.requestID = nil; value.previousEnabled = nil
        value.requestedEnabled = nil; value.posting = false; value.uncertain = false
        value.notice = notice
        drafts[key] = value
    }
    private func restoreUnsubmittedClimateDrafts(remote: IPhoneTripRemote, seat: String,
                                                commands: [(action: IPhoneTripRemote.Action, value: Any)]) {
        for command in commands where ["hvac.temperature", "hvac.fan"].contains(command.action.id) {
            let key = draftKey(remote: remote, action: command.action, seat: seat)
            guard var value = drafts[key], value.pendingToken == nil, value.notice == nil else { continue }
            value.temperature = value.confirmedTemperature; value.level = value.confirmedLevel
            value.notice = "적용하지 못했어요. 이전 입력값으로 되돌렸어요."
            drafts[key] = value
        }
    }
    func observeCommandStatuses(maximumReads: Int = 16,
                                pause: () async throws -> Void = { try await Task.sleep(for: .seconds(2)) }) async {
        let generation = observationID
        guard maximumReads > 0 else { return }
        do {
            for index in 0..<min(maximumReads, 16) {
                try Task.checkCancellation()
                guard generation == observationID, commandResults.contains(where: \.needsObservation) else { return }
                if index > 0 { try await pause() }
                try Task.checkCancellation()
                guard generation == observationID else { return }
                if busy || checkingStatus { try await pause(); continue }
                if !(await refreshCommandStatuses()) { return }
            }
            if generation == observationID && commandResults.contains(where: \.needsObservation) {
                markUnconfirmed("추가 상태 확인을 멈췄어요. 상태 다시 확인을 눌러 마지막 응답을 확인할 수 있어요.")
            }
        } catch is CancellationError { }
        catch { }
    }

    @discardableResult
    func refreshCommandStatuses() async -> Bool {
        guard !busy, !checkingStatus, preparation.accountIsCurrent,
              let detail = preparation.detail, detail.state == .active,
              detail.myCar?.id == loadedCarID else { return false }
        let generation = observationID
        let carID = loadedCarID
        checkingStatus = true
        defer { checkingStatus = false; finishCommandIfReady() }
        do {
            let value = try await preparation.activityRequest { try await api.remotes(detail.id, token: $0) }
            try Task.checkCancellation()
            guard generation == observationID, preparation.accountIsCurrent,
                  preparation.detail?.state == .active, preparation.detail?.myCar?.id == carID else { return false }
            loadedRemotes = value
            supportReadGeneration += 1
            if value.isEmpty {
                markUnconfirmed("차량의 현재 허용 상태로 결과를 확인할 수 없어요.")
                trackedCommands = []
                statusNotice = "차량의 허용 상태가 바뀌어 명령 결과를 확인할 수 없어요. 실제 작동 여부는 차에서 확인해 주세요."
                return false
            }
            mergeStatuses(value, includeRecent: false)
            return commandResults.contains(where: \.needsObservation)
        } catch is CancellationError { return false }
        catch {
            guard generation == observationID else { return false }
            if tripActivityAccessLost(error) {
                loadedRemotes = []; trackedCommands = []; statusNotice = nil
                message = tripPreparationErrorMessage(error)
                await preparation.load()
            } else {
                markUnconfirmed("최신 응답을 확인하지 못했어요. 아래는 마지막 확인 상태예요. 명령은 자동으로 다시 보내지 않아요.")
            }
            return false
        }
    }

    private func mergeStatuses(_ remotes: [IPhoneTripRemote], includeRecent: Bool) {
        defer { finishCommandIfReady() }
        statusNotice = nil
        let requests = remotes.flatMap { remote in
            (remote.requests ?? []).map { (remote, $0) }
        }
        for index in trackedCommands.indices {
            guard let (_, request) = requests.first(where: { $0.1.id == trackedCommands[index].id
                && $0.0.id == trackedCommands[index].deviceID && $0.1.capabilityId == trackedCommands[index].actionID }) else {
                if trackedCommands[index].needsObservation { trackedCommands[index].confirmationUnavailable = true }
                continue
            }
            trackedCommands[index].stage = request.stage
            trackedCommands[index].reason = request.reason
            trackedCommands[index].mayHaveExecuted = request.mayHaveExecuted
            trackedCommands[index].confirmationUnavailable = false
        }
        if includeRecent {
            for (remote, request) in requests where !trackedCommands.contains(where: { $0.id == request.id }) {
                guard let action = remote.actions.first(where: { $0.id == request.capabilityId }) else { continue }
                trackedCommands.append(.init(id: request.id, deviceID: remote.id, actionID: action.id, label: action.label,
                    stage: request.stage, reason: request.reason, mayHaveExecuted: request.mayHaveExecuted))
            }
            trackedCommands = Array(trackedCommands.prefix(5))
        }
        for key in Array(drafts.keys) {
            guard let value = drafts[key], let token = value.pendingToken, let id = value.requestID else { continue }
            if let (_, request) = requests.first(where: { $0.1.id == id && $0.0.id == key.deviceID && $0.1.capabilityId == key.actionID }) {
                resolveToggle(key, token: token, stage: request.stage, mayHaveExecuted: request.mayHaveExecuted)
            } else {
                restoreDraft(key, token: token, uncertain: true,
                             notice: "응답을 확인하지 못했어요. 이전 표시로 되돌렸어요. 차량 상태를 확인해 주세요.")
            }
        }
        if !trackedCommands.isEmpty {
            message = trackedCommands.map { $0.label + " · " + $0.title
                + ($0.confirmationUnavailable ? " (최신 결과 확인 불가)" : "") }.joined(separator: " / ")
                + ". 실제 작동 여부는 차에서 확인해 주세요."
        }
        if trackedCommands.contains(where: \.confirmationUnavailable) {
            statusNotice = "현재 응답 목록에 없는 요청은 결과를 확인할 수 없어요. 명령은 자동으로 다시 보내지 않아요."
        }
    }

    private func markUnconfirmed(_ notice: String) {
        if commandInFlight { feedbackUnconfirmed = true }
        defer { finishCommandIfReady() }
        for index in trackedCommands.indices where trackedCommands[index].needsObservation {
            trackedCommands[index].confirmationUnavailable = true
        }
        for key in Array(drafts.keys) where drafts[key]?.pendingToken != nil && drafts[key]?.posting == false {
            if let token = drafts[key]?.pendingToken {
                restoreDraft(key, token: token, uncertain: true,
                             notice: "응답을 확인하지 못했어요. 이전 표시로 되돌렸어요. 차량 상태를 확인해 주세요.")
            }
        }
        statusNotice = notice
    }

    private func current(_ remote: IPhoneTripRemote, action: IPhoneTripRemote.Action) -> Bool {
        remotes.contains { $0.id == remote.id && $0.grantRevision == remote.grantRevision
            && $0.actions.contains { $0.id == action.id && $0.revision == action.revision } }
    }
    nonisolated static func stageTitle(_ stage: String) -> String {
        switch stage {
        case "queued": "전달 대기"; case "delivered": "전달됨"; case "received": "차량 수신"
        case "sdk-accepted": "차량에 접수됨"; case "state-confirmed": "차량 응답 확인"
        case "rejected": "거절됨"; case "cancelled": "취소됨"; case "expired": "만료됨"; default: "확인할 수 없음"
        }
    }
}

struct TripRemoteCommandStatus: Identifiable {
    var id: String
    var deviceID: String
    var actionID: String
    var label: String
    var stage: String
    var reason: String?
    var mayHaveExecuted: Bool
    var confirmationUnavailable = false
    var area: String? = nil
    var needsObservation: Bool { !confirmationUnavailable && !IPhoneTripRemoteRequest.terminal.contains(stage) }
    var title: String { TripLiveRemoteStore.stageTitle(stage) }
    var reasonTitle: String? {
        switch reason {
        case "expired": "요청의 유효 시간이 지났어요."
        case "lease-expired": "차량의 처리 확인 시간이 지났어요."
        case "superseded": "같은 조작의 새 요청으로 바뀌었어요."
        case "receiver-paused": "차량의 리모컨 수신이 꺼져 있어요."
        case "driving-restricted": "주행 중이라 차량이 실행하지 않았어요."
        case "explicit-cancellation": "요청이 취소됐어요."
        case "trip-context-withdrawn", "source-permission-withdrawn": "여행의 리모컨 허용이 변경됐어요."
        case "friendship-ended", "device-revoked": "현재 연결로는 명령을 확인할 수 없어요."
        default: stage == "rejected" ? "차량이 명령을 거절했어요." : nil
        }
    }
}

struct TripLiveRemoteView: View {
    @State private var store: TripLiveRemoteStore
    @State private var hasLoaded = false
    @State private var wasBackgrounded = false
    @Environment(\.dismiss) private var dismiss
    @Environment(\.scenePhase) private var scenePhase
    init(preparation: TripPreparationStore, api: IPhoneTripActivityAPI = .init()) { _store = State(initialValue: TripLiveRemoteStore(preparation: preparation, api: api)) }
    var body: some View {
        NavigationStack { content }
            .disabled(store.commandInFlight)
            .interactiveDismissDisabled(store.commandInFlight)
            .overlay {
                if store.commandInFlight {
                    ZStack {
                        WegoTokens.Palette.ink.opacity(WegoTokens.Opacity.modalScrim)
                        ProgressView().tint(WegoTokens.Palette.onInk).controlSize(.large)
                    }
                    .ignoresSafeArea()
                    .contentShape(Rectangle())
                    .accessibilityElement(children: .ignore).accessibilityLabel("적용 중")
                    .accessibilityIdentifier("tripRemoteScreenLoading")
                }
            }
            .overlay(alignment: .bottom) {
                if let feedback = store.feedback, !store.commandInFlight {
                    Text(feedback.message)
                        .font(WegoTokens.Typography.label)
                        .foregroundStyle(WegoTokens.Palette.onInk)
                        .padding(WegoTokens.Space.medium)
                        .frame(maxWidth: .infinity)
                        .background(WegoTokens.Palette.ink, in: RoundedRectangle(cornerRadius: WegoTokens.Radius.control))
                        .padding(WegoTokens.Space.screen)
                        .accessibilityIdentifier("tripRemoteToast")
                        .allowsHitTesting(false)
                        .task(id: feedback.id) {
                            do {
                                try await Task.sleep(for: .seconds(WegoTokens.Motion.toastDuration))
                                store.dismissFeedback(feedback.id)
                            } catch { }
                        }
                }
            }
    }
    private var content: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: WegoTokens.Space.medium) {
                if !hasLoaded && store.remotes.isEmpty { WegoLoadingView("차량 리모컨 확인 중", layout: .detail) }
                if hasLoaded && store.remotes.isEmpty && !store.busy {
                    if let message = store.message {
                        WegoLoadingFailureView(message: message, messageIdentifier: "tripRemoteCommandStatus") { Task { await store.load() } }
                    } else {
                        Text("지금 사용할 수 있는 리모컨이 없어요. 운전자의 허용과 차량 수신 상태를 확인해 주세요.").font(WegoTokens.Typography.label)
                    }
                }
                ForEach(store.remotes) { remote in
                    HStack(alignment: .top, spacing: WegoTokens.Space.compact) {
                        AvatarBadge(name: remote.ownerName, tone: .ink)
                        VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
                            Text(store.preparation.detail.flatMap { detail in detail.myCar.map { detail.numberedName($0) } } ?? remote.deviceName)
                                .font(WegoTokens.Typography.cardTitle)
                        }
                    }
                    TripRemoteDashboard(store: store, remote: remote, busy: store.busy) { action, seat, value in
                        Task { await store.send(remote: remote, action: action, seat: seat, value: value) }
                    } applyClimate: { seat, commands in
                        await store.sendBundle(remote: remote, seat: seat, commands: commands)
                    }
                    .id(remote.id + ":" + String(remote.grantRevision))

                }
            }.padding(WegoTokens.Space.screen)
        }
        .foregroundStyle(WegoTokens.Palette.text).background(WegoTokens.Palette.background)
        .navigationTitle("여행 리모컨").navigationBarTitleDisplayMode(.inline)
        .toolbar(.visible, for: .navigationBar)
        .toolbar {
            ToolbarItem(placement: .cancellationAction) { Button("닫기") { dismiss() } }
        }
        .task { await store.load(); hasLoaded = true }
        .onDisappear { store.discardDrafts() }
        .onChange(of: scenePhase) { _, phase in
            #if DEBUG
            Logger(subsystem: "io.wegoh.iphone", category: "remote-support")
                .info("remote.scene: changed phase=\(String(describing: phase), privacy: .public)")
            #endif
            if phase == .background { wasBackgrounded = true }
        }
        .task(id: scenePhase == .active && hasLoaded) {
            guard scenePhase == .active && hasLoaded else { return }
            let refreshImmediately = wasBackgrounded
            wasBackgrounded = false
            await store.maintainSupport(refreshImmediately: refreshImmediately)
        }
        .task(id: scenePhase == .active ? store.observationID : nil) {
            guard scenePhase == .active else { return }
            await store.observeCommandStatuses()
        }
    }
}

private extension IPhoneTripRemote.Action {
    var availableSupport: IPhoneTripRemote.Support? { support?.isFresh == true ? support : nil }
    func supportedArea(_ seat: String?) -> IPhoneTripRemote.Support.Area? {
        guard let seat, let support = availableSupport, TripRemoteSeats.allows(id, seat: seat, support: support) else { return nil }
        return support.areas.first { $0.id == seat }
    }
    func supportMessage(_ seat: String?) -> String? {
        guard let support else { return "차량의 지원 정보를 아직 확인하지 못했어요. 허용 범위를 다시 확인해 주세요." }
        guard support.status == "known" && support.isCurrent else { return "차량의 최신 지원 정보를 확인해 주세요." }
        if !support.available { return "이 차량에서 지원하지 않는 조작이에요." }
        if argumentKind != "switch" && supportedArea(seat) == nil {
            guard let seat else { return "조절할 좌석을 먼저 선택해 주세요." }
            if seat == TripRemoteSeats.driver { return "운전석은 원격으로 조절할 수 없어요." }
            if !TripRemoteSeats.allows(id, seat: seat, support: support) {
                return "운전석과 함께 바뀌는 좌석이라 원격으로 조절할 수 없어요."
            }
            let supported = TripRemoteSeats.order.filter { seat in
                support.areas.contains { $0.id == seat } && TripRemoteSeats.allows(id, seat: seat, support: support)
            }.map(tripRemoteSeatTitle)
            return tripRemoteSeatTitle(seat) + "에서는 지원하지 않는 조작이에요."
                + (supported.isEmpty ? "" : " " + supported.joined(separator: "·") + "에서 조절할 수 있어요.")
        }
        return nil
    }
    /// 고른 좌석이 다른 좌석과 한 SDK 구역으로 묶여 있으면 함께 바뀌는 좌석을 알린다.
    func sharedNotice(_ seat: String?) -> String? {
        guard let seat, supportedArea(seat) != nil, let support = availableSupport else { return nil }
        if TripRemoteSeats.carWide.contains(id) { return "운전석을 포함한 차 전체에 적용돼요." }
        let others = support.zone(of: seat).filter { $0 != seat }.map(tripRemoteSeatTitle)
        guard let first = others.first else { return nil }
        return others.count <= 2 ? others.joined(separator: "·") + "도 함께 바뀌어요." : "\(first) 등 \(others.count)개 좌석도 함께 바뀌어요."
    }
}

/// 리모컨 "조절할 좌석" 선택지. 차량이 기능별로 보고한 지원 좌석과 조절 구역에서 만든다.
enum TripRemoteSeats {
    static let order = (1...3).flatMap { row in ["LEFT", "CENTER", "RIGHT"].map { "ROW_\(row)_\($0)" } }
    /// 원격 조작에서 늘 빼는 운전석. Pleos 차량 SDK에 운전석 위치 API가 없어 차량 앱·서버와 같이 좌측 운전석으로 본다.
    static let driver = "ROW_1_LEFT"
    /// 차 전체 공조 전원. Pleos SDK가 전역 전원으로 정의해 고른 좌석과 관계없이 운전석을 포함한 차 전체에 적용된다.
    /// 풍량·에어컨·공기청정은 고른 좌석의 SDK 구역을 바꾸므로 온도처럼 운전석과 한 구역이면 조절하지 않는다.
    static let carWide: Set<String> = ["hvac.power"]
    /// 좌석을 받는 기능의 지원 정보를 하나도 받지 못했을 때 보이는 4인 차량 기준 좌석(운전석 제외).
    static let fallback = ["ROW_1_RIGHT", "ROW_2_LEFT", "ROW_2_RIGHT"]

    /// 운전석은 어떤 기능에서도 조절하지 않고, 좌석별 기능은 운전석과 한 구역으로 묶인 좌석도 조절하지 않는다.
    static func allows(_ actionID: String, seat: String, support: IPhoneTripRemote.Support) -> Bool {
        seat != driver && (carWide.contains(actionID) || !support.zone(of: seat).contains(driver))
    }

    static func usesFallback(_ actions: [IPhoneTripRemote.Action]) -> Bool {
        let seated = actions.filter { $0.argumentKind != "switch" }
        return !seated.isEmpty && !seated.contains { $0.support?.status == "known" }
    }

    /// 어느 기능에서든 단독으로 조절되는 좌석은 모두 보이고, 여러 좌석이 묶인 구역은 그 구역의 좌석이
    /// 하나도 보이지 않을 때만 첫 좌석을 대표로 보인다. 실내 전체 공조처럼 넓은 구역 때문에 따로
    /// 조절할 수 없는 가운데·3열 좌석이 선택지에 늘어나지 않는다. 운전석은 대표로도 고르지 않는다.
    static func options(_ actions: [IPhoneTripRemote.Action]) -> [String] {
        if usesFallback(actions) { return fallback }
        var shown = Set<String>()
        var zones: [[String]] = []
        for action in actions where action.argumentKind != "switch" {
            guard let support = action.support, support.status == "known", support.available else { continue }
            let seats = Set(support.areas.map(\.id).filter { allows(action.id, seat: $0, support: support) })
            shown.formUnion(seats.filter { support.zone(of: $0).count == 1 })
            zones += support.zones.map { zone in order.filter { zone.contains($0) && seats.contains($0) } }.filter { !$0.isEmpty }
        }
        zones.sort { (order.firstIndex(of: $0[0]) ?? 0) < (order.firstIndex(of: $1[0]) ?? 0) }
        for zone in zones where shown.isDisjoint(with: zone) { shown.insert(zone[0]) }
        return order.filter(shown.contains)
    }
}

private struct TripRemoteDashboard: View {
    let store: TripLiveRemoteStore
    let remote: IPhoneTripRemote
    let busy: Bool
    let send: (IPhoneTripRemote.Action, String, Any) -> Void
    let applyClimate: (String, [(action: IPhoneTripRemote.Action, value: Any)]) async -> Void
    @State private var seat: String?
    @State private var submittingClimate = false
    private var temperature: Double {
        get { action("hvac.temperature").map { store.draft(store.draftKey(remote: remote, action: $0, seat: seat)).temperature } ?? 22.5 }
        nonmutating set { if let action = action("hvac.temperature") { store.setTemperature(newValue, key: store.draftKey(remote: remote, action: action, seat: seat)) } }
    }
    private var fan: Int {
        get { action("hvac.fan").map { store.draft(store.draftKey(remote: remote, action: $0, seat: seat)).level } ?? 3 }
        nonmutating set { if let action = action("hvac.fan") { store.setLevel(newValue, key: store.draftKey(remote: remote, action: action, seat: seat)) } }
    }
    private var seats: [String] { TripRemoteSeats.options(remote.actions) }
    private var hasSeatedActions: Bool { remote.actions.contains { $0.argumentKind != "switch" } }
    private var climatePending: Bool {
        ["hvac.temperature", "hvac.fan"].contains { id in
            guard let action = action(id) else { return false }
            return store.draft(store.draftKey(remote: remote, action: action, seat: seat)).toggleLocked
        }
    }

    var body: some View {
        TimelineView(.periodic(from: .now, by: 1)) { _ in
            VStack(alignment: .leading, spacing: WegoTokens.Space.large) {
                if hasSeatedActions {
                    SectionHeader("조절할 좌석")
                    if seats.isEmpty {
                        Text(store.refreshingSupport ? "차량이 지원하는 좌석을 자동으로 확인하고 있어요."
                             : "이 차량에서 지금 좌석별로 조절할 수 있는 기능이 없어요.")
                            .foregroundStyle(WegoTokens.Palette.secondary)
                    } else {
                        ChoiceChips(options: seats.map(Self.seatTitle), selection: Binding(
                            get: { seat.map { [Self.seatTitle($0)] } ?? [] },
                            set: { selection in if let value = seats.first(where: { selection.contains(Self.seatTitle($0)) }) { seat = value } }
                        ), allowsMultipleSelection: false)
                        .disabled(busy || submittingClimate || climatePending)
                        .accessibilityIdentifier("tripRemoteSeatSelection")
                        Text((seat.map { Self.seatTitle($0) + "의 설정을 조절해요." } ?? "조절할 좌석을 직접 선택해 주세요.") + " 운전석은 원격으로 조절할 수 없어요.")
                            .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
                            .accessibilityIdentifier("tripRemoteChooseSupportedSeat")
                        if TripRemoteSeats.usesFallback(remote.actions) {
                            Text("차량의 지원 좌석을 받기 전이라 기본 네 좌석을 보여 줘요. 지원 정보를 받으면 조절할 수 있어요.")
                                .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
                                .accessibilityIdentifier("tripRemoteFallbackSeats")
                        }
                    }
                }
                if remote.actions.contains(where: { $0.id.hasPrefix("hvac.") }) {
                    WegoCard(.ink) {
                        Text("공조 · " + (seat.map(Self.seatTitle) ?? "좌석 선택"))
                            .font(WegoTokens.Typography.section)
                        if let action = action("hvac.temperature") {
                            VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
                                Text("설정 온도").foregroundStyle(WegoTokens.Palette.onInkSecondary)
                                HStack(spacing: WegoTokens.Space.medium) {
                                    adjustment("minus", label: "온도 내리기", enabled: canAdjustTemperature(-1)) { adjustTemperature(-1) }
                                    TextField("설정 온도", value: Binding(get: { temperature }, set: { temperature = $0 }), format: .number)
                                        .keyboardType(.decimalPad).multilineTextAlignment(.center)
                                        .font(WegoTokens.Typography.hero).monospacedDigit()
                                        .disabled(action.supportedArea(seat) == nil)
                                    Text("°C").font(WegoTokens.Typography.cardTitle)
                                    adjustment("plus", label: "온도 올리기", enabled: canAdjustTemperature(1)) { adjustTemperature(1) }
                                }.accessibilityIdentifier("tripRemoteTemperature")
                                supportHint(action, number: temperature, onInk: true)
                            }
                        }
                        if let action = action("hvac.fan") {
                            VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
                                HStack(spacing: WegoTokens.Space.medium) {
                                    Text("풍량 단계").foregroundStyle(WegoTokens.Palette.onInkSecondary)
                                    adjustment("minus", label: "풍량 줄이기", enabled: action.supportedArea(seat)?.contains(Double(fan - 1)) == true) { fan -= 1 }
                                    TextField("풍량", value: Binding(get: { fan }, set: { fan = $0 }), format: .number).keyboardType(.numberPad)
                                        .multilineTextAlignment(.center).font(WegoTokens.Typography.cardTitle)
                                        .disabled(action.supportedArea(seat) == nil)
                                    adjustment("plus", label: "풍량 늘리기", enabled: action.supportedArea(seat)?.contains(Double(fan + 1)) == true) { fan += 1 }
                                }.accessibilityIdentifier("tripRemoteFan")
                                supportHint(action, number: Double(fan), onInk: true)
                            }
                        }
                        Button("설정 적용") {
                            let commands = climateCommands
                            guard let seat, !commands.isEmpty, !busy, !submittingClimate else { return }
                            submittingClimate = true
                            Task {
                                await applyClimate(seat, commands)
                                submittingClimate = false
                            }
                        }.buttonStyle(.wego(.soft)).disabled(busy || submittingClimate || climateCommands.isEmpty)
                            .accessibilityLabel(climateTitle).accessibilityIdentifier("tripRemoteApplyClimate")
                    }
                    ForEach(remote.actions.filter { $0.id.hasPrefix("hvac.") && !["hvac.temperature", "hvac.fan"].contains($0.id) }) { action in
                        WegoCard(.surface) { TripRemoteSettingRow(store: store, remote: remote, action: action, seat: seat, send: send) }
                    }
                }
                ForEach([TripRemoteGroup.windows, .lights, .seats]) { group in
                    let actions = remote.actions.filter { group.actionIDs.contains($0.id) }
                    if !actions.isEmpty {
                        WegoCard(.surface) {
                            Text(group.title).font(WegoTokens.Typography.section)
                            ForEach(actions) { action in TripRemoteSettingRow(store: store, remote: remote, action: action, seat: seat, send: send) }
                            if group == .seats { Text("시트 열선·통풍은 정차 중에만 실행돼요.").font(WegoTokens.Typography.caption) }
                            if group == .lights && actions.contains(where: { $0.id == "light.cabin" }) {
                                Text("실내등은 정차 중에만 실행돼요.").font(WegoTokens.Typography.caption)
                            }
                        }
                    }
                }
            }.font(WegoTokens.Typography.body)
        }
        .onChange(of: seats) { _, options in
            if let seat, !options.contains(seat) { self.seat = nil }
        }
    }

    private func action(_ id: String) -> IPhoneTripRemote.Action? { remote.actions.first { $0.id == id } }
    private var climateCommands: [(action: IPhoneTripRemote.Action, value: Any)] {
        var result: [(action: IPhoneTripRemote.Action, value: Any)] = []
        if let action = action("hvac.temperature"), action.supportedArea(seat)?.contains(temperature) == true,
           store.climateValueChanged(store.draftKey(remote: remote, action: action, seat: seat)) { result.append((action, temperature)) }
        if let action = action("hvac.fan"), action.supportedArea(seat)?.contains(Double(fan)) == true,
           store.climateValueChanged(store.draftKey(remote: remote, action: action, seat: seat)) { result.append((action, fan)) }
        return result
    }
    private var climateTitle: String {
        let titles = climateCommands.map { $0.action.id == "hvac.temperature" ? "온도 \(temperature.formatted())°C" : "풍량 \(fan)" }
        let supported = ["hvac.temperature", "hvac.fan"].contains { id in action(id).map { $0.supportedArea(seat) != nil } == true }
        if titles.isEmpty && supported { return "바꾼 설정이 없어요" }
        return titles.isEmpty ? "지원 좌석과 설정값을 확인해 주세요" : (seat.map(Self.seatTitle) ?? "좌석 선택") + " · " + titles.joined(separator: " · ") + " 적용"
    }
    private func canAdjustTemperature(_ direction: Double) -> Bool {
        guard let area = action("hvac.temperature")?.supportedArea(seat), let step = area.step else { return false }
        return area.contains(temperature + direction * step)
    }
    private func adjustTemperature(_ direction: Double) {
        guard canAdjustTemperature(direction), let step = action("hvac.temperature")?.supportedArea(seat)?.step else { return }
        temperature += direction * step
    }
    @ViewBuilder private func supportHint(_ action: IPhoneTripRemote.Action, number: Double, onInk: Bool) -> some View {
        if store.refreshingSupport && action.support?.isCurrent != true {
            Text("차량 지원 정보를 자동으로 확인하고 있어요.").font(WegoTokens.Typography.caption)
                .foregroundStyle(onInk ? WegoTokens.Palette.onInkSecondary : WegoTokens.Palette.secondary)
        } else if let message = action.supportMessage(seat) {
            Text(message).font(WegoTokens.Typography.caption)
                .foregroundStyle(onInk ? WegoTokens.Palette.onInkSecondary : WegoTokens.Palette.secondary)
        } else if let area = action.supportedArea(seat), let min = area.min, let max = area.max {
            Text("지원 범위 \(min.formatted())–\(max.formatted())" + (area.step.map { " · \($0.formatted())씩" } ?? " · 값을 직접 입력해 주세요"))
                .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.onInkSecondary)
            if !area.contains(number) { Text("지원 범위의 설정값을 직접 입력해 주세요.").font(WegoTokens.Typography.caption) }
            if let notice = action.sharedNotice(seat) {
                Text(notice).font(WegoTokens.Typography.caption)
                    .foregroundStyle(onInk ? WegoTokens.Palette.onInkSecondary : WegoTokens.Palette.secondary)
            }
        }
    }
    private func adjustment(_ symbol: String, label: String, enabled: Bool, change: @escaping () -> Void) -> some View {
        Button(action: change) {
            Image(systemName: symbol).font(WegoTokens.Typography.cardTitle)
                .frame(minWidth: WegoTokens.Metrics.touchTarget, minHeight: WegoTokens.Metrics.touchTarget)
                .contentShape(Rectangle())
        }.buttonStyle(.plain).disabled(!enabled).accessibilityLabel(label)
    }
    private static func seatTitle(_ value: String) -> String { tripRemoteSeatTitle(value) }
}

private func tripRemoteSeatTitle(_ value: String) -> String {
    switch value {
    case "ROW_1_LEFT": "운전석"
    case "ROW_1_RIGHT": "조수석"
    case "ROW_2_LEFT": "뒷좌석 왼쪽"
    case "ROW_2_CENTER": "뒷좌석 가운데"
    case "ROW_2_RIGHT": "뒷좌석 오른쪽"
    case "ROW_3_LEFT": "3열 왼쪽"
    case "ROW_3_CENTER": "3열 가운데"
    case "ROW_3_RIGHT": "3열 오른쪽"
    default: "좌석 선택"
    }
}

private struct TripRemoteSettingRow: View {
    let store: TripLiveRemoteStore
    let remote: IPhoneTripRemote
    let action: IPhoneTripRemote.Action
    let seat: String?
    let send: (IPhoneTripRemote.Action, String, Any) -> Void
    private var key: TripRemoteDraftKey { store.draftKey(remote: remote, action: action, seat: seat) }
    private var draft: TripRemoteDraft { store.draft(key) }
    private var level: Int {
        get { draft.level }
        nonmutating set { store.setLevel(newValue, key: key) }
    }
    private var targetTitle: String { action.argumentKind == "switch" ? "차 전체" : seat.map(tripRemoteSeatTitle) ?? "좌석 선택" }
    private var area: IPhoneTripRemote.Support.Area? { action.supportedArea(seat) }
    private var permitted: Bool { action.supportMessage(seat) == nil }
    var body: some View {
        VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
            if !["seat-switch", "switch"].contains(action.argumentKind) {
                Text(action.label + " · 요청 대상 " + targetTitle).font(WegoTokens.Typography.label)
            }
            if store.refreshingSupport && action.support?.isCurrent != true {
                Text("차량 지원 정보를 자동으로 확인하고 있어요.").font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
            } else if let message = action.supportMessage(seat) {
                Text(message).font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
            } else if let notice = action.sharedNotice(seat) {
                Text(notice).font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
            }
            if ["seat-switch", "switch"].contains(action.argumentKind) {
                Toggle(action.label, isOn: Binding(get: { draft.enabled }, set: { value in
                    _ = store.toggle(remote: remote, action: action, seat: seat, enabled: value)
                }))
                .disabled(store.busy || !permitted || draft.toggleLocked)
                .tint(WegoTokens.Palette.accent)
                .accessibilityLabel(action.label + " · " + targetTitle)
                .accessibilityIdentifier("tripRemoteToggle-" + action.id)
            } else {
                HStack(spacing: WegoTokens.Space.small) {
                    TextField("설정값", value: Binding(get: { level }, set: { level = $0 }), format: .number).keyboardType(.numberPad).disabled(!permitted)
                    Stepper("설정값 조절", onIncrement: { if area?.contains(Double(level + 1)) == true { level += 1 } },
                            onDecrement: { if area?.contains(Double(level - 1)) == true { level -= 1 } })
                        .labelsHidden().disabled(!permitted)
                }
                if let area, let min = area.min, let max = area.max {
                    Text("지원 범위 \(min.formatted())–\(max.formatted())" + (action.argumentKind == "window-position" ? "%" : "단계"))
                        .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
                }
                Button(targetTitle + " · " + (action.argumentKind == "window-position" ? "\(level)% 적용" : "\(level)단계 적용")) {
                    guard permitted, area?.contains(Double(level)) == true else { return }; send(action, seat ?? "", level)
                }.buttonStyle(.wego(.soft)).disabled(store.busy || !permitted || area?.contains(Double(level)) != true)
                    .accessibilityIdentifier("tripRemoteSend-" + action.id)
            }
        }
    }
}

struct TripLiveControls: View {
    let preparation: TripPreparationStore
    @Bindable var voice: TripVoiceStore
    @State private var sheet: Destination?
    private enum Destination: String, Identifiable { case signal; var id: Self { self } }
    var body: some View {
        VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
            TripVoiceControls(voice: voice)
            HStack(spacing: WegoTokens.Space.small) {
                Button { sheet = .signal } label: {
                    Label(preparation.activeSignals.isEmpty ? "손들기" : "진행 중인 손들기", systemImage: "hand.raised").font(WegoTokens.Typography.action)
                        .frame(maxWidth: .infinity, minHeight: WegoTokens.Metrics.tripProgressActionHeight)
                        .foregroundStyle(WegoTokens.Palette.accent)
                        .background(WegoTokens.Palette.accentSoft, in: RoundedRectangle(cornerRadius: WegoTokens.Radius.control))
                        .contentShape(Rectangle())
                }.buttonStyle(.plain).disabled(preparation.detail?.canUseTripSignals != true && preparation.activeSignals.isEmpty).accessibilityIdentifier("tripLiveSignal")
                TripVoiceHoldButton(voice: voice)
            }
            HStack(alignment: .center, spacing: WegoTokens.Space.small) {
                Text(voice.message ?? "누르고 녹음한 뒤 손을 떼면 보내요 · 최대 15초")
                    .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
                if voice.needsMicrophoneSettings && voice.message != nil {
                    Button("설정 열기") {
                        if let url = URL(string: UIApplication.openSettingsURLString) { UIApplication.shared.open(url) }
                    }.font(WegoTokens.Typography.caption.weight(.semibold))
                        .frame(minHeight: WegoTokens.Metrics.touchTarget).contentShape(Rectangle())
                }
                if voice.floor.floor == nil { TripVoiceControls(voice: voice).voiceMenu }
            }
        }
        .disabled(preparation.busy || preparation.needsRefresh || !preparation.accountIsCurrent)
        .onChange(of: sheet) { _, value in if value != nil { voice.deactivate() } }
        .sheet(item: $sheet, onDismiss: { Task { await voice.activate() } }) { _ in
            NavigationStack {
                if !preparation.accountIsCurrent { Text("로그인을 다시 확인해 주세요.").font(WegoTokens.Typography.label) }
                else { TripLiveSignalView(preparation: preparation) }
            }
        }
    }
}
