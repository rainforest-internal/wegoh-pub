import CoreLocation
import Foundation

@MainActor
final class TripSignalLocation: NSObject, CLLocationManagerDelegate {
    struct Point: Sendable { var lat: Double; var lng: Double; var heading: Double? }
    enum Failure: LocalizedError {
        case permission, unavailable, heading
        var errorDescription: String? {
            switch self {
            case .permission: "들를 곳을 찾으려면 iPhone 설정에서 WegoH 위치 권한을 허용해 주세요."
            case .unavailable: "현재 위치를 확인할 수 없어요. 잠시 후 다시 시도해 주세요."
            case .heading: "진행 방향을 확인할 수 없어요. 차에서 경로 안내를 시작한 뒤 다시 찾거나 장소 없이 요청해 주세요."
            }
        }
    }
    private var continuation: CheckedContinuation<Point, Error>?
    private var timeout: Task<Void, Never>?
    private var heading: Double?
    private lazy var manager: CLLocationManager = {
        let manager = CLLocationManager(); manager.delegate = self
        manager.desiredAccuracy = kCLLocationAccuracyHundredMeters
        return manager
    }()

    func current() async throws -> Point {
        guard continuation == nil else { throw Failure.unavailable }
        return try await withTaskCancellationHandler {
            try await withCheckedThrowingContinuation { result in
                continuation = result
                heading = nil
                switch manager.authorizationStatus {
                case .notDetermined: manager.requestWhenInUseAuthorization()
                case .authorizedAlways, .authorizedWhenInUse: locate()
                default: finish(.failure(Failure.permission))
                }
                timeout = Task { [weak self] in
                    do { try await Task.sleep(for: .seconds(12)); self?.finish(.failure(Failure.unavailable)) }
                    catch { }
                }
            }
        } onCancel: { Task { @MainActor [weak self] in self?.finish(.failure(CancellationError())) } }
    }
    func cancel() { finish(.failure(CancellationError())) }
    private func locate() {
        if CLLocationManager.headingAvailable() { manager.startUpdatingHeading() }
        manager.requestLocation()
    }
    private func finish(_ result: Result<Point, Error>) {
        let waiting = continuation; continuation = nil
        timeout?.cancel(); timeout = nil
        manager.stopUpdatingHeading(); manager.stopUpdatingLocation()
        waiting?.resume(with: result)
    }
    nonisolated func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        Task { @MainActor [weak self] in
            guard let self, self.continuation != nil else { return }
            switch self.manager.authorizationStatus {
            case .authorizedAlways, .authorizedWhenInUse: self.locate()
            case .restricted, .denied: self.finish(.failure(Failure.permission))
            default: break
            }
        }
    }
    nonisolated func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        guard let location = locations.last, location.horizontalAccuracy >= 0,
              abs(location.timestamp.timeIntervalSinceNow) < 30 else { return }
        let point = Point(lat: location.coordinate.latitude, lng: location.coordinate.longitude,
                          heading: location.course >= 0 ? location.course : nil)
        Task { @MainActor [weak self] in
            guard let self, self.continuation != nil else { return }
            var point = point
            point.heading = point.heading ?? self.heading
            self.finish(.success(point))
        }
    }
    nonisolated func locationManager(_ manager: CLLocationManager, didUpdateHeading newHeading: CLHeading) {
        guard newHeading.headingAccuracy >= 0 else { return }
        let angle = newHeading.trueHeading >= 0 ? newHeading.trueHeading : newHeading.magneticHeading
        Task { @MainActor [weak self] in self?.heading = angle }
    }
    nonisolated func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        Task { @MainActor [weak self] in self?.finish(.failure(Failure.unavailable)) }
    }
}
