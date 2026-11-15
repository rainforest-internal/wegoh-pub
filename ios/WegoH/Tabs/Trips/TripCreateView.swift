import SwiftUI

struct TripCreateView: View {
    let onCreate: (IPhoneTripDraft) async throws -> Void

    @Environment(\.dismiss) private var dismiss
    @Environment(\.timeZone) private var timeZone
    @State private var draft = IPhoneTripDraft()
    @State private var choosingDate: DateField?
    @State private var pickerDate = Date.now
    @State private var saving = false
    @State private var errorMessage: String?
    @FocusState private var titleFocused: Bool
    @FocusState private var descriptionFocused: Bool

    private enum DateField: String, Identifiable {
        case start = "시작일"
        case end = "종료일"
        var id: Self { self }
    }

    init(onCreate: @escaping (IPhoneTripDraft) async throws -> Void) {
        self.onCreate = onCreate
    }

    private var canCreate: Bool {
        !saving && draft.title.unicodeScalars.count <= 40 && draft.description.unicodeScalars.count <= 300 && draft.isValid
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: WegoTokens.Space.large) {
                VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
                    fieldLabel("제목 · 필수", value: draft.title, limit: 40)
                    WegoField("여행 제목", text: $draft.title, focus: $titleFocused,
                              prompt: "예: 강릉 바다 여행", identifier: "tripCreateTitle", showsTitle: false)
                        .submitLabel(.next)
                        .onSubmit { descriptionFocused = true }
                }
                VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
                    fieldLabel("설명", value: draft.description, limit: 300)
                    WegoField("여행 설명", text: $draft.description, focus: $descriptionFocused,
                              axis: .vertical, prompt: "어떤 여행인지 일행에게 알려주세요.",
                              identifier: "tripCreateDescription", showsTitle: false)
                }

                VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
                    SectionHeader("날짜")
                    HStack(spacing: WegoTokens.Space.large) {
                        dateButton(.start, value: draft.startDate, other: draft.endDate)
                        dateButton(.end, value: draft.endDate, other: draft.startDate)
                    }
                    .background {
                        Canvas { context, size in
                            var connector = Path()
                            connector.move(to: CGPoint(x: 0, y: size.height / 2))
                            connector.addLine(to: CGPoint(x: size.width, y: size.height / 2))
                            context.stroke(connector, with: .color(WegoTokens.Palette.accent),
                                           style: StrokeStyle(lineWidth: WegoTokens.Metrics.hairlineWidth,
                                                              dash: [WegoTokens.Metrics.hairlineWidth, WegoTokens.Metrics.timelineWidth]))
                        }
                        .accessibilityHidden(true)
                    }
                    Text("각 날짜는 비워 둘 수 있어요. 두 날짜의 간격은 최대 30일이에요.")
                        .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
                }


            }
            .padding(.horizontal, WegoTokens.Space.screen)
            .padding(.vertical, WegoTokens.Space.compact)
            .disabled(saving)
        }
        .scrollDismissesKeyboard(.interactively)
        .font(WegoTokens.Typography.body)
        .foregroundStyle(WegoTokens.Palette.text)
        .background(WegoTokens.Palette.background)
        .navigationTitle("새 여행 만들기")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .cancellationAction) {
                Button("취소") { if !saving { dismiss() } }
                    .disabled(saving)
                    .accessibilityIdentifier("tripCreateCancel")
            }
        }
        .interactiveDismissDisabled(saving)
        .safeAreaInset(edge: .bottom) {
            VStack(spacing: WegoTokens.Space.small) {
                if let errorMessage {
                    Text(errorMessage).font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.danger)
                        .accessibilityIdentifier("tripCreateError")
                }
                Text("친구는 여행을 만든 뒤 여행 화면에서 초대할 수 있어요.")
                    .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
                Button(action: create) {
                    HStack(spacing: WegoTokens.Space.small) {
                        if saving { WegoButtonLoadingLabel("여행 만드는 중…", onAccent: true) }
                        else { Text("여행 만들기") }
                    }
                    .font(WegoTokens.Typography.action)
                    .frame(maxWidth: .infinity, minHeight: WegoTokens.Metrics.primaryButtonHeight)
                }
                .buttonStyle(WegoPrimaryButtonStyle())
                .disabled(!canCreate)
                .accessibilityIdentifier("tripCreateSave")
            }
            .padding(.horizontal, WegoTokens.Space.screen)
            .padding(.vertical, WegoTokens.Space.small)
            .background(WegoTokens.Palette.background)
        }
        .sheet(item: $choosingDate) { field in datePicker(field) }
    }

    private func fieldLabel(_ label: String, value: String, limit: Int) -> some View {
        let count = value.unicodeScalars.count
        return HStack(alignment: .firstTextBaseline) {
            Text(label).font(WegoTokens.Typography.label.weight(.semibold))
            Spacer()
            Text("\(count)/\(limit)").font(WegoTokens.Typography.caption.monospacedDigit())
                .foregroundStyle(count > limit ? WegoTokens.Palette.danger : WegoTokens.Palette.secondary)
                .accessibilityLabel("최대 \(limit)자 중 \(count)자 입력")
        }
    }

    private var calendar: Calendar {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = timeZone
        return calendar
    }

    private var dayFormat: DateFormatter {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.calendar = calendar
        formatter.timeZone = timeZone
        formatter.dateFormat = "yyyy-MM-dd"
        return formatter
    }

    private func dateButton(_ field: DateField, value: String?, other: String?) -> some View {
        Button {
            titleFocused = false
            descriptionFocused = false
            pickerDate = (value ?? other).flatMap(dayFormat.date(from:)) ?? Date.now
            choosingDate = field
        } label: {
            VStack(alignment: .leading, spacing: WegoTokens.Space.xSmall) {
                Text(field.rawValue + " (선택)").font(WegoTokens.Typography.label).foregroundStyle(WegoTokens.Palette.secondary)
                Text(value ?? "날짜 미정")
                    .font(WegoTokens.Typography.section)
                    .foregroundStyle(value == nil ? WegoTokens.Palette.secondary : WegoTokens.Palette.text)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(WegoTokens.Space.medium)
            .frame(minHeight: WegoTokens.Metrics.settingsMenuHeight, alignment: .leading)
            .background(WegoTokens.Palette.surface, in: RoundedRectangle(cornerRadius: WegoTokens.Radius.card))
            .overlay {
                RoundedRectangle(cornerRadius: WegoTokens.Radius.card)
                    .strokeBorder(WegoTokens.Palette.divider, lineWidth: WegoTokens.Metrics.hairlineWidth)
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(field.rawValue)
        .accessibilityValue(value ?? "미정")
        .accessibilityIdentifier(field == .start ? "tripCreateStartDate" : "tripCreateEndDate")
    }

    private func datePicker(_ field: DateField) -> some View {
        let value = field == .start ? $draft.startDate : $draft.endDate
        let other = field == .start ? draft.endDate : draft.startDate
        var bounds = Date.distantPast...Date.distantFuture
        if let other, let day = dayFormat.date(from: other),
           let limit = calendar.date(byAdding: .day, value: field == .start ? -30 : 30, to: day) {
            bounds = min(day, limit)...max(day, limit)
        }
        return NavigationStack {
            ScrollView {
                DatePicker(field.rawValue, selection: $pickerDate, in: bounds, displayedComponents: .date)
                    .datePickerStyle(.graphical)
                    .environment(\.calendar, calendar)
                    .environment(\.timeZone, timeZone)
                    .tint(WegoTokens.Palette.accent)
                    .padding(.horizontal, WegoTokens.Space.medium)
                if value.wrappedValue != nil {
                    Button { value.wrappedValue = nil; choosingDate = nil } label: {
                        Text("\(field.rawValue) 비우기").font(WegoTokens.Typography.label)
                            .frame(minHeight: WegoTokens.Metrics.touchTarget)
                            .contentShape(Rectangle())
                    }
                }
            }
            .navigationTitle("\(field.rawValue) 선택")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("취소") { choosingDate = nil } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("선택") { value.wrappedValue = dayFormat.string(from: pickerDate); choosingDate = nil }
                }
            }
        }
        .presentationDetents([.medium, .large])
    }

    private func create() {
        guard canCreate else { return }
        saving = true
        errorMessage = nil
        titleFocused = false
        descriptionFocused = false
        let submitted = draft
        Task { @MainActor in
            do {
                try await onCreate(submitted)
                dismiss()
            } catch {
                errorMessage = tripPreparationErrorMessage(error)
                saving = false
            }
        }
    }
}
