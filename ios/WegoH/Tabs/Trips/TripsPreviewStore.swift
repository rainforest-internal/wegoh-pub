import Observation

struct AcceptedTripPreview: Identifiable {
    let invitation: TripPreviewInvitation
    let locationConsent: Bool
    var id: String { invitation.id }
}

@Observable
final class TripsPreviewStore {
    private(set) var invitations: [TripPreviewInvitation]
    let myTrips: [TripPreview]
    let pastTrips: [TripPreview]
    private(set) var accepted: [AcceptedTripPreview] = []

    init(invitations: [TripPreviewInvitation] = TripPreviewData.invitations,
         myTrips: [TripPreview] = TripPreviewData.myTrips,
         pastTrips: [TripPreview] = TripPreviewData.pastTrips) {
        self.invitations = invitations
        self.myTrips = myTrips
        self.pastTrips = pastTrips
    }

    func accept(_ invitation: TripPreviewInvitation, locationConsent: Bool) {
        guard invitations.contains(where: { $0.id == invitation.id }) else { return }
        invitations.removeAll { $0.id == invitation.id }
        accepted.append(AcceptedTripPreview(invitation: invitation, locationConsent: true))
    }

    func decline(_ invitation: TripPreviewInvitation) {
        invitations.removeAll { $0.id == invitation.id }
    }
}
