import SwiftUI
import UIKit

struct LoginView: View {
    let secondaryTitle: String
    let onClose: () -> Void
    @Environment(SessionManager.self) private var session
    @State private var window: UIWindow?

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Spacer()
                Button {
                    session.cancelSignIn()
                    onClose()
                } label: {
                    Image(systemName: "xmark")
                        .font(WegoTokens.Typography.section)
                        .foregroundStyle(WegoTokens.Palette.secondary)
                        .frame(width: WegoTokens.Metrics.touchTarget, height: WegoTokens.Metrics.touchTarget)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityLabel(secondaryTitle)
                .accessibilityIdentifier("loginLater")
            }
            .padding(.horizontal, WegoTokens.Space.compact)
            ScrollView {
                VStack(alignment: .leading, spacing: WegoTokens.Space.large) {
                    Image("BrandMark").resizable()
                        .frame(width: WegoTokens.Metrics.loginMarkSize, height: WegoTokens.Metrics.loginMarkSize)
                        .accessibilityLabel("WegoH")
                    VStack(alignment: .leading, spacing: WegoTokens.Space.compact) {
                        Text("내 계정으로 로그인")
                            .font(WegoTokens.Typography.title)
                            .foregroundStyle(WegoTokens.Palette.text)
                            .accessibilityAddTraits(.isHeader)
                            .accessibilityIdentifier("loginTitle")
                        Text("WegoH에서 쓰는 이메일로 로그인하고 이 iPhone의 로그인을 승인해 주세요.")
                            .font(WegoTokens.Typography.body)
                            .foregroundStyle(WegoTokens.Palette.secondary)
                            .lineSpacing(WegoTokens.Space.xSmall)
                    }
                    VStack(spacing: 0) {
                        loginStep(number: "1", title: "이메일 인증", filled: true)
                        Divider().overlay(WegoTokens.Palette.divider)
                            .padding(.leading, WegoTokens.Metrics.touchTarget)
                        loginStep(number: "2", title: "이 iPhone의 로그인 승인", filled: false)
                    }
                    .padding(.horizontal, WegoTokens.Space.screen)
                    .padding(.vertical, WegoTokens.Space.small)
                    .background(WegoTokens.Palette.surface, in: RoundedRectangle(cornerRadius: WegoTokens.Radius.card))
                    .padding(.top, WegoTokens.Metrics.loginStepsSpace - WegoTokens.Space.large)
                    if let message = session.message {
                        Text(message)
                            .font(WegoTokens.Typography.body)
                            .foregroundStyle(WegoTokens.Palette.text)
                            .accessibilityIdentifier("loginStatus")
                    }
                }
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, WegoTokens.Space.large)
                .padding(.top, WegoTokens.Metrics.loginTopSpace)
                .padding(.bottom, WegoTokens.Space.large)
            }
            .scrollBounceBehavior(.basedOnSize)
            switch session.phase {
            case .checkingSession, .signingIn, .signingOut:
                WegoLoadingView(session.phase == .signingIn ? "이메일 인증 중…" : session.phase == .signingOut ? "로그아웃 중…" : "로그인 확인 중…", layout: .row)
                    .padding(WegoTokens.Space.medium)
            case .restoreFailed:
                ActionButton(title: "다시 확인") { Task { await session.restore() } }
            case .logoutPending:
                ActionButton(title: "로그아웃 다시 시도") { Task { await session.signOut() } }
            case .signedOut:
                ActionButton(title: "이메일로 로그인", icon: "envelope") {
                    guard let window else { return }
                    Task { await session.signIn(anchor: window) }
                }
                .disabled(window == nil)
                .accessibilityIdentifier("loginWebContinue")
            case .signedIn:
                EmptyView()
            }
        }
        .background(WegoTokens.Palette.background.ignoresSafeArea())
        .background(IPhoneLoginWindowReader { window = $0 }.allowsHitTesting(false))
        .onChange(of: session.phase, initial: true) { _, phase in
            if phase == .signedIn { onClose() }
        }
    }

    private func loginStep(number: String, title: String, filled: Bool) -> some View {
        HStack(spacing: WegoTokens.Space.medium) {
            Text(number).font(WegoTokens.Typography.label.weight(.semibold))
                .foregroundStyle(filled ? WegoTokens.Palette.onAccent : WegoTokens.Palette.accent)
                .frame(width: WegoTokens.Metrics.loginStepBadgeSize, height: WegoTokens.Metrics.loginStepBadgeSize)
                .background(filled ? WegoTokens.Palette.accent : WegoTokens.Palette.background, in: Circle())
                .overlay { if !filled { Circle().strokeBorder(WegoTokens.Palette.accent, lineWidth: WegoTokens.Metrics.timelineWidth) } }
            Text(title).font(WegoTokens.Typography.body)
                .foregroundStyle(WegoTokens.Palette.text)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(.vertical, WegoTokens.Space.compact)
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .combine)
    }
}
