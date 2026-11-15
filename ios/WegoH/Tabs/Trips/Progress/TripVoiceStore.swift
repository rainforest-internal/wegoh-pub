import AVFAudio
import Foundation
import Observation
import UIKit
#if DEBUG
import OSLog
#endif

private final class TripVoiceObservers: @unchecked Sendable {
    var values: [NSObjectProtocol] = []
    deinit { values.forEach(NotificationCenter.default.removeObserver) }
}

@MainActor @Observable
final class TripVoiceStore {
    let preparation: TripPreparationStore
    private(set) var connected = false
    private(set) var connecting = false
    private(set) var participating = true
    private(set) var sending = false
    private(set) var recordingFull = false
    private(set) var floor = TripVoiceFloorState()
    private(set) var message: String?
    private(set) var elapsed = 0
    private(set) var muted: Set<String> = []
    private(set) var updatingFilter = false
    private(set) var heardFloor: TripVoiceWire.Floor?
    private let audio = TripVoiceAudio()
    private let http = IPhoneSessionAPI()
    @ObservationIgnored private var feedTask: Task<Void, Never>?
    @ObservationIgnored private var connectTask: Task<Void, Error>?
    @ObservationIgnored private var pressTask: Task<Void, Never>?
    @ObservationIgnored private var leaseTask: Task<Void, Never>?
    @ObservationIgnored private var uploadTask: Task<Void, Never>?
    @ObservationIgnored private var playbackTask: Task<Void, Never>?
    @ObservationIgnored private var inbox = TripVoiceClipInbox()
    @ObservationIgnored private var recording: TripVoiceClipCapture?
    @ObservationIgnored private var pendingUpload: TripVoiceClipDraft?
    @ObservationIgnored private let observers = TripVoiceObservers()
    private var epoch = UUID()
    private var held: UUID?
    private var active = false
    private var boundContext: String?
    private var lastSpeaker: TripVoiceWire.Floor?
    private var sentClips = 0
    private var receivedClips = 0

    init(preparation: TripPreparationStore) {
        self.preparation = preparation
        for name in [AVAudioSession.interruptionNotification, AVAudioSession.routeChangeNotification, AVAudioSession.mediaServicesWereResetNotification] {
            observers.values.append(NotificationCenter.default.addObserver(forName: name, object: nil, queue: .main) { [weak self] note in
                let began = (note.userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt) == AVAudioSession.InterruptionType.began.rawValue
                let removed = (note.userInfo?[AVAudioSessionRouteChangeReasonKey] as? UInt) == AVAudioSession.RouteChangeReason.oldDeviceUnavailable.rawValue
                if (note.name == AVAudioSession.interruptionNotification && began) || removed || note.name == AVAudioSession.mediaServicesWereResetNotification {
                    Task { @MainActor in
                        guard let self, self.active else { return }
                        self.disconnect()
                        self.message = "오디오 연결이 바뀌었어요. 다시 눌러 주세요."
                    }
                }
            })
        }
    }
    deinit { feedTask?.cancel(); connectTask?.cancel(); pressTask?.cancel(); leaseTask?.cancel(); uploadTask?.cancel(); playbackTask?.cancel() }
    var contextID: String { "\(preparation.detail?.id ?? ""):\(preparation.detail?.me?.id ?? ""):\(preparation.detail?.state.rawValue ?? ""):\(preparation.accountIsCurrent)" }
    var current: Bool { active && UIApplication.shared.applicationState == .active && preparation.accountIsCurrent && preparation.detail?.state == .active && !preparation.isPreview }
    var speakerName: String? { floor.floor.flatMap { value in preparation.detail?.members.first { $0.id == value.speakerId }?.name } }
    var needsMicrophoneSettings: Bool { AVAudioApplication.shared.recordPermission == .denied }
    var canReport: Bool { heardFloor != nil || lastSpeaker != nil }
    var canPress: Bool { current && !sending && (held != nil || (!connecting && floor.floor == nil)) }
    var status: String {
        if floor.speaking { return recordingFull ? "녹음 완료 · 손을 떼면 보내요" : "녹음 중 · \(elapsed)/15초" }
        if sending { return "음성 보내는 중" }
        if let speakerName { return "\(speakerName)님 음성 재생 중" }
        if connecting { return "준비하는 중" }
        if pendingUpload != nil { return "눌러서 다시 보내기" }
        if !participating { return "눌러서 참여하고 녹음" }
        return connected ? "눌러서 녹음" : "눌러서 다시 연결"
    }
    func activate() async {
        active = true
        if boundContext != contextID { disconnect(); boundContext = contextID }
        guard current else { disconnect(); return }
        do { try await ensureConnection(enable: false) }
        catch is CancellationError { }
        catch { if active { fail(error) } }
    }
    func deactivate() { active = false; disconnect() }

    private func participation(_ trip: String, token: String, previous: TripVoiceParticipation? = nil) async throws -> TripVoiceParticipation {
        struct Choice: Encodable { let participating: Bool; let memberJoinedAt: String; let revision: Int }
        let payload = try previous.map { try JSONEncoder().encode(Choice(participating: true, memberJoinedAt: $0.memberJoinedAt, revision: $0.revision)) }
        let data = try await http.resource("trips/" + trip + "/voice-participation", method: previous == nil ? "GET" : "PATCH", payload: payload, token: token)
        let value = try JSONDecoder().decode(TripVoiceParticipation.self, from: data)
        guard value.isValid, value.tripId == trip else { throw TripVoiceFailure.protocolMismatch }
        return value
    }
    private func ensureConnection(enable: Bool) async throws {
        guard current else { throw CancellationError() }
        if connected { return }
        if let connectTask { try await connectTask.value; if connected || !enable { return } }
        let stamp = epoch
        connecting = true
        let task = Task { @MainActor in
            defer { if self.epoch == stamp { self.connecting = false; self.connectTask = nil } }
            guard let trip = self.preparation.detail?.id else { throw CancellationError() }
            try await self.preparation.activityRequest { token in
                var choice = try await self.participation(trip, token: token)
                guard self.current, self.epoch == stamp else { throw CancellationError() }
                if !choice.participating && enable {
                    guard self.held != nil else { throw CancellationError() }
                    choice = try await self.participation(trip, token: token, previous: choice)
                }
                self.participating = choice.participating
                guard choice.participating else { return }
                struct Filters: Decodable { let mutedSpeakerIds: [String] }
                let filters = try JSONDecoder().decode(Filters.self, from: try await self.http.resource("trips/" + trip + "/voice/filters", token: token))
                guard filters.mutedSpeakerIds.count <= 20, filters.mutedSpeakerIds.allSatisfy(validTripAccountID) else { throw TripVoiceFailure.protocolMismatch }
                let feed = try JSONDecoder().decode(TripVoiceClipFeed.self, from: try await self.http.resource("trips/" + trip + "/voice-clips", token: token))
                guard self.current, self.epoch == stamp else { throw CancellationError() }
                self.muted = Set(filters.mutedSpeakerIds)
                try self.inbox.ingest(feed, excluding: self.excludedSpeakers)
                try self.audio.listen()
                self.connected = true
                self.feedTask = Task { @MainActor [weak self] in await self?.poll(stamp: stamp) }
            }
        }
        connectTask = task
        try await task.value
    }
    private var excludedSpeakers: Set<String> { muted.union(preparation.detail?.me.map { [$0.id] } ?? []) }
    private func poll(stamp: UUID) async {
        do {
            while current && epoch == stamp && connected {
                try await Task.sleep(for: .seconds(1))
                guard current, epoch == stamp, let trip = preparation.detail?.id, let cursor = inbox.cursor else { return }
                let data = try await preparation.activityRequest { token in
                    try await http.resource("trips/" + trip + "/voice-clips?cursor=" + cursor, token: token)
                }
                guard current, epoch == stamp else { return }
                let feed = try JSONDecoder().decode(TripVoiceClipFeed.self, from: data)
                guard feed.cursor.split(separator: ":").first == cursor.split(separator: ":").first else {
                    throw TripVoiceFailure.protocolMismatch
                }
                try inbox.ingest(feed, excluding: excludedSpeakers)
                if floor.floor != nil && !floor.speaking { try await refreshFilters(trip: trip, stamp: stamp) }
                startPlayback()
            }
        } catch is CancellationError { }
        catch { if current && epoch == stamp { fail(error) } }
    }
    private func refreshFilters(trip: String, stamp: UUID) async throws {
        struct Filters: Decodable { let mutedSpeakerIds: [String] }
        let data = try await preparation.activityRequest { token in try await http.resource("trips/" + trip + "/voice/filters", token: token) }
        guard current, epoch == stamp else { throw CancellationError() }
        let filters = try JSONDecoder().decode(Filters.self, from: data)
        guard filters.mutedSpeakerIds.count <= 20, filters.mutedSpeakerIds.allSatisfy(validTripAccountID) else { throw TripVoiceFailure.protocolMismatch }
        muted = Set(filters.mutedSpeakerIds)
        for speaker in muted { inbox.discard(speaker: speaker) }
        if let speaker = floor.floor?.speakerId, muted.contains(speaker) {
            audio.clearPlayback(); floor.reset(); heardFloor = nil
        }
    }
    func press() {
        guard canPress, held == nil else { return }
        if pendingUpload != nil { sendPending(); return }
        let press = UUID(); held = press; message = nil
        pressTask = Task { @MainActor in
            do {
                switch AVAudioApplication.shared.recordPermission {
                case .undetermined:
                    let allowed = await AVAudioApplication.requestRecordPermission()
                    guard self.held == press, self.current else { return }
                    self.held = nil
                    self.message = allowed ? "마이크를 허용했어요. 다시 누르고 녹음해 주세요." : TripVoiceFailure.microphone.localizedDescription
                    return
                case .denied: throw TripVoiceFailure.microphone
                case .granted: break
                @unknown default: throw TripVoiceFailure.microphone
                }
                try await self.ensureConnection(enable: true)
                guard self.held == press, self.current, self.connected, let me = self.preparation.detail?.me else { return }
                let id = UUID().uuidString.replacingOccurrences(of: "-", with: "").lowercased()
                let recorder = TripVoiceClipCapture(clientMessageId: id)
                self.recording = recorder; self.recordingFull = false
                self.floor.reset(); _ = self.floor.request()
                _ = self.floor.granted(.init(leaseId: id, speakerId: me.id))
                self.elapsed = 0
                let stamp = self.epoch
                try self.audio.capture(frame: { [weak self] frame in
                    do {
                        #if DEBUG
                        let pcm = LocalServerUIFixture.voicePCM(frame)
                        #else
                        let pcm = frame
                        #endif
                        if try recorder.append(pcm) {
                            Task { @MainActor in
                                if self?.epoch == stamp && self?.held == press { self?.finishCapture() }
                            }
                        }
                    } catch { Task { @MainActor in if self?.epoch == stamp { self?.fail(error) } } }
                }, failure: { [weak self] in Task { @MainActor in if self?.epoch == stamp { self?.fail(TripVoiceFailure.audio) } } })
                self.leaseTask = Task { @MainActor in
                    for second in 1...15 {
                        do { try await Task.sleep(for: .seconds(1)) } catch { return }
                        guard self.current, self.epoch == stamp, self.held == press else { return }
                        self.elapsed = recorder.durationMs / 1000
                        if second == 15 { self.finishCapture() }
                    }
                }
            } catch is CancellationError { }
            catch {
                guard self.current, self.held == press else { return }
                self.cancelRecording()
                self.message = error.localizedDescription
            }
        }
    }
    private func finishCapture() {
        guard held != nil else { return }
        audio.stopCapture(); recordingFull = true
        elapsed = min(15, (recording?.durationMs ?? 0) / 1000)
        leaseTask?.cancel(); leaseTask = nil
        try? audio.listen()
    }
    func release() {
        guard held != nil else { return }
        held = nil; pressTask?.cancel(); pressTask = nil; leaseTask?.cancel(); leaseTask = nil
        audio.stopCapture(); recordingFull = false; floor.reset()
        if let draft = recording?.finish(), !draft.pcm.isEmpty { pendingUpload = draft }
        recording = nil
        try? audio.listen()
        sendPending()
    }
    func cancelRecording() {
        held = nil; _ = recording?.finish(); recording = nil; pressTask?.cancel(); pressTask = nil; leaseTask?.cancel(); leaseTask = nil
        audio.stopCapture(); recordingFull = false
        if floor.speaking { floor.reset(); try? audio.listen() }
    }
    private func sendPending() {
        guard current, !sending, let draft = pendingUpload, let trip = preparation.detail?.id else { startPlayback(); return }
        guard !draft.isExpired else {
            pendingUpload = nil; message = "음성 전송 시간이 지났어요. 다시 녹음해 주세요."; return
        }
        let stamp = epoch
        sending = true
        uploadTask = Task { @MainActor in
            defer { if self.epoch == stamp { self.sending = false; self.uploadTask = nil; self.startPlayback() } }
            do {
                let payload = try draft.payload()
                let data = try await self.preparation.activityRequest { token in
                    try await self.http.resource("trips/" + trip + "/voice-clips", method: "POST", payload: payload, token: token, status: 201, alternateStatus: 200)
                }
                guard self.current, self.epoch == stamp else { return }
                let receipt = try JSONDecoder().decode(TripVoiceClip.self, from: data)
                guard receipt.isValid, receipt.speakerId == self.preparation.detail?.me?.id, receipt.durationMs == draft.durationMs else { throw TripVoiceFailure.protocolMismatch }
                self.pendingUpload = nil; self.sentClips += 1
                self.message = "음성을 보냈어요."
                self.recordProbe()
            } catch is CancellationError { }
            catch {
                guard self.current, self.epoch == stamp else { return }
                switch error {
                case IPhoneSessionError.unavailable, IPhoneSessionError.rateLimited,
                     IPhoneResourceError.unavailable, is URLError:
                    self.message = "음성을 보내지 못했어요. 다시 누르면 재전송해요."
                default:
                    self.fail(error)
                }
            }
        }
    }
    private func startPlayback() {
        guard current, connected, !sending, held == nil, playbackTask == nil else { return }
        let stamp = epoch
        playbackTask = Task { @MainActor in
            defer { if self.epoch == stamp { self.playbackTask = nil } }
            do {
                while self.current && self.epoch == stamp && self.held == nil && !self.sending, let clip = self.inbox.next() {
                    guard !self.excludedSpeakers.contains(clip.speakerId), let trip = self.preparation.detail?.id else { continue }
                    let data: Data
                    do { data = try await self.preparation.activityRequest { token in try await self.http.resource("trips/" + trip + "/voice-clips/" + clip.id, token: token) } }
                    catch IPhoneResourceError.missing { continue }
                    guard self.current, self.epoch == stamp, !self.excludedSpeakers.contains(clip.speakerId), self.held == nil else { continue }
                    let pcm = try JSONDecoder().decode(TripVoiceClipContent.self, from: data).decoded(for: clip)
                    let speaker = TripVoiceWire.Floor(leaseId: clip.id, speakerId: clip.speakerId)
                    self.floor.started(speaker); self.heardFloor = speaker; self.lastSpeaker = speaker
                    try self.audio.playClip(pcm)
                    self.receivedClips += 1
                    let deadline = ContinuousClock.now.advanced(by: .milliseconds(clip.durationMs + 2_000))
                    while self.current && self.epoch == stamp && self.audio.clipPlaying {
                        guard ContinuousClock.now < deadline else { throw TripVoiceFailure.audio }
                        try await Task.sleep(for: .milliseconds(50))
                    }
                    guard self.current, self.epoch == stamp else { return }
                    self.floor.reset(); self.heardFloor = nil; self.recordProbe()
                }
            } catch is CancellationError { }
            catch { if self.current && self.epoch == stamp { self.fail(error) } }
        }
    }
    func setMuted(_ speaker: String, enabled: Bool) async {
        guard current, !updatingFilter, let trip = preparation.detail?.id else { return }
        let stamp = epoch
        updatingFilter = true
        defer { if epoch == stamp { updatingFilter = false } }
        struct Choice: Encodable { let muted: Bool }
        do {
            let payload = try JSONEncoder().encode(Choice(muted: enabled))
            _ = try await preparation.activityRequest { token in try await http.resource("trips/" + trip + "/voice/filters/" + speaker, method: "PUT", payload: payload, token: token) }
            guard current, epoch == stamp else { return }
            if enabled {
                muted.insert(speaker); inbox.discard(speaker: speaker)
                if floor.floor?.speakerId == speaker { audio.clearPlayback(); floor.reset(); heardFloor = nil }
            } else { muted.remove(speaker) }
        } catch { if current && epoch == stamp { message = "음소거 설정을 바꾸지 못했어요." } }
    }
    func reportLastSpeaker() async {
        guard current, let heard = heardFloor ?? lastSpeaker, let trip = preparation.detail?.id else { return }
        struct Report: Encodable { let speakerId: String; let leaseId: String; let reason: String }
        let stamp = epoch
        do {
            let payload = try JSONEncoder().encode(Report(speakerId: heard.speakerId, leaseId: heard.leaseId, reason: "other"))
            _ = try await preparation.activityRequest { token in try await http.resource("trips/" + trip + "/voice/reports", method: "POST", payload: payload, token: token, status: 202) }
            guard current, epoch == stamp else { return }
            message = "음성 신고를 접수했어요. 원음은 보관하지 않아요."
        } catch { if current && epoch == stamp { message = "신고를 보내지 못했어요. 최근 들은 음성만 신고할 수 있어요." } }
    }
    private func fail(_ error: Error) {
        let wasConnected = connected
        disconnect()
        if !wasConnected, case IPhoneResourceError.missing = error { message = "새 음성 전송 방식을 준비 중이에요." }
        else { message = "음성 연결을 확인하지 못했어요. 다시 눌러 주세요." }
        recordProbe()
    }
    private func disconnect() {
        epoch = UUID(); held = nil; _ = recording?.finish(); recording = nil; pendingUpload = nil
        connectTask?.cancel(); connectTask = nil; pressTask?.cancel(); pressTask = nil; leaseTask?.cancel(); leaseTask = nil
        feedTask?.cancel(); feedTask = nil; uploadTask?.cancel(); uploadTask = nil; playbackTask?.cancel(); playbackTask = nil
        audio.stop(); inbox.clear(); connected = false; connecting = false; sending = false; recordingFull = false; updatingFilter = false
        floor.reset(); heardFloor = nil; lastSpeaker = nil
    }
    private func recordProbe() {
        #if DEBUG
        Logger(subsystem: "io.wegoh.iphone", category: "TripVoice").info("trip.voice.clip: synced sent=\(self.sentClips, privacy: .public) received=\(self.receivedClips, privacy: .public) played_samples=\(self.audio.playedFrames, privacy: .public) connected=\(self.connected, privacy: .public)")
        #endif
    }
}
