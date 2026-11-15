import Foundation

struct IPhoneProfile: Decodable, Equatable {
    let id: String
    var displayName: String
    var handle: String
}

struct IPhoneVehicleProfile: Decodable, Equatable, Identifiable {
    let deviceId: String
    var plateNumber: String
    /// The owner's chosen name; empty follows `defaultName` ("{계정 이름}의 차").
    var name: String
    var defaultName: String
    var revision: Int
    var id: String { deviceId }
    var displayName: String { name.isEmpty ? defaultName : name }
}

struct ProfileVehicle: Equatable, Identifiable {
    var profile: IPhoneVehicleProfile
    var id: String { profile.deviceId }
    var name: String { profile.displayName }
}

protocol IPhoneProfileServing {
    func profile(token: String) async throws -> IPhoneProfile
    func vehicles(token: String) async throws -> [ProfileVehicle]
    func name(_ name: String, expected: String, token: String) async throws -> String
    func handle(_ handle: String, expected: String, token: String) async throws -> String
    func vehicle(_ id: String, token: String) async throws -> IPhoneVehicleProfile
    func plate(_ plate: String, vehicle: IPhoneVehicleProfile, token: String) async throws -> IPhoneVehicleProfile
    func vehicleName(_ name: String, vehicle: IPhoneVehicleProfile, token: String) async throws -> IPhoneVehicleProfile
}

struct IPhoneProfileAPI: IPhoneProfileServing {
    private let http: IPhoneSessionAPI
    init(configuration: URLSessionConfiguration? = nil) { http = IPhoneSessionAPI(configuration: configuration) }

    func profile(token: String) async throws -> IPhoneProfile {
        struct Result: Decodable { let user: IPhoneProfile }
        let result: Result = try decode(await http.resource("profile", token: token))
        guard result.user.id.range(of: #"\Ateam-[0-9a-f]{40}\z"#, options: .regularExpression) != nil,
              !result.user.displayName.isEmpty, result.user.displayName.unicodeScalars.count <= 64,
              ProfileField.handle.valid(result.user.handle) else { throw IPhoneSessionError.invalidResponse }
        return result.user
    }

    func vehicles(token: String) async throws -> [ProfileVehicle] {
        struct Result: Decodable { let devices: [LinkedVehicle] }
        let list: Result = try decode(await http.resource("vehicles", token: token))
        guard list.devices.count <= 100, Set(list.devices.map(\.id)).count == list.devices.count else {
            throw IPhoneSessionError.invalidResponse
        }
        var result: [ProfileVehicle] = []
        for vehicle in list.devices {
            guard validDeviceID(vehicle.id), !vehicle.name.isEmpty else { throw IPhoneSessionError.invalidResponse }
            result.append(ProfileVehicle(profile: try await self.vehicle(vehicle.id, token: token)))
        }
        return result
    }

    func name(_ name: String, expected: String, token: String) async throws -> String {
        guard ProfileField.name.valid(name) else { throw IPhoneResourceError.invalidInput }
        struct Result: Decodable { struct User: Decodable { let displayName: String }; let user: User }
        let value: Result = try decode(await http.resource("profile", method: "PUT",
            payload: JSONEncoder().encode(["displayName": name, "expectedDisplayName": expected]), token: token))
        guard value.user.displayName == name else { throw IPhoneSessionError.invalidResponse }
        return value.user.displayName
    }

    func handle(_ handle: String, expected: String, token: String) async throws -> String {
        guard ProfileField.handle.valid(handle) else { throw IPhoneResourceError.invalidInput }
        struct Result: Decodable { let handle: String }
        let value: Result = try decode(await http.resource("profile/handle", method: "PUT",
            payload: JSONEncoder().encode(["handle": handle, "expectedHandle": expected]), token: token))
        guard value.handle == handle else { throw IPhoneSessionError.invalidResponse }
        return value.handle
    }

    func vehicle(_ id: String, token: String) async throws -> IPhoneVehicleProfile {
        guard validDeviceID(id) else { throw IPhoneResourceError.invalidInput }
        let profile: IPhoneVehicleProfile = try decode(await http.resource("vehicles/\(id)/profile", token: token))
        try validate(profile, device: id)
        return profile
    }

    func plate(_ plate: String, vehicle: IPhoneVehicleProfile, token: String) async throws -> IPhoneVehicleProfile {
        try await save(plate: plate, name: vehicle.name, vehicle: vehicle, token: token)
    }

    func vehicleName(_ name: String, vehicle: IPhoneVehicleProfile, token: String) async throws -> IPhoneVehicleProfile {
        try await save(plate: vehicle.plateNumber, name: name, vehicle: vehicle, token: token)
    }

    /// Plate and name share one revision; each edit resends the other field unchanged.
    private func save(plate: String, name: String, vehicle: IPhoneVehicleProfile, token: String) async throws -> IPhoneVehicleProfile {
        guard ProfileField.plate.valid(plate), ProfileField.vehicleName.valid(name), validDeviceID(vehicle.deviceId),
              vehicle.revision < 2_147_483_647 else {
            throw IPhoneResourceError.invalidInput
        }
        struct Request: Encodable { let plateNumber: String; let name: String; let expectedRevision: Int }
        let value: IPhoneVehicleProfile = try decode(await http.resource("vehicles/\(vehicle.deviceId)/profile", method: "PUT",
            payload: JSONEncoder().encode(Request(plateNumber: plate, name: name, expectedRevision: vehicle.revision)), token: token))
        try validate(value, device: vehicle.deviceId)
        guard value.plateNumber == plate, value.name == name, value.revision == vehicle.revision + 1 else {
            throw IPhoneSessionError.invalidResponse
        }
        return value
    }

    private func validDeviceID(_ id: String) -> Bool {
        id.range(of: #"\A[a-f0-9]{32}\z"#, options: .regularExpression) != nil
    }
    private func validate(_ value: IPhoneVehicleProfile, device: String) throws {
        guard value.deviceId == device, ProfileField.plate.valid(value.plateNumber), ProfileField.vehicleName.valid(value.name),
              !value.defaultName.isEmpty, value.defaultName.unicodeScalars.count <= 80,
              (0...2_147_483_647).contains(value.revision) else { throw IPhoneSessionError.invalidResponse }
    }
    private func decode<T: Decodable>(_ data: Data) throws -> T {
        do { return try JSONDecoder().decode(T.self, from: data) }
        catch { throw IPhoneSessionError.invalidResponse }
    }
}

enum ProfileField: String, Identifiable {
    case name, handle, plate, vehicleName
    var id: String { rawValue }
    var title: String {
        switch self { case .name: "이름"; case .handle: "친구 코드"; case .plate: "차량 번호"; case .vehicleName: "차량 이름" }
    }
    var hint: String {
        switch self {
        case .name: "이름은 1~30자로 입력해 주세요."
        case .handle: "영문 소문자·숫자·밑줄(_)·점(.)으로 3~20자를 입력해 주세요. 첫 글자는 영문 소문자나 숫자여야 해요. 변경 후 24시간 동안 다시 바꿀 수 없어요."
        case .plate: "한글과 숫자로 입력해 주세요. 비워서 저장하면 등록한 번호를 지워요."
        case .vehicleName: "20자 이내로 입력해 주세요. 비워서 저장하면 기본 이름으로 돌아가요. 연결 차량 목록과 리모컨에 이 이름이 보여요."
        }
    }
    func normalized(_ text: String) -> String {
        let value = text.trimmingCharacters(in: .whitespacesAndNewlines)
        return self == .handle ? String(value.hasPrefix("@") ? value.dropFirst() : Substring(value)).lowercased() : value
    }
    func filteredInput(_ text: String) -> String {
        guard self == .handle else { return text }
        return text.filter { $0.isASCII && ($0.isLetter || $0.isNumber || $0 == "_" || $0 == ".") }.lowercased()
    }
    func valid(_ value: String) -> Bool {
        switch self {
        case .name:
            return (1...30).contains(value.unicodeScalars.count) && value == normalized(value) &&
                !value.unicodeScalars.contains { [.control, .format, .surrogate, .privateUse, .unassigned].contains($0.properties.generalCategory) }
        case .handle: return value.range(of: #"\A[a-z0-9][a-z0-9_.]{2,19}\z"#, options: .regularExpression) != nil
        case .plate: return value.isEmpty || (value.range(of: #"\A[0-9가-힣]{2,16}\z"#, options: .regularExpression) != nil && value.contains(where: { $0.isASCII && $0.isNumber }))
        case .vehicleName:
            return value.isEmpty || (value.unicodeScalars.count <= 20 && value == normalized(value) &&
                !value.unicodeScalars.contains { [.control, .format, .surrogate, .privateUse, .unassigned, .lineSeparator, .paragraphSeparator].contains($0.properties.generalCategory) })
        }
    }
}

func profileErrorMessage(_ error: Error) -> String {
    switch error {
    case IPhoneResourceError.conflict: "다른 곳에서 변경됐거나 이미 사용 중인 친구 코드예요. 프로필을 새로고침한 뒤 확인해 주세요."
    case IPhoneResourceError.missing: "차량 연결이 변경됐어요. 프로필을 새로고침해 주세요."
    case IPhoneResourceError.invalidInput: "입력 내용을 확인해 주세요."
    case IPhoneSessionError.forbidden: "프로필 수정 권한이 추가되기 전 로그인이에요. 로그아웃 후 다시 로그인해 주세요."
    default: (error as? LocalizedError)?.errorDescription ?? "프로필을 처리할 수 없어요. 다시 시도해 주세요."
    }
}
