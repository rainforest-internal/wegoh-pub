struct TripPreviewInvitation: Identifiable, Hashable {
    let id: String
    let title: String
    let ownerName: String
}

struct TripPreparingCarPreview: Identifiable {
    let id: String
    let title: String
    let driverName: String
    let members: [String]
    let passengerCapacity: Int
}

struct TripCarRider: Identifiable, Equatable {
    let id: String
    let name: String
    let isDriver: Bool
    let isMe: Bool
    let role: IPhoneTripRole?
}

struct TripPreparingCoursePreview: Identifiable {
    let id: String
    let title: String
    let addedBy: String
    let stops: [String]
}

struct TripPreparationPreviewData {
    let invitationCount: Int
    let acceptedInvitationCount: Int
    let selectedCarID: String?
    let allMembersAssigned: Bool
    let pickupName: String?
    let dropoffName: String?
    let cars: [TripPreparingCarPreview]
    let courses: [TripPreparingCoursePreview]
}

struct TripPreview: Identifiable {
    enum State {
        case planned, active, completed, cancelled

        var label: String {
            switch self {
            case .planned: "준비 중"
            case .active: "진행 중"
            case .completed: "종료"
            case .cancelled: "취소"
            }
        }
    }

    let id: String
    let title: String
    let state: State
    let dateLabel: String
    let ownerName: String
    let members: [String]
    let cars: [String]
    let summary: String
    let stops: [String]
    var preparation: TripPreparationPreviewData? = nil

    var memberCount: Int { members.count }
    var carCount: Int { cars.count }
}

enum TripPreviewData {
    static let invitations = [
        TripPreviewInvitation(id: "jeju", title: "제주 동쪽 한 바퀴", ownerName: "사용자C")
    ]

    static let myTrips = [
        TripPreview(
            id: "gangneung", title: "서해안 드라이브", state: .active,
            dateLabel: "11월 12일–13일", ownerName: "사용자A",
            members: ["사용자A", "사용자C", "사용자D", "사용자B", "사용자E"], cars: ["사용자A의 차", "사용자B의 차"],
            summary: "간월암에서 꽃지해수욕장을 지나 대천해수욕장까지, 서해안 바다를 함께 달려요.",
            stops: ["간월암", "꽃지해수욕장", "대천해수욕장"],
            preparation: TripPreparationPreviewData(
                invitationCount: 4, acceptedInvitationCount: 4, selectedCarID: "user-f-car", allMembersAssigned: true,
                pickupName: nil, dropoffName: nil,
                cars: [TripPreparingCarPreview(id: "user-f-car", title: "사용자A의 차", driverName: "사용자A", members: ["사용자A", "사용자C", "사용자D"], passengerCapacity: 4),
                       TripPreparingCarPreview(id: "user-j-car", title: "사용자B의 차", driverName: "사용자B", members: ["사용자B", "사용자E"], passengerCapacity: 1)],
                courses: [TripPreparingCoursePreview(id: "gyeongpo-lake", title: "간월호 한 바퀴", addedBy: "사용자A", stops: ["간월호"]),
                          TripPreparingCoursePreview(id: "gangneung-coast", title: "서해안 해안도로 코스", addedBy: "사용자A", stops: ["간월암", "꽃지해수욕장", "대천해수욕장"]),
                          TripPreparingCoursePreview(id: "jumunjin-coast", title: "보령 해안도로", addedBy: "사용자B", stops: ["대천해수욕장", "무창포해수욕장"])])
        ),
        TripPreview(
            id: "yangpyeong", title: "양평 두물머리 나들이", state: .planned,
            dateLabel: "날짜 미정", ownerName: "사용자D",
            members: ["사용자D", "사용자A", "사용자E"], cars: ["사용자D의 차"],
            summary: "두물머리 강변을 산책하고 양수리에서 늦은 점심을 먹기로 했어요.",
            stops: ["두물머리", "세미원", "양수리전통시장"],
            preparation: TripPreparationPreviewData(
                invitationCount: 2, acceptedInvitationCount: 2,
                selectedCarID: "user-i-car", allMembersAssigned: true,
                pickupName: nil, dropoffName: nil,
                cars: [TripPreparingCarPreview(id: "user-i-car", title: "사용자D의 차", driverName: "사용자D",
                                               members: ["사용자D", "사용자A", "사용자E"], passengerCapacity: 4)],
                courses: [TripPreparingCoursePreview(id: "yangpyeong-river", title: "두물머리 강변 산책",
                                                     addedBy: "사용자D", stops: ["두물머리", "세미원", "양수리전통시장"])])
        ),
        TripPreview(
            id: "gapyeong", title: "가평 숲길 드라이브", state: .planned,
            dateLabel: "날짜 미정", ownerName: "사용자B",
            members: ["사용자B", "사용자C", "사용자A", "사용자D", "사용자E"],
            cars: ["사용자B의 차", "사용자A의 차"],
            summary: "두 대의 차로 아침고요수목원과 청평호를 함께 돌아봐요.",
            stops: ["아침고요수목원", "청평호", "자라섬"],
            preparation: TripPreparationPreviewData(
                invitationCount: 4, acceptedInvitationCount: 4,
                selectedCarID: "user-f-car", allMembersAssigned: true,
                pickupName: nil, dropoffName: nil,
                cars: [
                    TripPreparingCarPreview(id: "user-j-car", title: "사용자B의 차", driverName: "사용자B",
                                            members: ["사용자B", "사용자C"], passengerCapacity: 4),
                    TripPreparingCarPreview(id: "user-f-car", title: "사용자A의 차", driverName: "사용자A",
                                            members: ["사용자A", "사용자D", "사용자E"], passengerCapacity: 4)
                ],
                courses: [TripPreparingCoursePreview(id: "gapyeong-forest", title: "가평 숲과 호수길",
                                                     addedBy: "사용자B", stops: ["아침고요수목원", "청평호", "자라섬"])])
        ),
        TripPreview(
            id: "new-trip", title: "처음 준비하는 여행", state: .planned,
            dateLabel: "날짜 미정", ownerName: "사용자E", members: ["사용자E"], cars: [],
            summary: "차량과 경로가 없는 처음 상태를 확인하는 샘플이에요.", stops: [],
            preparation: TripPreparationPreviewData(invitationCount: 0, acceptedInvitationCount: 0,
                selectedCarID: nil, allMembersAssigned: false, pickupName: nil, dropoffName: nil,
                cars: [], courses: [])
        )
    ]

    static let pastTrips = [
        TripPreview(
            id: "suwon", title: "수원 화성 산책", state: .completed,
            dateLabel: "10월 24일 (토)", ownerName: "사용자D",
            members: ["사용자D", "사용자E", "사용자A", "사용자B", "사용자C"], cars: ["사용자D의 차", "사용자B의 차"],
            summary: "장안문에서 성곽길을 걷고 행궁동 골목에서 저녁을 함께했어요.",
            stops: ["장안문", "화홍문", "행궁동"]
        )
    ]
}
