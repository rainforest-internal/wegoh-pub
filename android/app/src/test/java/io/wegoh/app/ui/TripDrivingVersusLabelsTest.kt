package io.wegoh.app.ui

import io.wegoh.app.nativeauth.TripDrivingVersus
import org.junit.Assert.assertEquals
import org.junit.Test

class TripDrivingVersusLabelsTest {
    private fun value(reason: String?,state: String="unavailable")=TripDrivingVersus(
        "safe-driving-versus",true,state,reason,emptyList(),emptyList(),false)

    @Test fun privateUnavailableReasonsExplainTheNextCheckWithoutClaimingMissingMeasurements() {
        assertEquals("경로를 확인할 수 없어 점수를 숨겼어요. 경로 공개 상태를 확인해 주세요",
            versusReasonLabel(value("course-unavailable")))
        assertEquals("공유 설정이 바뀌어 점수를 숨겼어요. 차량에서 공유 설정과 점수 전송을 확인해 주세요",
            versusReasonLabel(value("report-authorization-changed")))
        assertEquals("공개할 수 없는 점수가 있어 비교할 수 없어요",versusReasonLabel(value("sharing-unavailable")))
        assertEquals("경로 공개 확인 필요",versusCarStateLabel("sharing-unavailable","course-unavailable"))
        assertEquals("점수 전송 확인 필요",versusCarStateLabel("sharing-unavailable","report-authorization-changed"))
        assertEquals("공유 상태 확인 필요",versusCarStateLabel("sharing-unavailable","sharing-unavailable"))
        assertEquals("측정 불가",versusCarStateLabel("unavailable","report-authorization-changed"))
    }

    @Test fun currentReasonsDescribeConnectionAndMembershipInsteadOfScoreConsent() {
        assertEquals("차량 연결 확인 필요",versusCarStateLabel("sharing-unavailable","vehicle-connection-required"))
        assertEquals("점수 전송 확인 필요",versusCarStateLabel("sharing-unavailable","report-device-changed"))
        assertEquals("여행 참가 상태 확인 필요",versusCarStateLabel("sharing-unavailable","participant-unavailable"))
        assertEquals("차량 연결과 참가 상태 확인 필요",versusCarStateLabel("sharing-unavailable","vehicle-authority-unavailable"))
        assertEquals("차량 연결과 여행 참가 상태를 확인해 주세요",versusReasonLabel(value("vehicle-authority-unavailable")))
    }

    @Test fun oldAndFutureReasonsKeepSafeFallbacks() {
        assertEquals("모든 차의 주행과 점수 전송이 끝나면 확정돼요",
            versusReasonLabel(value("final-reports-pending","pending")))
        assertEquals("점수가 있는 차가 두 대 이상이어야 비교할 수 있어요",versusReasonLabel(value("insufficient-measurements")))
        assertEquals("대결 결과를 확인할 수 없어요",versusReasonLabel(value("future-reason")))
        assertEquals("여행 전체의 점수를 비교한 결과예요",versusReasonLabel(value(null,"final")))
        assertEquals("공유 상태 확인 필요",versusCarStateLabel("sharing-unavailable","future-reason"))
        assertEquals("측정 결과 없음",versusCarStateLabel("future-state"))
    }
}
