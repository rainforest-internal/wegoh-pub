import SwiftUI

struct TripManagementView: View {
    let store: TripPreparationStore
    @Environment(\.dismiss) private var dismiss
    @State private var confirmation: ManagementAction?
    @State private var editingTrip = false
    @State private var editingCar: IPhoneTripCar?
    @State private var message: String?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: WegoTokens.Space.medium) {
                if let detail = store.detail, store.accountIsCurrent {
                    Group {
                    if detail.isOwner || detail.myPermissions.edit {
                        WegoCard(.surface) {
                            Button("여행 이름·설명·날짜 고치기") { editingTrip = true }
                                .frame(minHeight: WegoTokens.Metrics.touchTarget)
                        }
                    }
                    if detail.state == .planned {
                        SectionHeader("차량")
                        ForEach(detail.cars.filter { $0.isMine || detail.isOwner }) { car in
                            WegoCard(.outlined) {
                                Text(detail.numberedName(car)).font(WegoTokens.Typography.section)
                                Text("운전자 \(car.driverName) · 동승 자리 \(car.seats)명").font(WegoTokens.Typography.caption)
                                HStack {
                                    if car.isMine { Button("차 이름·자리 고치기") { editingCar = car } }
                                    Spacer()
                                    Button("차 삭제", role: .destructive) { confirmation = .car(car.id) }
                                }.frame(minHeight: WegoTokens.Metrics.touchTarget)
                            }
                        }
                        if detail.isOwner || detail.myPermissions.edit {
                            SectionHeader("공유 경로")
                            ForEach(detail.courses) { course in
                                WegoCard(.outlined) {
                                    HStack {
                                        Text(course.title).font(WegoTokens.Typography.section)
                                        Spacer()
                                        Button("빼기", role: .destructive) { confirmation = .course(course.packId) }
                                            .frame(minHeight: WegoTokens.Metrics.touchTarget)
                                    }
                                }
                            }
                        }
                    }
                    if detail.isOwner {
                        SectionHeader("일행")
                        ForEach(detail.members.filter { !$0.isOwner }) { member in
                            WegoCard(.outlined) {
                                HStack {
                                    Text(member.name).font(WegoTokens.Typography.section)
                                    Spacer()
                                    Button(member.state == .pending ? "초대 취소" : "내보내기", role: .destructive) {
                                        confirmation = .member(member.id)
                                    }.frame(minHeight: WegoTokens.Metrics.touchTarget)
                                }
                            }
                        }
                        if detail.state == .active {
                            Button("여행 완료", role: .destructive) { confirmation = .finish }
                                .frame(maxWidth: .infinity, minHeight: WegoTokens.Metrics.primaryButtonHeight)
                                .buttonStyle(.wego(.soft)).accessibilityIdentifier("tripOwnerFinish")
                        } else if detail.state == .planned {
                            Button("여행 취소", role: .destructive) { confirmation = .cancel }
                                .frame(maxWidth: .infinity, minHeight: WegoTokens.Metrics.primaryButtonHeight)
                                .buttonStyle(.wego(.soft)).accessibilityIdentifier("tripOwnerCancel")
                        }
                    } else {
                        Button("여행 나가기", role: .destructive) { confirmation = .leave }
                            .frame(maxWidth: .infinity, minHeight: WegoTokens.Metrics.primaryButtonHeight)
                            .buttonStyle(.wego(.soft)).accessibilityIdentifier("tripLeave")
                    }
                    if detail.routeContractVersion == 2 && detail.state == .active {
                        Text("출발한 여행의 차와 공유 경로 구성은 바꿀 수 없어요.")
                            .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
                    }
                    }.disabled(store.busy || store.needsRefresh)
                }
                if store.busy { WegoLoadingView("변경 확인 중", layout: .row) }
                if store.needsRefresh {
                    Button("다시 불러오기") { Task { await store.load(); message = store.errorMessage } }
                        .disabled(store.busy || !store.accountIsCurrent)
                }
                if let message { Text(message).foregroundStyle(WegoTokens.Palette.danger).font(WegoTokens.Typography.label) }
            }.padding(WegoTokens.Space.screen)
        }
        .foregroundStyle(WegoTokens.Palette.text).background(WegoTokens.Palette.background)
        .navigationTitle("여행 관리").navigationBarTitleDisplayMode(.inline)
        .toolbar { ToolbarItem(placement: .cancellationAction) { Button("닫기") { dismiss() } } }
        .sheet(isPresented: $editingTrip) { NavigationStack { TripMetadataEditView(store: store) } }
        .sheet(item: $editingCar) { car in NavigationStack { TripCarEditView(store: store, car: car) } }
        .onChange(of: store.accountIsCurrent) { _, current in
            if !current { editingCar = nil; editingTrip = false; confirmation = nil }
        }
        .alert(confirmation?.title ?? "확인", isPresented: Binding(get: { confirmation != nil }, set: { if !$0 { confirmation = nil } })) {
            Button("취소", role: .cancel) { confirmation = nil }
            Button(confirmation?.verb ?? "확인", role: .destructive) {
                guard let action = confirmation else { return }
                confirmation = nil
                Task { await perform(action) }
            }
        } message: { Text(confirmation?.message ?? "") }
    }

    private func perform(_ action: ManagementAction) async {
        do {
            switch action {
            case .car(let id): try await store.deleteCar(carID: id)
            case .course(let id): try await store.removeCourse(packID: id)
            case .member(let id): try await store.removeMember(accountID: id)
            case .finish: try await store.finishTrip()
            case .cancel: try await store.cancelTrip()
            case .leave: try await store.leaveTrip()
            }
            message = store.errorMessage
            if store.hasLeftTrip || store.detail?.state == .completed || store.detail?.state == .cancelled { dismiss() }
        } catch { message = tripPreparationErrorMessage(error) }
    }

    private enum ManagementAction {
        case car(String), course(String), member(String), finish, cancel, leave
        var verb: String {
            switch self { case .car: "삭제"; case .course: "빼기"; case .member: "내보내기"; case .finish: "여행 완료"; case .cancel: "여행 취소"; case .leave: "나가기" }
        }
        var title: String {
            switch self { case .car: "차를 삭제할까요?"; case .course: "경로를 뺄까요?"; case .member: "일행을 내보낼까요?"; case .finish: "여행을 완료할까요?"; case .cancel: "여행을 취소할까요?"; case .leave: "여행에서 나갈까요?" }
        }
        var message: String {
            switch self {
            case .car: "이 차와 탑승 구성을 여행에서 삭제해요."
            case .course: "이 여행에서 경로를 빼요. 내 경로 원본은 그대로예요."
            case .member: "이 일행의 여행 참여 또는 대기 중 초대를 해제해요."
            case .finish: "모든 차의 남은 경로가 있어도 여행을 완료해요. 완료 후에는 바꿀 수 없어요."
            case .cancel: "준비 중인 여행을 취소해요."
            case .leave: "이 여행에서 나가요. 다시 참여하려면 초대가 필요해요."
            }
        }
    }
}

private struct TripMetadataEditView: View {
    let store: TripPreparationStore
    @Environment(\.dismiss) private var dismiss
    @State private var title = ""
    @State private var description = ""
    @State private var start = ""
    @State private var end = ""
    @State private var message: String?
    private var draft: IPhoneTripDraft { .init(title: title, description: description,
        startDate: start.isEmpty ? nil : start, endDate: end.isEmpty ? nil : end) }
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: WegoTokens.Space.medium) {
                WegoField("여행 이름", text: $title)
                WegoField("설명", text: $description)
                WegoField("시작일 · YYYY-MM-DD 또는 비워 두기", text: $start)
                WegoField("종료일 · YYYY-MM-DD 또는 비워 두기", text: $end)
                if let message { Text(message).font(WegoTokens.Typography.label).foregroundStyle(WegoTokens.Palette.danger) }
            }.padding(WegoTokens.Space.screen)
        }.background(WegoTokens.Palette.background).navigationTitle("여행 고치기").navigationBarTitleDisplayMode(.inline)
            .scrollDismissesKeyboard(.interactively)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("취소") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button { Task { do { try await store.updateTrip(draft); dismiss() } catch { message = tripPreparationErrorMessage(error) } } } label: {
                        if store.busy { WegoButtonLoadingLabel("저장 중…") }
                        else { Text("저장") }
                    }
                        .disabled(!draft.isValid || store.busy || store.needsRefresh)
                }
            }
            .onAppear { if let detail = store.detail { title = detail.title; description = detail.description; start = detail.startDate ?? ""; end = detail.endDate ?? "" } }
    }
}

private struct TripCarEditView: View {
    let store: TripPreparationStore
    let car: IPhoneTripCar
    @Environment(\.dismiss) private var dismiss
    @State private var name = ""
    @State private var seats = 1
    @State private var message: String?
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: WegoTokens.Space.medium) {
                WegoField("차 이름", text: $name)
                Stepper("동승 자리 \(seats)명", value: $seats, in: 1...8).font(WegoTokens.Typography.body)
                if let message { Text(message).font(WegoTokens.Typography.label).foregroundStyle(WegoTokens.Palette.danger) }
            }.padding(WegoTokens.Space.screen)
        }.background(WegoTokens.Palette.background).navigationTitle("차 고치기").navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("취소") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button { Task { do { try await store.updateCar(carID: car.id, name: name, seats: seats); dismiss() } catch { message = tripPreparationErrorMessage(error) } } } label: {
                        if store.busy { WegoButtonLoadingLabel("저장 중…") }
                        else { Text("저장") }
                    }
                        .disabled(!validTripText(name, max: 20) || store.busy || store.needsRefresh)
                }
            }.onAppear { name = car.name; seats = car.seats }
    }
}

struct TripMemberLocationsView: View {
    let store: TripPreparationStore
    @State private var scores: TripDrivingVersusStore
    @State private var page: IPhoneTripLocations?
    @State private var loading = false
    @State private var hasLoaded = false
    @State private var message: String?
    init(store: TripPreparationStore) { self.store = store; _scores = State(initialValue: TripDrivingVersusStore(preparation: store)) }
    @Environment(\.scenePhase) private var scenePhase
    @Environment(\.dismiss) private var dismiss
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: WegoTokens.Space.medium) {
                if store.accountIsCurrent, store.detail?.state == .active {
                    if !hasLoaded || loading && page == nil { WegoLoadingView("일행 위치 확인 중", layout: .detail) }
                    if let page, !page.locations.isEmpty {
                        WegoMapPreview(markers: page.locations.map { location in
                            .init(id: location.accountId, name: ([location.name] + [scoreLabel(car(for: location.accountId, in: store.detail))].compactMap { $0 }).joined(separator: " · "),
                                  latitude: location.latitude, longitude: location.longitude) }, accessibilityTitle: "일행 위치 지도")
                            .frame(height: WegoTokens.Metrics.courseMapHeight)
                            .clipShape(RoundedRectangle(cornerRadius: WegoTokens.Radius.card))
                    } else if hasLoaded && !loading && message == nil {
                        WegoCard(.surface) {
                            VStack(spacing: WegoTokens.Space.small) {
                                Image(systemName: "map").font(WegoTokens.Typography.title).accessibilityHidden(true)
                                Text("아직 위치를 공유한 일행이 없어요").font(WegoTokens.Typography.section)
                            }
                            .frame(maxWidth: .infinity, minHeight: WegoTokens.Metrics.placeMapHeight)
                            .multilineTextAlignment(.center)
                        }
                    }
                    if hasLoaded, message == nil, let detail = store.detail {
                        let members = detail.members.filter { $0.state == .accepted }
                        SectionHeader("일행 \(members.count)명")
                        WegoCard(.surface) {
                            VStack(spacing: WegoTokens.Space.medium) {
                                ForEach(members) { member in
                                    locationRow(member, detail: detail)
                                    if member.id != members.last?.id { Divider().overlay(WegoTokens.Palette.divider) }
                                }
                            }
                        }
                    }
                } else { Text("현재 여행의 위치를 볼 수 없어요.").font(WegoTokens.Typography.body) }
                if let message {
                    if page == nil && !loading { WegoLoadingFailureView(message: message) { Task { await load() } } }
                    else { Text(message).font(WegoTokens.Typography.label).foregroundStyle(WegoTokens.Palette.danger) }
                }
            }.padding(WegoTokens.Space.screen)
        }.background(WegoTokens.Palette.background).foregroundStyle(WegoTokens.Palette.text)
            .navigationTitle("일행 위치").navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("닫기") { dismiss() } } }
            .refreshable { await load() }
            .task(id: scenePhase) {
                guard scenePhase == .active else { return }
                repeat {
                    await load()
                    // 차량은 10초마다 위치를 보내므로 그보다 짧게 읽어 지연을 줄인다.
                    do { try await Task.sleep(for: .seconds(5)) } catch { return }
                } while !Task.isCancelled
            }
            .onChange(of: store.accountIsCurrent) { _, current in if !current { page = nil } }
    }
    private func locationRow(_ member: IPhoneTripMember, detail: IPhoneTripDetail) -> some View {
        let location = page?.locations.first { $0.accountId == member.id }
        let car = self.car(for: member.id, in: detail)
        return HStack(spacing: WegoTokens.Space.compact) {
            AvatarBadge(name: member.name, tone: .ink, size: WegoTokens.Metrics.friendAvatarSize)
            VStack(alignment: .leading, spacing: WegoTokens.Space.xSmall) {
                Text(member.name + (member.isMe ? " · 나" : "")).font(WegoTokens.Typography.section)
                if let car { Text(detail.numberedName(car)).font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary) }
                if let score = scoreLabel(car) { Text(score).font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.text) }
                if let location {
                    Text(capturedTime(location.capturedAt)).font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
                } else {
                    Text("아직 받은 위치가 없어요").font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .accessibilityElement(children: .combine)
    }

    private func car(for accountID: String, in detail: IPhoneTripDetail?) -> IPhoneTripCar? {
        detail?.cars.first { $0.driverId == accountID || $0.passengers.contains { $0.id == accountID } }
    }

    /// 서버가 공개한 여행 전체 점수만 보여 준다. 측정 전·공유 불가·참가 종료는 점수를 만들지 않는다.
    private func scoreLabel(_ car: IPhoneTripCar?) -> String? {
        guard let car, let value = scores.visibleValue, value.scope == "trip",
              let item = value.cars.first(where: { $0.id == car.id }), item.state == "ready", let score = item.totalScore else { return nil }
        return "안전운전 \(score)점 · " + (item.final == true ? "확정" : "현재")
    }

    private func capturedTime(_ raw: String) -> String {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        guard let date = formatter.date(from: raw) ?? ISO8601DateFormatter().date(from: raw) else { return "최근 수신한 위치" }
        let relative = RelativeDateTimeFormatter()
        relative.locale = Locale(identifier: "ko_KR")
        return relative.localizedString(for: date, relativeTo: Date())
    }

    private func load() async {
        guard !loading, store.accountIsCurrent, store.detail?.state == .active else { page = nil; return }
        loading = true; message = nil
        defer { loading = false; hasLoaded = true }
        do {
            let result = try await store.locations()
            guard !Task.isCancelled, store.accountIsCurrent, store.detail?.state == .active else { page = nil; return }
            page = result
        } catch is CancellationError { }
        catch { page = nil; message = tripPreparationErrorMessage(error) }
        await scores.load()
    }
}
