package io.wegoh.app.ui

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.runtime.saveable.Saver

enum class AppDestination(val id: String) {
    TRIPS("trips"),
    COURSES("courses"),
    DISCOVER("discover"),
    CAR("car"),
    PACK("pack"),
    CREATOR("creator"),
    ROOMS("rooms"),
    ROOM_CREATE("room-create"),
    ROOM_JOIN("room-join"),
    ROOM("room"),
    ROOM_PLAN("room-plan"),
    SHARING("sharing"),
    MESSAGES("messages"),
    MUSIC("music"),
    ROOM_ENDED("room-ended"),
    FRIENDS("friends"),
    FRIEND("friend"),
    PAIR("pair"),
    CREATE("create"),
    EDITOR("editor"),
    PLACE("place"),
    EVENT("event"),
    PUBLISH("publish"),
    REMIX("remix"),
    RESULTS("results"),
    RESULT("result"),
    RESULT_SAVE("result-save"),
    PROFILE("profile"),
    VOICE("voice"),
    SAFETY("safety"),
    NEARBY("nearby"),
    SETTINGS("settings"),
    STATES("states"),
    JOURNEYS("journeys"),
    LOCATION_MAP("location-map"),
    MUSIC_PICKER("music-picker"),
    CHALLENGE("challenge"),
    CHALLENGE_RESULT("challenge-result"),
    NEARBY_DETAIL("nearby-detail"),
    NEARBY_VOTE("nearby-vote"),
    OPERATIONS("operations"),
    PACK_MANAGE("pack-manage"),
    COMMUNITY("community"),
    GROUP_CALL("group-call"),
    VOICE_CREATE("voice-create"),
    RECORDING_IMPORT("recording-import"),
    MUSIC_SYNC("music-sync"),
    CLEANLINESS("cleanliness"),
    HOME("home"),
    ACCOUNT("account"),
    PRIVACY("privacy");
    companion object {
        fun fromId(id: String)=entries.firstOrNull {it.id==id}
        fun require(id: String)=requireNotNull(fromId(id)) {"Unknown app destination"}
    }
}

class AppNavigator(initial: AppDestination) {
    private var stack by mutableStateOf(listOf(initial))
    val current get()=stack.last()
    val canGoBack get()=stack.size>1
    fun push(destination: AppDestination) {if(destination!=current)stack=stack+destination}
    fun replace(destination: AppDestination) {stack=stack.dropLast(1)+destination}
    fun root(destination: AppDestination) {stack=listOf(destination)}
    fun back(): Boolean {
        if(!canGoBack)return false
        stack=stack.dropLast(1);return true
    }
    companion object {
        val Saver=Saver<AppNavigator,Any>(save={it.stack.map {item->item.id}},restore={saved->
            val ids=when(saved) {is String->listOf(saved);is List<*>->saved.filterIsInstance<String>();else->emptyList()}
            val destinations=ids.mapNotNull(AppDestination::fromId)
            AppNavigator(destinations.firstOrNull() ?: AppDestination.DISCOVER).also {
                if(destinations.isNotEmpty())it.stack=destinations
            }
        })
    }
}
