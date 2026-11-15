import json
import os
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from fastapi import HTTPException, Request, Response
from team_room_music import TeamRoomMusic
from voice_controls import controls


class VoiceControlBodyRegressionTests(unittest.IsolatedAsyncioTestCase):
    def request(self, payload):
        async def receive():
            return dict(type='http.request', body=payload, more_body=False)
        return Request(dict(type='http', method='POST', path='/', headers=[]), receive)

    async def test_valid_json_reaches_closed_room_authorization(self):
        for trip_context in (False, True):
            for name, body in (('filter_speaker', dict(muted=True)),
                               ('report', dict(speakerId='speaker', leaseId='a'*32, reason='privacy'))):
                with self.subTest(trip_context=trip_context, handler=name):
                    auth=MagicMock();auth.browser.return_value=dict(id='viewer')
                    rooms=MagicMock();rooms.access.side_effect=HTTPException(404)
                    service=SimpleNamespace(auth=auth,rooms=rooms,recent_floors={})
                    endpoint=next(route.endpoint for route in controls(service,trip_context=trip_context).routes if route.endpoint.__name__==name)
                    args=dict(room='context',request=self.request(json.dumps(body).encode()),response=Response())
                    if name=='filter_speaker':args['speaker']='speaker'
                    with patch('voice_controls.psycopg.connect'), patch('voice_controls.resolve_trip_context',return_value=dict(roomId='room')):
                        with self.assertRaises(HTTPException) as error:
                            await endpoint(**args)
                    self.assertEqual(error.exception.status_code,404)
                    rooms.access.assert_called_once()

    async def test_duplicate_json_fields_still_rejected_before_database_access(self):
        auth=MagicMock();auth.browser.return_value=dict(id='viewer')
        service=SimpleNamespace(auth=auth,rooms=MagicMock())
        endpoint=next(route.endpoint for route in controls(service).routes if route.endpoint.__name__=='filter_speaker')
        with patch('voice_controls.psycopg.connect') as connect:
            with self.assertRaises(HTTPException) as error:
                await endpoint('room','speaker',self.request(b'{"muted":true,"muted":false}'),Response())
        self.assertEqual(error.exception.status_code,400)
        connect.assert_not_called()


class RoomPlaylistBlockRegressionTests(unittest.TestCase):
    def test_legacy_owner_keeps_content_free_deletion_reference_after_block(self):
        auth=SimpleNamespace(dsn='',enabled=True,content_service=MagicMock())
        service=TeamRoomMusic(auth,MagicMock())
        conn=MagicMock()
        for current_join in (None,'previous-join'):
            conn.execute.return_value.fetchall.return_value=[('track','blocked',b'protected','previous-join',current_join)]
            with self.subTest(current_join=current_join), patch('team_room_music.blocked',return_value=True):
                value=service.shared_playlist(conn,'room','owner',dict(ownerId='owner'))
                self.assertEqual(value['tracks'],[dict(id='track',track=None,artist=None,addedBy=None,canDelete=True,review=None)])
                self.assertEqual(service.shared_playlist(conn,'room','owner',dict(ownerId='owner'),trip_context=True)['tracks'],[])
        auth.content_service.shared.assert_not_called()


class MediaAuthorityFixtureRegressionTests(unittest.TestCase):
    def test_standalone_fixture_explicitly_enables_and_restores_voice(self):
        from test_team_trips import TripTests
        from test_trip_merge_music_authority import TripMediaAuthorityIntegrationTests
        captured=[]
        with patch.dict(os.environ,{'WEGOH_VOICE_ENABLED':'0'}), \
                patch.object(TripTests,'setUpClass',side_effect=lambda:captured.append(os.environ.get('WEGOH_VOICE_ENABLED'))), \
                patch.object(TripTests,'tearDownClass'):
            try:
                TripMediaAuthorityIntegrationTests.setUpClass()
                self.assertEqual(captured,['1'])
            finally:
                TripMediaAuthorityIntegrationTests.doClassCleanups()
            self.assertEqual(os.environ['WEGOH_VOICE_ENABLED'],'0')


if __name__=='__main__':unittest.main()
