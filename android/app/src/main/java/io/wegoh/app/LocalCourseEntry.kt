package io.wegoh.app

/** Runtime authority, never decoded from a course label or serialized into a pack. */
internal sealed interface CourseOwner {
    data class Local(val key: String): CourseOwner
    data class Account(val storageKey: String,val epoch: Long): CourseOwner {
        override fun toString()="Account"
    }
}

/** Minted only while combining repository objects and the scoped account selection. */
internal sealed class CourseSelection(val pack: DrivePack) {
    class Local(pack: DrivePack): CourseSelection(pack)
    class Account(pack: DrivePack): CourseSelection(pack)
}
internal fun courseSelection(pack: DrivePack?,repository: List<DrivePack>,account: DrivePack?): CourseSelection? = when {
    pack==null -> null
    pack===account -> CourseSelection.Account(pack)
    repository.any {it===pack} -> CourseSelection.Local(pack)
    else -> null
}

/** Unpaired entry has no account/SNS state, even when a private pack has identical bytes. */
internal fun localCourseEntryState(state: WegoState,repository: List<DrivePack>,selection: CourseSelection?,
    sessionOwner: CourseOwner?,navigationOwner: CourseOwner?,historyOwner: CourseOwner?): WegoState {
    val local=(selection as? CourseSelection.Local)?.takeIf {it.pack===state.selected && repository.any {pack->pack===it.pack}}
    val owner=local?.let {CourseOwner.Local(it.pack.key)}
    val session=owner!=null && owner==sessionOwner
    val navigation=owner!=null && owner==navigationOwner
    val history=owner!=null && owner==historyOwner
    val defaults=WegoState()
    val base=if(local!=null)state else defaults.copy(setupAllowed=state.setupAllowed,policy=state.policy,
        storageReady=state.storageReady,locationConsented=state.locationConsented,
        error=state.error.takeIf {!state.storageReady})
    return base.copy(accountCourses=AccountCourseState(),accountPlaylists=AccountPlaylistState(),
        accountProfile=AccountProfileState(),accountDiscovery=AccountDiscoveryState(),
        packs=repository,selectedKey=local?.pack?.key,active=session && base.active,
        location=if(session)base.location else defaults.location,
        history=if(history)base.history else emptyList(),
        courseResult=base.courseResult.takeIf {local!=null},
        navigation=if(navigation)base.navigation else defaults.navigation,
        navigationBusy=navigation && base.navigationBusy,
        navigationPhase=if(navigation)base.navigationPhase else NavigationPhase.IDLE,
        navigationObservation=base.navigationObservation.takeIf {navigation},
        navigationOverview=base.navigationOverview.takeIf {navigation},
        published=emptyList(),catalogueBusy=false,downloading=null,
        reportOrigin=null,reportBusy=false,reportOutcome=null,
        sharingVisits=false,visitSharingAllowed=false)
}
