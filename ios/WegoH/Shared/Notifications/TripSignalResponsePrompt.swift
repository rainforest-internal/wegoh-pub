import SwiftUI
import UIKit

struct TripSignalInboxModifier: ViewModifier {
    private struct Request: Equatable {
        let accountID: String?
        let phase: SessionManager.Phase
        let scenePhase: ScenePhase
    }
    @Environment(SessionManager.self) private var session
    @Environment(\.scenePhase) private var scenePhase
    @State private var inbox: TripSignalInbox?
    @State private var push = IPhonePushManager.shared

    func body(content: Content) -> some View {
        content
            .background {
                TripSignalPromptPresenter(inbox: inbox, active: scenePhase == .active && inbox?.isCurrent == true,
                                          promptID: inbox?.prompt?.id)
            }
            .task(id: Request(accountID: session.current?.accountID, phase: session.phase, scenePhase: scenePhase)) {
                guard session.phase == .signedIn, session.current?.scopes.isSuperset(of: ["trips:read", "trips:manage"]) == true, scenePhase == .active else {
                    if session.phase != .signedIn { inbox?.clear(); inbox = nil }
                    return
                }
                if inbox?.isCurrent != true { inbox = TripSignalInbox(session: session) }
                guard let inbox else { return }
                await inbox.refresh(discover: true)
                while !Task.isCancelled, inbox.isCurrent {
                    do { try await Task.sleep(for: .seconds(15)) }
                    catch { return }
                    await inbox.refresh()
                }
            }
            .onChange(of: scenePhase) { _, phase in if phase != .active { inbox?.suspend() } }
            .task(id: push.foregroundHandRaise?.eventID) {
                guard scenePhase == .active, let event = push.foregroundHandRaise,
                      push.accepts(event), let tripID = event.tripID else { return }
                await inbox?.refresh(tripID: tripID)
            }
            .onChange(of: push.openedNotification) { _, event in
                guard let event, event.kind == .handRaise || event.kind == .handRaiseReaction,
                      push.accepts(event), let tripID = event.tripID else { return }
                Task { await inbox?.refresh(tripID: tripID) }
            }
    }
}

private struct TripSignalResponsePrompt: View {
    let inbox: TripSignalInbox

    var body: some View {
        if inbox.isCurrent, let prompt = inbox.prompt {
            VStack(spacing: 0) {
                ScrollView {
                    VStack(alignment: .leading, spacing: WegoTokens.Space.large) {
                        Label("받은 손들기", systemImage: "hand.raised.fill")
                            .font(WegoTokens.Typography.section).foregroundStyle(WegoTokens.Palette.accent)
                        Text("일행이 잠시\n들르고 싶어 해요")
                            .font(WegoTokens.Typography.hero).accessibilityAddTraits(.isHeader)
                        Text(prompt.trip.title).font(WegoTokens.Typography.label)
                            .foregroundStyle(WegoTokens.Palette.secondary)
                        WegoCard(.ink) {
                            if let car = prompt.trip.cars.first(where: { $0.id == prompt.signal.requesterCarId }) {
                                Text(prompt.trip.numberedName(car)).font(WegoTokens.Typography.label)
                            }
                            Text(TripSignalReason.allCases.first { $0.serverKind == prompt.signal.kind }?.title ?? "손들기")
                                .font(WegoTokens.Typography.title)
                            Text(prompt.signal.destination?.name ?? "장소는 운전자가 정해요")
                                .font(WegoTokens.Typography.section)
                            if let seconds = prompt.signal.candidateDetails?.detourSeconds {
                                Text("들르면 \(seconds >= 0 ? "+" : "")\(Int(ceil(Double(seconds) / 60)))분")
                                    .font(WegoTokens.Typography.label).foregroundStyle(WegoTokens.Palette.onInkSecondary)
                            }
                        }
                        Text("우리 차에서 한 명만 답하면 돼요.")
                            .font(WegoTokens.Typography.section)
                        Text("모든 차가 동의하면 다음 목적지 앞에 추가돼요.")
                            .font(WegoTokens.Typography.body).foregroundStyle(WegoTokens.Palette.secondary)
                        if let message = inbox.message {
                            Text(message).font(WegoTokens.Typography.label).foregroundStyle(WegoTokens.Palette.danger)
                            if inbox.needsVerification {
                                Button("상태 다시 확인") { Task { await inbox.refresh(tripID: prompt.trip.id) } }
                                    .buttonStyle(.wego(.soft)).disabled(inbox.checking || inbox.responding)
                            }
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(WegoTokens.Space.screen)
                    .padding(.top, WegoTokens.Space.large)
                }
                VStack(spacing: WegoTokens.Space.small) {
                    responseButton("동의", agree: true, primary: true)
                    responseButton("다음에", agree: false, primary: false)
                }
                .padding(WegoTokens.Space.screen)
            }
            .foregroundStyle(WegoTokens.Palette.text)
            .background(WegoTokens.Palette.background.ignoresSafeArea())
            .accessibilityIdentifier("incomingSignalPrompt")
            .overlay {
                if inbox.responding {
                    WegoTokens.Palette.ink.opacity(WegoTokens.Opacity.modalScrim).ignoresSafeArea()
                    ProgressView("응답 보내는 중")
                        .padding(WegoTokens.Space.large)
                        .background(WegoTokens.Palette.background, in: RoundedRectangle(cornerRadius: WegoTokens.Radius.card))
                }
            }
            .task {
                while !Task.isCancelled, inbox.isCurrent, inbox.prompt != nil {
                    do { try await Task.sleep(for: .seconds(3)) }
                    catch { return }
                    await inbox.refresh()
                }
            }
        } else { WegoLoadingView("요청 확인 중", layout: .detail).background(WegoTokens.Palette.background.ignoresSafeArea()) }
    }

    private func responseButton(_ title: String, agree: Bool, primary: Bool) -> some View {
        Button { Task { await inbox.respond(agree: agree) } } label: {
            Text(title).font(WegoTokens.Typography.action)
                .frame(maxWidth: .infinity, minHeight: WegoTokens.Metrics.tripSignalResponseButtonHeight)
        }
        .buttonStyle(.wego(primary ? .primary : .soft))
        .disabled(!inbox.canRespond)
        .accessibilityIdentifier(agree ? "incomingSignalAgree" : "incomingSignalPass")
    }
}

private struct TripSignalPromptPresenter: UIViewControllerRepresentable {
    let inbox: TripSignalInbox?
    let active: Bool
    let promptID: String?

    func makeCoordinator() -> Coordinator { Coordinator() }
    func makeUIViewController(context: Context) -> UIViewController { UIViewController() }
    func updateUIViewController(_ anchor: UIViewController, context: Context) {
        context.coordinator.update(anchor: anchor, inbox: inbox, active: active)
    }
    static func dismantleUIViewController(_ controller: UIViewController, coordinator: Coordinator) { coordinator.close() }

    @MainActor final class Coordinator {
        private weak var anchor: UIViewController?
        private var inbox: TripSignalInbox?
        private var active = false
        private var controller: UIHostingController<TripSignalResponsePrompt>?
        private var transitioning = false

        func update(anchor: UIViewController, inbox: TripSignalInbox?, active: Bool) {
            self.anchor = anchor; self.inbox = inbox; self.active = active
            render()
        }
        func close() { active = false; render() }
        private func render() {
            guard !transitioning else { return }
            guard active, let inbox, inbox.isCurrent, inbox.prompt != nil else {
                guard let controller else { return }
                transitioning = true
                controller.dismiss(animated: true) {
                    self.controller = nil; self.transitioning = false; self.render()
                }
                return
            }
            guard controller == nil, var top = anchor?.view.window?.rootViewController else { return }
            while let presented = top.presentedViewController { top = presented }
            guard !top.isBeingDismissed, !top.isBeingPresented, !(top is UIAlertController) else { return }
            let controller = UIHostingController(rootView: TripSignalResponsePrompt(inbox: inbox))
            controller.modalPresentationStyle = .overFullScreen
            controller.modalTransitionStyle = .crossDissolve
            controller.isModalInPresentation = true
            controller.view.accessibilityViewIsModal = true
            self.controller = controller
            transitioning = true
            top.present(controller, animated: true) { self.transitioning = false; self.render() }
        }
    }
}
