import SwiftUI

struct AddFriendView: View {
    let store: FriendsStore
    let account: AccountSession
    @Environment(SessionManager.self) private var session
    @Environment(\.dismiss) private var dismiss
    @State private var code = ""
    @State private var result: FriendPerson?
    @State private var searched = false
    @State private var isSearching = false
    @State private var error: String?
    @State private var searchTask: Task<Void, Never>?
    @State private var read = UUID()
    @FocusState private var codeFocused: Bool

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: WegoTokens.Space.large) {
                VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
                    Text("친구 코드").font(WegoTokens.Typography.label.weight(.semibold))
                        .foregroundStyle(WegoTokens.Palette.secondary)
                    HStack(spacing: WegoTokens.Space.small) {
                        WegoField("친구 코드", text: $code, focus: $codeFocused,
                                  prompt: "예: weekend.drive", identifier: "friendCodeInput", showsTitle: false)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                            .keyboardType(.asciiCapable)
                            .submitLabel(.search)
                            .onSubmit(search)
                            .onChange(of: code) { _, _ in
                                searchTask?.cancel(); read = UUID(); isSearching = false
                                searched = false; result = nil; error = nil
                            }
                        Button("검색", action: search)
                            .buttonStyle(.wego(.primary))
                            .fixedSize(horizontal: true, vertical: false)
                            .disabled(normalizedFriendCode(code) == nil || isSearching || store.isMutating)
                            .accessibilityIdentifier("friendSearch")
                    }
                    Text("상대가 알려준 친구 코드를 입력해 주세요. @가 있어도 검색할 수 있어요.")
                        .font(WegoTokens.Typography.label).foregroundStyle(WegoTokens.Palette.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                if isSearching { WegoLoadingView("친구를 찾는 중", layout: .row) }
                if let error { Text(error).foregroundStyle(WegoTokens.Palette.danger).accessibilityIdentifier("friendSearchError") }
                if let error = store.error { Text(error).foregroundStyle(WegoTokens.Palette.danger).accessibilityIdentifier("friendActionError") }
                if let person = result {
                    VStack(alignment: .leading, spacing: WegoTokens.Space.compact) {
                        sectionTitle("검색 결과")
                        WegoCard(.outlined) {
                            VStack(alignment: .leading, spacing: WegoTokens.Space.medium) {
                                FriendIdentity(person: person, tone: .ink, avatarSize: WegoTokens.Metrics.friendSearchAvatarSize)
                                switch store.relationship(to: person) {
                                case .none:
                                    resultAction("친구 요청 보내기", action: .request, person: person)
                                        .accessibilityIdentifier("friendSendRequest")
                                case .incoming:
                                    resultAction("받은 요청 수락", action: .accept, person: person)
                                case .outgoing:
                                    Label("요청 보냄", systemImage: "checkmark.circle.fill")
                                        .font(WegoTokens.Typography.action).foregroundStyle(WegoTokens.Palette.accent)
                                        .accessibilityIdentifier("friendRequestSent")
                                case .friend: Text("이미 연결된 친구예요.")
                                case .blocked: Text("차단한 친구예요.")
                                case .selfAccount: Text("내 친구 코드예요. 다른 사람의 코드를 입력해 주세요.")
                                }
                            }
                        }
                        .disabled(store.isMutating)
                    }
                } else if searched && error == nil {
                    Text("일치하는 친구가 없어요. 코드를 다시 확인해 주세요.")
                        .foregroundStyle(WegoTokens.Palette.secondary)
                        .accessibilityIdentifier("friendSearchEmpty")
                }

            }
            .padding(.horizontal, WegoTokens.Space.screen)
            .padding(.vertical, WegoTokens.Space.medium)
        }
        .onDisappear { searchTask?.cancel() }
        .scrollBounceBehavior(.basedOnSize)
        .background(WegoTokens.Palette.background)
        .foregroundStyle(WegoTokens.Palette.text)
        .navigationTitle("친구 추가")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar(.visible, for: .navigationBar)
        .toolbar {
            ToolbarItem(placement: .confirmationAction) {
                Button("완료") { dismiss() }.accessibilityIdentifier("friendAddDone")
            }
        }
        .presentationCornerRadius(WegoTokens.Radius.sheet)
    }

    private func sectionTitle(_ title: String) -> some View {
        SectionHeader(title)
    }

    private func resultAction(_ title: String, action: FriendAction, person: FriendPerson) -> some View {
        Button(title) { perform(action, person: person) }
            .buttonStyle(.wego(.primary))
    }

    private func search() {
        guard normalizedFriendCode(code) != nil, !isSearching else { return }
        codeFocused = false
        searchTask?.cancel()
        let stamp = UUID(), query = code
        read = stamp; isSearching = true; searched = false; result = nil; error = nil
        searchTask = Task {
            defer { if read == stamp { isSearching = false } }
            do {
                let found = try await store.search(code: query, session: session, account: account)
                guard read == stamp else { return }
                result = found; searched = true
            } catch is CancellationError { }
            catch { if read == stamp, session.current == account { self.error = friendErrorMessage(error) } }
        }
    }

    private func perform(_ action: FriendAction, person: FriendPerson) {
        Task { await store.perform(action, person: person, session: session, account: account) }
    }
}
