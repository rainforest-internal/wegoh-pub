package io.wegoh.app.nativebusiness

import io.wegoh.app.VehicleRemoteResult
import io.wegoh.app.nativeauth.NativeBusinessCodec
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Test

class NativeBusinessCommandStatusTest {
    private val owner="team-"+"c".repeat(40)
    private val device="d".repeat(32)
    private fun status(stage: String,reason: String?): String {
        val time="2026-11-01T00:00:00Z"
        val item=JSONObject().put("id","a".repeat(32)).put("roomId",JSONObject.NULL).put("ownerId",owner)
            .put("targetDeviceId",device).put("requesterId","team-"+"e".repeat(40))
            .put("capabilityId","light.cabin").put("capabilityRevision",1).put("stage",stage)
            .put("mayHaveExecuted",false).put("physicalExecutionVerified",false).put("createdAt",time).put("expiresAt",time)
            .put("reason",reason ?: JSONObject.NULL)
        val inbox=JSONObject().put("serverNow",time).put("supportedControlActions",JSONArray()).put("requests",JSONArray().put(item))
        val command=NativeBusinessCodec.commands(inbox,device,owner).commands.single()
        return businessCommandStatus(command.stage,command.reason).first
    }

    @Test fun drivingRejectionReadsTheSameAsTheVehicleRemoteHistory() {
        assertEquals("주행 중 제한",status("rejected","driving-restricted"))
        assertEquals(VehicleRemoteResult.DRIVING_BLOCKED.label,status("rejected","driving-restricted"))
    }

    @Test fun otherRejectionsStayRejected() {
        assertEquals("거절됨",status("rejected",null))
        assertEquals("취소됨",status("cancelled","explicit-cancellation"))
    }
}
