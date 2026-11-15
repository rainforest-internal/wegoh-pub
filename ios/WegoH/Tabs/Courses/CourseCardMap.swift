import SwiftUI

struct CourseCardRevision: Hashable {
    let id: String
    let version: Int
    let checksum: String

    init(_ item: CourseDiscoveryItem) {
        id = item.id; version = item.version; checksum = item.checksum
    }

    init(_ course: CourseSummary) {
        id = course.id; version = course.version; checksum = course.checksum
    }
}

@MainActor
final class CourseCardPlaces {
    private struct RouteKey: Hashable {
        let revision: CourseCardRevision
        let points: [CourseCoordinate]
    }

    private struct Flight {
        let id: UUID
        let task: Task<CourseRoute, Error>
    }

    private var routes: [RouteKey: CourseRoute] = [:]
    private var routeOrder: [RouteKey] = []
    private var inFlight: [RouteKey: Flight] = [:]

    func route(for revision: CourseCardRevision, points: [CourseCoordinate],
               load: @escaping @MainActor () async throws -> CourseRoute) async throws -> CourseRoute {
        let key = RouteKey(revision: revision, points: points)
        while true {
            try Task.checkCancellation()
            if let cached = routes[key] { return cached }
            if let flight = inFlight[key] {
                let value = try await flight.task.value
                try Task.checkCancellation()
                return value
            }
            if inFlight.count < 2 { break }
            try await Task.sleep(for: .milliseconds(100))
        }

        let id = UUID()
        let task = Task { @MainActor [weak self] in
            defer {
                if self?.inFlight[key]?.id == id { self?.inFlight[key] = nil }
            }
            let value = try await load()
            try Task.checkCancellation()
            if let self, self.inFlight[key]?.id == id {
                if self.routeOrder.count >= 24 { self.routes.removeValue(forKey: self.routeOrder.removeFirst()) }
                self.routes[key] = value
                self.routeOrder.append(key)
            }
            return value
        }
        inFlight[key] = Flight(id: id, task: task)
        let result = try await task.value
        try Task.checkCancellation()
        return result
    }

    func clear() {
        for flight in inFlight.values { flight.task.cancel() }
        inFlight.removeAll()
        routes.removeAll()
        routeOrder.removeAll()
    }
}

struct CourseCardMap: View {
    @Environment(SessionManager.self) private var session
    @Environment(\.scenePhase) private var scenePhase
    var height = WegoTokens.Metrics.courseDetailMapHeight
    /// 목록 응답의 장소. 카드가 보이는 즉시 표식을 그리고 도로 경로만 따로 읽는다.
    let stops: [CourseCardStop]
    let loadRoute: ([CourseCoordinate]) async throws -> CourseRoute

    @State private var intersectsViewport = false
    @State private var appeared = false
    @State private var path: [CourseCoordinate] = []
    @State private var routeFailed = false

    private var enabled: Bool {
        appeared && intersectsViewport && scenePhase == .active && session.phase == .signedIn
    }

    var body: some View {
        Group {
            if enabled {
                WegoMapPreview(markers: stops.map { .init(id: $0.id, name: $0.name, latitude: $0.lat, longitude: $0.lng) },
                               path: path, accessibilityTitle: "경로 장소 지도", isThumbnail: true)
                    .overlay(alignment: .topTrailing) {
                        if routeFailed {
                            Text("경로 조회 실패")
                                .font(WegoTokens.Typography.caption)
                                .foregroundStyle(WegoTokens.Palette.text)
                                .padding(WegoTokens.Space.xSmall)
                                .background(WegoTokens.Palette.surface, in: Capsule())
                                .padding(WegoTokens.Space.xSmall)
                        }
                    }
            } else {
                Color.clear
            }
        }
        .frame(maxWidth: .infinity)
        .frame(height: height)
        .background(WegoTokens.Palette.surface)
        .clipShape(RoundedRectangle(cornerRadius: WegoTokens.Radius.control))
        .allowsHitTesting(false)
        .accessibilityHidden(true)
        .onGeometryChange(for: Bool.self) { proxy in
            guard let viewport = proxy.bounds(of: .scrollView(axis: .vertical)) else { return false }
            return CGRect(origin: .zero, size: proxy.size).intersects(viewport)
        } action: { intersectsViewport = $0 }
        .onAppear { appeared = true }
        .onDisappear { appeared = false }
        .task(id: enabled) {
            // 같은 카드의 장소는 바뀌지 않으므로(.id로 버전을 구분) 다시 보일 때 받은 경로를 그대로 쓴다.
            guard enabled, path.isEmpty, stops.count > 1, let account = session.current else { return }
            routeFailed = false
            do {
                try await Task.sleep(for: .milliseconds(250))
                let route = try await loadRoute(stops.map { CourseCoordinate(lat: $0.lat, lng: $0.lng) })
                guard !Task.isCancelled, session.phase == .signedIn, session.current == account else { return }
                path = route.path
            } catch is CancellationError {
            } catch {
                if !Task.isCancelled, session.current == account { routeFailed = true }
            }
        }
    }
}

/// One line under a course card map: stops in visit order, destination emphasized and kept visible longest.
struct CourseCardStopNames: View {
    let names: [String]

    var body: some View {
        HStack(spacing: WegoTokens.Space.xSmall) {
            ForEach(names.indices, id: \.self) { index in
                if index > 0 {
                    Image(systemName: "arrow.right")
                        .font(WegoTokens.Typography.caption)
                        .foregroundStyle(WegoTokens.Palette.secondary)
                }
                let isDestination = index == names.count - 1
                Text(names[index])
                    .font(isDestination ? WegoTokens.Typography.caption.weight(.bold) : WegoTokens.Typography.caption)
                    .foregroundStyle(isDestination ? WegoTokens.Palette.text : WegoTokens.Palette.secondary)
                    .lineLimit(1)
                    .truncationMode(.tail)
                    .layoutPriority(isDestination ? 1 : 0)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(Self.accessibilityLabel(names))
    }

    static func accessibilityLabel(_ names: [String]) -> String {
        guard let destination = names.last else { return "" }
        guard names.count > 1 else { return "장소 \(destination)" }
        return "경로 " + names.dropLast().joined(separator: ", ") + ", 목적지 \(destination)"
    }
}
