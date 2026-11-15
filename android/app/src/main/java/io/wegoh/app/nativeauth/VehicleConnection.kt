package io.wegoh.app.nativeauth

import android.content.Context
import android.os.Handler
import android.os.Looper
import org.json.JSONArray
import org.json.JSONObject
import java.io.Closeable
import java.util.concurrent.CopyOnWriteArraySet
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicLong

/** App integration boundary: start/observe/disconnect, never CSR/PEM/token plumbing.
 * One installation and active account per Android OS user. Existing profile/key is
 * preserved; migration is decided by the server, not by discarding old state.
 * Setup stays closed until the app supplies actual CarUx + foreground permission.
 */
class VehicleConnection private constructor(context: Context, profile: String,
    private val nativeFactory: (NativeDeviceIdentity) -> NativeApiClient,
    private val enrollmentFactory: () -> NativeApiClient, private val clock: () -> Long) : Closeable {
    constructor(context: Context) : this(context,"vehicle",{NativeApiClient.native(it)},
        {NativeApiClient.enrollment()},System::currentTimeMillis)

    enum class Scope(val wire: String) { COURSES("courses:read"), PLAYLISTS("playlists:read"), ACCOUNT_WRITE("account:write") }
    enum class Stage { CHECKING, READY, SETUP_BLOCKED, APPROVAL_REQUIRED, CONNECTING,
        CONNECTED, LOCKED, REMOTE_REVOCATION_PENDING, DENIED, EXPIRED, RECOVERY_REQUIRED, UNAVAILABLE }
    class Progress internal constructor(val stage: Stage, val userCode: String? = null,
        val verificationUri: String? = null, val expiresAtMillis: Long? = null,
        val retryAfterSeconds: Int? = null, val canRegisterAgain: Boolean = false,
        approvedOptionalScopes: Set<Scope> = emptySet(),deniedOptionalScopes: Set<Scope> = emptySet(), val previousConnection: Progress? = null) {
        val deniedOptionalScopes: Set<Scope> = java.util.Collections.unmodifiableSet(deniedOptionalScopes.toSet())
        val approvedOptionalScopes: Set<Scope> = java.util.Collections.unmodifiableSet(approvedOptionalScopes.toSet())
        override fun toString() = "VehicleConnection.Progress($stage)"
    }
    private val applicationContext=context.applicationContext
    private val logicalProfile=profile
    private val ownerKey=applicationContext.noBackupFilesDir.absolutePath+":"+logicalProfile
    private lateinit var store: NativeConnectionState
    @Volatile private var lostIdentity=false
    private val codec=NativeAccessCodec(context.applicationContext)
    private val worker=Executors.newSingleThreadScheduledExecutor()
    /** Listen-together calls must answer within the presence window, so they do not queue behind [worker]'s reads. */
    private val lanes=NativeCallLanes(worker,Executors.newSingleThreadExecutor())
    private val privacyWorker=Executors.newSingleThreadExecutor()
    private val eventWorker=Executors.newFixedThreadPool(2)
    @Volatile private var poll: java.util.concurrent.ScheduledFuture<*>?=null
    private val main=Handler(Looper.getMainLooper())
    private val uiEvents=SharedNativeEvents({action->main.post {action()}},
        {listener,callback->connectOwnedEvents(listener,false,callback)})
    private val climateEvents=SharedNativeEvents({action->main.post {action()}},
        {listener,callback->connectOwnedEvents(listener,true,callback)})
    private val observers=CopyOnWriteArraySet<(Progress)->Unit>()
    private val sockets=CopyOnWriteArraySet<Closeable>()
    private val socketGuard=Any()
    private val epoch=AtomicLong(0)
    @Volatile private var sessionRenewal: java.util.concurrent.ScheduledFuture<*>?=null
    private val sessionRecheckQueued=AtomicBoolean(false)
    private val socketVersion=AtomicLong(0)
    internal data class DataBoundary(val revision: Long,val storageKey: String,val scopes: Set<Scope>,val expiresAtMillis: Long)
    @Volatile private var dataBoundary: DataBoundary?=null
    private val socialClients=CopyOnWriteArraySet<NativeSocialClient>()
    private val voiceReservation=java.util.concurrent.atomic.AtomicReference<Any?>(null)
    private val functionalGate=FunctionalPermissionGate()
    private val functionalVersion=AtomicLong(0)
    private val mutationGate=NativeMutationGate()
    private fun invalidateFunctionalPermissions(reason: String,scope: String?=null,failure: Throwable?=null) {
        synchronized(functionalGate) {functionalVersion.incrementAndGet();functionalGate.clear()}
        functionalDiagnostic(NativeFunctionalDiagnostics.invalidated(reason,scope,failure,gateCleared=true,clients=socialClients.size))
        socialClients.forEach {it.authorityInvalidated(reason)}
    }
    /** A permission snapshot replaced the cached one: clients end without clearing the gate. */
    private fun functionalStampChanged(reason: String,scope: String) {
        functionalDiagnostic(NativeFunctionalDiagnostics.invalidated(reason,scope,null,gateCleared=false,clients=socialClients.size))
        socialClients.forEach {it.authorityInvalidated(reason)}
    }
    /** Every invalidation writes its line, so a periodic loop stays visible; per-client endings are rate limited. */
    private fun functionalDiagnostic(line: String) {WegoLog.i("WegoH",line)}
    private val socialEndLimit=DiagnosticRateLimit(android.os.SystemClock::elapsedRealtime)
    internal fun socialEnded(client: NativeSocialClient,why: NativeFunctionalDiagnostics.End,cause: String?,expiryInSeconds: Long?) {
        val suppressed=socialEndLimit.admit("${client.diagnosticKind} ${why.wire} $cause") ?: return
        WegoLog.i("WegoH",NativeFunctionalDiagnostics.ended(client.diagnosticKind,why,cause,expiryInSeconds,suppressed))
    }
    private val executions=CopyOnWriteArraySet<CourseExecutionMonitor>()
    internal fun readDisplayAuthority(): Progress {
        val current=progress
        return Progress(current.stage,canRegisterAgain=lostIdentity,approvedOptionalScopes=current.approvedOptionalScopes,deniedOptionalScopes=deniedScopes)
    }
    internal fun dataEpoch()=epoch.get()
    internal fun dataStreamRevision()=socketVersion.get()
    internal fun accountDataBoundary()=contentDataBoundary(Scope.COURSES)
    internal fun verifiedScoreReportAuthority(): ScoreReportAuthority? =
        if(verifiedDataBoundary()!=null)functionalGate.scoreReportAuthority(clock()) else null
    internal fun verifiedDataBoundary()=dataBoundary?.takeIf {foreground && currentSnapshot(it)}
    internal fun contentDataBoundary(scope: Scope)=verifiedDataBoundary()?.takeIf {scope in it.scopes && scope !in deniedScopes}
    private fun currentSnapshot(value: DataBoundary?)=value!=null && !closed.get() && value==dataBoundary &&
        value.revision==epoch.get() && clock()<value.expiresAtMillis && (!blocked.get() || progress.stage==Stage.CHECKING)
    private val blocked=AtomicBoolean(true)
    private val closed=AtomicBoolean(false)
    private val initialized=AtomicBoolean(false)
    private val starting=AtomicBoolean(false)
    private val disconnectBeforeReady=AtomicBoolean(false)
    @Volatile private var setupAllowed=false
    private val drivingSetupEpoch=java.util.concurrent.atomic.AtomicLong(0)
    @Volatile private var foreground=false
    @Volatile private var progress=Progress(Stage.CHECKING)
    @Volatile private var deniedScopes: Set<Scope> = emptySet()
    private lateinit var identity: NativeDeviceIdentity

    /** Background failure reports go out only on a verified, current session; a rejection never signs out. */
    private val diagnosticsSender=ClientDiagnostics.Sender {body->
        if(closed.get() || blocked.get() || progress.stage!=Stage.CONNECTED || !sessionReusable())return@Sender false
        nativeFactory(identity).clientDiagnostics(body,read().getJSONObject("credentials").getString("accessToken"))
        true
    }
    private val accountReads=object: AuthorizedAccountReads {
        override fun <T> read(scope: Scope?,callback: (Result<T>)->Unit,normalizeFailure: (Throwable)->Throwable,fetch: (NativeApiClient,JSONObject)->T)=readValue(scope,callback,normalizeFailure=normalizeFailure,fetch=fetch)
    }
    val profileApi: ProfileApi = NativeProfileApi(accountReads,::updateProfileName,::updateVehicleProfile)
    val coursesApi: CoursesApi = NativeCoursesApi(accountReads)
    val discoveryApi: DiscoveryApi = NativeDiscoveryApi(accountReads)
    internal val courseRoadMapsApi = CourseRoadMapsApi(accountReads)
    val playlistsApi: PlaylistsApi = NativePlaylistsApi(accountReads)
    internal fun currentDataBoundary()=dataBoundary?.takeIf {currentSnapshot(it)}
    private val boundaryObservers=CopyOnWriteArraySet<()->Unit>()
    private val boundaryExpiry=Runnable {boundaryObservers.forEach {it()}}
    internal fun observeDataBoundary(observer: ()->Unit): Closeable {
        boundaryObservers.add(observer)
        observer()
        return Closeable {boundaryObservers.remove(observer)}
    }

    init {
        synchronized(OWNERS) { check(OWNERS[ownerKey]?.get()?.let { !it.closed.get() } != true) { "NATIVE_CONNECTION_ALREADY_OPEN" };OWNERS[ownerKey]=java.lang.ref.WeakReference(this) }
        ClientDiagnostics.attach(diagnosticsSender)
        worker.execute {
            safely(allowClosed=true,operation=NativeConnectionDiagnostics.Operation.INITIALIZE) {
                store=NativeConnectionState(applicationContext,selectedProfile())
                val existing=store.hasStateOrKey()
                store.locked {
                    store.initialize();var root=store.read()
                    identity=NativeDeviceIdentity(context.applicationContext,root.getString("installationId"))
                    if(existing || root.optBoolean("identityInitialized")) identity.requireExisting()
                    else identity.initialize()
                    if(!root.has("publicContract")) {
                        val migrated=if(existing) NativeConnectionMigration.convert(root,identity.installationKeyId())
                            else NativeConnectionMigration.fresh(root)
                        if(existing) migrated.put("prePublicV1SourceSha256",store.preservePrePublicV1())
                        store.write(migrated)
                        check(NativeAccessCodec.canonical(store.read()).contentEquals(NativeAccessCodec.canonical(migrated))) {"NATIVE_STATE_MIGRATION_INVALID"}
                        root=store.read()
                    } else root=NativeConnectionMigration.convert(root,identity.installationKeyId())
                    val state=root.getJSONObject("access")
                    epoch.set(maxOf(epoch.get(),state.getLong("epoch")))
                    if(disconnectBeforeReady.get()) lockState(state,epoch.incrementAndGet())
                    else if(state.has("credentials") && !state.has("authorization")) {
                        if(state.optBoolean("keepSignedIn",false)) state.put("phase","account_check_required")
                        else lockState(state,epoch.incrementAndGet())
                    }
                    store.write(root);initialized.set(true)
                }
                publishStored()
                if(read().has("credentials") && !read().has("authorization") && read().optString("phase") !in setOf("locked","revoke_pending"))verifyAccount()
                else if(foreground)step()
            }
        }
    }
    fun observe(observer: (Progress)->Unit): Closeable {
        observers.add(observer);main.post { if(observers.contains(observer)) observer(visible(progress)) }
        return Closeable { observers.remove(observer) }
    }
    /** NO_SETUP or unknown restrictions must pass false. This is not a speed/gear heuristic. */
    fun setSetupAllowed(allowed: Boolean) {
        if(setupAllowed==allowed)return
        if(!allowed && setupAllowed)drivingSetupEpoch.incrementAndGet()
        setupAllowed=allowed;mutationGate.setAllowed(allowed && foreground)
        emit(if(lostIdentity)Progress(Stage.RECOVERY_REQUIRED,canRegisterAgain=true) else progress)
        if(!allowed) {poll?.cancel(false);poll=null}
        else if(foreground && !closed.get()) worker.execute {safely {if(read().has("authorization"))step()}}
    }
    fun setForeground(visible: Boolean) {
        if(foreground==visible)return
        if(!visible && foreground)drivingSetupEpoch.incrementAndGet()
        foreground=visible
        mutationGate.setAllowed(visible && setupAllowed)
        if(!visible) {poll?.cancel(false);poll=null;closeUiSockets("background") }
        emit(if(lostIdentity)Progress(Stage.RECOVERY_REQUIRED,canRegisterAgain=true) else progress)
        if(visible)ensureConnected()
    }
    private fun requestSessionRecheck(cause: String) {
        if(closed.get() || !sessionRecheckQueued.compareAndSet(false,true))return
        invalidateFunctionalPermissions("session_recheck_$cause")
        worker.execute {try {safely {
            verifyAccount()
        }}finally{sessionRecheckQueued.set(false)}}
    }
    private fun authenticationFailed(error: Throwable?) {
        if(error is NativeApiClient.Failure && error.status==401)requestSessionRecheck("unauthorized")
    }
    fun status(): Progress = visible(progress)
    /** Explicit user action only. Empty optional set requests only required scopes. */
    fun start(name: String, optionalScopes: Set<Scope> = emptySet()) {
        if(closed.get())return
        if(!setupAllowed || !foreground) { emit(Progress(Stage.SETUP_BLOCKED));return }
        if(!starting.compareAndSet(false,true))return
        try {worker.execute {try {safely(operation=NativeConnectionDiagnostics.Operation.START) {
            check(setupAllowed && foreground && !closed.get())
            var saved=read()
            val pending=saved.optJSONObject("authorization")
            if(pending!=null || !saved.has("credentials"))emit(Progress(Stage.CONNECTING))
            if(pending!=null && pending.optJSONObject("public")?.let {publicExpiry(it)<=clock()}==true &&
                !pending.optBoolean("expired") && pending.optJSONObject("response")?.optString("disposition") !in setOf("TERMINAL","USER_RESTART_ALLOWED","REAUTHORIZE")) {
                val expected=epoch.get()
                update(expected) {it.getJSONObject("authorization").put("nextPollAt",0)}
                try {step(reconcileExpired=true)} catch(failure: NativeApiClient.Failure) {
                    if(pending.getString("action")!="ACCOUNT_AUTHORIZE" || failure.code!="AUTHORIZATION_EXPIRED")throw failure
                    check(expected==epoch.get() && setupAllowed && foreground && !closed.get())
                    update(expected) {it.getJSONObject("authorization").put("expired",true)}
                }
                check(expected==epoch.get() && setupAllowed && foreground && !closed.get());saved=read()
            }
            if(saved.has("credentials") && !saved.has("authorization")) {
                val expired=saved.getJSONObject("credentials").getLong("grantExpiresAt")<=clock()/1000
                if(!expired) {verifyAccount();return@safely}
                val next=epoch.incrementAndGet();update(next,allowNewEpoch=true) {lockState(it,next)}
            }
            if(progress.stage!=Stage.CONNECTING)emit(Progress(Stage.CONNECTING))
            recoverCertificateIfNeeded()
            if(saved.has("authorization")) {
                val response=saved.getJSONObject("authorization").optJSONObject("response")
                if(saved.getJSONObject("authorization").optBoolean("expired")) {
                    update(epoch.get()) {it.put("cancelledAuthorization",it.getJSONObject("authorization"));it.remove("authorization")}
                    begin(name,read(),optionalScopes)
                } else if(response?.optString("disposition")=="USER_RESTART_ALLOWED") restart(name,saved,optionalScopes)
                else if(response?.optString("disposition") in setOf("TERMINAL","REAUTHORIZE")) {
                    update(epoch.get()) { it.put("cancelledAuthorization",it.getJSONObject("authorization"));it.remove("authorization") }
                    begin(name,read(),optionalScopes)
                }
            } else begin(name,read(),optionalScopes)
            step()
        }}finally{starting.set(false)}}}catch(failure: java.util.concurrent.RejectedExecutionException) {
            starting.set(false)
            if(!closed.get())throw failure
        }
    }
    fun requestScopes(name: String, optionalScopes: Set<Scope>) {
        if(!setupAllowed || !foreground || closed.get() || progress.stage!=Stage.CONNECTED || blocked.get()) return
        val requested=progress.approvedOptionalScopes+optionalScopes
        if(progress.approvedOptionalScopes.containsAll(requested) && progress.deniedOptionalScopes.intersect(requested).isEmpty()) return
        blocked.set(true);val next=epoch.incrementAndGet();closeSockets("scope_request");poll?.cancel(false);poll=null
        emit(Progress(Stage.CONNECTING))
        worker.execute { safely {
            check(next==epoch.get() && !closed.get())
            update(next,allowNewEpoch=true) {it.put("epoch",next)}
            begin(name,read(),requested)
            if(foreground && setupAllowed) step() else publishStored()
        } }
    }
    /** Refresh status/recover the same operation; never creates a new key or approval. */
    fun check() { worker.execute { safely(operation=NativeConnectionDiagnostics.Operation.CHECK) { step() } } }
    fun ensureConnected() {
        if(closed.get())return
        worker.execute {safely {
            if(read().has("credentials") && !read().has("authorization")) {verifyAccount(force=false);publishStored()}
            else step()
        }}
    }

    /** Explicit loss recovery only. Preserve every old cipher/key/travel record.
     * The phone must revoke the lost device; no old identity/grant is restored.
     * This only prepares a new installation. start() requires its own user action. */
    fun registerNewInstallation() {
        if(!setupAllowed || !foreground || !lostIdentity || closed.get()) {emit(if(lostIdentity)Progress(Stage.RECOVERY_REQUIRED,canRegisterAgain=true) else Progress(Stage.SETUP_BLOCKED));return}
        blocked.set(true);val next=epoch.incrementAndGet();closeSockets("new_installation");poll?.cancel(false);poll=null
        worker.execute {safely {
            check(setupAllowed && foreground && lostIdentity && next==epoch.get())
            val previousProfile=runCatching {selectedProfile()}.getOrDefault(logicalProfile)
            val selector=selectionStore(next=true)
            selector.locked {
                selector.initialize();val selection=selector.read()
                val old=previousProfile
                val history=selection.optJSONArray("previousProfiles") ?: JSONArray()
                history.put(old)
                val fresh="recovered_"+randomId().take(24)
                selection.put("previousProfiles",history).put("activeProfile",fresh)
                selector.write(selection) // Explicit intent is durable before a new key exists.
                store=NativeConnectionState(applicationContext,fresh)
            }
            store.locked {
                store.initialize();val root=store.read()
                identity=NativeDeviceIdentity(applicationContext,root.getString("installationId"));identity.initialize()
                root.put("identityInitialized",true).put("publicContract",1).put("access",JSONObject().put("epoch",next).put("phase","ready").put("outbox",JSONArray()))
                store.write(root);initialized.set(true)
            }
            lostIdentity=false;disconnectBeforeReady.set(false);publishStored()
        }}
    }
    private fun selectionStore(next: Boolean = false): NativeConnectionState {
        val prefix="selection_"+NativeDeviceIdentity.sha256(logicalProfile.toByteArray()).take(24)
        val matcher=Regex("wegoh\\.native\\.state\\."+prefix+"(?:_([1-9][0-9]{0,4}))?(?:\\.enc(?:\\.bak)?)?")
        val keys=java.security.KeyStore.getInstance("AndroidKeyStore").apply {load(null)}
        val names=keys.aliases().toList()+applicationContext.noBackupFilesDir.listFiles().orEmpty().map {it.name}
        val indices=names.mapNotNull {matcher.matchEntire(it)?.groupValues?.get(1)?.let {n -> if(n.isEmpty())0 else n.toInt()}}
        val index=if(next)(indices.maxOrNull() ?: 0)+1 else indices.maxOrNull() ?: 0
        check(index<=99999)
        return NativeConnectionState(applicationContext,prefix+if(index==0)"" else "_$index")
    }
    private fun selectedProfile(): String {
        val selection=selectionStore()
        if(!selection.hasStateOrKey())return logicalProfile
        // Newest immutable selector never silently falls back if its key/file is lost.
        return selection.locked {selection.initialize();selection.read().getString("activeProfile").also {check(Regex("recovered_[a-f0-9]{24}").matches(it)) {"NATIVE_STATE_INVALID"}}}
    }
    /** Immediate UI/WSS lock is independent from an in-flight10s request. The
     * separate writer persists only revoke capability before trying the network.
     * No travel records are removed and no previous account is restored on failure.
     */
    fun disconnect() {
        blocked.set(true);val next=epoch.incrementAndGet()
        if(!initialized.get()) disconnectBeforeReady.set(true)
        closeSockets("disconnect")
        emit(Progress(Stage.LOCKED))
        if(!initialized.get()) return
        privacyWorker.execute {
            try {
                update(next,allowNewEpoch=true) { lockState(it,next) }
                emit(Progress(if(read().getJSONArray("outbox").length()>0) Stage.REMOTE_REVOCATION_PENDING else Stage.LOCKED))
                if(!closed.get()) worker.execute { safely { drainRevocations() } }
            } catch(failure: Throwable) { emit(Progress(Stage.RECOVERY_REQUIRED)) }
        }
    }
    fun switchAccount(name: String, optionalScopes: Set<Scope> = emptySet()) {
        disconnect()
        privacyWorker.execute { if(!closed.get()) start(name,optionalScopes) }
    }
    class Permissions internal constructor(scopes: Set<Scope>,val keepSignedIn: Boolean,
        val consentVersion: Long,val grantExpiresAtMillis: Long) {
        val approvedOptionalScopes: Set<Scope> = java.util.Collections.unmodifiableSet(scopes.toSet())
        override fun toString() = "VehicleConnection.Permissions(redacted)"
    }
    fun readCourses(callback: (Result<NativeApiClient.Document>)->Unit)=coursesApi.readCourses(callback)
    fun readPublicPacks(callback: (Result<NativeApiClient.Document>)->Unit)=discoveryApi.readPublicPacks(callback)
    fun readPlaylists(callback: (Result<NativeApiClient.Document>)->Unit)=playlistsApi.readPlaylists(callback)
    fun readPackVersion(id: String,version: Int,callback: (Result<NativeApiClient.PackVersion>)->Unit)=coursesApi.readPackVersion(id,version,callback)
    fun readPlaylist(id: String,callback: (Result<NativeApiClient.Document>)->Unit)=playlistsApi.readPlaylist(id,callback)
    fun readAccountDisplayName(callback: (Result<String>)->Unit)=profileApi.readDisplayName(callback)
    fun updateAccountName(name: String,expectedName: String,callback: (Result<String>)->Unit)=profileApi.updateDisplayName(name,expectedName,callback)

    private fun updateVehicleProfile(plate: String,name: String,revision: Int,callback: (Result<VehicleProfile>)->Unit) {
        require(VehicleProfile.validPlate(plate) && VehicleProfile.validName(name) && revision>=0)
        val expected=epoch.get()
        readValue(null,callback) {client,credentials ->
            val boundary=verifiedDataBoundary()
            check(boundary!=null && foreground && setupAllowed && !closed.get() && expected==epoch.get())
            val response=decodeVehicleProfile(client.updateVehicleProfile(plate,name,revision,credentials.getString("accessToken")),credentials.getString("deviceId"))
            check(response.plateNumber==plate && response.name==name && response.revision.toLong()==revision.toLong()+1)
            check(foreground && setupAllowed && !closed.get() && expected==epoch.get() && boundary==verifiedDataBoundary())
            response
        }
    }
    private fun updateProfileName(name: String,expectedName: String,callback: (Result<String>)->Unit) {
        require(validAccountName(name))
        val expected=epoch.get()
        readValue(null,callback) {client,credentials ->
            val boundary=verifiedDataBoundary()
            check(boundary!=null && foreground && setupAllowed && !closed.get() && expected==epoch.get())
            val response=client.updateAccountName(name,expectedName,credentials.getString("accessToken"))
            val user=response.getJSONObject("user")
            check(response.keys().asSequence().toSet()==setOf("user") && user.keys().asSequence().toSet()==setOf("id","displayName"))
            check(user.get("id")==credentials.getString("accountId") && user.get("displayName")==name)
            check(foreground && setupAllowed && !closed.get() && expected==epoch.get() && boundary==verifiedDataBoundary())
            name
        }
    }
    fun readPermissions(callback: (Result<Permissions>)->Unit) = readValue(null,callback) {client,credentials ->
        val value=client.readDocument("/v1/device/permissions",credentials.getString("accessToken")).asObject()
        check(value.get("authorizationVersion")==1 && value.getString("deviceId")==credentials.getString("deviceId") && value.get("keepSignedIn") is Boolean)
        check(value.getJSONArray("scopes").toString()==credentials.getJSONArray("scopes").toString())
        for(field in listOf("consentVersion","grantExpiresAt")) {
            check((value.get(field) is Int || value.get(field) is Long) && value.getLong(field)==credentials.getLong(field))
        }
        Permissions(Scope.entries.filter {scope -> val values=value.getJSONArray("scopes");(0 until values.length()).any {values.getString(it)==scope.wire}}.toSet(),
            value.getBoolean("keepSignedIn"),value.getLong("consentVersion"),value.getLong("grantExpiresAt")*1000)
    }
    internal fun readCommandReceiver(callback: (Result<CommandReceiver>)->Unit) =
        commandReceiverAccess(enabling=false, callback) {client, credentials ->
            CommandReceiver.decode(client.commandReceiver(credentials.getString("accessToken")),
                credentials.getString("deviceId"), credentials.getString("grantId"))
        }

    internal fun setCommandReceiver(previous: CommandReceiver, enabled: Boolean, callback: (Result<CommandReceiver>)->Unit) =
        commandReceiverAccess(enabling=enabled, callback={result->
            if(result.isSuccess)invalidateFunctionalPermissions("receiver_changed")
            callback(result)
        }) {client, credentials ->
            check(previous.deviceId == credentials.getString("deviceId") && previous.grantId == credentials.getString("grantId"))
            val value = client.setCommandReceiver(previous, enabled, credentials.getString("accessToken"))
            val updated = CommandReceiver.decode(value, previous.deviceId, previous.grantId)
            val expectedRevision = if (enabled == previous.enabled) previous.revision else previous.revision + 1
            check(updated.enabled == enabled && updated.revision == expectedRevision)
            updated
        }

    private fun commandReceiverAccess(enabling: Boolean, callback: (Result<CommandReceiver>)->Unit,
        fetch: (NativeApiClient, JSONObject)->CommandReceiver) {
        val expected = epoch.get()
        val setup = drivingSetupEpoch.get()
        fun allowed(): Boolean {
            if (closed.get() || expected != epoch.get()) return false
            return if (enabling) foreground && setupAllowed && setup == drivingSetupEpoch.get()
            else foreground || climateReceivers.isNotEmpty()
        }

        if (!allowed()) {
            main.post { callback(Result.failure(IllegalStateException("NATIVE_RECEIVER_UNAVAILABLE"))) }
            return
        }
        val permit = if (enabling) mutationGate.permit({ allowed() && currentSnapshot(dataBoundary) }, {}) else null
        worker.execute {
            var boundary: DataBoundary? = null
            val result = runCatching {
                check(allowed())
                verifyAccount(force=false)
                boundary = dataBoundary
                check(allowed() && !blocked.get() && currentSnapshot(boundary))
                val credentials = read().getJSONObject("credentials")
                val client = nativeFactory(identity)
                if (permit == null) fetch(client, credentials)
                else client.withMutationPermit(permit) { fetch(client, credentials) }
            }.onFailure(::authenticationFailed)
            permit?.close()
            main.post {
                if (result.isFailure || allowed() && currentSnapshot(boundary)) callback(result)
                else callback(Result.failure(IllegalStateException("NATIVE_RECEIVER_CHANGED")))
            }
        }
    }

    /** Sends one opt-in error report with the current vehicle credential; no scope or purpose is added. */
    internal fun sendClientReport(body: JSONObject,callback: (Result<String>)->Unit)=readValue(null,callback) {client,credentials->
        client.clientReport(body,credentials.getString("accessToken"))
    }
    fun readFunctionalPermissions(callback: (Result<FunctionalPermissions>)->Unit) {
        val expected=functionalVersion.get()
        readValue(null,{result ->
            if(expected!=functionalVersion.get()) {callback(Result.failure(IllegalStateException("NATIVE_FUNCTIONAL_PERMISSION_STALE")));return@readValue}
            result.fold(onSuccess={snapshot->
                val checked=runCatching {synchronized(functionalGate) {
                    check(expected==functionalVersion.get()) {"NATIVE_FUNCTIONAL_PERMISSION_STALE"}
                    if(functionalGate.replace(snapshot))functionalStampChanged("stamp_changed","permissions.read");snapshot
                }}
                if(checked.isFailure)invalidateFunctionalPermissions("permissions_stale","permissions.read")
                callback(checked)
            },onFailure={invalidateFunctionalPermissions("permissions_read_failed","permissions.read");callback(Result.failure(it))})
        }) {client,credentials ->
            codec.functional.permissions(client.functionalPermissions(credentials.getString("accessToken"),codec.functional),
                credentials.getString("deviceId"),credentials.getString("grantId"),credentials.getLong("grantExpiresAt")*1000,clock())
        }
    }
    /** Explicit functional business client; creation does not open a socket or approve consent. */
    fun social(): NativeSocialClient {
        check(!closed.get()) {"NATIVE_SOCIAL_CLOSED"}
        return NativeSocialClient(this).also {socialClients.add(it);if(closed.get())it.close()}
    }
    internal fun tripSocial(): NativeSocialClient {
        check(!closed.get()) {"NATIVE_SOCIAL_CLOSED"}
        return NativeSocialClient(this,refreshOnDataChange=true).also {socialClients.add(it);if(closed.get())it.close()}
    }
    /** Creation performs no networking or consent action. One active Voice owner is reserved on open. */
    fun voice(): NativeVoiceClient {
        check(!closed.get()) {"NATIVE_VOICE_CLOSED"}
        return NativeVoiceClient(this)
    }
    internal fun reserveVoice(): Closeable? {
        val lease=Any()
        if(closed.get() || !voiceReservation.compareAndSet(null,lease))return null
        if(closed.get()) {voiceReservation.compareAndSet(lease,null);return null}
        return Closeable {voiceReservation.compareAndSet(lease,null)}
    }
    internal fun loadVoiceCodec()=NativeVoiceContract.load(applicationContext)
    internal fun voiceAudioBackend(): NativeVoiceAudioBackend = NativeVoiceAndroidAudio(applicationContext)
    internal fun socialClosed(client: NativeSocialClient) {socialClients.remove(client)}
    internal fun socialNow()=clock()
    internal fun socialBaseExpiry()=dataBoundary?.expiresAtMillis ?: 0L
    internal fun socialBaseCurrent(expected: Long)=expected==epoch.get() && foreground && currentSnapshot(dataBoundary)
    private val climateReceivers=CopyOnWriteArraySet<Any>()
    internal fun reserveClimateReceiver(): Closeable {
        check(!closed.get());val owner=Any();climateReceivers.add(owner)
        return Closeable {climateReceivers.remove(owner);socialClients.filter {it.climateReceiver}.forEach {it.authorityInvalidated("receiver_released",connectionWide=false)}}
    }
    internal fun climateBaseCurrent(expected: Long)=expected==epoch.get() && eventRuntimeAllowed(true) && currentSnapshot(dataBoundary)
    private fun eventRuntimeAllowed(climate: Boolean)=!closed.get() && (if(climate)climateReceivers.isNotEmpty() else foreground)
    internal fun climateSocial(): NativeSocialClient {
        check(!closed.get());return NativeSocialClient(this,true,refreshOnDataChange=true).also {socialClients.add(it)}
    }
    internal fun <T> socialCall(client: NativeSocialClient,token: Long,request: NativeSocialRequest<T>,callback: (Result<T>)->Unit): Closeable {
        val queuedAt=System.nanoTime()
        fun trace(result: String) {request.diagnosticScope?.let {WegoLog.i("WegoH","$it: $result")}}
        trace("queued")
        val cancelled=AtomicBoolean(false);val expected=epoch.get();val expectedFunctional=functionalVersion.get()
        val stamp=java.util.concurrent.atomic.AtomicReference<FunctionalPermissionGate.Stamp?>()
        val attempted=AtomicBoolean(false)
        /** Last step reached, so an unscoped failure before the business request still names where it failed. */
        var phase="prepare"
        val expectedSetup=drivingSetupEpoch.get()
        val permit=if(request.mutation && request.setupRequired)mutationGate.permit({
            setupAllowed && foreground && expectedSetup==drivingSetupEpoch.get() && !cancelled.get() &&
                client.current(token) && expected==epoch.get() && expectedFunctional==functionalVersion.get() &&
                stamp.get()?.let {functionalGate.current(it,clock())}==true
        },{attempted.set(true)}) else null
        lanes.execute(request.realtime) {
            trace("started wait_ms=${(System.nanoTime()-queuedAt)/1_000_000}${if(request.realtime)" lane=realtime" else ""}")
            var fetched: T? = null
            var fetchedValue = false
            val result=runCatching {
                check(client.current(token) && expected==epoch.get())
                // Off the worker only a settled, verified session is reused; refreshing or rechecking it stays on the worker.
                if(!request.realtime)verifyAccount(force=false)
                else if(blocked.get() || progress.stage!=Stage.CONNECTED || !sessionReusable())lanes.onShared {verifyAccount(force=false)}
                check(client.current(token) && expected==epoch.get() && !blocked.get())
                val credentials=read().getJSONObject("credentials");val api=nativeFactory(identity)
                fun permissions()=codec.functional.permissions(api.functionalPermissions(credentials.getString("accessToken"),codec.functional),
                    credentials.getString("deviceId"),credentials.getString("grantId"),credentials.getLong("grantExpiresAt")*1000,clock())
                val cached=functionalGate.cached(credentials.getString("deviceId"),credentials.getString("grantId"),clock())
                if(cached==null)phase="permissions"
                val before=cached ?: permissions()
                phase="stamp"
                trace("permissions loaded source=${if(cached==null)"server" else "cache"}")
                val current=synchronized(functionalGate) {
                    check(!cancelled.get() && client.current(token) && expected==epoch.get() && expectedFunctional==functionalVersion.get())
                    if(functionalGate.replace(before)) {
                        functionalStampChanged("stamp_changed",NativeFunctionalDiagnostics.scope(request.diagnosticScope,null,phase))
                        throw NativeSocialFailure(NativeSocialFailure.Kind.STALE)
                    }
                    functionalGate.stamp(request.all,request.any,clock())
                };stamp.set(current)
                check(client.current(token) && expectedFunctional==functionalVersion.get())
                if(permit==null)attempted.set(request.mutation)
                val fetch={request.fetch(api,credentials.getString("accessToken"),before,credentials.getString("accountId"))}
                phase="request";trace("request started")
                NativeNetLog.forget()
                val value=try {if(permit!=null)api.withMutationPermit(permit,fetch) else fetch()} catch(error: Exception) {
                    if(!cancelled.get())NativeNetLog.decodeFailed(error);throw error
                }
                fetched=value;fetchedValue=true;phase="response";trace("response loaded")
                check(!cancelled.get() && client.current(token) && expected==epoch.get() && expectedFunctional==functionalVersion.get())
                synchronized(functionalGate) {
                    check(!cancelled.get() && client.current(token) && expected==epoch.get() && expectedFunctional==functionalVersion.get())
                    if(!functionalGate.current(current,clock())) {
                        functionalStampChanged("stamp_stale",NativeFunctionalDiagnostics.scope(request.diagnosticScope,null,phase));throw NativeSocialFailure(NativeSocialFailure.Kind.STALE,mayHaveExecuted=attempted.get())
                    }
                }
                check(client.current(token) && expected==epoch.get() && expectedFunctional==functionalVersion.get())
                client.limitLifetime(token,minOf(before.expiresAtMillis,dataBoundary?.expiresAtMillis ?: 0L,request.expires(value) ?: Long.MAX_VALUE))
                value
            }.recoverCatching {failure ->
                authenticationFailed(failure)
                // A client-side contract/precondition failure would otherwise look like an invalid server response.
                // A caller that cancelled meanwhile trips the same checks; that is not a failure of the exchange.
                if(!cancelled.get() && failure !is NativeApiClient.Failure && failure !is NativeSocialFailure && failure !is java.io.IOException)
                    WegoLog.w("WegoH","native.social: local failure scope=${request.diagnosticScope ?: "unscoped"} "+
                        NativeSocialErrorCodec.localCause(failure))
                throw socialRequestFailure(failure,attempted.get())
            }
            result.exceptionOrNull()?.let {trace(if(cancelled.get())"request cancelled" else "request failed "+NativeSocialErrorCodec.fields(it))}
            permit?.close()
            if(result.isFailure && fetchedValue) {
                @Suppress("UNCHECKED_CAST")
                request.discard(fetched as T)
            }
            main.post {
                if(cancelled.get() || !client.current(token) || expected!=epoch.get() || expectedFunctional!=functionalVersion.get()) {
                    trace("dropped reason=client_changed")
                    result.getOrNull()?.let {request.discard(it)}
                    return@post
                }
                val current=stamp.get()
                if(result.isSuccess && (current==null || !functionalGate.current(current,clock()))) {
                    result.getOrNull()?.let {request.discard(it)}
                    client.authorityInvalidated("stamp_stale",connectionWide=false);return@post
                }
                trace("finished result=${if(result.isSuccess)"succeeded" else "failed"}"+
                    if(result.isFailure)" "+NativeSocialErrorCodec.fields(checkNotNull(result.exceptionOrNull())) else "")
                callback(result)
                val failure=result.exceptionOrNull()
                if(NativeSocialErrorCodec.invalidatesAuthority(failure))invalidateFunctionalPermissions(NativeFunctionalDiagnostics.socialReason(failure),
                    NativeFunctionalDiagnostics.scope(request.diagnosticScope,failure,phase),failure)
            }
        }
        return Closeable {cancelled.set(true);permit?.close()}
    }
    class ScopeRequired(val scope: Scope) : IllegalStateException("NATIVE_SCOPE_REQUIRED")
    private fun <T> readValue(scope: Scope?,callback: (Result<T>)->Unit,onDiscard: (T)->Unit={},normalizeFailure: (Throwable)->Throwable={it},fetch: (NativeApiClient,JSONObject)->T) {
        val expected=epoch.get();val snapshot=java.util.concurrent.atomic.AtomicReference<DataBoundary?>();val fetched=java.util.concurrent.atomic.AtomicReference<T?>();worker.execute {
            val result=runCatching {
                check(foreground && !closed.get() && expected==epoch.get())
                verifyAccount(force=false);val saved=read();check(foreground && !blocked.get() && expected==epoch.get())
                snapshot.set(dataBoundary)
                if(scope!=null && (scope !in approvedScopes(saved) || scope in deniedScopes))throw ScopeRequired(scope)
                NativeNetLog.forget()
                val value=try {fetch(nativeFactory(identity),saved.getJSONObject("credentials"))} catch(error: Exception) {
                    NativeNetLog.decodeFailed(error);throw error
                };fetched.set(value)
                check(!blocked.get() && expected==epoch.get());value
            }.recoverCatching {authenticationFailed(it);throw normalizeFailure(it)}
            if(result.isFailure)fetched.get()?.let {runCatching {onDiscard(it)}}
            if(scope!=null && expected==epoch.get() && result.exceptionOrNull().let {it is NativeApiClient.Failure && it.code=="SCOPE_DENIED"}) {
                deniedScopes=deniedScopes+scope;publishStored()
            }
            main.post { if(expected==epoch.get() && foreground && (result.isFailure || currentSnapshot(snapshot.get()) && (scope==null || scope !in deniedScopes))) callback(result.fold(
                onSuccess={Result.success(it)},onFailure={failure ->
                    Result.failure(if(scope!=null && (failure is ScopeRequired || failure is NativeApiClient.Failure && failure.code=="SCOPE_DENIED")) ScopeRequired(scope)
                        else IllegalStateException("NATIVE_DATA_UNAVAILABLE"))
                })) else result.getOrNull()?.let {value->runCatching {worker.execute {onDiscard(value)}}} }
        }
    }
    internal inner class CourseExecutionMonitor internal constructor(private val boundary: DataBoundary,
        private val expiresAt: Long,private val invalidated: ()->Unit): Closeable {
        private val ended=AtomicBoolean(false)
        private var socket: Closeable?=null
        private var expiry: java.util.concurrent.ScheduledFuture<*>?=null
        internal fun isCurrent()=!ended.get() && !closed.get() && boundary==dataBoundary && boundary.revision==epoch.get() &&
            clock()<expiresAt && (!blocked.get() || progress.stage==Stage.CHECKING) && Scope.COURSES in boundary.scopes && Scope.COURSES !in deniedScopes
        internal fun adopt(value: Closeable) {
            synchronized(this) {
                if(!isCurrent()) {value.close();error("NATIVE_EXECUTION_UNAVAILABLE")}
                socket=value
                expiry=worker.schedule({invalidate()},(expiresAt-clock()).coerceAtLeast(1),TimeUnit.MILLISECONDS)
            }
        }
        internal fun invalidate() {if(end())main.post {invalidated()}}
        private fun end(): Boolean {
            if(ended.getAndSet(true))return false
            synchronized(this) {expiry?.cancel(false);expiry=null;runCatching {socket?.close()};socket=null}
            executions.remove(this);return true
        }
        override fun close() {end()}
    }
    internal fun monitorCourseExecution(boundary: DataBoundary,invalidated: ()->Unit,
        callback: (Result<CourseExecutionMonitor>)->Unit) {
        val expected=epoch.get()
        worker.execute {
            var pending: CourseExecutionMonitor?=null
            val result=runCatching {
                check(foreground && setupAllowed && !closed.get() && boundary==accountDataBoundary())
                verifyAccount(force=false)
                check(foreground && setupAllowed && boundary==accountDataBoundary() && expected==epoch.get())
                val monitor=CourseExecutionMonitor(boundary,boundary.expiresAtMillis,invalidated)
                pending=monitor;executions.add(monitor)
                val listener=object: VehicleEventsListener {
                    override fun onEvent(event: VehicleEvent) {
                        if(event.type=="invalidate" && event.resources.any {it=="courses" || it=="devices"})monitor.invalidate()
                    }
                    override fun onClosed()=monitor.invalidate()
                    override fun onUnavailable()=monitor.invalidate()
                }
                val saved=read();val scopes=saved.getJSONObject("credentials").getJSONArray("scopes")
                val approved=(0 until scopes.length()).map {scopes.getString(it)}.toSet()
                monitor.adopt(nativeFactory(identity).connectEvents(saved.getJSONObject("credentials").getString("accessToken"),
                    NativeEvents.connector(listener,approved)))
                check(foreground && setupAllowed && monitor.isCurrent())
                monitor
            }
            if(result.isFailure)pending?.close()
            main.post {
                if(expected==epoch.get() && foreground && !closed.get())callback(result.fold(
                    onSuccess={if(it.isCurrent())Result.success(it) else {it.close();Result.failure(IllegalStateException("NATIVE_EXECUTION_UNAVAILABLE"))}},
                    onFailure={Result.failure(IllegalStateException("NATIVE_EXECUTION_UNAVAILABLE"))}))
                else pending?.close()
            }
        }
    }
    /** Default WSS feed: TLS1.3/mTLS/Bearer are entirely managed by the SDK.
     * All callbacks arrive on main and are discarded after local epoch/background lock.
     * Server rotation reconnects through the same authority checks and requires a fresh snapshot. */
    fun connectEvents(listener: VehicleEventsListener, callback: (Result<Closeable>)->Unit) = uiEvents.subscribe(listener,callback)
    internal fun connectClimateEvents(listener: VehicleEventsListener,callback: (Result<Closeable>)->Unit)=climateEvents.subscribe(listener,callback)
    private fun connectOwnedEvents(listener: VehicleEventsListener,climate: Boolean,callback: (Result<Closeable>)->Unit) {
        val expected=epoch.get()
        val rotation=NativeEventRotation(
            current={expected==epoch.get() && eventRuntimeAllowed(climate) && !closed.get()},
            connect={quiet,events,completed->
                val connector=NativeApiClient.EventsConnector {endpoint,factory,trust,authorization ->
                    val version=socketVersion.get();val snapshot=dataBoundary
                    val guarded=OwnedVehicleEvents(main,
                        {expected==epoch.get() && version==socketVersion.get() && eventRuntimeAllowed(climate) && currentSnapshot(snapshot)},
                        {expected==epoch.get() && version==socketVersion.get() && eventRuntimeAllowed(climate) && !closed.get()},
                        {expected==epoch.get() && eventRuntimeAllowed(climate) && !closed.get()},
                        {closeSockets("event_queue_overflow")}, {requestSessionRecheck(it)}, events)
                    try {
                        val approved=read().getJSONObject("credentials").getJSONArray("scopes")
                        val scopes=(0 until approved.length()).map {approved.getString(it)}.toSet()
                        val socket=NativeEvents.connector(guarded,scopes,quiet).connect(endpoint,factory,trust,authorization)
                        Closeable {guarded.close();socket.close()}
                    } catch(error: Throwable) {guarded.close();throw error}
                }
                connectEvents(connector,climate,completed)
            },
            schedule={action->val task=Runnable {action()};main.postDelayed(task,11000);Closeable {main.removeCallbacks(task)}},
            listener=listener,completed=callback,log={WegoLog.i("WegoH",it)})
        rotation.start()
    }
    /** Trusted connector owns101/onOpen and must use the supplied default trust/TLS1.3
     * contract. Returned socket is closed on logout, background and manager.close.
     */
    fun connectEvents(connector: NativeApiClient.EventsConnector, callback: (Result<Closeable>)->Unit)=connectEvents(connector,false,callback)
    private fun connectEvents(connector: NativeApiClient.EventsConnector,climate: Boolean,callback: (Result<Closeable>)->Unit) {
        val expected=epoch.get();val resultVersion=AtomicLong(-1)
        val snapshot=java.util.concurrent.atomic.AtomicReference<DataBoundary?>()
        openNativeEventConnection(worker,eventWorker,prepare={
            check(eventRuntimeAllowed(climate) && !closed.get() && expected==epoch.get())
            verifyAccount(force=false);check(eventRuntimeAllowed(climate) && !blocked.get() && expected==epoch.get())
            snapshot.set(dataBoundary);resultVersion.set(socketVersion.get())
            val api=nativeFactory(identity)
            val accessToken=read().getJSONObject("credentials").getString("accessToken")
            val connect: ()->Closeable={api.connectEvents(accessToken,connector)}
            connect
        },complete={opened->
            val result=opened.mapCatching {socket->
                val adopted=synchronized(socketGuard) {
                    if(expected!=epoch.get() || resultVersion.get()!=socketVersion.get() || !eventRuntimeAllowed(climate) || blocked.get() || closed.get())false
                    else {sockets.add(socket);true}
                }
                if(!adopted) {socket.close();error("NATIVE_ACCOUNT_LOCKED")}
                Closeable {synchronized(socketGuard) {sockets.remove(socket)};socket.close()}
            }
            authenticationFailed(result.exceptionOrNull())
            main.post { if(expected==epoch.get() && eventRuntimeAllowed(climate) && (resultVersion.get()<0 || resultVersion.get()==socketVersion.get()) && (result.isFailure || currentSnapshot(snapshot.get()))) callback(result.fold(
                onSuccess={Result.success(it)},onFailure={Result.failure(NativeEventsFailure.from(it))})) }
        })
    }
    private fun begin(name: String, saved: JSONObject, optional: Set<Scope>) {
        val pkce=NativeApiClient.Pkce.generate()
        val certified=identity.certificateState() in setOf(NativeDeviceIdentity.CertificateState.CONFIGURED,NativeDeviceIdentity.CertificateState.RENEWAL_DUE)
        val action=if(certified) "ACCOUNT_AUTHORIZE" else if(identity.certificateState()==NativeDeviceIdentity.CertificateState.EXPIRED && saved.optJSONObject("certificate")?.has("generation")==true) "CONNECTION_REAUTHORIZE" else "CONNECTION_BEGIN"
        val request=JSONObject().put("authorizationVersion",1).put("operationId",randomId())
            .put("name",name).put("codeChallenge",pkce.challenge)
            .put("requestedScopes",JSONArray((codec.defaultScopes+optional.map { it.wire }).sorted()))
            .put(if(certified) "certificatePem" else "csrPem",if(certified) identity.certificatePem() else identity.csrPem())
        if(action=="CONNECTION_REAUTHORIZE") {
            request.put("installationKeyId",identity.installationKeyId()).put("expectedGeneration",saved.getJSONObject("certificate").getLong("generation"))
                .put("proofNonce","account-reauthorization").put("proof",NativeAccessCodec.encode(ByteArray(256)))
        }
        val revoke=NativeAccessCodec.preExchangeRevoke(pkce.verifier,identity.installationKeyId(),request.getString("operationId"))
        request.put("revokeCommitment",NativeAccessCodec.revokeCommitment(revoke))
        if(action=="CONNECTION_REAUTHORIZE") request.put("proof",identity.signAccess(codec.transcript(action,request,identity.installationKeyId(),pkce.challenge)))
        codec.request(action,request)
        val expected=epoch.get();blocked.set(true)
        update(expected) { it.put("authorization",JSONObject().put("action",action).put("request",request)
            .put("verifier",pkce.verifier).put("revokeCapability",revoke)).put("phase","begin_unconfirmed") }
    }
    private fun restart(name: String, saved: JSONObject, optional: Set<Scope>) {
        val old=saved.getJSONObject("authorization");val response=old.getJSONObject("response")
        check(response.getString("state")=="EXPIRED_NOT_ISSUED")
        val pkce=NativeApiClient.Pkce.generate()
        val body=JSONObject().put("authorizationVersion",1).put("operationId",randomId()).put("name",name)
            .put("csrPem",identity.csrPem()).put("codeChallenge",pkce.challenge)
            .put("requestedScopes",JSONArray((codec.defaultScopes+optional.map { it.wire }).sorted()))
            .put("previousConnectionId",response.getString("connectionId"))
            .put("restartTicket",response.getString("restartTicket")).put("oldCodeVerifier",old.getString("verifier"))
            .put("proofNonce",response.getString("proofNonce")).put("proof",NativeAccessCodec.encode(ByteArray(256)))
        val revoke=NativeAccessCodec.preExchangeRevoke(pkce.verifier,identity.installationKeyId(),body.getString("operationId"))
        body.put("revokeCommitment",NativeAccessCodec.revokeCommitment(revoke))
        body.put("proof",identity.signAccess(codec.transcript("CONNECTION_RESTART",body,identity.installationKeyId(),pkce.challenge,response.getString("connectionId"))))
        update(epoch.get()) { it.put("authorization",JSONObject().put("action","CONNECTION_RESTART")
            .put("request",body).put("verifier",pkce.verifier).put("revokeCapability",revoke)).put("phase","begin_unconfirmed") }
    }
    private fun step(reconcileExpired: Boolean=false) {
        if(closed.get() || !foreground) return
        if(lostIdentity) {emit(Progress(Stage.RECOVERY_REQUIRED,canRegisterAgain=true));return}
        if(!::identity.isInitialized) return
        if(!read().has("renewal")) recoverCertificateIfNeeded()
        // Prior-account remote revoke failure must not prevent a new explicit
        // phone approval; the server atomically replaces/revokes its old slot.
        runCatching { drainRevocations() }
        var saved=read()
        if(saved.has("credentials") && !saved.has("authorization")) { verifyAccount();return }
        if(!saved.has("authorization")) { publishStored();return }
        if(!setupAllowed) { emit(Progress(Stage.SETUP_BLOCKED));return }
        val expected=epoch.get();val auth=saved.getJSONObject("authorization")
        if(auth.optBoolean("expired")) {publishStored();return}
        if(auth.optLong("nextPollAt")>clock()) { publishStored();schedule(auth.optLong("nextPollAt")-clock());return }
        var response=auth.optJSONObject("response")
        val action=auth.getString("action");val original=auth.getJSONObject("request")
        val operation=original.getString("operationId")
        if(response==null) {
            // Exact BEGIN/ACCOUNT_AUTHORIZE is idempotent and never signs at CF.
            // The server ends this key's earlier unclaimed code, so a new
            // operation after cancel/switch/logout shows its code at once.
            response=call(action,original)
        } else if(response.getString("disposition")=="EXCHANGE") {
            val exchange=JSONObject().put("authorizationVersion",1).put("operationId",operation)
                .put("grantId",response.getString("grantId")).put("codeVerifier",auth.getString("verifier"))
            update(expected) { it.put("phase","exchange_unconfirmed") }
            val staged=if(auth.getString("action")=="CONNECTION_REAUTHORIZE") auth.getJSONObject("stagedCertificate") else null
            val result=call("SESSION_EXCHANGE",exchange,stagedCertificate=staged)
            if(staged!=null) {
                val currentEpoch=epoch.get()
                update(currentEpoch,allowNewEpoch=currentEpoch!=expected) {current -> saveCertificate(current,staged,auth)}
            }
            saveCredentials(result.getJSONObject("credentialReceipt"),expected)
            verifyAccount();return
        } else if(response.getString("disposition") in setOf("TERMINAL","USER_RESTART_ALLOWED","REAUTHORIZE")) {
            publishStored();return
        } else if(action=="ACCOUNT_AUTHORIZE") response=call(action,original)
        else {
            val recover=JSONObject().put("authorizationVersion",1).put("operationId",operation)
                .put("csrPem",identity.csrPem()).put("originalBeginHash",NativeDeviceIdentity.sha256(NativeAccessCodec.canonical(original)))
                .put("codeVerifier",auth.getString("verifier")).put("proofNonce","begin-recovery")
            val disposition=response.getString("disposition")
            if(!reconcileExpired && disposition in setOf("WAIT","CONTINUE_CLAIM")) {
                val claim=JSONObject().put("authorizationVersion",1).put("operationId",operation)
                    .put("codeVerifier",auth.getString("verifier")).put("proofNonce",auth.getString("proofNonce"))
                response=call("CONNECTION_CLAIM",sign("CONNECTION_CLAIM",claim,auth),response.getString("connectionId"))
            } else response=call("CONNECTION_RECOVER",sign("CONNECTION_RECOVER",recover,auth))
        }
        val result=response
        if(expected!=epoch.get()) {
            result.optJSONObject("certificateReceipt")?.let { cert ->
                update(epoch.get(),allowNewEpoch=true) { current ->
                    if(current.getLong("epoch")!=epoch.get()) lockState(current,epoch.get())
                    if(auth.getString("action")!="CONNECTION_REAUTHORIZE")saveCertificate(current,cert,auth)
                }
            }
            error("NATIVE_ACCOUNT_LOCKED")
        }
        update(expected) { current ->
            val pending=current.getJSONObject("authorization")
            result.optJSONObject("certificateReceipt")?.let {cert ->
                if(action=="CONNECTION_REAUTHORIZE") {
                    check(cert.getLong("generation")==original.getLong("expectedGeneration")+1 && cert.getString("generationOperationId")==operation)
                    pending.put("stagedCertificate",cert)
                } else saveCertificate(current,cert,auth)
            }
            if(result.has("userCode")) {
                val previous=pending.optJSONObject("public")
                val same=previous?.optString("userCode")==result.getString("userCode") && previous.optLong("expiresAt")==result.getLong("expiresAt") &&
                    previous.has("serverTime") && previous.has("receivedAtMillis")
                pending.put("public",JSONObject().put("userCode",result.getString("userCode"))
                    .put("verificationUri",result.getString("verificationUri")).put("expiresAt",result.getLong("expiresAt"))
                    .put("serverTime",if(same)previous!!.getLong("serverTime") else result.getLong("serverTime"))
                    .put("receivedAtMillis",if(same)previous!!.getLong("receivedAtMillis") else clock()))
            }
            if(result.has("proofNonce")) pending.put("proofNonce",result.getString("proofNonce"))
            pending.put("response",result).put("nextPollAt",clock()+result.optLong("interval",5)*1000)
            current.put("phase","authorizing")
        }
        publishStored()
        if(result.getString("disposition")=="EXCHANGE") worker.execute { safely { step() } }
        else if(result.getString("disposition") in setOf("WAIT","RECONCILE","CONTINUE_CLAIM")) schedule(result.optLong("interval",5)*1000)
    }
    private fun saveCertificate(current: JSONObject, cert: JSONObject, auth: JSONObject) {
        identity.installManagedCertificate(cert.getString("certificatePem"),cert.getString("certificateSha256"))
        current.put("certificate",cert)
        current.put("certificateRecovery",certificateRecoveryProof(cert,auth))
    }
    private fun certificateRecoveryProof(cert: JSONObject,auth: JSONObject): JSONObject {
        val request=JSONObject().put("authorizationVersion",1).put("operationId",randomId())
            .put("installationKeyId",identity.installationKeyId()).put("generationOperationId",cert.getString("generationOperationId"))
            .put("expectedGeneration",cert.getLong("generation")).put("codeVerifier",auth.getString("verifier"))
            .put("proofNonce",auth.getString("proofNonce"))
        return sign("CERTIFICATE_RECOVER",request,auth)
    }
    private fun recoverCertificateIfNeeded() {
        val pending=read().optJSONObject("pendingPublicCertificateRecovery")
        if(pending!=null) {
            val expected=epoch.get()
            try {
                val cert=call("CERTIFICATE_RECOVER",pending).getJSONObject("certificateReceipt")
                check(cert.getLong("generation")==pending.getLong("expectedGeneration") && cert.getString("generationOperationId")==pending.getString("generationOperationId"))
                update(expected) {current ->
                    identity.installManagedCertificate(cert.getString("certificatePem"),cert.getString("certificateSha256"))
                    current.put("certificate",cert).put("certificateRecovery",pending);current.remove("pendingPublicCertificateRecovery")
                }
            } catch(failure: NativeApiClient.Failure) {
                if(failure.code!="OPERATION_NOT_FOUND")throw failure
                update(expected) {it.remove("pendingPublicCertificateRecovery")}
            }
        }
        val saved=read();val receipt=saved.optJSONObject("certificate") ?: return
        val missing=identity.certificateState()==NativeDeviceIdentity.CertificateState.MISSING
        val different=!missing && runCatching {identity.certificateSha256()!=receipt.getString("certificateSha256")}.getOrDefault(true)
        if(!missing && !different) return
        val request=saved.optJSONObject("certificateRecovery") ?: error("NATIVE_CERTIFICATE_RECOVERY_REQUIRED")
        val expected=epoch.get();val result=call("CERTIFICATE_RECOVER",request)
        val cert=result.getJSONObject("certificateReceipt")
        check(cert.getLong("generation")==request.getLong("expectedGeneration") && cert.getString("generationOperationId")==request.getString("generationOperationId"))
        update(expected) {current ->
            identity.installManagedCertificate(cert.getString("certificatePem"),cert.getString("certificateSha256"));current.put("certificate",cert)
        }
    }
    private fun sign(action: String, body: JSONObject, auth: JSONObject): JSONObject {
        body.put("proof",NativeAccessCodec.encode(ByteArray(256)))
        body.put("proof",identity.signAccess(codec.transcript(action,body,identity.installationKeyId(),
            auth.getJSONObject("request").getString("codeChallenge"),auth.optJSONObject("response")?.optString("connectionId"))))
        return body
    }
    private fun call(action: String, body: JSONObject, connectionId: String? = null, deviceId: String? = null, stagedCertificate: JSONObject? = null): JSONObject {
        return (if(codec.operation(action).getString("host")=="enroll") enrollmentFactory() else nativeFactory(identity))
            .access(action,body,codec,connectionId,deviceId,identity.installationKeyId(),stagedCertificate)
    }

    /** Same-key technical maintenance: no new account grant or phone approval.
     * Every operation/PKCE is encrypted before IO; only rebind can use the staged
     * leaf, and neither its reply nor a late callback may reopen a locked epoch. */
    private fun renewCertificate(expected: Long,allowStaleRestart: Boolean = true): Boolean {
        try {return renewCertificateAttempt(expected)}
        catch(failure: NativeApiClient.Failure) {
            if(failure.code=="STALE_EPOCH" && allowStaleRestart) {
                update(expected) {it.remove("renewal")}
                return renewCertificate(expected,false)
            }
            throw failure
        }
    }
    private fun renewCertificateAttempt(expected: Long): Boolean {
        var saved=read();val previous=saved.getJSONObject("credentials")
        check(expected==epoch.get() && !closed.get())
        blocked.set(true);closeSockets("certificate_renewal")
        emit(Progress(Stage.CONNECTING))
        var renewal=saved.optJSONObject("renewal")
        if(renewal==null) {
            val pkce=NativeApiClient.Pkce.generate()
            val body=JSONObject().put("authorizationVersion",1).put("operationId",randomId())
                .put("csrPem",identity.csrPem()).put("installationKeyId",identity.installationKeyId())
                .put("grantId",previous.getString("grantId")).put("deviceId",previous.getString("deviceId"))
                .put("recoveryCapability",previous.getString("recoveryCapability"))
                .put("expectedGeneration",previous.getLong("generation")).put("codeChallenge",pkce.challenge)
                .put("proofNonce","certificate-renewal").put("proof",NativeAccessCodec.encode(ByteArray(256)))
            body.put("proof",identity.signAccess(codec.transcript("CERTIFICATE_RENEW_BEGIN",body,identity.installationKeyId(),pkce.challenge)))
            val value=JSONObject().put("request",body).put("verifier",pkce.verifier)
            update(expected) {it.put("renewal",value).put("phase","renewal_begin_unconfirmed")}
            renewal=value
        }
        var response=renewal.optJSONObject("response")
        if(response==null) {
            response=call("CERTIFICATE_RENEW_BEGIN",renewal.getJSONObject("request"))
            val value=response
            update(expected) {it.getJSONObject("renewal").put("response",value).put("proofNonce",value.getString("proofNonce"))}
        }
        var staged=renewal.optJSONObject("stagedCertificate")
        if(staged==null) {
            // Re-read after begin, because a crash may have occurred after its exact
            // successful receipt was persisted and before the first claim.
            renewal=read().getJSONObject("renewal")
            response=renewal.getJSONObject("response")
            val connection=response.getString("connectionId")
            val claim=JSONObject().put("authorizationVersion",1)
                .put("operationId",renewal.getJSONObject("request").getString("operationId"))
                .put("codeVerifier",renewal.getString("verifier")).put("proofNonce",renewal.getString("proofNonce"))
                .put("proof",NativeAccessCodec.encode(ByteArray(256)))
            claim.put("proof",identity.signAccess(codec.transcript("CERTIFICATE_RENEW_CLAIM",claim,identity.installationKeyId(),renewal.getJSONObject("request").getString("codeChallenge"),connection)))
            val result=call("CERTIFICATE_RENEW_CLAIM",claim,connection)
            if(result.getString("disposition")=="RECONCILE") {
                update(expected) {it.getJSONObject("renewal").put("claimResponse",result)}
                schedule(result.optLong("interval",5)*1000);return false
            }
            check(result.getString("disposition")=="CERTIFICATE_RECEIPT")
            staged=result.getJSONObject("certificateReceipt")
            check(staged.getLong("generation")==previous.getLong("generation")+1 &&
                staged.getString("generationOperationId")==renewal.getJSONObject("request").getString("operationId") &&
                staged.getString("certificateSha256")!=previous.getString("certificateSha256"))
            // Validate key/CN/EKU/validity now, without replacing current identity.
            identity.stagedKeyManager(staged.getString("certificatePem"),staged.getString("certificateSha256"))
            val value=staged
            update(expected) {it.getJSONObject("renewal").put("stagedCertificate",value).put("claimResponse",result)}
        }
        check(expected==epoch.get())
        renewal=read().getJSONObject("renewal")
        var rebind=renewal.optJSONObject("rebindRequest")
        if(rebind==null) {
            rebind=JSONObject().put("authorizationVersion",1).put("operationId",randomId())
                .put("connectionId",response!!.getString("connectionId"))
                .put("grantId",previous.getString("grantId")).put("deviceId",previous.getString("deviceId"))
                .put("recoveryCapability",previous.getString("recoveryCapability"))
            val value=rebind
            update(expected) {it.getJSONObject("renewal").put("rebindRequest",value);it.put("phase","renewal_rebind_unconfirmed")}
        }
        val result=call("CREDENTIAL_REBIND",rebind,stagedCertificate=staged)
        val credential=result.getJSONObject("credentialReceipt")
        for(field in listOf("accountId","grantId","deviceId","installationKeyId","recoveryCapability","revokeCapability"))
            check(credential.getString(field)==previous.getString(field))
        for(field in listOf("slotRevision","grantExpiresAt")) check(credential.getLong(field)==previous.getLong(field))
        val oldScopes=previous.getJSONArray("scopes");val scopes=credential.getJSONArray("scopes")
        check((0 until scopes.length()).all {i -> (0 until oldScopes.length()).any {scopes.getString(i)==oldScopes.getString(it)}} &&
            credential.getLong("consentVersion")>=previous.getLong("consentVersion") &&
            credential.getLong("generation")==staged.getLong("generation") &&
            credential.getString("certificateSha256")==staged.getString("certificateSha256") &&
            credential.getLong("credentialEpoch")>previous.getLong("credentialEpoch"))
        val auth=JSONObject().put("request",renewal.getJSONObject("request")).put("verifier",renewal.getString("verifier"))
            .put("proofNonce",renewal.getString("proofNonce")).put("response",response)
        if(expected!=epoch.get()) {
            // Main may have committed just before logout. Keep only its public
            // certificate and revoke-only authority, never access/refresh tokens.
            update(epoch.get(),allowNewEpoch=true) {current ->
                saveCertificate(current,staged,auth)
                val outbox=current.getJSONArray("outbox")
                for(i in outbox.length()-1 downTo 0) if(outbox.getJSONObject(i).getJSONObject("request").getString("grantId")==credential.getString("grantId")) outbox.remove(i)
                outbox.put(JSONObject().put("deviceId",credential.getString("deviceId"))
                    .put("installationKeyId",credential.getString("installationKeyId")).put("generation",credential.getLong("generation"))
                    .put("request",JSONObject().put("authorizationVersion",1).put("operationId",randomId())
                        .put("grantId",credential.getString("grantId")).put("revokeCapability",credential.getString("revokeCapability"))))
                current.remove("renewal");current.put("phase","revoke_pending")
            }
            error("NATIVE_ACCOUNT_LOCKED")
        }
        update(expected) {current -> saveCertificate(current,staged,auth)}
        saveCredentials(credential,expected)
        update(expected) {it.remove("renewal")}
        return true
    }
    private fun saveCredentials(receipt: JSONObject, expected: Long) {
        if(expected!=epoch.get()) {
            // Logout already owns the exact precommitted grant-only outbox.
            // A late unrelated receipt must never add/replace remote authority.
            validateLateReceipt(receipt,read().getJSONArray("outbox"),identity.installationKeyId(),identity.certificateSha256())
            error("NATIVE_ACCOUNT_LOCKED")
        }
        update(expected) { saved ->
        val cert=saved.optJSONObject("certificate")
        check(receipt.getString("certificateSha256")==identity.certificateSha256())
        if(cert!=null) check(receipt.getString("certificateSha256")==cert.getString("certificateSha256") &&
            receipt.getLong("generation")==cert.getLong("generation"))
        else saved.put("certificate",JSONObject().put("certificateSha256",receipt.getString("certificateSha256"))
            .put("generation",receipt.getLong("generation")).put("installationKeyId",receipt.getString("installationKeyId")))
        val auth=saved.optJSONObject("authorization")
        val previous=saved.optJSONObject("credentials")
        if(auth!=null) {
            check(receipt.getString("grantId")==auth.getJSONObject("response").getString("grantId"))
            check(receipt.getString("recoveryCapability")==NativeAccessCodec.capability(auth.getString("verifier"),receipt.getString("grantId"),"recovery"))
            check(receipt.getString("revokeCapability")==auth.getString("revokeCapability"))
            val requested=auth.getJSONObject("request").getJSONArray("requestedScopes")
            check((0 until receipt.getJSONArray("scopes").length()).all { i -> (0 until requested.length()).any { requested.getString(it)==receipt.getJSONArray("scopes").getString(i) } })
        } else {
            check(previous!=null)
            validateReplacement(receipt,previous)
            val oldScopes=previous.getJSONArray("scopes");val scopes=receipt.getJSONArray("scopes")
            check((0 until scopes.length()).all { i -> (0 until oldScopes.length()).any { scopes.getString(i)==oldScopes.getString(it) } })
            if(receipt.getLong("credentialEpoch")==previous.getLong("credentialEpoch")) check(NativeAccessCodec.canonical(receipt).contentEquals(NativeAccessCodec.canonical(previous)))
        }
        if(previous!=null && receipt.getLong("credentialEpoch")!=previous.getLong("credentialEpoch")) closeSockets("credential_epoch")
        if(auth!=null)deniedScopes=emptySet()
        saved.put("credentials",receipt).put("phase","account_check_required");saved.remove("authorization");saved.remove("pendingCredential")
        }
    }
    private fun verifyAccount(allowRecovery: Boolean = true,force: Boolean = true) {
        val previous=dataBoundary?.takeIf {it.revision==epoch.get() && progress.stage in setOf(Stage.CONNECTED,Stage.CHECKING)}
        try {
            if(!force && sessionReusable())return
            verifyAccountAttempt(allowRecovery)
            if(currentSnapshot(dataBoundary)) {
                sessionRenewal?.cancel(false)
                val at=read().getJSONObject("credentials").getLong("expiresAt")*1000-30000
                val owner=epoch.get()
                sessionRenewal=worker.schedule({if(owner==epoch.get() && !closed.get())safely {verifyAccount()}},(at-clock()).coerceAtLeast(1000),TimeUnit.MILLISECONDS)
            }
        }catch(failure: Throwable) {
            dataBoundary=null;executions.toList().forEach {it.invalidate()}
            if(!lockTerminalFailure(failure) && (previous!=null || progress.stage==Stage.CHECKING)) {
                closeSockets("account_check_failed");emit(if(progress.stage in setOf(Stage.CONNECTED,Stage.CHECKING))Progress(Stage.UNAVAILABLE) else progress)
            }
            throw failure
        }
    }
    /** The verified session is current and its certificate and access token are still usable without a refresh. */
    private fun sessionReusable()=currentSnapshot(dataBoundary) && identity.certificateState(java.util.Date(clock())) in setOf(NativeDeviceIdentity.CertificateState.CONFIGURED,NativeDeviceIdentity.CertificateState.RENEWAL_DUE) &&
        read().optJSONObject("credentials")?.optLong("expiresAt",0)?.let {it*1000>clock()+30000}==true
    private fun verifyAccountAttempt(allowRecovery: Boolean) {
        val expected=epoch.get();var saved=read()
        check(saved.has("credentials") && !saved.has("authorization") && saved.optString("phase") !in setOf("locked","revoke_pending"))
        val previous=if(currentSnapshot(dataBoundary)) {
            progress.takeIf {it.stage==Stage.CONNECTED} ?: progress.previousConnection
        } else null
        blocked.set(true);emit(Progress(Stage.CHECKING,previousConnection=previous))
        val certificateState=identity.certificateState(java.util.Date(clock()))
        if(saved.has("renewal") || certificateState in setOf(NativeDeviceIdentity.CertificateState.RENEWAL_DUE,NativeDeviceIdentity.CertificateState.EXPIRED)) {
            if(!renewCertificate(expected)) return
            saved=read()
        }
        if(saved.has("pendingCredential") || saved.getJSONObject("credentials").getLong("expiresAt")*1000<=clock()+30000) {
            credentialOperation(if(saved.has("pendingCredential")) saved.getJSONObject("pendingCredential").getString("action") else "SESSION_REFRESH",expected)
            saved=read()
        }
        val cred=saved.getJSONObject("credentials");check(identity.certificateSha256()==cred.getString("certificateSha256"))
        val client=nativeFactory(identity)
        val permission: JSONObject
        try {
            val account=client.account(cred.getString("accessToken"))
            check(account.get("deviceId") is String && account.getString("deviceId")==cred.getString("deviceId"))
            val user=account.getJSONObject("user")
            check(user.get("id") is String && user.getString("id")==cred.getString("accountId"))
            permission=client.readDocument("/v1/device/permissions",cred.getString("accessToken")).asObject()
            check(permission.get("deviceId") is String && permission.getString("deviceId")==cred.getString("deviceId") && permission.get("keepSignedIn") is Boolean)
            for(field in listOf("consentVersion","grantExpiresAt")) check(permission.get(field) is Int || permission.get(field) is Long)
            val currentScopes=permission.getJSONArray("scopes")
            check((0 until currentScopes.length()).all { currentScopes.get(it) is String })
            if(currentScopes.toString()!=cred.getJSONArray("scopes").toString() || permission.getLong("consentVersion")!=cred.getLong("consentVersion") ||
                permission.getLong("grantExpiresAt")!=cred.getLong("grantExpiresAt")) {
                check(allowRecovery);credentialOperation("SESSION_RECOVER",expected);verifyAccount(false);return
            }
        } catch(failure: NativeApiClient.Failure) {
            if(allowRecovery && failure.status in setOf(401,403)) {
                credentialOperation("SESSION_RECOVER",expected);verifyAccount(false);return
            };throw failure
        }
        if(functionalGate.cached(cred.getString("deviceId"),cred.getString("grantId"),clock())==null) {
            val functional=codec.functional.permissions(client.functionalPermissions(cred.getString("accessToken"),codec.functional),
                cred.getString("deviceId"),cred.getString("grantId"),cred.getLong("grantExpiresAt")*1000,clock())
            synchronized(functionalGate) {
                check(expected==epoch.get())
                if(functionalGate.replace(functional)) {
                    functionalVersion.incrementAndGet()
                    functionalStampChanged("stamp_changed","verify_account")
                }
            }
        }
        update(expected) { it.put("phase","connected").put("keepSignedIn",permission.getBoolean("keepSignedIn")) }
        check(expected==epoch.get())
        val scopes=cred.getJSONArray("scopes")
        dataBoundary=run {
            val key=java.security.MessageDigest.getInstance("SHA-256").digest(
                ("wegoh.account-records.v1\u0000"+cred.getString("grantId")+"\u0000"+cred.getString("accountId")).toByteArray(Charsets.UTF_8))
                .joinToString("") {"%02x".format(it.toInt() and 255)}
            val approved=Scope.entries.filter {scope -> (0 until scopes.length()).any {scopes.getString(it)==scope.wire}}.toSet()
            DataBoundary(expected,key,java.util.Collections.unmodifiableSet(approved),cred.getLong("grantExpiresAt")*1000)
        }
        blocked.set(false);publishStored()
    }
    private fun credentialOperation(action: String, expected: Long) {
        val saved=read();val cred=saved.getJSONObject("credentials")
        var pending=saved.optJSONObject("pendingCredential")
        if(pending==null) {
            val field=if(action=="SESSION_REFRESH") "refreshToken" else "recoveryCapability"
            pending=JSONObject().put("action",action).put("request",JSONObject().put("authorizationVersion",1).put("operationId",randomId())
                .put("grantId",cred.getString("grantId")).put("deviceId",cred.getString("deviceId")).put(field,cred.getString(field)))
            val value=pending;update(expected) { it.put("pendingCredential",value).put("phase","credential_unconfirmed") }
        }
        val receipt=call(pending.getString("action"),pending.getJSONObject("request")).getJSONObject("credentialReceipt")
        validateReplacement(receipt,cred) // Even a late response remains bound to the in-flight old account.
        saveCredentials(receipt,expected)
    }
    private fun lockState(saved: JSONObject, next: Long) {
        saved.optJSONObject("credentials")?.let { credential ->
            saved.getJSONArray("outbox").put(JSONObject().put("deviceId",credential.getString("deviceId"))
                .put("installationKeyId",credential.getString("installationKeyId")).put("generation",credential.getLong("generation"))
                .put("request",JSONObject().put("authorizationVersion",1).put("operationId",randomId())
                    .put("grantId",credential.getString("grantId")).put("revokeCapability",credential.getString("revokeCapability"))))
        }
        saved.optJSONObject("renewal")?.let {renewal ->
            renewal.optJSONObject("stagedCertificate")?.let {staged ->
                val auth=JSONObject().put("request",renewal.getJSONObject("request")).put("verifier",renewal.getString("verifier"))
                    .put("proofNonce",renewal.getString("proofNonce")).put("response",renewal.getJSONObject("response"))
                val list=saved.getJSONArray("outbox")
                for(i in 0 until list.length()) {
                    val pending=list.getJSONObject(i)
                    if(pending.getJSONObject("request").getString("grantId")==saved.optJSONObject("credentials")?.optString("grantId"))
                        pending.put("stagedCertificate",staged).put("stagedCertificateRecovery",certificateRecoveryProof(staged,auth))
                }
            }
        }
        saved.optJSONObject("authorization")?.let {auth ->
            val grant=auth.optJSONObject("response")?.optString("grantId")
            if(!grant.isNullOrEmpty() && auth.has("revokeCapability")) {
                val pending=JSONObject().put("request",JSONObject().put("authorizationVersion",1).put("operationId",randomId())
                    .put("grantId",grant).put("revokeCapability",auth.getString("revokeCapability")))
                auth.optJSONObject("stagedCertificate")?.let {pending.put("stagedCertificate",it)}
                saved.getJSONArray("outbox").put(pending)
            } else {
                auth.optJSONObject("public")?.let {saved.put("cancelledAuthorization",JSONObject().put("public",it))}
                storeCancelOnLock(saved,auth,next,clock()) {request -> sign("CONNECTION_CANCEL",request,auth)}
            }
        }
        for(key in listOf("credentials","authorization","pendingCredential","keepSignedIn","renewal")) saved.remove(key)
        saved.put("epoch",next).put("phase",if(saved.getJSONArray("outbox").length()>0) "revoke_pending" else "locked")
    }
    /** Best effort: the code is already gone locally. A failed send is retried on the next
     * drain until the code's own TTL would have ended it on the server anyway. */
    private fun drainCancellation() {
        val pending=read().optJSONObject("pendingCancel") ?: return
        if(!cancelSettled(pending,clock()) {action,body -> call(action,body)}) return
        update(epoch.get()) {current -> clearCancel(current,pending)}
    }
    private fun drainRevocations() {
        if(!::identity.isInitialized || closed.get()) return
        runCatching {drainCancellation()}
        while(true) {
            val saved=read();val outbox=saved.getJSONArray("outbox");if(outbox.length()==0) return
            val pending=outbox.getJSONObject(0)
            var usedStaged=false
            val staged=pending.optJSONObject("stagedCertificate")
            val value=if(staged!=null) {
                try {call("GRANT_REVOKE",pending.getJSONObject("request"),stagedCertificate=staged).also {usedStaged=true}}
                catch(failure: NativeApiClient.Failure) {
                    if(failure.code!="CERTIFICATE_BINDING_MISMATCH")throw failure
                    call("GRANT_REVOKE",pending.getJSONObject("request"))
                }
            } else call("GRANT_REVOKE",pending.getJSONObject("request"))
            check(value.getString("grantId")==pending.getJSONObject("request").getString("grantId"))
            update(epoch.get()) { current ->
                if(usedStaged && pending.has("stagedCertificateRecovery")) {
                    // Revoke-only staging does not commit a certificate generation.
                    // A later public purpose proof, never this ack, establishes it.
                    current.put("pendingPublicCertificateRecovery",pending.getJSONObject("stagedCertificateRecovery"))
                }
                val list=current.getJSONArray("outbox")
                if(list.length()>0 && list.getJSONObject(0).getJSONObject("request").getString("operationId")==pending.getJSONObject("request").getString("operationId")) list.remove(0)
                if(list.length()==0 && current.optString("phase")=="revoke_pending") current.put("phase","locked")
            }
            publishStored()
        }
    }
    private fun closeSockets(cause: String) {
        invalidateFunctionalPermissions("sockets_$cause")
        closeUiSockets(cause)
        executions.toList().forEach {it.invalidate()}
    }
    private fun closeUiSockets(cause: String) {
        uiEvents.reset()
        climateEvents.reset()
        invalidateFunctionalPermissions("ui_sockets_$cause")
        val closing=synchronized(socketGuard) {
            socketVersion.incrementAndGet();sockets.toList().also {sockets.clear()}
        }
        closing.forEach {runCatching {it.close()}}
    }
    private fun read(): JSONObject = store.locked { JSONObject(store.read().getJSONObject("access").toString()) }
    private fun update(expected: Long, allowNewEpoch: Boolean = false, change: (JSONObject)->Unit) = store.locked {
        check(expected==epoch.get() && (!closed.get() || allowNewEpoch))
        val root=store.read();val saved=root.getJSONObject("access")
        check(allowNewEpoch || saved.getLong("epoch")==expected)
        change(saved);check(expected==epoch.get());store.write(root)
    }
    private fun publishStored() {
        val saved=read();val auth=saved.optJSONObject("authorization");val response=auth?.optJSONObject("response")
        val stage=when {
            auth?.optBoolean("expired")==true -> Stage.EXPIRED
            saved.optString("phase")=="connected" && !blocked.get() -> Stage.CONNECTED
            saved.getJSONArray("outbox").length()>0 && !saved.has("authorization") && !saved.has("credentials") -> Stage.REMOTE_REVOCATION_PENDING
            response?.optString("disposition")=="USER_RESTART_ALLOWED" -> Stage.EXPIRED
            response?.optString("disposition")=="REAUTHORIZE" -> Stage.RECOVERY_REQUIRED
            response?.optString("disposition")=="TERMINAL" -> Stage.DENIED
            auth?.has("public")==true && response?.optString("state")=="PENDING" -> Stage.APPROVAL_REQUIRED
            auth!=null -> Stage.CONNECTING
            saved.has("credentials") -> Stage.CHECKING
            saved.optString("phase")=="locked" -> Stage.LOCKED
            else -> Stage.READY
        }
        val public=auth?.optJSONObject("public")
        emit(Progress(stage,public?.optString("userCode"),public?.optString("verificationUri"),public?.let {publicExpiry(it)},
            auth?.optLong("nextPollAt")?.let { ((it-clock()+999)/1000).coerceIn(0,86400).toInt() },
            approvedOptionalScopes=if(stage==Stage.CONNECTED) approvedScopes(saved) else emptySet(),
            deniedOptionalScopes=if(stage==Stage.CONNECTED) deniedScopes else emptySet()))
    }
    private fun approvedScopes(saved: JSONObject): Set<Scope> {
        val values=saved.optJSONObject("credentials")?.optJSONArray("scopes") ?: return emptySet()
        return Scope.entries.filter {scope -> (0 until values.length()).any {values.optString(it)==scope.wire}}.toSet()
    }
    private fun schedule(delay: Long) {
        poll?.cancel(false);poll=null
        if(!closed.get() && foreground && setupAllowed) poll=worker.schedule({poll=null;safely {step()}},delay.coerceIn(1000,60000),TimeUnit.MILLISECONDS)
    }
    private fun lockTerminalFailure(failure: Throwable): Boolean {
        if(failure !is NativeApiClient.Failure || failure.code !in setOf("CONSENT_REVOKED","GRANT_EXPIRED"))return false
        blocked.set(true);closeSockets("terminal_failure");poll?.cancel(false);poll=null
        val persisted=runCatching {
            if(read().has("credentials")) {val next=epoch.incrementAndGet();update(next,allowNewEpoch=true) {lockState(it,next)}}
        }.isSuccess
        emit(Progress(if(!persisted)Stage.RECOVERY_REQUIRED else if(failure.code=="GRANT_EXPIRED")Stage.EXPIRED else Stage.DENIED))
        return true
    }
    private fun diagnostic(event: NativeConnectionDiagnostics.Event,operation: NativeConnectionDiagnostics.Operation?,failure: Throwable?=null) {
        if(operation!=null)runCatching {
            WegoLog.i("WegoConnection",NativeConnectionDiagnostics.message(event,operation,progress.stage,failure))
        }
    }
    private fun safely(allowClosed: Boolean = false,operation: NativeConnectionDiagnostics.Operation?=null,block: ()->Unit) {
        if(closed.get() && !allowClosed) return
        diagnostic(NativeConnectionDiagnostics.Event.STARTED,operation)
        try { block() } catch(failure: Throwable) {
            diagnostic(NativeConnectionDiagnostics.Event.FAILED,operation,failure)
            if(closed.get()) return
            blocked.set(true)
            if(failure is NativeApiClient.Failure && failure.code=="AUTHORIZATION_EXPIRED" && ::store.isInitialized) {
                val saved=read()
                if(saved.optJSONObject("authorization")?.optString("action")=="ACCOUNT_AUTHORIZE") {
                    update(epoch.get()) {it.getJSONObject("authorization").put("expired",true)}
                    publishStored();return
                }
            }
            if(lockTerminalFailure(failure)) return
            if(failure.message in setOf("NATIVE_PRIVATE_KEY_MISSING","NATIVE_STATE_KEY_MISSING","NATIVE_STATE_FILE_MISSING","NATIVE_STATE_INVALID") ||
                generateSequence(failure as Throwable?) {it.cause}.any {it is javax.crypto.AEADBadTagException}) lostIdentity=true
            if(::identity.isInitialized && runCatching {read().optString("phase") in setOf("locked","revoke_pending")}.getOrDefault(false)) {publishStored();return}
            emit(Progress(when {
                failure is NativeApiClient.Failure && failure.code in setOf("GRANT_EXPIRED","AUTHORIZATION_EXPIRED","RECEIPT_EXPIRED") -> Stage.EXPIRED
                failure is NativeApiClient.Failure && failure.code in setOf("CONSENT_REVOKED","INSTALLATION_REVOKED") -> Stage.DENIED
                else -> Stage.RECOVERY_REQUIRED
            },canRegisterAgain=lostIdentity))
        } finally {diagnostic(NativeConnectionDiagnostics.Event.FINISHED,operation)}
    }
    private fun visible(value: Progress): Progress = if(!setupAllowed || !foreground) {
        if(value.stage in setOf(Stage.APPROVAL_REQUIRED,Stage.CONNECTING,Stage.READY,Stage.SETUP_BLOCKED)) Progress(Stage.SETUP_BLOCKED)
        else Progress(value.stage)
    } else value
    private fun emit(value: Progress) {
        progress=value;val current=epoch.get()
        boundaryObservers.forEach {it()}
        main.removeCallbacks(boundaryExpiry)
        currentDataBoundary()?.let {main.postDelayed(boundaryExpiry,(it.expiresAtMillis-clock()).coerceAtLeast(1))}
        executions.toList().filterNot {it.isCurrent()}.forEach {it.invalidate()}
        main.post { if(!closed.get() && current==epoch.get()) observers.forEach { it(visible(progress)) } }
    }
    override fun close() {
        if(closed.getAndSet(true)) return
        ClientDiagnostics.detach(diagnosticsSender)
        mutationGate.setAllowed(false)
        boundaryObservers.forEach {it()};boundaryObservers.clear();main.removeCallbacks(boundaryExpiry)
        blocked.set(true);closeSockets("connection_closed")
        socialClients.toList().forEach {it.close()}
        observers.clear();poll?.cancel(false);poll=null;sessionRenewal?.cancel(false);sessionRenewal=null;lanes.shutdown();privacyWorker.shutdown();eventWorker.shutdown()
        synchronized(OWNERS) { if(OWNERS[ownerKey]?.get()===this) OWNERS.remove(ownerKey) }
    }
    companion object {
        fun validAccountName(value: String): Boolean = value==value.trim() && value.codePointCount(0,value.length) in 1..30 &&
            value.codePoints().allMatch {Character.getType(it) !in setOf(Character.CONTROL.toInt(),Character.FORMAT.toInt(),Character.SURROGATE.toInt(),Character.PRIVATE_USE.toInt(),Character.UNASSIGNED.toInt())}
        val DEFAULT_SCOPES: Set<Scope> get()=setOf(Scope.COURSES,Scope.PLAYLISTS)
        /** Code deadline on the device clock: server-relative when the receipt kept serverTime. */
        internal fun publicExpiry(value: JSONObject): Long {
            val expires=value.getLong("expiresAt")
            return if(value.has("serverTime") && value.has("receivedAtMillis"))
                value.getLong("receivedAtMillis")+(expires-value.getLong("serverTime")).coerceAtLeast(0)*1000
            else expires*1000
        }
        internal fun validateReplacement(receipt: JSONObject,previous: JSONObject) {
            for(field in listOf("accountId","grantId","deviceId","installationKeyId","recoveryCapability","revokeCapability"))
                check(receipt.getString(field)==previous.getString(field))
            for(field in listOf("slotRevision","grantExpiresAt"))check(receipt.getLong(field)==previous.getLong(field))
            check(receipt.getLong("credentialEpoch")>=previous.getLong("credentialEpoch") && receipt.getLong("consentVersion")>=previous.getLong("consentVersion"))
            val scopes=receipt.getJSONArray("scopes");val old=previous.getJSONArray("scopes")
            check((0 until scopes.length()).all {i->(0 until old.length()).any {scopes.getString(i)==old.getString(it)}})
        }
        /** 차량 "취소"/logout of a code that has no grant here yet ends it on the server too. */
        internal fun cancelRequest(auth: JSONObject): JSONObject? {
            if(auth.optBoolean("expired") || auth.optString("action") !in setOf("CONNECTION_BEGIN","CONNECTION_RESTART","CONNECTION_REAUTHORIZE","ACCOUNT_AUTHORIZE")) return null
            val response=auth.optJSONObject("response")
            if(response!=null && (response.has("grantId") || response.optString("state") !in setOf("PENDING","APPROVED"))) return null
            return JSONObject().put("authorizationVersion",1).put("operationId",auth.getJSONObject("request").getString("operationId"))
                .put("codeVerifier",auth.getString("verifier")).put("proofNonce","connection-cancel")
        }
        /** A server code lives at most 5 minutes and was created before the lock, so past this
         * window from the lock there is nothing left for a retry to end. */
        internal const val CANCEL_RETRY_WINDOW_MS=300_000L
        /** lockState drops a grant-less code with its verifier, so its cancel is signed now or never.
         * A signing failure must not block the local lock. */
        internal fun storeCancelOnLock(saved: JSONObject,auth: JSONObject,epoch: Long,nowMs: Long,sign: (JSONObject)->JSONObject) {
            val request=cancelRequest(auth) ?: return
            val signed=runCatching {sign(request)}.getOrNull() ?: return
            saved.put("pendingCancel",JSONObject().put("request",signed).put("epoch",epoch).put("deadline",nowMs+CANCEL_RETRY_WINDOW_MS))
        }
        /** True when [pending] is done with: the server settled it, or its retry window passed. */
        internal fun cancelSettled(pending: JSONObject,nowMs: Long,call: (String,JSONObject)->JSONObject): Boolean =
            nowMs>=pending.getLong("deadline") || sendCancel(pending.getJSONObject("request"),call)
        /** Clears only the cancel that was sent; a later lock's own cancel stays. */
        internal fun clearCancel(current: JSONObject,sent: JSONObject) {
            val stored=current.optJSONObject("pendingCancel") ?: return
            if(stored.optLong("epoch")==sent.getLong("epoch") &&
                stored.getJSONObject("request").getString("operationId")==sent.getJSONObject("request").getString("operationId"))
                current.remove("pendingCancel")
        }
        /** True once the server settled it (ended, or reports it cannot be cancelled); false keeps it for a retry. */
        internal fun sendCancel(request: JSONObject,call: (String,JSONObject)->JSONObject): Boolean = try {
            call("CONNECTION_CANCEL",request);true
        } catch(failure: NativeApiClient.Failure) {
            failure.status in 400..499 && failure.status !in setOf(408,429)
        } catch(failure: java.io.IOException) {false}
        internal fun validateLateReceipt(receipt: JSONObject,outbox: JSONArray,key: String,certificate: String) {
            check(receipt.getString("installationKeyId")==key && receipt.getString("certificateSha256")==certificate)
            check((0 until outbox.length()).any {i->val request=outbox.getJSONObject(i).getJSONObject("request")
                request.getString("grantId")==receipt.getString("grantId") && request.getString("revokeCapability")==receipt.getString("revokeCapability")})
        }
        private val OWNERS=HashMap<String,java.lang.ref.WeakReference<VehicleConnection>>()
        private fun randomId() = java.util.UUID.randomUUID().toString().replace("-","")
        internal fun synthetic(context: Context, profile: String, port: Int, ca: java.security.cert.X509Certificate, eventsPort: Int? = null) = VehicleConnection(context,profile,
            {NativeApiClient.syntheticLoopback(port,ca,it,eventsPort=eventsPort)}, {NativeApiClient.syntheticLoopback(port,ca,null,true)},System::currentTimeMillis)
        internal fun existingProfile(context: Context, profile: String) = VehicleConnection(context,profile,
            {NativeApiClient.native(it)},{NativeApiClient.enrollment()},System::currentTimeMillis)
    }
}

/** The default feed's queued callbacks have the same lifetime as its owned socket. */
internal class OwnedVehicleEvents(
    private val main: Handler,
    private val current: ()->Boolean,
    private val live: ()->Boolean,
    private val terminalCurrent: ()->Boolean,
    private val closeAll: ()->Unit,
    private val invalidateDevices: (String)->Unit,
    private val listener: VehicleEventsListener
) : VehicleEventsListener, Closeable {
    private val active=AtomicBoolean(true)
    private val queued=java.util.concurrent.atomic.AtomicInteger(0)
    private val overflow=AtomicBoolean(false)
    private fun post(data: Boolean=true,action: ()->Unit) {
        if(!active.get())return
        if(queued.incrementAndGet()>8) {
            queued.decrementAndGet()
            if(active.get() && overflow.compareAndSet(false,true)) {
                closeAll()
                // Overflow already occurred: auto-close must not erase its captured terminal notice.
                main.post {if(terminalCurrent())listener.onUnavailable()}
            }
            return
        }
        main.post {try {
            if(active.get() && (if(data)current() else live()) && !overflow.get())action()
        } finally {queued.decrementAndGet()}}
    }
    override fun onOpen()=post {listener.onOpen()}
    override fun onEvent(event: VehicleEvent)=post {
        if(event.type=="invalidate" && "devices" in event.resources)invalidateDevices("event_devices")
        listener.onEvent(event)
    }
    override fun onClosed()=post(false) {listener.onClosed()}
    override fun onClosed(code: Int)=post(false) {
        if(code==4003)invalidateDevices("event_4003")
        listener.onClosed(code)
    }
    override fun onUnavailable()=post(false) {listener.onUnavailable()}
    override fun close() {active.set(false)}
}
