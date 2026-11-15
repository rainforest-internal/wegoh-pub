import SwiftUI

struct WalkthroughView: View {
    private enum Step: String {
        case introduction, permissions, login, finished
    }

    @AppStorage("walkthrough.step") private var step = Step.introduction
    @Environment(SessionManager.self) private var session

    var body: some View {
        Group {
            switch step {
            case .introduction:
                IntroductionView { step = .permissions }
            case .permissions:
                PermissionSetupView(back: { step = .introduction }, later: { step = .finished }) {
                    step = .login
                }
            case .login, .finished:
                if session.needsReauthentication || (step == .login && session.current == nil) {
                    LoginView(secondaryTitle: "나중에 하기") {
                        session.acknowledgeReauthentication()
                        step = .finished
                    }
                    .onAppear {
                        if session.needsReauthentication { step = .login }
                    }
                } else {
                    AppTabs()
                        .onAppear {
                            if step == .login { step = .finished }
                        }
                }
            }
        }
    }
}

private struct IntroductionView: View {
    let next: () -> Void

    var body: some View {
        VStack(spacing: 0) {
            ScrollView {
                VStack(alignment: .leading, spacing: WegoTokens.Space.large) {
                    HStack {
                        BrandHeader(markSize: WegoTokens.Metrics.onboardingMarkSize)
                        Spacer()
                        Button(action: next) {
                            Text("건너뛰기").font(WegoTokens.Typography.body)
                                .frame(minWidth: WegoTokens.Metrics.touchTarget, minHeight: WegoTokens.Metrics.touchTarget)
                                .contentShape(Rectangle())
                        }
                        .accessibilityIdentifier("introSkip")
                    }
                    JourneyIllustration()
                    VStack(alignment: .leading, spacing: WegoTokens.Space.compact) {
                        Text("함께라서 더 즐거운\n주행 경험.")
                            .font(WegoTokens.Typography.title)
                            .accessibilityAddTraits(.isHeader)
                        Text("같이 여행을 기획하고\n즐거운 여행 경험을 나눠봐요.")
                            .font(WegoTokens.Typography.body)
                            .foregroundStyle(WegoTokens.Palette.secondary)
                            .lineSpacing(WegoTokens.Space.xSmall)
                    }
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.top, WegoTokens.Space.small)
                }
                .foregroundStyle(WegoTokens.Palette.text)
                .padding(.horizontal, WegoTokens.Space.large)
            }
            .scrollBounceBehavior(.basedOnSize)
            HStack(spacing: WegoTokens.Metrics.pageIndicatorSize) {
                Capsule().fill(WegoTokens.Palette.accent)
                    .frame(width: WegoTokens.Metrics.activePageIndicatorWidth)
                Circle().fill(WegoTokens.Palette.divider)
                    .frame(width: WegoTokens.Metrics.pageIndicatorSize)
                Circle().fill(WegoTokens.Palette.divider)
                    .frame(width: WegoTokens.Metrics.pageIndicatorSize)
            }
            .frame(height: WegoTokens.Metrics.pageIndicatorSize)
            .padding(.vertical, WegoTokens.Space.medium)
            .accessibilityLabel("소개, 3단계 중 1단계")
            ActionButton(title: "다음", action: next)
                .accessibilityIdentifier("introNext")
        }
        .background(WegoTokens.Palette.background.ignoresSafeArea())
    }
}

private struct JourneyIllustration: View {
    var body: some View {
        Canvas { context, size in
            context.scaleBy(x: size.width / 342, y: size.height / 352)
            var road = Path()
            road.move(to: CGPoint(x: -10, y: 300))
            road.addCurve(to: CGPoint(x: 150, y: 222), control1: CGPoint(x: 70, y: 300), control2: CGPoint(x: 80, y: 228))
            road.addCurve(to: CGPoint(x: 236, y: 120), control1: CGPoint(x: 220, y: 216), control2: CGPoint(x: 232, y: 170))
            road.addCurve(to: CGPoint(x: 360, y: 46), control1: CGPoint(x: 240, y: 70), control2: CGPoint(x: 290, y: 52))
            context.stroke(road, with: .color(WegoTokens.Palette.background), style: StrokeStyle(lineWidth: WegoTokens.Metrics.touchTarget, lineCap: .round))
            context.stroke(road, with: .color(WegoTokens.Palette.accent), style: StrokeStyle(lineWidth: WegoTokens.Metrics.timelineWidth, lineCap: .round, dash: [WegoTokens.Metrics.timelineWidth, WegoTokens.Space.compact]))
            for (x, y, color) in [(64.0, 283.0, WegoTokens.Palette.ink),
                                  (150, 222, WegoTokens.Palette.accent), (236, 122, WegoTokens.Palette.routeHighlight)] {
                let outer = WegoTokens.Metrics.friendAvatarSize
                let inner = WegoTokens.Metrics.coursePlaceSelectionSize
                context.fill(Path(ellipseIn: CGRect(x: x - outer / 2, y: y - outer / 2, width: outer, height: outer)), with: .color(WegoTokens.Palette.background))
                context.fill(Path(ellipseIn: CGRect(x: x - inner / 2, y: y - inner / 2, width: inner, height: inner)), with: .color(color))
            }
            let endDot = WegoTokens.Metrics.courseSummaryDotSize
            let endRing = WegoTokens.Metrics.onboardingMarkSize
            context.fill(Path(ellipseIn: CGRect(x: 300 - endDot / 2, y: 62 - endDot / 2, width: endDot, height: endDot)), with: .color(WegoTokens.Palette.accent))
            context.stroke(Path(ellipseIn: CGRect(x: 300 - endRing / 2, y: 62 - endRing / 2, width: endRing, height: endRing)), with: .color(WegoTokens.Palette.accent), lineWidth: WegoTokens.Metrics.timelineWidth)
        }
        .aspectRatio(342 / 352, contentMode: .fit)
        .background(WegoTokens.Palette.accentSoft)
        .overlay(alignment: .topLeading) {
            VStack(alignment: .leading, spacing: WegoTokens.Space.xSmall) {
                Text("강릉 바다 드라이브").font(WegoTokens.Typography.caption)
                    .foregroundStyle(WegoTokens.Palette.secondary)
                Text("일행 4명 · 차량 2대").font(WegoTokens.Typography.label.weight(.semibold))
                    .foregroundStyle(WegoTokens.Palette.text)
            }
            .padding(.horizontal, WegoTokens.Space.medium)
            .padding(.vertical, WegoTokens.Space.compact)
            .background(WegoTokens.Palette.background, in: RoundedRectangle(cornerRadius: WegoTokens.Radius.field))
            .padding(WegoTokens.Space.screen)
        }
        .overlay(alignment: .bottomTrailing) {
            Text("안목해변까지 함께").font(WegoTokens.Typography.caption.weight(.semibold))
                .foregroundStyle(WegoTokens.Palette.onInk)
                .padding(.horizontal, WegoTokens.Space.medium)
                .padding(.vertical, WegoTokens.Space.small)
                .background(WegoTokens.Palette.ink, in: Capsule())
                .padding(WegoTokens.Space.screen)
        }
        .clipShape(RoundedRectangle(cornerRadius: WegoTokens.Radius.hero))
        .accessibilityHidden(true)
    }
}

private struct PermissionSetupView: View {
    let back: () -> Void
    let later: () -> Void
    let finish: () -> Void
    @Environment(\.scenePhase) private var scenePhase
    @StateObject private var permissions = WalkthroughPermissions()
    @AccessibilityFocusState(for: .voiceOver) private var resultTitleFocused: Bool

    private var done: Bool { !permissions.hasPending && !permissions.isRequesting }

    var body: some View {
        VStack(spacing: 0) {
            ScrollView {
                VStack(alignment: .leading, spacing: WegoTokens.Space.xLarge) {
                    VStack(alignment: .leading, spacing: WegoTokens.Space.medium) {
                        Button(action: back) {
                            Image(systemName: "chevron.left").font(WegoTokens.Typography.cardTitle)
                                .frame(width: WegoTokens.Metrics.touchTarget, height: WegoTokens.Metrics.touchTarget)
                                .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        .padding(.leading, -WegoTokens.Space.compact)
                        .accessibilityLabel("소개로 돌아가기")
                        .accessibilityIdentifier("permissionsBack")
                        .disabled(permissions.isRequesting)
                        VStack(alignment: .leading, spacing: WegoTokens.Space.compact) {
                            Text(done ? "권한 확인 결과" : "여행에서 사용하는 권한")
                                .font(WegoTokens.Typography.title)
                                .accessibilityAddTraits(.isHeader)
                                .accessibilityIdentifier(done ? "permissionResultTitle" : "permissionSetupTitle")
                                .accessibilityFocused($resultTitleFocused)
                            if !done {
                                Text("계속을 누르면 iPhone이 위치, 마이크, 카메라 권한을 차례로 확인해요.")
                                    .font(WegoTokens.Typography.body)
                                    .foregroundStyle(WegoTokens.Palette.secondary)
                                    .lineSpacing(WegoTokens.Space.xSmall)
                            }
                        }
                    }
                    VStack(spacing: 0) {
                        PermissionRow(icon: "location", title: "위치", status: permissions.locationLabel,
                                      detail: done ? nil : "진행 중인 여행의 일행에게 현재 위치를 보여줘요.", connectsToNext: true)
                            .accessibilityIdentifier("locationRow")
                        PermissionRow(icon: "mic", title: "마이크", status: permissions.microphoneLabel,
                                      detail: done ? nil : "워키토키 버튼을 누르고 일행에게 말할 때 사용해요.", connectsToNext: true)
                            .accessibilityIdentifier("microphoneRow")
                        PermissionRow(icon: "camera", title: "카메라", status: permissions.cameraLabel,
                                      detail: done ? nil : "차량 화면에 표시된 연결 QR 코드를 스캔할 때 사용해요.")
                            .accessibilityIdentifier("cameraRow")
                    }
                }
                .foregroundStyle(WegoTokens.Palette.text)
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, WegoTokens.Space.large)
            }
            .scrollBounceBehavior(.basedOnSize)
            Text("설정은 나중에 iPhone에서 바꿀 수 있어요.")
                .font(WegoTokens.Typography.caption)
                .foregroundStyle(WegoTokens.Palette.secondary)
                .multilineTextAlignment(.center)
                .padding(.horizontal, WegoTokens.Space.large)
                .padding(.top, WegoTokens.Space.medium)
                .padding(.bottom, WegoTokens.Space.small)
            ActionButton(title: done ? "시작하기" : "계속", action: done ? finish : permissions.requestAll)
                .disabled(permissions.isRequesting)
                .accessibilityIdentifier(done ? "walkthroughDone" : "permissionsContinue")
            if !done {
                Button("나중에 하기", action: later)
                    .buttonStyle(.wego(.plain))
                    .disabled(permissions.isRequesting)
                    .accessibilityIdentifier("permissionsLater")
            }
        }
        .background(WegoTokens.Palette.background.ignoresSafeArea())
        .onAppear { permissions.updateScene(scenePhase) }
        .onChange(of: scenePhase) { _, phase in permissions.updateScene(phase) }
        .onChange(of: done && scenePhase == .active, initial: true) { _, showingResult in
            if showingResult { resultTitleFocused = true }
        }
    }
}

private struct PermissionRow: View {
    let icon: String
    let title: String
    let status: String
    let detail: String?
    var connectsToNext = false

    var body: some View {
        HStack(alignment: .top, spacing: WegoTokens.Space.medium) {
            Image(systemName: icon).font(WegoTokens.Typography.cardTitle)
                .foregroundStyle(WegoTokens.Palette.accent)
                .frame(width: WegoTokens.Metrics.permissionIconSize, height: WegoTokens.Metrics.permissionIconSize)
                .background(WegoTokens.Palette.accentSoft, in: Circle())
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: WegoTokens.Space.xSmall) {
                HStack(alignment: .firstTextBaseline, spacing: WegoTokens.Space.small) {
                    Text(title).font(WegoTokens.Typography.section)
                    StatusPill("선택")
                }
                if let detail {
                    Text(detail).font(WegoTokens.Typography.label)
                        .foregroundStyle(WegoTokens.Palette.secondary)
                        .lineSpacing(WegoTokens.Space.xSmall)
                    if status != "설정 전" {
                        Text(status).font(WegoTokens.Typography.caption)
                            .foregroundStyle(WegoTokens.Palette.secondary)
                    }
                } else {
                    Text(status).font(WegoTokens.Typography.cardTitle)
                }
            }
            .foregroundStyle(WegoTokens.Palette.text)
            .fixedSize(horizontal: false, vertical: true)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(.vertical, WegoTokens.Space.medium)
        .background {
            if connectsToNext {
                GeometryReader { geometry in
                    Path { path in
                        let x = WegoTokens.Metrics.permissionIconSize / 2
                        let y = WegoTokens.Space.medium + x
                        path.move(to: CGPoint(x: x, y: y))
                        path.addLine(to: CGPoint(x: x, y: geometry.size.height + y))
                    }
                    .stroke(WegoTokens.Palette.accent,
                            style: StrokeStyle(lineWidth: WegoTokens.Metrics.timelineWidth, lineCap: .round,
                                               dash: [WegoTokens.Metrics.timelineWidth, WegoTokens.Metrics.pageIndicatorSize]))
                }
                .accessibilityHidden(true)
            }
        }
        .accessibilityElement(children: .combine)
    }
}
