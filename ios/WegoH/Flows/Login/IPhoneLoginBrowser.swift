import AuthenticationServices
import SwiftUI

@MainActor
protocol IPhoneLoginBrowsing {
    func authenticate(url: URL, expiresAt: Date, state: String, anchor: ASPresentationAnchor) async throws -> URL
    func acceptIncomingURL(_ url: URL)
    func cancel()
}

@MainActor
final class IPhoneLoginBrowser: IPhoneLoginBrowsing {
    enum Failure: Error {
        case unavailable
        case expired
    }

    private final class Presentation: NSObject, ASWebAuthenticationPresentationContextProviding {
        let window: ASPresentationAnchor

        init(window: ASPresentationAnchor) {
            self.window = window
        }

        func presentationAnchor(for session: ASWebAuthenticationSession) -> ASPresentationAnchor {
            window
        }
    }

    private struct Attempt {
        let id: UUID
        let state: String
        let session: ASWebAuthenticationSession
        let presentation: Presentation
        let timer: Task<Void, Never>
        let continuation: CheckedContinuation<URL, Error>
    }

    private var active: Attempt?

    func authenticate(url: URL, expiresAt: Date, state: String, anchor: ASPresentationAnchor) async throws -> URL {
        let id = UUID()
        return try await withTaskCancellationHandler {
            try Task.checkCancellation()
            return try await withCheckedThrowingContinuation { continuation in
                guard active == nil, anchor.windowScene?.activationState == .foregroundActive else {
                    continuation.resume(throwing: Failure.unavailable)
                    return
                }
                let remaining = expiresAt.timeIntervalSinceNow
                guard remaining > 0 else {
                    continuation.resume(throwing: Failure.expired)
                    return
                }
                let callback: ASWebAuthenticationSession.CompletionHandler = { [weak self] url, error in
                    Task { @MainActor in
                        let result: Result<URL, Error>
                        if let error = error as? ASWebAuthenticationSessionError, error.code == .canceledLogin {
                            result = .failure(CancellationError())
                        } else if expiresAt <= .now {
                            result = .failure(Failure.expired)
                        } else if error == nil, let url {
                            result = .success(url)
                        } else {
                            result = .failure(Failure.unavailable)
                        }
                        self?.complete(id, result: result)
                    }
                }
                let session: ASWebAuthenticationSession
                if #available(iOS 17.4, *) {
                    session = ASWebAuthenticationSession(url: url, callback: .customScheme("io.wegoh.iphone"), completionHandler: callback)
                } else {
                    session = ASWebAuthenticationSession(url: url, callbackURLScheme: "io.wegoh.iphone", completionHandler: callback)
                }
                let presentation = Presentation(window: anchor)
                session.presentationContextProvider = presentation
                let timer = Task { [weak self] in
                    do {
                        try await Task.sleep(for: .seconds(remaining))
                    } catch { return }
                    self?.complete(id, result: .failure(Failure.expired), dismiss: true)
                }
                active = Attempt(id: id, state: state, session: session, presentation: presentation, timer: timer, continuation: continuation)
                if !session.start() { complete(id, result: .failure(Failure.unavailable)) }
            }
        } onCancel: {
            Task { @MainActor in self.complete(id, result: .failure(CancellationError()), dismiss: true) }
        }
    }

    func cancel() {
        guard let id = active?.id else { return }
        complete(id, result: .failure(CancellationError()), dismiss: true)
    }

    func acceptIncomingURL(_ url: URL) {
        guard let attempt = active,
              let parts = URLComponents(url: url, resolvingAgainstBaseURL: false),
              parts.scheme == "io.wegoh.iphone", parts.host == "login",
              parts.user == nil, parts.password == nil, parts.port == nil,
              parts.percentEncodedPath == "/callback", parts.fragment == nil,
              let items = parts.queryItems, items.count == 2,
              items.contains(URLQueryItem(name: "state", value: attempt.state)) else { return }
        complete(attempt.id, result: .success(url), dismiss: true)
    }

    private func complete(_ id: UUID, result: Result<URL, Error>, dismiss: Bool = false) {
        guard let attempt = active, attempt.id == id else { return }
        active = nil
        attempt.timer.cancel()
        if dismiss { attempt.session.cancel() }
        attempt.continuation.resume(with: result)
    }
}

struct IPhoneLoginWindowReader: UIViewRepresentable {
    let onWindow: (UIWindow?) -> Void

    final class WindowView: UIView {
        var onWindow: ((UIWindow?) -> Void)?

        override func didMoveToWindow() {
            super.didMoveToWindow()
            let notify = onWindow
            DispatchQueue.main.async { [weak window] in notify?(window) }
        }
    }

    func makeUIView(context: Context) -> WindowView {
        let view = WindowView()
        view.isUserInteractionEnabled = false
        view.onWindow = onWindow
        return view
    }

    func updateUIView(_ view: WindowView, context: Context) {
        view.onWindow = onWindow
    }
}
