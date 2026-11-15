package io.wegoh.app.nativeauth

import org.json.JSONObject

internal data class CommandReceiver(val deviceId: String, val grantId: String, val revision: Long, val enabled: Boolean) {
    override fun toString() = "CommandReceiver(revision=$revision, enabled=$enabled)"

    companion object {
        private val id = Regex("[a-f0-9]{32}")

        fun decode(value: JSONObject, deviceId: String, grantId: String): CommandReceiver {
            check(value.keys().asSequence().toSet() == setOf("deviceId", "grantId", "revision", "enabled"))
            check(id.matches(deviceId) && id.matches(grantId))
            check(value.get("deviceId") == deviceId && value.get("grantId") == grantId)
            val revision = value.get("revision")
            check(revision is Int || revision is Long)
            val number = (revision as Number).toLong()
            val enabled = value.get("enabled")
            check(number in 1..Int.MAX_VALUE.toLong() && enabled is Boolean)
            return CommandReceiver(deviceId, grantId, number, enabled)
        }
    }
}
