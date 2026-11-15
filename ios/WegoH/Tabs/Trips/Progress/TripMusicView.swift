import SwiftUI

struct TripMusicView: View {
    @State private var store: TripMusicStore
    @Environment(\.dismiss) private var dismiss
    @State private var showsAdd = false
    @State private var addMode: TripMusicAddMode?
    init(preparation: TripPreparationStore, api: any IPhoneTripMusicServing = IPhoneTripMusicAPI()) {
        _store = State(initialValue: TripMusicStore(preparation: preparation, api: api))
    }
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: WegoTokens.Space.medium) {
                if !store.preparation.accountIsCurrent {
                    Text("계정이 바뀌었어요. 여행 목록에서 다시 열어 주세요.")
                } else {
                    if let page = store.visiblePage {
                        WegoCard(.surface) {
                            Toggle("이 여행에 내 음악 공유", isOn: Binding(get: { page.musicSharing }, set: { value in Task { await store.setSharing(value) } }))
                                .font(WegoTokens.Typography.section)
                                .frame(minHeight: WegoTokens.Metrics.touchTarget)
                                .disabled(store.busy || store.resultUnknown).accessibilityIdentifier("tripMusicSharing")
                            Text("켜면 여행에 음악 링크를 추가할 수 있어요. 끄면 내 음악 공유가 중단돼요.")
                                .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
                        }
                        if !page.items.isEmpty { nowPlaying(page) }
                        if !page.items.isEmpty {
                            SectionHeader("여행 플레이리스트 \(page.items.count)개")
                            Text(page.canReorder ? "DJ와 여행 만든 사람이 순서를 정해요. 차에서는 이 순서로 다음 곡을 열어요."
                                                 : "DJ나 여행 만든 사람이 정한 순서예요. 차에서는 이 순서로 다음 곡을 열어요.")
                                .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
                        }
                        if page.items.isEmpty {
                            emptyState(page)
                        }
                        ForEach(Array(page.items.enumerated()), id: \.element.id) { index, item in
                            itemCard(item, index: index, page: page)
                        }
                        if page.musicSharing && !page.items.isEmpty {
                            Button("음악 추가") { showsAdd = true }
                                .buttonStyle(.wego(.primary)).disabled(store.busy || store.resultUnknown || !page.canAdd)
                        }

                    } else if store.busy || store.message == nil { WegoLoadingView("여행 음악을 불러오는 중", layout: .detail) }
                    if store.busy, store.visiblePage != nil { WegoLoadingView("여행 음악 확인 중", layout: .row) }
                    if let message = store.message {
                        Text(message).font(WegoTokens.Typography.label).accessibilityIdentifier("tripMusicMessage")
                    }
                    if store.resultUnknown {
                        Button("목록을 불러와 추가 결과 확인") { Task { await store.load() } }
                            .buttonStyle(.wego(.soft)).disabled(store.busy)
                            .accessibilityIdentifier("tripMusicReload")
                    }
                }
            }.padding(WegoTokens.Space.screen)
        }
        .scrollDismissesKeyboard(.interactively)
        .background(WegoTokens.Palette.background).foregroundStyle(WegoTokens.Palette.text)
        .navigationTitle("여행 플레이리스트").navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .cancellationAction) { Button("닫기") { dismiss() } }
            ToolbarItem(placement: .topBarTrailing) {
                Button { Task { await store.load() } } label: {
                    Image(systemName: "arrow.clockwise")
                        .frame(minWidth: WegoTokens.Metrics.touchTarget, minHeight: WegoTokens.Metrics.touchTarget)
                        .contentShape(Circle())
                }.accessibilityLabel("새로고침").disabled(store.busy)
            }
        }
        .sheet(isPresented: $showsAdd) {
            NavigationStack { addForm }
        }
        .onChange(of: store.visiblePage?.items.count) { previous, current in
            if showsAdd, let previous, let current, current > previous { showsAdd = false }
        }
        .onChange(of: showsAdd) { _, shown in
            addMode = nil
            if shown { Task { await store.loadLibrary() } }
        }
        .task(id: store.contextID) { await store.load() }
        .refreshable { await store.load() }
    }
    @ViewBuilder
    private func nowPlaying(_ page: IPhoneTripMusicPage) -> some View {
        WegoCard(.outlined) {
            Label("지금 차에서 재생 중", systemImage: "music.note")
                .font(WegoTokens.Typography.label).foregroundStyle(WegoTokens.Palette.accent)
            if page.nowPlaying.isEmpty {
                Text("차의 노래 듣기에서 곡을 재생하면 여기에 보여요.")
                    .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
            }
            ForEach(page.nowPlaying, id: \.startedBy.id) { playback in
                if let item = page.item(playback.itemId) {
                    VStack(alignment: .leading, spacing: WegoTokens.Space.xSmall) {
                        Text(item.title).font(WegoTokens.Typography.section)
                        Text("\(item.addedBy.name)님 추천 · \(playback.startedBy.name)님 차")
                            .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
                    }
                    .accessibilityElement(children: .combine)
                    .accessibilityIdentifier("tripMusicNowPlaying-" + playback.startedBy.id)
                }
            }
        }
    }

    private func itemCard(_ item: IPhoneTripMusicPage.Item, index: Int, page: IPhoneTripMusicPage) -> some View {
        WegoCard(.surface) {
            HStack(alignment: .top, spacing: WegoTokens.Space.small) {
                VStack(alignment: .leading, spacing: WegoTokens.Space.xSmall) {
                    if page.isPlaying(item) { StatusPill("재생 중", tone: .live) }
                    Text(item.title).font(WegoTokens.Typography.section)
                    Text("\(item.platform.label) · \(item.addedBy.name) 추가")
                        .font(WegoTokens.Typography.label).foregroundStyle(WegoTokens.Palette.secondary)
                    Text(item.visibilityLabel).font(WegoTokens.Typography.caption)
                        .foregroundStyle(WegoTokens.Palette.secondary)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .accessibilityElement(children: .combine)
                if page.canReorder && page.items.count > 1 {
                    Menu {
                        Button("맨 위로", systemImage: "arrow.up.to.line") { Task { await store.move(item, .top) } }
                            .disabled(index == 0)
                        Button("위로", systemImage: "arrow.up") { Task { await store.move(item, .up) } }
                            .disabled(index == 0)
                        Button("아래로", systemImage: "arrow.down") { Task { await store.move(item, .down) } }
                            .disabled(index + 1 == page.items.count)
                    } label: {
                        Image(systemName: "arrow.up.arrow.down")
                            .frame(minWidth: WegoTokens.Metrics.touchTarget, minHeight: WegoTokens.Metrics.touchTarget)
                            .contentShape(Rectangle())
                    }
                    .accessibilityLabel("\(item.title) 순서 바꾸기")
                    .disabled(store.busy || store.resultUnknown)
                    .accessibilityIdentifier("tripMusicMove-" + item.id)
                }
            }
        }.accessibilityIdentifier("tripMusicItem-" + item.id)
    }

    private func emptyState(_ page: IPhoneTripMusicPage) -> some View {
        VStack(spacing: WegoTokens.Space.medium) {
            Image(systemName: "music.note.list")
                .font(WegoTokens.Typography.title).foregroundStyle(WegoTokens.Palette.accent)
                .frame(width: WegoTokens.Metrics.emptyIconSize, height: WegoTokens.Metrics.emptyIconSize)
                .background(WegoTokens.Palette.accentSoft, in: Circle()).accessibilityHidden(true)
            Text("아직 여행 플레이리스트가 없어요").font(WegoTokens.Typography.section)
            Text("DJ나 일행이 음악을 추가하면 여기에 모이고, 차 화면의 노래 듣기에도 보여요.")
                .font(WegoTokens.Typography.label).foregroundStyle(WegoTokens.Palette.secondary)
            Button("음악 추가") { showsAdd = true }
                .buttonStyle(.wego(.primary)).disabled(!page.musicSharing || store.busy || store.resultUnknown || !page.canAdd)
            if !page.musicSharing {
                Text("위의 음악 공유를 켜면 음악을 추가할 수 있어요.")
                    .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
            }
        }
        .multilineTextAlignment(.center)
        .frame(maxWidth: .infinity).padding(WegoTokens.Space.large)
        .overlay {
            RoundedRectangle(cornerRadius: WegoTokens.Radius.card)
                .strokeBorder(WegoTokens.Palette.personalRouteBorder,
                              style: StrokeStyle(lineWidth: WegoTokens.Metrics.hairlineWidth, dash: [WegoTokens.Space.xSmall, WegoTokens.Space.xSmall]))
        }
        .accessibilityIdentifier("tripMusicEmpty")
    }

    private var addForm: some View {
        @Bindable var store = store
        let mode = addMode ?? (store.library != nil && store.savedChoices.isEmpty ? .link : .library)
        return ScrollView {
            VStack(alignment: .leading, spacing: WegoTokens.Space.medium) {
                Picker("추가 방법", selection: Binding(get: { mode }, set: { addMode = $0 })) {
                    ForEach(TripMusicAddMode.allCases) { Text($0.label).tag($0) }
                }
                .pickerStyle(.segmented).frame(minHeight: WegoTokens.Metrics.touchTarget).disabled(store.busy)
                .accessibilityIdentifier("tripMusicAddMode")
                if let page = store.visiblePage, mode == .library {
                    TripMusicLibraryPicker(store: store, page: page) { addMode = .link }
                } else if let page = store.visiblePage {
                    WegoCard(.outlined) {
                        VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
                            Text("제목").font(WegoTokens.Typography.label)
                            TextField("음악 제목", text: $store.draft.title)
                                .textFieldStyle(.roundedBorder).frame(minHeight: WegoTokens.Metrics.touchTarget).accessibilityIdentifier("tripMusicTitle")
                            Picker("플랫폼", selection: $store.draft.platform) {
                                ForEach(MusicPlatform.allCases) { Text($0.label).tag($0) }
                            }.frame(minHeight: WegoTokens.Metrics.touchTarget).accessibilityIdentifier("tripMusicPlatform")
                            Text("URL").font(WegoTokens.Typography.label)
                            TextField("https://", text: $store.draft.url)
                                .textContentType(.URL).keyboardType(.URL).textInputAutocapitalization(.never).autocorrectionDisabled()
                                .textFieldStyle(.roundedBorder).frame(minHeight: WegoTokens.Metrics.touchTarget).accessibilityIdentifier("tripMusicURL")
                                .onChange(of: store.draft.url) { _, value in
                                    if let url = MusicPreviewStore.validatedURL(value) { store.draft.platform = MusicPlatform.detected(for: url) }
                                }
                            Toggle("제목과 링크를 공유할 권리가 있어요", isOn: $store.draft.rightsConfirmed)
                                .frame(minHeight: WegoTokens.Metrics.touchTarget).accessibilityIdentifier("tripMusicRights")
                            Toggle("일행에게 공유 요청", isOn: $store.draft.reviewConsent)
                                .frame(minHeight: WegoTokens.Metrics.touchTarget).accessibilityIdentifier("tripMusicReview")
                            Text("공유 요청을 끄면 나에게만 보여요. 요청한 링크는 공유 검토가 끝나면 일행에게 보여요.")
                                .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
                            Button { Task { await store.add() } } label: {
                                Text(store.busy ? "처리 중…" : "추가")
                                    .frame(maxWidth: .infinity, minHeight: WegoTokens.Metrics.primaryButtonHeight)
                            }.buttonStyle(WegoPrimaryButtonStyle()).disabled(!store.canAdd)
                                .accessibilityIdentifier("tripMusicAdd")
                            if !page.canAdd { Text("여행 음악 목록이 가득 찼어요.").font(WegoTokens.Typography.caption) }
                        }.font(WegoTokens.Typography.body).disabled(store.busy)
                    }
                }
                if let message = store.message { Text(message).font(WegoTokens.Typography.label) }
            }.padding(WegoTokens.Space.screen)
        }
        .background(WegoTokens.Palette.background).foregroundStyle(WegoTokens.Palette.text)
        .navigationTitle("음악 추가").navigationBarTitleDisplayMode(.inline)
        .toolbar { ToolbarItem(placement: .cancellationAction) { Button("닫기") { showsAdd = false }.disabled(store.busy) } }
    }

}
