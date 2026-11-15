package io.wegoh.app

import io.wegoh.app.nativeauth.TripAction
import io.wegoh.app.nativeauth.TripRouteItem

class TripUiActions(
    val perform: (TripAction,()->Unit)->Unit = {_,_->},
    val inviteFriends: ()->Unit = {},
    val saveOrder: (List<TripRouteItem>,Long,()->Unit)->Unit = {_,_,_->},
    val navigate: (TripRouteStop)->Unit = {},
    val arrive: ()->Unit = {},
    val refreshDrivingVersus: ()->Unit = {},
    val later: ()->Unit = {},
    val completeCourse: ()->Unit = {},
    val loadSignalCandidates: (io.wegoh.app.nativeauth.TripSignalKind)->Unit = {},
    val sendSignal: (io.wegoh.app.nativeauth.SignalDestination?)->Unit = {},
    val refreshSignals: ()->Unit = {},
    val finishSignal: (String)->Unit = {},
    val voteOngoingSignal: (String)->Unit = {},
    val voteSignal: (String)->Unit = {},
    val dismissSignal: ()->Unit = {},
    val clearLink: ()->Unit = {},
    val filterSignalFacilities: (Set<io.wegoh.app.nativeauth.TripSignalFacility>)->Unit = {},
    val refreshRemotePolicy: ()->Unit = {},
    /** The active trip screen of this car opened (trip id) or closed (null). */
    val locationScreen: (String?)->Unit = {},
)
