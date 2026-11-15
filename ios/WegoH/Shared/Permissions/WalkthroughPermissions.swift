import AVFAudio
import AVFoundation
import CoreLocation
import SwiftUI

@MainActor
final class WalkthroughPermissions: NSObject, ObservableObject, CLLocationManagerDelegate {
    private enum Request: Equatable {
        case location
        case microphone(UUID)
        case waitingForCamera
        case camera(UUID)
    }

    @Published private var location: CLAuthorizationStatus = .notDetermined
    @Published private var microphone: AVAudioApplication.recordPermission = .undetermined
    @Published private var camera: AVAuthorizationStatus = .notDetermined
    @Published private var cameraRequestUnavailable = false
    @Published private var locationServicesOff = false
    @Published private var request: Request?
    private var phase: ScenePhase = .inactive
    private lazy var manager: CLLocationManager = {
        let manager = CLLocationManager()
        manager.delegate = self
        return manager
    }()

    var isRequesting: Bool { request != nil }
    private var cameraPending: Bool { camera == .notDetermined && !cameraRequestUnavailable }
    var hasPending: Bool { location == .notDetermined || microphone == .undetermined || cameraPending }

    var locationLabel: String {
        switch location {
        case .notDetermined: "설정 전"
        case .restricted: "사용 제한"
        case .denied: locationServicesOff ? "위치 서비스 꺼짐" : "허용 안 함"
        case .authorizedAlways, .authorizedWhenInUse: "허용됨"
        @unknown default: "확인할 수 없음"
        }
    }

    var microphoneLabel: String {
        switch microphone {
        case .undetermined: "설정 전"
        case .denied: "허용 안 함"
        case .granted: "허용됨"
        @unknown default: "확인할 수 없음"
        }
    }

    var cameraLabel: String {
        switch camera {
        case .notDetermined: cameraRequestUnavailable ? "확인할 수 없음" : "설정 전"
        case .restricted: "사용 제한"
        case .denied: "허용 안 함"
        case .authorized: "허용됨"
        @unknown default: "확인할 수 없음"
        }
    }

    func refresh() {
        location = manager.authorizationStatus
        microphone = AVAudioApplication.shared.recordPermission
        camera = AVCaptureDevice.authorizationStatus(for: .video)
        if camera != .notDetermined { cameraRequestUnavailable = false }
        if location == .denied {
            Task {
                let enabled = await Self.locationServicesEnabled()
                if location == .denied { locationServicesOff = !enabled }
            }
        } else {
            locationServicesOff = false
        }
    }

    private nonisolated static func locationServicesEnabled() async -> Bool {
        CLLocationManager.locationServicesEnabled()
    }

    func updateScene(_ phase: ScenePhase) {
        self.phase = phase
        if phase == .background {
            request = nil
        } else if phase == .active {
            refresh()
            continueIfActive()
        }
    }

    func requestAll() {
        guard phase == .active, request == nil else { return }
        refresh()
        if location == .notDetermined {
            request = .location
            manager.requestWhenInUseAuthorization()
        } else {
            requestMicrophoneIfNeeded()
        }
    }

    nonisolated func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        Task { @MainActor [weak self] in
            self?.refresh()
            self?.continueIfActive()
        }
    }

    private func continueIfActive() {
        guard phase == .active else { return }
        switch request {
        case .location where location != .notDetermined: requestMicrophoneIfNeeded()
        case .waitingForCamera: requestCameraIfNeeded()
        default: break
        }
    }

    private func requestMicrophoneIfNeeded() {
        guard microphone == .undetermined else {
            requestCameraIfNeeded()
            return
        }
        let id = UUID()
        request = .microphone(id)
        AVAudioApplication.requestRecordPermission { [weak self] _ in
            Task { @MainActor [weak self] in
                guard let self, self.request == .microphone(id) else { return }
                self.refresh()
                self.request = .waitingForCamera
                self.continueIfActive()
            }
        }
    }

    private func requestCameraIfNeeded() {
        guard cameraPending else {
            request = nil
            return
        }
        let id = UUID()
        request = .camera(id)
        AVCaptureDevice.requestAccess(for: .video) { [weak self] _ in
            Task { @MainActor [weak self] in
                guard let self, self.request == .camera(id) else { return }
                self.refresh()
                self.cameraRequestUnavailable = self.camera == .notDetermined
                self.request = nil
            }
        }
    }
}
