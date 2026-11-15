package io.wegoh.app.nativeauth

import java.io.Closeable
import org.json.JSONObject

sealed class TripAction {
    data class SetLocationSharing(val enabled: Boolean): TripAction()
    data class Start(val revision: Long,val routeContractVersion: Int=1,val endActiveTrip: Boolean=false): TripAction()
    data class Finish(val revision: Long): TripAction()
    data class EditIntro(val title: String,val description: String): TripAction()
    data class EditDates(val startDate: String?,val endDate: String?): TripAction()
    data class Invite(val accountId: String): TripAction()
    data class RemoveMember(val accountId: String): TripAction()
    object CreateLink: TripAction()
    object RevokeLink: TripAction()
    data class CreateCar(val name: String,val seats: Int): TripAction()
    data class EditCar(val carId: String,val name: String,val seats: Int): TripAction()
    data class DeleteCar(val carId: String): TripAction()
    data class Ride(val carId: String): TripAction()
    object LeaveCar: TripAction()
    data class AddPlace(val carId: String,val kind: String,val name: String,val lat: Double,val lng: Double): TripAction()
    data class DeletePlace(val carId: String,val placeId: String): TripAction()
    data class InviteRider(val carId: String,val accountId: String): TripAction()
    data class CancelRideInvite(val carId: String,val inviteId: String): TripAction()
    data class RemoveRider(val carId: String,val accountId: String): TripAction()
    data class AddCourse(val packId: String): TripAction()
    data class RemoveCourse(val packId: String): TripAction()
}
class TripInviteLink(val token: String,val expiresAt: String?) {
    override fun toString()="TripInviteLink(redacted)"
}
data class TripActionResult(val link: TripInviteLink?=null,val revision: Long?=null)
data class TripInviteFriend(val id: String,val name: String,val hasVehicle: Boolean?,val state: String?)
interface TripActions {
    fun perform(id: String,action: TripAction,callback: (Result<TripActionResult>)->Unit): Closeable
}
internal data class TripActionRequest(val method: String,val suffix: String,val body: JSONObject,val success: Set<Int> = setOf(200))
internal object TripActionCodec {
    private fun identifier(id: String)=id.also {require(Regex("[a-f0-9]{32}").matches(it))}
    private fun account(id: String)=id.also {require(Regex("team-[a-f0-9]{40}").matches(it))}
    private fun pack(id: String)=id.also {require(Regex("[a-z0-9][a-z0-9_-]{0,79}").matches(it))}
    private fun text(value: String,max: Int,empty: Boolean=false): String = value.trim().also {
        require(it.codePointCount(0,it.length) in (if(empty)0 else 1)..max && it.none {c->c.isISOControl() && !(empty && c=='\n')})
    }
    private fun car(name: String,seats: Int): JSONObject {
        require(seats in 1..8);return JSONObject().put("name",text(name,20)).put("seats",seats)
    }
    fun request(action: TripAction): TripActionRequest = when(action) {
        is TripAction.SetLocationSharing->TripActionRequest("PATCH","/location-sharing",JSONObject().put("locationConsent",action.enabled))
        is TripAction.Start->transition("start",action.revision).also {
            require(action.routeContractVersion in 1..2)
            if(action.routeContractVersion==2)it.body.put("routeContractVersion",2)
            if(action.endActiveTrip)it.body.put("endActiveTrip",true)
        }
        is TripAction.Finish->transition("finish",action.revision)
        is TripAction.EditIntro->TripActionRequest("PATCH","",JSONObject().put("title",text(action.title,40)).put("description",text(action.description,300,true)))
        is TripAction.EditDates->{
            val start=action.startDate?.let {java.time.LocalDate.parse(it)}
            val end=action.endDate?.let {java.time.LocalDate.parse(it)}
            require(start==null || end==null || java.time.temporal.ChronoUnit.DAYS.between(start,end) in 0..30)
            TripActionRequest("PATCH","",JSONObject().put("startDate",action.startDate ?: JSONObject.NULL).put("endDate",action.endDate ?: JSONObject.NULL))
        }
        is TripAction.Invite->TripActionRequest("POST","/members",JSONObject().put("accountId",account(action.accountId)),setOf(200,201))
        is TripAction.RemoveMember->TripActionRequest("DELETE","/members/${account(action.accountId)}",JSONObject())
        TripAction.CreateLink->TripActionRequest("POST","/link",JSONObject(),setOf(201))
        TripAction.RevokeLink->TripActionRequest("DELETE","/link",JSONObject())
        is TripAction.CreateCar->TripActionRequest("POST","/cars",car(action.name,action.seats),setOf(201))
        is TripAction.EditCar->TripActionRequest("PATCH","/cars/${identifier(action.carId)}",car(action.name,action.seats))
        is TripAction.DeleteCar->TripActionRequest("DELETE","/cars/${identifier(action.carId)}",JSONObject())
        is TripAction.Ride->TripActionRequest("PUT","/cars/${identifier(action.carId)}/ride",JSONObject())
        TripAction.LeaveCar->TripActionRequest("DELETE","/ride",JSONObject())
        is TripAction.AddPlace->{
            require(action.kind in setOf("pickup","drop") && action.lat.isFinite() && action.lat in -90.0..90.0 && action.lng.isFinite() && action.lng in -180.0..180.0)
            TripActionRequest("POST","/cars/${identifier(action.carId)}/places",JSONObject().put("kind",action.kind)
                .put("name",text(action.name,40)).put("lat",action.lat).put("lng",action.lng),setOf(201))
        }
        is TripAction.DeletePlace->TripActionRequest("DELETE","/cars/${identifier(action.carId)}/places/${identifier(action.placeId)}",JSONObject())
        is TripAction.InviteRider->TripActionRequest("POST","/cars/${identifier(action.carId)}/ride-invites",JSONObject().put("accountId",account(action.accountId)),setOf(201))
        is TripAction.CancelRideInvite->TripActionRequest("DELETE","/cars/${identifier(action.carId)}/ride-invites/${identifier(action.inviteId)}",JSONObject())
        is TripAction.RemoveRider->TripActionRequest("DELETE","/cars/${identifier(action.carId)}/riders/${account(action.accountId)}",JSONObject())
        is TripAction.AddCourse->TripActionRequest("POST","/courses",JSONObject().put("packId",pack(action.packId)),setOf(200,201))
        is TripAction.RemoveCourse->TripActionRequest("DELETE","/courses/${pack(action.packId)}",JSONObject())
    }
    private fun transition(action: String,revision: Long): TripActionRequest {
        require(revision in 1..Int.MAX_VALUE.toLong())
        return TripActionRequest("POST","/$action",JSONObject().put("revision",revision))
    }
    fun response(action: TripAction,value: JSONObject): TripActionResult {
        if(action is TripAction.SetLocationSharing) {
            check(value.get("locationConsent")==action.enabled)
            val revision=value.get("revision")
            check((revision is Int || revision is Long) && (revision as Number).toLong() in 1..Int.MAX_VALUE.toLong())
            return TripActionResult(revision=(revision as Number).toLong())
        }
        if(action!=TripAction.CreateLink)return TripActionResult()
        val token=value.getString("token");check(Regex("[A-Za-z0-9_-]{43}").matches(token))
        val expiry=if(value.isNull("expiresAt"))null else value.getString("expiresAt").also {java.time.Instant.parse(it)}
        return TripActionResult(TripInviteLink(token,expiry))
    }
}
