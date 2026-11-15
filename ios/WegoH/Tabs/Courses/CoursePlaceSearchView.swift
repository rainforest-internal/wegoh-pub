import SwiftUI

struct CoursePlaceSearchView: View {
    @Environment(SessionManager.self) private var session
    @Environment(\.dismiss) private var dismiss
    let account: AccountSession
    let api: any IPhoneCourseServing
    let onSelect: (CoursePlace) -> Void
    @State private var query = ""
    @State private var places: [CoursePlace] = []
    @State private var selected: CoursePlace?
    @State private var isSearching = false
    @State private var hasSearched = false
    @State private var error: String?
    @State private var searchTask: Task<Void, Never>?
    @State private var read = UUID()
    @FocusState private var searchFocused: Bool

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: WegoTokens.Space.large) {
                HStack(spacing: WegoTokens.Space.small) {
                    TextField("장소 이름 또는 주소", text: $query)
                        .font(WegoTokens.Typography.body)
                        .focused($searchFocused)
                        .submitLabel(.search)
                        .onSubmit { search() }
                        .accessibilityLabel("장소 이름 또는 주소")
                        .accessibilityIdentifier("coursePlaceQuery")
                        .padding(.horizontal, WegoTokens.Space.medium)
                        .padding(.vertical, WegoTokens.Space.compact)
                        .frame(minHeight: WegoTokens.Metrics.primaryButtonHeight)
                        .background(WegoTokens.Palette.background, in: RoundedRectangle(cornerRadius: WegoTokens.Radius.control))
                        .overlay {
                            RoundedRectangle(cornerRadius: WegoTokens.Radius.control)
                                .strokeBorder(searchFocused ? WegoTokens.Palette.accent : WegoTokens.Palette.divider,
                                              lineWidth: searchFocused ? WegoTokens.Metrics.selectedBorderWidth : WegoTokens.Metrics.hairlineWidth)
                        }
                    Button { search() } label: {
                        Image(systemName: "magnifyingglass").font(WegoTokens.Typography.section)
                            .frame(width: WegoTokens.Metrics.primaryButtonHeight, height: WegoTokens.Metrics.primaryButtonHeight)
                    }
                    .buttonStyle(WegoPrimaryButtonStyle())
                    .disabled(!validQuery || isSearching)
                    .accessibilityLabel("장소 검색")
                    .accessibilityIdentifier("coursePlaceSearch")
                }
                if let selected {
                    VStack(alignment: .leading, spacing: WegoTokens.Space.compact) {
                        sectionTitle("선택한 장소")
                        VStack(spacing: 0) {
                            CourseMapPreview(stops: [CourseStop(place: selected)])
                                .frame(height: WegoTokens.Metrics.placeMapHeight)
                            Divider().overlay(WegoTokens.Palette.divider)
                            VStack(alignment: .leading, spacing: WegoTokens.Space.xSmall) {
                                Text(selected.name).font(WegoTokens.Typography.section)
                                Text(selected.displayAddress).font(WegoTokens.Typography.label)
                                    .foregroundStyle(WegoTokens.Palette.secondary)
                            }
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(WegoTokens.Space.medium)
                        }
                        .clipShape(RoundedRectangle(cornerRadius: WegoTokens.Radius.card))
                        .overlay { RoundedRectangle(cornerRadius: WegoTokens.Radius.card).strokeBorder(WegoTokens.Palette.divider) }
                    }
                }
                VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
                    sectionTitle("검색 결과")
                    if isSearching { WegoLoadingView("장소를 찾는 중", layout: .row) }
                    if let error {
                        VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
                            Text(error).font(WegoTokens.Typography.label).foregroundStyle(WegoTokens.Palette.danger)
                                .accessibilityIdentifier("coursePlaceError")
                            Button("다시 검색", action: search)
                                .frame(minHeight: WegoTokens.Metrics.touchTarget)
                                .disabled(isSearching || !validQuery)
                                .accessibilityIdentifier("coursePlaceRetry")
                        }
                    }
                    if hasSearched && places.isEmpty && error == nil && !isSearching {
                        Text("검색 결과가 없어요. 다른 이름이나 주소로 찾아보세요.")
                            .font(WegoTokens.Typography.label).foregroundStyle(WegoTokens.Palette.secondary)
                    }
                    VStack(spacing: 0) {
                        ForEach(places) { place in
                            Button { searchFocused = false; selected = place } label: {
                                HStack(spacing: WegoTokens.Space.medium) {
                                    VStack(alignment: .leading, spacing: WegoTokens.Space.xSmall) {
                                        Text(place.name).font(WegoTokens.Typography.section)
                                            .foregroundStyle(WegoTokens.Palette.text)
                                        Text(place.displayAddress).font(WegoTokens.Typography.label)
                                            .foregroundStyle(WegoTokens.Palette.secondary)
                                    }
                                    .fixedSize(horizontal: false, vertical: true)
                                    .frame(maxWidth: .infinity, alignment: .leading)
                                    ZStack {
                                        if selected?.id == place.id {
                                            Circle().fill(WegoTokens.Palette.accent)
                                            Image(systemName: "checkmark").font(WegoTokens.Typography.label.weight(.semibold))
                                                .foregroundStyle(WegoTokens.Palette.onAccent)
                                        } else {
                                            Circle().strokeBorder(WegoTokens.Palette.divider, lineWidth: WegoTokens.Metrics.selectedBorderWidth)
                                        }
                                    }
                                    .frame(width: WegoTokens.Metrics.coursePlaceSelectionSize, height: WegoTokens.Metrics.coursePlaceSelectionSize)
                                    .accessibilityHidden(true)
                                }
                                .frame(minHeight: WegoTokens.Metrics.touchTarget)
                                .padding(.vertical, WegoTokens.Space.compact)
                                .contentShape(Rectangle())
                            }
                            .buttonStyle(.plain)
                            .accessibilityAddTraits(selected?.id == place.id ? .isSelected : [])
                            .accessibilityIdentifier("coursePlace-\(place.id)")
                            if place.id != places.last?.id { Divider().overlay(WegoTokens.Palette.divider) }
                        }
                    }
                    if !hasSearched && !isSearching {
                        Text("장소 이름이나 주소를 2자 이상 입력해 주세요.")
                            .font(WegoTokens.Typography.label).foregroundStyle(WegoTokens.Palette.secondary)
                    }
                }
            }
            .padding(.horizontal, WegoTokens.Space.screen)
            .padding(.vertical, WegoTokens.Space.small)
        }
        .scrollBounceBehavior(.basedOnSize)
        .background(WegoTokens.Palette.background)
        .foregroundStyle(WegoTokens.Palette.text)
        .navigationTitle("장소 추가")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .cancellationAction) { Button("취소") { dismiss() } }
        }
        .safeAreaInset(edge: .bottom) {
            Button {
                if let selected { onSelect(selected); dismiss() }
            } label: {
                Text("추가").font(WegoTokens.Typography.action)
                    .foregroundStyle(WegoTokens.Palette.onAccent)
                    .padding(.vertical, WegoTokens.Space.compact)
                    .frame(maxWidth: .infinity, minHeight: WegoTokens.Metrics.primaryButtonHeight)
            }
            .buttonStyle(WegoPrimaryButtonStyle())
            .disabled(selected == nil)
            .accessibilityIdentifier("coursePlaceAdd")
            .padding(.horizontal, WegoTokens.Space.screen)
            .padding(.vertical, WegoTokens.Space.small)
            .background(WegoTokens.Palette.background)
        }
        .presentationCornerRadius(WegoTokens.Radius.sheet)
        .onChange(of: query) { _, _ in
            searchTask?.cancel(); read = UUID(); isSearching = false
            places = []; selected = nil; hasSearched = false; error = nil
        }
        .onDisappear { searchTask?.cancel() }
    }

    private func sectionTitle(_ title: String) -> some View {
        Text(title).font(WegoTokens.Typography.label.weight(.semibold))
            .foregroundStyle(WegoTokens.Palette.secondary).accessibilityAddTraits(.isHeader)
    }

    private var validQuery: Bool { (2...60).contains(query.trimmingCharacters(in: .whitespacesAndNewlines).count) }

    private func search() {
        guard validQuery else { return }
        searchFocused = false
        searchTask?.cancel()
        let stamp = UUID(), text = query
        read = stamp; isSearching = true; hasSearched = true; selected = nil; error = nil
        searchTask = Task {
            defer { if read == stamp { isSearching = false } }
            do {
                let results = try await session.withToken(for: account) { try await api.search(text, token: $0) }
                guard read == stamp else { return }
                places = results; hasSearched = true
            } catch is CancellationError { }
            catch { if read == stamp && session.current == account { self.error = placeSearchErrorMessage(error) } }
        }
    }
}

func placeSearchErrorMessage(_ error: Error) -> String {
    switch error {
    case IPhoneResourceError.unavailable, IPhoneSessionError.unavailable:
        "장소 검색을 사용할 수 없어요. 입력한 검색어로 다시 시도해 주세요."
    case IPhoneResourceError.invalidInput:
        "장소 이름이나 주소를 2~60자로 입력해 주세요."
    case IPhoneSessionError.forbidden:
        "장소 검색 권한을 확인할 수 없어요. 다시 로그인해 주세요."
    default: courseErrorMessage(error)
    }
}
