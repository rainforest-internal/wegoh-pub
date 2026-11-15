import SwiftUI

struct TripCompletedLiveContent: View {
    let preparation: TripPreparationStore
    let model: TripCompletedModel
    var versus: TripDrivingVersusSummary? = nil
    var api = IPhoneTripHistoryAPI()
    @State private var sheet: Destination?
    private enum Destination: String, Identifiable { case share, history; var id: Self { self } }
    var body: some View {
        if model.isPreview { TripCompletedContent(model: model, versus: versus) }
        else {
            TripCompletedContent(model: model, versus: versus,
                                 shareCourse: { sheet = .share }, openRecord: { sheet = .history })
                .sheet(item: $sheet) { destination in
                    NavigationStack {
                        if !preparation.accountIsCurrent { Text("로그인을 다시 확인해 주세요.").font(WegoTokens.Typography.label) }
                        else if destination == .share { TripCompletedShareView(preparation: preparation, api: api) }
                        else { TripCompletedRecordView(preparation: preparation, api: api) }
                    }
                }
        }
    }
}

private struct TripCompletedShareView: View {
    let preparation: TripPreparationStore
    let api: IPhoneTripHistoryAPI
    @Environment(SessionManager.self) private var session
    @Environment(\.dismiss) private var dismiss
    @State private var options: IPhoneTripCourseDraftOptions?
    @State private var selection: Set<String> = []
    @State private var draft: CourseDraft?
    @State private var busy = false
    @State private var message: String?
    @State private var saved = false
    @State private var makingDraft = false
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: WegoTokens.Space.medium) {
                Text("공유 경로의 장소만 골라 새 경로로 다듬어요. 각자의 타는 곳·내리는 곳은 포함하지 않아요.")
                    .font(WegoTokens.Typography.body)
                if busy && !makingDraft { WegoLoadingView("공유 경로 확인 중", layout: options == nil ? .list : .row) }
                if let options {
                    if options.places.isEmpty { Text("지금 가져올 수 있는 공유 경로 장소가 없어요.").font(WegoTokens.Typography.label) }
                    ForEach(options.places) { place in
                        Button {
                            if selection.contains(place.id) { selection.remove(place.id) }
                            else if selection.count < 3 { selection.insert(place.id) }
                        } label: {
                            HStack(spacing: WegoTokens.Space.small) {
                                Image(systemName: selection.contains(place.id) ? "checkmark.circle.fill" : "circle")
                                VStack(alignment: .leading, spacing: WegoTokens.Space.xSmall) {
                                    Text(place.name).font(WegoTokens.Typography.section)
                                    if !place.canReuse { Text("원저자의 재사용 허용이 필요해요").font(WegoTokens.Typography.caption) }
                                }
                                Spacer()
                            }.frame(minHeight: WegoTokens.Metrics.touchTarget)
                        }.buttonStyle(.wego(.plain)).disabled(busy || !place.canReuse || (!selection.contains(place.id) && selection.count >= 3))
                            .accessibilityValue(selection.contains(place.id) ? "선택됨" : "선택 안 됨")
                    }
                    Text("최대 3곳 · 선택한 순서는 원래 공유 경로의 순서를 따라요.").font(WegoTokens.Typography.caption)
                    Button { Task { await makeDraft(options) } } label: {
                        if makingDraft { WegoButtonLoadingLabel("경로로 다듬는 중…", onAccent: true) }
                        else { Text("선택한 \(selection.count)곳으로 다듬기") }
                    }
                        .buttonStyle(.wego(.primary)).disabled(selection.isEmpty || busy || saved)
                        .accessibilityIdentifier("tripShareSelectedCourses")
                }
                if saved { Text("내 경로로 저장했어요.").font(WegoTokens.Typography.section) }
                if let message {
                    if options == nil && !busy { WegoLoadingFailureView(message: message) { Task { await load() } } }
                    else {
                        Text(message).font(WegoTokens.Typography.label).foregroundStyle(WegoTokens.Palette.danger)
                        Button("다시 불러오기") { Task { await load() } }.disabled(busy)
                    }
                }
            }.padding(WegoTokens.Space.screen)
        }.foregroundStyle(WegoTokens.Palette.text).background(WegoTokens.Palette.background)
            .navigationTitle("경로로 다듬어 공유").navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("닫기") { dismiss() }.disabled(busy) } }
            .interactiveDismissDisabled(busy)
            .task { await load() }
            .sheet(item: $draft) { draft in
                if let account = session.current, preparation.accountIsCurrent {
                    NavigationStack { CourseEditorView(draft: draft, account: account, api: IPhoneCourseAPI()) { _ in saved = true; selection = [] } }
                }
            }
    }
    private func load() async {
        guard !busy, let id = preparation.detail?.id, preparation.accountIsCurrent else { return }
        busy = true; message = nil; selection = []
        defer { busy = false }
        do { options = try await preparation.activityRequest { try await api.draftOptions(id, token: $0) } }
        catch is CancellationError { }
        catch {
            if tripActivityAccessLost(error) { options = nil }
            message = tripPreparationErrorMessage(error)
        }
    }
    private func makeDraft(_ options: IPhoneTripCourseDraftOptions) async {
        guard !busy, let id = preparation.detail?.id, preparation.accountIsCurrent, let account = session.current else { return }
        busy = true; makingDraft = true; message = nil
        defer { busy = false; makingDraft = false }
        do {
            let receipt = try await preparation.activityRequest { try await api.createDraft(id, options: options, selection: selection, token: $0) }
            draft = CourseDraft(copy: receipt, author: account.displayName)
        } catch is CancellationError { }
        catch { message = tripPreparationErrorMessage(error) }
    }
}

private struct TripCompletedRecordView: View {
    let preparation: TripPreparationStore
    let api: IPhoneTripHistoryAPI
    @Environment(\.dismiss) private var dismiss
    @State private var results: IPhoneTripResults?
    @State private var record: IPhoneTripSavedHistory?
    @State private var busy = false
    @State private var savedReceipt: IPhoneTripHistoryReceipt?
    @State private var savingHistory = false
    @State private var message: String?
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: WegoTokens.Space.medium) {
                if busy && !savingHistory { WegoLoadingView("여행 기록 확인 중", layout: results == nil ? .detail : .row) }
                if preparation.accountIsCurrent, let results {
                    WegoCard(.ink) {
                        Text(record?.title ?? results.summary?.title ?? preparation.detail?.title ?? "여행 기록")
                            .font(WegoTokens.Typography.cardTitle)
                        Text("시작 \(results.ownPeriod.startedAt)").font(WegoTokens.Typography.caption)
                        if let end = results.ownPeriod.endedAt { Text("종료 \(end)").font(WegoTokens.Typography.caption) }
                        if results.startTimeEstimated { Text("이전 여행의 추정 시작 시각이에요.").font(WegoTokens.Typography.caption) }
                    }
                    if let record {
                        SectionHeader("저장한 방문 기록")
                        if record.visits.isEmpty { Text("저장된 방문 기록이 없어요.").font(WegoTokens.Typography.label) }
                        ForEach(record.visits) { visit in
                            WegoRow(systemImage: "mappin.circle", title: visit.place.name, subtitle: visit.visitedAt)
                        }
                    } else if savedReceipt == nil && results.history == nil {
                        Button { Task { await save() } } label: {
                            if savingHistory { WegoButtonLoadingLabel("여행 기록 저장 중…", onAccent: true) }
                            else { Text("여행 기록 저장") }
                        }.buttonStyle(.wego(.primary)).disabled(busy)
                            .accessibilityIdentifier("tripSaveHistory")
                    }
                    if savedReceipt != nil && record == nil { Text("기록은 저장됐어요. 다시 불러오면 저장된 내용을 확인할 수 있어요.").font(WegoTokens.Typography.label) }
                }
                if let message {
                    if results == nil && !busy { WegoLoadingFailureView(message: message) { Task { await load() } } }
                    else { Text(message).font(WegoTokens.Typography.label).foregroundStyle(WegoTokens.Palette.danger) }
                }
                Button("다시 불러오기") { Task { await load() } }.disabled(busy)
            }.padding(WegoTokens.Space.screen)
        }.foregroundStyle(WegoTokens.Palette.text).background(WegoTokens.Palette.background)
            .navigationTitle("여행 기록").navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("닫기") { dismiss() }.disabled(busy) } }
            .interactiveDismissDisabled(busy).task { await load() }
    }
    private func load() async {
        guard !busy, let id = preparation.detail?.id, preparation.accountIsCurrent else { return }
        busy = true; message = nil
        defer { busy = false }
        do {
            results = try await preparation.activityRequest { try await api.results(id, token: $0) }
            if results?.history == nil && savedReceipt == nil { record = nil }
            if results?.history != nil || savedReceipt != nil { record = try await preparation.activityRequest { try await api.history(id, token: $0) } }
        } catch is CancellationError { }
        catch {
            if tripActivityAccessLost(error) { record = nil; results = nil }
            message = tripPreparationErrorMessage(error)
        }
    }
    private func save() async {
        guard !busy, savedReceipt == nil, let detail = preparation.detail, preparation.accountIsCurrent else { return }
        busy = true; savingHistory = true; message = nil
        defer { busy = false; savingHistory = false }
        do {
            savedReceipt = try await preparation.activityRequest { try await api.saveHistory(detail.id, title: detail.title, token: $0) }
            record = try await preparation.activityRequest { try await api.history(detail.id, token: $0) }
        } catch is CancellationError { }
        catch { message = tripPreparationErrorMessage(error) }
    }
}
