import AuthenticationServices
import Foundation
import Observation

struct AccountSession: Equatable {
    let accountID: String
    let displayName: String
    let expiresAt: Date
    var scopes: Set<String> = ["account:read"]
}

@MainActor
@Observable
final class SessionManager {
    enum Phase: Hashable {
        case signedOut, signingIn, checkingSession, signedIn, restoreFailed, signingOut, logoutPending
    }

    private(set) var phase: Phase = .checkingSession
    private(set) var needsReauthentication = false
    private(set) var message: String?
    private var verifiedSession: AccountSession?

    private let api: any IPhoneSessionServing
    private let browser: any IPhoneLoginBrowsing
    private let credentials: any IPhoneCredentialStoring
    @ObservationIgnored private var pendingRevokeToken: String?
    @ObservationIgnored private var operation: UUID?
    @ObservationIgnored private var expirationTask: Task<Void, Never>?
    @ObservationIgnored private var retryAfter: [Phase: Date] = [:]

    init(api: any IPhoneSessionServing = IPhoneSessionAPI(),
         browser: (any IPhoneLoginBrowsing)? = nil,
         credentials: (any IPhoneCredentialStoring)? = nil) {
        self.api = api
        self.browser = browser ?? IPhoneLoginBrowser()
        self.credentials = credentials ?? IPhoneCredentialStore()
    }

    var current: AccountSession? {
        guard let verifiedSession, verifiedSession.expiresAt > .now else { return nil }
        return verifiedSession
    }

    func withToken<T>(for account: AccountSession, _ work: (String) async throws -> T) async throws -> T {
        guard phase == .signedIn, current == account else { throw CancellationError() }
        guard let credential = try credentials.load(), !credential.logoutPending else {
            clearVerified()
            discardCredential(message: "로그인 정보를 다시 확인해 주세요.")
            throw IPhoneSessionError.invalidSession
        }
        do {
            let result = try await work(credential.token)
            try Task.checkCancellation()
            guard phase == .signedIn, current == account else { throw CancellationError() }
            return result
        } catch IPhoneSessionError.invalidSession {
            if current == account {
                clearVerified()
                discardCredential(message: "로그인 시간이 끝났어요. 다시 로그인해 주세요.")
            }
            throw IPhoneSessionError.invalidSession
        }
    }

    func updateDisplayName(_ name: String, for account: AccountSession) {
        guard phase == .signedIn, current == account else { return }
        verifiedSession = AccountSession(accountID: account.accountID, displayName: name,
                                         expiresAt: account.expiresAt, scopes: account.scopes)
    }

    func signIn(anchor: ASPresentationAnchor) async {
        guard phase == .signedOut, canRequest(.signingIn) else { return }
        do {
            if try credentials.load() != nil {
                await restore()
                return
            }
        } catch {
            phase = .restoreFailed
            message = "iPhone에서 로그인 정보를 읽을 수 없어요. 잠금을 해제한 뒤 다시 시도해 주세요."
            return
        }

        let id = begin(.signingIn)
        var attempt: IPhoneLoginAttempt?
        do {
            let request = try await api.beginLogin()
            attempt = request
            guard operation == id else { throw CancellationError() }
            let callback = try await browser.authenticate(url: request.authorizationURL, expiresAt: request.expiresAt, state: request.state, anchor: anchor)
            guard operation == id else { throw CancellationError() }
            let receipt = try await api.exchange(request, callbackURL: callback)
            attempt = nil
            guard operation == id, !Task.isCancelled else {
                revokeUnusedToken(receipt.accessToken)
                throw CancellationError()
            }
            guard receipt.account.expiresAt > .now else {
                revokeUnusedToken(receipt.accessToken)
                throw IPhoneSessionError.expired
            }
            do {
                try credentials.saveToken(receipt.accessToken)
            } catch {
                revokeUnusedToken(receipt.accessToken)
                throw error
            }
            applyVerified(receipt.account)
        } catch {
            if let attempt {
                Task { [api] in try? await api.cancel(attempt) }
            }
            guard operation == id else { return }
            operation = nil
            phase = .signedOut
            if error is CancellationError {
                message = nil
            } else if let browserError = error as? IPhoneLoginBrowser.Failure {
                switch browserError {
                case .expired: message = "로그인 시간이 지났어요. 다시 시작해 주세요."
                case .unavailable: message = "인증 화면을 열 수 없어요. 다시 시도해 주세요."
                }
            } else {
                report(error, during: .signingIn, fallback: "로그인 정보를 저장할 수 없어요. 다시 시도해 주세요.")
            }
        }
    }

    func cancelSignIn() {
        guard phase == .signingIn else { return }
        operation = nil
        phase = .signedOut
        message = nil
        browser.cancel()
    }

    func handleIncomingURL(_ url: URL) {
        guard phase == .signingIn else { return }
        browser.acceptIncomingURL(url)
    }

    func restore() async {
        guard operation == nil, phase != .logoutPending else { return }
        if let verifiedSession, verifiedSession.expiresAt <= .now {
            expire()
            return
        }
        if phase == .signedIn, verifiedSession != nil { return }
        let token: String
        do {
            guard let stored = try credentials.load() else {
                if phase != .signedOut { message = nil }
                clearVerified()
                phase = .signedOut
                return
            }
            if stored.logoutPending {
                clearVerified()
                phase = .logoutPending
                message = "이 iPhone의 로그아웃이 끝나지 않았어요. 다시 시도해 주세요."
                return
            }
            token = stored.token
        } catch {
            clearVerified()
            phase = .restoreFailed
            message = "iPhone에서 로그인 정보를 읽을 수 없어요. 잠금을 해제한 뒤 다시 시도해 주세요."
            return
        }
        let id = begin(.checkingSession)
        do {
            guard canRequest(.checkingSession) else {
                clearVerified()
                phase = .restoreFailed
                operation = nil
                return
            }
            let account = try await api.restore(token: token)
            guard operation == id else { return }
            if account.expiresAt <= .now || (verifiedSession.map { $0.expiresAt <= .now } ?? false) {
                expire()
            } else {
                applyVerified(account)
            }
        } catch {
            guard operation == id else { return }
            operation = nil
            if let verifiedSession, verifiedSession.expiresAt <= .now {
                expire()
                return
            }
            clearVerified()
            if case IPhoneSessionError.invalidSession = error {
                discardCredential(message: "로그인 시간이 끝났어요. 다시 로그인해 주세요.")
            } else {
                phase = .restoreFailed
                report(error, during: .checkingSession, fallback: "로그인 정보를 확인할 수 없어요. 다시 시도해 주세요.")
            }
        }
    }

    func acknowledgeReauthentication() {
        needsReauthentication = false
    }

    func signOut() async {
        guard phase != .signingIn, phase != .signingOut, phase != .signedOut else { return }
        needsReauthentication = false
        clearVerified()
        let id = begin(.signingOut)
        do {
            if let token = try prepareRevocation() {
                guard canRequest(.signingOut) else {
                    operation = nil
                    phase = .logoutPending
                    return
                }
                do {
                    try await api.logout(token: token)
                } catch IPhoneSessionError.invalidSession {
                }
            }
            guard operation == id else { return }
            try credentials.clearToken()
            pendingRevokeToken = nil
            operation = nil
            phase = .signedOut
        } catch {
            guard operation == id else { return }
            operation = nil
            phase = .logoutPending
            report(error, during: .signingOut, fallback: "로그아웃을 마치지 못했어요. 다시 시도해 주세요.")
        }
    }

    private func prepareRevocation() throws -> String? {
        if pendingRevokeToken == nil {
            do {
                pendingRevokeToken = try credentials.load()?.token
            } catch {
                do { try credentials.markLogoutPending() }
                catch { try credentials.clearToken() }
                throw error
            }
        }
        guard let pendingRevokeToken else { return nil }
        do { try credentials.markLogoutPending() }
        catch { try? credentials.clearToken() }
        return pendingRevokeToken
    }

    private func canRequest(_ action: Phase) -> Bool {
        if let date = retryAfter[action], date > .now {
            let seconds = ceil(max(1, date.timeIntervalSinceNow))
            message = "\(seconds.formatted(.number.precision(.fractionLength(0))))초 후에 다시 시도해 주세요."
            return false
        }
        return true
    }

    private func begin(_ phase: Phase) -> UUID {
        let id = UUID()
        operation = id
        self.phase = phase
        message = nil
        return id
    }

    private func applyVerified(_ account: AccountSession) {
        operation = nil
        needsReauthentication = false
        phase = .signedIn
        message = nil
        verifiedSession = account
        expirationTask?.cancel()
        expirationTask = Task { [weak self] in
            do {
                try await Task.sleep(for: .seconds(max(0, account.expiresAt.timeIntervalSinceNow)))
            } catch { return }
            guard let self, self.verifiedSession == account else { return }
            self.expire()
        }
    }

    private func clearVerified() {
        expirationTask?.cancel()
        expirationTask = nil
        verifiedSession = nil
    }

    private func expire() {
        operation = nil
        clearVerified()
        discardCredential(message: "로그인 시간이 끝났어요. 다시 로그인해 주세요.")
    }

    private func discardCredential(message: String) {
        needsReauthentication = true
        do {
            try credentials.clearToken()
            phase = .signedOut
            self.message = message
        } catch {
            try? credentials.markLogoutPending()
            phase = .logoutPending
            self.message = "이 iPhone의 로그인 정보를 지울 수 없어요. 다시 시도해 주세요."
        }
    }

    private func report(_ error: Error, during action: Phase, fallback: String) {
        if let apiError = error as? IPhoneSessionError {
            if case let .rateLimited(seconds) = apiError, let seconds, seconds > 0 {
                retryAfter[action] = Date(timeIntervalSinceNow: TimeInterval(seconds))
            }
            message = apiError.errorDescription ?? fallback
        } else {
            message = fallback
        }
    }

    private func revokeUnusedToken(_ token: String) {
        Task { [api] in try? await api.logout(token: token) }
    }

    deinit {
        expirationTask?.cancel()
    }
}
