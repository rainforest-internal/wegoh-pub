import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch
from fastapi import HTTPException
from team_trip_routes import route_position, music_projection, companion_rows, result_projection, display


class TripDisplayTests(unittest.TestCase):
    def setUp(self):
        self.actor = dict(id='owner', deviceId='device', grantId='grant')
        self.context = dict(tripId='trip', roomId='room', state='active')
        self.detail = dict(cars=[dict(id='mine', isMine=True, iRide=False), dict(id='other', isMine=False, iRide=False)],
            courses=[dict(packId='course', title='실제 코스', stops=[dict(id='a',lat=37, lng=127),dict(id='b',lat=37.1,lng=127)])])

    def test_route_projection_orders_cars_on_the_same_path(self):
        route=self.detail['courses'][0]['stops']
        self.assertGreater(route_position(dict(lat=37.08,lng=127),route),route_position(dict(lat=37.02,lng=127),route))
        self.assertIsNone(route_position(dict(lat=37,lng=127),[]))

    def test_planned_trip_does_not_read_other_car_coordinates(self):
        with patch('team_trip_routes.trip_cars') as read:
            result=companion_rows(Mock(),Mock(),Mock(),dict(self.context,state='planned'),self.actor,set(),self.detail)
        self.assertEqual(result,[dict(carId='other',label='위치 공유 꺼짐')]);read.assert_not_called()

    def test_shared_positions_are_coarse_distance_only(self):
        with patch('team_trip_routes.trip_cars',return_value=('mine',[dict(carId='other',lat=37.08,lng=127)])), \
             patch('team_trip_routes.latest_location',return_value=dict(lat=37.02,lng=127)):
            result=companion_rows(Mock(),Mock(),Mock(),self.context,self.actor,{'vehicle-reports:read'},self.detail)
        self.assertEqual(result[0]['direction'],'ahead')
        self.assertGreater(result[0]['distanceMeters'],6000)
        self.assertEqual(set(result[0]),{'carId','direction','distanceMeters'})

    def test_missing_position_distinguishes_consent_from_stale_report(self):
        with patch('team_trip_routes.trip_cars', return_value=('mine', [dict(carId='other')])), \
             patch('team_trip_routes.latest_location', return_value=None), \
             patch('team_trip_routes.car_shares_location', return_value=False) as shares:
            result = companion_rows(Mock(), Mock(), Mock(), self.context, self.actor, set(), self.detail)
            self.assertEqual(result[0]['label'], '위치 공유 꺼짐')
            shares.return_value = True
            result = companion_rows(Mock(), Mock(), Mock(), self.context, self.actor, set(), self.detail)
            self.assertEqual(result[0]['label'], '최근 공유 위치 없음')

    def test_music_needs_functional_and_room_consent(self):
        service=Mock()
        auth=SimpleNamespace(room_music_service=service)
        self.assertIsNone(music_projection(auth,Mock(),self.context,self.actor,set()))
        service.snapshot.assert_not_called()
        service.snapshot.side_effect=HTTPException(403,'consent required')
        from team_trip_routes import optional
        self.assertIsNone(optional(lambda: music_projection(auth,Mock(),self.context,self.actor,{'room-music:read'})))
        service.shared_playlist.assert_not_called()

    def test_shared_playlist_and_dj_are_real_metadata(self):
        service=Mock();service.room_permission.return_value=dict(expiresAt=2000000000);service.snapshot.return_value=dict(selection=dict(ownerId='dj',name='여행 노래',currentTrackId='song',tracks=[dict(id='song',title='실제 곡')]))
        service.shared_playlist.return_value=dict(tracks=[dict(track=dict(id='song',title='실제 곡'),addedBy=dict(name='추가한 친구'))])
        result=music_projection(SimpleNamespace(room_music_service=service),Mock(),self.context,self.actor,{'room-music:read'})
        self.assertEqual(result,dict(name='여행 노래',currentTitle='실제 곡',trackCount=1,djName='추가한 친구',displayExpiresAt=2000000000))

    def test_only_recorded_completions_are_shown_without_inventing_visits_or_scores(self):
        conn=Mock();conn.execute.return_value=[('course',datetime(2026,11,9,tzinfo=timezone.utc))]
        result=result_projection(SimpleNamespace(),conn,self.context,self.actor,set(),self.detail)
        self.assertEqual(result['timeline'],[dict(id='course:course',name='실제 코스',kind='경로 완료',at='2026-11-09T00:00:00+00:00')])
        self.assertIsNone(result['visitCount']);self.assertIsNone(result['metrics'])
        self.assertNotIn('score',result)

    def test_summary_rechecks_trip_access(self):
        with patch('team_trip_routes.resolve_trip_context',side_effect=HTTPException(404,'Trip unavailable')):
            with self.assertRaises(HTTPException): display(Mock(),Mock(),Mock(),'trip',self.actor,set(),self.detail)

    def test_display_never_outlives_current_room_report_consent(self):
        from datetime import timedelta
        now=datetime.now(timezone.utc)
        expiry=now+timedelta(seconds=1)
        context=dict(self.context,members={'owner':dict(state='accepted',locationConsent=True)})
        vehicle=Mock();vehicle.room_grants.return_value=({},dict(devices={'device':dict(expiresAt=expiry.isoformat())}),None,None)
        with patch('team_trip_routes.resolve_trip_context',return_value=context), \
             patch('team_trip_routes.music_projection',return_value=None), \
             patch('team_trip_routes.companion_rows',return_value=[dict(carId='other',distanceMeters=1000,direction='ahead')]), \
             patch('team_trip_routes.latest_location',return_value=dict(capturedAt=now)), \
             patch('team_trip_routes.result_projection',return_value=dict(timeline=[],visitCount=None,metrics=None)):
            result=display(SimpleNamespace(vehicle_service=vehicle),Mock(),Mock(),'trip',self.actor,set(),self.detail)
        self.assertLessEqual(datetime.fromisoformat(result['validUntil']),expiry)

    def test_display_never_outlives_driving_consent(self):
        from datetime import timedelta
        expiry = datetime.now(timezone.utc)+timedelta(seconds=1)
        with patch('team_trip_routes.resolve_trip_context',return_value=self.context), \
             patch('team_trip_routes.music_projection',return_value=None), \
             patch('team_trip_routes.companion_rows',return_value=[]), \
             patch('team_trip_routes.result_projection',return_value=dict(timeline=[],visitCount=None,metrics={},metricsExpiresAt=expiry)):
            result = display(Mock(),Mock(),Mock(),'trip',self.actor,set(),self.detail)
        self.assertLessEqual(datetime.fromisoformat(result['validUntil']),expiry)
        self.assertNotIn('metricsExpiresAt',result)

    def test_retired_driving_metrics_are_never_read(self):
        conn=Mock();conn.execute.return_value=[]
        driving=Mock()
        result=result_projection(SimpleNamespace(driving_service=driving),conn,self.context,self.actor,{'rooms:read','rooms:interact'},self.detail)
        self.assertIsNone(result['metrics']);self.assertIsNone(result['metricsExpiresAt'])
        driving.summary.assert_not_called();driving.options.assert_not_called()

    def test_history_visits_are_only_read_with_history_permission(self):
        conn=Mock();conn.execute.return_value=[]
        history=Mock();history.saved_room_history.return_value=dict(id='history')
        history.detail.return_value=dict(visits=[dict(id='visit',place=dict(name='실제 방문 장소'),visitedAt='2026-11-09T10:00:00Z')])
        auth=SimpleNamespace(history_service=history)
        result=result_projection(auth,conn,self.context,self.actor,{'history:read'},self.detail)
        self.assertEqual(result['visitCount'],1)
        self.assertEqual(result['timeline'][0]['name'],'실제 방문 장소')
        history.reset_mock()
        self.assertIsNone(result_projection(auth,conn,self.context,self.actor,set(),self.detail)['visitCount'])
        history.detail.assert_not_called();history.saved_room_history.assert_not_called()

if __name__=='__main__':unittest.main()
