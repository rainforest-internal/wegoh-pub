import Foundation

enum FriendRelationship: String, Decodable {
    case friend, incoming, outgoing, blocked, none
    case selfAccount = "self"
}

struct FriendPerson: Identifiable, Decodable, Equatable {
    let id: String
    let name: String?
    let handle: String?
    var relationship: FriendRelationship? = nil
    var direction: String? = nil
    var available: Bool? = nil
    var displayName: String { name ?? "사용할 수 없는 계정" }
    var code: String { handle.map { "@" + $0 } ?? "" }
    var isValid: Bool {
        validFriendID(id) && (name.map { !$0.isEmpty && $0.count <= 64 } ?? (available == false))
            && (handle.map { normalizedFriendCode($0) == $0 } ?? true)
    }
}

struct FriendsOverview: Decodable {
    var friends: [FriendPerson]
    var requests: [FriendPerson]
    var blocks: [FriendPerson]
}

struct FriendProfile: Decodable {
    let name: String
    let plateNumbers: [String]
}

enum FriendAction: Equatable {
    case request, accept, decline, cancel, disconnect, block, unblock
}

protocol IPhoneFriendsServing {
    func overview(token: String) async throws -> FriendsOverview
    func search(code: String, token: String) async throws -> FriendPerson?
    func perform(_ action: FriendAction, person: FriendPerson, token: String) async throws -> FriendRelationship
    func profile(_ person: FriendPerson, token: String) async throws -> FriendProfile
}

func normalizedFriendCode(_ value: String) -> String? {
    guard value.utf8.allSatisfy({ $0 < 128 }) else { return nil }
    var value = value.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
    if value.hasPrefix("@") { value.removeFirst() }
    return value.range(of: #"\A[a-z0-9][a-z0-9_.]{2,19}\z"#, options: .regularExpression) != nil ? value : nil
}

private func validFriendID(_ value: String) -> Bool {
    value.range(of: #"\Ateam-[a-f0-9]{40}\z"#, options: .regularExpression) != nil
}

final class IPhoneFriendsAPI: IPhoneFriendsServing {
    private let http: IPhoneSessionAPI
    init(configuration: URLSessionConfiguration? = nil) { http = IPhoneSessionAPI(configuration: configuration) }

    func overview(token: String) async throws -> FriendsOverview {
        let value: FriendsOverview = try decode(await http.resource("friends", token: token))
        let all = value.friends + value.requests + value.blocks
        guard all.count <= 10000, all.allSatisfy(\.isValid),
              Set(all.map(\.id)).count == all.count,
              (value.friends + value.requests).allSatisfy({ $0.name != nil && $0.handle != nil }),
              value.requests.allSatisfy({ ["incoming", "outgoing"].contains($0.direction) }) else {
            throw IPhoneSessionError.invalidResponse
        }
        return value
    }

    func search(code: String, token: String) async throws -> FriendPerson? {
        guard let code = normalizedFriendCode(code) else { throw IPhoneResourceError.invalidInput }
        var parts = URLComponents()
        parts.queryItems = [URLQueryItem(name: "handle", value: code)]
        struct Result: Decodable { let person: FriendPerson? }
        let result: Result = try decode(await http.resource("friends/search?" + (parts.percentEncodedQuery ?? ""), token: token))
        if let person = result.person {
            guard person.isValid, person.handle == code, person.name != nil, person.relationship != nil,
                  person.relationship != .blocked else { throw IPhoneSessionError.invalidResponse }
        }
        return result.person
    }

    func perform(_ action: FriendAction, person: FriendPerson, token: String) async throws -> FriendRelationship {
        guard validFriendID(person.id) else { throw IPhoneResourceError.invalidInput }
        let path: String, method: String, body: [String: Any]
        switch action {
        case .request: (path, method, body) = ("friends/requests", "POST", ["targetId": person.id])
        case .accept, .decline:
            (path, method, body) = ("friends/requests/\(person.id)/respond", "POST", ["accept": action == .accept])
        case .cancel, .disconnect: (path, method, body) = ("friends/\(person.id)", "DELETE", [:])
        case .block: (path, method, body) = ("blocks", "POST", ["targetId": person.id])
        case .unblock: (path, method, body) = ("blocks/\(person.id)", "DELETE", [:])
        }
        let status = action == .request || action == .block ? 201 : 200
        let data = try await http.resource(path, method: method, payload: JSONSerialization.data(withJSONObject: body),
                                           token: token, status: status, alternateStatus: 200)
        struct Receipt: Decodable { let status: String }
        let receipt: Receipt = try decode(data)
        let expected: [String] = switch action {
        case .request: ["pending", "accepted"]
        case .accept: ["accepted"]
        case .decline: ["declined"]
        case .cancel, .disconnect: ["removed"]
        case .block: ["blocked"]
        case .unblock: ["unblocked"]
        }
        guard expected.contains(receipt.status) else { throw IPhoneSessionError.invalidResponse }
        switch receipt.status {
        case "pending": return .outgoing
        case "accepted": return .friend
        case "blocked": return .blocked
        default: return .none
        }
    }

    func profile(_ person: FriendPerson, token: String) async throws -> FriendProfile {
        guard validFriendID(person.id) else { throw IPhoneResourceError.invalidInput }
        let value: FriendProfile = try decode(await http.resource("friends/\(person.id)/profile", token: token))
        guard !value.name.isEmpty, value.name.count <= 64, value.plateNumbers.count <= 100,
              value.plateNumbers.allSatisfy({ !$0.isEmpty && $0.count <= 16 }) else { throw IPhoneSessionError.invalidResponse }
        return value
    }

    private func decode<T: Decodable>(_ data: Data) throws -> T {
        do { return try JSONDecoder().decode(T.self, from: data) }
        catch { throw IPhoneSessionError.invalidResponse }
    }
}

func friendErrorMessage(_ error: Error) -> String {
    switch error {
    case IPhoneResourceError.invalidInput: "친구 코드를 확인해 주세요. 영문·숫자·밑줄·마침표로 된 3~20자 코드예요."
    case IPhoneResourceError.conflict: "친구 요청 상태가 바뀌었어요. 친구 목록을 새로고침해 주세요."
    case IPhoneResourceError.missing: "현재 친구 또는 요청을 찾을 수 없어요. 친구 목록을 새로고침해 주세요."
    case IPhoneSessionError.forbidden: "친구 기능 권한이 없어요. 설정에서 로그아웃한 뒤 다시 로그인해 주세요."
    case IPhoneResourceError.unavailable, IPhoneSessionError.unavailable: "친구 서버에 연결할 수 없어요. 잠시 후 다시 시도해 주세요."
    case IPhoneSessionError.invalidResponse: "서버의 친구 응답을 확인할 수 없어요. 다시 시도해 주세요."
    default: (error as? LocalizedError)?.errorDescription ?? "친구 요청을 처리하지 못했어요. 다시 시도해 주세요."
    }
}
