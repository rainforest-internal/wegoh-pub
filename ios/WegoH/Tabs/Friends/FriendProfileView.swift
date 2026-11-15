import SwiftUI

struct FriendProfileView: View {
    let person: FriendPerson
    let store: FriendsStore
    let account: AccountSession
    @Environment(SessionManager.self) private var session
    @State private var detail: FriendProfile?
    @State private var error: String?
    @Environment(\.dismiss) private var dismiss
    @State private var confirmsDisconnect = false
    @State private var confirmsBlock = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: WegoTokens.Space.large) {
                VStack(spacing: WegoTokens.Space.compact) {
                    FriendAvatar(name: detail?.name ?? person.displayName, tone: .ink,
                                 size: WegoTokens.Metrics.friendProfileAvatarSize, large: true)
                    Text(detail?.name ?? person.displayName).font(WegoTokens.Typography.title)
                        .accessibilityAddTraits(.isHeader)
                }
                .frame(maxWidth: .infinity)
                VStack(alignment: .leading, spacing: WegoTokens.Space.compact) {
                    sectionTitle("친구 정보")
                    VStack(alignment: .leading, spacing: 0) {
                        infoRow("이름", value: detail?.name ?? person.displayName)
                        if let detail, !detail.plateNumbers.isEmpty {
                            Divider().overlay(WegoTokens.Palette.divider)
                            infoRow("차량 번호", value: detail.plateNumbers.joined(separator: ", "))
                        }
                        if let error {
                            if detail == nil {
                                WegoLoadingFailureView(message: error, messageIdentifier: "friendProfileError") { Task { await loadProfile() } }
                            } else {
                                Text(error).font(WegoTokens.Typography.label).foregroundStyle(WegoTokens.Palette.danger)
                                    .padding(.vertical, WegoTokens.Space.compact).accessibilityIdentifier("friendProfileError")
                            }
                        }
                        if detail == nil && error == nil {
                            WegoLoadingView("프로필을 불러오는 중", layout: .detail)
                                .padding(.vertical, WegoTokens.Space.compact)
                        }
                    }
                    .padding(.horizontal, WegoTokens.Space.medium)
                    .background(WegoTokens.Palette.surface, in: RoundedRectangle(cornerRadius: WegoTokens.Radius.card))
                }
                VStack(alignment: .leading, spacing: WegoTokens.Space.compact) {
                    sectionTitle("친구 관리")
                    VStack(spacing: 0) {
                        Button(role: .destructive) { confirmsDisconnect = true } label: {
                            Text("친구 연결 해제").foregroundStyle(WegoTokens.Palette.text)
                                .frame(maxWidth: .infinity, minHeight: WegoTokens.Metrics.primaryButtonHeight, alignment: .leading)
                                .contentShape(Rectangle())
                        }.accessibilityIdentifier("friendDisconnect")
                        Divider().overlay(WegoTokens.Palette.divider)
                        Button(role: .destructive) { confirmsBlock = true } label: {
                            Text("친구 차단").foregroundStyle(WegoTokens.Palette.danger)
                                .frame(maxWidth: .infinity, minHeight: WegoTokens.Metrics.primaryButtonHeight, alignment: .leading)
                                .contentShape(Rectangle())
                        }.accessibilityIdentifier("friendBlock")
                    }
                    .font(WegoTokens.Typography.body).buttonStyle(.plain)
                    .padding(.horizontal, WegoTokens.Space.medium)
                    .background(WegoTokens.Palette.background, in: RoundedRectangle(cornerRadius: WegoTokens.Radius.card))
                    .overlay { RoundedRectangle(cornerRadius: WegoTokens.Radius.card).strokeBorder(WegoTokens.Palette.divider) }
                    Text("차단하면 친구 연결이 해제되고 차단 목록으로 이동해요. 차단을 해제해도 친구로 자동 연결되지 않아요.")
                        .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
                        .fixedSize(horizontal: false, vertical: true).padding(.horizontal, WegoTokens.Space.xSmall)
                }
            }
            .padding(.horizontal, WegoTokens.Space.screen)
            .padding(.vertical, WegoTokens.Space.screen)
        }
        .task { await loadProfile() }
        .disabled(store.isMutating)
        .scrollBounceBehavior(.basedOnSize)
        .background(WegoTokens.Palette.background)
        .foregroundStyle(WegoTokens.Palette.text)
        .navigationTitle("")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar(.visible, for: .navigationBar)
        .alert("\(person.displayName)님과 친구 연결을 해제할까요?", isPresented: $confirmsDisconnect) {
            Button("연결 해제", role: .destructive) { perform(.disconnect) }
            Button("취소", role: .cancel) {}
        }
        .alert("\(person.displayName)님을 차단할까요?", isPresented: $confirmsBlock) {
            Button("친구 차단", role: .destructive) { perform(.block) }
            Button("취소", role: .cancel) {}
        } message: {
            Text("친구 연결이 해제되고 차단 목록으로 이동해요. 차단을 해제해도 친구로 자동 연결되지 않아요.")
        }
    }

    private func loadProfile() async {
        error = nil
        do { detail = try await session.withToken(for: account) { try await store.api.profile(person, token: $0) } }
        catch is CancellationError { }
        catch { if session.current == account { self.error = friendErrorMessage(error) } }
    }

    private func sectionTitle(_ title: String) -> some View {
        Text(title).font(WegoTokens.Typography.label.weight(.semibold))
            .foregroundStyle(WegoTokens.Palette.secondary).accessibilityAddTraits(.isHeader)
    }

    private func infoRow(_ title: String, value: String) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: WegoTokens.Space.compact) {
            Text(title).foregroundStyle(WegoTokens.Palette.secondary)
            Spacer(minLength: WegoTokens.Space.small)
            Text(value).multilineTextAlignment(.trailing)
        }
        .font(WegoTokens.Typography.body)
        .padding(.vertical, WegoTokens.Space.compact)
        .frame(minHeight: WegoTokens.Metrics.primaryButtonHeight)
    }

    private func perform(_ action: FriendAction) {
        Task {
            if await store.perform(action, person: person, session: session, account: account) { dismiss() }
            else { error = store.error }
        }
    }
}
