import SwiftUI

struct CoursesHomeView: View {
    @Environment(SessionManager.self) private var session
    @State private var showsLogin = false
    @State private var selectedSection = CourseHomeSection.recommended
    @State private var showsPreview = false
    @State private var discoveryStore = CourseDiscoveryPreviewStore()
    private var api: IPhoneCourseAPI {
        #if DEBUG
        if let api = CourseUIFixture.apiIfRequested() { return api }
        if let configuration = CourseDiscoveryUIFixture.configuration { return IPhoneCourseAPI(configuration: configuration) }
        #endif
        return IPhoneCourseAPI()
    }
    var body: some View {
        Group {
            if let account = session.current {
                AccountCoursesView(account: account, session: session, api: api, selectedSection: $selectedSection) {
                    discoveryStore = CourseDiscoveryPreviewStore()
                    showsPreview = true
                }
                .id(CourseSessionIdentity(account: account))
            } else if session.phase == .checkingSession || session.phase == .signingOut {
                WegoLoadingView("계정을 확인하고 있어요.", layout: .list)
            } else {
                ScrollView {
                    VStack(alignment: .leading, spacing: WegoTokens.Space.medium) {
                        HStack {
                            Text("경로").font(WegoTokens.Typography.hero).accessibilityAddTraits(.isHeader)
                            Spacer()

                        }.frame(minHeight: WegoTokens.Metrics.settingsHeaderHeight)
                        CourseHomeSectionPicker(selection: $selectedSection)
                        if selectedSection == .owned {
                            ContentUnavailableView {
                                Label("내 경로를 만나보세요", systemImage: "map")
                            } description: {
                                Text("로그인하면 내 경로를 보고 새 경로를 만들 수 있어요.")
                            } actions: {
                                Button("로그인") { showsLogin = true }
                                    .buttonStyle(.wego(.primary)).accessibilityIdentifier("coursesLogin")
                            }
                        } else {
                            ContentUnavailableView {
                                Label(selectedSection == .recommended ? "나에게 맞는 경로를 만나보세요" : "구독한 경로 소식을 만나보세요",
                                      systemImage: selectedSection == .recommended ? "sparkles" : "person.crop.circle.badge.checkmark")
                            } description: {
                                Text("로그인하면 공개 경로를 둘러보고 창작자와 태그를 구독할 수 있어요.")
                            } actions: {
                                Button("로그인") { showsLogin = true }
                                    .buttonStyle(.wego(.primary)).accessibilityIdentifier("coursesLogin")
                            }
                            #if DEBUG
                            Button("디자인 미리보기") {
                                discoveryStore = CourseDiscoveryPreviewStore()
                                showsPreview = true
                            }
                            .font(WegoTokens.Typography.action)
                            .frame(minHeight: WegoTokens.Metrics.touchTarget)
                            .accessibilityIdentifier("coursesDiscoveryPreview")
                            #endif
                        }
                    }.padding(.horizontal, WegoTokens.Space.screen)
                }
            }
        }
        .background(WegoTokens.Palette.background)
        .foregroundStyle(WegoTokens.Palette.text)
        .navigationTitle("경로")
        .toolbar(.hidden, for: .navigationBar)
        .sheet(isPresented: $showsPreview) {
            NavigationStack {
                CourseDiscoveryPreviewView(initialSection: selectedSection, store: discoveryStore) {
                    showsPreview = false
                    selectedSection = .owned
                }
                .navigationDestination(for: CourseDiscoveryRoute.self) { route in
                    CourseDiscoveryPreviewDestination(route: route, store: discoveryStore).toolbar(.hidden, for: .tabBar)
                }
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) {
                        Button("닫기") { showsPreview = false }
                            .accessibilityIdentifier("courseDiscoveryPreviewClose")
                    }
                }
            }
        }
        .sheet(isPresented: $showsLogin) {
            LoginView(secondaryTitle: "취소") { showsLogin = false }
        }
    }
}

private struct CourseSessionIdentity: Hashable {
    let accountID: String
    let expiresAt: Date
    let scopes: Set<String>

    init(account: AccountSession) {
        accountID = account.accountID; expiresAt = account.expiresAt; scopes = account.scopes
    }
}

private struct AccountCoursesView: View {
    @Environment(SessionManager.self) private var session
    let account: AccountSession
    @Binding var selectedSection: CourseHomeSection
    let onPreview: () -> Void
    @State private var draft: CourseDraft?
    @State private var ownedStore: CoursesStore
    @State private var discoveryStore: CourseDiscoveryStore
    @State private var query = ""
    @State private var selectedTags: Set<String> = []
    @State private var sort = CourseDiscoverySort.stars

    init(account: AccountSession, session: SessionManager, api: IPhoneCourseAPI,
         selectedSection: Binding<CourseHomeSection>, onPreview: @escaping () -> Void) {
        self.account = account
        _selectedSection = selectedSection
        self.onPreview = onPreview
        _ownedStore = State(initialValue: CoursesStore(api: api))
        _discoveryStore = State(initialValue: CourseDiscoveryStore(session: session))
    }

    var body: some View {
        Group {
            if session.phase != .signedIn {
                WegoLoadingView("계정을 확인하고 있어요.", layout: .list)
            } else if selectedSection == .owned {
                OwnedCoursesView(account: account, selectedSection: $selectedSection, store: ownedStore)
            } else {
                CourseDiscoveryLiveView(account: account, store: discoveryStore, selectedSection: $selectedSection,
                                        query: $query, selectedTags: $selectedTags, sort: $sort,
                                        onCreate: { draft = CourseDraft(author: account.displayName) }, onPreview: onPreview)
            }
        }
        .sheet(item: $draft) { draft in
            if session.phase == .signedIn && session.current == account {
                NavigationStack {
                    CourseEditorView(draft: draft, account: account, api: ownedStore.api) { receipt in
                        ownedStore.apply(receipt)
                        selectedSection = .owned
                        Task { await ownedStore.load(session: session, account: account) }
                    }
                }
            } else { WegoLoadingView("계정을 확인하고 있어요.", layout: .detail) }
        }
    }
}

private struct OwnedCoursesView: View {
    @Environment(SessionManager.self) private var session
    let account: AccountSession
    @Binding var selectedSection: CourseHomeSection
    let store: CoursesStore
    @State private var draft: CourseDraft?

    init(account: AccountSession, selectedSection: Binding<CourseHomeSection>, store: CoursesStore) {
        self.account = account; _selectedSection = selectedSection; self.store = store
    }

    var body: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: WegoTokens.Space.medium) {
                HStack {
                    Text("경로").font(WegoTokens.Typography.hero).accessibilityAddTraits(.isHeader)
                    Spacer()

                }
                .frame(minHeight: WegoTokens.Metrics.settingsHeaderHeight)
                CourseHomeSectionPicker(selection: $selectedSection)
                if store.hasLoaded { ownedSummary }
                if !store.hasLoaded, let message = store.error {
                    WegoLoadingFailureView(message: message, messageIdentifier: "coursesError") { Task { await store.load(session: session, account: account) } }
                } else if let message = store.error {
                    VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
                        Text(message).font(WegoTokens.Typography.label)
                            .foregroundStyle(WegoTokens.Palette.danger)
                            .accessibilityIdentifier("coursesError")
                        Button("다시 시도") { Task { await store.load(session: session, account: account) } }
                            .frame(minHeight: WegoTokens.Metrics.touchTarget)
                    }
                }
                if !store.hasLoaded && store.error == nil {
                    WegoLoadingView("경로를 불러오는 중", layout: .list) { Task { await store.load(session: session, account: account) } }
                } else if store.isLoading {
                    WegoLoadingView("경로를 새로 불러오는 중", layout: .row)
                } else if showsEmptyList {
                    WegoEmptyListCard(systemImage: "point.topleft.down.to.point.bottomright.curvepath",
                                      title: "아직 만든 경로가 없어요",
                                      message: "가보고 싶은 장소를 첫 경로로 만들어 보세요.",
                                      actionTitle: "경로 만들기",
                                      actionIdentifier: "coursesCreate", contentIdentifier: "coursesEmpty", showsAction: false) {
                        draft = CourseDraft(author: account.displayName)
                    }
                        .disabled(session.phase != .signedIn)

                }
                ForEach(store.courses) { course in
                    NavigationLink(value: course) {
                      WegoCard(.outlined) {
                        VStack(alignment: .leading, spacing: WegoTokens.Space.compact) {
                            HStack(alignment: .firstTextBaseline, spacing: WegoTokens.Space.compact) {
                                Text(course.title).font(WegoTokens.Typography.section.weight(.bold))
                                    .frame(maxWidth: .infinity, alignment: .leading)
                                StatusPill(course.stateLabel, tone: course.state == "approved" ? .soft : .neutral)
                            }
                            CourseCardMap(stops: course.stops) { points in
                                try await store.previewRoute(for: course, points: points, session: session, account: account)
                            }
                            .id(CourseCardRevision(course))
                            CourseCardStopNames(names: course.stopNames)
                            Text(course.description).font(WegoTokens.Typography.label).lineLimit(2)
                                .foregroundStyle(WegoTokens.Palette.secondary)
                            Text("장소 \(course.stopCount)곳 · v\(course.version)")
                                .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
                        }
                        .contentShape(RoundedRectangle(cornerRadius: WegoTokens.Radius.card))
                      }
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("course-\(course.id)")
                    .disabled(session.phase != .signedIn)
                }
            }
            .padding(.horizontal, WegoTokens.Space.screen)
            .padding(.bottom, WegoTokens.Space.medium)
        }
        .scrollBounceBehavior(.always, axes: .vertical)
        .background(WegoTokens.Palette.background)
        .foregroundStyle(WegoTokens.Palette.text)
        .toolbar(.hidden, for: .navigationBar)
        .safeAreaInset(edge: .bottom) {
            WegoFloatingAction(title: "경로 만들기", identifier: "coursesCreate") { draft = CourseDraft(author: account.displayName) }
                .disabled(session.phase != .signedIn)
        }
        .refreshable { await store.load(session: session, account: account) }
        .task(id: session.phase) {
            if session.phase == .signedIn && !store.hasLoaded && store.error == nil {
                await store.load(session: session, account: account)
            }
        }
        .navigationDestination(for: CourseSummary.self) { course in
            CourseDetailView(summary: course, account: account, api: store.api, onSaved: store.apply) { revision, points in
                try await store.previewRoute(for: revision, points: points, session: session, account: account)
            }.toolbar(.hidden, for: .tabBar)
        }
        .sheet(item: $draft) { draft in
            NavigationStack {
                CourseEditorView(draft: draft, account: account, api: store.api, onSaved: store.apply)
            }
        }
    }

    private var showsEmptyList: Bool {
        store.hasLoaded && store.courses.isEmpty && store.error == nil
    }

    private var ownedSummary: some View {
      WegoCard(.ink, padding: WegoTokens.Space.screen) {
        HStack(spacing: WegoTokens.Space.medium) {
            VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
                Text("내가 만든 경로")
                    .font(WegoTokens.Typography.section.weight(.bold))
                    .foregroundStyle(WegoTokens.Palette.onInk)
                Text("장소를 고르고, 나만의 드라이브를 만들어요.")
                    .font(WegoTokens.Typography.label)
                    .foregroundStyle(WegoTokens.Palette.onInkSecondary)
            }
            Spacer(minLength: WegoTokens.Space.small)
            Text(store.hasLoaded ? "\(store.courses.count)" : "—")
                .font(WegoTokens.Typography.cardTitle.monospacedDigit())
                .foregroundStyle(WegoTokens.Palette.onInk)
                .frame(width: WegoTokens.Metrics.emptyCountBadgeSize, height: WegoTokens.Metrics.emptyCountBadgeSize)
                .overlay {
                    Circle().strokeBorder(WegoTokens.Palette.routeHighlight,
                                          style: StrokeStyle(lineWidth: WegoTokens.Metrics.hairlineWidth,
                                                             dash: [WegoTokens.Metrics.hairlineWidth, WegoTokens.Space.xSmall]))
                }
                .accessibilityLabel(store.hasLoaded ? "내 경로 \(store.courses.count)개" : "내 경로 불러오는 중")
        }
      }
    }
}
