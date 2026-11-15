import SwiftUI

struct NotificationSettingsView: View {
    @Environment(SessionManager.self) private var session
    @Environment(\.scenePhase) private var scenePhase
    @State private var push = IPhonePushManager.shared

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: WegoTokens.Space.large) {
                WegoCard(.outlined) {
                    VStack(alignment: .leading, spacing: WegoTokens.Space.medium) {
                        Label("친구와 여행 소식을 바로 받아요", systemImage: "bell.badge")
                            .font(WegoTokens.Typography.section)
                        Text("친구 요청과 수락, 여행 초대, 손들기 요청과 반응을 알려드려요.")
                            .font(WegoTokens.Typography.body).foregroundStyle(WegoTokens.Palette.secondary)
                        StatusPill(push.status, tone: .soft).accessibilityIdentifier("notificationPermissionStatus")
                    }
                }
                if session.current == nil {
                    Text("알림을 받으려면 로그인해 주세요.").font(WegoTokens.Typography.body)
                } else if push.authorization == .notDetermined {
                    Button("알림 허용") { Task { await push.requestPermission(session: session) } }
                        .buttonStyle(.wego(.primary)).disabled(push.isWorking).accessibilityIdentifier("notificationsRequest")
                } else if push.isAllowed {
                    Button("다시 확인") { Task { await push.update(session: session) } }
                        .buttonStyle(.wego(.soft)).disabled(push.isWorking).accessibilityIdentifier("notificationsRetry")
                }
                Link("iPhone 알림 설정 열기", destination: URL(string: UIApplication.openNotificationSettingsURLString)!)
                    .buttonStyle(.wego(.soft)).accessibilityIdentifier("notificationsOpenSettings")
                if let message = push.message { Text(message).font(WegoTokens.Typography.label).foregroundStyle(WegoTokens.Palette.danger) }
            }.padding(WegoTokens.Space.screen)
        }
        .foregroundStyle(WegoTokens.Palette.text).background(WegoTokens.Palette.background)
        .navigationTitle("알림 설정").navigationBarTitleDisplayMode(.inline)
        .task { await push.update(session: session) }
        .onChange(of: scenePhase) { _, phase in if phase == .active { Task { await push.update(session: session) } } }
    }
}
