import SwiftUI

enum VehicleLinkMethod: String, Identifiable, CaseIterable {
    case scan, code
    var id: String { rawValue }
    var title: String { self == .scan ? "QR 스캔" : "코드 입력" }
}

struct VehicleLinkView: View {
    @Environment(SessionManager.self) private var session
    @Environment(\.dismiss) private var dismiss
    @State private var method: VehicleLinkMethod
    @State private var input = ""
    @State private var detail: VehicleConnectionDetail?
    @State private var scopes: Set<String> = []
    @State private var keepSignedIn = false
    @State private var busy = false
    @State private var approved = false
    @State private var completed = false
    @State private var watchingCompletion = false
    @State private var knownVehicleIDs: Set<String>?
    @State private var limitReached = false
    @State private var message: String?
    @State private var lookupID = UUID()
    @FocusState private var codeFocused: Bool
    private let api = IPhoneVehicleAPI()

    init(initialMethod: VehicleLinkMethod) {
        _method = State(initialValue: initialMethod)
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: WegoTokens.Space.large) {
                    if let detail { review(detail) } else { entry }
                    if let message {
                        WegoCard(.surface) {
                            Text(message).font(WegoTokens.Typography.label)
                                .foregroundStyle(WegoTokens.Palette.secondary)
                        }
                        .accessibilityIdentifier("vehicleLinkMessage")
                    }
                }
                .padding(WegoTokens.Space.screen)
            }
            .background(WegoTokens.Palette.background)
            .foregroundStyle(WegoTokens.Palette.text)
            .navigationTitle(completed ? "차량 연결 완료" : approved ? "연결 승인 완료" : detail == nil ? "차량 연결" : "연결할 차량 확인")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(approved ? "완료" : "닫기") { dismiss() }.accessibilityIdentifier("vehicleCloseScan")
                }
                ToolbarItemGroup(placement: .keyboard) {
                    Spacer()
                    Button("입력 완료") { codeFocused = false }
                }
            }
            .onDisappear { lookupID = UUID() }
            .task(id: approved) { await watchVehicleCompletion() }
            .onChange(of: session.current?.accountID) { _, _ in dismiss() }
        }
    }

    @ViewBuilder private var entry: some View {
        WegoCard(.ink, padding: WegoTokens.Space.screen) {
            VStack(alignment: .leading, spacing: WegoTokens.Space.medium) {
                Text("QR 또는 코드로 연결").font(WegoTokens.Typography.cardTitle)
                RouteStrip(stops: ["iPhone", "차량"], onInk: true)
                Text("차량 화면의 연결 정보를 확인해 주세요.")
                    .font(WegoTokens.Typography.label).foregroundStyle(WegoTokens.Palette.onInkSecondary)
            }
        }
        ChoiceChips(options: VehicleLinkMethod.allCases.map(\.title), selection: Binding(
            get: { [method.title] },
            set: { value in
                if let next = VehicleLinkMethod.allCases.first(where: { value.contains($0.title) }) { method = next }
            }
        ), allowsMultipleSelection: false)
        .disabled(busy)
        if busy {
            WegoLoadingView("차량 확인 중", layout: .row)
        } else if method == .scan {
            VehicleQRScanner { payload in
                guard !busy, detail == nil else { return }
                guard let code = VehicleQR.comparisonCode(in: payload) else {
                    method = .code
                    message = "차량의 WegoH 연결 화면에 있는 QR을 스캔해 주세요."
                    return
                }
                Task { await lookup(code) }
            }
            .frame(minHeight: WegoTokens.Metrics.vehicleScannerHeight)
            .clipShape(RoundedRectangle(cornerRadius: WegoTokens.Radius.hero))
            Button("코드 직접 입력") { method = .code }
                .buttonStyle(.wego(.soft)).accessibilityIdentifier("vehicleUseCode")
        } else {
            VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
                SectionHeader("차량 연결 코드")
                WegoField("차량 연결 코드", text: $input, focus: $codeFocused,
                          prompt: "ABCD2345", identifier: "vehicleCodeInput", showsTitle: false)
                    .textInputAutocapitalization(.characters).autocorrectionDisabled()
                    .keyboardType(.asciiCapable).submitLabel(.continue)
                    .onSubmit { submitCode() }
                    .onChange(of: input) { _, _ in message = nil }
            }
            Button("차량 확인") { submitCode() }
                .buttonStyle(.wego(.primary))
                .disabled(VehicleQR.inputCode(input) == nil).accessibilityIdentifier("vehicleLookupCode")
        }
        Text("차량 화면의 영문·숫자 8자리 코드를 입력하세요.")
            .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
    }

    @ViewBuilder private func review(_ detail: VehicleConnectionDetail) -> some View {
        WegoCard(.ink, padding: WegoTokens.Space.screen) {
            VStack(alignment: .leading, spacing: WegoTokens.Space.medium) {
                Text("연결할 차량").font(WegoTokens.Typography.label).foregroundStyle(WegoTokens.Palette.onInkSecondary)
                Text(detail.deviceName).font(WegoTokens.Typography.cardTitle)
                    .accessibilityIdentifier("vehicleReviewName")
                RouteStrip(stops: [detail.currentAccountDisplayName + "의 iPhone", detail.deviceName],
                           progress: approved ? 1 : nil, onInk: true)
                LabeledContent("연결 계정", value: detail.currentAccountDisplayName)
                LabeledContent("코드") { Text(detail.userCode).font(WegoTokens.Typography.cardTitle.monospaced()) }
                if !approved {
                    LabeledContent("코드 만료", value: detail.expiry.formatted(date: .omitted, time: .shortened))
                    Text("차량 화면의 이름과 코드가 일치하는지 확인해 주세요.")
                        .font(WegoTokens.Typography.label).foregroundStyle(WegoTokens.Palette.onInkSecondary)
                }
            }
        }
        if approved {
            WegoCard(.soft) {
                VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
                    Label(completed ? "차량 연결을 마쳤어요" : "이 차량의 연결을 승인했어요", systemImage: "checkmark.circle.fill")
                        .font(WegoTokens.Typography.section)
                    if completed {
                        Text("이제 차량에서 WegoH를 쓸 수 있어요.")
                            .font(WegoTokens.Typography.label).foregroundStyle(WegoTokens.Palette.secondary)
                    } else if watchingCompletion {
                        WegoLoadingView("차량이 연결을 마치는 중", layout: .row)
                    } else {
                        Text("차량 화면에서 연결 결과를 확인해 주세요.")
                            .font(WegoTokens.Typography.label).foregroundStyle(WegoTokens.Palette.secondary)
                    }
                }
            }
            .accessibilityIdentifier("vehicleLinkApproved")
        } else if detail.state == "PENDING" {
            SectionHeader("차량에서 사용할 기능")
            ForEach(detail.disclosureSnapshot.scopeDisclosures) { item in
                WegoCard(.surface) {
                    VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
                        if item.required {
                            LabeledContent(item.title, value: "기본 연결")
                        } else {
                            Toggle(item.title, isOn: Binding(
                                get: { scopes.contains(item.scope) },
                                set: { enabled in
                                    if enabled { scopes.insert(item.scope) } else { scopes.remove(item.scope) }
                                }
                            ))
                        }
                        Text(item.purpose).font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
                        DisclosureGroup("사용 정보 보기") {
                            Text("정보: " + item.dataCategories.joined(separator: ", "))
                            Text("보관: " + item.retention)
                            Text("거부 시: " + item.refusalEffect)
                            Text("연결 해제 시: " + item.withdrawalEffect)
                        }
                        .font(WegoTokens.Typography.caption)
                    }
                }
                .disabled(busy)
            }
            WegoCard(.surface) {
                VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
                    Toggle("이 차량에서 로그인 유지", isOn: $keepSignedIn).disabled(busy)
                        .accessibilityIdentifier("vehicleKeepSignedIn")
                    Text(detail.disclosureSnapshot.keepSignedInDisclosure)
                        .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
                }
            }
            if limitReached {
                WegoCard(.outlined) {
                    VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
                        Label("이미 연결된 차량이 있어요", systemImage: "exclamationmark.triangle.fill")
                            .font(WegoTokens.Typography.section).foregroundStyle(WegoTokens.Palette.danger)
                        Text(VehicleLinkError.limit.localizedDescription)
                            .font(WegoTokens.Typography.label).foregroundStyle(WegoTokens.Palette.secondary)
                    }
                }
                .accessibilityElement(children: .combine)
                .accessibilityIdentifier("vehicleLinkLimit")
            }
            TimelineView(.periodic(from: .now, by: 1)) { context in
                VStack(alignment: .leading, spacing: WegoTokens.Space.medium) {
                    if detail.expiry <= context.date {
                        Text("코드가 만료되었어요. 차량에서 새 코드를 확인해 주세요.")
                            .font(WegoTokens.Typography.label).foregroundStyle(WegoTokens.Palette.danger)
                    }
                    Button { Task { await approve(detail) } } label: {
                        if busy { WegoButtonLoadingLabel("연결 승인 중…", onAccent: true) }
                        else { Text("이 차량 연결") }
                    }
                        .buttonStyle(.wego(.primary)).disabled(busy || detail.expiry <= context.date)
                        .accessibilityIdentifier("vehicleConfirmLink")
                }
            }
            Button("다른 코드 입력") { reset() }.buttonStyle(.wego(.plain)).disabled(busy)
        } else {
            WegoCard(.surface) {
                VStack(alignment: .leading, spacing: WegoTokens.Space.medium) {
                    Text(detail.state == "APPROVED" ? "이미 승인한 요청이에요. 차량에서 연결을 완료해 주세요." : "연결이 거절된 코드예요. 차량에서 새 코드를 확인해 주세요.")
                        .font(WegoTokens.Typography.body)
                    Button("다른 코드 입력") { reset() }.buttonStyle(.wego(.soft))
                }
            }
        }
    }

    private func reset() {
        detail = nil
        approved = false
        completed = false
        knownVehicleIDs = nil
        limitReached = false
        keepSignedIn = false
        scopes = []
        input = ""
        method = .code
        message = nil
    }

    private func submitCode() {
        guard !busy else { return }
        guard let code = VehicleQR.inputCode(input) else {
            message = VehicleLinkError.invalidCode.localizedDescription
            return
        }
        codeFocused = false
        Task { await lookup(code) }
    }

    @MainActor private func lookup(_ code: String) async {
        guard !busy, let account = session.current else { return }
        let id = UUID()
        lookupID = id
        busy = true
        message = nil
        defer { if lookupID == id { busy = false } }
        do {
            let result = try await session.withToken(for: account) { try await api.connection(code: code, token: $0) }
            guard lookupID == id else { return }
            detail = result
            scopes = result.initialScopes
            keepSignedIn = false
        } catch is CancellationError {}
        catch { if lookupID == id { message = error.localizedDescription } }
    }

    @MainActor private func approve(_ detail: VehicleConnectionDetail) async {
        guard !busy, !approved, let account = session.current else { return }
        busy = true
        message = nil
        limitReached = false
        let id = lookupID
        let selectedScopes = scopes
        let remember = keepSignedIn
        defer { if lookupID == id { busy = false } }
        // 승인 전 연결 목록을 기억해 두고, 차량이 토큰을 받아 새 기기로 나타나면 연결 완료로 본다.
        let known = try? await session.withToken(for: account) { try await api.vehicles(token: $0) }
        do {
            try await session.withToken(for: account) {
                try await api.approve(detail, scopes: selectedScopes, keepSignedIn: remember, token: $0)
            }
            guard lookupID == id else { return }
            knownVehicleIDs = known.map { Set($0.map(\.id)) }
            approved = true
        } catch is CancellationError {}
        catch VehicleLinkError.limit {
            // 계정당 1대 제한은 코드 문제가 아니므로 확인 화면을 유지하고 해결 방법을 함께 보여 준다.
            guard lookupID == id else { return }
            limitReached = true
        }
        catch {
            guard lookupID == id else { return }
            reset()
            message = error.localizedDescription + " 코드를 다시 조회해 현재 상태를 확인해 주세요."
        }
    }

    /// 승인 뒤 차량이 연결을 마쳤는지 내 차량 목록으로 확인한다. 승인 전 목록에 없던 기기가 생기면 완료다.
    static func vehicleFinishedLink(_ devices: [LinkedVehicle], known: Set<String>) -> Bool {
        devices.contains { !known.contains($0.id) }
    }

    @MainActor private func watchVehicleCompletion() async {
        guard approved, !completed, let known = knownVehicleIDs, let account = session.current else { return }
        watchingCompletion = true
        defer { watchingCompletion = false }
        for _ in 0..<90 {
            try? await Task.sleep(for: .seconds(2))
            guard !Task.isCancelled, approved, !completed else { return }
            guard let devices = try? await session.withToken(for: account, { try await api.vehicles(token: $0) }) else { continue }
            if Self.vehicleFinishedLink(devices, known: known) { completed = true; return }
        }
    }
}
