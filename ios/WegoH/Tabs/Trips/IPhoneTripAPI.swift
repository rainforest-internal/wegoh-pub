import Foundation

protocol IPhoneTripServing {
    func list(token: String) async throws -> IPhoneTripList
    func detail(_ tripID: String, token: String) async throws -> IPhoneTripDetail
    func create(_ draft: IPhoneTripDraft, token: String) async throws -> String
    func respond(_ tripID: String, accept: Bool, locationConsent: Bool, token: String) async throws
    func addMember(_ tripID: String, accountID: String, token: String) async throws
    func createCar(_ tripID: String, name: String, seats: Int, token: String) async throws -> String
    func createCar(_ tripID: String, name: String, seats: Int, remotePolicy: IPhoneTripRemotePolicy, token: String) async throws -> String
    func setRole(_ tripID: String, accountID: String, role: IPhoneTripRole, revision: Int, token: String) async throws
    func setRemotePolicy(_ tripID: String, carID: String, policy: IPhoneTripRemotePolicy, token: String) async throws
    func ride(_ tripID: String, carID: String, token: String) async throws
    func leaveCar(_ tripID: String, token: String) async throws
    func addCourse(_ tripID: String, packID: String, token: String) async throws
    func addCarPlace(_ tripID: String, carID: String, kind: IPhoneTripPlaceKind, name: String, lat: Double, lng: Double, token: String) async throws -> String
    func removeCarPlace(_ tripID: String, carID: String, placeID: String, token: String) async throws
    func saveMyPlaces(_ tripID: String, carID: String, draft: IPhoneTripMyPlacesDraft, token: String) async throws
    func prioritizeCourses(_ tripID: String, packIDs: [String], revision: Int, token: String) async throws
    func start(_ tripID: String, revision: Int, endActiveTrip: Bool, token: String) async throws
    func setLocationSharing(_ tripID: String, enabled: Bool, token: String) async throws
    func update(_ tripID: String, draft: IPhoneTripDraft, token: String) async throws
    func removeMember(_ tripID: String, accountID: String, token: String) async throws
    func cancel(_ tripID: String, revision: Int, token: String) async throws
    func finish(_ tripID: String, revision: Int, token: String) async throws
    func updateCar(_ tripID: String, carID: String, name: String, seats: Int, token: String) async throws
    func deleteCar(_ tripID: String, carID: String, token: String) async throws
    func removeCourse(_ tripID: String, packID: String, token: String) async throws
    func respondToRideInvitation(_ tripID: String, carID: String, invitationID: String, accept: Bool, token: String) async throws
    func locations(_ tripID: String, token: String) async throws -> IPhoneTripLocations
}

enum IPhoneTripRequestError: Error, LocalizedError {
    case invalidInput, conflict, missing, unavailable
    case routeConflict(String)

    var errorDescription: String? {
        switch self {
        case .routeConflict(let code):
            switch code {
            case "Account unavailable": "친구 관계나 계정 상태가 바뀌어 초대할 수 없어요. 친구 목록을 확인해 주세요."
            case "VEHICLE_CONTROL_UNSUPPORTED": "이 차량에서 지원하지 않는 조작이에요. 허용 범위를 다시 확인해 주세요."
            case "VEHICLE_CONTROL_AREA_UNSUPPORTED": "선택한 좌석은 이 조작을 지원하지 않아요. 지원하는 좌석을 선택해 주세요."
            case "VEHICLE_CONTROL_VALUE_UNSUPPORTED": "차량이 지원하는 설정 범위를 벗어났어요. 허용 범위를 다시 확인해 주세요."
            case "TRIP_ALREADY_ACTIVE": "이미 진행 중인 여행이 있어요. 기존 여행을 끝내고 시작할지 선택해 주세요."
            case "TRIP_MEMBER_ALREADY_ACTIVE": "다른 여행을 진행 중인 일행이 있어 시작할 수 없어요. 그 여행이 끝난 뒤 다시 시도해 주세요."
            case "TRIP_STATE_CONFLICT": "여행 단계가 바뀌어 이 작업을 할 수 없어요. 최신 여행 상태를 확인해 주세요."
            case "TRIP_CONTEXT_NOT_READY": "여행 연결 정보를 확인하지 못했어요. 잠시 후 목록을 새로고침해 주세요."
            case "TRIP_MEMBERSHIP_INCONSISTENT", "TRIP_MEMBERSHIP_CONFLICT": "여행 참여 정보가 맞지 않아 저장하지 못했어요. 목록을 새로고침한 뒤 다시 확인해 주세요."
            case "TRIP_REVISION_CONFLICT", "Route revision conflict": "여행 정보가 다른 곳에서 변경됐어요. 최신 내용을 불러온 뒤 다시 확인해 주세요."
            case "Vehicle owner required": "연결된 차량이 있어야 차를 만들 수 있어요. 설정에서 차량 연결을 확인해 주세요."
            case "Already driving": "이미 이 여행에서 운전할 차가 있어요. 기존 차를 확인해 주세요."
            // 리모컨을 받을 차량(리모컨 받기 켜짐)이 하나로 정해지지 않을 때. 새로고침으로는 바뀌지 않는다.
            case "Choose a vehicle for remote control": "차량에서 '리모컨 받기'를 켜면 허용할 수 있어요. 차량 앱 리모컨 탭에서 켠 뒤 다시 저장해 주세요."
            case "No vehicle ready for remote control": "지금은 차량 리모컨을 쓸 수 없어요. 잠시 후 다시 시도해 주세요."
            // 여행 리모컨 전송 시 차량 상태. 동승자가 다시 로그인해도 바뀌지 않는다.
            case "VEHICLE_REMOTE_RECEIVER_OFF": "차량이 리모컨을 받지 않고 있어요. 차량에서 '리모컨 받기'를 켜 달라고 운전자에게 알려 주세요."
            case "VEHICLE_REMOTE_DISCONNECTED": "차량 연결이 끊겨 리모컨을 보낼 수 없어요. 차량 앱 연결을 확인해 달라고 운전자에게 알려 주세요."
            case "Seats taken": "이미 탑승한 일행보다 좌석 수를 줄일 수 없어요."
            case "Car is full": "이 차에는 남은 자리가 없어요. 다른 차를 선택해 주세요."
            case "Trip is full": "이 여행은 참여 인원이 가득 차 더 참여할 수 없어요."
            case "Trip limit reached": "만들 수 있는 여행 수에 도달했어요. 준비·진행 중인 여행을 정리한 뒤 다시 시도해 주세요."
            case "Trip course limit": "여행에 추가할 수 있는 경로 수에 도달했어요. 기존 경로를 정리해 주세요."
            case "TRIP_ROUTE_PLAN_LOCKED": "출발한 여행의 타는 곳·내리는 곳과 경로는 바꿀 수 없어요."
            case "TRIP_PLACE_SELECTION_CHANGED": "승하차 선택이 바뀌었어요. 여행을 새로 불러온 뒤 선택을 확인해 주세요."
            case "TRIP_SIGNAL_JOIN_PENDING": "모든 차가 합류한 뒤 손들기를 이용할 수 있어요."
            case "TRIP_SIGNAL_ROUTE_FINISHED": "우리 차 경로가 끝나 새 손들기를 보낼 수 없어요."
            case "TRIP_SIGNAL_SHARED_FINISHED": "공유 경로가 끝나 새 손들기를 보낼 수 없어요."
            case "DRIVING_SCORE_PHASE_CONFLICT": "여행이나 우리 차 경로를 마친 뒤에 최종 점수를 보고할 수 있어요."
            default: "여행 상태가 바뀌었어요. 새로 불러온 뒤 확인해 주세요."
            }
        case .invalidInput: "여행에 입력한 내용을 확인해 주세요."
        case .conflict: "지금 상태에서는 이 요청을 처리할 수 없어요. 여행을 새로고침해 주세요."
        case .missing: "여행이나 선택한 항목을 찾을 수 없어요. 목록을 다시 확인해 주세요."
        case .unavailable: "여행 서버에 연결할 수 없어요. 잠시 후 다시 시도해 주세요."
        }
    }
}

final class IPhoneTripAPI: IPhoneTripServing {
    private struct IDReceipt: Decodable { let id: String }
    private struct StatusReceipt: Decodable { let status: String }
    private let http: IPhoneSessionAPI

    init(configuration: URLSessionConfiguration? = nil) {
        http = IPhoneSessionAPI(configuration: configuration)
    }

    func list(token: String) async throws -> IPhoneTripList {
        let value: IPhoneTripList = try await request("trips", token: token)
        guard value.isValid else { throw IPhoneSessionError.invalidResponse }
        return value
    }

    func detail(_ tripID: String, token: String) async throws -> IPhoneTripDetail {
        let value: IPhoneTripDetail = try await request(path(tripID), token: token)
        guard value.id == tripID, value.isValid else { throw IPhoneSessionError.invalidResponse }
        return value
    }

    func create(_ draft: IPhoneTripDraft, token: String) async throws -> String {
        guard draft.isValid else { throw IPhoneTripRequestError.invalidInput }
        var clean = draft
        clean.locationConsent = true
        clean.title = draft.title.trimmingCharacters(in: .whitespacesAndNewlines)
        clean.description = draft.description.trimmingCharacters(in: .whitespacesAndNewlines)
        let value: IDReceipt = try await request("trips", method: "POST", payload: JSONEncoder().encode(clean), token: token, status: 201)
        guard validTripID(value.id) else { throw IPhoneSessionError.invalidResponse }
        return value.id
    }

    func respond(_ tripID: String, accept: Bool, locationConsent: Bool, token: String) async throws {
        let payload = try JSONEncoder().encode(["accept": accept, "locationConsent": accept])
        let value: StatusReceipt = try await request(path(tripID) + "/respond", method: "POST", payload: payload, token: token)
        guard value.status == (accept ? "accepted" : "declined") else { throw IPhoneSessionError.invalidResponse }
    }

    func addMember(_ tripID: String, accountID: String, token: String) async throws {
        guard validTripAccountID(accountID) else { throw IPhoneTripRequestError.invalidInput }
        let value: StatusReceipt = try await request(path(tripID) + "/members", method: "POST",
            payload: JSONEncoder().encode(["accountId": accountID]), token: token, status: 201, alternateStatus: 200)
        guard ["pending", "accepted"].contains(value.status) else { throw IPhoneSessionError.invalidResponse }
    }

    func createCar(_ tripID: String, name: String, seats: Int, token: String) async throws -> String {
        guard validTripText(name, max: 20), (1...8).contains(seats) else { throw IPhoneTripRequestError.invalidInput }
        struct Car: Encodable { let name: String; let seats: Int }
        let body = Car(name: name.trimmingCharacters(in: .whitespacesAndNewlines), seats: seats)
        let value: IDReceipt = try await request(path(tripID) + "/cars", method: "POST", payload: JSONEncoder().encode(body), token: token, status: 201)
        guard validTripID(value.id) else { throw IPhoneSessionError.invalidResponse }
        return value.id
    }

    func ride(_ tripID: String, carID: String, token: String) async throws {
        guard validTripID(carID) else { throw IPhoneTripRequestError.invalidInput }
        let value: StatusReceipt = try await request(path(tripID) + "/cars/" + carID + "/ride", method: "PUT", payload: Data("{}".utf8), token: token)
        guard value.status == "riding" else { throw IPhoneSessionError.invalidResponse }
    }

    func leaveCar(_ tripID: String, token: String) async throws {
        let value: StatusReceipt = try await request(path(tripID) + "/ride", method: "DELETE", payload: Data("{}".utf8), token: token)
        guard value.status == "left" else { throw IPhoneSessionError.invalidResponse }
    }

    func addCourse(_ tripID: String, packID: String, token: String) async throws {
        guard validCourseID(packID) else { throw IPhoneTripRequestError.invalidInput }
        let value: StatusReceipt = try await request(path(tripID) + "/courses", method: "POST",
            payload: JSONEncoder().encode(["packId": packID]), token: token, status: 201, alternateStatus: 200)
        guard value.status == "added" else { throw IPhoneSessionError.invalidResponse }
    }

    func addCarPlace(_ tripID: String, carID: String, kind: IPhoneTripPlaceKind, name: String,
                     lat: Double, lng: Double, token: String) async throws -> String {
        guard validTripID(carID), kind != .signal, validTripText(name, max: 40), validTripCoordinates(lat: lat, lng: lng)
        else { throw IPhoneTripRequestError.invalidInput }
        struct Place: Encodable { let kind: IPhoneTripPlaceKind; let name: String; let lat: Double; let lng: Double }
        let body = Place(kind: kind, name: name.trimmingCharacters(in: .whitespacesAndNewlines), lat: lat, lng: lng)
        let value: IDReceipt = try await request(path(tripID) + "/cars/" + carID + "/places", method: "POST",
            payload: JSONEncoder().encode(body), token: token, status: 201)
        guard validTripID(value.id) else { throw IPhoneSessionError.invalidResponse }
        return value.id
    }

    func removeCarPlace(_ tripID: String, carID: String, placeID: String, token: String) async throws {
        guard validTripID(carID), validTripID(placeID) else { throw IPhoneTripRequestError.invalidInput }
        let value: StatusReceipt = try await request(path(tripID) + "/cars/" + carID + "/places/" + placeID,
            method: "DELETE", payload: Data("{}".utf8), token: token)
        guard value.status == "deleted" else { throw IPhoneSessionError.invalidResponse }
    }

    func start(_ tripID: String, revision: Int, endActiveTrip: Bool, token: String) async throws {
        guard (1...Int(Int32.max)).contains(revision) else { throw IPhoneTripRequestError.invalidInput }
        struct Body: Encodable {
            let revision: Int
            let routeContractVersion = 2
            let endActiveTrip: Bool?
        }
        struct Transition: Decodable { let tripId: String; let state: IPhoneTripState; let revision: Int }
        let value: Transition = try await request(path(tripID) + "/start", method: "POST",
            payload: JSONEncoder().encode(Body(revision: revision, endActiveTrip: endActiveTrip ? true : nil)), token: token)
        guard value.tripId == tripID, value.state == .active, (revision...Int(Int32.max)).contains(value.revision) else { throw IPhoneSessionError.invalidResponse }
    }

    func setLocationSharing(_ tripID: String, enabled: Bool, token: String) async throws {
        struct Sharing: Decodable { let locationConsent: Bool; let revision: Int }
        let value: Sharing = try await request(path(tripID) + "/location-sharing", method: "PATCH",
            payload: JSONEncoder().encode(["locationConsent": enabled]), token: token)
        guard value.locationConsent == enabled, value.revision > 0 else { throw IPhoneSessionError.invalidResponse }
    }

    func path(_ tripID: String) throws -> String {
        guard validTripID(tripID) else { throw IPhoneTripRequestError.invalidInput }
        return "trips/" + tripID
    }

    func request<Value: Decodable>(_ path: String, method: String = "GET", payload: Data? = nil,
                                            token: String, status: Int = 200, alternateStatus: Int? = nil) async throws -> Value {
        do {
            let data = try await http.resource(path, method: method, payload: payload, token: token,
                                               status: status, alternateStatus: alternateStatus)
            do { return try JSONDecoder().decode(Value.self, from: data) }
            catch { throw IPhoneSessionError.invalidResponse }
        } catch IPhoneResourceError.invalidInput { throw IPhoneTripRequestError.invalidInput }
        catch IPhoneResourceError.tripConflict(let code) { throw IPhoneTripRequestError.routeConflict(code) }
        catch IPhoneResourceError.conflict, IPhoneResourceError.vehicleLimit { throw IPhoneTripRequestError.conflict }
        catch IPhoneResourceError.missing { throw IPhoneTripRequestError.missing }
        catch IPhoneResourceError.unavailable, IPhoneSessionError.unavailable { throw IPhoneTripRequestError.unavailable }
    }
}

extension IPhoneTripServing {
    func update(_ tripID: String, draft: IPhoneTripDraft, token: String) async throws { throw TripPreparationError.previewUnsupported }
    func removeMember(_ tripID: String, accountID: String, token: String) async throws { throw TripPreparationError.previewUnsupported }
    func cancel(_ tripID: String, revision: Int, token: String) async throws { throw TripPreparationError.previewUnsupported }
    func finish(_ tripID: String, revision: Int, token: String) async throws { throw TripPreparationError.previewUnsupported }
    func updateCar(_ tripID: String, carID: String, name: String, seats: Int, token: String) async throws { throw TripPreparationError.previewUnsupported }
    func deleteCar(_ tripID: String, carID: String, token: String) async throws { throw TripPreparationError.previewUnsupported }
    func removeCourse(_ tripID: String, packID: String, token: String) async throws { throw TripPreparationError.previewUnsupported }
    func respondToRideInvitation(_ tripID: String, carID: String, invitationID: String, accept: Bool, token: String) async throws { throw TripPreparationError.previewUnsupported }
    func locations(_ tripID: String, token: String) async throws -> IPhoneTripLocations { throw TripPreparationError.previewUnsupported }
    func saveMyPlaces(_ tripID: String, carID: String, draft: IPhoneTripMyPlacesDraft, token: String) async throws { throw TripPreparationError.previewUnsupported }
    func prioritizeCourses(_ tripID: String, packIDs: [String], revision: Int, token: String) async throws { throw TripPreparationError.previewUnsupported }
    func createCar(_ tripID: String, name: String, seats: Int, remotePolicy: IPhoneTripRemotePolicy, token: String) async throws -> String {
        guard !remotePolicy.enabled else { throw TripPreparationError.previewUnsupported }
        return try await createCar(tripID, name: name, seats: seats, token: token)
    }
    func setRole(_ tripID: String, accountID: String, role: IPhoneTripRole, revision: Int, token: String) async throws { throw TripPreparationError.previewUnsupported }
    func setRemotePolicy(_ tripID: String, carID: String, policy: IPhoneTripRemotePolicy, token: String) async throws { throw TripPreparationError.previewUnsupported }
}

extension IPhoneTripAPI {
    func createCar(_ tripID: String, name: String, seats: Int, remotePolicy: IPhoneTripRemotePolicy, token: String) async throws -> String {
        guard validTripText(name, max: 20), (1...8).contains(seats), remotePolicy.isValid else { throw IPhoneTripRequestError.invalidInput }
        struct Body: Encodable { let name: String; let seats: Int; let remotePolicy: IPhoneTripRemotePolicy }
        struct Receipt: Decodable { let id: String }
        let receipt: Receipt = try await request(path(tripID) + "/cars", method: "POST",
            payload: JSONEncoder().encode(Body(name: name.trimmingCharacters(in: .whitespacesAndNewlines), seats: seats, remotePolicy: remotePolicy)), token: token, status: 201)
        guard validTripID(receipt.id) else { throw IPhoneSessionError.invalidResponse }
        return receipt.id
    }
    func setRole(_ tripID: String, accountID: String, role: IPhoneTripRole, revision: Int, token: String) async throws {
        guard validTripAccountID(accountID), (1...Int(Int32.max)).contains(revision) else { throw IPhoneTripRequestError.invalidInput }
        struct Body: Encodable { let role: IPhoneTripRole; let revision: Int }
        struct Receipt: Decodable { let status: String; let revision: Int }
        let receipt: Receipt = try await request(path(tripID) + "/members/" + accountID + "/role", method: "PUT",
            payload: JSONEncoder().encode(Body(role: role, revision: revision)), token: token)
        guard receipt.status == "updated", receipt.revision >= revision else { throw IPhoneSessionError.invalidResponse }
    }
    func setRemotePolicy(_ tripID: String, carID: String, policy: IPhoneTripRemotePolicy, token: String) async throws {
        guard validTripID(carID), policy.isValid else { throw IPhoneTripRequestError.invalidInput }
        struct Receipt: Decodable { let remotePolicy: IPhoneTripRemotePolicy }
        let receipt: Receipt = try await request(path(tripID) + "/cars/" + carID + "/remote-policy", method: "PUT",
            payload: JSONEncoder().encode(policy), token: token)
        guard receipt.remotePolicy.isValid, receipt.remotePolicy.enabled == policy.enabled,
              Set(receipt.remotePolicy.actions) == Set(policy.actions) else { throw IPhoneSessionError.invalidResponse }
    }
}

extension IPhoneTripAPI {
    func saveMyPlaces(_ tripID: String, carID: String, draft: IPhoneTripMyPlacesDraft, token: String) async throws {
        guard validTripID(carID), draft.isValid else { throw IPhoneTripRequestError.invalidInput }
        struct Receipt: Decodable {
            let revision: Int
            let routeRevision: Int
            let pickupPlaceId: String?
            let dropPlaceId: String?
            let dropAtPickup: Bool
            let status: String
            enum CodingKeys: String, CodingKey { case revision, routeRevision, pickupPlaceId, dropPlaceId, dropAtPickup, status }
            init(from decoder: Decoder) throws {
                let box = try decoder.container(keyedBy: CodingKeys.self)
                guard box.contains(.pickupPlaceId), box.contains(.dropPlaceId) else { throw IPhoneSessionError.invalidResponse }
                revision = try box.decode(Int.self, forKey: .revision)
                routeRevision = try box.decode(Int.self, forKey: .routeRevision)
                pickupPlaceId = try box.decodeIfPresent(String.self, forKey: .pickupPlaceId)
                dropPlaceId = try box.decodeIfPresent(String.self, forKey: .dropPlaceId)
                dropAtPickup = try box.decode(Bool.self, forKey: .dropAtPickup)
                status = try box.decode(String.self, forKey: .status)
            }
        }
        let value: Receipt = try await request(path(tripID) + "/cars/" + carID + "/my-places", method: "PUT",
            payload: JSONEncoder().encode(draft), token: token)
        guard (draft.revision...Int(Int32.max)).contains(value.revision), validTripRevision(value.routeRevision),
              ["updated", "unchanged"].contains(value.status),
              (value.pickupPlaceId.map(validTripID) ?? true), (value.dropPlaceId.map(validTripID) ?? true),
              (value.pickupPlaceId == nil) == (draft.pickup == nil),
              (value.dropPlaceId == nil) == (draft.drop == nil && !draft.dropAtPickup),
              !draft.dropAtPickup || value.dropAtPickup,
              !value.dropAtPickup || (value.pickupPlaceId != nil && value.dropPlaceId != nil)
        else { throw IPhoneSessionError.invalidResponse }
        if case .existing(let id) = draft.pickup, value.pickupPlaceId != id { throw IPhoneSessionError.invalidResponse }
        if case .existing(let id) = draft.drop, value.dropPlaceId != id { throw IPhoneSessionError.invalidResponse }
    }

    func prioritizeCourses(_ tripID: String, packIDs: [String], revision: Int, token: String) async throws {
        guard (2...10).contains(packIDs.count), packIDs.allSatisfy(validCourseID), Set(packIDs).count == packIDs.count,
              (1...Int(Int32.max)).contains(revision) else { throw IPhoneTripRequestError.invalidInput }
        struct Body: Encodable { let packIds: [String]; let revision: Int }
        struct Receipt: Decodable { let status: String; let revision: Int }
        let value: Receipt = try await request(path(tripID) + "/courses/priority", method: "PUT",
            payload: JSONEncoder().encode(Body(packIds: packIDs, revision: revision)), token: token)
        guard value.status == "updated", (revision...Int(Int32.max)).contains(value.revision) else { throw IPhoneSessionError.invalidResponse }
    }
}
