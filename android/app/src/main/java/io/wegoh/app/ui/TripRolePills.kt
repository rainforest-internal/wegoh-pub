@file:OptIn(androidx.compose.foundation.layout.ExperimentalLayoutApi::class)

package io.wegoh.app.ui

import androidx.compose.foundation.layout.*
import androidx.compose.runtime.Composable
import io.wegoh.app.nativeauth.*

internal fun tripRoleLabel(role: String?): String? = when(role) {
    "dj"->"DJ"
    "food"->"맛집 담당"
    "rest"->"쉼터 담당"
    else->null
}

@Composable
internal fun TripMemberRole(member: TripMember) {
    tripRoleLabel(member.role)?.let {CarStatusPill(it,kind=CarStatusTone.SOFT)}
}

@Composable
internal fun TripCarRoles(trip: TripDetail,car: TripCar) {
    val members=trip.members.filter {it.id==car.driverId || car.passengers.any {person->person.id==it.id}}
        .filter {tripRoleLabel(it.role)!=null}
    if(members.isNotEmpty())FlowRow(horizontalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall),
        verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall)) {
        members.forEach {CarStatusPill("${it.name} ${tripRoleLabel(it.role)}",kind=CarStatusTone.SOFT)}
    }
}

internal fun tripRemotePolicyLabel(policy: TripRemotePolicy?): String = when {
    policy==null->"리모컨 권한 확인 필요"
    !policy.enabled->"리모컨 허용 안 함"
    else->"리모컨 허용: "+remotePolicyFamilies.filter {(_,actions)->actions.any {it in policy.actions}}
        .joinToString(", ") {it.first}.ifEmpty {"허용한 기능 없음"}
}
