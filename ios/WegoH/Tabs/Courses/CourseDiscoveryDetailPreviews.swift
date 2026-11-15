import SwiftUI

struct CoursePublicPreviewView: View {
    let course: CourseDiscoveryCourse
    let store: CourseDiscoveryPreviewStore
    @State private var actionExplanation: String?
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: WegoTokens.Space.large) {
                CourseDiscoverySampleNote()
                if course.id == "coffee-coast" {
                    Label("자동차 경로 · 21km · 약 38분 · 샘플", systemImage: "car.side")
                        .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
                }
                Text(course.title).font(WegoTokens.Typography.title).accessibilityIdentifier("coursePublicPreviewTitle")
                if !course.description.isEmpty { Text(course.description).font(WegoTokens.Typography.body) }
                ScrollView(.horizontal) { HStack { ForEach(course.tags, id: \.self) { CourseDiscoveryTagLink(tag: $0) } } }.scrollIndicators(.hidden)
                if let creator = store.creator(course.creatorID) {
                    HStack(spacing: WegoTokens.Space.compact) {
                        NavigationLink(value: CourseDiscoveryRoute.creator(creator.id)) {
                            HStack { CourseCreatorAvatar(name: creator.name); Text(creator.name).font(WegoTokens.Typography.section) }
                        }.buttonStyle(.plain).accessibilityIdentifier("coursePublicCreator")
                        Spacer()
                        Button(store.followedCreators.contains(creator.id) ? "구독 중" : "구독") { store.toggleFollow(creator.id) }
                            .font(WegoTokens.Typography.action).frame(minHeight: WegoTokens.Metrics.touchTarget)
                            .accessibilityIdentifier("coursePublicFollow")
                    }.courseDiscoveryPanel()
                }
                Text("장소").font(WegoTokens.Typography.section)
                if course.stops.isEmpty {
                    Text("이 샘플에는 세부 장소 정보가 포함돼 있지 않아요.")
                        .font(WegoTokens.Typography.body).foregroundStyle(WegoTokens.Palette.secondary)
                }
                ForEach(Array(course.stops.enumerated()), id: \.offset) { index, stop in
                    HStack(alignment: .top, spacing: WegoTokens.Space.medium) {
                        Text("\(index + 1)").font(WegoTokens.Typography.label.weight(.semibold))
                            .foregroundStyle(WegoTokens.Palette.accent)
                            .frame(width: WegoTokens.Metrics.courseStopBadgeSize, height: WegoTokens.Metrics.courseStopBadgeSize)
                            .background(WegoTokens.Palette.accentSoft, in: Circle())
                        VStack(alignment: .leading, spacing: WegoTokens.Space.xSmall) {
                            Text(stop).font(WegoTokens.Typography.section)
                            if let address = address(index) { Text(address).font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary) }
                        }
                    }.padding(.vertical, WegoTokens.Space.small)
                }
                ActionButton(title: "여행에 경로 추가") { actionExplanation = "여행에 경로 추가" }
                    .accessibilityIdentifier("coursePreviewAddToTrip")
                CourseDiscoveryStarButton(course: course, store: store)
                Button("내 경로로 가져오기") { actionExplanation = "내 경로로 가져오기" }
                    .font(WegoTokens.Typography.action).frame(maxWidth: .infinity, minHeight: WegoTokens.Metrics.touchTarget)
                    .accessibilityIdentifier("coursePreviewImport")
                Text("가져오면 내 경로로 복사돼 장소를 바꿔 쓸 수 있어요. 원래 경로는 그대로예요. 미리보기에서는 복사하지 않아요.")
                    .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
            }.padding(WegoTokens.Space.screen)
        }
        .background(WegoTokens.Palette.background).foregroundStyle(WegoTokens.Palette.text)
        .navigationTitle("경로 미리보기").navigationBarTitleDisplayMode(.inline).toolbar(.visible, for: .navigationBar)
        .alert("\(actionExplanation ?? "경로") 미리보기", isPresented: Binding(get: { actionExplanation != nil }, set: { if !$0 { actionExplanation = nil } })) {
            Button("확인") { actionExplanation = nil }
        } message: { Text("이 화면에서는 동작 안내만 확인해요. 실제 여행에 추가하거나 내 경로를 바꾸지 않아요.") }
    }
    private func address(_ index: Int) -> String? {
        guard course.id == "coffee-coast" else { return nil }
        let addresses = ["강원 강릉시 창해로14번길", "강원 강릉시 저동", "강원 강릉시 주문진읍"]
        return addresses.indices.contains(index) ? addresses[index] : nil
    }
}

struct CourseCreatorPreviewView: View {
    let creator: CourseDiscoveryCreator
    let store: CourseDiscoveryPreviewStore
    @State private var selectedTag: String?
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: WegoTokens.Space.large) {
                CourseDiscoverySampleNote()
                VStack(alignment: .leading, spacing: WegoTokens.Space.medium) {
                    CourseCreatorAvatar(name: creator.name)
                    Text(creator.name).font(WegoTokens.Typography.title).accessibilityIdentifier("courseCreatorPreviewName")
                    Text([creator.courseCount.map { "공개 경로 \($0)개" }, creator.subscriberCount.map { "구독자 \($0)명" }].compactMap { $0 }.joined(separator: " · "))
                        .font(WegoTokens.Typography.label)
                    Text("시안 통계 · 아래에서는 일부 샘플 경로만 보여요.").font(WegoTokens.Typography.caption)
                    HStack { ForEach(creator.tags, id: \.self) { Text("#" + $0).font(WegoTokens.Typography.caption) } }
                }
                Button(store.followedCreators.contains(creator.id) ? "구독 중 · 구독 해제" : "창작자 구독") { store.toggleFollow(creator.id) }
                    .font(WegoTokens.Typography.action).frame(maxWidth: .infinity, minHeight: WegoTokens.Metrics.primaryButtonHeight)
                    .foregroundStyle(WegoTokens.Palette.onAccent).background(WegoTokens.Palette.accent, in: RoundedRectangle(cornerRadius: WegoTokens.Radius.control))
                    .accessibilityIdentifier("courseCreatorFollow")
                Text("구독하면 새 경로를 공개할 때 경로 탭의 구독에 표시돼요.")
                    .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
                ScrollView(.horizontal) {
                    HStack {
                        Button("전체") { selectedTag = nil }.font(WegoTokens.Typography.label)
                            .padding(WegoTokens.Space.small).background(selectedTag == nil ? WegoTokens.Palette.accentSoft : WegoTokens.Palette.surface, in: Capsule())
                        ForEach(creator.tags, id: \.self) { tag in
                            Button("#" + tag) { selectedTag = tag }.font(WegoTokens.Typography.label)
                                .padding(WegoTokens.Space.small).background(selectedTag == tag ? WegoTokens.Palette.accentSoft : WegoTokens.Palette.surface, in: Capsule())
                        }
                    }
                }.scrollIndicators(.hidden)
                ForEach(store.courses(creator: creator.id, tag: selectedTag)) { course in
                    if let age = course.published { Text(age).font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary) }
                    CourseDiscoveryCard(course: course, store: store)
                }
            }.padding(WegoTokens.Space.screen)
        }
        .background(WegoTokens.Palette.background).foregroundStyle(WegoTokens.Palette.text)
        .navigationTitle("창작자").navigationBarTitleDisplayMode(.inline).toolbar(.visible, for: .navigationBar)
    }
}

struct CourseTagPreviewView: View {
    let tag: String
    let store: CourseDiscoveryPreviewStore
    @State private var query = ""
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: WegoTokens.Space.large) {
                CourseDiscoverySampleNote()
                HStack {
                    Image(systemName: "magnifyingglass").foregroundStyle(WegoTokens.Palette.secondary)
                    TextField("태그나 경로 이름", text: $query)
                        .font(WegoTokens.Typography.body).autocorrectionDisabled()
                        .accessibilityIdentifier("courseTagSearch")
                }
                .padding(WegoTokens.Space.compact)
                .background(WegoTokens.Palette.surface, in: RoundedRectangle(cornerRadius: WegoTokens.Radius.field))
                VStack(alignment: .leading, spacing: WegoTokens.Space.medium) {
                    Text("#" + tag).font(WegoTokens.Typography.title).accessibilityIdentifier("courseTagPreviewTitle")
                    if tag == "먹방" { Text("시안 통계 · 경로 42개 · 이 태그를 자주 올리는 창작자 3명").font(WegoTokens.Typography.label) }
                    Text("아래에서는 제공된 샘플 경로만 보여요.").font(WegoTokens.Typography.caption)
                    Button(store.followedTags.contains(tag) ? "태그 구독 중 · 해제" : "태그 구독") { store.toggleTag(tag) }
                        .font(WegoTokens.Typography.action).frame(minHeight: WegoTokens.Metrics.touchTarget)
                        .foregroundStyle(WegoTokens.Palette.routeHighlight).accessibilityIdentifier("courseTagFollow")
                }
                .padding(WegoTokens.Space.screen).frame(maxWidth: .infinity, alignment: .leading)
                .foregroundStyle(WegoTokens.Palette.onInk).background(WegoTokens.Palette.ink, in: RoundedRectangle(cornerRadius: WegoTokens.Radius.hero))
                if tag == "먹방" {
                    ScrollView(.horizontal) { HStack { ForEach(["시장", "해산물", "당일치기", "카페"], id: \.self) { CourseDiscoveryTagLink(tag: $0) } } }.scrollIndicators(.hidden)
                    Text("이 태그를 자주 올리는 창작자 · 시안 통계").font(WegoTokens.Typography.section)
                    HStack(alignment: .top, spacing: WegoTokens.Space.small) {
                        ForEach(["user-g", "user-h", "user-k"], id: \.self) { id in
                            if let creator = store.creator(id) {
                                NavigationLink(value: CourseDiscoveryRoute.creator(id)) {
                                    VStack(spacing: WegoTokens.Space.small) {
                                        CourseCreatorAvatar(name: creator.name)
                                        Text(creator.name).font(WegoTokens.Typography.label.weight(.semibold))
                                        Text("#먹방 \(id == "user-g" ? 9 : id == "user-h" ? 6 : 4)개").font(WegoTokens.Typography.caption)
                                    }.frame(maxWidth: .infinity).courseDiscoveryPanel()
                                }.buttonStyle(.plain).accessibilityIdentifier("courseTagCreator-\(id)")
                            }
                        }
                    }
                }
                Text("샘플 경로 · 별표 많은 순").font(WegoTokens.Typography.section)
                let courses = store.courses(tag: tag, query: query).sorted { (store.starCount($0) ?? 0) > (store.starCount($1) ?? 0) }
                if courses.isEmpty { Text("조건에 맞는 샘플 경로가 없어요.").font(WegoTokens.Typography.body).accessibilityIdentifier("courseTagSearchEmpty") }
                ForEach(courses) { CourseDiscoveryCard(course: $0, store: store) }
            }.padding(WegoTokens.Space.screen)
        }
        .background(WegoTokens.Palette.background).foregroundStyle(WegoTokens.Palette.text)
        .navigationTitle("태그").navigationBarTitleDisplayMode(.inline).toolbar(.visible, for: .navigationBar)
        .scrollDismissesKeyboard(.interactively)
    }
}
