package io.wegoh.app.ui

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.*
import io.wegoh.app.TripGear
import io.wegoh.app.TripRouteStop
import io.wegoh.app.TripUiActions
import io.wegoh.app.TripsPageState
import io.wegoh.app.WegoController
import io.wegoh.app.tripLocationPromptNeeded

@Composable
internal fun rememberTripNavigationActions(controller: WegoController,state: TripsPageState,actions: TripUiActions): TripUiActions {
    var pending by remember {mutableStateOf<Pair<String,TripRouteStop>?>(null)}
    var consent by remember {mutableStateOf(false)}
    var screenTrip by remember {mutableStateOf<String?>(null)}
    var declined by remember {mutableStateOf(emptySet<String>())}
    val currentState by rememberUpdatedState(state)
    val currentActions by rememberUpdatedState(actions)
    val focused by rememberUpdatedState(LocalCarWindowVisibility.current?.state?.focused==true)
    val locationPermission=rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) {
        controller.refreshTripLocation()
    }
    val permission=rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) {
        val target=pending;pending=null
        if(target!=null && currentState.selectedId==target.first && controller.state.setupAllowed && focused)
            currentActions.navigate(target.second)
    }
    fun proceed() {
        val target=pending ?: return
        if(currentState.selectedId!=target.first || !controller.state.setupAllowed || !focused) {pending=null;return}
        if(controller.hasCoursePermissions()) {pending=null;currentActions.navigate(target.second)}
        else permission.launch(WegoController.COURSE_PERMISSIONS)
    }
    LaunchedEffect(state.selectedId,controller.state.setupAllowed,state.gear) {
        if(!controller.state.setupAllowed || state.gear!=TripGear.PARK || pending?.first!=state.selectedId) {
            pending=null;consent=false
        }
    }
    val entry=tripLocationPromptNeeded(screenTrip,state.selectedId,declined,controller.state.setupAllowed,
        controller.state.storageReady,controller.state.active,controller.state.locationConsented) && focused
    fun dismiss() {
        if(pending==null)screenTrip?.let {declined=declined+it}
        pending=null;consent=false
    }
    if((consent && pending!=null || entry) && controller.state.setupAllowed)CarPopup("위치 사용",::dismiss,body={
        CarText("이 차의 위치를 여행 지도에 표시해요",maxLines=Int.MAX_VALUE)
        CarText("다음 장소까지 남은 거리와 도착 여부를 확인해요",maxLines=Int.MAX_VALUE)
        CarText("여행 위치 공유를 켜면 일행에게 이 차의 위치가 보여요",secondary=true,maxLines=Int.MAX_VALUE)
        CarText("위치는 앱이 열려 있을 때만 확인해요",secondary=true,maxLines=Int.MAX_VALUE)
        CarText("길 안내를 눌러야 다음 장소를 내비게이션으로 보내요",secondary=true,maxLines=Int.MAX_VALUE)
    },actions={
        CarButton("동의",{
            consent=false
            if(!controller.consentLocation()) {if(pending==null)screenTrip?.let {declined=declined+it};pending=null}
            else if(pending!=null)proceed()
            else if(!controller.hasPermissions())locationPermission.launch(WegoController.PERMISSIONS)
        },primary=true)
        CarButton("나중에",::dismiss)
    })
    return remember(actions,permission) {TripUiActions(perform=actions.perform,inviteFriends=actions.inviteFriends,saveOrder=actions.saveOrder,
        navigate={stop->
            val id=currentState.selectedId
            if(id!=null && controller.state.setupAllowed && focused) {
                pending=id to stop
                if(controller.state.locationConsented)proceed() else consent=true
            }
        },arrive=actions.arrive,refreshDrivingVersus=actions.refreshDrivingVersus,later=actions.later,completeCourse=actions.completeCourse,
        loadSignalCandidates=actions.loadSignalCandidates,sendSignal=actions.sendSignal,refreshSignals=actions.refreshSignals,
        finishSignal=actions.finishSignal,voteOngoingSignal=actions.voteOngoingSignal,voteSignal=actions.voteSignal,dismissSignal=actions.dismissSignal,clearLink=actions.clearLink,
        filterSignalFacilities=actions.filterSignalFacilities,refreshRemotePolicy=actions.refreshRemotePolicy,
        locationScreen={screenTrip=it})}
}
