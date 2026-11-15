package io.wegoh.app.ui

import androidx.compose.foundation.layout.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import io.wegoh.app.CourseDrivingResult

@Composable
internal fun CourseDrivingResultCard(result: CourseDrivingResult?,modifier: Modifier=Modifier) {
    CarCard(modifier.fillMaxWidth()) {
        CarText("경로 안전운전 결과",style=CarType.Section,maxLines=2)
        CarText(result?.score?.let {"${it}점"} ?: "측정 불가",Modifier.fillMaxWidth(),style=CarType.Hero,maxLines=2)
        if(result?.score!=null) {
            CarMetadata(listOf("급가속 ${result.accelerations}회","급감속 ${result.brakings}회"),style=CarType.Body,secondary=false)
            CarText("1회당 5점 감점",secondary=true,maxLines=2)
            if(result.interrupted)CarText("일부 구간만 측정했어요",secondary=true,maxLines=2)
        } else CarText(if(result==null)"측정 결과를 확인할 수 없어요" else
            "속도 정보가 부족해 측정하지 못했어요",secondary=true,maxLines=2)
    }
}
