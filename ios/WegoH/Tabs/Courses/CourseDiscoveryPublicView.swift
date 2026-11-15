import SwiftUI

struct CourseDiscoveryPublicView: View {
    @Environment(SessionManager.self) private var session
    @Environment(\.dismiss) private var dismiss
    let item: CourseDiscoveryItem
    let eventID: String?
    let account: AccountSession
    let store: CourseDiscoveryStore
    @State private var draft: CourseDraft?
    @State private var showsTrips = false
    @State private var showsReport = false
    @State private var actionError: String?
    @State private var notice: String?
    @State private var isImporting = false
    @State private var hasRequestedDetail = false
    private var api: IPhoneCourseAPI {
        #if DEBUG
        return IPhoneCourseAPI(configuration: CourseDiscoveryUIFixture.configuration)
        #else
        return IPhoneCourseAPI()
        #endif
    }
    private var detail: CourseDiscoveryDetail? {
        guard session.current == account, session.phase == .signedIn,
              let value = store.detail, value.pack.id == item.id, value.pack.version == item.version else { return nil }
        return value
    }
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: WegoTokens.Space.large) {
                if store.detailLoading, detail != nil {
                    WegoLoadingView("경로를 새로 불러오는 중", layout: .row)
                }
                if let value = detail {
                    content(value)
                } else if !hasRequestedDetail || store.errorMessage == nil {
                    Text(item.title).font(WegoTokens.Typography.title).accessibilityAddTraits(.isHeader)
                    WegoLoadingView("경로를 불러오는 중", layout: .detail) { retryDetail() }
                }
                if hasRequestedDetail, let message = actionError ?? store.errorMessage {
                    if detail == nil { WegoLoadingFailureView(message: message, messageIdentifier: "courseDiscoveryError", retry: retryDetail) }
                    else { CourseLiveError(message: message, retry: retryDetail) }
                }
                if let notice {
                    Text(notice).font(WegoTokens.Typography.label).foregroundStyle(WegoTokens.Palette.accent)
                        .accessibilityIdentifier("coursePublicNotice")
                }
            }.padding(WegoTokens.Space.screen)
        }
        .background(WegoTokens.Palette.background).foregroundStyle(WegoTokens.Palette.text)
        .navigationTitle("공개 경로").navigationBarTitleDisplayMode(.inline).toolbar(.visible, for: .navigationBar).toolbar(.hidden, for: .tabBar)
        .task(id: item.key) {
            hasRequestedDetail = true
            await store.loadDetail(item)
            if let eventID, detail != nil { perform { try await store.markRead(eventID: eventID) } }
        }
        .toolbar {
            if detail != nil {
                ToolbarItem(placement: .topBarTrailing) {
                    Menu {
                        Button("관심 없는 경로", systemImage: "eye.slash") {
                            perform { try await store.notInterested(item); dismiss() }
                        }.accessibilityIdentifier("coursePublicNotInterested")
                        Button("신고", systemImage: "flag", role: .destructive) { showsReport = true }
                            .accessibilityIdentifier("coursePublicReport")
                    } label: { Image(systemName: "ellipsis").frame(minWidth: WegoTokens.Metrics.touchTarget, minHeight: WegoTokens.Metrics.touchTarget) }
                    .accessibilityLabel("공개 경로 더 보기").accessibilityIdentifier("coursePublicMenu")
                    .disabled(store.busy)
                }
            }
        }
        .confirmationDialog("경로 신고", isPresented: $showsReport, titleVisibility: .visible) {
            Button("유해한 내용") { report("harmful") }
            Button("개인정보 노출") { report("privacy") }
            Button("권리 침해") { report("rights") }
            Button("기타") { report("other") }
            Button("취소", role: .cancel) { }
        } message: { Text("신고 사유를 선택해 주세요.") }
        .sheet(item: $draft) { draft in
            NavigationStack {
                CourseEditorView(draft: draft, account: account, api: api) { _ in notice = "내 경로로 저장했어요." }
            }
        }
        .sheet(isPresented: $showsTrips) {
            NavigationStack {
                CourseDiscoveryTripPicker(item: item, store: store) { notice = "여행에 경로를 추가했어요." }
            }
        }
        .onChange(of: session.current?.accountID) { _, _ in draft = nil; showsTrips = false }
    }

    private func content(_ value: CourseDiscoveryDetail) -> some View {
        let current = value.item
        return VStack(alignment: .leading, spacing: WegoTokens.Space.large) {
            WegoCard(.outlined, padding: 0) {
                CourseRoutePreview(stops: value.pack.stops, account: account, api: api,
                                   mapHeight: WegoTokens.Metrics.courseDetailMapHeight,
                                   loadRoute: { try await store.previewRoute(for: item, points: $0) })
            }.clipShape(RoundedRectangle(cornerRadius: WegoTokens.Radius.card))
            Text(value.pack.title).font(WegoTokens.Typography.title).accessibilityAddTraits(.isHeader)
                .accessibilityIdentifier("coursePublicTitle")
            Text(value.pack.description).font(WegoTokens.Typography.body).fixedSize(horizontal: false, vertical: true)
            Text("장소 \(value.pack.stops.count)곳 · v\(value.pack.version)")
                .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
            CourseCreatorRankPill(rank: item.creatorRank)
            ScrollView(.horizontal) {
                HStack(spacing: WegoTokens.Space.small) {
                    ForEach(value.tags, id: \.self) { tag in
                        NavigationLink(value: CourseLiveRoute.tag(tag)) { StatusPill("#" + tag, tone: .soft) }
                            .buttonStyle(.plain).frame(minHeight: WegoTokens.Metrics.touchTarget)
                            .accessibilityLabel("\(tag) 태그 검색").accessibilityIdentifier("coursePublicTag-\(tag)")
                    }
                }
            }.scrollIndicators(.hidden)
            WegoCard(.surface) {
              HStack(spacing: WegoTokens.Space.compact) {
                if value.creatorId != nil {
                    NavigationLink(value: CourseLiveRoute.creator(current)) {
                        HStack { AvatarBadge(name: value.pack.author, tone: .ink); Text(value.pack.author).font(WegoTokens.Typography.section) }
                    }.buttonStyle(.plain).accessibilityIdentifier("coursePublicCreator")
                } else { Text(value.pack.author).font(WegoTokens.Typography.section) }
                Spacer()
                if value.canFollow {
                    Button(value.followId == nil ? "구독" : "구독 중 · 해제") {
                        perform {
                            if let id = value.followId { try await store.unfollowCreator(followID: id) }
                            else { try await store.followCreator(current) }
                        }
                    }.buttonStyle(.wego(.plain))
                        .disabled(store.busy).accessibilityIdentifier("coursePublicFollow")
                }
              }
            }
            SectionHeader("장소와 도착 메시지")
            RouteList(stops: value.pack.stops.map {
                RouteStop(id: $0.id, title: $0.name, subtitle: [$0.address, $0.action.message].compactMap { $0 }.filter { !$0.isEmpty }.joined(separator: "\n"))
            }, numbered: true)
            ActionButton(title: "여행에 경로 추가") { showsTrips = true }
                .disabled(store.busy).accessibilityIdentifier("coursePublicAddToTrip")
            HStack(alignment: .top, spacing: WegoTokens.Space.small) {
                WegoCard(.soft) { CourseLiveStarButton(item: current, store: store).frame(maxWidth: .infinity) }
                Button {
                    isImporting = true
                    perform {
                        defer { isImporting = false }
                        draft = try await store.copy(current)
                    }
                } label: {
                    WegoCard(.outlined) {
                        Group {
                            if isImporting { WegoButtonLoadingLabel("가져오는 중") }
                            else { Text("내 경로로 가져오기").font(WegoTokens.Typography.action) }
                        }.frame(maxWidth: .infinity, minHeight: WegoTokens.Metrics.touchTarget)
                    }
                }.buttonStyle(.plain).disabled(store.busy || isImporting).accessibilityIdentifier("coursePublicImport")
            }
            Text("가져온 경로는 내 이름으로 편집할 수 있어요. 장소와 태그를 확인하고 제공 동의 후 저장해 주세요.")
                .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
        }
    }
    private func retryDetail() {
        Task {
            if store.needsRefresh { await store.refresh() }
            await store.loadDetail(item)
        }
    }

    private func report(_ reason: String) {
        perform { try await store.report(item, reason: reason); notice = "신고를 접수했어요." }
    }
    private func perform(_ operation: @escaping () async throws -> Void) {
        actionError = nil
        Task { do { try await operation() } catch is CancellationError { } catch { actionError = courseErrorMessage(error) } }
    }
}

struct CourseDiscoveryCreatorView: View {
    @Environment(SessionManager.self) private var session
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    let item: CourseDiscoveryItem?
    let creatorID: String
    let account: AccountSession
    let store: CourseDiscoveryStore
    @State private var selectedTags: Set<String> = []
    @State private var actionError: String?
    @State private var hasRequestedCreator = false
    init(item: CourseDiscoveryItem, account: AccountSession, store: CourseDiscoveryStore) {
        self.item = item
        creatorID = item.creatorId ?? ""
        self.account = account
        self.store = store
    }
    init(creatorID: String, account: AccountSession, store: CourseDiscoveryStore) {
        item = nil
        self.creatorID = creatorID
        self.account = account
        self.store = store
    }
    private var creator: CourseDiscoveryPublicCreator? {
        guard session.current == account, session.phase == .signedIn,
              let value = store.creator, value.creator.id == creatorID else { return nil }
        return value
    }
    var body: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: WegoTokens.Space.large) {
                if store.creatorLoading, creator != nil {
                    WegoLoadingView("창작자를 새로 불러오는 중", layout: .row)
                }
                if let value = creator {
                    WegoCard(.ink) {
                      VStack(alignment: .leading, spacing: WegoTokens.Space.medium) {
                        let identityLayout = dynamicTypeSize.isAccessibilitySize
                            ? AnyLayout(VStackLayout(alignment: .leading, spacing: WegoTokens.Space.medium))
                            : AnyLayout(HStackLayout(alignment: .center, spacing: WegoTokens.Space.medium))
                        identityLayout {
                            AvatarBadge(name: value.creator.name, tone: .neutral, size: WegoTokens.Metrics.profileAvatarSize)
                            VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
                                Text(value.creator.name).font(WegoTokens.Typography.title).accessibilityIdentifier("courseCreatorName")
                                CourseCreatorRankPill(rank: value.courses.compactMap(\.creatorRank).min())
                                Text("공개 경로 \(value.creator.courseCount)개 · 구독자 \(value.creator.followerCount)명 · 별표 \(value.creator.starCount)개")
                                    .font(WegoTokens.Typography.label).foregroundStyle(WegoTokens.Palette.onInkSecondary)
                            }.fixedSize(horizontal: false, vertical: true)
                        }
                        if let rank = value.courses.compactMap(\.creatorRank).min(), (1...3).contains(rank) {
                            Text("드라이브 셀럽 · 공개 경로 별표 기준 \(rank)위")
                                .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.onInkSecondary)
                        }
                        let tags = CourseTagInsights(courses: value.courses, selectedTags: []).relatedTags
                        if !tags.isEmpty {
                            ScrollView(.horizontal) {
                                HStack(spacing: WegoTokens.Space.small) {
                                    ForEach(Array(tags.prefix(3))) { tag in
                                        Text("#\(tag.tag) \(tag.count)")
                                            .font(WegoTokens.Typography.caption.weight(.semibold))
                                            .padding(.horizontal, WegoTokens.Space.small)
                                            .padding(.vertical, WegoTokens.Space.xSmall)
                                            .foregroundStyle(WegoTokens.Palette.onInk)
                                            .overlay { Capsule().strokeBorder(WegoTokens.Palette.routeHighlight,
                                                                             lineWidth: WegoTokens.Metrics.hairlineWidth) }
                                    }
                                }
                            }.scrollIndicators(.hidden)
                        }
                        let representative = value.courses.first ?? item
                        if value.creator.following || representative?.canFollow == true {
                            Button(value.creator.following ? "구독 중 · 구독 해제" : "창작자 구독") {
                                actionError = nil
                                Task {
                                    do {
                                        if let id = value.creator.followId { try await store.unfollowCreator(followID: id) }
                                        else if let representative { try await store.followCreator(representative) }
                                    } catch is CancellationError { } catch { actionError = courseErrorMessage(error) }
                                }
                            }.buttonStyle(.plain).font(WegoTokens.Typography.action)
                                .frame(maxWidth: .infinity, minHeight: WegoTokens.Metrics.primaryButtonHeight)
                                .foregroundStyle(value.creator.following ? WegoTokens.Palette.onInk : WegoTokens.Palette.ink)
                                .background(value.creator.following ? .clear : WegoTokens.Palette.routeHighlight,
                                            in: RoundedRectangle(cornerRadius: WegoTokens.Radius.control))
                                .overlay { RoundedRectangle(cornerRadius: WegoTokens.Radius.control)
                                        .strokeBorder(value.creator.following ? WegoTokens.Palette.routeHighlight : .clear,
                                                      lineWidth: WegoTokens.Metrics.hairlineWidth) }
                                .disabled(store.busy).accessibilityIdentifier("courseCreatorFollow")
                        }
                        Text("구독하면 새 경로가 경로 탭의 구독에 표시돼요.")
                            .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.onInkSecondary)
                      }
                    }
                    ScrollView(.horizontal) {
                        HStack(spacing: WegoTokens.Space.small) {
                            CourseDiscoveryFilterChip(title: "전체", selected: selectedTags.isEmpty, accessibilityID: "courseCreatorFilter-all") { selectedTags.removeAll() }
                            ForEach(Array(Set(value.courses.flatMap(\.tags))).sorted(), id: \.self) { tag in
                                CourseDiscoveryFilterChip(title: "#" + tag, selected: selectedTags.contains(tag), accessibilityID: "courseCreatorFilter-\(tag)") { toggleTag(tag) }
                            }
                        }
                    }.scrollIndicators(.hidden)
                    let courses = value.courses.filter { selectedTags.isSubset(of: Set($0.tags)) }
                    if courses.isEmpty { Text("조건에 맞는 공개 경로가 없어요.").font(WegoTokens.Typography.body) }
                    ForEach(courses, id: \.key) { course in
                        CourseLiveCompactCard(item: course, store: store)
                    }
                } else if !hasRequestedCreator || store.errorMessage == nil {
                    WegoLoadingView("창작자를 불러오는 중", layout: .detail, onRetry: retryCreator)
                }
                if hasRequestedCreator, let message = actionError ?? store.errorMessage {
                    if creator == nil { WegoLoadingFailureView(message: message, messageIdentifier: "courseDiscoveryError", retry: retryCreator) }
                    else { CourseLiveError(message: message, retry: retryCreator) }
                }
            }.padding(WegoTokens.Space.screen)
        }
        .background(WegoTokens.Palette.background).foregroundStyle(WegoTokens.Palette.text)
        .navigationTitle("창작자").navigationBarTitleDisplayMode(.inline).toolbar(.visible, for: .navigationBar).toolbar(.hidden, for: .tabBar)
        .task(id: creatorID) {
            hasRequestedCreator = true
            await store.loadCreator(id: creatorID)
        }
    }
    private func retryCreator() {
        Task {
            if store.needsRefresh { await store.refresh() }
            await store.loadCreator(id: creatorID)
        }
    }

    private func toggleTag(_ tag: String) {
        if selectedTags.contains(tag) { selectedTags.remove(tag) } else { selectedTags.insert(tag) }
    }
}

private struct CourseDiscoveryTripPicker: View {
    @Environment(\.dismiss) private var dismiss
    let item: CourseDiscoveryItem
    let store: CourseDiscoveryStore
    let onAdded: () -> Void
    @State private var error: String?
    @State private var hasLoadedTrips = false
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: WegoTokens.Space.medium) {
                Text("경로를 추가할 여행을 골라 주세요.").font(WegoTokens.Typography.body)
                if (!hasLoadedTrips || store.tripsLoading) && store.trips.isEmpty && (!hasLoadedTrips || store.errorMessage == nil) {
                    WegoLoadingView("여행을 불러오는 중", layout: .list, onRetry: retryTrips)
                } else if store.tripsLoading {
                    WegoLoadingView("여행을 새로 불러오는 중", layout: .row)
                }
                if hasLoadedTrips, let message = error ?? store.errorMessage {
                    if store.trips.isEmpty { WegoLoadingFailureView(message: message, messageIdentifier: "courseDiscoveryError", retry: retryTrips) }
                    else { CourseLiveError(message: message, retry: retryTrips) }
                }
                if hasLoadedTrips && store.trips.isEmpty && !store.tripsLoading && store.errorMessage == nil {
                    Text("추가할 수 있는 여행이 없어요. 여행 탭에서 여행을 먼저 만들어 주세요.")
                        .font(WegoTokens.Typography.label).foregroundStyle(WegoTokens.Palette.secondary)
                }
                ForEach(store.trips) { trip in
                    Button {
                        error = nil
                        Task {
                            do { try await store.addToTrip(item, tripID: trip.id); onAdded(); dismiss() }
                            catch is CancellationError { } catch { self.error = courseErrorMessage(error) }
                        }
                    } label: {
                        HStack {
                            VStack(alignment: .leading, spacing: WegoTokens.Space.xSmall) {
                                Text(trip.title).font(WegoTokens.Typography.section)
                                Text(trip.state == .planned ? "준비 중" : "진행 중 · 여행 설정에 따라 추가가 제한될 수 있어요")
                                    .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
                            }
                            Spacer()
                            Image(systemName: "plus")
                        }.frame(minHeight: WegoTokens.Metrics.touchTarget).contentShape(Rectangle()).courseDiscoveryPanel()
                    }.buttonStyle(.plain).disabled(store.busy).accessibilityIdentifier("courseTripAdd-\(trip.id)")
                }
            }.padding(WegoTokens.Space.screen)
        }.background(WegoTokens.Palette.background).foregroundStyle(WegoTokens.Palette.text)
            .navigationTitle("여행에 경로 추가").navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("닫기") { dismiss() } } }
            .task { await loadTrips() }
    }

    private func retryTrips() { Task { await loadTrips() } }

    private func loadTrips() async {
        if store.needsRefresh { await store.refresh() }
        await store.loadTrips()
        hasLoadedTrips = true
    }
}
