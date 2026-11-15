package io.wegoh.app

import android.content.Context
import android.os.Handler
import android.os.Looper

internal class NavigationCoordinator(private val context: Context,private val read: ()->WegoState,
    private val update: (WegoState)->Unit,private val isForeground: ()->Boolean,
    private val fail: (String)->Unit,private val log: (String)->Unit) {
    private val main=Handler(Looper.getMainLooper())
    private var generation=0
    private var clientEpochCounter=0
    private var client: NavigationClient?=null
    private var state: WegoState
        get()=read()
        set(value)=update(value)
    fun request(pack: DrivePack,ownerCurrent: ()->Boolean,running: ()->Boolean) {
        val request = ++generation
        val clientEpoch=++clientEpochCounter
        fun current()=clientEpoch==clientEpochCounter && ownerCurrent()
        client?.release();client=null
        state = state.copy(navigationBusy = true,navigationPhase=NavigationPhase.CONNECTING,navigationOverview=null,navigationObservation=null,error = null)
        runCatching {
            if (client == null) client = NavigationClient(context, report={ status -> main.post {
                if(!current())return@post
                if(isForeground()) {state = state.copy(navigation = status);log("NAVI $status")}
            } },overview={data->main.post {
                if(isForeground() && current() && (data==null || data.packKey==state.selectedKey))state=state.copy(navigationOverview=data)
            }},canRequest={state.setupAllowed && state.storageReady && (state.selectedKey==pack.key || running()) && current()},onPhase={phase->main.post {
                if(!current())return@post
                state=state.copy(navigationPhase=phase,navigationBusy=phase in setOf(NavigationPhase.CONNECTING,NavigationPhase.SENT,NavigationPhase.SEARCHING,NavigationPhase.CALCULATED))
                if(phase==NavigationPhase.FAILED)fail("길 안내를 시작하지 못했어요")
            }},onObservation={observation->main.post {
                if(isForeground() && current())state=state.copy(navigationObservation=observation)
            }})
            client!!.request(pack)
            main.postDelayed({
                if(generation==request && clientEpoch==clientEpochCounter && (state.selectedKey==pack.key || running()) && state.navigationBusy) {
                    clientEpochCounter++;client?.release();client=null
                    state=state.copy(navigationBusy=false,navigationPhase=NavigationPhase.FAILED,navigationObservation=null)
                    fail("길 안내 시작을 확인하지 못했어요")
                }
            },15000)
        }.onFailure {
            clientEpochCounter++;client?.release();client=null
            state=state.copy(navigationBusy=false,navigationPhase=NavigationPhase.FAILED,navigationObservation=null);fail("길 안내를 시작하지 못했어요")
        }
    }
    fun cancel(resetLabel: Boolean=false) {
        generation++;clientEpochCounter++;client?.release();client=null
        state=state.copy(navigationBusy=false,navigationPhase=NavigationPhase.IDLE,navigationOverview=null,navigationObservation=null,
            navigation=if(resetLabel)"안내 시작 전" else state.navigation)
    }
}
