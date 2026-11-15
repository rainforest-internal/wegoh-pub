import Observation
import UIKit
import UserNotifications

@MainActor @Observable
final class IPhonePushManager {
    static let shared = IPhonePushManager()
    private(set) var authorization: UNAuthorizationStatus = .notDetermined
    private(set) var isWorking = false
    private(set) var message: String?
    private(set) var openedNotification: IPhonePushNotification?
    private(set) var foregroundTripInvitation: IPhonePushNotification?
    private(set) var foregroundHandRaise: IPhonePushNotification?
    @ObservationIgnored private var recentInvitationIDs: [String] = []
    private var pendingNotification: IPhonePushNotification?
    private var accountID: String?
    private var deviceToken: Data?
    private var registeredIdentity: String?
    private weak var session: SessionManager?
    private let api = IPhonePushAPI()
    private let center = UNUserNotificationCenter.current()
    private let installationID: String = {
        let key = "push.installationID"
        if let value = UserDefaults.standard.string(forKey: key), UUID(uuidString: value) != nil { return value }
        let value = UUID().uuidString.lowercased()
        UserDefaults.standard.set(value, forKey: key)
        return value
    }()

    var isAllowed: Bool { authorization == .authorized || authorization == .provisional || authorization == .ephemeral }
    var status: String {
        switch authorization {
        case .notDetermined: "설정 전"
        case .denied: "허용 안 함"
        case .authorized, .provisional, .ephemeral: "허용됨"
        @unknown default: "확인할 수 없음"
        }
    }

    func update(session: SessionManager) async {
        self.session = session
        if session.phase == .signingOut || session.phase == .logoutPending || (session.phase == .signedOut && accountID != nil) {
            resetAccount(nil)
            pendingNotification = nil
        }
        guard session.phase == .signedIn, let account = session.current else { return }
        if accountID != account.accountID { resetAccount(account.accountID) }
        authorization = await center.notificationSettings().authorizationStatus
        guard session.current == account, session.phase == .signedIn else { return }
        if let pending = pendingNotification { receive(pending) }
        if isAllowed {
            UIApplication.shared.registerForRemoteNotifications()
            await registerIfNeeded()
        } else if authorization == .denied {
            do { try await session.withToken(for: account) { try await self.api.unregister(installationID: self.installationID, token: $0) }; registeredIdentity = nil }
            catch { message = "알림 해제를 확인하지 못했어요. 다시 확인해 주세요." }
        }
    }

    func requestPermission(session: SessionManager) async {
        guard !isWorking, session.current != nil else { return }
        isWorking = true; message = nil
        defer { isWorking = false }
        do {
            _ = try await center.requestAuthorization(options: [.alert, .sound, .badge])
            await update(session: session)
        } catch { message = "알림 권한을 확인하지 못했어요. 다시 시도해 주세요." }
    }

    func didRegister(_ token: Data) {
        deviceToken = token
        Task { await registerIfNeeded() }
    }
    func registrationFailed() { message = "알림을 켜지 못했어요. 알림 설정에서 다시 시도해 주세요." }

    private func registerIfNeeded() async {
        guard isAllowed, let session, session.phase == .signedIn, let account = session.current,
              accountID == account.accountID, let deviceToken else { return }
        let identity = account.accountID + ":" + String(account.expiresAt.timeIntervalSince1970) + ":" + deviceToken.base64EncodedString()
        guard registeredIdentity != identity else { return }
        registeredIdentity = identity
        #if DEBUG
        let environment = "sandbox"
        #else
        let environment = "production"
        #endif
        do {
            try await session.withToken(for: account) {
                try await self.api.register(installationID: self.installationID, deviceToken: deviceToken, environment: environment, token: $0)
            }
            guard session.current == account else { registeredIdentity = nil; return }
            message = nil
        } catch {
            if registeredIdentity == identity { registeredIdentity = nil }
            if session.current == account { message = "알림을 켜지 못했어요. 다시 시도해 주세요." }
        }
    }

    #if DEBUG
    func bindForUITesting(session: SessionManager) {
        guard TripPushUIFixture.requested, session.phase == .signedIn, let account = session.current else { return }
        self.session = session
        if accountID != account.accountID { resetAccount(account.accountID) }
        if let pendingNotification { receive(pendingNotification) }
    }
    #endif

    private func resetAccount(_ id: String?) {
        accountID = id
        registeredIdentity = nil
        openedNotification = nil
        foregroundTripInvitation = nil
        foregroundHandRaise = nil
        recentInvitationIDs.removeAll()
    }

    func accepts(_ notification: IPhonePushNotification) -> Bool {
        accountID == notification.accountID && session?.phase == .signedIn && session?.current?.accountID == notification.accountID
    }
    @discardableResult
    func receiveForeground(_ notification: IPhonePushNotification) -> Bool {
        guard accepts(notification) else { return false }
        if notification.kind == .handRaise || notification.kind == .handRaiseReaction { foregroundHandRaise = notification }
        guard notification.kind == .tripInvitation, !recentInvitationIDs.contains(notification.eventID) else { return true }
        if recentInvitationIDs.count >= 64 { recentInvitationIDs.removeFirst() }
        recentInvitationIDs.append(notification.eventID)
        foregroundTripInvitation = notification
        return true
    }

    func receive(_ notification: IPhonePushNotification) {
        guard accountID != nil else { pendingNotification = notification; return }
        pendingNotification = nil
        guard accepts(notification) else { return }
        openedNotification = notification
    }
}

final class WegoAppDelegate: NSObject, UIApplicationDelegate, UNUserNotificationCenterDelegate {
    func application(_ application: UIApplication, didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil) -> Bool {
        UNUserNotificationCenter.current().delegate = self
        return true
    }
    func application(_ application: UIApplication, didRegisterForRemoteNotificationsWithDeviceToken deviceToken: Data) {
        IPhonePushManager.shared.didRegister(deviceToken)
    }
    func application(_ application: UIApplication, didFailToRegisterForRemoteNotificationsWithError error: Error) {
        IPhonePushManager.shared.registrationFailed()
    }
    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification) async -> UNNotificationPresentationOptions {
        guard let value = IPhonePushNotification(userInfo: notification.request.content.userInfo) else { return [] }
        return await MainActor.run { IPhonePushManager.shared.receiveForeground(value) ? [.banner, .sound] : [] }
    }
    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse) async {
        guard response.actionIdentifier == UNNotificationDefaultActionIdentifier,
              let value = IPhonePushNotification(userInfo: response.notification.request.content.userInfo) else { return }
        await MainActor.run { IPhonePushManager.shared.receive(value) }
    }
}
