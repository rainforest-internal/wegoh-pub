"""R7 exact native policy and wire parity without HTTP/database fixtures."""
import json
from pathlib import Path
import unittest

from native_access_policy import (AUTHORIZATION_VERSION, KNOWN_SCOPES, MANDATORY_SCOPES,
    ROUTES, RouteDenied, ScopeDenied, authorize_route)


class NativeCourseOriginalPolicyTests(unittest.TestCase):
    def test_exact_get_requires_courses_and_both_mandatory_scopes(self):
        path='/v1/studio/packs/coast_1/versions/2147483647'
        self.assertEqual(authorize_route(AUTHORIZATION_VERSION,'GET',path,KNOWN_SCOPES),'courses:read')
        for scopes in [MANDATORY_SCOPES,KNOWN_SCOPES-{'account:read'},KNOWN_SCOPES-{'device:self:manage'}]:
            with self.subTest(scopes=scopes),self.assertRaises(ScopeDenied):
                authorize_route(AUTHORIZATION_VERSION,'GET',path,scopes)
        for method in ['POST','PUT','DELETE','PATCH','HEAD']:
            with self.subTest(method=method),self.assertRaises(RouteDenied):
                authorize_route(AUTHORIZATION_VERSION,method,path,KNOWN_SCOPES)

    def test_original_id_and_version_rules_equal_public_download(self):
        tails=['a/versions/1','a'*80+'/versions/2147483647','a-b_2/versions/42',
               'A/versions/1','_a/versions/1','a'*81+'/versions/1',
               'a/versions/0','a/versions/01','a/versions/2147483648','a/versions/99999999999',
               'a/versions/1/','a/versions/1?all=1','a/versions/1#x','a/versions/1/reuse-permission',
               'a%2fb/versions/1','a/../b/versions/1']
        for tail in tails:
            outcomes=[]
            for prefix in ['/v1/packs/','/v1/studio/packs/']:
                try:outcomes.append(authorize_route(AUTHORIZATION_VERSION,'GET',prefix+tail,KNOWN_SCOPES))
                except RouteDenied:outcomes.append('denied')
            with self.subTest(tail=tail):self.assertEqual(*outcomes)

    def test_wire_matches_the_exact_route_and_immediate_publication_projection(self):
        wire=json.loads(Path(__file__).with_name('native_access_wire.json').read_text())['courseOriginalRead']
        route=next(rule for rule in ROUTES if rule.template==wire['path'])
        self.assertEqual((wire['method'],wire['pattern'],wire['scope']),
                         (route.method,route.pattern,route.scope))
        self.assertTrue(wire['ownerOnly'])
        self.assertNotIn('allowedReviewStates', wire)
        self.assertEqual(wire['publicationPolicy'], 'immediate-with-post-publication-restrictions')
        self.assertEqual(wire['responseFields'],['schemaVersion','id','version','title','author','description','stops'])
        self.assertEqual((wire['versionMaximum'],wire['maximumBytes'],wire['minimumStops'],wire['maximumStops']),
                         (2147483647,262144,1,3))


if __name__=='__main__':unittest.main()
