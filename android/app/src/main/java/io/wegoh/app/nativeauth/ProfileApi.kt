package io.wegoh.app.nativeauth

/** [name] is the owner's chosen vehicle name; empty means the server's [defaultName] ("{계정 이름}의 차"). */
data class VehicleProfile(val plateNumber: String,val name: String,val defaultName: String,val revision: Int) {
    val displayName: String get()=name.ifEmpty {defaultName}
    companion object {
        fun validPlate(value: String)=value.isEmpty() || value.length in 2..16 &&
            value.all {it in '0'..'9' || it in '가'..'힣'} && value.any {it in '0'..'9'}
        fun validName(value: String)=value.isEmpty() || value.codePointCount(0,value.length)<=20 && value==value.trim() &&
            value.codePoints().noneMatch {Character.getType(it).toByte() in NAME_REJECTED_TYPES}
        private val NAME_REJECTED_TYPES=setOf(Character.CONTROL,Character.FORMAT,Character.SURROGATE,Character.PRIVATE_USE,
            Character.UNASSIGNED,Character.LINE_SEPARATOR,Character.PARAGRAPH_SEPARATOR)
    }
}

interface ProfileApi {
    fun readVehicleProfile(callback: (Result<VehicleProfile>)->Unit) {callback(Result.failure(UnsupportedOperationException()))}
    fun updateVehicleProfile(plate: String,name: String,revision: Int,callback: (Result<VehicleProfile>)->Unit) {callback(Result.failure(UnsupportedOperationException()))}
    fun readDisplayName(callback: (Result<String>)->Unit)
    fun updateDisplayName(name: String,expectedName: String,callback: (Result<String>)->Unit)
}

internal class NativeProfileApi(private val reads: AuthorizedAccountReads,
    private val update: (String,String,(Result<String>)->Unit)->Unit,
    private val updateVehicle: (String,String,Int,(Result<VehicleProfile>)->Unit)->Unit): ProfileApi {
    override fun readVehicleProfile(callback: (Result<VehicleProfile>)->Unit)=reads.read(null,callback) {client,credentials ->
        decodeVehicleProfile(client.vehicleProfile(credentials.getString("accessToken")),credentials.getString("deviceId"))
    }
    override fun updateVehicleProfile(plate: String,name: String,revision: Int,callback: (Result<VehicleProfile>)->Unit)=updateVehicle(plate,name,revision,callback)
    override fun readDisplayName(callback: (Result<String>)->Unit)=reads.read(null,callback) {client,credentials ->
        val account=client.account(credentials.getString("accessToken"))
        check(account.keys().asSequence().toSet()==setOf("user","deviceId") && account.get("deviceId")==credentials.getString("deviceId"))
        val user=account.getJSONObject("user")
        check(user.keys().asSequence().toSet()==setOf("id","displayName") && user.get("id")==credentials.getString("accountId"))
        val name=user.get("displayName")
        check(name is String && name.isNotBlank() && name.codePointCount(0,name.length) in 1..64 && name.none {it.code<32 || it.code in 127..159})
        name
    }
    override fun updateDisplayName(name: String,expectedName: String,callback: (Result<String>)->Unit)=update(name,expectedName,callback)
}

internal fun decodeVehicleProfile(value: org.json.JSONObject,device: String): VehicleProfile {
    check(value.keys().asSequence().toSet()==setOf("deviceId","plateNumber","name","defaultName","revision") && value.get("deviceId")==device)
    val plate=value.get("plateNumber");val name=value.get("name");val defaultName=value.get("defaultName");val revision=value.get("revision")
    check(plate is String && VehicleProfile.validPlate(plate) && name is String && VehicleProfile.validName(name) &&
        defaultName is String && defaultName.isNotBlank() && defaultName.codePointCount(0,defaultName.length)<=80 &&
        revision is Int && revision>=0)
    return VehicleProfile(plate,name,defaultName,revision)
}
