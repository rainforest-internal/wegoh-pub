package io.wegoh.app

import io.wegoh.app.nativeauth.*

data class TripSignalState(val kind: TripSignalKind=TripSignalKind.RESTROOM,val candidates: List<SignalCandidate> = emptyList(),
    val sentWithoutDestination: Boolean=false,val loading: Boolean=false,val sending: Boolean=false,val sentId: String?=null,val hint: String?=null,
    val checked: Boolean=false,val hasActiveSignal: Boolean=false,val ongoing: TripSignal?=null,val latestGroupSignal: TripSignal?=null,
    val ending: Boolean=false,val overlayTrip: TripDetail?=null,val overlay: TripSignal?=null,
    val voting: Boolean=false,val voted: String?=null,val result: String?=null,
    val requiredFacilities: Set<TripSignalFacility> = TripSignalKind.RESTROOM.defaultFacilities)

/** Hand-raise is a preset, large-target action (Pleos driver-distraction design: preset first, minimal touch).
 * P uses the full composer once CarUx is unrestricted. D uses the reduced driving composer whenever this
 * distraction-optimized activity has actually read CarUx; no keyboard, filtering or setup is offered there.
 * Unknown CarUx and other gears fail closed. */
private fun TripsPageState.signalGearAllowed(setupAllowed: Boolean): Boolean =
    gear==TripGear.PARK && setupAllowed || gear==TripGear.DRIVE && (setupAllowed || carUxKnown)

internal fun TripsPageState.canUseSignalControls(setupAllowed: Boolean): Boolean =
    signalGearAllowed(setupAllowed) && detail?.let {it.state=="active" && it.myCar!=null && it.myCar?.routePlan?.phase!="done"}!=false

internal fun TripsPageState.canUseSignalResponses(setupAllowed: Boolean): Boolean = signalGearAllowed(setupAllowed)

/** D단과, 진행 중 여행이 열린 채 CarUx가 설정을 막은 N·R·미확인 기어는 같은 주행 대시보드를 보인다.
 * 화면만 같고 조작 허용은 각 컨트롤의 기존 조건(손들기는 D·P만, 워키토키는 D만)을 그대로 따른다.
 * N단 0km/h도 Pleos 기준 비주차 제한 상태라 조작을 넓히지 않고, 읽기 정보만 잃지 않게 한다. */
internal fun TripsPageState.showsDrivingDashboard(setupAllowed: Boolean): Boolean =
    gear==TripGear.DRIVE || gear!=TripGear.PARK && !setupAllowed && detail?.state=="active"

/** The composer drops facility filters and long candidate lists outside P. */
internal fun TripsPageState.usesDrivingSignalComposer(): Boolean = gear!=TripGear.PARK

/** Auto-recommended places shown while driving, besides "장소 없이 보내기". */
internal const val DRIVING_SIGNAL_CANDIDATES=2

internal fun TripDetail.signalRouteStop(drive: TripDrivingState): TripRouteStop? {
    val car=myCar ?: return null
    val stops=TripRouteOrder.resolve(TripRouteOrder.initial(this,car),this,car)
    return tripNextStop(stops,drive)?.takeIf {stop->
        stop.lat?.let {it in 32.0..39.0}==true && stop.lng?.let {it in 124.0..132.0}==true
    }
}

internal fun TripDetail.signalFromMyCar(signal: TripSignal): Boolean {
    val car=myCar ?: return signal.accountId==me?.id
    if(signal.requesterCarId!=null)return car.id==signal.requesterCarId
    return signal.accountId==car.driverId || car.passengers.any {it.id==signal.accountId} ||
        members.any {it.id==signal.accountId && it.carId==car.id}
}

/** 요청자가 탄 차. 운전자뿐 아니라 동승자의 요청도 그 차로 찾는다. */
internal fun TripDetail.signalCar(signal: TripSignal): TripCar? =
    cars.firstOrNull {it.id==signal.requesterCarId}
        ?: cars.firstOrNull {car->car.driverId==signal.accountId || car.passengers.any {it.id==signal.accountId}}
        ?: members.firstOrNull {it.id==signal.accountId}?.carId?.let {id->cars.firstOrNull {it.id==id}}

/** 차량이 먼저 띄울 새 손들기. 다른 차 요청은 응답하도록, 우리 차 동승자의 장소 없는 요청은
 * 세울 곳을 정할 운전자에게 알린다. 내가 보낸 요청과 모든 차 응답(그룹) 요청은 제외한다. */
internal fun TripDetail.announcesSignal(signal: TripSignal): Boolean =
    !signal.isGroupDecision && myCar?.isMine==true && signal.accountId!=me?.id &&
        (signal.destination==null || !signalFromMyCar(signal))

internal fun TripDetail.canRespondToSignal(signal: TripSignal): Boolean {
    val car=myCar ?: return false
    if(state!="active" || me?.accepted!=true || !signal.inProgress || signal.contextState!="valid" || signal.destination==null)return false
    if(signal.decisionRule!=null)return signal.isGroupDecision && signal.canRespond==true && signal.responseChoice==null &&
        !signalFromMyCar(signal)
    return car.isMine && signal.myVote==null && !signalFromMyCar(signal)
}
