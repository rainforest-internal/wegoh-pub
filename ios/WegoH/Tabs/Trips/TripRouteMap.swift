import SwiftUI

struct TripRouteMap: View {
    let detail: IPhoneTripDetail
    var showsTitle = true
    var onPresentation: ((Bool) -> Void)? = nil
    /// 다른 차 현재 위치 표식(`otherCarMarkers`). 경로 장소 번호와 지도 시점에는 영향을 주지 않는다.
    var cars: [WegoMapMarker] = []
    @State private var expanded = false

    @Environment(SessionManager.self) private var session
    @State private var routes = TripRouteGeometryCache()
    @State private var cacheAccount: String?
    @State private var route: CourseRoute?
    @State private var loadedKey: ReadKey?
    @State private var read = UUID()
    @State private var loading = true
    @State private var failed = false
    private struct ReadKey: Equatable {
        let accountID: String?
        let points: [CourseCoordinate]
    }
    private var orderedMarkers: [WegoMapMarker] { Self.markers(courses: detail.courses, car: detail.myCar) }
    private var points: [CourseCoordinate] { orderedMarkers.map { CourseCoordinate(lat: $0.latitude, lng: $0.longitude) } }
    private var key: ReadKey { ReadKey(accountID: session.current?.accountID, points: points) }

    var body: some View {
        if !orderedMarkers.isEmpty {
            VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
                if showsTitle { Text("여행 경로 지도")
                    .font(WegoTokens.Typography.section)
                    .accessibilityAddTraits(.isHeader) }
                Button { expanded = true } label: {
                    WegoMapPreview(markers: Self.numberedMarkers(orderedMarkers) + cars,
                                   path: loadedKey == key ? route?.path ?? [] : [], accessibilityTitle: "여행 경로 지도")
                        .frame(height: WegoTokens.Metrics.courseMapHeight)
                        .clipShape(RoundedRectangle(cornerRadius: WegoTokens.Radius.card))
                        .allowsHitTesting(false)
                }.buttonStyle(.plain)
                    .accessibilityLabel("여행 경로 지도 크게 보기, " + orderedMarkers.map(\.name).joined(separator: ", ")
                        + (cars.isEmpty ? "" : ", 다른 차 " + cars.map(\.name).joined(separator: ", ")))
                    .accessibilityIdentifier("tripRouteMap")
                if points.count > 1 {
                    if loading { ProgressView("도로 경로를 불러오는 중") }
                    else if failed {
                        Button("도로 경로 다시 불러오기") { Task { await load() } }
                            .frame(minHeight: WegoTokens.Metrics.touchTarget)
                    }
                }
            }
            .font(WegoTokens.Typography.caption)
            .task(id: key) { await load() }
            .onChange(of: expanded) { _, value in onPresentation?(value) }
            .sheet(isPresented: $expanded) {
                NavigationStack {
                    WegoMapPreview(markers: Self.numberedMarkers(orderedMarkers) + cars, path: loadedKey == key ? route?.path ?? [] : [],
                                   accessibilityTitle: "여행 전체 경로 지도")
                        .navigationTitle("여행 경로 지도").navigationBarTitleDisplayMode(.inline)
                        .toolbar { ToolbarItem(placement: .cancellationAction) { Button("닫기") { expanded = false } } }
                }
            }
        }
    }

    private func load() async {
        let stamp = UUID(), requested = key
        read = stamp; failed = false; loading = true
        defer { if read == stamp { loading = false } }
        guard let account = session.current else { return }
        if cacheAccount != account.accountID {
            routes = TripRouteGeometryCache(); cacheAccount = account.accountID
        }
        if loadedKey != requested { route = nil }
        do {
            let value = try await routes.route(for: requested.points) { points in
                try await session.withToken(for: account) { try await IPhoneCourseAPI().route(points, token: $0) }
            }
            guard !Task.isCancelled, read == stamp, key == requested, session.current == account else { return }
            route = value; loadedKey = requested
        } catch is CancellationError { }
        catch { if read == stamp && key == requested { failed = true } }
    }

    static func numberedMarkers(_ markers: [WegoMapMarker]) -> [WegoMapMarker] {
        var result: [WegoMapMarker] = []
        var positions: [CourseCoordinate: Int] = [:]
        for (index, marker) in markers.enumerated() {
            let coordinate = CourseCoordinate(lat: marker.latitude, lng: marker.longitude)
            if let position = positions[coordinate] {
                result[position].sequenceLabel = (result[position].sequenceLabel ?? "") + "·\(index + 1)"
            } else {
                positions[coordinate] = result.count
                var numbered = marker; numbered.sequenceLabel = "\(index + 1)"
                result.append(numbered)
            }
        }
        return result
    }

    /// 서버 일행 위치의 차 위치 중 내 차를 뺀 다른 차만 표식으로 만든다. 경로·픽업·드랍은 쓰지 않는다.
    static func otherCarMarkers(detail: IPhoneTripDetail, page: IPhoneTripLocations?) -> [WegoMapMarker] {
        guard let page, page.tripId == detail.id else { return [] }
        let mine = detail.myCar?.id
        return page.cars.compactMap { position in
            guard position.carId != mine, let index = detail.cars.firstIndex(where: { $0.id == position.carId }) else { return nil }
            let car = detail.cars[index]
            let stale = (page.age(of: position) ?? 0) > tripCarLocationStaleSeconds
            let label = "\(car.ordinal ?? (index + 1))호차" + (stale ? " · 이전 위치" : "")
            return WegoMapMarker(id: "car:" + car.id, name: label, latitude: position.latitude, longitude: position.longitude,
                                 sequenceLabel: label, isVehicle: true)
        }
    }

    static func markers(courses: [IPhoneTripCourse], car: IPhoneTripCar?) -> [WegoMapMarker] {
        let courseStops = courses.flatMap { course in
            (course.stops ?? []).map { stop in
                WegoMapMarker(id: "course:\(course.id):\(stop.id)", name: stop.name,
                              latitude: stop.lat, longitude: stop.lng)
            }
        }
        guard let car, car.isMine || car.iRide else { return courseStops }
        func marker(_ place: IPhoneTripCarPlace) -> WegoMapMarker? {
            guard let id = place.id, let kind = place.kind, let lat = place.lat, let lng = place.lng else { return nil }
            return WegoMapMarker(id: "\(kind.rawValue):\(id)", name: place.name, latitude: lat, longitude: lng)
        }
        if let order = car.routePlan?.segments.flatMap(\.items) ?? car.routeOrder, !order.isEmpty {
            let indexed = Dictionary(uniqueKeysWithValues: (courseStops + car.places.compactMap(marker)).map { ($0.id, $0) })
            return order.compactMap { item in
                let key = item.courseId.map { "course:\($0):\(item.ref)" } ?? "\(item.type):\(item.ref)"
                return indexed[key]
            }
        }
        func selected(_ kind: IPhoneTripPlaceKind) -> [WegoMapMarker] {
            car.places.filter { $0.kind == kind && $0.selectedBy?.isEmpty == false }.compactMap(marker)
        }
        return selected(.pickup) + courseStops + selected(.drop)
    }
}

/// 차량 앱은 위치를 10초마다 보내므로 세 번 놓친 위치(30초 초과)는 이전 위치로 구분한다. 서버는 60초 이내 위치만 준다.
let tripCarLocationStaleSeconds: TimeInterval = 30
/// 다른 차 위치를 다시 읽는 주기. 차량 앱의 전송 주기와 같다.
let tripCarLocationRefreshSeconds = 10

@MainActor
final class TripRouteGeometryCache {
    private var cached: [[CourseCoordinate]: CourseRoute] = [:]
    private var order: [[CourseCoordinate]] = []

    func route(for points: [CourseCoordinate],
               load: ([CourseCoordinate]) async throws -> CourseRoute) async throws -> CourseRoute {
        let distinct = points.reduce(into: [CourseCoordinate]()) { if $0.last != $1 { $0.append($1) } }
        guard distinct.count > 1 else { return CourseRoute(distanceMeters: 0, durationSeconds: 0, path: []) }
        var path: [CourseCoordinate] = [], distance = 0.0, duration = 0.0
        var start = 0
        while start < distinct.count - 1 {
            try Task.checkCancellation()
            let end = min(start + 2, distinct.count - 1)
            let leg = Array(distinct[start...end])
            let value: CourseRoute
            if let existing = cached[leg] { value = existing }
            else {
                value = try await load(leg)
                try Task.checkCancellation()
                if order.count >= 64 { cached.removeValue(forKey: order.removeFirst()) }
                cached[leg] = value; order.append(leg)
            }
            path += path.last == value.path.first ? Array(value.path.dropFirst()) : value.path
            distance += value.distanceMeters; duration += value.durationSeconds
            start = end
        }
        return CourseRoute(distanceMeters: distance, durationSeconds: duration, path: path)
    }
}
