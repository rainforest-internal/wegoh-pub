package io.wegoh.app.ui

import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import io.wegoh.app.BuildConfig
import io.wegoh.app.nativeauth.ClientDiagnostics
import io.wegoh.app.nativeauth.VehicleConnection

/** Sends one error report for a fixed screen id; the callback carries the server's report id. */
internal fun interface CarErrorReporter {
    fun send(screen: String,callback: (Result<String>)->Unit)
}

internal val LocalCarErrorReporter=staticCompositionLocalOf<CarErrorReporter?> {null}

@Composable
internal fun ProvideCarErrorReports(connection: VehicleConnection,content: @Composable ()->Unit) {
    val reporter=remember(connection) {
        CarErrorReporter {screen,callback->connection.sendClientReport(ClientDiagnostics.body(screen,
            ClientDiagnostics.failure(screen),BuildConfig.VERSION_NAME,BuildConfig.VERSION_CODE,ClientDiagnostics.lines()),callback)}
    }
    CompositionLocalProvider(LocalCarErrorReporter provides reporter,content=content)
}

internal enum class CarErrorReportStatus { IDLE, SENDING, SENT, FAILED }

/** "오류 보고하기" starts off; sending is possible only after the user turns it on. */
internal data class CarErrorReportState(val enabled: Boolean=false,val status: CarErrorReportStatus=CarErrorReportStatus.IDLE,
    val reportId: String?=null) {
    val canSend get()=enabled && status!=CarErrorReportStatus.SENDING && status!=CarErrorReportStatus.SENT
    val message get()=when(status) {
        CarErrorReportStatus.SENT->"보냈어요 · 보고 번호 ${reportId.orEmpty().take(8)}"
        CarErrorReportStatus.FAILED->"보내지 못했어요. 다시 눌러 주세요"
        else->null
    }
    fun toggled(on: Boolean)=if(status==CarErrorReportStatus.SENDING)this else CarErrorReportState(enabled=on)
    fun sending()=if(canSend)copy(status=CarErrorReportStatus.SENDING,reportId=null) else this
    fun finished(result: Result<String>)=if(status!=CarErrorReportStatus.SENDING)this else result.fold(
        onSuccess={copy(status=CarErrorReportStatus.SENT,reportId=it)},onFailure={copy(status=CarErrorReportStatus.FAILED)})
}

/** Inline report controls for an error state; nothing is shown without a reporter. */
@Composable
internal fun CarErrorReport(screen: String) {
    val reporter=LocalCarErrorReporter.current ?: return
    var state by remember(screen) {mutableStateOf(CarErrorReportState())}
    CarDivider()
    CarSwitch("오류 보고하기",state.enabled,enabled=state.status!=CarErrorReportStatus.SENDING) {state=state.toggled(it)}
    if(state.enabled)CarText("최근 앱 진단 기록을 보내요. 계정·위치·여행 제목은 빼고 보내요",secondary=true,maxLines=3)
    CarButton(if(state.status==CarErrorReportStatus.SENDING)"보내는 중" else "전송하기",{
        val next=state.sending()
        if(next!==state) {
            state=next
            reporter.send(screen) {result->state=state.finished(result)}
        }
    },Modifier.fillMaxWidth(),enabled=state.canSend,icon=CarSymbol.Share,busy=state.status==CarErrorReportStatus.SENDING)
    state.message?.let {CarText(it,secondary=state.status==CarErrorReportStatus.SENT,maxLines=2)}
}
