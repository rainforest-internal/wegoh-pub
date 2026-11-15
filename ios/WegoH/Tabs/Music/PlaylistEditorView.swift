import SwiftUI

struct PlaylistEditorView: View {
    let store: MusicPreviewStore
    let account: AccountSession
    @Environment(SessionManager.self) private var session
    let item: MusicPreviewItem?
    @Environment(\.dismiss) private var dismiss
    @State private var platform: MusicPlatform
    @State private var title: String
    @State private var url: String
    @State private var error: String?
    @State private var confirmsDelete = false
    @FocusState private var titleFocused: Bool
    @FocusState private var urlFocused: Bool

    init(store: MusicPreviewStore, account: AccountSession, item: MusicPreviewItem? = nil) {
        self.store = store
        self.account = account
        self.item = item
        _platform = State(initialValue: item?.platform ?? .melon)
        _title = State(initialValue: item?.title ?? "")
        _url = State(initialValue: item?.url?.absoluteString ?? "")
    }

    private var canSave: Bool {
        let title = title.trimmingCharacters(in: .whitespacesAndNewlines)
        let url = url.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !title.isEmpty, !url.isEmpty else { return false }
        guard let item else { return true }
        return title != item.title || url != item.url?.absoluteString || platform != item.platform
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: WegoTokens.Space.large) {
                VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
                    fieldTitle("플레이리스트 이름")
                    HStack(spacing: WegoTokens.Space.small) {
                        TextField("플레이리스트 이름", text: $title)
                            .focused($titleFocused)
                            .accessibilityLabel("플레이리스트 이름")
                            .accessibilityIdentifier("musicPlaylistTitle")
                        clearButton("이름 지우기", id: "musicClearTitle", empty: title.isEmpty) {
                            title = ""; titleFocused = true
                        }
                    }
                    .playlistFieldSurface(focused: titleFocused)
                }
                VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
                    fieldTitle("플랫폼")
                    PlaylistPlatformLayout {
                        ForEach([MusicPlatform.youtubeMusic, .youtube, .spotify, .melon, .other]) { choice in
                            Button { platform = choice } label: {
                                Text(choice.label)
                                    .font(WegoTokens.Typography.label.weight(platform == choice ? .semibold : .regular))
                                    .foregroundStyle(platform == choice ? WegoTokens.Palette.onInk : WegoTokens.Palette.text)
                                    .padding(.horizontal, WegoTokens.Space.medium)
                                    .padding(.vertical, WegoTokens.Space.small)
                                    .frame(minHeight: WegoTokens.Metrics.touchTarget)
                                    .background(platform == choice ? WegoTokens.Palette.ink : WegoTokens.Palette.background, in: Capsule())
                                    .overlay { Capsule().strokeBorder(platform == choice ? WegoTokens.Palette.ink : WegoTokens.Palette.divider) }
                                    .contentShape(Capsule())
                            }
                            .buttonStyle(.plain)
                            .accessibilityIdentifier(platform == choice ? "musicPlatform" : "musicPlatform-\(choice.rawValue)")
                            .accessibilityAddTraits(platform == choice ? .isSelected : [])
                        }
                    }
                    .accessibilityElement(children: .contain)
                    .accessibilityLabel("플랫폼")
                }
                VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
                    fieldTitle("플레이리스트 링크")
                    HStack(spacing: WegoTokens.Space.small) {
                        TextField("https://", text: $url)
                            .focused($urlFocused)
                            .accessibilityLabel("플레이리스트 링크")
                            .accessibilityIdentifier("musicPlaylistURL")
                            .keyboardType(.URL)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                            .submitLabel(.done)
                            .onSubmit(save)
                            .onChange(of: url) { _, value in
                                if let url = MusicPreviewStore.validatedURL(value) {
                                    let detected = MusicPlatform.detected(for: url)
                                    if detected != .other { platform = detected }
                                }
                            }
                        clearButton("링크 지우기", id: "musicClearURL", empty: url.isEmpty) {
                            url = ""; urlFocused = true
                        }
                    }
                    .playlistFieldSurface(focused: urlFocused, subdued: true)
                    Text("음악 서비스에서 공유한 플레이리스트 링크를 붙여 넣어 주세요.")
                        .font(WegoTokens.Typography.label)
                        .foregroundStyle(WegoTokens.Palette.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                if let error {
                    HStack(alignment: .top, spacing: WegoTokens.Space.compact) {
                        Image(systemName: "exclamationmark.circle")
                            .font(WegoTokens.Typography.cardTitle)
                            .foregroundStyle(WegoTokens.Palette.danger)
                            .accessibilityHidden(true)
                        Text(error).font(WegoTokens.Typography.label)
                            .fixedSize(horizontal: false, vertical: true)
                            .accessibilityIdentifier("musicPlaylistError")
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(WegoTokens.Space.compact)
                    .overlay { RoundedRectangle(cornerRadius: WegoTokens.Radius.control).strokeBorder(WegoTokens.Palette.danger) }
                }
                if store.needsReload {
                    Button("목록 새로고침") {
                        Task { await store.load(session: session, account: account, force: true); error = store.error }
                    }.buttonStyle(.wego(.soft))
                }
                if item != nil {
                    Button(role: .destructive) { confirmsDelete = true } label: {
                        Text("목록에서 삭제").font(WegoTokens.Typography.body)
                            .foregroundStyle(WegoTokens.Palette.danger)
                            .frame(maxWidth: .infinity, minHeight: WegoTokens.Metrics.primaryButtonHeight, alignment: .leading)
                            .padding(.horizontal, WegoTokens.Space.medium)
                            .background(WegoTokens.Palette.surface, in: RoundedRectangle(cornerRadius: WegoTokens.Radius.card))
                            .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("musicDeletePlaylist")
                }
            }
            .padding(.horizontal, WegoTokens.Space.screen)
            .padding(.vertical, WegoTokens.Space.screen)
        }
        .scrollBounceBehavior(.basedOnSize)
        .background(WegoTokens.Palette.background)
        .foregroundStyle(WegoTokens.Palette.text)
        .navigationTitle(item == nil ? "플레이리스트 추가" : "플레이리스트 수정")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar(.visible, for: .navigationBar)
        .toolbar {
            if item == nil {
                ToolbarItem(placement: .cancellationAction) {
                    Button("취소") { dismiss() }.accessibilityIdentifier("musicEditorCancel")
                }
            }
            ToolbarItem(placement: .confirmationAction) {
                Button(item == nil ? "추가" : "저장", action: save)
                    .font(WegoTokens.Typography.action)
                    .disabled(!canSave || store.needsReload || store.isMutating || store.isLoading)
                    .accessibilityIdentifier("musicSavePlaylist")
            }
        }
        .disabled(store.isMutating)
        .interactiveDismissDisabled(store.isMutating)
        .overlay {
            if store.isMutating {
                ZStack {
                    WegoTokens.Palette.ink.opacity(WegoTokens.Opacity.modalScrim)
                    WegoLoadingSpinner(onInk: true)
                }.ignoresSafeArea().contentShape(Rectangle()).accessibilityLabel("저장 중")
            }
        }
        .presentationCornerRadius(WegoTokens.Radius.sheet)
        .alert("목록에서 삭제할까요?", isPresented: $confirmsDelete) {
            Button("삭제", role: .destructive) {
                if let item {
                    Task {
                        error = await store.remove(id: item.id, session: session, account: account)
                        if error == nil { dismiss() }
                    }
                }
            }
            Button("취소", role: .cancel) {}
        }
    }

    private func fieldTitle(_ title: String) -> some View {
        Text(title).font(WegoTokens.Typography.label.weight(.semibold))
            .foregroundStyle(WegoTokens.Palette.secondary)
            .accessibilityAddTraits(.isHeader)
    }

    private func clearButton(_ title: String, id: String, empty: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: "xmark.circle.fill")
                .frame(minWidth: WegoTokens.Metrics.touchTarget, minHeight: WegoTokens.Metrics.touchTarget)
        }
        .buttonStyle(.borderless)
        .foregroundStyle(WegoTokens.Palette.secondary)
        .accessibilityLabel(title)
        .accessibilityIdentifier(id)
        .opacity(empty ? 0 : 1)
        .disabled(empty)
        .accessibilityHidden(empty)
    }

    private func save() {
        guard canSave else { return }
        titleFocused = false
        urlFocused = false
        Task {
            error = await store.save(id: item?.id, title: title, platform: platform, rawURL: url, session: session, account: account)
            if error == nil { dismiss() }
        }
    }
}

private extension View {
    func playlistFieldSurface(focused: Bool, subdued: Bool = false) -> some View {
        font(WegoTokens.Typography.body)
            .padding(.horizontal, WegoTokens.Space.medium)
            .frame(minHeight: WegoTokens.Metrics.primaryButtonHeight)
            .background(subdued && !focused ? WegoTokens.Palette.surface : WegoTokens.Palette.background,
                        in: RoundedRectangle(cornerRadius: WegoTokens.Radius.control))
            .overlay {
                RoundedRectangle(cornerRadius: WegoTokens.Radius.control)
                    .strokeBorder(focused ? WegoTokens.Palette.accent : WegoTokens.Palette.divider,
                                  lineWidth: focused ? WegoTokens.Metrics.selectedBorderWidth : WegoTokens.Metrics.hairlineWidth)
            }
    }
}

private struct PlaylistPlatformLayout: Layout {
    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        arrangement(width: proposal.width ?? .infinity, subviews: subviews).size
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        let layout = arrangement(width: bounds.width, subviews: subviews)
        for (index, frame) in layout.frames.enumerated() {
            subviews[index].place(at: CGPoint(x: bounds.minX + frame.minX, y: bounds.minY + frame.minY),
                                 anchor: .topLeading, proposal: ProposedViewSize(frame.size))
        }
    }

    private func arrangement(width: CGFloat, subviews: Subviews) -> (size: CGSize, frames: [CGRect]) {
        var frames: [CGRect] = []
        var x: CGFloat = 0, y: CGFloat = 0, rowHeight: CGFloat = 0, measuredWidth: CGFloat = 0
        for subview in subviews {
            let ideal = subview.sizeThatFits(.unspecified)
            let size = ideal.width > width ? subview.sizeThatFits(ProposedViewSize(width: width, height: nil)) : ideal
            if x > 0 && x + size.width > width {
                x = 0; y += rowHeight + WegoTokens.Space.small; rowHeight = 0
            }
            frames.append(CGRect(origin: CGPoint(x: x, y: y), size: size))
            measuredWidth = max(measuredWidth, x + size.width)
            x += size.width + WegoTokens.Space.small
            rowHeight = max(rowHeight, size.height)
        }
        return (CGSize(width: measuredWidth, height: y + rowHeight), frames)
    }
}
