import Foundation
import Observation

@MainActor
@Observable
final class ProfileLoadStore {
    var profile: IPhoneProfile?
    var vehicles: [ProfileVehicle] = []
    private(set) var profileLoading = false
    private(set) var vehiclesLoading = false
    private(set) var hasLoadedVehicles = false
    private(set) var error: String?
    private(set) var vehicleError: String?
    private var operation: UUID?

    var isLoading: Bool { profileLoading || vehiclesLoading }

    func load(session: SessionManager, account: AccountSession, api: any IPhoneProfileServing) async {
        let stamp = UUID()
        operation = stamp
        profileLoading = true
        vehiclesLoading = true
        error = nil
        vehicleError = nil
        async let profileRead = readProfile(session: session, account: account, api: api, stamp: stamp)
        async let vehiclesRead: Void = readVehicles(session: session, account: account, api: api, stamp: stamp)
        let value = await profileRead
        await vehiclesRead
        guard operation == stamp, session.phase == .signedIn, session.current == account, let value else { return }
        session.updateDisplayName(value.displayName, for: account)
    }

    private func readProfile(session: SessionManager, account: AccountSession, api: any IPhoneProfileServing,
                             stamp: UUID) async -> IPhoneProfile? {
        defer { if operation == stamp { profileLoading = false } }
        do {
            let value = try await session.withToken(for: account) { try await api.profile(token: $0) }
            guard operation == stamp, value.id == account.accountID else { return nil }
            profile = value
            return value
        } catch is CancellationError { }
        catch {
            if operation == stamp, session.phase == .signedIn, session.current == account {
                self.error = profileErrorMessage(error)
            }
        }
        return nil
    }

    private func readVehicles(session: SessionManager, account: AccountSession, api: any IPhoneProfileServing,
                              stamp: UUID) async {
        defer { if operation == stamp { vehiclesLoading = false } }
        do {
            let items = try await session.withToken(for: account) { try await api.vehicles(token: $0) }
            guard operation == stamp else { return }
            vehicles = items
            hasLoadedVehicles = true
        } catch is CancellationError { }
        catch {
            if operation == stamp, session.phase == .signedIn, session.current == account {
                vehicleError = profileErrorMessage(error)
            }
        }
    }
}
