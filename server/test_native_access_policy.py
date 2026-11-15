"""Pure policy boundaries; no DB, network, issuer or Android fixture."""
import itertools
import unittest
from native_access_policy import (AUTHORIZATION_VERSION, MANDATORY_SCOPES, OPTIONAL_SCOPES, KNOWN_SCOPES,
    ScopeDenied, RouteDenied, authorize_route, event_resources, EventProjection)


class PolicyTests(unittest.TestCase):
    def test_01_every_scope_subset_and_exact_rest_methods(self):
        all_scopes=sorted(KNOWN_SCOPES)
        samples=[('GET','/v1/account','account:read'),('GET','/v1/packs','courses:read'),
          ('GET','/v1/studio/packs','courses:read'),('GET','/v1/packs/coast_1/versions/2147483647','courses:read'),
          ('GET','/v1/playlists','playlists:read'),('GET','/v1/playlists/'+'a'*32,'playlists:read'),
          ('GET','/v1/device/permissions','device:self:manage'),('DELETE','/v1/device','device:self:manage')]
        self.assertEqual(AUTHORIZATION_VERSION,1)
        for count in range(len(all_scopes)+1):
            for subset in itertools.combinations(all_scopes,count):
                scopes=frozenset(subset)
                for method,path,required in samples:
                    with self.subTest(scopes=subset,path=path):
                        if MANDATORY_SCOPES<=scopes and required in scopes:
                            self.assertEqual(authorize_route(AUTHORIZATION_VERSION,method,path,scopes),required)
                        else:
                            with self.assertRaises(ScopeDenied):authorize_route(AUTHORIZATION_VERSION,method,path,scopes)
    def test_02_no_prefix_coercion_or_write_expansion(self):
        for method,path in [('POST','/v1/packs'),('GET','/v1/account/'),('get','/v1/account'),
          ('GET','/v1/playlists/'+'A'*32),('GET','/v1/account?all=1'),('GET','/v1/packs/a/versions/0'),
          ('GET','/v1/packs/a/versions/01'),('GET','/v1/packs/a/versions/2147483648'),
          ('GET','/v1/packs/%2f/versions/1'),('POST','/v1/device/commands/claim'),
          ('POST','/v1/mission/progress'),('DELETE','/v1/device/other')]:
            with self.subTest(method=method,path=path):
                with self.assertRaises(RouteDenied):authorize_route(AUTHORIZATION_VERSION,method,path,KNOWN_SCOPES)
        for version in [2,True,'1',None]:
            with self.assertRaises(ScopeDenied):authorize_route(version,'GET','/v1/account',KNOWN_SCOPES)
        for scopes in [set(KNOWN_SCOPES),KNOWN_SCOPES|{'admin:all'}]:
            with self.assertRaises(ScopeDenied):authorize_route(AUTHORIZATION_VERSION,'GET','/v1/account',scopes)
    def test_03_wss_each_subset_and_unprojected_changes(self):
        for optional in [frozenset(),frozenset({'courses:read'}),frozenset({'playlists:read'}),OPTIONAL_SCOPES]:
            scopes=MANDATORY_SCOPES|optional
            expected=['devices']+(['courses'] if 'courses:read' in optional else [])+(['playlists'] if 'playlists:read' in optional else [])
            self.assertEqual(event_resources(AUTHORIZATION_VERSION,'GET','/v1/events',scopes),tuple(sorted(expected)))
        for scopes in [frozenset(),frozenset({'account:read'}),frozenset({'device:self:manage'}),OPTIONAL_SCOPES]:
            with self.assertRaises(ScopeDenied):event_resources(AUTHORIZATION_VERSION,'GET','/v1/events',scopes)
        p=EventProjection(MANDATORY_SCOPES,'a'*16,'b'*32)
        self.assertEqual(p.snapshot(),dict(type='snapshot',epoch='a'*16,seq=0,resources=['devices']))
        self.assertIsNone(p.changed(frozenset({'courses','playlists'})))
        self.assertIsNone(p.changed(frozenset({'devices'}),device_id='c'*32))
        self.assertEqual(p.heartbeat(),dict(type='heartbeat',epoch='a'*16,seq=0))
        self.assertEqual(p.changed(frozenset({'devices'}),device_id='b'*32),dict(type='invalidate',epoch='a'*16,seq=1,resources=['devices']))
    def test_04_wss_exact_fields_and_source_payload_rejection(self):
        p=EventProjection(KNOWN_SCOPES,'a'*16,'b'*32)
        frame=p.changed(frozenset({'devices','playlists','courses'}),device_id='b'*32)
        self.assertEqual(set(frame),{'type','epoch','seq','resources'})
        self.assertEqual(frame['resources'],['courses','devices','playlists'])
        for invalid in [{'courses':'private title'},frozenset({'history'}),frozenset({'vehicle'})]:
            with self.assertRaises(ValueError):p.changed(invalid)
        self.assertEqual(p.seq,1)

if __name__=='__main__':unittest.main()
