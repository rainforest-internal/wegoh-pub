from concurrent.futures import ThreadPoolExecutor
import inspect
import threading
import unittest
from unittest.mock import patch

from fastapi import Request
import psycopg

import test_iphone_trip_history as fixture
from team_rooms import TeamRooms


class IPhoneSocialLockOrderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.IPhoneTripHistoryTests.setUpClass.__func__(cls)

    def setUp(self):
        self.history = fixture.IPhoneTripHistoryTests()
        self.history.setUp()
        self.addCleanup(self.history.doCleanups)
        self.history.complete()
        self.h = self.history.h
        self.planned = self.h.create()

    @staticmethod
    def request_path():
        frame = inspect.currentframe()
        try:
            while frame is not None:
                request = frame.f_locals.get('request')
                if isinstance(request, Request):
                    return request.url.path
                frame = frame.f_back
        finally:
            del frame

    def race(self, path, data, expected):
        h = self.h
        session = h.phone.api.module.TEAM_AUTH.iphone_sessions
        authenticate, graph = session.authenticate, TeamRooms.graph_lock
        editor_path = '/v1/iphone/trips/' + self.planned
        writer_token = threading.Event()
        writer_graph_first = threading.Event()
        editor_attempted = threading.Event()
        editor_graph = threading.Event()
        pids = {}
        database_errors = []

        def token(request, *args, **kwargs):
            try:
                result = authenticate(request, *args, **kwargs)
            except psycopg.Error as error:
                database_errors.append(error.sqlstate)
                raise
            if request.url.path == path and kwargs.get('lock') and not writer_token.is_set():
                pids['writer'] = kwargs['connection'].info.backend_pid
                writer_token.set()
                ready = editor_attempted if writer_graph_first.is_set() else editor_graph
                self.assertTrue(ready.wait(4), 'The second transaction did not reach its lock')
            return result

        def shared(conn):
            current = self.request_path()
            if current == path and not writer_token.is_set():
                writer_graph_first.set()
            if current == editor_path:
                pids['editor'] = conn.info.backend_pid
                editor_attempted.set()
            try:
                value = graph(conn)
            except psycopg.Error as error:
                database_errors.append(error.sqlstate)
                raise
            if current == editor_path:
                editor_graph.set()
            return value

        edit = dict(title='Concurrent edit', description='Same session, separate trip', startDate=None, endDate=None)
        with patch.object(session, 'authenticate', side_effect=token), patch.object(TeamRooms, 'graph_lock', side_effect=shared):
            with ThreadPoolExecutor(max_workers=2) as pool:
                writer = pool.submit(h.phone.iphone, path, data, 'POST' if '/stars/' not in path else 'PUT',
                                     token=h.alice['accessToken'])
                self.assertTrue(writer_token.wait(4), 'The first transaction did not lock its session')
                editor = pool.submit(h.phone.iphone, editor_path, edit, 'PATCH', token=h.alice['accessToken'])
                results = writer.result(timeout=10), editor.result(timeout=10)
        self.assertEqual(database_errors, [], 'Concurrent PostgreSQL transaction errors')
        self.assertEqual(results[0][0], expected, results[0][2])
        self.assertEqual(results[1][0], 200, results[1][2])
        self.assertNotEqual(pids['writer'], pids['editor'])

    def test_history_save_and_trip_edit_complete_on_two_connections(self):
        self.race('/v1/iphone/trips/' + self.history.trip + '/history', dict(title='Concurrent history'), 201)

    def test_trip_draft_and_trip_edit_complete_on_two_connections(self):
        options = self.history.options()
        self.race('/v1/iphone/trips/' + self.history.trip + '/course-drafts',
                  dict(selectionIds=[options['places'][0]['id']], selectionFingerprint=options['selectionFingerprint']), 201)

    def test_course_star_and_trip_edit_complete_on_two_connections(self):
        pack = self.history.packs[0]
        self.race(f"/v1/iphone/courses/stars/{pack['id']}/versions/1", {}, 200)

    def test_public_copy_and_trip_edit_complete_on_two_connections(self):
        pack = self.history.packs[0]
        self.race(f"/v1/iphone/courses/public/{pack['id']}/versions/1/copy", {}, 201)

    def test_publication_and_location_read_take_the_graph_before_session_revalidation(self):
        h = self.h
        sessions = h.phone.api.module.TEAM_AUTH.iphone_sessions
        authenticate, graph = sessions.authenticate, TeamRooms.graph_lock
        h.checked(h.call('/' + self.planned + '/start', dict(revision=h.detail(self.planned)['revision']), 'POST'))
        operations = (
            ('/v1/iphone/courses', dict(pack=h.phone.api.pack(), rightsConfirmed=True), 'POST', 201),
            ('/v1/iphone/trips/' + self.planned + '/locations', None, 'GET', 200),
        )
        for path, data, method, status in operations:
            with self.subTest(path=path):
                order = []
                def token(request, *args, **kwargs):
                    result = authenticate(request, *args, **kwargs)
                    if request.url.path == path and kwargs.get('connection') is not None:
                        order.append('session')
                    return result
                def shared(conn):
                    if self.request_path() == path:
                        order.append('graph')
                    return graph(conn)
                with patch.object(sessions, 'authenticate', side_effect=token), patch.object(TeamRooms, 'graph_lock', side_effect=shared):
                    result = h.phone.iphone(path, data, method, token=h.alice['accessToken'])
                self.assertEqual(result[0], status, result[2])
                self.assertEqual(order[:2], ['graph', 'session'])
