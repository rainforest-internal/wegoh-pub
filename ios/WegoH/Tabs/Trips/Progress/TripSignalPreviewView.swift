import SwiftUI

struct TripSignalPreviewView: View {
    @Bindable var store: TripSignalPreviewStore
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: WegoTokens.Space.large) {
                Text("디자인 미리보기 · 요청과 응답은 서버에 전송되지 않아요.")
                    .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
                switch store.phase {
                case .reason: reasons
                case .place: places
                case .waiting, .received, .agreed, .declined, .completed, .cancelled: response
                }
            }
            .padding(WegoTokens.Space.screen)
        }
        .background(WegoTokens.Palette.background)
        .foregroundStyle(WegoTokens.Palette.text)
        .navigationTitle(store.phase == .reason ? "손들기 1/2" : store.phase == .place ? "손들기 2/2" : "손들기")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .cancellationAction) {
                Button(store.phase == .place ? "이유" : "닫기") {
                    if store.phase == .place { store.back() } else { dismiss() }
                }
            }
            if store.phase == .waiting {
                ToolbarItem(placement: .topBarTrailing) {
                    Menu("미리보기 상태") {
                        Button("모두 동의한 상태 보기") { store.resolveSample(agreed: true) }
                        Button("다음에로 끝난 상태 보기") { store.resolveSample(agreed: false) }
                    }.accessibilityIdentifier("signalPreviewScenario")
                }
            }
        }
        .safeAreaInset(edge: .bottom) { footer.padding(WegoTokens.Space.screen).background(WegoTokens.Palette.background) }
    }

    private var reasons: some View {
        VStack(alignment: .leading, spacing: WegoTokens.Space.medium) {
            Text("무엇이 필요하세요?").font(WegoTokens.Typography.title)
            Text("하나를 고르면 일행 모두에게 알리고, 들를 곳을 함께 정해요.")
                .font(WegoTokens.Typography.body).foregroundStyle(WegoTokens.Palette.secondary)
            LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: WegoTokens.Space.small), count: 3),
                      spacing: WegoTokens.Space.small) {
                ForEach(TripSignalReason.allCases) { reason in
                    Button { store.chooseReason(reason) } label: {
                        VStack(spacing: WegoTokens.Space.small) {
                            Image(systemName: reason.symbol).font(WegoTokens.Typography.cardTitle)
                            Text(reason.title).font(WegoTokens.Typography.label.weight(.semibold))
                        }
                        .padding(WegoTokens.Space.compact)
                        .frame(maxWidth: .infinity, minHeight: WegoTokens.Metrics.tripSignalReasonTileHeight)
                        .background(store.reason == reason ? WegoTokens.Palette.accentSoft : WegoTokens.Palette.background,
                                    in: RoundedRectangle(cornerRadius: WegoTokens.Radius.control))
                        .overlay { RoundedRectangle(cornerRadius: WegoTokens.Radius.control)
                            .strokeBorder(store.reason == reason ? WegoTokens.Palette.accent : WegoTokens.Palette.divider) }
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .foregroundStyle(store.reason == reason ? WegoTokens.Palette.accent : WegoTokens.Palette.text)
                    .accessibilityAddTraits(store.reason == reason ? .isSelected : [])
                    .accessibilityIdentifier("signalReason-\(reason.rawValue)")
                }
            }
            Label("들를 곳은 맨 앞 차 기준으로 찾아요. 그래야 지나치지 않고 뒤차도 따라갈 수 있어요.", systemImage: "car.side")
                .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary).tripProgressCard()
        }
    }

    private var places: some View {
        VStack(alignment: .leading, spacing: WegoTokens.Space.medium) {
            Text("어디에 들를까요?").font(WegoTokens.Typography.title)
            Text("맨 앞 차(1호차 · 사용자A의 차)보다 앞에 있는 휴게소예요.")
                .font(WegoTokens.Typography.label).foregroundStyle(WegoTokens.Palette.secondary)
            ScrollView(.horizontal) {
                HStack(spacing: WegoTokens.Space.small) {
                    ForEach(TripSignalFacility.allCases) { facility in
                        Button {
                            if store.facilities.contains(facility) { store.facilities.remove(facility) }
                            else { store.facilities.insert(facility) }
                        } label: {
                            Text(facility.title).font(WegoTokens.Typography.caption.weight(.semibold))
                                .padding(WegoTokens.Space.small)
                                .foregroundStyle(store.facilities.contains(facility) ? WegoTokens.Palette.onInk : WegoTokens.Palette.text)
                                .background(store.facilities.contains(facility) ? WegoTokens.Palette.ink : WegoTokens.Palette.surface, in: Capsule())
                                .frame(minHeight: WegoTokens.Metrics.touchTarget)
                        }.buttonStyle(.plain).accessibilityValue(store.facilities.contains(facility) ? "선택" : "선택 안 함")
                    }
                }
            }.scrollIndicators(.hidden)
            Text("조건에 맞는 곳 \(store.candidates.count)곳 · 샘플 검색 결과")
                .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
            ForEach(store.candidates) { place in
                Button { store.placeID = place.id } label: {
                    VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
                        HStack {
                            Text(place.name).font(WegoTokens.Typography.section)
                            Spacer()
                            Text(place.ahead).font(WegoTokens.Typography.caption.weight(.semibold))
                            Image(systemName: store.placeID == place.id ? "checkmark.circle.fill" : "circle")
                        }
                        Text(place.detail).font(WegoTokens.Typography.caption)
                        Text(TripSignalFacility.allCases.filter { place.facilities.contains($0) }.map(\.title).joined(separator: " · "))
                            .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
                    }
                    .tripProgressCard(selected: store.placeID == place.id)
                }.buttonStyle(.plain).accessibilityIdentifier("signalPlace-\(place.id)")
            }
            Button { store.placeID = nil } label: {
                HStack {
                    VStack(alignment: .leading, spacing: WegoTokens.Space.xSmall) {
                        Text("아무 데나 세워 주세요").font(WegoTokens.Typography.section)
                        Text("장소는 운전자가 정해요").font(WegoTokens.Typography.caption)
                    }
                    Spacer()
                    Image(systemName: store.placeID == nil ? "checkmark.circle.fill" : "circle")
                }.tripProgressCard(selected: store.placeID == nil)
            }.buttonStyle(.plain).accessibilityIdentifier("signalPlace-anywhere")
            if store.selectedPlace != nil { routeChange }
            Text("다른 모든 그룹이 동의하면 다음 목적지 앞에 추가돼요.")
                .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
        }
    }

    private var response: some View {
        VStack(alignment: .leading, spacing: WegoTokens.Space.medium) {
            VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
                Text(statusTitle).font(WegoTokens.Typography.caption.weight(.semibold))
                Text(statusHeadline).font(WegoTokens.Typography.title)
                    .accessibilityIdentifier("signalStatusHeadline")
                Text("\(store.reason.title) · \(store.selectedPlace?.name ?? "장소는 운전자가 정해요")")
                    .font(WegoTokens.Typography.section)
                if let place = store.selectedPlace { Text("맨 앞 차에서 \(place.ahead) · \(place.detail)").font(WegoTokens.Typography.caption) }
            }.tripProgressCard(ink: true)
            if store.selectedPlace != nil && (store.phase == .received || store.phase == .agreed) { routeChange }
            if [.waiting, .received, .agreed, .declined].contains(store.phase) {
                Text("그룹별 응답").font(WegoTokens.Typography.section)
                groupRow("1호차 · 사용자A의 차 · 우리 차", status: store.received ? (store.phase == .received ? "지금 응답" : store.phase == .declined ? "다음에" : "동의") : "동의")
                groupRow("2호차 · 사용자B의 차", status: store.received ? "동의" : store.phase == .declined ? "다음에"
                         : store.phase == .agreed ? "동의" : "응답 대기 중")
                if store.phase == .declined && !store.received {
                    Text("다음에를 고른 그룹이 있어 이번 요청이 끝났어요.").font(WegoTokens.Typography.label)
                }
            }
            Text(store.phase == .agreed
                 ? "모든 그룹이 동의한 샘플 상태예요. 실제 차량 경로나 내비게이션은 바뀌지 않아요."
                 : "우리 차 응답은 한 번만 보낼 수 있어요. 한 그룹이라도 다음에를 고르면 이번 요청은 끝나요.")
                .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
        }
    }

    private var routeChange: some View {
        VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
            Text("동의하면 이렇게 바뀌어요").font(WegoTokens.Typography.section)
            Text("지금 경로 · 강릉 바다 드라이브").font(WegoTokens.Typography.caption)
            Label("경포해변 → \(store.selectedPlace?.name ?? "들를 곳") → 안목 커피거리 → 주문진항", systemImage: "point.topleft.down.to.point.bottomright.curvepath")
                .font(WegoTokens.Typography.label)
        }.tripProgressCard()
    }

    @ViewBuilder private var footer: some View {
        switch store.phase {
        case .reason: ActionButton(title: "다음") { store.next() }.accessibilityIdentifier("signalNext")
        case .place: ActionButton(title: "\(store.reason.title) 요청 보내기") { store.send() }
                .disabled(!store.canSend).accessibilityIdentifier("signalSend")
        case .received:
            HStack(spacing: WegoTokens.Space.small) {
                Button { store.vote(agree: false) } label: {
                    Text("다음에").frame(maxWidth: .infinity, minHeight: WegoTokens.Metrics.primaryButtonHeight)
                        .contentShape(Rectangle())
                }.accessibilityIdentifier("signalPass")
                ActionButton(title: "동의") { store.vote(agree: true) }.accessibilityIdentifier("signalAgree")
            }
        case .waiting, .agreed:
            if store.received { ActionButton(title: "여행으로") { dismiss() } }
            else {
                VStack(spacing: WegoTokens.Space.small) {
                    if store.phase == .agreed { ActionButton(title: "손들기 완료") { store.finish() }.accessibilityIdentifier("signalFinish") }
                    Button(role: .destructive) { store.cancel() } label: {
                        Text("손들기 취소").font(WegoTokens.Typography.action)
                            .frame(minHeight: WegoTokens.Metrics.touchTarget).contentShape(Rectangle())
                    }.accessibilityIdentifier("signalCancel")
                }
            }
        case .declined, .completed, .cancelled: ActionButton(title: "여행으로") { dismiss() }
        }
    }

    private func groupRow(_ title: String, status: String) -> some View {
        HStack { Label(title, systemImage: "car.side"); Spacer(); Text(status) }
            .font(WegoTokens.Typography.label).tripProgressCard()
    }
    private var statusTitle: String {
        switch store.phase {
        case .waiting: "동의 기다리는 중"
        case .received: "받은 손들기 요청"
        case .agreed: "모든 그룹 동의"
        case .declined: "다음에로 끝났어요"
        case .completed: "손들기 완료"
        case .cancelled: "손들기 취소"
        default: "손들기"
        }
    }
    private var statusHeadline: String {
        switch store.phase {
        case .waiting: "일행의 답을 기다리고 있어요"
        case .received: "사용자E님이 손을 들었어요"
        case .agreed: store.selectedPlace == nil ? "일행이 들르기에 동의했어요" : "다음 목적지 앞에 추가됐어요"
        case .declined: "요청을 마쳤어요"
        case .completed: "들르기를 마쳤어요"
        case .cancelled: "요청을 취소했어요"
        default: "손들기"
        }
    }
}

extension View {
    func tripProgressCard(ink: Bool = false, selected: Bool = false) -> some View {
        WegoCard(ink ? .ink : .outlined) { self }
            .overlay {
                if selected && !ink {
                    RoundedRectangle(cornerRadius: WegoTokens.Radius.card)
                        .strokeBorder(WegoTokens.Palette.accent, lineWidth: WegoTokens.Metrics.selectedBorderWidth)
                }
            }
            .contentShape(Rectangle())
    }
}
