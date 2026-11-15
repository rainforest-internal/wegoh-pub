import SwiftUI

enum CourseLiveRoute: Hashable {
    case course(CourseDiscoveryItem, eventID: String? = nil)
    case creator(CourseDiscoveryItem)
    case creatorID(String)
    case tag(String)
}

struct CourseDiscoveryLiveView: View {
    @Environment(SessionManager.self) private var session
    let account: AccountSession
    @Binding var selectedSection: CourseHomeSection
    let onCreate: () -> Void
    let onPreview: () -> Void
    let store: CourseDiscoveryStore
    @Binding private var query: String
    @Binding private var selectedTags: Set<String>
    @State private var actionError: String?
    @Binding private var sort: CourseDiscoverySort
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    init(account: AccountSession, store: CourseDiscoveryStore, selectedSection: Binding<CourseHomeSection>,
         query: Binding<String>, selectedTags: Binding<Set<String>>, sort: Binding<CourseDiscoverySort>,
         onCreate: @escaping () -> Void, onPreview: @escaping () -> Void) {
        self.account = account
        _selectedSection = selectedSection
        self.onCreate = onCreate
        self.onPreview = onPreview
        self.store = store
        _query = query; _selectedTags = selectedTags; _sort = sort
    }

    var body: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: WegoTokens.Space.medium) {
                HStack {
                    Text("경로").font(WegoTokens.Typography.hero).accessibilityAddTraits(.isHeader)
                    Spacer()

                }.frame(minHeight: WegoTokens.Metrics.settingsHeaderHeight)
                CourseHomeSectionPicker(selection: $selectedSection, unreadCount: store.library?.unreadCount ?? 0)
                if let message = actionError ?? store.errorMessage {
                    if store.library == nil {
                        WegoLoadingFailureView(message: message, messageIdentifier: "courseDiscoveryError", retry: reload)
                    } else {
                        CourseLiveError(message: message, retry: reload)
                    }
                }
                if store.library == nil && store.errorMessage == nil {
                    WegoLoadingView("경로를 불러오는 중", layout: .list, onRetry: reload)
                } else if store.loading {
                    WegoLoadingView("경로를 새로 불러오는 중", layout: .row)
                }
                if let library = store.library {
                    if selectedSection == .subscriptions { subscriptions(library) }
                    else { recommendations(library) }
                }
                #if DEBUG
                Button("디자인 미리보기", action: onPreview)
                    .font(WegoTokens.Typography.caption)
                    .frame(minHeight: WegoTokens.Metrics.touchTarget)
                    .accessibilityIdentifier("coursesDiscoveryPreview")
                #endif
            }.padding(.horizontal, WegoTokens.Space.screen).padding(.bottom, WegoTokens.Space.medium)
        }
        .scrollDismissesKeyboard(.interactively)
        .scrollBounceBehavior(.always, axes: .vertical)
        .background(WegoTokens.Palette.background).foregroundStyle(WegoTokens.Palette.text)
        .toolbar(.hidden, for: .navigationBar)
        .safeAreaInset(edge: .bottom) {
            WegoFloatingAction(title: "경로 만들기", identifier: "coursesCreate", action: onCreate)
                .disabled(session.phase != .signedIn)
        }
        .refreshable { await store.load(query: query, tags: selectedTags.sorted()) }
        .task(id: session.phase) {
            if session.phase == .signedIn && store.library == nil && store.errorMessage == nil {
                await store.load(query: query, tags: selectedTags.sorted())
            }
        }
        .navigationDestination(for: CourseLiveRoute.self) { route in
            switch route {
            case .course(let item, let eventID):
                CourseDiscoveryPublicView(item: item, eventID: eventID, account: account, store: store)
            case .creator(let item): CourseDiscoveryCreatorView(item: item, account: account, store: store)
            case .creatorID(let id): CourseDiscoveryCreatorView(creatorID: id, account: account, store: store)
            case .tag(let tag): CourseDiscoveryTagView(tag: tag, account: account, session: session)
            }
        }
    }

    private func recommendations(_ library: CourseDiscoveryLibrary) -> some View {
        LazyVStack(alignment: .leading, spacing: WegoTokens.Space.medium) {
            HStack(spacing: WegoTokens.Space.small) {
                Image(systemName: "magnifyingglass").foregroundStyle(WegoTokens.Palette.secondary)
                TextField("태그나 경로 이름으로 찾기", text: $query)
                    .font(WegoTokens.Typography.body).autocorrectionDisabled().submitLabel(.search)
                    .onSubmit(reload).accessibilityIdentifier("courseDiscoverySearch")
                Button("검색", action: reload).font(WegoTokens.Typography.action)
                    .frame(minHeight: WegoTokens.Metrics.touchTarget)
                    .accessibilityIdentifier("courseDiscoverySearchSubmit")
            }.padding(WegoTokens.Space.compact)
                .background(WegoTokens.Palette.surface, in: RoundedRectangle(cornerRadius: WegoTokens.Radius.field))
            Text("인기 태그").font(WegoTokens.Typography.section)
            ScrollView(.horizontal) {
                HStack(spacing: WegoTokens.Space.small) {
                    CourseDiscoveryFilterChip(title: "전체", selected: selectedTags.isEmpty, accessibilityID: "courseFilter-all") {
                        selectedTags.removeAll(); query = ""; reload()
                    }
                    ForEach(courseVisibleFilterTags(popular: library.popularTags, selected: selectedTags), id: \.self) { tag in
                        filterChip(tag)
                    }
                }
            }.scrollIndicators(.hidden)
            if !selectedTags.isEmpty {
                CourseTagOverview(library: library, selectedTags: selectedTags, store: store, onTag: toggleTag)
            }
            HStack {
                SectionHeader(query.isEmpty && selectedTags.isEmpty ? "추천 경로" : "검색 결과 \(library.recommended.count)개")
                Spacer()
                if !selectedTags.isEmpty {
                    Picker("정렬", selection: $sort) {
                        ForEach(CourseDiscoverySort.allCases) { Text($0.rawValue).tag($0) }
                    }.pickerStyle(.menu).font(WegoTokens.Typography.label)
                }
            }
            if library.recommended.isEmpty && !store.loading {
                Text("조건에 맞는 공개 경로가 없어요.").font(WegoTokens.Typography.body)
                    .foregroundStyle(WegoTokens.Palette.secondary).accessibilityIdentifier("courseDiscoverySearchEmpty")
            }
            ForEach(selectedTags.isEmpty ? library.recommended : sort.courses(library.recommended), id: \.key) { item in
                if selectedTags.isEmpty {
                    CourseLiveCard(item: item, store: store, selectedTags: selectedTags, onTag: toggleTag)
                } else {
                    CourseLiveCompactCard(item: item, store: store, showsFollow: true)
                }
            }
        }
    }

    private func subscriptions(_ library: CourseDiscoveryLibrary) -> some View {
        LazyVStack(alignment: .leading, spacing: WegoTokens.Space.medium) {
            Text("구독한 태그").font(WegoTokens.Typography.section)
            if library.followedTags.isEmpty {
                Text("추천에서 태그를 선택해 구독할 수 있어요.")
                    .font(WegoTokens.Typography.label).foregroundStyle(WegoTokens.Palette.secondary)
            }
            ForEach(library.followedTags, id: \.self) { tag in
                HStack {
                    Button("#" + tag) {
                        selectedTags = [tag]; selectedSection = .recommended; reload()
                    }.font(WegoTokens.Typography.action).frame(minHeight: WegoTokens.Metrics.touchTarget)
                    Spacer()
                    Button("구독 해제") { perform { try await store.setTagFollowed(tag: tag, followed: false) } }
                        .font(WegoTokens.Typography.label).frame(minHeight: WegoTokens.Metrics.touchTarget)
                        .disabled(store.busy).accessibilityIdentifier("courseFollowingTag-\(tag)")
                }.courseDiscoveryPanel()
            }
            Text("구독한 창작자 \(library.following.count)").font(WegoTokens.Typography.section)
                .accessibilityIdentifier("courseFollowingCount")
            ScrollView(.horizontal) {
                LazyHStack(alignment: .top, spacing: WegoTokens.Space.medium) {
                    ForEach(library.following) { creator in
                        CourseSubscribedCreatorTile(creator: creator, store: store,
                            hasNews: library.news.contains { !$0.read && $0.item.creatorId == creator.creatorId })
                    }
                }
            }.scrollIndicators(.hidden)
            HStack(alignment: .firstTextBaseline) {
                Text("구독 소식").font(WegoTokens.Typography.section)
                Spacer()
                Text("읽지 않은 소식 \(library.unreadCount)").font(WegoTokens.Typography.caption)
                    .foregroundStyle(WegoTokens.Palette.secondary).accessibilityIdentifier("courseNewsUnreadCount")
            }
            if library.news.isEmpty {
                WegoCard(.outlined) {
                    WegoStatusColumn(spacing: WegoTokens.Space.small) {
                        Image(systemName: "point.topleft.down.to.point.bottomright.curvepath")
                            .font(WegoTokens.Typography.section)
                            .foregroundStyle(WegoTokens.Palette.accent)
                            .frame(width: WegoTokens.Metrics.emptyRequestIconSize, height: WegoTokens.Metrics.emptyRequestIconSize)
                            .background(WegoTokens.Palette.accentSoft, in: RoundedRectangle(cornerRadius: WegoTokens.Radius.control))
                            .accessibilityHidden(true)
                        Text("새 구독 소식이 없어요")
                            .font(WegoTokens.Typography.section)
                            .accessibilityAddTraits(.isHeader)
                        Text("구독한 창작자의 새 경로가 여기에 표시돼요.")
                            .font(WegoTokens.Typography.label)
                            .foregroundStyle(WegoTokens.Palette.secondary)
                    }
                    .fixedSize(horizontal: false, vertical: true)
                }
            }
            ForEach(library.news) { news in
                CourseLiveCompactCard(item: news.item, store: store, eventID: news.eventId,
                                      isUnread: !news.read, publishedAt: news.approvedAt)
            }
            Text("저장한 경로 \(library.saved.count)").font(WegoTokens.Typography.section).accessibilityIdentifier("courseSavedCount")
            if library.saved.isEmpty {
                Text("아직 저장한 경로가 없어요. 공개 경로에서 별표를 눌러 저장하세요.")
                    .font(WegoTokens.Typography.label).foregroundStyle(WegoTokens.Palette.secondary)
            }
            LazyVGrid(columns: Array(repeating: GridItem(.flexible(), alignment: .top),
                                     count: dynamicTypeSize.isAccessibilitySize ? 1 : 2),
                      alignment: .leading, spacing: WegoTokens.Space.compact) {
                ForEach(library.saved, id: \.key) { item in CourseLiveSavedCard(item: item, store: store) }
            }
        }
    }

    private func filterChip(_ tag: String) -> some View {
        CourseDiscoveryFilterChip(title: "#" + tag, selected: selectedTags.contains(tag), accessibilityID: "courseFilter-\(tag)") { toggleTag(tag) }
    }
    private func toggleTag(_ tag: String) {
        if selectedTags.contains(tag) { selectedTags.remove(tag) } else { selectedTags.insert(tag) }
        reload()
    }
    private func reload() {
        actionError = nil
        Task { await store.load(query: query, tags: selectedTags.sorted()) }
    }
    private func perform(_ operation: @escaping () async throws -> Void) {
        actionError = nil
        Task { do { try await operation() } catch is CancellationError { } catch { actionError = courseErrorMessage(error) } }
    }
}

struct CourseLiveCard: View {
    let item: CourseDiscoveryItem
    let store: CourseDiscoveryStore
    var selectedTags: Set<String> = []
    let onTag: (String) -> Void

    var body: some View {
        WegoCard(.outlined, radius: WegoTokens.Radius.hero) {
          VStack(alignment: .leading, spacing: WegoTokens.Space.compact) {
            NavigationLink(value: CourseLiveRoute.course(item)) {
                VStack(alignment: .leading, spacing: WegoTokens.Space.compact) {
                    CourseDiscoveryCardMap(item: item, store: store)
                    CourseCardStopNames(names: item.stopNames)
                    Text(item.title).font(WegoTokens.Typography.cardTitle)
                    Text("장소 \(item.stopCount)곳 · v\(item.version)")
                        .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
                    if !item.description.isEmpty {
                        Text(item.description).font(WegoTokens.Typography.label).lineLimit(2)
                            .foregroundStyle(WegoTokens.Palette.secondary)
                    }
                }
                .contentShape(Rectangle())
            }.buttonStyle(.plain).accessibilityIdentifier("courseDiscovery-\(item.id)")
            ScrollView(.horizontal) {
                HStack(spacing: WegoTokens.Space.small) {
                    ForEach(item.tags, id: \.self) { tag in
                        CourseDiscoveryFilterChip(title: "#" + tag, selected: selectedTags.contains(tag), accessibilityID: "courseFilter-\(item.id)-\(tag)", softWhenUnselected: true) { onTag(tag) }
                    }
                }
            }.scrollIndicators(.hidden)
            HStack(alignment: .top, spacing: WegoTokens.Space.small) {
                ViewThatFits(in: .horizontal) {
                    HStack(spacing: WegoTokens.Space.small) {
                        creatorIdentity
                        CourseCreatorRankPill(rank: item.creatorRank)
                        CourseLiveFollowButton(item: item, store: store)
                    }.fixedSize(horizontal: true, vertical: false)
                    VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
                        creatorIdentity
                        ViewThatFits(in: .horizontal) {
                            HStack(spacing: WegoTokens.Space.small) {
                                CourseCreatorRankPill(rank: item.creatorRank)
                                CourseLiveFollowButton(item: item, store: store)
                            }.fixedSize(horizontal: true, vertical: false)
                            VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
                                CourseCreatorRankPill(rank: item.creatorRank)
                                CourseLiveFollowButton(item: item, store: store)
                            }
                        }
                    }
                }
                Spacer(minLength: 0)
                CourseLiveStarButton(item: item, store: store)
            }
          }
        }
    }

    @ViewBuilder
    private var creatorIdentity: some View {
        if item.creatorId != nil {
            NavigationLink(value: CourseLiveRoute.creator(item)) {
                HStack(spacing: WegoTokens.Space.small) {
                    AvatarBadge(name: item.author, tone: .ink, size: WegoTokens.Metrics.tripMemberAvatarSize)
                    Text(item.author).font(WegoTokens.Typography.label)
                        .fixedSize(horizontal: false, vertical: true)
                }.frame(minHeight: WegoTokens.Metrics.touchTarget)
            }.buttonStyle(.plain).accessibilityIdentifier("courseCreator-\(item.id)")
        } else { Text(item.author).font(WegoTokens.Typography.label) }
    }
}

struct CourseLiveStarButton: View {
    let item: CourseDiscoveryItem
    let store: CourseDiscoveryStore
    @State private var error: String?
    var body: some View {
        VStack(alignment: .leading, spacing: WegoTokens.Space.xSmall) {
            Button {
                error = nil
                Task {
                    do { try await store.setStarred(item, !item.starred) }
                    catch is CancellationError { } catch { self.error = courseErrorMessage(error) }
                }
            } label: {
                Label("\(item.starCount)", systemImage: item.starred ? "star.fill" : "star")
                    .font(WegoTokens.Typography.label.weight(.semibold)).foregroundStyle(WegoTokens.Palette.accent)
                    .frame(minHeight: WegoTokens.Metrics.touchTarget)
            }.buttonStyle(.plain).disabled(store.busy)
                .accessibilityLabel("\(item.title) \(item.starred ? "저장 취소" : "저장")")
                .accessibilityValue(item.starred ? "저장됨" : "저장 안 됨")
                .accessibilityIdentifier("courseStar-\(item.id)")
            if let error { Text(error).font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.danger) }
        }
    }
}

struct CourseLiveError: View {
    let message: String
    let retry: () -> Void
    var body: some View {
        VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
            Text(message).font(WegoTokens.Typography.label).foregroundStyle(WegoTokens.Palette.danger)
                .accessibilityIdentifier("courseDiscoveryError")
            Button("다시 시도", action: retry).font(WegoTokens.Typography.action)
                .frame(minHeight: WegoTokens.Metrics.touchTarget)
        }.courseDiscoveryPanel()
    }
}
