package io.wegoh.app.nativeauth

data class TripSummary(val id: String,val title: String,val isOwner: Boolean,val ownerName: String,
    val memberCount: Int,val carCount: Int,val startDate: String?=null,val endDate: String?=null,
    val state: String?=null,val myRole: String?=null,val routePreview: List<TripRoutePreviewPlace> = emptyList())
data class TripRoutePreviewPlace(val name: String,val courseId: String,val ref: String)
data class TripInvitation(val tripId: String,val title: String,val ownerName: String,
    val startDate: String?=null,val endDate: String?=null,val memberCount: Int?=null,val carCount: Int?=null)
data class TripList(val trips: List<TripSummary>,val invitations: List<TripInvitation>)
data class TripPermissions(val invite: Boolean=false,val edit: Boolean=false)
/** Server-judged departure readiness: accepted, in a car, and either a driver with a connected vehicle
 *  or a passenger who chose both pickup and drop. */
enum class TripReadiness(val wire: String,val label: String) {
    INVITED("invited","수락 전"),NEEDS_CAR("needsCar","준비 중"),NEEDS_VEHICLE("needsVehicle","준비 중"),
    NEEDS_PLACES("needsPlaces","준비 중"),READY("ready","준비 완료")
}
data class TripMember(val id: String,val name: String,val accepted: Boolean,val isOwner: Boolean,val isMe: Boolean,
    val carId: String?=null,val hasVehicle: Boolean?=null,val permissions: TripPermissions?=null,val role: String?=null,
    val readiness: TripReadiness?=null)
data class TripPassenger(val id: String,val name: String,val isMe: Boolean)
data class TripPlace(val name: String,val id: String?=null,val kind: String?=null,val lat: Double?=null,
    val lng: Double?=null,val addedBy: String?=null,val createdAt: String?=null,
    val selectedBy: List<String>?=null,val selectedCount: Int?=null)
data class TripRouteItem(val type: String,val ref: String,val courseId: String?=null,val dropRef: String?=null) {
    val key get()="$type:${courseId.orEmpty()}:$ref"
}
data class TripCourseStop(val id: String,val name: String,val lat: Double?=null,val lng: Double?=null)
data class TripCourse(val packId: String,val title: String,val version: Int?=null,val stopCount: Int?=null,
    val addedByName: String?=null,val reviewed: Boolean?=null,val canRemove: Boolean?=null,
    val completedCarIds: List<String>?=null,val stops: List<TripCourseStop>?=null)
data class TripRideInvite(val id: String,val carId: String,val accountId: String,val createdAt: String?=null)
data class TripLink(val active: Boolean,val expiresAt: String?=null)
data class TripRemotePolicy(val enabled: Boolean,val actions: Set<String>,val deviceId: String?,val revision: Long?=null) {
    companion object {
        val supportedActions=setOf("hvac.temperature","hvac.fan","hvac.power","hvac.ac","hvac.air_cleaner",
            "light.cabin","light.reading","light.ambient","window.position","seat.heat","seat.ventilation")
    }
}
data class TripCar(val id: String,val name: String,val driverId: String,val driverName: String,val seats: Int,
    val isMine: Boolean,val iRide: Boolean,val passengers: List<TripPassenger>,val places: List<TripPlace>?=null,
    val routeOrder: List<TripRouteItem>?=null,val routeNext: TripRouteItem?=null,val routeNextKnown: Boolean=false,
    val routeRevision: Long=0,val remotePolicy: TripRemotePolicy?=null,
    val routePlan: TripRoutePlan?=null,val routeStatus: TripRouteStatus?=null,val ordinal: Int?=null) {
    val numberedName get()=ordinal?.let {"${it}호차 $name"} ?: name
}
data class TripDetail(val id: String,val title: String,val description: String,val members: List<TripMember>,val cars: List<TripCar>,
    val startDate: String?=null,val endDate: String?=null,val state: String?=null,val revision: Long?=null,
    val myPermissions: TripPermissions?=null,val courses: List<TripCourse>?=null,
    val rideInvites: List<TripRideInvite>?=null,val link: TripLink?=null,val display: TripDisplay?=null,val locationSharing: Boolean=false,
    val routeContractVersion: Int=1,val startConflict: TripStartConflict?=null) {
    val me get()=members.firstOrNull {it.isMe}
    val isOwner get()=me?.isOwner==true
    val canEdit get()=isOwner || myPermissions?.edit==true
    val canAddCourse get()=me?.accepted==true && state in setOf("planned","active")
    val canInvite get()=isOwner || myPermissions?.invite==true
    val myCar get()=cars.firstOrNull {it.isMine || it.iRide}
    val myRole get()=myCar?.let {if(it.isMine)"내 차 운전" else "${it.driverName}의 차 탑승"} ?: "탑승 차량 미정"
}

/** Another running trip the starter takes part in; isOwner decides between finishing it and leaving it. */
data class TripActiveTrip(val id: String,val title: String,val isOwner: Boolean)
/** Owner-only pre-start check of a planned trip: one running trip per person. */
data class TripStartConflict(val activeTrips: List<TripActiveTrip>,val busyMemberIds: List<String>)

data class TripTimelineEntry(val id: String,val name: String,val kind: String,val at: String)
data class TripMusic(val name: String?,val currentTitle: String?,val trackCount: Int,val djName: String?)
data class TripCompanionPosition(val carId: String,val label: String?,val distanceMeters: Double?,val direction: String?)
data class TripMetrics(val distanceKm: Double,val drivingSeconds: Double)
data class TripDisplay(val timeline: List<TripTimelineEntry>,val visitCount: Int?,val metrics: TripMetrics?,
    val music: TripMusic?,val companions: List<TripCompanionPosition>,val expiresAtElapsedMillis: Long=Long.MAX_VALUE,val endedAt: String?=null,
    val companionsExpiresAtElapsedMillis: Long=expiresAtElapsedMillis)
