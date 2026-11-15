import Foundation
import Observation

@MainActor
@Observable
final class FriendsStore {
    private(set) var friends: [FriendPerson] = []
    private(set) var incoming: [FriendPerson] = []
    private(set) var outgoing: [FriendPerson] = []
    private(set) var blocked: [FriendPerson] = []
    private(set) var isLoading = false
    private(set) var hasLoaded = false
    private(set) var isMutating = false
    private(set) var error: String?
    let api: any IPhoneFriendsServing
    private var read: UUID?
    private var relationships: [String: FriendRelationship] = [:]

    init(api: any IPhoneFriendsServing = IPhoneFriendsAPI()) { self.api = api }

    func load(session: SessionManager, account: AccountSession) async {
        guard !isLoading, !isMutating, session.current == account else { return }
        let stamp = UUID()
        read = stamp; isLoading = true; error = nil
        defer { if read == stamp { isLoading = false } }
        do {
            let value = try await session.withToken(for: account) { try await api.overview(token: $0) }
            guard read == stamp else { return }
            friends = value.friends
            incoming = value.requests.filter { $0.direction == "incoming" }
            outgoing = value.requests.filter { $0.direction == "outgoing" }
            blocked = value.blocks
            relationships = [:]
            for item in friends { relationships[item.id] = .friend }
            for item in incoming { relationships[item.id] = .incoming }
            for item in outgoing { relationships[item.id] = .outgoing }
            for item in blocked { relationships[item.id] = .blocked }
            hasLoaded = true
        } catch is CancellationError { }
        catch { if read == stamp, session.current == account { self.error = friendErrorMessage(error) } }
    }

    func search(code: String, session: SessionManager, account: AccountSession) async throws -> FriendPerson? {
        let person = try await session.withToken(for: account) { try await api.search(code: code, token: $0) }
        if let person { relationships[person.id] = person.relationship ?? FriendRelationship.none }
        return person
    }

    func relationship(to person: FriendPerson) -> FriendRelationship { relationships[person.id] ?? .none }

    @discardableResult
    func perform(_ action: FriendAction, person: FriendPerson, session: SessionManager, account: AccountSession) async -> Bool {
        guard !isMutating, session.current == account else { return false }
        read = nil; isLoading = false; isMutating = true; error = nil
        defer { isMutating = false }
        do {
            let relationship = try await session.withToken(for: account) { try await api.perform(action, person: person, token: $0) }
            friends.removeAll { $0.id == person.id }
            incoming.removeAll { $0.id == person.id }
            outgoing.removeAll { $0.id == person.id }
            blocked.removeAll { $0.id == person.id }
            switch relationship {
            case .friend: friends.append(person)
            case .outgoing: outgoing.append(person)
            case .blocked: blocked.append(person)
            default: break
            }
            relationships[person.id] = relationship
            return true
        } catch is CancellationError { return false }
        catch {
            if session.current == account { self.error = friendErrorMessage(error) }
            return false
        }
    }
}
