import SwiftUI

struct CourseRoutePreview: View {
    @Environment(SessionManager.self) private var session
    let stops: [CourseStop]
    let account: AccountSession
    let api: any IPhoneCourseServing
    var mapHeight = WegoTokens.Metrics.courseMapHeight
    var loadRoute: (([CourseCoordinate]) async throws -> CourseRoute)?
    @State private var route: CourseRoute?
    @State private var loading = false
    @State private var failed = false
    @State private var read = UUID()
    @State private var routePoints: [CourseCoordinate] = []
    private var currentRoute: CourseRoute? { routePoints == points ? route : nil }
    private var points: [CourseCoordinate] { stops.map { CourseCoordinate(lat: $0.latitude, lng: $0.longitude) } }

    var body: some View {
        VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
            CourseMapPreview(stops: stops, path: currentRoute?.path ?? [])
                .frame(height: mapHeight)
            if stops.count > 1 {
                Group {
                    if loading || (currentRoute == nil && !failed) {
                        WegoLoadingView("도로 경로를 불러오는 중", layout: .row) { Task { await load() } }
                    }
                    if failed {
                        VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
                            Text("도로 경로를 불러오지 못했어요.")
                            Button("경로 다시 시도") { Task { await load() } }
                                .frame(minHeight: WegoTokens.Metrics.touchTarget)
                        }
                        .accessibilityIdentifier("courseRouteError")
                    }
                    if let route = currentRoute {
                        Text("자동차 경로 \(route.distanceMeters / 1000, specifier: "%.1f")km · 약 \(Int(ceil(route.durationSeconds / 60)))분")
                            .accessibilityIdentifier("courseRouteLoaded")
                    }
                }
                .font(WegoTokens.Typography.caption)
                .foregroundStyle(WegoTokens.Palette.secondary)
                .padding(.horizontal, WegoTokens.Space.medium)
                .padding(.bottom, WegoTokens.Space.small)
            }
        }
        .task(id: points) { await load() }
    }

    private func load() async {
        let stamp = UUID()
        read = stamp
        if routePoints != points { route = nil }
        routePoints = points
        failed = false
        loading = points.count > 1
        defer { if read == stamp { loading = false } }
        guard points.count > 1 else { return }
        let requested = points
        do {
            try await Task.sleep(for: .milliseconds(350))
            let value: CourseRoute
            if let loadRoute { value = try await loadRoute(requested) }
            else { value = try await session.withToken(for: account) { try await api.route(requested, token: $0) } }
            guard read == stamp, !Task.isCancelled else { return }
            route = value
        } catch is CancellationError { }
        catch { if read == stamp, session.current == account { failed = true } }
    }
}
