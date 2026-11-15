package io.wegoh.app.nativeauth

import android.content.Context
import android.util.Base64
import org.json.JSONArray
import org.json.JSONObject
import java.net.URI
import java.security.MessageDigest
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

internal const val NATIVE_WIRE_MAX_BYTES = 262144

internal fun readBundledNativeAccessWire(input: java.io.InputStream): JSONObject =
    StrictNativeJson.parse(boundedBytes(input,NATIVE_WIRE_MAX_BYTES),NATIVE_WIRE_MAX_BYTES)

/** Internal wire boundary. No credential DTO is handed to UI or logged.
 * Both platforms consume the byte-identical server/native_access_wire.json.
 */
internal class NativeAccessCodec(context: Context) {
    private val wire = context.assets.open("native_access_wire.json").use {readBundledNativeAccessWire(it)}
    init {check(wire.getInt("schemaVersion")==1) {"NATIVE_PROTOCOL_CONTRACT_INVALID"}}
    val functional by lazy {NativeFunctionalCodec(wire.getJSONObject("functional"))}
    private val operations = wire.getJSONArray("operations").objects().associateBy { it.getString("action") }
    private val knownScopes = setOf("account:read", "account:write", "courses:read", "device:self:manage", "playlists:read")
    private val requiredScopes = setOf("account:read", "device:self:manage")
    val defaultScopes get() = listOf("account:read", "device:self:manage")
    fun operation(action: String): JSONObject = operations[action] ?: invalid()
    fun origin(action: String): URI = URI(wire.getJSONObject("origins").getString(operation(action).getString("host")))
    fun path(action: String, connectionId: String? = null, deviceId: String? = null): String {
        var path = operation(action).getString("path")
        if (path.contains("{connectionId}")) path = path.replace("{connectionId}", hex(connectionId, 32))
        if (path.contains("{deviceId}")) path = path.replace("{deviceId}", hex(deviceId, 32))
        check(!path.contains('{')); return path
    }
    fun request(action: String, value: JSONObject): JSONObject {
        val op = operation(action)
        val required = op.getJSONArray("requestRequired").strings().toSet()
        val optional = op.getJSONArray("requestOptional").strings().toSet()
        closed(value, required, optional)
        val types = wire.getJSONObject("requestFieldTypes")
        value.keys().forEach { key ->
            if (key == "proofNonce") {
                val fixed=op.optJSONObject("fixedRequestValues")
                if(fixed?.has(key)==true) check(value.get(key)==fixed.get(key)) else secret(value.get(key))
            } else typed(types.getString(key), value.get(key))
        }
        check(value.get("authorizationVersion") == 1 || value.get("authorizationVersion") == 1L)
        check(canonical(value).size <= wire.getJSONObject("envelope").getInt("bodyLimitBytes"))
        return value
    }
    fun response(action: String, status: Int, value: JSONObject, operationId: String,
        installationKeyId: String): JSONObject {
        val common = wire.getJSONObject("responseCommonFields")
        val variants = operation(action).getJSONArray("responseVariants").objects().filter {
            it.getInt("httpStatus") == status && it.getString("state") == value.optString("state") &&
                it.getString("disposition") == value.optString("disposition") &&
                value.keys().asSequence().toSet() == (common.keys().asSequence().toSet() + it.getJSONObject("required").keys().asSequence().toSet()) }
        check(variants.size == 1) { "NATIVE_RESPONSE_INVALID" }
        val variant = variants.single()
        val required = variant.getJSONObject("required")
        val optional = variant.getJSONObject("optional")
        closed(value, common.keys().asSequence().toSet() + required.keys().asSequence().toSet(),
            optional.keys().asSequence().toSet())
        common.keys().forEach { typed(common.getString(it), value.get(it)) }
        required.keys().forEach { typed(required.getString(it), value.get(it)) }
        optional.keys().forEach { if (value.has(it)) typed(optional.getString(it), value.get(it)) }
        check(value.getString("operation") == action && value.getString("operationId") == operationId)
        val time=value.getLong("serverTime")
        value.optJSONObject("credentialReceipt")?.let { check(time < it.getLong("expiresAt") && it.getLong("expiresAt") <= time+900) }
        value.optJSONObject("certificateReceipt")?.let {
            val cert=NativeDeviceIdentity.parseCertificates(it.getString("certificatePem")).single()
            cert.checkValidity(java.util.Date(time*1000))
        }
        if (value.has("verificationUri")) check(value.getString("verificationUri") ==
            "https://wegoh.devforest.io/enroll.html?user_code=${value.getString("userCode")}")
        for (field in listOf("certificateReceipt", "credentialReceipt")) if (value.has(field)) {
            check(value.getJSONObject(field).getString("installationKeyId") == installationKeyId)
        }
        return value
    }
    fun error(status: Int, value: JSONObject): NativeApiClient.Failure {
        closed(value, setOf("authorizationVersion", "error"), setOf("retryAfter"))
        typed("Version", value.get("authorizationVersion"))
        val code = value.get("error") as? String ?: invalid()
        check(wire.getJSONObject("errors").optJSONArray(status.toString())?.strings()?.contains(code) == true)
        if (value.has("retryAfter")) typed("RetryAfter", value.get("retryAfter"))
        return NativeApiClient.Failure(status, code, if(value.has("retryAfter")) value.getInt("retryAfter") else null)
    }
    fun transcript(action: String, value: JSONObject, keyId: String, challenge: String,
        connectionId: String? = null): ByteArray {
        check(operation(action).getBoolean("keyProofRequired"))
        request(action, value)
        val body = JSONObject(value.toString()).apply { remove("proof") }
        if(action in setOf("CERTIFICATE_RENEW_BEGIN","CONNECTION_REAUTHORIZE")) check(value.getString("codeChallenge")==challenge)
        val id = when(action) {
            "CONNECTION_RECOVER", "CONNECTION_CANCEL", "CERTIFICATE_RECOVER", "CERTIFICATE_RENEW_BEGIN", "CONNECTION_REAUTHORIZE" -> "-"
            "CONNECTION_RESTART" -> hex(value.get("previousConnectionId"), 32)
            else -> hex(connectionId, 32)
        }
        return listOf("WegoH native access v2", action, origin(action).toString(), "POST",
            path(action, connectionId), value.getString("operationId"), id, hex(keyId,64),
            secret(challenge), value.getString("proofNonce"), NativeDeviceIdentity.sha256(canonical(body)))
            .joinToString("\n").toByteArray(Charsets.US_ASCII)
    }
    private fun record(name: String, value: Any) {
        val objectValue = value as? JSONObject ?: invalid()
        val schema = wire.getJSONObject("receipts").getJSONObject(name)
        val fields = schema.getJSONObject("required")
        closed(objectValue, fields.keys().asSequence().toSet(), emptySet())
        fields.keys().forEach { typed(fields.getString(it), objectValue.get(it)) }
        if(name == "credentialReceipt") check(objectValue.getLong("expiresAt") <= objectValue.getLong("grantExpiresAt"))
        if(name == "certificateReceipt") {
            val leaf = NativeDeviceIdentity.parseCertificates(objectValue.getString("certificatePem")).single()
            check(NativeDeviceIdentity.sha256(leaf.encoded) == objectValue.getString("certificateSha256"))
            check(NativeDeviceIdentity.sha256(leaf.publicKey.encoded) == objectValue.getString("installationKeyId"))
            check(leaf.notAfter.time / 1000 == objectValue.getLong("expiresAt"))
            val rsa=leaf.publicKey as? java.security.interfaces.RSAPublicKey ?: invalid()
            check(rsa.modulus.bitLength()==2048 && rsa.publicExponent==java.math.BigInteger.valueOf(65537))
            check(leaf.subjectX500Principal.name.matches(Regex("CN=WegoH-[a-f0-9]{32}")) && leaf.subjectX500Principal != leaf.issuerX500Principal)
            val sha2Oids=setOf("1.2.840.113549.1.1.11","1.2.840.113549.1.1.12","1.2.840.113549.1.1.13",
                "1.2.840.10045.4.3.2","1.2.840.10045.4.3.3","1.2.840.10045.4.3.4")
            if(leaf.sigAlgOID=="1.2.840.113549.1.1.10") {
                val params=java.security.AlgorithmParameters.getInstance("PSS").apply { init(leaf.sigAlgParams) }
                val digest=params.getParameterSpec(java.security.spec.PSSParameterSpec::class.java).digestAlgorithm.uppercase().replace("-","")
                check(digest in setOf("SHA256","SHA384","SHA512"))
            } else check(leaf.sigAlgOID in sha2Oids)
            NativeDeviceIdentity.requireClientKeyUsage(leaf)
            check(leaf.basicConstraints == -1 && leaf.extendedKeyUsage?.contains("1.3.6.1.5.5.7.3.2") == true)
        }
    }
    private fun typed(type: String, value: Any) {
        when(type) {
            "Id" -> hex(value,32)
            "InstallationKeyId", "CertificateSha256" -> hex(value,64)
            "AccountId" -> check(value is String && Regex("team-[a-f0-9]{40}").matches(value))
            "Secret", "S25643", "ServerNonce" -> secret(value)
            "RSA2048Signature342" -> base64(value,256)
            "PkceVerifier" -> check(value is String && Regex("[A-Za-z0-9._~-]{43,128}").matches(value))
            "UserCode" -> check(value is String && Regex("[A-HJ-NP-Z2-9]{8}").matches(value))
            "Version" -> check(number(value,1,1)==1L)
            "Timestamp" -> number(value,0,253402300799)
            "Counter" -> number(value,0,9007199254740991)
            "Epoch" -> number(value,1,9007199254740991)
            "Generation", "ConsentVersion" -> number(value,1,2147483647)
            "PollInterval" -> number(value,5,60)
            "RetryAfter" -> number(value,5,86400)
            "literal Bearer", "CredentialKind" -> check(value == "Bearer")
            "ScopeSet" -> {
                val scopes=(value as? JSONArray ?: invalid()).strings()
                check(scopes.isNotEmpty() && scopes == scopes.distinct().sorted() && knownScopes.containsAll(scopes) && scopes.containsAll(requiredScopes))
            }
            "DeviceName" -> {
                check(value is String && value == value.trim() && value.codePointCount(0,value.length) in 1..80 && value.toByteArray(Charsets.UTF_8).size<=240)
                check(value.codePoints().toArray().none { it<32 || it in 127..159 || it in 0xd800..0xdfff })
            }
            "SingleValidatedPem" -> check(value is String && value.length in 1..8192 && value.all { it.code<=127 } &&
                Regex("-----BEGIN (CERTIFICATE|CERTIFICATE REQUEST)-----[A-Za-z0-9+/=\\r\\n]+-----END \\1-----\\n?").matches(value))
            "State" -> check(value is String && wire.getJSONArray("states").strings().contains(value))
            "Disposition" -> check(value is String && wire.getJSONArray("dispositions").strings().contains(value))
            "AuthorizationOperation" -> check(value is String && operations.containsKey(value))
            "FixedPhoneUri" -> check(value is String)
            "certificateReceipt", "credentialReceipt" -> record(type,value)
            else -> invalid()
        }
    }
    companion object {
        internal fun hex(value: Any?, count: Int): String = (value as? String)?.also {
            check(Regex("[a-f0-9]{$count}").matches(it)) } ?: invalid()
        internal fun secret(value: Any): String = base64(value,32)
        private fun base64(value: Any, count: Int): String {
            check(value is String && Regex("[A-Za-z0-9_-]+").matches(value))
            val bytes=Base64.decode(value,Base64.URL_SAFE or Base64.NO_WRAP or Base64.NO_PADDING)
            check(bytes.size==count && encode(bytes)==value);return value
        }
        internal fun encode(bytes: ByteArray): String = Base64.encodeToString(bytes,Base64.URL_SAFE or Base64.NO_PADDING or Base64.NO_WRAP)
        internal fun capability(verifier: String, grantId: String, purpose: String): String {
            check(purpose in setOf("recovery","revoke"));hex(grantId,32)
            val mac=Mac.getInstance("HmacSHA256");mac.init(SecretKeySpec(verifier.toByteArray(Charsets.US_ASCII),"HmacSHA256"))
            return encode(mac.doFinal("WegoH native access v2 $purpose\n$grantId".toByteArray(Charsets.US_ASCII)))
        }
        internal fun preExchangeRevoke(verifier: String,key: String,operation: String): String {
            check(Regex("[A-Za-z0-9._~-]{43,128}").matches(verifier));hex(key,64);hex(operation,32)
            val mac=Mac.getInstance("HmacSHA256");mac.init(SecretKeySpec(verifier.toByteArray(Charsets.US_ASCII),"HmacSHA256"))
            return encode(mac.doFinal("WegoH native access v2 revoke-before-exchange\n$key\n$operation".toByteArray(Charsets.US_ASCII)))
        }
        internal fun revokeCommitment(capability: String): String {
            secret(capability)
            return NativeDeviceIdentity.sha256("WegoH native v2 revoke\n$capability".toByteArray(Charsets.US_ASCII))
        }
        internal fun canonical(value: Any): ByteArray = canonicalText(value).toByteArray(Charsets.UTF_8)
        private fun canonicalText(value: Any): String = when(value) {
            is JSONObject -> value.keys().asSequence().toList().sorted().joinToString(",","{","}") {
                quote(it)+":"+canonicalText(value.get(it)) }
            is JSONArray -> (0 until value.length()).joinToString(",","[","]") { canonicalText(value.get(it)) }
            is String -> quote(value)
            is Boolean, is Int, is Long -> value.toString()
            else -> invalid()
        }
        private fun quote(value: String): String = buildString {
            append('"');for(c in value) when(c) {
                '"' -> append("\\\"");'\\' -> append("\\\\");'\b' -> append("\\b");'\u000c' -> append("\\f")
                '\n' -> append("\\n");'\r' -> append("\\r");'\t' -> append("\\t")
                else -> if(c.code<32) append("\\u%04x".format(c.code)) else append(c)
            };append('"')
        }
        private fun number(value: Any, min: Long, max: Long): Long {
            check(value is Int || value is Long);return (value as Number).toLong().also { check(it in min..max) }
        }
        private fun closed(value: JSONObject, required: Set<String>, optional: Set<String>) {
            val keys=value.keys().asSequence().toSet();check(keys.containsAll(required) && (required+optional).containsAll(keys))
        }
        private fun invalid(): Nothing = error("NATIVE_WIRE_INVALID")
        private fun JSONArray.strings(): List<String> = (0 until length()).map { get(it) as? String ?: invalid() }
        private fun JSONArray.objects(): List<JSONObject> = (0 until length()).map { get(it) as? JSONObject ?: invalid() }
    }
}

/** org.json otherwise accepts duplicate keys and coerces primitives. This bounded
 * RFC8259 reader rejects them before typed DTO validation. No original text escapes.
 */
internal object StrictNativeJson {
    fun parse(bytes: ByteArray, maximum: Int = 12288): JSONObject = objectValue(bytes,maximum,false)
    fun parseFunctional(bytes: ByteArray, maximum: Int = 65536): JSONObject = objectValue(bytes,maximum,false,true)
    // Business projections contain nullable fields and finite durations/coordinates.
    // Authorization/wire parsing retains its integer-only literal contract.
    fun parseBusiness(bytes: ByteArray, maximum: Int = 1048576): JSONObject = objectValue(bytes,maximum,true)
    private fun objectValue(bytes: ByteArray, maximum: Int, business: Boolean, functionalProofNull: Boolean = false): JSONObject {
        check(bytes.size in 1..maximum)
        val decoder=Charsets.UTF_8.newDecoder().onMalformedInput(java.nio.charset.CodingErrorAction.REPORT)
            .onUnmappableCharacter(java.nio.charset.CodingErrorAction.REPORT)
        val reader=Reader(decoder.decode(java.nio.ByteBuffer.wrap(bytes)).toString(),business,functionalProofNull)
        return (reader.value(0) as? JSONObject ?: error("NATIVE_JSON_INVALID")).also { reader.end() }
    }
    private class Reader(private val text: String,private val business: Boolean,private val functionalProofNull: Boolean) {
        private var at=0
        private fun ws() { while(at<text.length && text[at] in " \r\n\t") at++ }
        fun end() { ws();check(at==text.length) }
        fun value(depth: Int,allowNull: Boolean = false): Any {
            check(depth<24);ws();check(at<text.length)
            return when(text[at]) {
                '{' -> { at++;val obj=JSONObject();ws();if(take('}')) obj else {
                    do {
                        ws();val key=string();check(!obj.has(key));ws();check(take(':'))
                        obj.put(key,value(depth+1,functionalProofNull && depth==0 && key=="approvedDisclosureVersion"));ws()
                    } while(take(','))
                    check(take('}'));obj } }
                '[' -> { at++;val arr=JSONArray();ws();if(take(']')) arr else {
                    do { arr.put(value(depth+1));ws() } while(take(','));check(take(']'));arr } }
                '"' -> string()
                't' -> literal("true",true)
                'f' -> literal("false",false)
                'n' -> {check((business || allowNull) && text.startsWith("null",at));at+=4;JSONObject.NULL}
                else -> if(business) businessNumber() else {
                    val start=at;if(text[at]=='-') at++;check(at<text.length)
                    if(text[at]=='0') at++ else { check(text[at] in '1'..'9');while(at<text.length && text[at] in '0'..'9') at++ }
                    text.substring(start,at).toLong()
                }
            }
        }
        private fun businessNumber(): Number {
            val start=at
            if(take('-'))check(at<text.length)
            if(!take('0')) {
                check(at<text.length && text[at] in '1'..'9')
                while(at<text.length && text[at] in '0'..'9')at++
            }
            var decimal=false
            if(take('.')) {
                decimal=true;check(at<text.length && text[at] in '0'..'9')
                while(at<text.length && text[at] in '0'..'9')at++
            }
            if(at<text.length && text[at] in "eE") {
                decimal=true;at++
                if(at<text.length && text[at] in "+-")at++
                check(at<text.length && text[at] in '0'..'9')
                while(at<text.length && text[at] in '0'..'9')at++
            }
            val token=text.substring(start,at)
            return if(decimal)token.toDouble().also {check(it.isFinite())}else token.toLong()
        }
        private fun take(c: Char): Boolean = if(at<text.length && text[at]==c) { at++;true } else false
        private fun literal(token: String, value: Boolean): Boolean { check(text.startsWith(token,at));at+=token.length;return value }
        private fun string(): String {
            check(take('"'));val out=StringBuilder()
            while(at<text.length) {
                val c=text[at++];if(c=='"') {
                    val value=out.toString();var i=0
                    while(i<value.length) { val x=value[i++];if(Character.isHighSurrogate(x)) {
                        check(i<value.length && Character.isLowSurrogate(value[i++]));
                    } else check(!Character.isLowSurrogate(x)) };return value
                }
                check(c.code>=32)
                if(c!='\\') out.append(c) else {
                    check(at<text.length);when(val e=text[at++]) {
                        '"','\\','/' -> out.append(e)
                        'b' -> out.append('\b');'f' -> out.append('\u000c');'n' -> out.append('\n');'r' -> out.append('\r');'t' -> out.append('\t')
                        'u' -> { check(at+4<=text.length);val hex=text.substring(at,at+4);check(Regex("[0-9a-fA-F]{4}").matches(hex));out.append(hex.toInt(16).toChar());at+=4 }
                        else -> error("NATIVE_JSON_INVALID")
                    }
                }
            };error("NATIVE_JSON_INVALID")
        }
    }
}
