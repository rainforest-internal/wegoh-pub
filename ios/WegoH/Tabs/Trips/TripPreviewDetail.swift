import SwiftUI

struct TripPreviewDetail: View {
    let trip: TripPreview

    var body: some View {
        Group {
        if trip.state == .completed {
            TripCompletedView(model: TripCompletedModel(preview: trip))
        } else if trip.state == .active || (trip.state == .planned && trip.preparation != nil) {
            TripPreparationView(preview: trip)
        } else {
            summary
        }
        }.toolbar(.hidden, for: .tabBar)
    }

    private var summary: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: WegoTokens.Space.large) {
                TripPreviewHeading(status: trip.state.label, title: trip.title,
                                   subtitle: "\(trip.dateLabel) · 만든 사람 \(trip.ownerName)",
                                   titleIdentifier: "tripDetailTitle")

                Text(trip.summary)
                    .font(WegoTokens.Typography.body)

                VStack(alignment: .leading, spacing: WegoTokens.Space.medium) {
                    Text("여행 경로")
                        .font(WegoTokens.Typography.section)
                        .accessibilityAddTraits(.isHeader)
                    ForEach(trip.stops.indices, id: \.self) { index in
                        HStack(alignment: .firstTextBaseline, spacing: WegoTokens.Space.medium) {
                            Text("\(index + 1)")
                                .font(WegoTokens.Typography.section.monospacedDigit())
                                .foregroundStyle(WegoTokens.Palette.accent)
                            Text(trip.stops[index])
                                .font(WegoTokens.Typography.body)
                        }
                        .accessibilityElement(children: .combine)
                    }
                }

                Divider().overlay(WegoTokens.Palette.divider)

                VStack(alignment: .leading, spacing: WegoTokens.Space.medium) {
                    LabeledContent("일행 \(trip.memberCount)명", value: trip.members.joined(separator: ", "))
                    LabeledContent("차량 \(trip.carCount)대", value: trip.cars.joined(separator: ", "))
                }
                .font(WegoTokens.Typography.label)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(WegoTokens.Space.large)
        }
        .foregroundStyle(WegoTokens.Palette.text)
        .background(WegoTokens.Palette.background)
        .navigationTitle("샘플 여행")
        .navigationBarTitleDisplayMode(.inline)
    }
}

private struct TripPreviewHeading: View {
    let status: String
    let title: String
    let subtitle: String
    let titleIdentifier: String

    var body: some View {
        VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
            Text(status)
                .font(WegoTokens.Typography.label.weight(.semibold))
                .foregroundStyle(WegoTokens.Palette.accent)
            Text(title)
                .font(WegoTokens.Typography.hero)
                .foregroundStyle(WegoTokens.Palette.text)
                .accessibilityAddTraits(.isHeader)
                .accessibilityIdentifier(titleIdentifier)
            Text(subtitle)
                .font(WegoTokens.Typography.label)
                .foregroundStyle(WegoTokens.Palette.secondary)
        }
    }
}
