import SwiftUI

struct FriendsHomeView: View {
    @Environment(SessionManager.self) private var session
    @State private var showsLogin = false

    var body: some View {
        Group {
            if let account = session.current {
                if Set(["friends:read", "friends:manage"]).isSubset(of: account.scopes) {
                    AccountFriendsView(account: account).id(FriendsSessionIdentity(account: account))
                } else {
                    ContentUnavailableView {
                        Label("친구 기능을 연결해 주세요", systemImage: "person.2")
                    } description: {
                        Text("설정에서 로그아웃한 뒤 다시 로그인하면 친구 검색과 요청 관리 권한을 승인할 수 있어요.")
                    }
                }
            } else if session.phase == .checkingSession || session.phase == .signingOut {
                WegoLoadingView(session.phase == .signingOut ? "로그아웃 중…" : "로그인 확인 중…", layout: .list)
            } else if session.phase == .restoreFailed {
                WegoLoadingFailureView(message: session.message ?? "계정을 확인할 수 없어요.") { Task { await session.restore() } }
            } else {
                ContentUnavailableView {
                    Label("함께 떠날 친구를 찾아보세요", systemImage: "person.2")
                } description: {
                    Text("로그인하면 친구 코드를 검색하고 친구 요청을 보낼 수 있어요.")
                } actions: {
                    Button("로그인") { showsLogin = true }.buttonStyle(.wego(.primary))
                }
            }
        }
        .background(WegoTokens.Palette.background)
        .sheet(isPresented: $showsLogin) {
            LoginView(secondaryTitle: "닫기") { showsLogin = false }
        }
    }
}

private struct FriendsSessionIdentity: Hashable {
    let accountID: String
    let expiresAt: Date
    let scopes: Set<String>

    init(account: AccountSession) {
        accountID = account.accountID; expiresAt = account.expiresAt; scopes = account.scopes
    }
}

private struct AccountFriendsView: View {
    let account: AccountSession
    @Environment(SessionManager.self) private var session
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @State private var store = FriendsStore(api: friendsAPI())
    @State private var showsAdd = false

    private var hasLoadedSuccessfully: Bool { store.hasLoaded && store.error == nil }
    private var showsEmptyFriends: Bool { hasLoadedSuccessfully && store.friends.isEmpty }

    var body: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 0) {
                VStack(alignment: .leading, spacing: WegoTokens.Space.xSmall) {
                    HStack {
                        Text("친구").font(WegoTokens.Typography.hero).accessibilityAddTraits(.isHeader)
                        Spacer()

                    }
                    .frame(minHeight: WegoTokens.Metrics.settingsHeaderHeight)
                    Text("함께 떠날 사람들을 모아보세요.")
                        .font(WegoTokens.Typography.label).foregroundStyle(WegoTokens.Palette.secondary)
                }
                if !store.hasLoaded, let error = store.error {
                    WegoLoadingFailureView(message: error, messageIdentifier: "friendsError") { Task { await store.load(session: session, account: account) } }
                } else if let error = store.error {
                    VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
                        Text(error).font(WegoTokens.Typography.label).accessibilityIdentifier("friendsError")
                        Button("다시 불러오기") { Task { await store.load(session: session, account: account) } }
                            .frame(minHeight: WegoTokens.Metrics.touchTarget)
                    }
                    .padding(.top, WegoTokens.Space.medium)
                }
                if !store.hasLoaded && store.error == nil {
                    WegoLoadingView("친구를 불러오는 중", layout: .list) { Task { await store.load(session: session, account: account) } }
                        .padding(.top, WegoTokens.Space.medium)
                } else if store.isLoading {
                    WegoLoadingView("친구를 새로 불러오는 중", layout: .row)
                }
                if store.hasLoaded {
                    sectionTitle("받은 요청", count: store.incoming.count)
                    if hasLoadedSuccessfully && store.incoming.isEmpty {
                        WegoEmptyRequestRow(systemImage: "person.badge.plus", message: "받은 친구 요청이 없어요.")
                    }
                    ForEach(store.incoming) { person in
                        WegoCard(.soft, padding: WegoTokens.Space.compact) {
                            if dynamicTypeSize >= .xxLarge {
                                VStack(alignment: .leading, spacing: WegoTokens.Space.compact) {
                                    requestIdentity(person)
                                    requestActions(person).frame(maxWidth: .infinity, alignment: .trailing)
                                }
                            } else {
                                HStack(spacing: WegoTokens.Space.compact) {
                                    requestIdentity(person)
                                    requestActions(person)
                                }
                            }
                        }
                        .padding(.bottom, WegoTokens.Space.compact)
                    }
                    sectionTitle("내 친구", count: store.friends.count)
                    if showsEmptyFriends {
                        WegoEmptyListCard(
                            systemImage: "person.2",
                            title: "아직 연결된 친구가 없어요",
                            message: "친구 코드를 받아 추가해보세요.",
                            actionTitle: "친구 추가",
                            actionIdentifier: "friendsAdd",
                            contentIdentifier: "friendsEmpty", showsAction: false
                        ) {
                            showsAdd = true
                        }

                    }
                    ForEach(store.friends) { person in
                        NavigationLink {
                            FriendProfileView(person: person, store: store, account: account).toolbar(.hidden, for: .tabBar)
                        } label: {
                            HStack(spacing: WegoTokens.Space.compact) {
                                FriendIdentity(person: person, tone: person.id == store.friends.first?.id ? .ink : .soft)
                                Image(systemName: "chevron.right").font(WegoTokens.Typography.label.weight(.semibold))
                                    .foregroundStyle(WegoTokens.Palette.secondary).accessibilityHidden(true)
                            }
                            .padding(.vertical, WegoTokens.Space.small)
                            .frame(minHeight: WegoTokens.Metrics.friendRowHeight)
                            .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        .accessibilityLabel("\(person.displayName) 프로필 보기")
                        .accessibilityIdentifier("friendProfile-\(person.id)")
                        if person.id != store.friends.last?.id { Divider().overlay(WegoTokens.Palette.divider) }
                    }
                    if !store.outgoing.isEmpty || !store.blocked.isEmpty {
                        VStack(spacing: 0) {
                            DisclosureGroup {
                                if store.outgoing.isEmpty { empty("보낸 친구 요청이 없어요.") }
                                ForEach(store.outgoing) { person in
                                    VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
                                        FriendIdentity(person: person)
                                        Button("요청 취소") { perform(.cancel, person: person) }
                                            .frame(minHeight: WegoTokens.Metrics.touchTarget)
                                            .accessibilityIdentifier("friendCancel-\(person.id)")
                                    }.padding(.vertical, WegoTokens.Space.small)
                                }
                            } label: {
                                Text("보낸 요청 \(store.outgoing.count)").accessibilityIdentifier("friendsOutgoing")
                                    .padding(.vertical, WegoTokens.Space.medium)
                            }
                            Divider().overlay(WegoTokens.Palette.divider)
                            DisclosureGroup {
                                if store.blocked.isEmpty { empty("차단한 친구가 없어요.") }
                                ForEach(store.blocked) { person in
                                    VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
                                        FriendIdentity(person: person)
                                        Button("차단 해제") { perform(.unblock, person: person) }
                                            .frame(minHeight: WegoTokens.Metrics.touchTarget)
                                            .accessibilityIdentifier("friendUnblock-\(person.id)")
                                    }.padding(.vertical, WegoTokens.Space.small)
                                }
                            } label: {
                                Text("차단한 친구 \(store.blocked.count)").accessibilityIdentifier("friendsBlocked")
                                    .padding(.vertical, WegoTokens.Space.medium)
                            }
                        }
                        .font(WegoTokens.Typography.body)
                        .padding(.horizontal, WegoTokens.Space.medium)
                        .background(WegoTokens.Palette.surface, in: RoundedRectangle(cornerRadius: WegoTokens.Radius.card))
                        .padding(.top, WegoTokens.Space.compact)
                    }
                }
            }
            .padding(.horizontal, WegoTokens.Space.screen)
            .padding(.bottom, WegoTokens.Space.medium)
        }
        .task {
            if !store.hasLoaded && store.error == nil { await store.load(session: session, account: account) }
        }
        .refreshable { await store.load(session: session, account: account) }
        .disabled(store.isMutating)
        .scrollBounceBehavior(.always, axes: .vertical)
        .background(WegoTokens.Palette.background)
        .foregroundStyle(WegoTokens.Palette.text)
        .navigationTitle("친구")
        .toolbar(.hidden, for: .navigationBar)
        .safeAreaInset(edge: .bottom) {
            if store.hasLoaded {
                WegoFloatingAction(title: "친구 추가", identifier: "friendsAdd") { showsAdd = true }
            }
        }
        .sheet(isPresented: $showsAdd) {
            NavigationStack { AddFriendView(store: store, account: account) }
        }
    }

    private func requestIdentity(_ person: FriendPerson) -> some View {
        FriendIdentity(person: person, showsCode: false, tone: .accent, avatarSize: WegoTokens.Metrics.touchTarget)
    }

    private func requestActions(_ person: FriendPerson) -> some View {
        HStack(spacing: WegoTokens.Space.small) {
            Button("거절") { perform(.decline, person: person) }
                .buttonStyle(.wego(.plain))
                .accessibilityIdentifier("friendDecline-\(person.id)")
            Button("수락") { perform(.accept, person: person) }
                .buttonStyle(.wego(.primary)).fixedSize(horizontal: true, vertical: false)
                .accessibilityIdentifier("friendAccept-\(person.id)")
        }.fixedSize(horizontal: true, vertical: false)
    }

    private func perform(_ action: FriendAction, person: FriendPerson) {
        Task { await store.perform(action, person: person, session: session, account: account) }
    }

    private func sectionTitle(_ title: String, count: Int) -> some View {
        SectionHeader(count == 0 ? title : "\(title) \(count)")
            .padding(.top, WegoTokens.Space.large).padding(.bottom, WegoTokens.Space.small)
            .accessibilityAddTraits(.isHeader)
    }

    private func empty(_ text: String) -> some View {
        Text(text).font(WegoTokens.Typography.label).foregroundStyle(WegoTokens.Palette.secondary)
            .fixedSize(horizontal: false, vertical: true).padding(.vertical, WegoTokens.Space.small)
    }
}

struct FriendIdentity: View {
    let person: FriendPerson
    var showsCode = true
    var tone: FriendAvatar.Tone = .soft
    var avatarSize = WegoTokens.Metrics.friendAvatarSize

    var body: some View {
        HStack(spacing: WegoTokens.Space.compact) {
            FriendAvatar(name: person.displayName, tone: tone, size: avatarSize)
            VStack(alignment: .leading, spacing: WegoTokens.Space.xSmall) {
                Text(person.displayName).font(WegoTokens.Typography.section)
                if showsCode {
                    Text(person.code).font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
                }
            }
            .fixedSize(horizontal: false, vertical: true)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .accessibilityElement(children: .combine)
    }
}

struct FriendAvatar: View {
    enum Tone { case soft, accent, ink }
    let name: String
    var tone: Tone = .soft
    var size = WegoTokens.Metrics.friendAvatarSize
    var large = false

    var body: some View {
        AvatarBadge(name: name, tone: tone == .ink ? .ink : tone == .accent ? .accent : .soft, size: size)
            .accessibilityHidden(true)
    }
}

@MainActor
private func friendsAPI() -> any IPhoneFriendsServing {
    #if DEBUG
    if FriendsUIFixture.requested { return IPhoneFriendsAPI(configuration: FriendsUIFixture.configuration()) }
    #endif
    return IPhoneFriendsAPI()
}
