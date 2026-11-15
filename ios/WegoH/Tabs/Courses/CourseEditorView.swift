import SwiftUI

struct CourseEditorView: View {
    @Environment(SessionManager.self) private var session
    @Environment(\.dismiss) private var dismiss
    let account: AccountSession
    let api: any IPhoneCourseServing
    let onSaved: (CourseSaveReceipt) -> Void
    @State var draft: CourseDraft
    @State private var showsPlaces = false
    @State private var replacing: String?
    @State private var isSaving = false
    @State private var error: String?
    @State private var showsDiscard = false
    @State private var newTag = ""
    @State private var tagError: String?
    @FocusState private var titleFocused: Bool
    @FocusState private var descriptionFocused: Bool
    @FocusState private var tagFocused: Bool

    init(draft: CourseDraft, account: AccountSession, api: any IPhoneCourseServing,
         onSaved: @escaping (CourseSaveReceipt) -> Void) {
        _draft = State(initialValue: draft)
        self.account = account
        self.api = api
        self.onSaved = onSaved
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: WegoTokens.Space.large) {
                VStack(alignment: .leading, spacing: WegoTokens.Space.medium) {
                    sectionTitle("경로 정보")
                    VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
                        fieldLabel("경로 이름 · 필수", count: draft.pack.title.utf16.count, maximum: 100)
                        WegoField("경로 이름", text: $draft.pack.title, focus: $titleFocused,
                                  prompt: "예: 강릉 바다 드라이브", identifier: "courseTitle", showsTitle: false)
                            .submitLabel(.next)
                            .onSubmit { titleFocused = false; descriptionFocused = true }
                    }
                    VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
                        fieldLabel("경로 설명 · 필수", count: draft.pack.description.utf16.count, maximum: 500)
                        WegoField("경로 설명", text: $draft.pack.description, focus: $descriptionFocused,
                                  axis: .vertical, prompt: "어떤 장소를 함께 가는 경로인가요?",
                                  identifier: "courseDescription", showsTitle: false)
                    }
                }
                VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
                    sectionTitle("태그 \(draft.tags.count)/8")
                    Text("글자나 숫자로 시작하는 태그를 24자까지 입력해 주세요. 밑줄과 하이픈도 쓸 수 있어요.")
                        .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
                    ScrollView(.horizontal) {
                        HStack(spacing: WegoTokens.Space.small) {
                            ForEach(draft.tags, id: \.self) { tag in
                                Button { draft.tags.removeAll { $0 == tag } } label: {
                                    Label("#" + tag, systemImage: "xmark")
                                        .font(WegoTokens.Typography.caption.weight(.semibold))
                                        .padding(WegoTokens.Space.small)
                                        .background(WegoTokens.Palette.accentSoft, in: Capsule())
                                        .frame(minHeight: WegoTokens.Metrics.touchTarget)
                                }
                                .buttonStyle(.plain).accessibilityLabel("\(tag) 태그 삭제")
                                .accessibilityIdentifier("courseEditorTag-\(tag)")
                            }
                        }
                    }.scrollIndicators(.hidden)
                    HStack(spacing: WegoTokens.Space.small) {
                        WegoField("태그 입력", text: $newTag, focus: $tagFocused,
                                  identifier: "courseTagInput", showsTitle: false)
                            .textInputAutocapitalization(.never).autocorrectionDisabled()
                            .submitLabel(.done).onSubmit(addTag)
                        Button("추가", action: addTag)
                            .buttonStyle(.wego(.soft)).fixedSize(horizontal: true, vertical: false)
                            .disabled(newTag.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || draft.tags.count >= 8)
                            .accessibilityIdentifier("courseTagAdd")
                    }
                    if let tagError {
                        Text(tagError).font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.danger)
                            .accessibilityIdentifier("courseTagError")
                    }
                }
                VStack(alignment: .leading, spacing: WegoTokens.Space.compact) {
                    sectionTitle("장소 \(draft.pack.stops.count)/3")
                    WegoCard(.outlined, padding: 0) {
                      VStack(spacing: 0) {
                        if draft.pack.stops.isEmpty {
                            Text("아래에서 장소를 추가하면 여기에 표시돼요.")
                                .font(WegoTokens.Typography.body).foregroundStyle(WegoTokens.Palette.secondary)
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .padding(WegoTokens.Space.medium)
                                .accessibilityIdentifier("coursePlacesEmpty")
                        } else {
                            CourseRoutePreview(stops: draft.pack.stops, account: account, api: api,
                                               mapHeight: WegoTokens.Metrics.courseEditorMapHeight)
                        }
                        ForEach(Array(draft.pack.stops.enumerated()), id: \.element.id) { index, stop in
                            Divider().overlay(WegoTokens.Palette.divider)
                            HStack(alignment: .top, spacing: WegoTokens.Space.compact) {
                                CourseStopBadge(number: index + 1, isDestination: index == draft.pack.stops.count - 1)
                                VStack(alignment: .leading, spacing: WegoTokens.Space.xSmall) {
                                    Text(stop.name).font(WegoTokens.Typography.section)
                                    if let address = stop.address {
                                        Text(address).font(WegoTokens.Typography.caption)
                                            .foregroundStyle(WegoTokens.Palette.secondary)
                                    }
                                    Button { replacing = stop.id; showsPlaces = true } label: {
                                        Text("장소 변경").font(WegoTokens.Typography.label.weight(.semibold))
                                            .frame(minHeight: WegoTokens.Metrics.touchTarget, alignment: .leading)
                                            .contentShape(Rectangle())
                                    }
                                }
                                .frame(maxWidth: .infinity, alignment: .leading)
                                HStack(spacing: 0) {
                                    moveButton(stop: stop, index: index, offset: -1)
                                    moveButton(stop: stop, index: index, offset: 1)
                                    Button { draft.pack.stops.removeAll { $0.id == stop.id } } label: {
                                        Image(systemName: "trash").foregroundStyle(WegoTokens.Palette.danger)
                                            .frame(width: WegoTokens.Metrics.touchTarget, height: WegoTokens.Metrics.touchTarget)
                                    }
                                    .accessibilityLabel("\(stop.name) 삭제")
                                    .accessibilityIdentifier("courseRemove-\(index)")
                                }
                            }
                            .padding(WegoTokens.Space.medium)
                            .buttonStyle(.plain)
                        }
                        Divider().overlay(WegoTokens.Palette.divider)
                        Button { replacing = nil; showsPlaces = true } label: {
                            Label("추가하기", systemImage: "plus")
                                .font(WegoTokens.Typography.action).foregroundStyle(WegoTokens.Palette.accent)
                                .frame(maxWidth: .infinity, minHeight: WegoTokens.Metrics.primaryButtonHeight)
                                .background(WegoTokens.Palette.accentSoft)
                                .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        .disabled(draft.pack.stops.count >= 3)
                        .accessibilityLabel("장소 추가하기")
                        .accessibilityIdentifier("courseAddPlace")
                      }
                    }
                    .clipShape(RoundedRectangle(cornerRadius: WegoTokens.Radius.card))
                    Text("장소를 최대 3곳까지 추가하고 순서를 바꿀 수 있어요.")
                        .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
                        .padding(.horizontal, WegoTokens.Space.xSmall)
                }
                VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
                    WegoCard(.surface) {
                        Toggle("경로와 장소 정보를 제3자에게 제공하는 데 동의해요", isOn: $draft.rightsConfirmed)
                        .accessibilityIdentifier("courseRights")
                        .tint(WegoTokens.Palette.accent)
                    }
                    Text(draft.isEditing ? "저장하면 새 버전으로 바로 공개돼요. 이전 버전은 유지됩니다." : "저장하면 다른 사람이 볼 수 있는 공개 경로가 됩니다.")
                        .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
                        .padding(.horizontal, WegoTokens.Space.xSmall)
                }
                if let error {
                    Text(error).font(WegoTokens.Typography.label).foregroundStyle(WegoTokens.Palette.danger)
                        .accessibilityIdentifier("courseSaveError")
                }
            }
            .padding(.horizontal, WegoTokens.Space.screen)
            .padding(.vertical, WegoTokens.Space.compact)
        }
        .scrollBounceBehavior(.basedOnSize)
        .scrollDismissesKeyboard(.interactively)
        .font(WegoTokens.Typography.body)
        .background(WegoTokens.Palette.background)
        .foregroundStyle(WegoTokens.Palette.text)
        .toolbar(.visible, for: .navigationBar)
        .presentationCornerRadius(WegoTokens.Radius.sheet)
        .navigationTitle(draft.isEditing ? "경로 수정" : "경로 만들기")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItemGroup(placement: .keyboard) {
                if titleFocused || descriptionFocused || tagFocused {
                    Spacer()
                    Button("완료", action: dismissKeyboard)
                        .font(WegoTokens.Typography.action)
                        .frame(minHeight: WegoTokens.Metrics.touchTarget)
                        .accessibilityIdentifier("courseKeyboardDismiss")
                }
            }
            ToolbarItem(placement: .cancellationAction) {
                Button("취소") {
                    if draft.hasChanges { showsDiscard = true } else { dismiss() }
                }
                .disabled(isSaving)
                .accessibilityIdentifier("courseEditorCancel")
            }
        }
        .safeAreaInset(edge: .bottom) {
            VStack(spacing: WegoTokens.Space.small) {
                if let requirement = draft.saveRequirement {
                    Text(requirement)
                        .font(WegoTokens.Typography.caption)
                        .foregroundStyle(WegoTokens.Palette.secondary)
                        .accessibilityIdentifier("courseSaveRequirement")
                }
                Button { dismissKeyboard(); Task { await save() } } label: {
                    if isSaving { WegoButtonLoadingLabel("저장 중", onAccent: true) }
                    else { Text("저장하고 공개") }
                }
                .buttonStyle(.wego(.primary))
                .disabled(!draft.canSave || isSaving || session.phase != .signedIn)
                .accessibilityIdentifier("courseSave")
            }
            .padding(.horizontal, WegoTokens.Space.screen).padding(.vertical, WegoTokens.Space.small)
            .background(WegoTokens.Palette.background)
        }
        .interactiveDismissDisabled(draft.hasChanges || isSaving)
        .disabled(isSaving)
        .confirmationDialog("작성한 내용을 버릴까요?", isPresented: $showsDiscard, titleVisibility: .visible) {
            Button("버리기", role: .destructive) { dismiss() }
            Button("계속 작성", role: .cancel) { }
        }
        .sheet(isPresented: $showsPlaces) {
            NavigationStack {
                CoursePlaceSearchView(account: account, api: api) { place in
                    var stop = CourseStop(place: place)
                    if let replacing, let index = draft.pack.stops.firstIndex(where: { $0.id == replacing }) {
                        let old = draft.pack.stops[index]
                        stop.id = old.id
                        stop.radiusMeters = old.radiusMeters
                        if old.action.message != "\(old.name)에 도착했어요." { stop.action = old.action }
                        draft.pack.stops[index] = stop
                    } else if draft.pack.stops.count < 3 {
                        draft.pack.stops.append(stop)
                    }
                }
            }
        }
    }

    private func addTag() {
        guard draft.tags.count < 8 else { tagError = "태그는 최대 8개까지 추가할 수 있어요."; return }
        guard let tag = normalizedCourseTag(newTag) else {
            tagError = "글자나 숫자로 시작하는 태그를 24자까지 입력해 주세요."
            return
        }
        guard !draft.tags.contains(where: { courseTagKey($0) == courseTagKey(tag) }) else {
            tagError = "이미 추가한 태그예요."
            return
        }
        draft.tags.append(tag)
        newTag = ""
        tagError = nil
    }

    private func dismissKeyboard() {
        titleFocused = false
        descriptionFocused = false
        tagFocused = false
    }

    private func sectionTitle(_ title: String) -> some View {
        SectionHeader(title)
    }

    private func fieldLabel(_ title: String, count: Int, maximum: Int) -> some View {
        HStack(alignment: .firstTextBaseline) {
            Text(title).font(WegoTokens.Typography.caption)
            Spacer()
            Text("\(count)/\(maximum)")
                .font(WegoTokens.Typography.caption.monospacedDigit())
                .foregroundStyle(WegoTokens.Palette.secondary)
                .accessibilityLabel("최대 \(maximum)자 중 \(count)자 입력")
        }
    }

    private func moveButton(stop: CourseStop, index: Int, offset: Int) -> some View {
        Button { draft.pack.stops.swapAt(index, index + offset) } label: {
            Image(systemName: offset < 0 ? "arrow.up" : "arrow.down")
                .foregroundStyle(WegoTokens.Palette.secondary)
                .frame(width: WegoTokens.Metrics.touchTarget, height: WegoTokens.Metrics.touchTarget)
        }
        .disabled(!(draft.pack.stops.indices).contains(index + offset))
        .accessibilityLabel("\(stop.name) \(offset < 0 ? "위로" : "아래로")")
    }

    private func save() async {
        guard !isSaving, draft.canSave else { return }
        isSaving = true
        error = nil
        defer { isSaving = false }
        do {
            let saved = try await session.withToken(for: account) { try await api.save(draft, token: $0) }
            onSaved(saved)
            dismiss()
        } catch is CancellationError { }
        catch { if session.current == account { self.error = courseErrorMessage(error) } }
    }
}
