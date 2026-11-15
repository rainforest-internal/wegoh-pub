import SwiftUI

struct CourseHomeSectionPicker: View {
    @Binding var selection: CourseHomeSection
    var unreadCount = 0
    var accessibilityPrefix = "coursesSection"
    var body: some View {
        HStack(spacing: WegoTokens.Space.xSmall) {
            ForEach(CourseHomeSection.allCases) { section in
                Button { selection = section } label: {
                    HStack(spacing: WegoTokens.Space.xSmall) {
                        Text(section.rawValue).font(WegoTokens.Typography.action)
                            .multilineTextAlignment(.center)
                            .fixedSize(horizontal: false, vertical: true)
                        if section == .subscriptions && unreadCount > 0 {
                            Circle().fill(WegoTokens.Palette.accent)
                                .frame(width: WegoTokens.Metrics.settingsStatusDotSize, height: WegoTokens.Metrics.settingsStatusDotSize)
                                .accessibilityHidden(true)
                        }
                    }
                    .frame(maxWidth: .infinity, minHeight: WegoTokens.Metrics.touchTarget)
                    .padding(.horizontal, WegoTokens.Space.xSmall)
                    .foregroundStyle(selection == section ? WegoTokens.Palette.text : WegoTokens.Palette.secondary)
                    .background(selection == section ? WegoTokens.Palette.background : .clear,
                                in: RoundedRectangle(cornerRadius: WegoTokens.Radius.field))
                }
                .buttonStyle(.plain).accessibilityAddTraits(selection == section ? .isSelected : [])
                .accessibilityIdentifier("\(accessibilityPrefix)-\(section.accessibilityID)")
                .accessibilityValue(section == .subscriptions && unreadCount > 0 ? "읽지 않은 소식 \(unreadCount)개" : "")
            }
        }
        .padding(WegoTokens.Space.xSmall)
        .background(WegoTokens.Palette.surface, in: RoundedRectangle(cornerRadius: WegoTokens.Radius.control))
    }
}

enum CourseDiscoveryRoute: Hashable { case course(String), creator(String), tag(String) }

struct CourseDiscoveryPreviewView: View {
    let onOwned: () -> Void
    let store: CourseDiscoveryPreviewStore
    @State private var section: CourseHomeSection
    @State private var query = ""
    @State private var selectedTags: Set<String> = []
    @State private var showsCreateExplanation = false

    init(initialSection: CourseHomeSection, store: CourseDiscoveryPreviewStore, onOwned: @escaping () -> Void) {
        _section = State(initialValue: initialSection == .owned ? .recommended : initialSection)
        self.store = store
        self.onOwned = onOwned
    }
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: WegoTokens.Space.medium) {
                HStack {
                    Text("경로").font(WegoTokens.Typography.hero)
                    Spacer()
                    Button { showsCreateExplanation = true } label: {
                        Label("경로 만들기", systemImage: "plus").font(WegoTokens.Typography.label.weight(.semibold))
                            .padding(WegoTokens.Space.compact).foregroundStyle(WegoTokens.Palette.onAccent)
                            .background(WegoTokens.Palette.accent, in: Capsule())
                    }.buttonStyle(.plain)
                }
                CourseHomeSectionPicker(selection: $section, unreadCount: store.unreadCount, accessibilityPrefix: "coursesPreviewSection")
                CourseDiscoverySampleNote()
                if section == .subscriptions { subscriptions }
                else { recommendations }
            }.padding(WegoTokens.Space.screen)
        }
        .accessibilityIdentifier("courseDiscoveryPreviewContent")
        .background(WegoTokens.Palette.background).foregroundStyle(WegoTokens.Palette.text)
        .navigationTitle("디자인 미리보기").navigationBarTitleDisplayMode(.inline)
        .toolbar(.visible, for: .navigationBar)
        .onChange(of: section) { _, value in if value == .owned { onOwned() } }
        .alert("내 경로에서 만들 수 있어요", isPresented: $showsCreateExplanation) {
            Button("내 경로로 이동") { onOwned() }
            Button("계속 미리보기", role: .cancel) { }
        } message: { Text("미리보기에서는 실제 경로를 저장하지 않아요.") }
    }

    private var recommendations: some View {
        VStack(alignment: .leading, spacing: WegoTokens.Space.medium) {
            HStack {
                Image(systemName: "magnifyingglass").foregroundStyle(WegoTokens.Palette.secondary)
                TextField("태그나 경로 이름으로 찾기", text: $query)
                    .font(WegoTokens.Typography.body).autocorrectionDisabled()
                    .accessibilityIdentifier("courseDiscoverySearch")
            }.padding(WegoTokens.Space.compact)
                .background(WegoTokens.Palette.surface, in: RoundedRectangle(cornerRadius: WegoTokens.Radius.field))
            Text("인기 태그").font(WegoTokens.Typography.section)
            ScrollView(.horizontal) {
                HStack(spacing: WegoTokens.Space.small) {
                    CourseDiscoveryFilterChip(title: "전체", selected: selectedTags.isEmpty, accessibilityID: "courseFilter-all") {
                        selectedTags.removeAll()
                        query = ""
                    }
                    ForEach(CourseDiscoveryPreviewStore.popularTags, id: \.self) { tag in
                        CourseDiscoveryFilterChip(title: "#" + tag, selected: selectedTags.contains(tag), accessibilityID: "courseFilter-\(tag)") {
                            toggleFilter(tag)
                        }
                    }
                }
            }.scrollIndicators(.hidden)
            Text(query.isEmpty && selectedTags.isEmpty ? "추천 경로" : "검색 결과").font(WegoTokens.Typography.section)
            let results = store.recommendations(query: query, selectedTags: selectedTags)
            if results.isEmpty { Text("조건에 맞는 샘플 경로가 없어요.").font(WegoTokens.Typography.body).accessibilityIdentifier("courseDiscoverySearchEmpty") }
            ForEach(results) { course in
                CourseDiscoveryCard(course: course, store: store, selectedTags: selectedTags, onTag: toggleFilter)
            }
        }
    }

    private func toggleFilter(_ tag: String) {
        if selectedTags.contains(tag) { selectedTags.remove(tag) } else { selectedTags.insert(tag) }
    }

    private var subscriptions: some View {
        VStack(alignment: .leading, spacing: WegoTokens.Space.medium) {
            if !store.followedTags.isEmpty {
                Text("구독한 태그").font(WegoTokens.Typography.section)
                ScrollView(.horizontal) {
                    HStack(spacing: WegoTokens.Space.small) {
                        ForEach(store.followedTags.sorted(), id: \.self) { tag in
                            Button { store.toggleTag(tag) } label: {
                                Label("#" + tag, systemImage: "xmark").font(WegoTokens.Typography.caption)
                                    .padding(WegoTokens.Space.small).background(WegoTokens.Palette.accentSoft, in: Capsule())
                                    .frame(minHeight: WegoTokens.Metrics.touchTarget)
                            }.buttonStyle(.plain).accessibilityLabel("#\(tag) 태그 구독 해제")
                                .accessibilityIdentifier("courseFollowingTag-\(tag)")
                        }
                    }
                }.scrollIndicators(.hidden)
            }
            Text("구독한 창작자 \(store.following.count)").font(WegoTokens.Typography.section)
                .accessibilityIdentifier("courseFollowingCount")
            ScrollView(.horizontal) {
                HStack(spacing: WegoTokens.Space.large) {
                    ForEach(store.following) { creator in
                        NavigationLink(value: CourseDiscoveryRoute.creator(creator.id)) {
                            VStack(spacing: WegoTokens.Space.small) {
                                CourseCreatorAvatar(name: creator.name)
                                Text(creator.name).font(WegoTokens.Typography.caption)
                            }
                        }.buttonStyle(.plain).accessibilityIdentifier("courseFollowing-\(creator.id)")
                    }
                }
            }.scrollIndicators(.hidden)
            HStack {
                Text("구독 소식").font(WegoTokens.Typography.section)
                Spacer()
                Text("읽지 않은 소식 \(store.unreadCount)").font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
                    .accessibilityIdentifier("courseNewsUnreadCount")
            }
            if store.visibleNews.isEmpty { Text("구독한 창작자의 샘플 소식이 없어요.").font(WegoTokens.Typography.body) }
            ForEach(store.visibleNews) { news in
                if let course = store.course(news.courseID), let creator = store.creator(course.creatorID) {
                    NavigationLink(value: CourseDiscoveryRoute.course(course.id)) {
                        VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
                            HStack {
                                Text("\(creator.name) · \(news.age)").font(WegoTokens.Typography.caption)
                                Spacer()
                                if !store.readNews.contains(news.id) { Text("새 소식").font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.accent) }
                            }
                            Text(course.title).font(WegoTokens.Typography.section)
                            Text(course.tags.map { "#" + $0 }.joined(separator: " ")).font(WegoTokens.Typography.caption)
                                .foregroundStyle(WegoTokens.Palette.secondary)
                        }.courseDiscoveryPanel()
                    }.buttonStyle(.plain).accessibilityIdentifier("courseNews-\(news.id)")
                }
            }
            Text("저장한 경로 \(store.saved.count)").font(WegoTokens.Typography.section).accessibilityIdentifier("courseSavedCount")
            ForEach(store.saved) { course in
                NavigationLink(value: CourseDiscoveryRoute.course(course.id)) {
                    HStack(spacing: WegoTokens.Space.compact) {
                        Image(systemName: "star.fill").foregroundStyle(WegoTokens.Palette.accent)
                        VStack(alignment: .leading, spacing: WegoTokens.Space.xSmall) {
                            Text(course.title).font(WegoTokens.Typography.section)
                            Text([store.creator(course.creatorID)?.name, course.stopCount.map { "장소 \($0)곳" }].compactMap { $0 }.joined(separator: " · "))
                                .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
                        }
                        Spacer()
                        Image(systemName: "chevron.right")
                    }.courseDiscoveryPanel()
                }.buttonStyle(.plain).accessibilityIdentifier("courseSaved-\(course.id)")
            }
        }
    }
}

struct CourseDiscoveryPreviewDestination: View {
    let route: CourseDiscoveryRoute
    let store: CourseDiscoveryPreviewStore
    var body: some View {
        switch route {
        case .course(let id):
            if let course = store.course(id) { CoursePublicPreviewView(course: course, store: store).onAppear { store.markRead(id) } }
        case .creator(let id):
            if let creator = store.creator(id) { CourseCreatorPreviewView(creator: creator, store: store) }
        case .tag(let name): CourseTagPreviewView(tag: name, store: store)
        }
    }
}

struct CourseDiscoverySampleNote: View {
    var body: some View {
        Text("디자인 미리보기 · 구독·저장은 이 화면의 샘플에서만 바뀌어요.")
            .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
    }
}

struct CourseDiscoveryFilterChip: View {
    let title: String
    let selected: Bool
    let accessibilityID: String
    var softWhenUnselected = false
    let action: () -> Void
    var body: some View {
        Button(action: action) {
            Text(title).font(WegoTokens.Typography.caption.weight(.semibold))
                .padding(WegoTokens.Space.small)
                .foregroundStyle(selected ? WegoTokens.Palette.onInk : softWhenUnselected ? WegoTokens.Palette.accent : WegoTokens.Palette.text)
                .background(selected ? WegoTokens.Palette.ink : softWhenUnselected ? WegoTokens.Palette.accentSoft : WegoTokens.Palette.background, in: Capsule())
                .overlay {
                    Capsule().strokeBorder(selected || softWhenUnselected ? .clear : WegoTokens.Palette.divider,
                                           lineWidth: WegoTokens.Metrics.hairlineWidth)
                }
                .frame(minHeight: WegoTokens.Metrics.touchTarget)
        }.buttonStyle(.plain).accessibilityAddTraits(selected ? .isSelected : [])
            .accessibilityIdentifier(accessibilityID)
    }
}

struct CourseDiscoveryTagLink: View {
    let tag: String
    var body: some View {
        NavigationLink(value: CourseDiscoveryRoute.tag(tag)) {
            Text("#" + tag).font(WegoTokens.Typography.caption.weight(.semibold))
                .padding(WegoTokens.Space.small).foregroundStyle(WegoTokens.Palette.accent)
                .background(WegoTokens.Palette.accentSoft, in: Capsule())
                .frame(minHeight: WegoTokens.Metrics.touchTarget)
        }.buttonStyle(.plain).accessibilityIdentifier("courseTag-\(tag)")
    }
}

struct CourseCreatorAvatar: View {
    let name: String
    var body: some View {
        AvatarBadge(name: name, tone: .ink).accessibilityHidden(true)
    }
}

struct CourseDiscoveryCard: View {
    let course: CourseDiscoveryCourse
    let store: CourseDiscoveryPreviewStore
    var selectedTags: Set<String> = []
    var onTag: ((String) -> Void)?
    var body: some View {
        VStack(alignment: .leading, spacing: WegoTokens.Space.compact) {
            NavigationLink(value: CourseDiscoveryRoute.course(course.id)) {
                VStack(alignment: .leading, spacing: WegoTokens.Space.compact) {
                    Text(course.title).font(WegoTokens.Typography.cardTitle)
                    Text([course.stopCount.map { "장소 \($0)곳" }, course.stops.isEmpty ? nil : course.stops.joined(separator: " → ")].compactMap { $0 }.joined(separator: " · "))
                        .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
                }
            }.buttonStyle(.plain).accessibilityIdentifier("courseDiscovery-\(course.id)")
            ScrollView(.horizontal) {
                HStack(spacing: WegoTokens.Space.small) {
                    ForEach(course.tags, id: \.self) { tag in
                        if let onTag {
                            CourseDiscoveryFilterChip(title: "#" + tag, selected: selectedTags.contains(tag), accessibilityID: "courseFilter-\(course.id)-\(tag)", softWhenUnselected: true) { onTag(tag) }
                        } else { CourseDiscoveryTagLink(tag: tag) }
                    }
                }
            }.scrollIndicators(.hidden)
            HStack {
                if let creator = store.creator(course.creatorID) {
                    NavigationLink(value: CourseDiscoveryRoute.creator(creator.id)) {
                        HStack(spacing: WegoTokens.Space.small) { CourseCreatorAvatar(name: creator.name); Text(creator.name).font(WegoTokens.Typography.label) }
                    }.buttonStyle(.plain).accessibilityIdentifier("courseCreator-\(creator.id)-\(course.id)")
                    Button(store.followedCreators.contains(creator.id) ? "구독 중" : "구독") { store.toggleFollow(creator.id) }
                        .font(WegoTokens.Typography.caption.weight(.semibold)).foregroundStyle(WegoTokens.Palette.accent)
                        .frame(minHeight: WegoTokens.Metrics.touchTarget)
                        .accessibilityIdentifier("courseFollow-\(creator.id)-\(course.id)")
                }
                Spacer(minLength: 0)
                CourseDiscoveryStarButton(course: course, store: store)
            }
        }.courseDiscoveryPanel()
    }
}

struct CourseDiscoveryStarButton: View {
    let course: CourseDiscoveryCourse
    let store: CourseDiscoveryPreviewStore
    var body: some View {
        Button { store.toggleStar(course.id) } label: {
            Label(store.starCount(course).map(String.init) ?? (store.starredCourses.contains(course.id) ? "저장됨" : "저장"),
                  systemImage: store.starredCourses.contains(course.id) ? "star.fill" : "star")
                .font(WegoTokens.Typography.label.weight(.semibold)).foregroundStyle(WegoTokens.Palette.accent)
                .frame(minHeight: WegoTokens.Metrics.touchTarget)
        }.buttonStyle(.plain).accessibilityLabel("\(course.title) \(store.starredCourses.contains(course.id) ? "저장 취소" : "저장")")
            .accessibilityValue(store.starredCourses.contains(course.id) ? "저장됨" : "저장 안 됨")
            .accessibilityIdentifier("courseStar-\(course.id)")
    }
}

extension View {
    func courseDiscoveryPanel() -> some View {
        WegoCard(.outlined) { self }
    }
}
