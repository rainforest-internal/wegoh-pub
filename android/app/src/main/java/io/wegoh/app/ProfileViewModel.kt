package io.wegoh.app

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.flow.StateFlow

data class AccountProfileState(val status: AccountReadStatus=AccountReadStatus.CONNECTION_REQUIRED,val name: String?=null,
    val canEdit: Boolean=false,val saving: Boolean=false,val message: String?=null,val needsReload: Boolean=false,val isCurrent: Boolean=true,
    val vehicle: io.wegoh.app.nativeauth.VehicleProfile?=null,val vehicleUnavailable: Boolean=false,val vehicleLoading: Boolean=false)

internal fun ProfileDataState.toUiState()=AccountProfileState(status,name,canEdit,saving,when(notice) {
    ProfileNotice.SAVED->"이름을 변경했어요"
    ProfileNotice.VEHICLE_SAVED->"차량 번호를 저장했어요"
    ProfileNotice.CONFIRM_REQUIRED->"변경 여부를 다시 확인해 주세요"
    null->null
},needsReload,isCurrent,vehicle,vehicleUnavailable,vehicleLoading)

internal class ProfileViewModel(private val repository: ProfileRepository): ViewModel() {
    val uiState: StateFlow<AccountProfileState> = repository.states.map {it.toUiState()}
        .stateIn(viewModelScope,SharingStarted.WhileSubscribed(5000),repository.state.toUiState())
    fun load()=repository.request()
    fun refresh()=repository.request(true)
    fun saveName(name: String)=repository.saveName(name)
    fun saveVehicle(plate: String)=repository.saveVehicle(plate)

    class Factory(private val repository: ProfileRepository): ViewModelProvider.Factory {
        override fun <T: ViewModel> create(modelClass: Class<T>): T {
            require(modelClass==ProfileViewModel::class.java)
            return modelClass.cast(ProfileViewModel(repository))!!
        }
    }
}
