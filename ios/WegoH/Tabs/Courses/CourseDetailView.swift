import SwiftUI

struct CourseDetailView: View {
    @Environment(SessionManager.self) private var session
    let account: AccountSession
    let api: any IPhoneCourseServing
    let onSaved: (CourseSaveReceipt) -> Void
    let loadRoute: (CourseSummary, [CourseCoordinate]) async throws -> CourseRoute
    @State private var currentSummary: CourseSummary
    @State private var detail: CourseDetail?
    @State private var readStamp: UUID?
    @State private var error: String?
    @State private var draft: CourseDraft?

    init(summary: CourseSummary, account: AccountSession, api: any IPhoneCourseServing,
         onSaved: @escaping (CourseSaveReceipt) -> Void,
         loadRoute: @escaping (CourseSummary, [CourseCoordinate]) async throws -> CourseRoute) {
        _currentSummary = State(initialValue: summary)
        self.account = account
        self.api = api
        self.onSaved = onSaved
        self.loadRoute = loadRoute
    }

    private var canRead: Bool { session.current == account && session.phase == .signedIn }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: WegoTokens.Space.screen) {
                if !canRead {
                    Text("다시 로그인한 뒤 경로를 열어 주세요.")
                        .font(WegoTokens.Typography.body).foregroundStyle(WegoTokens.Palette.secondary)
                } else if let detail {
                    VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
                        StatusPill(currentSummary.stateLabel, tone: currentSummary.state == "approved" ? .soft : .neutral)
                        Text(detail.pack.title).font(WegoTokens.Typography.title)
                            .accessibilityAddTraits(.isHeader)
                            .accessibilityIdentifier("courseDetailTitle")
                        Text("\(detail.pack.author) · v\(detail.pack.version) · 장소 \(detail.pack.stops.count)곳")
                            .font(WegoTokens.Typography.label).foregroundStyle(WegoTokens.Palette.secondary)
                        Text(detail.pack.description).font(WegoTokens.Typography.body)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    WegoCard(.outlined, padding: 0) {
                        CourseRoutePreview(stops: detail.pack.stops, account: account, api: api,
                                           mapHeight: WegoTokens.Metrics.courseDetailMapHeight,
                                           loadRoute: { try await loadRoute(currentSummary, $0) })
                    }.clipShape(RoundedRectangle(cornerRadius: WegoTokens.Radius.card))
                    VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
                        Text("장소와 도착 메시지").font(WegoTokens.Typography.label.weight(.semibold))
                            .foregroundStyle(WegoTokens.Palette.secondary)
                            .accessibilityAddTraits(.isHeader)
                        RouteList(stops: detail.pack.stops.map {
                            RouteStop(id: $0.id, title: $0.name,
                                      subtitle: [$0.address, $0.action.message].compactMap { $0 }.filter { !$0.isEmpty }.joined(separator: "\n"))
                        }, numbered: true)
                    }
                } else if let error {
                    WegoLoadingFailureView(message: error, messageIdentifier: "courseDetailError") { Task { await load() } }
                } else {
                    Text(currentSummary.title).font(WegoTokens.Typography.title)
                        .accessibilityAddTraits(.isHeader)
                    WegoLoadingView("경로를 불러오는 중", layout: .detail) { Task { await load() } }
                }
            }
            .padding(.horizontal, WegoTokens.Space.screen)
            .padding(.vertical, WegoTokens.Space.small)
        }
        .scrollBounceBehavior(.basedOnSize)
        .background(WegoTokens.Palette.background)
        .foregroundStyle(WegoTokens.Palette.text)
        .navigationTitle("")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar(.visible, for: .navigationBar)
        .task { if detail == nil { await load() } }
        .toolbar {
            if canRead, let detail, detail.pack.version < 2_147_483_647 {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("수정") { draft = CourseDraft(detail: detail) }
                        .accessibilityIdentifier("courseEdit")
                        .disabled(session.phase != .signedIn)
                }
            }
        }
        .sheet(item: $draft) { draft in
            NavigationStack {
                CourseEditorView(draft: draft, account: account, api: api) { receipt in
                    readStamp = nil
                    detail = nil
                    error = nil
                    currentSummary = CourseSummary(id: receipt.id, version: receipt.version,
                                                   title: receipt.pack.title, author: receipt.pack.author,
                                                   description: receipt.pack.description,
                                                   stopCount: receipt.pack.stops.count,
                                                   stopNames: receipt.pack.stops.map(\.name),
                                                   checksum: receipt.checksum, state: receipt.state,
                                                   stops: receipt.pack.stops.map(CourseCardStop.init))
                    onSaved(receipt)
                    Task { await load() }
                }
            }
        }
        .onChange(of: session.current) { _, _ in invalidateIfNeeded() }
        .onChange(of: session.phase) { _, _ in invalidateIfNeeded() }
    }

    private func invalidateIfNeeded() {
        guard !canRead else { return }
        readStamp = nil
        detail = nil
        draft = nil
        error = nil
    }

    private func load() async {
        guard canRead else { invalidateIfNeeded(); return }
        let stamp = UUID()
        let requested = currentSummary
        readStamp = stamp
        detail = nil
        error = nil
        do {
            let value = try await session.withToken(for: account) { try await api.detail(requested, token: $0) }
            guard readStamp == stamp, currentSummary == requested, canRead else { return }
            detail = value
        } catch is CancellationError { }
        catch {
            guard readStamp == stamp, currentSummary == requested, canRead else { return }
            self.error = courseErrorMessage(error)
        }
    }

}

struct CourseStopBadge: View {
    let number: Int
    var isDestination = false

    var body: some View {
        Text("\(number)").font(WegoTokens.Typography.label.weight(.semibold).monospacedDigit())
            .foregroundStyle(isDestination ? WegoTokens.Palette.onInk : WegoTokens.Palette.onAccent)
            .frame(width: WegoTokens.Metrics.courseStopBadgeSize, height: WegoTokens.Metrics.courseStopBadgeSize)
            .background(isDestination ? WegoTokens.Palette.ink : WegoTokens.Palette.accent,
                        in: RoundedRectangle(cornerRadius: isDestination ? WegoTokens.Space.small : WegoTokens.Metrics.courseStopBadgeSize / 2))
            .accessibilityLabel("\(number)번째 장소")
    }
}
