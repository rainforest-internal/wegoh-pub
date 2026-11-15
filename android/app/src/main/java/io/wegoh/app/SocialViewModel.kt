package io.wegoh.app

import androidx.lifecycle.ViewModel
import io.wegoh.app.nativeauth.SocialSignalKind

internal class SocialViewModel(private val repository: SocialRepository): ViewModel() {
    val uiState=repository.states
    fun manageFriend(target: String,block: Boolean)=repository.manageFriend(target,block)
    fun load()=repository.request()
    fun refresh()=repository.request(true)
    fun selectRoom(id: String)=repository.selectRoom(id)
    fun closeRoom()=repository.closeRoom()
    fun signal(kind: SocialSignalKind)=repository.signal(kind)
    fun respond(target: String,accept: Boolean)=repository.respond(target,accept)
}
