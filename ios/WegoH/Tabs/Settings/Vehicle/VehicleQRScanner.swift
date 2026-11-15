import AVFoundation
import SwiftUI
import VisionKit

struct VehicleQRScanner: View {
    let onScan: (String) -> Void

    @Environment(\.scenePhase) private var scenePhase
    @State private var state: ScannerState = .checking

    private enum ScannerState {
        case checking, ready, denied, restricted, unsupported, unavailable
    }

    var body: some View {
        Group {
            switch state {
            case .checking:
                WegoLoadingView("카메라 확인 중")
            case .ready:
                if scenePhase == .active {
                    QRScannerCamera(onScan: onScan, onUnavailable: { state = .unavailable })
                        .safeAreaInset(edge: .bottom) {
                            Text("차량 화면의 연결 QR 코드를 비춰 주세요.")
                                .font(WegoTokens.Typography.body)
                                .frame(maxWidth: .infinity)
                                .padding(WegoTokens.Space.medium)
                                .background(.regularMaterial)
                        }
                        .accessibilityIdentifier("vehicleScannerCamera")
                }
            case .denied:
                ContentUnavailableView {
                    Label("카메라 권한이 꺼져 있어요", systemImage: "camera")
                } description: {
                    Text("차량 QR 코드를 읽으려면 iPhone 설정에서 카메라를 허용해 주세요.")
                } actions: {
                    Link("iPhone 설정 열기", destination: URL(string: UIApplication.openSettingsURLString)!)
                }
                .accessibilityIdentifier("vehicleScannerDenied")
            case .restricted:
                ContentUnavailableView("카메라 사용이 제한되어 있어요", systemImage: "camera")
                    .accessibilityIdentifier("vehicleScannerRestricted")
            case .unsupported:
                ContentUnavailableView("QR 스캔을 사용할 수 없어요", systemImage: "qrcode.viewfinder",
                                       description: Text("코드 직접 입력으로 연결해 주세요."))
                    .accessibilityIdentifier("vehicleScannerUnavailable")
            case .unavailable:
                ContentUnavailableView {
                    Label("카메라를 열 수 없어요", systemImage: "camera")
                } actions: {
                    Button("다시 시도") { Task { await checkCamera() } }
                }
                .accessibilityIdentifier("vehicleScannerUnavailable")
            }
        }
        .task(id: scenePhase) {
            if scenePhase == .active {
                await checkCamera()
            } else {
                state = .checking
            }
        }
    }

    @MainActor
    private func checkCamera() async {
        guard DataScannerViewController.isSupported, AVCaptureDevice.default(for: .video) != nil else {
            state = .unsupported
            return
        }
        if AVCaptureDevice.authorizationStatus(for: .video) == .notDetermined {
            _ = await AVCaptureDevice.requestAccess(for: .video)
        }
        guard !Task.isCancelled else { return }
        switch AVCaptureDevice.authorizationStatus(for: .video) {
        case .authorized: state = DataScannerViewController.isAvailable ? .ready : .unavailable
        case .denied: state = .denied
        case .restricted: state = .restricted
        default: state = .unavailable
        }
    }
}

private struct QRScannerCamera: UIViewControllerRepresentable {
    let onScan: (String) -> Void
    let onUnavailable: () -> Void

    func makeUIViewController(context: Context) -> Controller {
        Controller(onScan: onScan, onUnavailable: onUnavailable)
    }

    func updateUIViewController(_ controller: Controller, context: Context) {}

    static func dismantleUIViewController(_ controller: Controller, coordinator: ()) {
        controller.stop()
    }

    final class Controller: UIViewController, DataScannerViewControllerDelegate {
        private let scanner = DataScannerViewController(
            recognizedDataTypes: [.barcode(symbologies: [.qr])],
            recognizesMultipleItems: false,
            isHighFrameRateTrackingEnabled: false,
            isHighlightingEnabled: true
        )
        private let onScan: (String) -> Void
        private let onUnavailable: () -> Void
        private var delivered = false

        init(onScan: @escaping (String) -> Void, onUnavailable: @escaping () -> Void) {
            self.onScan = onScan
            self.onUnavailable = onUnavailable
            super.init(nibName: nil, bundle: nil)
        }

        @available(*, unavailable)
        required init?(coder: NSCoder) { fatalError() }

        override func viewDidLoad() {
            super.viewDidLoad()
            addChild(scanner)
            scanner.view.frame = view.bounds
            scanner.view.autoresizingMask = [.flexibleWidth, .flexibleHeight]
            view.addSubview(scanner.view)
            scanner.didMove(toParent: self)
        }

        override func viewDidAppear(_ animated: Bool) {
            super.viewDidAppear(animated)
            guard !delivered, UIApplication.shared.applicationState == .active else { return }
            scanner.delegate = self
            do { try scanner.startScanning() }
            catch {
                stop()
                onUnavailable()
            }
        }

        override func viewWillDisappear(_ animated: Bool) {
            stop()
            super.viewWillDisappear(animated)
        }

        func stop() {
            scanner.delegate = nil
            scanner.stopScanning()
        }

        func dataScanner(_ dataScanner: DataScannerViewController, didAdd addedItems: [RecognizedItem],
                         allItems: [RecognizedItem]) {
            guard !delivered, dataScanner.delegate != nil, UIApplication.shared.applicationState == .active else { return }
            for case .barcode(let code) in addedItems {
                guard let raw = code.payloadStringValue, !raw.isEmpty else { continue }
                delivered = true
                stop()
                onScan(raw)
                return
            }
        }

        func dataScanner(_ dataScanner: DataScannerViewController,
                         becameUnavailableWithError error: DataScannerViewController.ScanningUnavailable) {
            guard dataScanner.delegate != nil else { return }
            stop()
            onUnavailable()
        }
    }
}
