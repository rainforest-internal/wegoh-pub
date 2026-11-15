import SwiftUI

struct MusicHomeView: View {
    @Environment(SessionManager.self) private var session
    @State private var showsLogin = false
    var body: some View {
        Group {
            if let account = session.current {
                AccountMusicHomeView(account: account).id(account.accountID)
            } else if session.phase == .checkingSession || session.phase == .signingOut {
                WegoLoadingView("계정 확인 중…", layout: .list)
            } else if session.phase == .restoreFailed {
                WegoLoadingFailureView(message: session.message ?? "계정을 확인할 수 없어요.") { Task { await session.restore() } }
            } else {
                ContentUnavailableView {
                    Label("함께 들을 음악을 모아보세요", systemImage: "music.note.list")
                } description: {
                    Text("로그인하면 플레이리스트를 저장하고 연결한 차량에서도 볼 수 있어요.")
                } actions: {
                    Button("로그인") { showsLogin = true }.buttonStyle(.wego(.primary))
                }
            }
        }
        .background(WegoTokens.Palette.background)
        .sheet(isPresented: $showsLogin) { LoginView(secondaryTitle: "닫기") { showsLogin = false } }
    }
}

private struct AccountMusicHomeView: View {
    let account: AccountSession
    @Environment(SessionManager.self) private var session
    @State private var store = MusicPreviewStore()
    @State private var showsAdd = false

    var body: some View {
        Group {
            if !store.hasLoaded, let error = store.error {
                WegoLoadingFailureView(message: error) { Task { await store.load(session: session, account: account, force: true) } }
            } else if !store.hasLoaded {
                WegoLoadingView("음악 불러오는 중…", layout: .list)
            } else {
                content
            }
        }
        .task { await store.load(session: session, account: account) }
    }

    private var content: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 0) {
                HStack {
                    Text("음악").font(WegoTokens.Typography.hero)
                        .accessibilityAddTraits(.isHeader)
                    Spacer()
                }
                .frame(minHeight: WegoTokens.Metrics.settingsHeaderHeight)

                WegoCard(.ink, padding: WegoTokens.Space.screen) {
                    VStack(alignment: .leading, spacing: WegoTokens.Space.medium) {
                        Text("내 플레이리스트 \(store.items.count)개")
                            .font(WegoTokens.Typography.label)
                            .foregroundStyle(WegoTokens.Palette.onInkSecondary)
                        PlaylistEqualizer(isEmpty: store.items.isEmpty)
                        Text("여행에서 함께 들을\n플레이리스트를 모아두세요.")
                            .font(WegoTokens.Typography.cardTitle)
                            .foregroundStyle(WegoTokens.Palette.onInk)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                .padding(.top, WegoTokens.Space.screen)

                SectionHeader("내 플레이리스트")
                    .padding(.top, WegoTokens.Space.large)
                    .padding(.bottom, WegoTokens.Space.xSmall)
                if store.items.isEmpty {
                    WegoEmptyListCard(systemImage: "music.note",
                                      title: "플레이리스트를 추가해 주세요.",
                                      message: "음악 서비스에서 공유한 플레이리스트 링크를 붙여 넣으면 돼요.",
                                      actionTitle: "플레이리스트 추가",
                                      actionIdentifier: "musicAddPlaylist", contentIdentifier: "musicEmpty", showsAction: false) { showsAdd = true }

                }
                if let error = store.error {
                    Text(error).font(WegoTokens.Typography.label).foregroundStyle(WegoTokens.Palette.danger)
                        .padding(.vertical, WegoTokens.Space.small)
                }
                ForEach(store.items) { item in
                    HStack(spacing: WegoTokens.Space.small) {
                        if let url = item.url {
                            Link(destination: url) {
                                WegoRow(systemImage: "music.note", title: item.title, subtitle: item.platform.label,
                                        accessorySystemImage: "arrow.up.right")
                                    .padding(.vertical, WegoTokens.Space.compact)
                                    .contentShape(Rectangle())
                            }
                            .buttonStyle(.plain)
                            .accessibilityLabel("\(item.title), \(item.platform.label)")
                            .accessibilityHint("저장한 플레이리스트 링크 열기")
                            .accessibilityIdentifier("musicItem-\(item.id)")
                        }
                        NavigationLink {
                            PlaylistEditorView(store: store, account: account, item: item).toolbar(.hidden, for: .tabBar)
                        } label: {
                            Image(systemName: "pencil")
                                .font(WegoTokens.Typography.label)
                                .foregroundStyle(WegoTokens.Palette.secondary)
                                .frame(minWidth: WegoTokens.Metrics.touchTarget, minHeight: WegoTokens.Metrics.touchTarget)
                                .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        .accessibilityLabel("\(item.title) 수정")
                        .accessibilityIdentifier("musicEdit-\(item.id)")
                    }
                    if item.id != store.items.last?.id { Divider().overlay(WegoTokens.Palette.divider) }
                }
            }
            .padding(.horizontal, WegoTokens.Space.screen)
            .padding(.bottom, WegoTokens.Space.medium)
        }
        .refreshable { await store.load(session: session, account: account, force: true) }
        .scrollBounceBehavior(.basedOnSize)
        .background(WegoTokens.Palette.background)
        .foregroundStyle(WegoTokens.Palette.text)
        .navigationTitle("음악")
        .toolbar(.hidden, for: .navigationBar)
        .safeAreaInset(edge: .bottom) {
            WegoFloatingAction(title: "플레이리스트 추가", identifier: "musicAddPlaylist") { showsAdd = true }
                .disabled(store.isLoading || store.isMutating || store.needsReload || !account.scopes.contains("account:write"))
        }
        .sheet(isPresented: $showsAdd) {
            NavigationStack { PlaylistEditorView(store: store, account: account) }
        }
    }
}

private struct PlaylistEqualizer: View {
    let isEmpty: Bool

    var body: some View {
        Canvas { context, size in
            context.scaleBy(x: size.width / 83, y: size.height / 44)
            let heights = isEmpty ? Array(repeating: 4.0, count: 8) : [16.0, 30, 44, 24, 36, 12, 28, 20]
            for (index, height) in heights.enumerated() {
                let rect = CGRect(x: Double(index) * 11, y: 44 - height, width: 6, height: height)
                let color = !isEmpty && (index == 2 || index == 6) ? WegoTokens.Palette.onInk : WegoTokens.Palette.routeHighlight
                context.fill(RoundedRectangle(cornerRadius: 3).path(in: rect), with: .color(color))
            }
        }
        .frame(width: WegoTokens.Metrics.musicEqualizerWidth, height: WegoTokens.Metrics.musicEqualizerHeight)
        .accessibilityHidden(true)
    }
}
