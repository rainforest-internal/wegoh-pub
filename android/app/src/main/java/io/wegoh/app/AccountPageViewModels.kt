package io.wegoh.app

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider

internal class CoursesViewModel(repository: CoursesRepository,private val selectCourse: (AccountCourse)->Unit): ViewModel() {
    val uiState=repository.states
    private val repository=repository
    fun load()=repository.request()
    fun refresh()=repository.request(true)
    fun select(course: AccountCourse)=selectCourse(course)
}

internal class PlaylistsViewModel(private val repository: PlaylistsRepository,private val openLink: (String,Long,String)->String?): ViewModel() {
    val uiState=repository.states
    fun load()=repository.request()
    fun refresh()=repository.request(true)
    fun select(item: PlaylistSummary)=repository.select(item)
    fun link(id: String,revision: Long,track: String)=openLink(id,revision,track)
}

internal class DiscoveryViewModel(private val repository: DiscoveryRepository,private val downloadPack: (PublishedPack)->Unit): ViewModel() {
    val uiState=repository.states
    fun load()=repository.request()
    fun refresh()=repository.request(true)
    fun download(pack: PublishedPack)=downloadPack(pack)
}

internal class FeatureViewModelFactory<T: ViewModel>(private val type: Class<T>,private val create: ()->T): ViewModelProvider.Factory {
    override fun <V: ViewModel> create(modelClass: Class<V>): V {
        require(modelClass==type)
        return modelClass.cast(create())!!
    }
}
