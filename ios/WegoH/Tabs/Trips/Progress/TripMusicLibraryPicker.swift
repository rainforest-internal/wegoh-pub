import SwiftUI

enum TripMusicAddMode: String, CaseIterable, Identifiable {
    case library, link
    var id: Self { self }
    var label: String {
        switch self {
        case .library: "내 플레이리스트"
        case .link: "링크 입력"
        }
    }
}

/// 계정의 내 플레이리스트에 저장한 곡을 골라 제목·링크를 다시 입력하지 않고 여행 플레이리스트에 추가한다.
struct TripMusicLibraryPicker: View {
    @Bindable var store: TripMusicStore
    let page: IPhoneTripMusicPage
    let onLink: () -> Void

    var body: some View {
        let choices = store.savedChoices
        VStack(alignment: .leading, spacing: WegoTokens.Space.medium) {
            if store.library == nil {
                if store.libraryFailed {
                    WegoCard(.outlined) {
                        Text("내 플레이리스트를 불러오지 못했어요.").font(WegoTokens.Typography.body)
                        Button("다시 불러오기") { Task { await store.loadLibrary() } }
                            .buttonStyle(.wego(.soft)).disabled(store.libraryLoading)
                            .accessibilityIdentifier("tripMusicLibraryReload")
                    }
                } else {
                    WegoLoadingView("내 플레이리스트를 불러오는 중", layout: .row)
                }
            } else if choices.isEmpty {
                WegoCard(.outlined) {
                    Text("내 플레이리스트에 저장한 곡이 없어요").font(WegoTokens.Typography.section)
                    Text("음악 탭에서 저장한 곡은 여기서 바로 고를 수 있어요.")
                        .font(WegoTokens.Typography.label).foregroundStyle(WegoTokens.Palette.secondary)
                    Button("링크 직접 입력", action: onLink).buttonStyle(.wego(.soft))
                        .accessibilityIdentifier("tripMusicLibraryUseLink")
                }.accessibilityIdentifier("tripMusicLibraryEmpty")
            } else {
                SectionHeader("내 플레이리스트 \(choices.count)곡")
                ForEach(choices) { choice in row(choice) }
                WegoCard(.outlined) {
                    Toggle("제목과 링크를 공유할 권리가 있어요", isOn: $store.savedRightsConfirmed)
                        .font(WegoTokens.Typography.body)
                        .frame(minHeight: WegoTokens.Metrics.touchTarget).accessibilityIdentifier("tripMusicSavedRights")
                    Text("추가하면 공유 검토를 거쳐 일행에게 보이고, 차 화면의 노래 듣기에도 함께 보여요.")
                        .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
                    Button { Task { await store.addSaved() } } label: {
                        Text(store.busy ? "처리 중…" : "여행에 추가")
                            .frame(maxWidth: .infinity, minHeight: WegoTokens.Metrics.primaryButtonHeight)
                    }.buttonStyle(WegoPrimaryButtonStyle()).disabled(!store.canAddSaved)
                        .accessibilityIdentifier("tripMusicSavedAdd")
                    if !page.canAdd { Text("여행 음악 목록이 가득 찼어요.").font(WegoTokens.Typography.caption) }
                }
            }
        }
        .disabled(store.busy)
    }

    private func row(_ choice: TripMusicSavedChoice) -> some View {
        let selected = store.savedSelection == choice.selection
        let detail = choice.playlistName == choice.title ? choice.platform.label : "\(choice.platform.label) · \(choice.playlistName)"
        return Button { store.savedSelection = selected ? nil : choice.selection } label: {
            HStack(spacing: WegoTokens.Space.small) {
                VStack(alignment: .leading, spacing: WegoTokens.Space.xSmall) {
                    Text(choice.title).font(WegoTokens.Typography.section)
                    Text(choice.alreadyAdded ? detail + " · 이미 추가함" : detail)
                        .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
                }
                Spacer(minLength: WegoTokens.Space.small)
                Image(systemName: choice.alreadyAdded || selected ? "checkmark.circle.fill" : "circle")
                    .font(WegoTokens.Typography.cardTitle).foregroundStyle(WegoTokens.Palette.accent).accessibilityHidden(true)
            }
            .frame(maxWidth: .infinity, minHeight: WegoTokens.Metrics.touchTarget)
            .padding(WegoTokens.Space.medium)
            .background(WegoTokens.Palette.surface, in: RoundedRectangle(cornerRadius: WegoTokens.Radius.control))
            .overlay {
                RoundedRectangle(cornerRadius: WegoTokens.Radius.control)
                    .strokeBorder(selected ? WegoTokens.Palette.accent : .clear, lineWidth: WegoTokens.Metrics.selectedBorderWidth)
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain).disabled(choice.alreadyAdded)
        .accessibilityLabel("\(choice.title), \(detail)")
        .accessibilityValue(choice.alreadyAdded ? "이미 추가함" : selected ? "선택됨" : "선택 안 됨")
        .accessibilityIdentifier("tripMusicSaved-" + choice.id)
    }
}
