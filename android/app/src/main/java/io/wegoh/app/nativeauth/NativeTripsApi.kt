package io.wegoh.app.nativeauth

import java.io.Closeable

interface TripsApi: TripActions, TripLocationTransport {
    fun readSignals(id: String,callback: (Result<TripSignalPage>)->Unit): Closeable
    fun signalCandidates(id: String,kind: TripSignalKind,location: SignalLocation,callback: (Result<List<SignalCandidate>>)->Unit): Closeable
    fun signalCandidates(id: String,kind: TripSignalKind,location: SignalLocation,requiredFacilities: Set<TripSignalFacility>,callback: (Result<List<SignalCandidate>>)->Unit): Closeable =
        signalCandidates(id,kind,location,callback)
    fun sendSignal(id: String,kind: TripSignalKind,destination: SignalDestination?,callback: (Result<String>)->Unit): Closeable
    fun finishSignal(id: String,signal: String,result: String,callback: (Result<Unit>)->Unit): Closeable
    fun voteSignal(id: String,signal: String,choice: String,callback: (Result<Unit>)->Unit): Closeable
    fun voteSignalResult(id: String,signal: String,choice: String,callback: (Result<TripSignalVoteResult>)->Unit): Closeable =
        voteSignal(id,signal,choice) {reply->callback(reply.map {TripSignalVoteResult(choice)})}
    fun readList(callback: (Result<TripList>)->Unit): Closeable
    fun readDetail(id: String,callback: (Result<TripDetail>)->Unit): Closeable
    fun readSection(detail: TripDetail,section: String,callback: (Result<TripDetail>)->Unit): Closeable {
        callback(Result.failure(IllegalStateException("Trip section unavailable")));return Closeable {}
    }
    fun enableAutomaticLocationSharing(id: String,callback: (Result<TripActionResult>)->Unit): Closeable =
        perform(id,TripAction.SetLocationSharing(true),callback)
    fun respond(id: String,accept: Boolean,locationConsent: Boolean?,callback: (Result<Unit>)->Unit): Closeable
    fun readPlaces(id: String,carId: String,callback: (Result<List<TripPlace>>)->Unit): Closeable
    fun saveRouteOrder(id: String,carId: String,routeRevision: Long,items: List<TripRouteItem>,callback: (Result<Unit>)->Unit): Closeable
    fun saveRouteOrder(id: String,carId: String,routeRevision: Long,items: List<TripRouteItem>,contractVersion: Int,callback: (Result<Unit>)->Unit): Closeable =
        saveRouteOrder(id,carId,routeRevision,items,callback)
    fun routeProgress(id: String,carId: String,routeRevision: Long,next: TripRouteItem?,callback: (Result<Unit>)->Unit): Closeable
    fun routeArrival(id: String,carId: String,routeRevision: Long,progressRevision: Long,item: TripRouteItem,callback: (Result<TripRoutePlan>)->Unit): Closeable {
        callback(Result.failure(IllegalStateException("Trip arrival unavailable")));return Closeable {}
    }
    fun routeArrival(id: String,carId: String,routeRevision: Long,progressRevision: Long,item: TripRouteItem,
        singleJoinCompletion: Boolean,callback: (Result<TripRoutePlan>)->Unit): Closeable =
        routeArrival(id,carId,routeRevision,progressRevision,item,callback)
    fun reportTripDrivingScore(id: String,carId: String,report: DrivingScoreReport,callback: (Result<Unit>)->Unit): Closeable {
        callback(Result.failure(UnsupportedOperationException("TRIP_SCORE_UNAVAILABLE")));return Closeable {}
    }
    fun readDrivingVersus(id: String,callback: (Result<TripDrivingVersus>)->Unit): Closeable {
        callback(Result.failure(IllegalStateException("Trip comparison unavailable")));return Closeable {}
    }
    fun completeCourse(id: String,carId: String,packId: String,callback: (Result<Unit>)->Unit): Closeable
    fun completeJoinedCourse(id: String,carId: String,packId: String,routeRevision: Long,progressRevision: Long,
        report: DrivingScoreReport,callback: (Result<Unit>)->Unit): Closeable {
        callback(Result.failure(IllegalStateException("Trip course completion unavailable")));return Closeable {}
    }
    fun reportDrivingScore(id: String,carId: String,packId: String,report: DrivingScoreReport,callback: (Result<Unit>)->Unit): Closeable {
        callback(Result.failure(IllegalStateException("Driving score report unavailable")));return Closeable {}
    }
    fun completeCourse(id: String,carId: String,packId: String,report: DrivingScoreReport,callback: (Result<Unit>)->Unit): Closeable =
        completeCourse(id,carId,packId,callback)
    fun reportFinalDrivingScore(id: String,carId: String,packId: String,report: DrivingScoreReport,callback: (Result<Unit>)->Unit): Closeable =
        completeCourse(id,carId,packId,report,callback)
    fun readInviteFriends(id: String,callback: (Result<List<TripInviteFriend>>)->Unit): Closeable
}

internal class NativeTripsApi(private val client: NativeSocialClient): TripsApi {
    override fun readLocationShare(id: String,callback: (Result<TripLocationShare>)->Unit): Closeable =
        client.call(NativeSocialRequest(setOf(FunctionalPurpose.ROOMS_READ),diagnosticScope="trip.location.share.read",fetch={api,token,_,_->
            NativeTripsCodec.locationShare(api.tripLocationShare(id,token),id)}),callback)
    override fun readCarLocations(id: String,callback: (Result<TripLocationShare>)->Unit): Closeable =
        client.call(NativeSocialRequest(setOf(FunctionalPurpose.ROOMS_READ),diagnosticScope="trip.location.cars.read",fetch={api,token,_,_->
            NativeTripsCodec.locationShare(api.tripLocationShare(id,token),id)}),callback)
    override fun reportLocation(id: String,shareId: String,fix: TripLocationFix,callback: (Result<Unit>)->Unit): Closeable =
        client.call(NativeSocialRequest(setOf(FunctionalPurpose.ROOMS_READ),mutation=true,fetch={api,token,permission,_->
            val result=api.tripLocationReport(id,NativeTripsCodec.locationBody(shareId,fix),permission.revision,token)
            check(result.length()==1 && result.getString("status")=="accepted");Unit}),callback)
    override fun readSignals(id: String,callback: (Result<TripSignalPage>)->Unit)=client.call(
        NativeSocialRequest(setOf(FunctionalPurpose.ROOMS_READ),diagnosticScope="trip.signals.read",fetch={api,token,_,_->TripLoadDiagnostics.decode("trip.signals",id,NativeFunctionalDiagnostics.pathTemplate("GET",NativeApiClient.tripPath(id)+"/signals")) {TripSignalsCodec.page(api.tripSignals(id,token))}}),callback)
    override fun signalCandidates(id: String,kind: TripSignalKind,location: SignalLocation,callback: (Result<List<SignalCandidate>>)->Unit)=
        signalCandidates(id,kind,location,emptySet(),callback)
    override fun signalCandidates(id: String,kind: TripSignalKind,location: SignalLocation,requiredFacilities: Set<TripSignalFacility>,callback: (Result<List<SignalCandidate>>)->Unit)=client.call(
        NativeSocialRequest(setOf(FunctionalPurpose.ROOMS_READ),diagnosticScope="trip.signals.candidates",fetch={api,token,permission,_->TripSignalsCodec.candidates(
            api.tripSignalCandidates(id,TripSignalsCodec.candidateBody(kind,location,requiredFacilities),permission.revision,token))}),callback)
    override fun sendSignal(id: String,kind: TripSignalKind,destination: SignalDestination?,callback: (Result<String>)->Unit)=client.call(
        NativeSocialRequest(setOf(FunctionalPurpose.ROOMS_READ,FunctionalPurpose.ROOMS_INTERACT),mutation=true,
            diagnosticScope="trip.signals.send",fetch={api,token,permission,_->api.tripSignalSend(id,TripSignalsCodec.sendBody(kind,destination),permission.revision,token).getString("id")}),callback)
    override fun finishSignal(id: String,signal: String,result: String,callback: (Result<Unit>)->Unit)=client.call(
        NativeSocialRequest(setOf(FunctionalPurpose.ROOMS_READ,FunctionalPurpose.ROOMS_INTERACT),mutation=true,
            fetch={api,token,permission,_->
                require(result in setOf("completed","cancelled"))
                val response=api.tripSignalFinish(id,signal,org.json.JSONObject().put("result",result),permission.revision,token)
                check(response.getString("status")==result);Unit}),callback)
    override fun voteSignal(id: String,signal: String,choice: String,callback: (Result<Unit>)->Unit)=client.call(
        NativeSocialRequest(setOf(FunctionalPurpose.ROOMS_READ,FunctionalPurpose.ROOMS_INTERACT),mutation=true,
            diagnosticScope="trip.signals.vote",fetch={api,token,permission,_->api.tripSignalVote(id,signal,TripSignalsCodec.voteBody(choice),permission.revision,token);Unit}),callback)
    override fun voteSignalResult(id: String,signal: String,choice: String,callback: (Result<TripSignalVoteResult>)->Unit)=client.call(
        NativeSocialRequest(setOf(FunctionalPurpose.ROOMS_READ,FunctionalPurpose.ROOMS_INTERACT),mutation=true,
            diagnosticScope="trip.signals.vote",fetch={api,token,permission,_->TripSignalsCodec.voteResult(
                api.tripSignalVote(id,signal,TripSignalsCodec.voteBody(choice),permission.revision,token),choice)}),callback)
    override fun perform(id: String,action: TripAction,callback: (Result<TripActionResult>)->Unit): Closeable {
        val request=TripActionCodec.request(action)
        return client.call(NativeSocialRequest(setOf(FunctionalPurpose.ROOMS_READ,FunctionalPurpose.ROOMS_INTERACT),mutation=true,setupRequired=true,
            fetch={api,token,permission,_->TripActionCodec.response(action,api.nativeTripAction(id,request,permission.revision,token))}),callback)
    }
    override fun enableAutomaticLocationSharing(id: String,callback: (Result<TripActionResult>)->Unit): Closeable {
        val action=TripAction.SetLocationSharing(true)
        val request=TripActionCodec.request(action)
        return client.call(NativeSocialRequest(setOf(FunctionalPurpose.ROOMS_READ,FunctionalPurpose.ROOMS_INTERACT),mutation=true,
            fetch={api,token,permission,_->TripActionCodec.response(action,api.nativeTripAction(id,request,permission.revision,token))}),callback)
    }
    override fun readInviteFriends(id: String,callback: (Result<List<TripInviteFriend>>)->Unit): Closeable =
        client.call(NativeSocialRequest(setOf(FunctionalPurpose.ROOMS_READ),fetch={api,token,_,_->
            NativeTripsCodec.friends(api.nativeTripFriends(id,token))}),callback)
    override fun readList(callback: (Result<TripList>)->Unit)=client.call(NativeSocialRequest(setOf(FunctionalPurpose.ROOMS_READ),
        diagnosticScope="trip.list.read",fetch={api,token,_,_->TripLoadDiagnostics.decode("trip.list",null,NativeFunctionalDiagnostics.pathTemplate("GET",NativeApiClient.tripPath(null))) {NativeTripsCodec.list(api.tripsRead(null,token))}}),callback)
    override fun readDetail(id: String,callback: (Result<TripDetail>)->Unit): Closeable {
        NativeApiClient.tripPath(id)
        return client.call(NativeSocialRequest(setOf(FunctionalPurpose.ROOMS_READ),diagnosticScope="trip.detail.read",
            fetch={api,token,_,_->
                val began=android.os.SystemClock.elapsedRealtime()
                TripLoadDiagnostics.decode("trip.detail",id,NativeFunctionalDiagnostics.pathTemplate("GET",NativeApiClient.nativeTripPath(id))) {NativeTripsCodec.detail(api.nativeTripRead(id,token),id,began)}
            }),callback)
    }
    override fun readSection(detail: TripDetail,section: String,callback: (Result<TripDetail>)->Unit): Closeable =
        client.call(NativeSocialRequest(setOf(FunctionalPurpose.ROOMS_READ),diagnosticScope="trip.$section.read",
            fetch={api,token,_,_->
                val began=android.os.SystemClock.elapsedRealtime()
                NativeTripsCodec.section(detail,api.nativeTripSection(detail.id,section,token),section,began)
            }),callback)
    override fun respond(id: String,accept: Boolean,locationConsent: Boolean?,callback: (Result<Unit>)->Unit): Closeable {
        NativeApiClient.tripPath(id)
        return client.call(NativeSocialRequest(setOf(FunctionalPurpose.ROOMS_READ,FunctionalPurpose.ROOMS_INTERACT),mutation=true,setupRequired=true,
            fetch={api,token,permission,_->NativeTripsCodec.response(api.tripRespond(id,accept,locationConsent,permission.revision,token),accept)}),callback)
    }
    override fun readPlaces(id: String,carId: String,callback: (Result<List<TripPlace>>)->Unit): Closeable =
        client.call(NativeSocialRequest(setOf(FunctionalPurpose.ROOMS_READ),fetch={api,token,_,_->
            NativeTripsCodec.places(api.nativeTripPlaces(id,carId,token).getJSONArray("places"))}),callback)
    override fun saveRouteOrder(id: String,carId: String,routeRevision: Long,items: List<TripRouteItem>,callback: (Result<Unit>)->Unit): Closeable {
        return saveRouteOrder(id,carId,routeRevision,items,1,callback)
    }
    override fun saveRouteOrder(id: String,carId: String,routeRevision: Long,items: List<TripRouteItem>,contractVersion: Int,callback: (Result<Unit>)->Unit): Closeable {
        require(contractVersion in 1..2)
        val body=NativeTripsCodec.routeBody(items).put("routeRevision",routeRevision).apply {if(contractVersion==2)put("routeContractVersion",2)}
        return client.call(NativeSocialRequest(setOf(FunctionalPurpose.ROOMS_READ,FunctionalPurpose.ROOMS_INTERACT),mutation=true,setupRequired=true,
            fetch={api,token,permission,_->api.nativeTripRouteOrder(id,carId,body,permission.revision,token);Unit}),callback)
    }
    override fun completeCourse(id: String,carId: String,packId: String,callback: (Result<Unit>)->Unit): Closeable =
        client.call(NativeSocialRequest(setOf(FunctionalPurpose.ROOMS_READ,FunctionalPurpose.ROOMS_INTERACT),mutation=true,setupRequired=true,
            fetch={api,token,permission,_->api.nativeTripCourseComplete(id,carId,packId,permission.revision,token);Unit}),callback)
    override fun reportDrivingScore(id: String,carId: String,packId: String,report: DrivingScoreReport,callback: (Result<Unit>)->Unit): Closeable {
        require(!report.final)
        return client.call(NativeSocialRequest(setOf(FunctionalPurpose.ROOMS_READ,FunctionalPurpose.ROOMS_INTERACT),mutation=true,
            fetch={api,token,permission,_->
                val status=api.nativeTripDrivingScore(id,carId,packId,report.body(),permission.revision,token).getString("status")
                check(status in setOf("updated","unchanged"));Unit}),callback)
    }
    override fun completeCourse(id: String,carId: String,packId: String,report: DrivingScoreReport,callback: (Result<Unit>)->Unit): Closeable {
        require(report.final)
        return client.call(NativeSocialRequest(setOf(FunctionalPurpose.ROOMS_READ,FunctionalPurpose.ROOMS_INTERACT),mutation=true,setupRequired=true,
            fetch={api,token,permission,_->
                val body=report.body()
                api.nativeTripCourseComplete(id,carId,packId,body,permission.revision,token);Unit}),callback)
    }
    override fun completeJoinedCourse(id: String,carId: String,packId: String,routeRevision: Long,progressRevision: Long,
        report: DrivingScoreReport,callback: (Result<Unit>)->Unit): Closeable {
        require(report.final)
        val progress=TripRouteContractCodec.completionBody(routeRevision,progressRevision)
        return client.call(NativeSocialRequest(setOf(FunctionalPurpose.ROOMS_READ,FunctionalPurpose.ROOMS_INTERACT),mutation=true,setupRequired=true,
            fetch={api,token,permission,_->
                val body=org.json.JSONObject()
                for(key in progress.keys())body.put(key,progress.get(key))
                check(api.nativeTripCourseComplete(id,carId,packId,body,permission.revision,token).getString("status")=="completed");Unit}),callback)
    }
    override fun reportFinalDrivingScore(id: String,carId: String,packId: String,report: DrivingScoreReport,callback: (Result<Unit>)->Unit): Closeable {
        require(report.final)
        return client.call(NativeSocialRequest(setOf(FunctionalPurpose.ROOMS_READ,FunctionalPurpose.ROOMS_INTERACT),mutation=true,
            fetch={api,token,permission,_->
                check(api.nativeTripCourseComplete(id,carId,packId,report.body(),permission.revision,token).getString("status")=="completed");Unit}),callback)
    }
    override fun routeArrival(id: String,carId: String,routeRevision: Long,progressRevision: Long,item: TripRouteItem,callback: (Result<TripRoutePlan>)->Unit): Closeable =
        routeArrival(id,carId,routeRevision,progressRevision,item,false,callback)
    override fun routeArrival(id: String,carId: String,routeRevision: Long,progressRevision: Long,item: TripRouteItem,
        singleJoinCompletion: Boolean,callback: (Result<TripRoutePlan>)->Unit): Closeable {
        val body=TripRouteContractCodec.arrivalBody(routeRevision,progressRevision,item,singleJoinCompletion)
        return client.call(NativeSocialRequest(setOf(FunctionalPurpose.ROOMS_READ,FunctionalPurpose.ROOMS_INTERACT),mutation=true,setupRequired=true,
            diagnosticScope="trip.route-arrival",fetch={api,token,permission,_->
                TripRouteContractCodec.arrival(api.nativeTripRouteArrival(id,carId,body,permission.revision,token))}),callback)
    }
    override fun reportTripDrivingScore(id: String,carId: String,report: DrivingScoreReport,callback: (Result<Unit>)->Unit): Closeable =
        client.call(NativeSocialRequest(setOf(FunctionalPurpose.ROOMS_READ,FunctionalPurpose.ROOMS_INTERACT),mutation=true,
            fetch={api,token,permission,_->
                check(api.nativeTripTotalScore(id,carId,report.body(),permission.revision,token).getString("status") in setOf("updated","unchanged"));Unit}),callback)
    override fun readDrivingVersus(id: String,callback: (Result<TripDrivingVersus>)->Unit): Closeable =
        client.call(NativeSocialRequest(setOf(FunctionalPurpose.ROOMS_READ),diagnosticScope="trip.driving-versus.read",fetch={api,token,_,_->
            TripDrivingVersusCodec.read(api.nativeTripDrivingVersus(id,token))}),callback)
    override fun routeProgress(id: String,carId: String,routeRevision: Long,next: TripRouteItem?,callback: (Result<Unit>)->Unit): Closeable {
        val body=org.json.JSONObject().put("routeRevision",routeRevision).put("next",next?.let {
            NativeTripsCodec.routeBody(listOf(it)).getJSONArray("items").getJSONObject(0)
        } ?: org.json.JSONObject.NULL)
        return client.call(NativeSocialRequest(setOf(FunctionalPurpose.ROOMS_READ,FunctionalPurpose.ROOMS_INTERACT),mutation=true,
            diagnosticScope="trip.route-progress",fetch={api,token,permission,_->
                check(api.nativeTripRouteProgress(id,carId,body,permission.revision,token).getString("status")=="updated");Unit}),callback)
    }
}
