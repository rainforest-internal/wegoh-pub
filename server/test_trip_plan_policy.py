import asyncio
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from fastapi import HTTPException, Request, Response
from team_trip_plan import TeamTripPlan, trip_dates, place_fields
from team_trip_routes import TeamTripRoutes
from team_trips import TeamTrips
from api_doc_trip_plan import NATIVE, OPS
from native_functional_policy import authorize, is_functional_route, FunctionalError, WIRE
from ops.live import migration_pipeline


class TripPlanPolicyTests(unittest.TestCase):
    def test_dates_and_place_boundaries(self):
        self.assertEqual(trip_dates({}), dict(startDate=None, endDate=None))
        self.assertEqual(trip_dates(dict(startDate='2028-02-29', endDate='2028-03-30'))['endDate'], '2028-03-30')
        self.assertEqual(trip_dates(dict(endDate=None), dict(startDate='2026-01-01', endDate='2026-01-02')),
            dict(startDate='2026-01-01', endDate=None))
        for data in (dict(startDate='2026-02-29'), dict(startDate='20261108'), dict(startDate='2026-1-08'),
                dict(startDate=True), dict(startDate='2026-01-01', endDate='2026-02-01'),
                dict(startDate='2026-01-02', endDate='2026-01-01')):
            with self.subTest(data=data), self.assertRaises(HTTPException) as error:
                trip_dates(data)
            self.assertEqual(error.exception.detail, 'Invalid trip dates')
        place = dict(kind='pickup', name=' 픽업 ', lat=90, lng=-180)
        self.assertEqual(place_fields(place)['name'], '픽업')
        for update in (dict(kind=[]), dict(name=''), dict(name='x'*41), dict(name='a\n'), dict(lat=True),
                dict(lng=181), dict(lat=float('nan')), dict(extra=1)):
            with self.subTest(update=update), self.assertRaises(HTTPException):
                place_fields(dict(place, **update))

    def test_route_shape_duplicates_and_merged_drop(self):
        course = dict(type='course', courseId='pack-1', ref='stop-1', dropRef='a'*32)
        self.assertEqual(TeamTripPlan.order_fields([course]), [course])
        for items in (None, {}, [dict(type=[])], [dict(type='course', ref='stop-1')],
                [dict(course, dropRef=None)], [dict(course, unknown=True)], [course, course],
                [course, dict(type='drop', ref='a'*32)], [dict(type='pickup', ref='A'*32)],
                [dict(type='pickup', ref='a'*32)] * 51):
            with self.subTest(items=items), self.assertRaises(HTTPException):
                TeamTripPlan.order_fields(items)

    def test_places_reject_huge_integer_coordinates(self):
        for key in ('lat', 'lng'):
            for value in (10**400, -(10**400)):
                with self.subTest(key=key, positive=value > 0):
                    data = dict(kind='pickup', name='픽업', lat=0, lng=0)
                    data[key] = value
                    with self.assertRaises(HTTPException) as error:
                        place_fields(data)
                    self.assertEqual(error.exception.status_code, 400)
                    self.assertEqual(error.exception.detail, 'Invalid car place')

    def test_all_mounted_native_routes_are_exact_and_have_only_current_purposes(self):
        auth = SimpleNamespace(enabled=True, dsn='synthetic', trip_signal_contexts=object(), trip_places_service=object())
        auth.trip_service = TeamTrips(auth)
        mounted = {(method.lower(), route.path) for router in (auth.trip_service.router(), TeamTripRoutes(auth).router())
            for route in router.routes for method in route.methods}
        self.assertTrue(set(OPS) <= mounted)
        from api_doc_trip_hand_raise import NATIVE as HAND_RAISE_NATIVE
        from api_doc_trip_driving_versus import OPS as DRIVING_VERSUS
        from api_doc_trip_merge import NATIVE_VOICE_PARTICIPATION
        voice = {(method, NATIVE_VOICE_PARTICIPATION) for method in ('get', 'patch')}
        native = NATIVE | HAND_RAISE_NATIVE | set(DRIVING_VERSUS)
        self.assertEqual({key for key in mounted if key[1].startswith('/v1/native/trips/')}, native | voice)
        values = dict(id='a'*32, carId='b'*32, placeId='c'*32, inviteId='d'*32,
            accountId='team-'+'e'*40, packId='my-course')
        for method, template in native:
            path = template.format(**values)
            rule = next(row for row in WIRE['nativeRoutes'] if row['method'].lower() == method and row['path'] == template)
            purposes = frozenset(rule['all'])
            with self.subTest(method=method, path=path):
                self.assertTrue(authorize(method.upper(), path, purposes))
                self.assertFalse(is_functional_route(method.upper(), path+'/extra'))
                self.assertFalse(is_functional_route(method.upper(), path.replace('a'*32, 'A'*32)))
                with self.assertRaises(FunctionalError):
                    authorize(method.upper(), path, frozenset())
        root = '/v1/native/trips/'+'a'*32
        for method, suffix in [('PUT','/cars/'+'b'*32+'/places/'+'c'*32+'/select'),
                ('POST','/cars/'+'b'*32+'/ride-invites/'+'d'*32+'/respond'), ('POST','/cancel')]:
            self.assertFalse(is_functional_route(method, root+suffix))
        self.assertFalse(is_functional_route('POST', '/v1/native/trip-links/preview'))
        self.assertEqual(len(WIRE['nativeRoutes']), len({(row['method'],row['path']) for row in WIRE['nativeRoutes']}))

    def test_new_writes_reject_extra_duplicate_and_oversize_bodies_before_db(self):
        account = 'team-'+'a'*40
        auth = SimpleNamespace(enabled=True, dsn='synthetic', trip_signal_contexts=object(), trip_places_service=object(),
            browser=MagicMock(return_value=dict(id=account)), rate=MagicMock())
        auth.trip_service = TeamTrips(auth)
        for router in (auth.trip_service.router(), TeamTripRoutes(auth).router()):
            for route in router.routes:
                if not any((method.lower(),route.path) in OPS for method in route.methods) or 'GET' in route.methods:
                    continue
                for raw, status in [(b'{"unexpected":true}',400), (b'{"accept":true,"accept":false}',400), (b' '*4097,413)]:
                    async def receive():
                        return dict(type='http.request', body=raw, more_body=False)
                    request = Request(dict(type='http', method=next(iter(route.methods)), path=route.path, headers=[]), receive)
                    if route.path.startswith('/v1/native/'):
                        request.state.device_identity = dict(id=account)
                    args = {name:'a'*32 for name in route.param_convertors}
                    with self.subTest(path=route.path, raw=raw[:30]), patch('psycopg.connect', side_effect=AssertionError('No database allowed')), \
                            patch('team_trip_routes.request_actor', return_value=dict(id=account)), \
                            patch('team_trips.request_actor', return_value=dict(id=account)):
                        with self.assertRaises(HTTPException) as error:
                            asyncio.run(route.endpoint(**args, request=request, response=Response()))
                        self.assertEqual(error.exception.status_code, status)

    def test_migration_manifest_and_append_only_schema(self):
        root = Path(__file__).parent
        manifest = migration_pipeline.load_manifest(root)
        states = {state['version']: state for state in manifest['states']}
        step = next(step for step in manifest['migrations'] if step['id'] == 'trip_plan_v1')
        self.assertEqual((step['from'],step['to']), ('trip_room_merge_v1','trip_plan_v1'))
        raw = (root/step['path']).read_bytes()
        schema = (root/'schema.sql').read_bytes()
        self.assertEqual(schema.count(raw), 1)
        archived=subprocess.check_output(['git','show','f175cda782199c6c6ab4e87374e73673e368a837:server/schema.sql'],cwd=root.parent)
        self.assertEqual(archived.count(raw),1)
        historical = archived[:archived.index(raw) + len(raw)]
        old = historical[:-len(raw)-1]
        self.assertEqual(migration_pipeline.digest(old), states[step['from']]['schemaFiles']['server/schema.sql'])
        self.assertEqual(migration_pipeline.digest(historical), states[step['to']]['schemaFiles']['server/schema.sql'])
        self.assertEqual(migration_pipeline.digest(schema),
            states[manifest['targetVersion']]['schemaFiles']['server/schema.sql'])
        self.assertNotRegex(raw.decode(), r'(?im)^\s*(DROP|DELETE|UPDATE)\b')
        self.assertNotRegex(raw.decode(), r'(?m)^\s+(name|lat|lng)\s')


if __name__ == '__main__':
    unittest.main()
