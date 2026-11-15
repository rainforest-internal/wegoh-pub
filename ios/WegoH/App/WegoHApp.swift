import KakaoMapsSDK
import SwiftUI

@main
struct WegoHApp: App {
    @UIApplicationDelegateAdaptor(WegoAppDelegate.self) private var appDelegate
    @Environment(\.scenePhase) private var scenePhase
    @State private var sessionManager = SessionManager()

    init() {
        #if DEBUG
        if let fixture = TripMusicUIFixture.sessionIfRequested() ?? TripFriendInvitationUIFixture.sessionIfRequested() ?? LocalServerUIFixture.sessionIfRequested() ?? CourseDiscoveryUIFixture.sessionIfRequested() ?? TripRouteUIFixture.sessionIfRequested() ?? TripActivityUIFixture.sessionIfRequested() ?? FriendsUIFixture.sessionIfRequested() ?? CourseUIFixture.sessionIfRequested() {
            _sessionManager = State(initialValue: fixture)
        }
        #endif
        if let key = APIKeys.mapAPIKey?.trimmingCharacters(in: .whitespacesAndNewlines), !key.isEmpty {
            SDKInitializer.InitSDK(appKey: key)
        }
    }

    var body: some Scene {
        WindowGroup {
            Group {
                #if DEBUG
                if WegoLoadingUIFixture.requested { WegoLoadingUIFixture() }
                else { sessionRoot }
                #else
                sessionRoot
                #endif
            }
                #if DEBUG
                .defaultAppStorage(LocalServerUIFixture.firstRunStorage ?? .standard)
                #endif
                .tint(WegoTokens.Palette.accent)
                .environment(sessionManager)
                .onOpenURL { sessionManager.handleIncomingURL($0) }
                .task(id: sessionManager.phase) {
                    #if DEBUG
                    if TripPushUIFixture.requested { TripPushUIFixture.bind(session: sessionManager); return }
                    if ProcessInfo.processInfo.arguments.contains(where: { $0.contains("-ui-") || $0 == "-profile-ui-testing" }) { return }
                    #endif
                    await IPhonePushManager.shared.update(session: sessionManager)
                }
        }
        .onChange(of: scenePhase, initial: true) { _, phase in
            #if DEBUG
            if WegoLoadingUIFixture.requested { return }
            #endif
            if phase == .active {
                Task { await sessionManager.restore() }
            }
        }
    }

    @ViewBuilder private var sessionRoot: some View {
        switch sessionManager.phase {
        case .checkingSession:
            WegoLoadingView("로그인 확인 중", layout: .launch)
                .background(WegoTokens.Palette.background.ignoresSafeArea())
        case .restoreFailed:
            WegoLoadingFailureView(message: sessionManager.message ?? "로그인 정보를 확인할 수 없어요.") {
                Task { await sessionManager.restore() }
            }
        case .signingOut:
            WegoLoadingView("로그아웃 중", layout: .launch)
        case .logoutPending:
            WegoLoadingFailureView(message: sessionManager.message ?? "로그아웃을 마치지 못했어요.") {
                Task { await sessionManager.signOut() }
            }
        case .signedOut, .signingIn, .signedIn:
            #if DEBUG
            if TripMusicUIFixture.requested { TripMusicUIFixture() }
            else if TripFriendInvitationUIFixture.requested { TripFriendInvitationUIFixture() }
            else if TripRouteUIFixture.requested { TripRouteUIFixture() }
            else if TripActivityUIFixture.requested { TripActivityUIFixture() }
            else { WalkthroughView() }
            #else
            WalkthroughView()
            #endif
        }
    }
}
