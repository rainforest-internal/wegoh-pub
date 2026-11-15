import SwiftUI

struct TripPreparationView: View {
    @State private var headerScrolled = false
    @Environment(SessionManager.self) private var session
    @Environment(\.scenePhase) private var scenePhase
    @Environment(\.dismiss) private var dismiss
    @State private var voice: TripVoiceStore
    @State private var store: TripPreparationStore
    @State private var sheet: PreparationSheet?
    @State private var confirmsEndingActiveTrip = false
    var versusAPI = IPhoneTripDrivingVersusAPI()
    var placeSearchAPI: any IPhoneCourseServing = IPhoneCourseAPI()
    var friendsAPI: any IPhoneFriendsServing = IPhoneFriendsAPI()

    init(tripID: String, session: SessionManager, onMutation: (@MainActor () async -> Void)? = nil) {
        let store = TripPreparationStore(tripID: tripID, session: session, onMutation: onMutation)
        _store = State(initialValue: store)
        _voice = State(initialValue: TripVoiceStore(preparation: store))
    }

    init(preview: TripPreview) {
        let store = TripPreparationStore(preview: preview)
        _store = State(initialValue: store)
        _voice = State(initialValue: TripVoiceStore(preparation: store))
    }

    init(store: TripPreparationStore, versusAPI: IPhoneTripDrivingVersusAPI, placeSearchAPI: any IPhoneCourseServing,
         friendsAPI: any IPhoneFriendsServing = IPhoneFriendsAPI()) {
        _store = State(initialValue: store)
        _voice = State(initialValue: TripVoiceStore(preparation: store))
        self.versusAPI = versusAPI; self.placeSearchAPI = placeSearchAPI
        self.friendsAPI = friendsAPI
    }

    var body: some View {
        Group {
            if !store.accountIsCurrent {
                Text("로그인한 계정이 바뀌었어요. 여행 목록에서 다시 열어 주세요.").padding(WegoTokens.Space.screen)
            } else if let detail = store.detail {
                ScrollView {
                    VStack(alignment: .leading, spacing: WegoTokens.Space.medium) {
                        if store.loading { WegoLoadingView("여행을 새로 확인하고 있어요.", layout: .row) }
                        if detail.state != .completed { heading(detail) }
                        if detail.state == .active && detail.myCar == nil {
                            Button("탈 차 고르기") { sheet = .cars }
                                .buttonStyle(.wego(.soft))
                                .disabled(store.busy || store.needsRefresh)
                                .accessibilityIdentifier("tripProgressCars")
                        }
                        if !store.isPreview && detail.state == .planned {
                            TripRouteMap(detail: detail)
                        }
                        if detail.state == .active {
                            TripProgressView(detail: detail, isPreview: store.isPreview, courseStops: store.previewCourseStops, preparation: store,
                                             versusAPI: versusAPI, voice: voice,
                                             remotePreferences: Binding(get: { store.previewRemotePreferences },
                                                                        set: { store.setPreviewRemotePreferences($0) }))
                        } else if detail.state == .planned {
                            checklist(detail)
                            memberReadiness(detail)
                            preparationActivities(detail)
                            cars(detail)
                            TripRouteOverviewView(store: store, editPlaces: { sheet = .pickup }, addCourse: { sheet = .courses }, createCourse: { sheet = .newCourse }, compact: true, showDetails: { sheet = .route })
                            if detail.myCar?.isMine == true { remotePolicy(detail) }
                        } else if detail.state == .completed {
                            TripCompletedLiveContent(preparation: store, model: TripCompletedModel(detail: detail, isPreview: store.isPreview,
                                                                            dateLabel: store.previewDateLabel),
                                                 versus: detail.myCar == nil ? nil : TripDrivingVersusSummary(preparation: store, api: versusAPI))
                        } else {
                            Text(detail.description).font(WegoTokens.Typography.body)
                            ForEach(detail.cars) { car in
                                TripPreparingCarCard(car: car.previewCard, selected: car.isMine || car.iRide, riders: detail.riders(in: car),
                                                     selectedLabel: car.isMine ? "내가 운전하는 차" : "내가 탄 차")
                            }
                        }
                        if detail.state != .active && detail.state != .completed && detail.state != .planned { courses(detail) }
                        if let error = store.errorMessage {
                            errorNotice(error)
                            Button("다시 불러오기") { Task { await store.load() } }.disabled(store.busy)
                        }
                    }
                    .padding(.horizontal, WegoTokens.Space.screen)
                    .padding(.vertical, WegoTokens.Space.small)
                    .background {
                        GeometryReader { proxy in
                            Color.clear.preference(key: TripHeaderOffsetKey.self, value: proxy.frame(in: .named("tripScroll")).minY)
                        }
                    }
                }
                .coordinateSpace(name: "tripScroll")
                .onPreferenceChange(TripHeaderOffsetKey.self) { headerScrolled = $0 < -WegoTokens.Space.small }
                .clipped()
                .scrollBounceBehavior(.always, axes: .vertical)
                .refreshable { await store.load() }
                .safeAreaInset(edge: .bottom) {
                    if detail.state == .active && !store.isPreview {
                        TripLiveControls(preparation: store, voice: voice)
                            .padding(.horizontal, WegoTokens.Space.screen)
                            .padding(.vertical, WegoTokens.Space.small)
                            .background(WegoTokens.Palette.background)
                    } else if detail.state == .planned {
                        VStack(spacing: WegoTokens.Space.xSmall) {
                            Button {
                                if detail.startConflict?.activeTrips.isEmpty == false { confirmsEndingActiveTrip = true }
                                else { Task { try? await store.start() } }
                            } label: {
                                HStack {
                                    if store.busy { WegoButtonLoadingLabel("여행 시작 중…", onAccent: true) }
                                    else { Text(detail.isOwner ? "여행 시작" : "여행 시작은 여행 만든 사람만 할 수 있어요") }
                                }
                            }
                            .buttonStyle(.wego(.primary))
                            .disabled(store.busy || store.needsRefresh || !canStart(detail))
                            .accessibilityIdentifier("tripPreparingStart")
                            if let caption = startCaption(detail) {
                                Text(caption)
                                    .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
                            }
                        }
                        .padding(.horizontal, WegoTokens.Space.screen)
                        .padding(.vertical, WegoTokens.Space.small)
                        .background(WegoTokens.Palette.background)
                    }
                }
                .toolbar {
                    ToolbarItem(placement: .principal) {
                        if headerScrolled {
                            Text("\(detail.title) · \(detail.state.label)")
                                .font(WegoTokens.Typography.label.weight(.semibold)).lineLimit(1)
                        }
                    }
                    if detail.state == .planned && (detail.isOwner || detail.myPermissions.invite) {
                        ToolbarItem(placement: .topBarTrailing) {
                            Button { sheet = .invite } label: {
                                Label("초대", systemImage: "person.badge.plus")
                                    .labelStyle(.titleAndIcon)
                                    .font(WegoTokens.Typography.label)
                                    .fixedSize()
                                    .frame(minHeight: WegoTokens.Metrics.touchTarget)
                                    .contentShape(Capsule())
                            }
                            .disabled(store.busy || store.isPreview)
                            .accessibilityIdentifier("tripPreparingInvite")
                        }
                        if !store.isPreview {
                            if #available(iOS 26.0, *) { ToolbarSpacer(.fixed, placement: .topBarTrailing) }
                        }
                    }
                    if !store.isPreview {
                        ToolbarItem(placement: .topBarTrailing) {
                            Button { sheet = .management } label: {
                                Image(systemName: "ellipsis")
                                    .font(WegoTokens.Typography.label)
                                    .frame(minWidth: WegoTokens.Metrics.touchTarget, minHeight: WegoTokens.Metrics.touchTarget)
                                    .contentShape(Circle())
                            }
                            .accessibilityLabel("관리")
                            .accessibilityIdentifier("tripManagement")
                        }
                    }
                }
                .alert(activeTripAlert(detail).title, isPresented: $confirmsEndingActiveTrip) {
                    Button("취소", role: .cancel) {}
                    Button(activeTripAlert(detail).verb, role: .destructive) {
                        Task { try? await store.start(endActiveTrip: true) }
                    }
                    .accessibilityIdentifier("tripPreparingEndActiveTripAndStart")
                } message: { Text(activeTripAlert(detail).message) }
            } else if store.loading || store.errorMessage == nil {
                WegoLoadingView("여행을 불러오는 중", layout: .detail)
            } else {
                WegoLoadingFailureView(message: store.errorMessage ?? "여행을 불러올 수 없어요.") {
                    Task { await store.load() }
                }.padding(WegoTokens.Space.screen)
            }
        }
        .background(WegoTokens.Palette.background)
        .foregroundStyle(WegoTokens.Palette.text)
        .buttonStyle(.plain)
        .navigationTitle("")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar(.hidden, for: .tabBar)
        .toolbar(.visible, for: .navigationBar)
        .toolbarBackground(.ultraThinMaterial, for: .navigationBar)
        .toolbarBackground(.visible, for: .navigationBar)
        .safeAreaInset(edge: .top, spacing: 0) {
            WegoTokens.Palette.divider.frame(height: headerScrolled ? WegoTokens.Metrics.hairlineWidth : 0)
        }
        .task(id: scenePhase) {
            guard scenePhase == .active else { return }
            repeat {
                await store.refreshVisibleState()
                guard !store.isPreview, !Task.isCancelled, store.accountIsCurrent, !store.hasLeftTrip else { return }
                // 진행 중 여행은 운전자의 안내·도착과 탑승 차·다른 차의 실시간 진행(위치 공유 기반)을 따라가도록 더 자주 읽는다.
                do { try await Task.sleep(for: .seconds(store.detail?.state == .active ? 5 : 15)) } catch { return }
            } while !Task.isCancelled
        }
        .task(id: store.detail?.state) {
            guard let event = IPhonePushManager.shared.openedNotification,
                  event.accountID == session.current?.accountID, event.tripID == store.detail?.id,
                  store.accountIsCurrent, store.detail?.state == .active,
                  event.kind == .handRaise || event.kind == .handRaiseReaction else { return }
            sheet = .signal
        }
        .onChange(of: store.hasLeftTrip) { _, left in if left { sheet = nil; dismiss() } }
        .onReceive(NotificationCenter.default.publisher(for: TripSignalInbox.responseChanged)) { event in
            guard event.object as? String == store.detail?.id else { return }
            Task { await store.refreshVisibleState() }
        }
        .onChange(of: session.current?.accountID) { _, _ in
            if !store.accountIsCurrent { sheet = nil }
        }
        .onChange(of: sheet) { _, value in if value != nil { voice.deactivate() } }
        .sheet(item: $sheet, onDismiss: { Task { await voice.activate() } }) { destination in
            NavigationStack {
                if !store.accountIsCurrent {
                    Text("로그인을 다시 확인해 주세요.")
                } else {
                switch destination {
                case .cars: TripCarsView(store: store)
                case .createCar: TripCarCreateHost(store: store)
                case .courses:
                    TripCoursePickerView(store: store, api: placeSearchAPI)
                case .newCourse:
                    TripCoursePickerView(store: store, api: placeSearchAPI, startCreating: true)
                case .invite:
                    TripFriendInvitationView(store: store, load: friendChoices)
                case .route:
                    ScrollView {
                        TripRouteOverviewView(store: store, editPlaces: { sheet = .pickup }, addCourse: { sheet = .courses }, createCourse: { sheet = .newCourse })
                            .padding(WegoTokens.Space.screen)
                    }
                    .navigationTitle("전체 경로").navigationBarTitleDisplayMode(.inline)
                    .toolbar { ToolbarItem(placement: .cancellationAction) { Button("닫기") { sheet = nil } } }
                case .pickup: TripMyPlacesView(store: store, searchAPI: placeSearchAPI)
                case .roles: TripRolesView(store: store)
                case .policy: TripRemotePolicyView(store: store)
                case .management: TripManagementView(store: store)
                case .versus: TripDrivingVersusView(preparation: store, api: versusAPI)
                case .signal: TripLiveSignalView(preparation: store)
                }
                }
            }
        }
    }

    private func heading(_ detail: IPhoneTripDetail) -> some View {
        VStack(alignment: .leading, spacing: WegoTokens.Space.xSmall) {
            HStack {
                StatusPill(detail.state.label, tone: detail.state == .active ? .live : .neutral)
                Spacer()
                if store.isPreview {
                    Text("샘플 · \(store.previewActorName ?? "미리보기")")
                        .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
                }
            }
            Text(detail.title).font(WegoTokens.Typography.title)
                .accessibilityAddTraits(.isHeader).accessibilityIdentifier("tripDetailTitle")
            Text("\(store.previewDateLabel ?? tripDateLabel(start: detail.startDate, end: detail.endDate)) · 만든 사람 \(detail.members.first(where: \.isOwner)?.name ?? "")\(detail.isOwner ? " · 나" : "")\(detail.state == .active ? " · 일행 \(detail.members.filter { $0.state == .accepted }.count)명" : "")")
                .font(WegoTokens.Typography.label).foregroundStyle(WegoTokens.Palette.secondary)
        }
    }

    private func checklist(_ detail: IPhoneTripDetail) -> some View {
        let invited = detail.members.filter { !$0.isOwner }
        let pending = invited.filter { $0.state == .pending }.count
        let readyCount = detail.members.filter { $0.readiness == .ready }.count
        let isDriver = detail.myCar?.isMine == true
        let canSelectPlaces = detail.myCar?.iRide == true && !isDriver
        let pickup = detail.myCar?.places.first { $0.kind == .pickup && $0.selectedBy?.contains(detail.me?.id ?? "") == true }
        let drop = detail.myCar?.places.first { $0.kind == .drop && $0.selectedBy?.contains(detail.me?.id ?? "") == true }
        let pickupReady = isDriver || (pickup != nil && drop != nil)
        let routeReady = detail.myCar != nil && !detail.courses.isEmpty
        let ready = [!invited.isEmpty && readyCount == detail.members.count, detail.myCar != nil, pickupReady, routeReady]
        let completed = ready.filter { $0 }.count
        return VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
            HStack {
                sectionTitle("준비 체크리스트")
                Spacer()
                Text("\(completed)/4 · \(completed == 4 ? "준비 완료" : "준비 필요")")
                    .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.accent)
            }
            WegoCard(.surface, padding: WegoTokens.Space.compact) {
                VStack(spacing: 0) {
                    checklistRow("일행 준비", complete: ready[0],
                                 subtitle: invited.isEmpty ? "초대한 참여자가 없어요."
                                     : "준비 \(readyCount)/\(detail.members.count)명" + (pending > 0 ? " · 수락 기다림 \(pending)명" : ""),
                                 actionTitle: "초대하기", enabled: !store.isPreview && (detail.isOwner || detail.myPermissions.invite)) { sheet = .invite }
                    checklistDivider
                    checklistRow("탈 차 고르기", complete: ready[1],
                                 subtitle: detail.myCar.map { detail.numberedName($0) } ?? "탈 차를 골라 주세요.",
                                 actionTitle: "보기", enabled: true) { sheet = .cars }
                    checklistDivider
                    checklistRow("타는 곳·내리는 곳 정하기", complete: ready[2],
                                 subtitle: isDriver ? "운전자는 정하지 않아도 돼요." : detail.myCar == nil ? "탈 차를 고르면 정할 수 있어요." : "타는 곳 \(pickup == nil ? "미지정" : "지정") · 내리는 곳 \(drop == nil ? "미지정" : "지정")",
                                 actionTitle: "정하기", enabled: canSelectPlaces) { sheet = .pickup }
                        .accessibilityIdentifier("tripPreparingPickup")
                    checklistDivider
                    checklistRow("경로 준비", complete: routeReady,
                                 subtitle: "경로 \(detail.courses.count)개" + (detail.myCar == nil ? " · 탈 차를 골라 주세요." : ""),
                                 actionTitle: "보기", enabled: true) { sheet = .route }
                }
            }
        }
    }

    private var checklistDivider: some View {
        WegoTokens.Palette.divider.frame(height: WegoTokens.Metrics.hairlineWidth)
    }

    private func checklistRow(_ title: String, complete: Bool, subtitle: String,
                              actionTitle: String, enabled: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(spacing: WegoTokens.Space.compact) {
                Image(systemName: complete ? "checkmark.circle.fill" : "circle")
                    .font(WegoTokens.Typography.cardTitle)
                    .foregroundStyle(complete || enabled ? WegoTokens.Palette.accent : WegoTokens.Palette.personalRouteBorder)
                    .frame(width: WegoTokens.Metrics.tripChecklistIconSize, height: WegoTokens.Metrics.tripChecklistIconSize)
                    .accessibilityHidden(true)
                VStack(alignment: .leading, spacing: WegoTokens.Space.xSmall) {
                    Text(title).font(WegoTokens.Typography.label.weight(.semibold))
                    Text(subtitle).font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                HStack(spacing: WegoTokens.Space.xSmall) {
                    Text(actionTitle)
                    Image(systemName: "chevron.right").accessibilityHidden(true)
                }
                .font(WegoTokens.Typography.caption.weight(.semibold))
                .foregroundStyle(enabled ? WegoTokens.Palette.accent : WegoTokens.Palette.secondary)
                .frame(width: WegoTokens.Metrics.touchTarget * 2, alignment: .trailing)
            }
            .frame(maxWidth: .infinity, minHeight: WegoTokens.Metrics.touchTarget)
            .padding(.vertical, WegoTokens.Space.small)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain).disabled(!enabled || store.busy || store.needsRefresh)
        .accessibilityValue(complete ? "준비 완료" : "준비 필요")
    }

    private func memberReadiness(_ detail: IPhoneTripDetail) -> some View {
        let readyCount = detail.members.filter { $0.readiness == .ready }.count
        return VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
            HStack {
                sectionTitle("일행 준비")
                Spacer()
                Text("준비 \(readyCount)/\(detail.members.count)명")
                    .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.accent)
                    .accessibilityIdentifier("tripPreparingReadinessSummary")
            }
            WegoCard(.surface, padding: WegoTokens.Space.compact) {
                VStack(spacing: 0) {
                    ForEach(Array(detail.members.enumerated()), id: \.element.id) { index, member in
                        if index > 0 { checklistDivider }
                        readinessRow(member, detail: detail)
                    }
                }
            }
        }
    }

    private func readinessRow(_ member: IPhoneTripMember, detail: IPhoneTripDetail) -> some View {
        let car = detail.cars.first { $0.driverId == member.id || $0.passengers.contains { $0.id == member.id } }
        let subtitle: String = switch member.readiness {
        case .ready: car.map { detail.numberedName($0) + ($0.driverId == member.id ? " 운전" : " 탑승") } ?? "출발 준비를 마쳤어요."
        case .invited: "초대를 아직 수락하지 않았어요."
        case .needsCar: member.isMe ? "탈 차를 골라 주세요." : "탈 차를 아직 고르지 않았어요."
        case .needsVehicle: member.isMe ? "운전할 차를 차량 앱에 연결해 주세요." : "운전할 차가 아직 연결되지 않았어요."
        case .needsPlaces: member.isMe ? "타는 곳과 내리는 곳을 정해 주세요." : "타는 곳과 내리는 곳을 아직 정하지 않았어요."
        }
        return HStack(spacing: WegoTokens.Space.compact) {
            AvatarBadge(name: member.name, tone: member.readiness == .ready ? .accent : .soft,
                        size: WegoTokens.Metrics.tripMemberAvatarSize)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: WegoTokens.Space.xSmall) {
                Text(member.name + (member.isMe ? " · 나" : "") + (member.isOwner ? " · 만든 사람" : ""))
                    .font(WegoTokens.Typography.label.weight(.semibold)).lineLimit(1)
                Text(subtitle).font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            StatusPill(member.readiness.label, tone: member.readiness == .ready ? .soft : .neutral)
        }
        .frame(maxWidth: .infinity, minHeight: WegoTokens.Metrics.touchTarget)
        .padding(.vertical, WegoTokens.Space.small)
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("tripPreparingReadiness-\(member.id)")
    }

    private func preparationActivities(_ detail: IPhoneTripDetail) -> some View {
        let roles = detail.members.filter { $0.state == .accepted && $0.role != nil && $0.role != .member }
        return VStack(spacing: WegoTokens.Space.small) {
            Button { sheet = .roles } label: {
                WegoCard(.surface, padding: WegoTokens.Space.small) {
                    WegoRow(systemImage: "person.2", title: "역할",
                            subtitle: roles.isEmpty ? "아직 정한 역할이 없어요." : roles.map { "\($0.name) · \($0.role?.title ?? "")" }.joined(separator: " · "))
                }
            }.accessibilityIdentifier("tripRoles")
            Button { sheet = .versus } label: {
                WegoCard(.surface, padding: WegoTokens.Space.small) {
                    WegoRow(systemImage: "flag.checkered", title: "함께 미션", subtitle: "안전운전 점수 대결 · 여행 전체 · 자동 참가")
                }
            }.accessibilityIdentifier("tripPreparingMissions")
        }
        .buttonStyle(.plain)
    }

    private func remotePolicy(_ detail: IPhoneTripDetail) -> some View {
        let preferences = store.isPreview ? store.previewRemotePreferences : TripRemotePreferences(policy: detail.myCar?.remotePolicy)
        return Button { sheet = .policy } label: {
            WegoCard(.surface, padding: WegoTokens.Space.small) {
                WegoRow(systemImage: "slider.horizontal.3", title: "동승자 리모컨 허용", subtitle: preferences.summary)
            }
        }
        .buttonStyle(.plain)
        .accessibilityHint("허용할 조작을 바꿔요")
        .accessibilityIdentifier("tripPreparingRemotePolicy")
    }

    private func cars(_ detail: IPhoneTripDetail) -> some View {
        VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
            HStack {
                sectionTitle("차 \(detail.cars.count)대 · 일행 \(detail.members.filter { $0.state == .accepted }.count)명")
                Spacer()
                if !detail.cars.isEmpty {
                    Button("차·탑승 보기 ›") { sheet = .cars }.font(WegoTokens.Typography.caption.weight(.semibold))
                        .foregroundStyle(WegoTokens.Palette.accent).frame(minHeight: WegoTokens.Metrics.touchTarget)
                        .accessibilityIdentifier("tripPreparingCars")
                }
            }
            if let car = detail.myCar {
                TripPreparingCarCard(car: car.previewCard(named: detail.numberedName(car)), selected: true, riders: detail.riders(in: car),
                                     selectedLabel: car.isMine ? "내가 운전하는 차" : "내가 탄 차", roleMembers: detail.roleMembers(in: car))
            } else {
                VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
                    Label(detail.cars.isEmpty ? "아직 차가 없어요" : "탈 차를 골라 주세요", systemImage: "car.side")
                        .font(WegoTokens.Typography.section)
                    Text("내 차로 운전하거나, 일행이 만든 차를 골라 주세요.")
                        .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
                    if !detail.cars.isEmpty { softButton("탈 차 고르기") { sheet = .cars } }
                    softButton("내 차로 운전할게요") { sheet = .createCar }
                }
                .padding(WegoTokens.Space.medium)
                .overlay { RoundedRectangle(cornerRadius: WegoTokens.Radius.card).strokeBorder(WegoTokens.Palette.divider) }
            }
            if detail.myCar != nil && !detail.cars.contains(where: \.isMine) {
                softButton("+ 내 차로 운전할게요") { sheet = .createCar }
            }
            if !detail.cars.isEmpty && !detail.unassigned.isEmpty { TripUnassignedMembers(names: detail.unassigned.map(\.name)) }
        }
    }

    private func courses(_ detail: IPhoneTripDetail) -> some View {
        VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
            HStack {
                sectionTitle("경로")
                Spacer()
                if detail.state == .planned {
                    Button { sheet = .courses } label: {
                        Label("내 경로 추가", systemImage: "plus")
                            .font(WegoTokens.Typography.label.weight(.semibold)).foregroundStyle(WegoTokens.Palette.accent)
                            .frame(minHeight: WegoTokens.Metrics.touchTarget).contentShape(Rectangle())
                    }.disabled(store.busy)
                        .accessibilityIdentifier("tripPreparingAddCourse")
                }
            }
            if detail.courses.isEmpty {
                Text("함께 갈 경로를 추가해 주세요.").font(WegoTokens.Typography.label)
                    .foregroundStyle(WegoTokens.Palette.secondary).frame(maxWidth: .infinity, minHeight: WegoTokens.Metrics.touchTarget)
                    .padding(WegoTokens.Space.compact)
                    .overlay { RoundedRectangle(cornerRadius: WegoTokens.Radius.control).strokeBorder(WegoTokens.Palette.divider) }
            }
            ForEach(Array(detail.courses.enumerated()), id: \.element.id) { index, course in
                VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
                    HStack {
                        Text("\(index + 1). \(course.title)").font(WegoTokens.Typography.section)
                        Spacer()
                        Text(detail.state == .planned ? "예정" : "경로").font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
                    }
                    Text("장소 \(course.stopCount)곳").font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
                    if let stops = store.previewCourseStops[course.id] {
                        Text(stops.joined(separator: " → ")).font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
                    }
                }
                .padding(.vertical, WegoTokens.Space.small)
            }
        }
    }

    private func canStart(_ detail: IPhoneTripDetail) -> Bool {
        detail.isOwner && detail.myCar != nil && !detail.courses.isEmpty && detail.busyMemberNames.isEmpty
    }

    private func startCaption(_ detail: IPhoneTripDetail) -> String? {
        guard detail.isOwner else { return (detail.members.first(where: \.isOwner).map { $0.name + "님이" } ?? "여행 만든 사람이") + " 여행을 시작하면 알려드려요" }
        if detail.myCar == nil || detail.courses.isEmpty { return "탈 차와 경로를 정하면 시작할 수 있어요." }
        if !detail.busyMemberNames.isEmpty {
            return "\(detail.busyMemberNames.joined(separator: ", "))님이 다른 여행을 진행 중이라 지금은 시작할 수 없어요."
        }
        if detail.startConflict?.activeTrips.isEmpty == false { return "진행 중인 여행을 끝내고 이 여행을 시작할 수 있어요." }
        let preparing = detail.members.filter { $0.readiness != .ready }.count
        return preparing > 0 ? "아직 준비 중인 일행이 \(preparing)명 있어요." : nil
    }

    /// One running trip per person: owned trips are finished, joined trips are left.
    private func activeTripAlert(_ detail: IPhoneTripDetail) -> (title: String, message: String, verb: String) {
        let running = detail.startConflict?.activeTrips ?? []
        let name = (running.first?.title ?? "") + (running.count > 1 ? " 외 \(running.count - 1)개" : "")
        let owned = running.allSatisfy(\.isOwner), joined = !running.contains(where: \.isOwner)
        return ("이미 진행 중인 여행이 있어요 · \(name)",
                owned ? "기존 여행을 완료하면 결과와 점수가 확정되고, 이어서 이 여행을 시작해요."
                    : joined ? "기존 여행에서 나가고 이 여행을 시작해요. 기존 여행은 다른 일행과 계속 진행돼요."
                    : "내가 만든 여행은 완료하고, 참여 중인 여행에서는 나간 뒤 이 여행을 시작해요.",
                owned ? "기존 여행 완료하고 시작" : joined ? "기존 여행에서 나가고 시작" : "기존 여행 끝내고 시작")
    }
    private func sectionTitle(_ title: String) -> some View { SectionHeader(title) }
    private func errorNotice(_ message: String) -> some View { Text(message).font(WegoTokens.Typography.label).foregroundStyle(WegoTokens.Palette.danger) }
    private func softButton(_ title: String, action: @escaping () -> Void) -> some View {
        Button(action: action) { Text(title).font(WegoTokens.Typography.label.weight(.semibold)).frame(maxWidth: .infinity, minHeight: WegoTokens.Metrics.touchTarget) }
            .foregroundStyle(WegoTokens.Palette.accent)
            .background(WegoTokens.Palette.accentSoft, in: RoundedRectangle(cornerRadius: WegoTokens.Radius.field))
            .disabled(store.busy || store.needsRefresh)
    }

    private func friendChoices() async throws -> [TripFriendInvitationChoice] {
        guard !store.isPreview, let account = session.current else { throw IPhoneSessionError.invalidSession }
        let overview = try await session.withToken(for: account) { try await friendsAPI.overview(token: $0) }
        let existing = Dictionary(uniqueKeysWithValues: (store.detail?.members ?? []).map { ($0.id, $0.state) })
        return overview.friends.map { TripFriendInvitationChoice(id: $0.id, name: $0.displayName, code: $0.code, memberState: existing[$0.id]) }
    }
}

private enum PreparationSheet: String, Identifiable {
    case cars, createCar, courses, newCourse, invite, pickup, roles, policy, management, versus, signal, route
    var id: String { rawValue }
}

extension IPhoneTripState {
    var label: String {
        switch self { case .planned: "준비 중"; case .active: "진행 중"; case .completed: "종료"; case .cancelled: "취소" }
    }
}

extension IPhoneTripMemberReadiness {
    var label: String {
        switch self { case .ready: "준비 완료"; case .invited: "수락 전"; case .needsCar, .needsVehicle, .needsPlaces: "준비 중" }
    }
}

extension IPhoneTripCar {
    func previewCard(named displayName: String) -> TripPreparingCarPreview {
        TripPreparingCarPreview(id: id, title: displayName, driverName: driverName, members: [driverName] + passengers.map(\.name), passengerCapacity: seats)
    }
    var previewCard: TripPreparingCarPreview {
        TripPreparingCarPreview(id: id, title: name, driverName: driverName,
                                members: [driverName] + passengers.map(\.name), passengerCapacity: seats)
    }
}

func tripDateLabel(start: String?, end: String?) -> String {
    if let start, let end, start != end { "\(start) – \(end)" }
    else { start ?? end ?? "날짜 미정" }
}

private struct TripHeaderOffsetKey: PreferenceKey {
    static var defaultValue: CGFloat = 0
    static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) { value = nextValue() }
}
