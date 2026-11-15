#if DEBUG
import SwiftUI

struct TripCarCreateUIFixture: View {
    @State private var vehicles: [ProfileVehicle] = []

    var body: some View {
        TripCarCreateView(vehicles: vehicles, suggestedName: "사용자D의 차", reloadVehicles: { await loadVehicles() }) { _, _, _ in }
            .task { await loadVehicles() }
    }

    private func loadVehicles() async {
        let api = IPhoneProfileAPI(configuration: CourseUIFixture.configuration())
        vehicles = (try? await api.vehicles(token: String(repeating: "F", count: 43))) ?? []
    }
}
#endif
