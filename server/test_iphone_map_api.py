"""iPhone map API with real account sessions and synthetic map providers."""
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

import psycopg

from place_search import MockPlaceSearch, PlaceSearch
from route_preview import MockRoutePreview, RoutePreview
import test_iphone_session as account


SEARCH_QUERY = '?' + urlencode({'q': '가상 장소'})
SEARCH = '/v1/iphone/places/search' + SEARCH_QUERY
PREVIEW = '/v1/iphone/routes/preview'
ROUTE = {'origin': {'lat': 37.4, 'lng': 126.9},
         'points': [{'lat': 37.5, 'lng': 127.0}, {'lat': 37.6, 'lng': 127.1}]}


class IphoneMapApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.addClassCleanup(account.IphoneSessionTests.doClassCleanups)
        cls.search = PlaceSearch(MockPlaceSearch(), limit=2)
        route_preview = RoutePreview(MockRoutePreview())
        with patch('studio.PlaceSearch.from_environment', return_value=cls.search), \
                patch('studio.RoutePreview.from_environment', return_value=route_preview):
            account.IphoneSessionTests.setUpClass()

    def setUp(self):
        self.session = account.IphoneSessionTests('test_login_bootstraps_same_account_and_restores_then_logs_out')
        self.session.setUp()
        self.search._attempts.clear()

    def test_map_routes_require_current_iphone_session_and_share_web_account_budget(self):
        token = self.session.login()['accessToken']
        web = self.session.api.login()

        self.session.assert_error(self.session.iphone(SEARCH), 401, 'IPHONE_SESSION_REQUIRED')
        self.assertEqual(self.session.api.call(SEARCH, session=web, bearer=token)[0], 404)
        self.assertEqual(self.session.api.native(SEARCH, token=token)[0], 404)
        self.assertEqual(self.session.iphone('/v1/places/search' + SEARCH_QUERY, token=token)[0], 404)

        status, headers, places = self.session.iphone(SEARCH, token=token)
        self.assertEqual((status, places['places'][0]['name']), (200, '가상 검색 장소'))
        self.assertIn('no-store', self.session.header(headers, 'cache-control'))
        status, headers, preview = self.session.iphone(PREVIEW, ROUTE, 'POST', token=token)
        self.assertEqual((status, preview), (200, {'distanceMeters': 12000, 'durationSeconds': 1800,
            'path': [[37.4, 126.9], [37.5, 127.0], [37.6, 127.1]]}))
        self.assertIn('no-store', self.session.header(headers, 'cache-control'))

        self.assertEqual(self.session.api.call('/v1/places/search' + SEARCH_QUERY, session=web)[0], 200)
        limited = self.session.iphone(SEARCH, token=token)
        self.session.assert_error(limited, 429, 'PLACE_SEARCH_RATE_LIMITED')
        self.assertEqual(self.session.header(limited[1], 'retry-after'), '60')

        with psycopg.connect(self.session.api.dsn) as conn:
            conn.execute('UPDATE iphone_sessions SET scopes=%s', (['account:read'],))
        self.session.assert_error(self.session.iphone(PREVIEW, ROUTE, 'POST', token=token),
                                  403, 'IPHONE_SCOPE_DENIED')
        self.assertEqual(self.session.iphone(account.SESSION, method='DELETE', token=token)[0], 204)
        self.session.assert_error(self.session.iphone(SEARCH, token=token), 401, 'IPHONE_SESSION_REVOKED')
