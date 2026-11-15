package io.wegoh.app

import io.wegoh.app.nativeauth.*
import java.io.Closeable
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow

data class SocialPageState(val status: AccountReadStatus=AccountReadStatus.CONNECTION_REQUIRED,
    val overview: SocialOverview?=null,val room: SocialRoom?=null,val isCurrent: Boolean=false,
    val busy: Boolean=false,val notice: String?=null,
    val roomMusic: SocialRoomMusic?=null,val musicNotice: String?=null)

internal class SocialRepository(private val connection: VehicleConnection): Closeable {
    private val mutable=MutableStateFlow(SocialPageState())
    val states=mutable.asStateFlow()
    val state get()=states.value
    private var client: NativeSocialClient?=null
    private val invalidationReloads=InvalidationReloads()
    private var pending: Closeable?=null
    private var generation=0L
    private var foreground=false
    private var allowed=false
    private var activated=false
    private var dirty=true
    private var closed=false
    private val rooms=mutableMapOf<String,SocialRoom>()
    private val snapshot=AccountReadSnapshot(connection,null) {clear()}
    private val observer=connection.observe {progress->
        if(snapshot.invalidated())clear()
        if(activated && foreground && allowed && progress.stage==VehicleConnection.Stage.CONNECTED && dirty && !state.busy)request()
    }
    private fun clear() {
        cancel();snapshot.forget();rooms.clear();dirty=true;mutable.value=SocialPageState()
    }
    private fun cancel() {generation++;pending?.close();pending=null;client?.close();client=null}
    fun setForeground(value: Boolean) {
        if(closed || foreground==value)return
        foreground=value
        if(!value){cancel();mutable.value=if(snapshot.canRetain())state.copy(isCurrent=false,busy=false) else SocialPageState()}
        else android.os.Handler(android.os.Looper.getMainLooper()).post {if(activated && foreground && allowed)request()}
    }
    fun setSetupAllowed(value: Boolean) {allowed=value}
    fun request(force: Boolean=false) {
        if(closed || !foreground || !allowed) {
            WegoLog.i("WegoH","social.overview: load skipped reason="+when {closed->"closed";!foreground->"not_foreground";else->"setup_not_allowed"});return
        }
        activated=true
        if(connection.status().stage!=VehicleConnection.Stage.CONNECTED) {WegoLog.i("WegoH","social.overview: load skipped reason=not_connected");return}
        if(state.busy) {WegoLog.i("WegoH","social.overview: load skipped reason=busy");return}
        if(force){dirty=true;rooms.clear()}
        if(state.isCurrent && !dirty) {WegoLog.i("WegoH","social.overview: load skipped reason=current");return}
        if(!state.isCurrent)dirty=true
        WegoLog.i("WegoH","social.overview: load started")
        cancel();val token=generation
        mutable.value=state.copy(status=if(state.overview==null)AccountReadStatus.LOADING else AccountReadStatus.READY,busy=true,isCurrent=false,notice=null)
        val social=connection.social();client=social
        var changed=false
        social.open(object: NativeSocialObserver {
            override fun onResourcesChanged(resources: Set<String>) {if(token==generation){changed=true;dirty=true;rooms.clear()}}
            override fun onInvalidated() {
                if(token!=generation)return
                WegoLog.i("WegoH","social.overview: invalidated")
                clear()
                if(!foreground || !allowed)return
                if(changed)request(true)
                else invalidationReloads.take()?.let {attempt->
                    WegoLog.i("WegoH","social.overview: reload after invalidation attempt=$attempt")
                    request(true)
                }
            }
            override fun onConnectionLost() {
                if(token!=generation)return
                WegoLog.w("WegoH","social.overview: load failed reason=connection_lost")
                mutable.value=if(snapshot.canRetain())state.copy(isCurrent=false,busy=false) else SocialPageState(AccountReadStatus.UNAVAILABLE)
            }
        }) {result ->
            if(token!=generation || closed)return@open
            result.fold(onSuccess={
                if(!dirty && state.overview!=null && snapshot.canRetain())mutable.value=state.copy(status=AccountReadStatus.READY,isCurrent=true,busy=false)
                else pending=social.overviewApi.readOverview {reply ->
                    if(token!=generation || closed)return@readOverview
                    reply.fold(onSuccess={value->
                        val boundary=connection.verifiedDataBoundary()
                        if(boundary==null){clear();return@readOverview}
                        snapshot.remember(boundary);dirty=false;invalidationReloads.reset()
                        mutable.value=SocialPageState(AccountReadStatus.READY,value,isCurrent=true)
                    },onFailure=::failed)
                }
            },onFailure=::failed)
        }
    }
    private fun failed(error: Throwable) {
        WegoLog.w("WegoH","social.overview: load failed "+NativeSocialErrorCodec.fields(error))
        val prepare=(error as? NativeSocialFailure)?.kind in setOf(NativeSocialFailure.Kind.CONSENT_REQUIRED,NativeSocialFailure.Kind.NOT_FOUND,NativeSocialFailure.Kind.FORBIDDEN)
        mutable.value=if(!prepare && state.overview!=null && snapshot.canRetain())state.copy(isCurrent=false,busy=false,notice="새로고침해 주세요")
            else SocialPageState(if(prepare)AccountReadStatus.PERMISSION_REQUIRED else AccountReadStatus.UNAVAILABLE)
    }
    fun selectRoom(id: String) {
        if(!foreground || !allowed || !state.isCurrent || state.busy)return
        val current=client ?: return
        val token=generation;mutable.value=state.copy(busy=true,roomMusic=null,musicNotice="음악 불러오는 중")
        fun readMusic(room: SocialRoom) {
            rooms[id]=room;mutable.value=state.copy(room=room)
            pending=current.roomsApi.readMusic(id) {reply->
                if(token==generation && state.room?.id==id)reply.fold(onSuccess={
                    mutable.value=state.copy(busy=false,roomMusic=it,musicNotice=if(it.selection==null)"공유 중인 음악이 없어요" else null)
                },onFailure={error->
                    val prepare=(error as? NativeSocialFailure)?.kind in setOf(NativeSocialFailure.Kind.CONSENT_REQUIRED,
                        NativeSocialFailure.Kind.FORBIDDEN,NativeSocialFailure.Kind.NOT_FOUND)
                    mutable.value=state.copy(busy=false,roomMusic=null,musicNotice=if(prepare)"음악을 이용할 수 없어요" else "음악을 불러오지 못했어요. 새로고침해 주세요")
                })
            }
        }
        rooms[id]?.takeIf {it.expiresAt.toEpochMilli()>System.currentTimeMillis()}?.let {readMusic(it);return}
        pending=current.roomsApi.readRoom(id) {reply->if(token==generation)reply.fold(onSuccess=::readMusic,onFailure=::failed)}
    }
    fun closeRoom(){pending?.close();pending=null;mutable.value=state.copy(room=null,busy=false,roomMusic=null,musicNotice=null)}
    fun signal(kind: SocialSignalKind) {
        val room=state.room ?: return
        if(!foreground || !allowed || !state.isCurrent || state.busy || room.readOnly)return
        val token=generation;mutable.value=state.copy(busy=true)
        pending=client?.roomsApi?.sendStatusSignal(room.id,kind) {reply->if(token==generation)reply.fold(onSuccess={
            rooms.remove(room.id);mutable.value=state.copy(busy=false,notice="상태를 전했어요")
        },onFailure=::failed)}
    }
    fun respond(target: String,accept: Boolean) {
        if(!foreground || !allowed || !state.isCurrent || state.busy || state.overview?.friendsReadOnly!=false)return
        val token=generation;mutable.value=state.copy(busy=true)
        pending=client?.friendsApi?.respond(target,accept) {reply->if(token==generation)reply.fold(onSuccess={mutable.value=state.copy(busy=false);request(true)},onFailure=::failed)}
    }
    fun manageFriend(target: String,block: Boolean) {
        if(!foreground || !allowed || !state.isCurrent || state.busy || state.overview?.friendsReadOnly!=false)return
        val token=generation;mutable.value=state.copy(busy=true)
        val callback: (Result<Unit>)->Unit={reply->if(token==generation)reply.fold(onSuccess={mutable.value=state.copy(busy=false);request(true)},onFailure=::failed)}
        pending=if(block)client?.friendsApi?.block(target,callback) else client?.friendsApi?.remove(target,callback)
    }
    override fun close(){closed=true;cancel();observer.close();snapshot.forget();rooms.clear();mutable.value=SocialPageState()}
}
