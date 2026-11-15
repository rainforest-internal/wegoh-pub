import SwiftUI

struct AppTabs: View {
    @Environment(\.scenePhase) private var scenePhase
    @State private var wasBackgrounded = false
    @State private var returnFromBackground: UUID?
    @State private var selectedTab = 0
    @State private var friendsNotificationID: String?
    @State private var tripsNotification: IPhonePushNotification?
    @State private var push = IPhonePushManager.shared
    var body: some View {
        TabView(selection: $selectedTab) {
            NavigationStack {
                TripsHomeView(notification: tripsNotification, returnFromBackground: returnFromBackground, isSelected: selectedTab == 0)
            }
            .id(tripsNotification?.eventID)
            .tabItem { Label("여행", systemImage: "map") }
            .tag(0)

            NavigationStack {
                CoursesHomeView()
            }
            .tabItem { Label("경로", systemImage: "point.topleft.down.to.point.bottomright.curvepath") }
            .tag(1)

            NavigationStack {
                MusicHomeView()
            }
            .tabItem { Label("음악", systemImage: "music.note.list") }
            .tag(2)

            NavigationStack {
                FriendsHomeView()
            }
            .id(friendsNotificationID)
            .tabItem { Label("친구", systemImage: "person.2") }
            .tag(3)

            NavigationStack {
                SettingsView()
            }
            .tabItem { Label("설정", systemImage: "gearshape") }
            .tag(4)
        }
        .modifier(TripSignalInboxModifier())
        .onChange(of: scenePhase) { _, phase in
            if phase == .background {
                wasBackgrounded = true
            } else if phase == .active && wasBackgrounded {
                wasBackgrounded = false
                returnFromBackground = UUID()
            }
        }
        .onChange(of: push.openedNotification, initial: true) { _, event in
            guard let event else { tripsNotification = nil; return }
            if event.isFriendEvent { tripsNotification = nil; friendsNotificationID = event.eventID; selectedTab = 3 }
            else { tripsNotification = event; selectedTab = 0 }
        }
    }
}
