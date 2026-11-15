package io.wegoh.app.nativeauth

import org.json.JSONArray
import org.json.JSONObject
import java.time.LocalTime
import java.util.concurrent.Executors
import java.util.concurrent.ScheduledExecutorService
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.time.format.DateTimeFormatter

/**
 * Recent WegoH diagnostic lines kept in this process for the opt-in error report.
 * Lines are masked when recorded, so the buffer never holds identifiers, tokens, places or
 * titles. logcat is not read; only lines written through [WegoLog] enter the buffer.
 */
internal class DiagnosticRing(private val maxLines: Int=MAX_LINES,private val maxBytes: Int=MAX_TEXT_BYTES) {
    private val lines=ArrayDeque<String>()
    private var bytes=0

    @Synchronized fun add(line: String) {
        val value=ClientDiagnostics.mask(line)
        lines.addLast(value);bytes+=size(value)
        while(lines.size>maxLines || bytes>maxBytes)bytes-=size(lines.removeFirst())
    }
    @Synchronized fun snapshot(): List<String> = lines.toList()

    companion object {
        const val MAX_LINES=60
        const val MAX_TEXT_BYTES=6144
        private fun size(line: String)=line.toByteArray(Charsets.UTF_8).size
    }
}

/** Last failure an error screen can name in its report. Fixed words and path templates only. */
internal data class ClientFailure(val reason: String,val requestTemplate: String?)

/** One failure only the app saw, in the server's POST /v1/native/diagnostics shape. No values, ids or text. */
internal class ClientDiagnosticEvent(val kind: String,val method: String,val route: String,val requestId: String,
    val traceId: String,val status: Int?,val decodePath: String?,val decodeRule: String?,val elapsedMs: Long) {
    /** Repeats of the same failure while a batch is pending are one report. */
    val key: String get()="$kind $method $route ${status ?: 0} ${decodePath ?: ""} ${decodeRule ?: ""}"
    fun json(): JSONObject = JSONObject().put("kind",kind).put("method",method).put("route",route)
        .put("requestId",requestId).put("traceId",traceId).put("elapsedMs",elapsedMs).also {value->
            status?.let {value.put("status",it)}
            decodePath?.let {value.put("decodePath",it)}
            decodeRule?.let {value.put("decodeRule",it)}
        }
    override fun toString()="ClientDiagnosticEvent($kind $method $route)"
}

/** Bounded pending reports. Batches stay within the server limits (20 events, 8 KiB). */
internal class ClientDiagnosticsQueue(private val capacity: Int=MAX_EVENTS) {
    private val pending=ArrayList<ClientDiagnosticEvent>()
    private val keys=HashSet<String>()
    /** Reports not queued because the queue was full or the same failure was already pending. */
    var dropped=0
        private set

    @Synchronized fun offer(event: ClientDiagnosticEvent): Boolean {
        if(event.key in keys || pending.size>=capacity) {dropped++;return false}
        pending.add(event);keys.add(event.key);return true
    }
    @Synchronized fun isEmpty()=pending.isEmpty()
    /** Oldest first, as many as fit one request body. */
    @Synchronized fun take(): List<ClientDiagnosticEvent> {
        val batch=ArrayList<ClientDiagnosticEvent>()
        for(event in pending) {
            if(batch.size==MAX_EVENTS || body(batch+event).size>MAX_BYTES)break
            batch.add(event)
        }
        pending.subList(0,batch.size).clear();batch.forEach {keys.remove(it.key)}
        return batch
    }
    /** A batch that could not leave the device goes back in front, still within capacity. */
    @Synchronized fun restore(batch: List<ClientDiagnosticEvent>) {
        val kept=batch.filter {it.key !in keys}.take(capacity-pending.size)
        dropped+=batch.size-kept.size
        pending.addAll(0,kept);kept.forEach {keys.add(it.key)}
    }
    companion object {
        const val MAX_EVENTS=20
        const val MAX_BYTES=ClientDiagnostics.MAX_BODY_BYTES
        fun body(batch: List<ClientDiagnosticEvent>): ByteArray =
            JSONObject().put("events",JSONArray().also {array->batch.forEach {array.put(it.json())}}).toString().toByteArray(Charsets.UTF_8)
    }
}

/** App-side diagnostics, both sent only as fixed words, templates and masked lines:
 * - failures only the app saw, queued and sent in the background to POST /v1/native/diagnostics;
 * - recent masked WegoLog lines and the last failure per screen, for the opt-in error report.
 * Sending a queued report never blocks a request, never retries an HTTP rejection and never surfaces
 * an error; only a batch that could not reach the server is kept.
 */
internal object ClientDiagnostics {
    const val MAX_LINE_CHARS=240
    /** Server request limit; oldest lines are dropped until the JSON body fits. */
    const val MAX_BODY_BYTES=8192
    private val ring=DiagnosticRing()
    private val failures=HashMap<String,ClientFailure>()
    private val time=DateTimeFormatter.ofPattern("HH:mm:ss.SSS")
    private val screen=Regex("[a-z][a-z0-9_.]{1,47}")
    private val reason=Regex("[A-Za-z0-9_.-]{1,48}")
    private val template=Regex("(GET|POST|PUT|PATCH|DELETE|OTHER) /[A-Za-z0-9/{}_?=&.-]{0,159}")

    // Same rules as server/client_reports.py `mask`; the server masks again.
    private val sensitiveKey=Regex("\\b((?:account|device|grant|owner|user|member|friend|email|phone|plate|title|name|"+
        "nickname|address|query|token|secret|password|lat|lng|lon|latitude|longitude)[A-Za-z_]*)=(\"[^\"]*\"|\\S+)",RegexOption.IGNORE_CASE)
    private val masks=listOf(
        Regex("(?i)\\bbearer\\s+\\S+") to "Bearer {token}",
        Regex("(?i)\\b[a-z][a-z0-9+.-]*://\\S+") to "{url}",
        Regex("[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}") to "{email}",
        Regex("(?i)\\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\\b") to "{id}",
        Regex("\\b(?=[A-Za-z0-9_-]*[0-9])(?=[A-Za-z0-9_-]*[A-Za-z])[A-Za-z0-9_-]{24,}={0,2}") to "{token}",
        Regex("(?i)\\b[0-9a-f]{12,}\\b") to "{hex}",
        Regex("-?\\b[0-9]{1,3}\\.[0-9]{4,}\\b") to "{num}",
        Regex("[^\\x20-\\x7e]+") to "{text}")

    /** Drop values that could identify a person, account, vehicle, place or credential. */
    fun mask(line: String): String {
        var value=sensitiveKey.replace(line) {"${it.groupValues[1]}={masked}"}
        for((pattern,replacement) in masks)value=pattern.replace(value,Regex.escapeReplacement(replacement))
        return value.take(MAX_LINE_CHARS)
    }

    fun record(level: Char,tag: String,message: String) {
        ring.add("${LocalTime.now().format(time)} $level/$tag $message")
    }
    @Synchronized fun failed(scope: String,failure: ClientFailure) {failures[scope]=failure}
    @Synchronized fun failure(scope: String)=failures[scope]

    fun lines(): List<String> = ring.snapshot()

    /** Report body; screen, reason and template outside their fixed forms become unknown/null. */
    fun body(screen: String,failure: ClientFailure?,versionName: String,versionCode: Int,lines: List<String>): JSONObject {
        require(this.screen.matches(screen))
        var kept=lines.map(::mask)
        fun json()=JSONObject().put("reportVersion",1).put("screen",screen)
            .put("reason",failure?.reason?.takeIf {reason.matches(it)} ?: "unknown")
            .put("requestTemplate",failure?.requestTemplate?.takeIf {template.matches(it)} ?: JSONObject.NULL)
            .put("appVersion",versionName).put("appBuild",versionCode).put("lines",JSONArray(kept))
        var value=json()
        while(value.toString().toByteArray(Charsets.UTF_8).size>MAX_BODY_BYTES && kept.isNotEmpty()) {kept=kept.drop(1);value=json()}
        return value
    }

    // Background failure reports (POST /v1/native/diagnostics).
    const val ROUTE="/v1/native/diagnostics"
    private const val FIRST_DELAY_MS=5_000L
    /** At most one report request per interval: two a minute, below the server's 30 per account. */
    private const val INTERVAL_MS=30_000L
    private const val NOT_READY_DELAY_MS=60_000L

    /** Returns false when no signed-in vehicle session can send now; throws when the send failed. */
    fun interface Sender { fun send(body: ByteArray): Boolean }

    private val queue=ClientDiagnosticsQueue(MAX_PENDING)
    private const val MAX_PENDING=40
    @Volatile private var sender: Sender?=null
    private val scheduled=AtomicBoolean(false)
    @Volatile private var lastSentAt=0L
    private val executor: ScheduledExecutorService by lazy {
        Executors.newSingleThreadScheduledExecutor {task->Thread(task,"wegoh-client-diagnostics").apply {
            isDaemon=true;priority=Thread.MIN_PRIORITY
        }}
    }

    fun report(event: ClientDiagnosticEvent) {if(queue.offer(event))schedule(FIRST_DELAY_MS)}
    fun attach(value: Sender) {sender=value;if(!queue.isEmpty())schedule(FIRST_DELAY_MS)}
    fun detach(value: Sender) {if(sender===value)sender=null}

    private fun schedule(delay: Long) {
        if(!scheduled.compareAndSet(false,true))return
        val wait=maxOf(delay,lastSentAt+INTERVAL_MS-System.currentTimeMillis())
        runCatching {executor.schedule({flush()},wait,TimeUnit.MILLISECONDS)}.onFailure {scheduled.set(false)}
    }
    private fun flush() {
        scheduled.set(false)
        val send=sender ?: return
        val batch=queue.take()
        if(batch.isEmpty())return
        val ready=try {
            send.send(ClientDiagnosticsQueue.body(batch)).also {if(it)lastSentAt=System.currentTimeMillis()}
        } catch(_: java.io.IOException) {lastSentAt=System.currentTimeMillis();queue.restore(batch);true
        } catch(_: Exception) {lastSentAt=System.currentTimeMillis();true}
        if(!ready)queue.restore(batch)
        if(!queue.isEmpty())schedule(if(ready)INTERVAL_MS else NOT_READY_DELAY_MS)
    }
}

/** Writes to logcat as before and keeps a masked copy for the opt-in error report. */
internal object WegoLog {
    /** logcat writer. JVM unit tests replace it because android.util.Log is a stub there. */
    @Volatile internal var logcat: (Char,String,String)->Unit = {level,tag,message->
        if(level=='W')android.util.Log.w(tag,message) else android.util.Log.i(tag,message)}
    fun i(tag: String,message: String) {ClientDiagnostics.record('I',tag,message);logcat('I',tag,message)}
    fun w(tag: String,message: String) {ClientDiagnostics.record('W',tag,message);logcat('W',tag,message)}
}
