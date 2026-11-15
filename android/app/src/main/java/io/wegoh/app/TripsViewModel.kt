package io.wegoh.app

import androidx.lifecycle.ViewModel

internal class TripsViewModel(private val repository: TripsRepository): ViewModel() {
    val uiState=repository.states
    val actions=TripUiActions(perform=repository::perform,inviteFriends=repository::readInviteFriends,saveOrder=repository::saveOrder,
        navigate=repository::navigate,arrive=repository::arrive,refreshDrivingVersus=repository::refreshDrivingVersus,later=repository::later,completeCourse=repository::completeCourse,
        loadSignalCandidates=repository::loadSignalCandidates,sendSignal=repository::sendTripSignal,refreshSignals=repository::refreshSignals,
        finishSignal=repository::finishTripSignal,voteOngoingSignal=repository::voteOngoingTripSignal,voteSignal=repository::voteTripSignal,dismissSignal=repository::dismissTripSignal,clearLink=repository::clearLink,filterSignalFacilities=repository::setSignalFacilities,
        refreshRemotePolicy=repository::refreshRemotePolicy)
    fun load()=repository.request()
    fun refresh()=repository.request(true)
    fun select(id: String)=repository.select(id)
    fun closeDetail()=repository.closeDetail()
    fun respond(id: String,accept: Boolean,locationConsent: Boolean?)=repository.respond(id,accept,locationConsent)
}
