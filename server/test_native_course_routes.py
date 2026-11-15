import unittest
from unittest.mock import patch
from fastapi import HTTPException
import psycopg

from native_course_routes import checked_points
from native_access_policy import KNOWN_SCOPES, RouteDenied, ScopeDenied, authorize_route
from route_preview import MockRoutePreview, RoutePreview
import test_team_auth as fixture


class NativeCourseRoutePolicyTests(unittest.TestCase):
    def test_exact_route_and_bound_revision_order(self):
        path = '/v1/native/courses/coast/versions/2147483647/route-preview'
        self.assertEqual(authorize_route(1, 'POST', path, KNOWN_SCOPES), 'courses:read')
        with self.assertRaises(ScopeDenied):
            authorize_route(1, 'POST', path, KNOWN_SCOPES - {'courses:read'})
        for method, value in [('GET', path), ('POST', path + '/'),
                              ('POST', path.replace('2147483647', '2147483648'))]:
            with self.assertRaises(RouteDenied):
                authorize_route(1, method, value, KNOWN_SCOPES)
        points = [dict(lat=37.4, lng=127), dict(lat=37.5, lng=127.1)]
        detail = dict(checksum='a'*64, pack=dict(stops=[dict(latitude=p['lat'], longitude=p['lng']) for p in points]))
        self.assertEqual(checked_points(dict(checksum='a'*64, points=points), detail), points)
        for value in [dict(checksum='b'*64, points=points), dict(checksum='a'*64, points=points[::-1]),
                      dict(checksum='a'*64, points=points, origin=points[0])]:
            with self.assertRaises(HTTPException):
                checked_points(value, detail)


class NativeCourseRouteHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.routes = RoutePreview(MockRoutePreview())
        with patch('studio.RoutePreview.from_environment', return_value=cls.routes):
            fixture.TeamTests.setUpClass()

    @classmethod
    def tearDownClass(cls):
        fixture.TeamTests.tearDownClass()

    def setUp(self):
        self.api = fixture.TeamTests('test_01_jwt_verification_and_exact_hosts')
        self.api.setUp()
        self.session = self.api.login()
        self.bob = self.api.login('bob')
        self.pack = self.api.pack()
        self.pack['stops'].append(dict(self.pack['stops'][0], id='second', latitude=37.6, longitude=127.1))
        status, _, published = self.api.publish(self.pack, self.bob, who='bob')
        self.assertEqual(status, 201, published)
        self.body = dict(checksum=published['checksum'],
                         points=[dict(lat=stop['latitude'], lng=stop['longitude']) for stop in self.pack['stops']])
        _, _, self.credential = self.api.pair(self.session)
        self.certificate = self.api._native_fingerprint
        self.path = f"/v1/native/courses/{self.pack['id']}/versions/1/route-preview"
        self.routes._attempts.clear()

    def call(self, path=None, body=None):
        return self.api.native(path or self.path, self.body if body is None else body, 'POST',
            token=self.credential['accessToken'], certificate=self.certificate)

    def test_current_native_course_and_exact_coordinates_only(self):
        status, headers, result = self.call()
        self.assertEqual(status, 200, result)
        self.assertEqual(result['path'], [[p['lat'], p['lng']] for p in self.body['points']])
        self.assertIn('no-store', headers['cache-control'])
        self.assertEqual(self.call(body=dict(self.body, checksum='0'*64))[0], 409)
        self.assertEqual(self.call(body=dict(self.body, points=self.body['points'][::-1]))[0], 409)
        self.assertEqual(self.api.call(self.path, self.body, 'POST', session=self.session)[0], 404)
        self.assertEqual(self.call(path=self.path.replace(self.pack['id'], 'private-missing'))[0], 404)

    def test_block_before_or_during_provider_denies_result(self):
        original = self.routes.provider
        api, session, bob = self.api, self.session, self.bob

        class BlockingProvider:
            def preview(self, origin, points, timeout):
                self_result = original.preview(origin, points, timeout)
                blocked = api.call('/v1/social/blocks', dict(targetId=bob['user']['id']), 'POST', session=session)
                if blocked[0] != 201:
                    raise AssertionError(blocked[0])
                return self_result

        with patch.object(self.routes, 'provider', BlockingProvider()):
            self.assertEqual(self.call()[0], 404)
        with patch.object(self.routes, 'provider') as provider:
            self.assertEqual(self.call()[0], 404)
            provider.preview.assert_not_called()

    def test_single_place_has_no_road_and_deleted_version_cannot_return_result(self):
        one = self.api.pack()
        status, _, published = self.api.publish(one, self.bob, who='bob')
        self.assertEqual(status, 201)
        path = self.path.replace(self.pack['id'], one['id'])
        body = dict(checksum=published['checksum'], points=[dict(lat=one['stops'][0]['latitude'], lng=one['stops'][0]['longitude'])])
        with patch.object(self.routes, 'provider') as provider:
            response = self.call(path, body)
            self.assertEqual(response[0], 200, response[2])
            self.assertEqual(response[2], dict(distanceMeters=0, durationSeconds=0, path=[]))
            provider.preview.assert_not_called()
        original, api, pack = self.routes.provider, self.api, self.pack

        class DeletingProvider:
            def preview(self, origin, points, timeout):
                value = original.preview(origin, points, timeout)
                with psycopg.connect(api.dsn) as conn:
                    conn.execute('DELETE FROM pack_versions WHERE pack_id=%s AND version=1', (pack['id'],))
                return value

        with patch.object(self.routes, 'provider', DeletingProvider()):
            self.assertEqual(self.call()[0], 404)


if __name__ == '__main__':
    unittest.main()
