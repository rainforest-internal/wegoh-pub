import SwiftUI

enum CourseDiscoverySort: String, CaseIterable, Identifiable {
    case stars = "별표 많은 순", title = "이름순"
    var id: Self { self }

    func courses(_ values: [CourseDiscoveryItem]) -> [CourseDiscoveryItem] {
        values.sorted { first, second in
            if self == .stars, first.starCount != second.starCount { return first.starCount > second.starCount }
            if first.title != second.title { return first.title < second.title }
            return first.key < second.key
        }
    }
}

struct CourseTagOverview: View {
    let library: CourseDiscoveryLibrary
    let selectedTags: Set<String>
    let store: CourseDiscoveryStore
    let onTag: (String) -> Void
    @State private var error: String?
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    private var insight: CourseTagInsights { .init(courses: library.recommended, selectedTags: selectedTags) }

    var body: some View {
        VStack(alignment: .leading, spacing: WegoTokens.Space.medium) {
            WegoCard(.ink) {
                VStack(alignment: .leading, spacing: WegoTokens.Space.medium) {
                    Text(selectedTags.sorted().map { "#" + $0 }.joined(separator: " · "))
                        .font(WegoTokens.Typography.title).accessibilityIdentifier("courseTagTitle")
                    Text("경로 \(insight.courses.count)개 · 이 태그를 올린 창작자 \(insight.creators.count)명")
                        .font(WegoTokens.Typography.label).foregroundStyle(WegoTokens.Palette.onInkSecondary)
                    Text("현재 검색 결과에서 집계했어요. 선택한 태그가 모두 포함된 경로를 보여드려요.")
                        .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.onInkSecondary)
                    ForEach(selectedTags.sorted(), id: \.self) { tag in
                        let followed = library.followedTags.contains { courseTagKey($0) == courseTagKey(tag) }
                        Button(followed ? "#\(tag) 태그 구독 해제" : "#\(tag) 태그 구독") {
                            error = nil
                            Task { do { try await store.setTagFollowed(tag: tag, followed: !followed) }
                                   catch is CancellationError { } catch { self.error = courseErrorMessage(error) } }
                        }
                        .buttonStyle(.plain).font(WegoTokens.Typography.action)
                        .frame(maxWidth: .infinity, minHeight: WegoTokens.Metrics.touchTarget)
                        .foregroundStyle(WegoTokens.Palette.onInk)
                        .overlay { RoundedRectangle(cornerRadius: WegoTokens.Radius.control)
                            .strokeBorder(WegoTokens.Palette.inkDivider, lineWidth: WegoTokens.Metrics.hairlineWidth) }
                        .disabled(store.busy).accessibilityIdentifier("courseTagFollow-\(tag)")
                    }
                }
            }
            if !insight.relatedTags.isEmpty {
                SectionHeader("함께 많이 쓰는 태그")
                ScrollView(.horizontal) {
                    HStack(spacing: WegoTokens.Space.small) {
                        ForEach(insight.relatedTags.prefix(8)) { value in
                            CourseDiscoveryFilterChip(title: "#" + value.tag, selected: false,
                                accessibilityID: "courseRelatedTag-\(value.tag)") { onTag(value.tag) }
                        }
                    }
                }.scrollIndicators(.hidden)
            }
            if !insight.creators.isEmpty {
                SectionHeader("자주 올리는 창작자")
                LazyVGrid(columns: Array(repeating: GridItem(.flexible(), alignment: .top),
                                         count: dynamicTypeSize.isAccessibilitySize ? 1 : 3),
                          alignment: .leading, spacing: WegoTokens.Space.small) {
                    ForEach(insight.creators.prefix(3)) { value in
                        NavigationLink(value: CourseLiveRoute.creator(value.item)) {
                            WegoCard(.outlined, padding: WegoTokens.Space.small) {
                                VStack(spacing: WegoTokens.Space.small) {
                                    AvatarBadge(name: value.item.author, tone: .ink)
                                    Text(value.item.author).font(WegoTokens.Typography.label)
                                    Text("검색 결과 \(value.count)개").font(WegoTokens.Typography.caption)
                                        .foregroundStyle(WegoTokens.Palette.secondary)
                                }.frame(maxWidth: .infinity)
                            }
                        }.buttonStyle(.plain).accessibilityIdentifier("courseTagCreator-\(value.id)")
                    }
                }
            }
            if let error { Text(error).font(WegoTokens.Typography.label).foregroundStyle(WegoTokens.Palette.danger) }
        }
    }
}

struct CourseDiscoveryTagView: View {
    let account: AccountSession
    @State private var store: CourseDiscoveryStore
    @State private var query = ""
    @State private var selectedTags: Set<String>
    @State private var sort = CourseDiscoverySort.stars

    init(tag: String, account: AccountSession, session: SessionManager) {
        self.account = account
        _selectedTags = State(initialValue: [tag])
        _store = State(initialValue: CourseDiscoveryStore(session: session))
    }

    var body: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: WegoTokens.Space.medium) {
                WegoField("태그나 경로 이름", text: $query, identifier: "courseTagSearch")
                    .submitLabel(.search).onSubmit(reload)
                if store.library == nil && store.errorMessage == nil {
                    WegoLoadingView("경로를 불러오는 중", layout: .list, onRetry: reload)
                } else if store.loading {
                    WegoLoadingView("경로를 새로 불러오는 중", layout: .row)
                }
                if let library = store.library {
                    if !selectedTags.isEmpty {
                        CourseTagOverview(library: library, selectedTags: selectedTags, store: store, onTag: toggleTag)
                    }
                    HStack {
                        SectionHeader("경로 \(library.recommended.count)개")
                        Spacer()
                        Picker("정렬", selection: $sort) {
                            ForEach(CourseDiscoverySort.allCases) { Text($0.rawValue).tag($0) }
                        }.pickerStyle(.menu)
                    }
                    if library.recommended.isEmpty && !store.loading {
                        Text("조건에 맞는 공개 경로가 없어요.").font(WegoTokens.Typography.body)
                    }
                    ForEach(sort.courses(library.recommended), id: \.key) { item in
                        CourseLiveCompactCard(item: item, store: store, showsFollow: true)
                    }
                }
                if let error = store.errorMessage {
                    if store.library == nil { WegoLoadingFailureView(message: error, messageIdentifier: "courseDiscoveryError", retry: reload) }
                    else { CourseLiveError(message: error, retry: reload) }
                }
            }.padding(WegoTokens.Space.screen)
        }
        .scrollDismissesKeyboard(.interactively)
        .foregroundStyle(WegoTokens.Palette.text).background(WegoTokens.Palette.background)
        .navigationTitle("태그 검색").navigationBarTitleDisplayMode(.inline).toolbar(.visible, for: .navigationBar).toolbar(.hidden, for: .tabBar)
        .task { await store.load(query: query, tags: selectedTags.sorted()) }
        .scrollBounceBehavior(.always, axes: .vertical)
        .refreshable { await store.load(query: query, tags: selectedTags.sorted()) }
    }

    private func toggleTag(_ tag: String) {
        if selectedTags.contains(tag) { selectedTags.remove(tag) } else { selectedTags.insert(tag) }
        reload()
    }
    private func reload() { Task { await store.load(query: query, tags: selectedTags.sorted()) } }
}
