import SwiftUI
import Observation

struct IPhoneTripDrivingVersus: Decodable {
    struct Course: Decodable {
        var packId: String
        var version: Int
        var state: String
        var score: Int?
        var isValid: Bool {
            validCourseID(packId) && (1...Int(Int32.max)).contains(version)
                && ["pending", "final", "unavailable", "sharing-unavailable"].contains(state)
                && (score.map { (0...100).contains($0) } ?? true)
                && (state == "final" || score == nil)
                && (state != "final" || score != nil)
        }
    }
    struct Car: Decodable, Identifiable {
        var carId: String
        var name: String
        var participating: Bool
        var state: String
        var averageScore: Double?
        var measuredCourseCount: Int
        var courses: [Course]
        var totalScore: Int? = nil
        var final: Bool? = nil
        var id: String { carId }
        var isValid: Bool {
            validTripID(carId) && validTripText(name, max: 80) && participating
                && ["pending", "ready", "unavailable", "withdrawn", "sharing-unavailable"].contains(state)
                && (averageScore.map { $0.isFinite && (0...100).contains($0) } ?? true)
                && (0...courses.count).contains(measuredCourseCount) && courses.count <= 10
                && courses.allSatisfy(\.isValid) && Set(courses.map { "\($0.packId):\($0.version)" }).count == courses.count
                && measuredCourseCount == courses.filter { $0.state == "final" && $0.score != nil }.count
                && (averageScore == nil || measuredCourseCount > 0)
                && (totalScore.map { (0...100).contains($0) } ?? true)
                && (state != "sharing-unavailable" || (averageScore == nil && totalScore == nil))
        }
    }
    var kind: String
    var automatic: Bool
    var state: String
    var reason: String?
    var cars: [Car]
    var winnerCarIds: [String]
    var tied: Bool
    var scope: String? = nil
    var isValid: Bool {
        kind == "safe-driving-versus" && automatic && (scope == nil || scope == "trip") && ["pending", "final", "unavailable"].contains(state)
            && (reason.map { validTripText($0, max: 120) } ?? true)
            && (scope != "trip" || cars.allSatisfy { $0.averageScore == nil && $0.courses.isEmpty && $0.measuredCourseCount == 0 && $0.final != nil && ($0.state != "ready" || $0.totalScore != nil) })
            && cars.count <= 20 && cars.allSatisfy(\.isValid) && Set(cars.map(\.id)).count == cars.count
            && Set(winnerCarIds).count == winnerCarIds.count && Set(winnerCarIds).isSubset(of: Set(cars.map(\.id)))
            && (state == "final" || (winnerCarIds.isEmpty && !tied)) && tied == (winnerCarIds.count > 1)
            && (state != "final" || (!winnerCarIds.isEmpty && winnerCarIds.allSatisfy { id in cars.contains { $0.id == id && $0.state == "ready" && (scope == "trip" ? $0.totalScore != nil && $0.final == true : $0.averageScore != nil) } }))
    }
    static func preview(_ detail: IPhoneTripDetail) -> Self {
        .init(kind: "safe-driving-versus", automatic: true, state: "pending", reason: "preview",
              cars: detail.cars.map { .init(carId: $0.id, name: detail.numberedName($0), participating: true, state: "pending", averageScore: nil, measuredCourseCount: 0, courses: []) },
              winnerCarIds: [], tied: false)
    }
}

struct IPhoneTripDrivingVersusAPI {
    private let transport: IPhoneSessionAPI
    init(configuration: URLSessionConfiguration? = nil) { transport = IPhoneSessionAPI(configuration: configuration) }
    func load(_ tripID: String, token: String) async throws -> IPhoneTripDrivingVersus {
        guard validTripID(tripID) else { throw IPhoneTripRequestError.invalidInput }
        let data = try await transport.resource("trips/" + tripID + "/driving-score", token: token)
        let value: IPhoneTripDrivingVersus
        do { value = try JSONDecoder().decode(IPhoneTripDrivingVersus.self, from: data) }
        catch { throw IPhoneSessionError.invalidResponse }
        guard value.isValid else { throw IPhoneSessionError.invalidResponse }
        return value
    }
}

@MainActor @Observable
final class TripDrivingVersusStore {
    let preparation: TripPreparationStore
    private let api: IPhoneTripDrivingVersusAPI
    private(set) var value: IPhoneTripDrivingVersus?
    private var loadedCarID: String?
    private var requestID = UUID()
    private(set) var busy = true
    private(set) var message: String?
    init(preparation: TripPreparationStore, api: IPhoneTripDrivingVersusAPI = .init()) { self.preparation = preparation; self.api = api }
    var contextID: String { "\(preparation.detail?.me?.id ?? ""):\(preparation.detail?.myCar?.id ?? ""):\(preparation.detail?.revision ?? 0):\(preparation.accountIsCurrent)" }
    var visibleValue: IPhoneTripDrivingVersus? { preparation.accountIsCurrent && loadedCarID == preparation.detail?.myCar?.id ? value : nil }
    func load() async {
        let stamp = UUID(); requestID = stamp
        if loadedCarID != preparation.detail?.myCar?.id { value = nil; loadedCarID = nil }; message = nil
        guard preparation.accountIsCurrent, let detail = preparation.detail, let carID = detail.myCar?.id else { busy = false; return }
        if preparation.isPreview { value = .preview(detail); loadedCarID = carID; busy = false; return }
        busy = true
        defer { if requestID == stamp { busy = false } }
        do {
            let result = try await preparation.activityRequest { try await api.load(detail.id, token: $0) }
            guard requestID == stamp, preparation.detail?.myCar?.id == carID, preparation.accountIsCurrent else { return }
            value = result; loadedCarID = carID
        } catch is CancellationError { }
        catch { if requestID == stamp { message = tripPreparationErrorMessage(error) } }
    }
}

struct TripDrivingVersusView: View {
    @State private var store: TripDrivingVersusStore
    @Environment(\.dismiss) private var dismiss
    init(preparation: TripPreparationStore, api: IPhoneTripDrivingVersusAPI = .init()) { _store = State(initialValue: TripDrivingVersusStore(preparation: preparation, api: api)) }
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: WegoTokens.Space.medium) {
                Text("안전운전 점수 대결").font(WegoTokens.Typography.title)
                if store.preparation.isPreview { Text("미리보기 · 실제 점수나 승자를 만들지 않아요.").font(WegoTokens.Typography.caption) }
                if store.busy { WegoLoadingView("점수 확인 중", layout: store.visibleValue == nil ? .detail : .row).font(WegoTokens.Typography.label) }
                if let value = store.visibleValue {
                    TripDrivingVersusCard(value: value,
                                          carNames: Dictionary(uniqueKeysWithValues: (store.preparation.detail?.cars ?? []).map { ($0.id, store.preparation.detail?.numberedName($0) ?? $0.name) }),
                                          courseNames: Dictionary(uniqueKeysWithValues: (store.preparation.detail?.courses ?? []).map { ("\($0.packId):\($0.version)", $0.title) }))
                }
                if let message = store.message {
                    if store.visibleValue == nil && !store.busy {
                        WegoLoadingFailureView(message: message) { Task { await store.load() } }
                    } else { Text(message).font(WegoTokens.Typography.label) }
                }
                WegoCard(.surface) {
                    VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
                        SectionHeader("규칙")
                        Text("여행 시작 때 100점에서 시작해 급가속·급감속마다 5점씩 줄어요. 차량이 점수와 횟수만 보내고, 속도 기록은 보내지 않아요.")
                            .font(WegoTokens.Typography.label)
                        Text("모든 차가 자동으로 참가해요. 별도 대결 참가 동의는 받지 않아요.")
                            .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
                    }
                }
            }.padding(WegoTokens.Space.screen)
        }.foregroundStyle(WegoTokens.Palette.text).background(WegoTokens.Palette.background)
            .navigationTitle("함께 미션").navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("닫기") { dismiss() } }
                ToolbarItem(placement: .topBarTrailing) {
                    Button { Task { await store.load() } } label: {
                        Image(systemName: "arrow.clockwise")
                            .frame(minWidth: WegoTokens.Metrics.touchTarget, minHeight: WegoTokens.Metrics.touchTarget)
                            .contentShape(Circle())
                    }.accessibilityLabel("새로고침").disabled(store.busy)
                }
            }.task(id: store.contextID) { await store.load() }
    }
}

struct TripDrivingVersusCard: View {
    let value: IPhoneTripDrivingVersus
    var carNames: [String: String] = [:]
    var courseNames: [String: String] = [:]
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    var body: some View {
        VStack(alignment: .leading, spacing: WegoTokens.Space.large) {
            WegoCard(.ink) {
                VStack(alignment: .leading, spacing: WegoTokens.Space.large) {
                    StatusPill(value.state == "final" ? "확정 · 여행 전체" : value.state == "pending" ? "진행 중 · 여행 전체" : "측정 불가 · 여행 전체", onInk: true)
                    if value.state == "final" {
                        Text(headline).font(WegoTokens.Typography.cardTitle)
                            .accessibilityIdentifier("tripVersusHeadline")
                    }
                    if value.state == "unavailable" {
                        Text(unavailableReason).font(WegoTokens.Typography.label)
                            .foregroundStyle(WegoTokens.Palette.onInkSecondary)
                    }
                    LazyVGrid(columns: columns, alignment: .leading, spacing: WegoTokens.Space.large) {
                        ForEach(value.cars) { car in
                            VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
                                Text(carNames[car.id] ?? car.name).font(WegoTokens.Typography.label.weight(.semibold))
                                    .lineLimit(1).truncationMode(.tail)
                                    .frame(maxWidth: .infinity, alignment: .leading)
                                if value.scope == "trip", let score = car.totalScore {
                                    Text("\(score)점")
                                        .font(WegoTokens.Typography.hero)
                                        .frame(minHeight: WegoTokens.Metrics.touchTarget, alignment: .bottomLeading)
                                } else {
                                    Text(stateTitle(car.state))
                                        .font(WegoTokens.Typography.label)
                                        .foregroundStyle(WegoTokens.Palette.onInkSecondary)
                                        .frame(minHeight: WegoTokens.Metrics.touchTarget, alignment: .bottomLeading)
                                }
                                Text(car.final == true ? "여행 최종 점수" : "여행 누적 점수")
                                    .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.onInkSecondary)
                            }
                            .frame(maxHeight: .infinity, alignment: .top)
                            .accessibilityIdentifier("tripVersusCar-" + car.id)
                        }
                    }
                }
            }
            Text("타는 곳부터 내리는 곳까지 여행 전체의 점수예요. 여행이 끝나면 점수가 높은 차가 이겨요.")
                .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
        }
    }

    private var columns: [GridItem] {
        Array(repeating: GridItem(.flexible(), alignment: .leading),
              count: dynamicTypeSize.isAccessibilitySize ? 1 : min(2, max(1, value.cars.count)))
    }

    fileprivate var headline: String {
        guard value.state == "final" else { return value.state == "pending" ? "최종 점수 집계 중" : "지금은 점수를 비교할 수 없어요" }
        let names = value.cars.filter { value.winnerCarIds.contains($0.id) }.map { carNames[$0.id] ?? $0.name }.joined(separator: ", ")
        return names.isEmpty ? "점수 집계를 마쳤어요" : names + (value.tied ? " · 공동 1등" : " · 승리")
    }
    var unavailableReason: String {
        switch value.reason {
        case "vehicle-connection-required": "점수를 보내는 차량 연결을 확인해 주세요. 같은 여행의 참여 차량끼리 점수를 비교해요."
        case "report-device-changed": "현재 연결된 차량의 새 점수가 필요해요. 이전 차량의 점수를 현재 차량 기록으로 표시하지 않아요."
        case "participant-unavailable": "현재 여행의 운전자와 참여 상태를 확인해 주세요."
        case "vehicle-authority-unavailable": "일부 차량의 연결이나 여행 참여 상태를 확인해 주세요."
        case "course-unavailable": "공유 경로를 현재 확인할 수 없어 점수와 결과를 숨겼어요. 경로 공개 상태를 확인해 주세요."
        case "report-authorization-changed": "점수를 보고한 뒤 공유 상태가 바뀌어 결과를 숨겼어요. 차량에서 공유 설정과 최종 보고를 확인해 주세요."
        case "sharing-unavailable": "공유가 확인되지 않은 점수와 최종 결과를 숨겼어요."
        case "contract-unavailable": "이전 방식으로 시작한 여행에는 자동 점수 비교 기록이 없어요."
        case "insufficient-measurements": "측정 가능한 차량이 두 대 이상이어야 비교할 수 있어요."
        case "shared-incomplete": "공유 경로를 마치기 전에 여행이 끝나 결과를 비교할 수 없어요."
        default: "비교할 수 있는 측정 결과가 충분하지 않거나 여행이 일찍 종료됐어요."
        }
    }
    func stateTitle(_ state: String) -> String {
        switch state {
        case "sharing-unavailable":
            switch value.reason {
            case "vehicle-connection-required": "차량 연결 확인 필요"
            case "report-device-changed": "현재 차량 보고 필요"
            case "participant-unavailable": "참여 상태 확인 필요"
            case "vehicle-authority-unavailable": "측정 연결 확인 필요"
            case "course-unavailable": "경로 공개 확인 필요"
            case "report-authorization-changed": "최종 보고 확인 필요"
            default: "공유 확인 필요"
            }
        case "unavailable": "측정 불가"
        case "withdrawn": "참가 종료"
        default: "집계 중"
        }
    }
}

struct TripDrivingVersusSummary: View {
    @State private var store: TripDrivingVersusStore
    @State private var showingDetails = false
    private let compact: Bool
    private let api: IPhoneTripDrivingVersusAPI
    init(preparation: TripPreparationStore, api: IPhoneTripDrivingVersusAPI = .init(), compact: Bool = false) {
        self.compact = compact; self.api = api; _store = State(initialValue: TripDrivingVersusStore(preparation: preparation, api: api))
    }
    private var carNames: [String: String] {
        guard let detail = store.preparation.detail else { return [:] }
        return Dictionary(uniqueKeysWithValues: detail.cars.map { ($0.id, detail.numberedName($0)) })
    }
    private var comparison: TripScoreComparison {
        TripScoreComparison(value: store.visibleValue, ownCarID: store.preparation.detail?.myCar?.id, carNames: carNames)
    }
    var body: some View {
        Button { showingDetails = true } label: {
            HStack(spacing: WegoTokens.Space.compact) {
                Image(systemName: "flag.checkered").foregroundStyle(WegoTokens.Palette.accent)
                VStack(alignment: .leading, spacing: WegoTokens.Space.xSmall) {
                    Text(compact ? "안전운전 점수 대결" : "안전운전 점수").font(compact ? WegoTokens.Typography.label.weight(.semibold) : WegoTokens.Typography.section)
                    Text(store.visibleValue == nil && store.busy ? "여행 전체 · 점수 확인 중" : store.visibleValue == nil && store.message != nil ? "점수를 불러오지 못했어요" : comparison.subtitle)
                        .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)

                }
                Spacer(minLength: 0)
                if let scores = comparison.scores {
                    Text(scores).font(WegoTokens.Typography.label.weight(.semibold))
                        .monospacedDigit().foregroundStyle(WegoTokens.Palette.accent).fixedSize()
                }
                Image(systemName: "chevron.right").foregroundStyle(WegoTokens.Palette.secondary)
            }
            .padding(compact ? WegoTokens.Space.small : WegoTokens.Space.compact)
            .frame(maxWidth: .infinity, minHeight: WegoTokens.Metrics.touchTarget, alignment: .leading)
            .background(compact ? .clear : WegoTokens.Palette.surface, in: RoundedRectangle(cornerRadius: WegoTokens.Radius.field))
            .contentShape(Rectangle())
        }.buttonStyle(.plain).accessibilityIdentifier("tripDrivingVersus")
            .task(id: store.contextID) { await store.load() }
            .sheet(isPresented: $showingDetails) { NavigationStack { TripDrivingVersusView(preparation: store.preparation, api: api) } }
    }
}

struct TripScoreComparison {
    let subtitle: String
    let scores: String?

    init(value: IPhoneTripDrivingVersus?, ownCarID: String?, carNames: [String: String]) {
        guard let value, value.scope == "trip",
              let own = value.cars.first(where: { $0.id == ownCarID }), let ownScore = own.totalScore,
              let opponent = value.cars.filter({ $0.id != ownCarID && $0.totalScore != nil })
                .max(by: { ($0.totalScore ?? 0) < ($1.totalScore ?? 0) }),
              let opponentScore = opponent.totalScore else {
            subtitle = "여행 전체 · 집계 중"; scores = nil; return
        }
        scores = "\(ownScore) : \(opponentScore)"
        let gap = abs(ownScore - opponentScore)
        if gap == 0 { subtitle = "여행 전체 · 같은 점수예요" }
        else {
            let leader = ownScore > opponentScore ? own : opponent
            let name = carNames[leader.id] ?? leader.name
            let shortName = name.components(separatedBy: " · ").first ?? name
            subtitle = "여행 전체 · \(shortName)가 \(gap)점 앞서요"
        }
    }
}
