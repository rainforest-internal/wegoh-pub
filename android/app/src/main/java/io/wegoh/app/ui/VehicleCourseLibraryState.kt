package io.wegoh.app.ui

import io.wegoh.app.*

internal fun vehicleCourseLibraryState(state: WegoState,tab: VehicleCourseFeedTab,tags: Set<String>): VehicleCourseFeedState {
    val account=state.accountCourses
    val discovery=state.accountDiscovery
    val library=discovery.library
    val mine=tab==VehicleCourseFeedTab.MINE
    val status=if(mine)when(account.status) {
        AccountCourseStatus.READY->AccountReadStatus.READY
        AccountCourseStatus.LOADING->AccountReadStatus.LOADING
        AccountCourseStatus.PERMISSION_REQUIRED->AccountReadStatus.PERMISSION_REQUIRED
        AccountCourseStatus.CONNECTION_REQUIRED->AccountReadStatus.CONNECTION_REQUIRED
        else->AccountReadStatus.UNAVAILABLE
    } else discovery.status
    val actionable=state.setupAllowed && !state.active && !state.reportBusy &&
        account.downloading==null && discovery.downloading==null
    fun card(item: CourseLibraryItem,isNew: Boolean=false)=VehicleCourseFeedCard(item.published.key,item.published.title,
        item.published.author,item.published.stopCount,item.published.description,item.tags,item.starCount,isNew,
        canOpen=actionable,canAdd=actionable,creatorRank=item.creatorRank,published=item.published)
    val cards=when(tab) {
        VehicleCourseFeedTab.RECOMMENDED->library?.public.orEmpty().map {card(it)}
        VehicleCourseFeedTab.SAVED->library?.saved.orEmpty().map {card(it)}
        VehicleCourseFeedTab.SUBSCRIPTIONS->library?.news.orEmpty().distinctBy {it.course.published.key}.map {card(it.course,!it.read)}
        VehicleCourseFeedTab.MINE->account.courses.map {course->
            val metadata=(library?.public.orEmpty()+library?.saved.orEmpty()).firstOrNull {it.published.key==course.published.key}
            VehicleCourseFeedCard(course.published.key,course.published.title,course.published.author,
                course.published.stopCount,course.published.description,course.tags.ifEmpty {metadata?.tags.orEmpty()},
                metadata?.starCount,canOpen=actionable && course.available,canAdd=actionable && course.available,creatorRank=metadata?.creatorRank,
                published=course.published.takeIf {course.available})
        }
    }
    val availableTags=(if(tab==VehicleCourseFeedTab.RECOMMENDED)library?.popularTags.orEmpty()
        else cards.flatMap {it.tags}.distinctBy(::vehicleCourseTagKey)).take(8)
    return VehicleCourseFeedState(tab,status,cards,availableTags,tags,library?.unreadCount,
        library?.following.orEmpty().mapNotNull {it.name},if(mine)account.isCurrent else discovery.isCurrent,
        sortLabel=if(tab==VehicleCourseFeedTab.RECOMMENDED)"별표 많은 순" else null,
        followingTags=library?.followedTags.orEmpty())
}
