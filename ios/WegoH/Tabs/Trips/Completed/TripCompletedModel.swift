import Foundation

struct TripCompletedModel {
    struct Course: Identifiable {
        let id: String
        let title: String
        let addedByName: String?
        let stopNames: [String]
        let stopCount: Int
        let completedCarCount: Int?
    }

    struct Car: Identifiable {
        let id: String
        let name: String
        let memberNames: [String]
    }

    let title: String
    let dateLabel: String
    let ownerName: String
    let description: String
    let memberCount: Int
    let carCount: Int
    let completedCarCount: Int?
    let routeNames: [String]
    let courses: [Course]
    let cars: [Car]
    let unassignedNames: [String]
    let isPreview: Bool

    var allRoutesCompleted: Bool { isPreview && carCount > 0 && completedCarCount == carCount }

    init(detail: IPhoneTripDetail, isPreview: Bool = false, dateLabel: String? = nil) {
        title = detail.title
        self.dateLabel = dateLabel ?? tripDateLabel(start: detail.startDate, end: detail.endDate)
        ownerName = detail.members.first(where: \.isOwner)?.name ?? ""
        description = detail.description
        memberCount = detail.members.filter { $0.state == .accepted }.count
        carCount = detail.cars.count
        self.isPreview = isPreview
        courses = detail.courses.map { course in
            Course(id: course.id, title: course.title, addedByName: course.addedByName,
                   stopNames: course.stops?.map(\.name) ?? [], stopCount: course.stopCount,
                   completedCarCount: detail.cars.isEmpty ? nil : course.completedCarIds?.count)
        }
        routeNames = detail.courses.flatMap { $0.stops?.map(\.name) ?? [] }
        cars = detail.cars.map { Car(id: $0.id, name: detail.numberedName($0), memberNames: [$0.driverName] + $0.passengers.map(\.name)) }
        unassignedNames = detail.unassigned.map(\.name)
        if !detail.cars.isEmpty, !detail.courses.isEmpty, detail.courses.allSatisfy({ $0.completedCarIds != nil }) {
            completedCarCount = detail.courses.reduce(Set(detail.cars.map(\.id))) { cars, course in
                cars.intersection(course.completedCarIds ?? [])
            }.count
        } else { completedCarCount = nil }
    }

    init(preview: TripPreview) {
        if preview.id == "suwon" {
            title = preview.title
            dateLabel = preview.dateLabel
            ownerName = preview.ownerName
            description = preview.summary
            memberCount = preview.memberCount
            carCount = preview.carCount
            completedCarCount = 2
            routeNames = ["장안문", "화홍문", "행궁동"]
            courses = [Course(id: "suwon-fortress", title: "수원 화성 성곽길", addedByName: "사용자D",
                              stopNames: routeNames, stopCount: 3, completedCarCount: 2)]
            cars = [Car(id: "user-i-car", name: "사용자D의 차", memberNames: ["사용자D", "사용자E", "사용자A"]),
                    Car(id: "user-j-car", name: "사용자B의 차", memberNames: ["사용자B", "사용자C"])]
            unassignedNames = []
        } else {
            title = preview.title
            dateLabel = preview.dateLabel
            ownerName = preview.ownerName
            description = preview.summary
            memberCount = preview.memberCount
            carCount = preview.carCount
            completedCarCount = nil
            routeNames = preview.stops
            courses = (preview.preparation?.courses ?? []).map {
                Course(id: $0.id, title: $0.title, addedByName: $0.addedBy, stopNames: $0.stops,
                       stopCount: $0.stops.count, completedCarCount: nil)
            }
            cars = (preview.preparation?.cars ?? []).map { Car(id: $0.id, name: $0.title, memberNames: $0.members) }
            let assigned = Set(cars.flatMap(\.memberNames))
            unassignedNames = preview.members.filter { !assigned.contains($0) }
        }
        isPreview = true
    }
}
