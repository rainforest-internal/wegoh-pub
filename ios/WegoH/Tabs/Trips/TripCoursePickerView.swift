import SwiftUI

struct TripCoursePickerView: View {
    private struct Choice: Identifiable {
        let id: String
        let title: String
        let subtitle: String
        let available: Bool
    }

    let store: TripPreparationStore
    var api: any IPhoneCourseServing = IPhoneCourseAPI()
    var startCreating = false
    @Environment(SessionManager.self) private var session
    @Environment(\.dismiss) private var dismiss
    @State private var choices: [Choice] = []
    @State private var selected: Set<String> = []
    @State private var savedAdditions: Set<String> = []
    @State private var draft: CourseDraft?
    @State private var beganCreation = false
    @State private var loading = true
    @State private var adding = false
    @State private var message: String?
    @State private var requestID = UUID()

    private var existing: Set<String> { Set(store.detail?.courses.map(\.id) ?? []).union(savedAdditions) }
    private var remaining: Int { max(0, 10 - existing.count) }
    private var writable: Bool { store.accountIsCurrent && !store.busy && !store.needsRefresh && !adding }

    var body: some View {
        Group {
            if store.accountIsCurrent { pickerContent }
            else { Text("로그인을 다시 확인해 주세요.").font(WegoTokens.Typography.label) }
        }
    }

    private var pickerContent: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: WegoTokens.Space.large) {
                Button {
                    guard !store.isPreview, let account = session.current else { return }
                    draft = CourseDraft(author: account.displayName)
                } label: {
                    WegoRow(systemImage: "plus", title: "새 경로 만들기",
                            subtitle: "저장하면 이 여행에 바로 추가해요")
                        .padding(WegoTokens.Space.medium)
                        .overlay {
                            RoundedRectangle(cornerRadius: WegoTokens.Radius.card)
                                .strokeBorder(WegoTokens.Palette.divider,
                                              style: StrokeStyle(lineWidth: WegoTokens.Metrics.hairlineWidth,
                                                                 dash: [WegoTokens.Space.xSmall, WegoTokens.Metrics.timelineWidth]))
                        }
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain).disabled(!writable || store.isPreview || remaining == 0)
                .accessibilityIdentifier("tripCourseCreate")
                if store.isPreview {
                    Text("미리보기에서는 실제 경로를 만들거나 저장하지 않아요.")
                        .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
                }
                SectionHeader(choices.isEmpty && (loading || message != nil) ? "내가 만든 경로" : "내가 만든 경로 \(choices.count)")
                if loading { WegoLoadingView("내 경로를 불러오는 중", layout: choices.isEmpty ? .list : .row) }
                if let message {
                    if choices.isEmpty && !loading {
                        WegoLoadingFailureView(message: message, messageIdentifier: "tripCoursePickerMessage") { Task { await load() } }
                    } else {
                        Text(message).font(WegoTokens.Typography.label)
                            .foregroundStyle(WegoTokens.Palette.danger)
                            .accessibilityIdentifier("tripCoursePickerMessage")
                    }
                }
                if store.needsRefresh {
                    WegoCard(.surface) {
                        VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
                            Text("추가한 경로를 확인한 뒤 나머지를 이어갈 수 있어요.").font(WegoTokens.Typography.label)
                            Button("여행 다시 불러오기") {
                                Task { await store.load(); await load() }
                            }.buttonStyle(.wego(.soft)).disabled(adding || store.busy)
                        }
                    }
                }
                ForEach(choices) { choice in
                    let included = existing.contains(choice.id)
                    let chosen = selected.contains(choice.id)
                    Button {
                        if chosen { selected.remove(choice.id) }
                        else if selected.count < remaining { selected.insert(choice.id) }
                    } label: {
                        WegoCard(included || !choice.available ? .surface : .outlined) {
                            HStack(spacing: WegoTokens.Space.compact) {
                                VStack(alignment: .leading, spacing: WegoTokens.Space.xSmall) {
                                    Text(choice.title).font(WegoTokens.Typography.section)
                                    Text(choice.subtitle).font(WegoTokens.Typography.caption)
                                        .foregroundStyle(WegoTokens.Palette.secondary)
                                }
                                .frame(maxWidth: .infinity, alignment: .leading)
                                if included { StatusPill("추가됨") }
                                else if !choice.available { StatusPill("공개 중지") }
                                else {
                                    Image(systemName: chosen ? "checkmark.circle.fill" : "circle")
                                        .foregroundStyle(chosen ? WegoTokens.Palette.accent : WegoTokens.Palette.secondary)
                                        .accessibilityHidden(true)
                                }
                            }
                        }
                        .overlay {
                            if chosen {
                                RoundedRectangle(cornerRadius: WegoTokens.Radius.card)
                                    .strokeBorder(WegoTokens.Palette.accent, lineWidth: WegoTokens.Metrics.selectedBorderWidth)
                            }
                        }
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .disabled(!writable || included || !choice.available || (!chosen && selected.count >= remaining))
                    .accessibilityAddTraits(chosen ? .isSelected : [])
                    .accessibilityIdentifier("tripCourseChoice-" + choice.id)
                }
                if !loading && choices.isEmpty && message == nil {
                    Text("아직 만든 경로가 없어요. 새 경로를 만들어 이 여행에 추가해 보세요.")
                        .font(WegoTokens.Typography.label).foregroundStyle(WegoTokens.Palette.secondary)
                }
                Text("여행에는 경로를 최대 10개까지 추가할 수 있어요. 고른 순서대로 추가하고, 일부만 추가되면 남은 경로부터 이어갈 수 있어요.")
                    .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
            }
            .padding(WegoTokens.Space.screen)
        }
        .background(WegoTokens.Palette.background).foregroundStyle(WegoTokens.Palette.text)
        .navigationTitle("내 경로에서 추가").navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .cancellationAction) {
                Button("취소") { dismiss() }.disabled(adding)
            }
            ToolbarItem(placement: .topBarTrailing) {
                Button("새로고침") { Task { await load() } }.disabled(loading || adding)
            }
        }
        .safeAreaInset(edge: .bottom) {
            Button { Task { await addSelected() } } label: {
                if adding { WegoButtonLoadingLabel("경로 추가 중…", onAccent: true) }
                else { Text("경로 \(selected.count)개 추가") }
            }
                .buttonStyle(.wego(.primary))
                .disabled(!writable || loading || selected.isEmpty || selected.count > remaining)
                .accessibilityIdentifier("tripCourseAddSelected")
                .padding(WegoTokens.Space.screen).background(WegoTokens.Palette.background)
        }
        .interactiveDismissDisabled(adding)
        .task(id: session.current?.accountID) {
            await load()
            if startCreating, !beganCreation, !store.isPreview, writable, remaining > 0,
               let account = session.current {
                beganCreation = true
                draft = CourseDraft(author: account.displayName)
            }
        }
        .onChange(of: session.current?.accountID) { _, _ in if !store.accountIsCurrent { dismiss() } }
        .onDisappear { requestID = UUID() }
        .onChange(of: existing) { _, included in selected.subtract(included) }
        .sheet(item: $draft) { value in
            if let account = session.current, store.accountIsCurrent, !store.isPreview {
                NavigationStack {
                    CourseEditorView(draft: value, account: account, api: api) { receipt in
                        guard session.current == account, store.accountIsCurrent else { draft = nil; return }
                        requestID = UUID()
                        loading = false
                        draft = nil
                        let choice = Choice(id: receipt.id, title: receipt.pack.title,
                                            subtitle: "장소 \(receipt.pack.stops.count)곳 · v\(receipt.version)",
                                            available: receipt.state == "approved")
                        choices.removeAll { $0.id == choice.id }
                        choices.insert(choice, at: 0)
                        if choice.available {
                            selected.insert(choice.id)
                            Task { await addSelected(ids: [choice.id]) }
                        } else { message = "저장한 경로는 공개 중지 상태여서 여행에 추가하지 않았어요." }
                    }
                }
            }
        }
    }

    private func load() async {
        guard !adding, store.accountIsCurrent else { return }
        let stamp = UUID()
        requestID = stamp
        loading = true
        message = nil
        defer { if requestID == stamp { loading = false } }
        if store.isPreview {
            choices = store.previewAvailableCourses.map {
                Choice(id: $0.id, title: $0.title, subtitle: "샘플 경로 · 장소 \($0.stopCount)곳", available: true)
            }
            selected.subtract(existing)
            return
        }
        guard let account = session.current else { choices = []; selected = []; return }
        do {
            let result = try await session.withToken(for: account) { try await api.list(token: $0) }
            guard requestID == stamp, session.current == account, store.accountIsCurrent else { return }
            choices = result.map { Choice(id: $0.id, title: $0.title,
                                         subtitle: "장소 \($0.stopCount)곳 · v\($0.version)", available: $0.state == "approved") }
            selected.formIntersection(Set(choices.filter(\.available).map(\.id)))
            selected.subtract(existing)
        } catch is CancellationError { }
        catch {
            guard requestID == stamp, store.accountIsCurrent else { return }
            choices = []
            selected = []
            message = tripPreparationErrorMessage(error)
        }
    }

    private func addSelected(ids: [String]? = nil) async {
        guard writable else { return }
        selected.subtract(existing)
        let pending = (ids ?? choices.filter { selected.contains($0.id) }.map(\.id)).filter { !existing.contains($0) }
        guard !pending.isEmpty, pending.count <= remaining else { return }
        adding = true
        message = nil
        defer { adding = false }
        var completed = 0
        for id in pending {
            do {
                try await store.addCourse(packID: id)
                savedAdditions.insert(id)
                selected.remove(id)
                completed += 1
                if store.needsRefresh {
                    message = "\(completed)개는 추가했지만 최신 여행 정보를 확인하지 못했어요. 다시 불러온 뒤 나머지를 추가해 주세요."
                    return
                }
            } catch {
                message = completed == 0 ? tripPreparationErrorMessage(error)
                    : "\(completed)개를 추가했고 나머지는 추가하지 못했어요. " + tripPreparationErrorMessage(error)
                return
            }
        }
        if selected.isEmpty { dismiss() }
    }
}
