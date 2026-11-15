package io.wegoh.app.ui

import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier

@Composable
fun AppUpdatePrompt(onYes: ()->Unit,onNo: ()->Unit) {
    CarPopup("최신 버전이 존재합니다.",onNo,
        body={CarText("업데이트를 위해 페이지를 이동할까요?",style=CarType.Body.copy(textAlign=androidx.compose.ui.text.style.TextAlign.Center),maxLines=2)},
        actions={
            CarButton("업데이트",onYes,Modifier.weight(1f),primary=true)
            CarButton("나중에",onNo,Modifier.weight(1f))
        })
}

@Composable
fun AppUpdateMarketError(onDismiss: ()->Unit) {
    CarPopup("앱 마켓을 열 수 없습니다",onDismiss,body={},
        actions={CarAction("확인",CarSymbol.Check,onDismiss,Modifier.weight(1f),primary=true)})
}
