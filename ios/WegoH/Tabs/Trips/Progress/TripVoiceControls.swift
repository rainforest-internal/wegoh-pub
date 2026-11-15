import SwiftUI
import UIKit

struct TripVoiceControls: View {
    @Bindable var voice: TripVoiceStore
    @Environment(\.scenePhase) private var scenePhase
    var body: some View {
        VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
            if voice.floor.floor != nil {
                HStack(spacing: WegoTokens.Space.small) {
                    Image(systemName: "waveform").foregroundStyle(WegoTokens.Palette.accent)
                    Text(voice.floor.speaking ? voice.status : (voice.speakerName ?? "일행") + "님 음성 재생 중")
                        .font(WegoTokens.Typography.label.weight(.semibold))
                    Spacer(minLength: 0)
                    voiceMenu
                }.padding(WegoTokens.Space.compact)
                    .background(WegoTokens.Palette.accentSoft, in: RoundedRectangle(cornerRadius: WegoTokens.Radius.field))
            }
        }
        .task(id: voice.contextID + ":" + String(scenePhase == .active)) {
            guard scenePhase == .active else { voice.deactivate(); return }
            await voice.activate()
        }
        .onDisappear { voice.deactivate() }
    }
    var voiceMenu: some View {
        Menu {
            ForEach(voice.preparation.detail?.members.filter { $0.state == .accepted && !$0.isMe } ?? []) { member in
                Button {
                    Task { await voice.setMuted(member.id, enabled: !voice.muted.contains(member.id)) }
                } label: {
                    Label(member.name + (voice.muted.contains(member.id) ? " 음소거 해제" : " 음소거"),
                          systemImage: voice.muted.contains(member.id) ? "speaker.wave.2" : "speaker.slash")
                }.disabled(voice.updatingFilter)
            }
            Button("최근 들은 음성 신고", role: .destructive) { Task { await voice.reportLastSpeaker() } }.disabled(!voice.canReport)
        } label: {
            Image(systemName: "ellipsis").font(WegoTokens.Typography.label)
                .frame(minWidth: WegoTokens.Metrics.touchTarget, minHeight: WegoTokens.Metrics.touchTarget)
                .contentShape(Rectangle())
        }.accessibilityLabel("워키토키 음소거 및 신고")
    }
}

struct TripVoiceHoldButton: View {
    @Bindable var voice: TripVoiceStore
    var body: some View {
        VStack(spacing: WegoTokens.Space.xSmall) {
            Label(voice.floor.speaking ? (voice.recordingFull ? "녹음 완료" : "녹음 중") : voice.speakerName != nil ? "듣는 중" : "워키토키", systemImage: "mic.fill")
                .font(WegoTokens.Typography.action)
            Text(voice.floor.speaking ? "손을 떼면 보내요" : voice.status).font(WegoTokens.Typography.caption)
        }
        .frame(maxWidth: .infinity, minHeight: WegoTokens.Metrics.tripProgressActionHeight)
        .foregroundStyle(voice.floor.speaking ? WegoTokens.Palette.onAccent : WegoTokens.Palette.onInk)
        .background(voice.floor.speaking ? WegoTokens.Palette.accent : WegoTokens.Palette.ink,
                    in: RoundedRectangle(cornerRadius: WegoTokens.Radius.control))
        .opacity(voice.canPress || voice.floor.speaking ? 1 : WegoTokens.Opacity.controlDisabled)
        .accessibilityHidden(true)
        .overlay {
            TripVoiceHoldSurface(enabled: voice.canPress, speaking: voice.floor.speaking, label: "워키토키, " + voice.status,
                                 press: { voice.press() }, release: { voice.release() }, cancel: { voice.cancelRecording() })
        }
    }
}

private struct TripVoiceHoldSurface: UIViewRepresentable {
    var enabled: Bool
    var speaking: Bool
    var label: String
    var press: () -> Void
    var release: () -> Void
    var cancel: () -> Void
    func makeUIView(context: Context) -> HoldControl { HoldControl() }
    func updateUIView(_ view: HoldControl, context: Context) {
        view.press = press; view.release = release; view.cancel = cancel
        view.isEnabled = enabled; view.speaking = speaking
        view.isAccessibilityElement = true; view.accessibilityTraits = enabled ? .button : [.button, .notEnabled]
        view.accessibilityLabel = label
        view.accessibilityIdentifier = "tripLiveVoice"
        if !enabled { view.finish(cancelled: true) }
    }
    static func dismantleUIView(_ view: HoldControl, coordinator: ()) { view.finish(cancelled: true) }
    final class HoldControl: UIControl {
        var press: (() -> Void)?
        var release: (() -> Void)?
        var cancel: (() -> Void)?
        var speaking = false
        private var held = false
        override func beginTracking(_ touch: UITouch, with event: UIEvent?) -> Bool {
            guard isEnabled else { return false }
            held = true; press?(); return true
        }
        override func continueTracking(_ touch: UITouch, with event: UIEvent?) -> Bool {
            guard bounds.contains(touch.location(in: self)) else { finish(cancelled: true); return false }
            return held
        }
        override func endTracking(_ touch: UITouch?, with event: UIEvent?) { finish() }
        override func cancelTracking(with event: UIEvent?) { finish(cancelled: true) }
        override func didMoveToWindow() { super.didMoveToWindow(); if window == nil { finish(cancelled: true) } }
        override func accessibilityActivate() -> Bool {
            guard isEnabled else { return false }
            if held { finish() }
            else if speaking { release?() }
            else { held = true; press?() }
            return true
        }
        func finish(cancelled: Bool = false) {
            guard held else { return }
            held = false
            if cancelled { cancel?() } else { release?() }
        }
    }
}
