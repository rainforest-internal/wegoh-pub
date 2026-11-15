import SwiftUI

struct TripCompletedView: View {
    let model: TripCompletedModel

    var body: some View {
        ScrollView {
            TripCompletedContent(model: model)
                .padding(.horizontal, WegoTokens.Space.screen)
                .padding(.vertical, WegoTokens.Space.small)
        }
        .background(WegoTokens.Palette.background)
        .foregroundStyle(WegoTokens.Palette.text)
        .navigationTitle("")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar(.visible, for: .navigationBar)
    }
}

struct TripCompletedContent: View {
    let model: TripCompletedModel
    var versus: TripDrivingVersusSummary? = nil
    var shareCourse: (() -> Void)? = nil
    var openRecord: (() -> Void)? = nil
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @ScaledMetric(relativeTo: .caption) private var avatarSide = WegoTokens.Metrics.tripMemberAvatarSize
    @State private var showingRecord = false

    var body: some View {
        VStack(alignment: .leading, spacing: WegoTokens.Space.large) {
            heading
            if !model.description.isEmpty { Text(model.description).font(WegoTokens.Typography.body) }
            summary
            if let versus { versus }
            if !model.courses.isEmpty { courses }
            Divider().overlay(WegoTokens.Palette.divider)
            participants
            Button { shareCourse?() } label: {
                Label("이 여행을 경로로 다듬어 공유", systemImage: "point.topleft.down.to.point.bottomright.curvepath")
            }
            .buttonStyle(.wego(.primary))
            .disabled(shareCourse == nil)
            .accessibilityIdentifier("tripCompletedShareCourse")
            Text("타는 곳·내리는 곳을 빼고 함께 달린 공유 경로만 가져와요.")
                .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
            Button {
                if let openRecord { openRecord() }
                else if model.isPreview { showingRecord = true }
            } label: {
                Label("여행 기록", systemImage: "clock.arrow.circlepath")
            }
            .buttonStyle(.wego(.soft)).disabled(!model.isPreview && openRecord == nil)
            .accessibilityIdentifier("tripCompletedRecords")
            Text("끝난 여행이라 바꿀 수 없어요")
                .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
                .frame(maxWidth: .infinity)
            if model.isPreview {
                Text("디자인 미리보기 · 완료 수는 샘플이에요.")
                    .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
            }
        }
        .foregroundStyle(WegoTokens.Palette.text)
        .sheet(isPresented: $showingRecord) { NavigationStack { sampleRecord } }
    }

    private var heading: some View {
        VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
            HStack {
                StatusPill("종료")
                Spacer()
                if model.isPreview { Text("샘플").font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary) }
            }
            Text(model.title).font(WegoTokens.Typography.title)
                .accessibilityAddTraits(.isHeader).accessibilityIdentifier("tripDetailTitle")
            Text("\(model.dateLabel) · 만든 사람 \(model.ownerName)")
                .font(WegoTokens.Typography.label).foregroundStyle(WegoTokens.Palette.secondary)
        }
    }

    private var summary: some View {
        WegoCard(.ink) {
            VStack(alignment: .leading, spacing: WegoTokens.Space.medium) {
                HStack(spacing: WegoTokens.Space.compact) {
                    Image(systemName: "checkmark.circle.fill").font(WegoTokens.Typography.title).accessibilityHidden(true)
                    Text(model.allRoutesCompleted ? "모든 경로 완료" : "여행을 마쳤어요")
                        .font(WegoTokens.Typography.section)
                }
                if !model.routeNames.isEmpty {
                    if model.routeNames.count <= 3 {
                        RouteStrip(stops: model.routeNames,
                                   progress: model.allRoutesCompleted ? model.routeNames.count - 1 : nil, onInk: true)
                    } else {
                        RouteList(stops: model.routeNames.enumerated().map { index, name in
                            RouteStop(id: String(index), title: name,
                                      state: model.allRoutesCompleted ? .arrived : .planned)
                        }, onInk: true, numbered: true)
                    }
                }
                Text(completionSummary)
                    .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.onInkSecondary)
                    .accessibilityIdentifier("tripCompletedSummary")
            }
        }
    }

    private var courses: some View {
        VStack(alignment: .leading, spacing: WegoTokens.Space.medium) {
            Text("경로").font(WegoTokens.Typography.section).accessibilityAddTraits(.isHeader)
            ForEach(Array(model.courses.enumerated()), id: \.element.id) { index, course in
                VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
                    HStack(alignment: .top, spacing: WegoTokens.Space.small) {
                        VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
                            Text("\(index + 1). \(course.title)").font(WegoTokens.Typography.section)
                            Text(courseSummary(course)).font(WegoTokens.Typography.caption)
                                .foregroundStyle(WegoTokens.Palette.secondary)
                        }
                        Spacer(minLength: 0)
                    }
                }
                .padding(.vertical, WegoTokens.Space.compact)
                .frame(maxWidth: .infinity, alignment: .leading)
                Divider().overlay(WegoTokens.Palette.divider)
            }
        }
    }

    private var participants: some View {
        VStack(alignment: .leading, spacing: WegoTokens.Space.medium) {
            Text("함께한 일행").font(WegoTokens.Typography.section).accessibilityAddTraits(.isHeader)
            if !model.cars.isEmpty {
                LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: WegoTokens.Space.small),
                                        count: dynamicTypeSize.isAccessibilitySize ? 1 : min(2, model.cars.count)), alignment: .leading, spacing: WegoTokens.Space.small) {
                    ForEach(model.cars) { car in
                        VStack(alignment: .leading, spacing: WegoTokens.Space.compact) {
                            Text(car.name).font(WegoTokens.Typography.label.weight(.semibold))
                            ViewThatFits(in: .horizontal) {
                                HStack(spacing: -WegoTokens.Space.small) {
                                    ForEach(Array(car.memberNames.enumerated()), id: \.offset) { index, name in
                                        AvatarBadge(name: name, tone: index == 0 ? .ink : .soft,
                                                    size: WegoTokens.Metrics.tripMemberAvatarSize)
                                            .accessibilityHidden(true)
                                    }
                                }
                                .fixedSize(horizontal: true, vertical: false)
                                LazyVGrid(columns: [GridItem(.adaptive(minimum: avatarSide), spacing: WegoTokens.Space.small)],
                                          spacing: WegoTokens.Space.small) {
                                    ForEach(Array(car.memberNames.enumerated()), id: \.offset) { index, name in
                                        AvatarBadge(name: name, tone: index == 0 ? .ink : .soft,
                                                    size: WegoTokens.Metrics.tripMemberAvatarSize)
                                            .accessibilityHidden(true)
                                    }
                                }
                            }
                        }
                        .padding(WegoTokens.Space.compact)
                        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                        .overlay { RoundedRectangle(cornerRadius: WegoTokens.Radius.control).strokeBorder(WegoTokens.Palette.divider) }
                        .accessibilityElement(children: .ignore)
                        .accessibilityLabel("\(car.name): \(car.memberNames.joined(separator: ", "))")
                    }
                }
            }
            if !model.unassignedNames.isEmpty {
                Text(model.unassignedNames.joined(separator: " · ")).font(WegoTokens.Typography.label)
                    .foregroundStyle(WegoTokens.Palette.secondary)
            }
        }
    }

    private var sampleRecord: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: WegoTokens.Space.large) {
                Text("샘플 여행 기록").font(WegoTokens.Typography.title).accessibilityIdentifier("tripCompletedSampleRecord")
                Text("디자인 미리보기이며 실제 주행 기록을 조회하거나 저장하지 않아요.")
                    .font(WegoTokens.Typography.body).foregroundStyle(WegoTokens.Palette.secondary)
                Text(model.title).font(WegoTokens.Typography.section)
                ForEach(model.courses) { course in
                    VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
                        Text(course.title).font(WegoTokens.Typography.section)
                        Text(course.stopNames.joined(separator: " → ")).font(WegoTokens.Typography.body)
                    }
                }
                participants
            }.padding(WegoTokens.Space.screen)
        }
        .background(WegoTokens.Palette.background).foregroundStyle(WegoTokens.Palette.text)
        .navigationTitle("여행 기록").navigationBarTitleDisplayMode(.inline)
        .toolbar { ToolbarItem(placement: .confirmationAction) { Button("닫기") { showingRecord = false } } }
    }

    private var completionSummary: String {
        let counts = "일행 \(model.memberCount)명 · 차량 \(model.carCount)대"
        return model.completedCarCount.map {
            let scope = model.isPreview ? "" : "표시된 경로 기준 "
            return "\(counts) · \(scope)완료한 차 \($0)/\(model.carCount)"
        } ?? counts
    }

    private func courseSummary(_ course: TripCompletedModel.Course) -> String {
        var values = [String]()
        if let addedByName = course.addedByName { values.append("\(addedByName) 추가") }
        values.append("장소 \(course.stopCount)곳")
        if let completed = course.completedCarCount { values.append("완료한 차 \(completed)/\(model.carCount)") }
        return values.joined(separator: " · ")
    }
}
