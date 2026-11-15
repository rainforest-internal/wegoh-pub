"""Functional contract negative boundaries without personal/operating state."""
import json,unittest
from native_functional_policy import *
class FunctionalPolicyTests(unittest.TestCase):
 def body(self):return dict(authorizationVersion=1,grantId='a'*32,revision=0,approvedPurposes=['rooms:read'],functionalDisclosureVersion=WIRE['disclosureVersion'],functionalDisclosureSha256=WIRE['disclosureSha256'])
 def test_consent_closed_and_explicit(self):
  self.assertEqual(decode_consent(self.body())['approvedPurposes'],['rooms:read'])
  for field in ['role','token','ownerId']:
   with self.assertRaises(FunctionalError):decode_consent(dict(self.body(),**{field:'x'}))
 def test_bad_version_bool_revision_duplicate_json(self):
  for change in [dict(authorizationVersion=True),dict(revision=True),dict(revision=-1),dict(approvedPurposes=['rooms:read','rooms:read']),dict(approvedPurposes=['unknown:read'])]:
   with self.assertRaises(FunctionalError):decode_consent(dict(self.body(),**change))
  with self.assertRaises(FunctionalError):decode_consent(b'{"revision":0,"revision":1}')
 def test_disclosure_is_exact(self):
  with self.assertRaises(FunctionalError):decode_consent(dict(self.body(),functionalDisclosureSha256='0'*64))
 def test_previous_disclosure_only_restores_stored_settings(self):
  old=WIRE['previousDisclosures'][0]
  value=dict(self.body(),approvedPurposes=[],functionalDisclosureVersion=old['version'],functionalDisclosureSha256=old['sha256'])
  self.assertEqual(decode_stored_consent(value)['approvedPurposes'],[])
  with self.assertRaises(FunctionalError):decode_consent(value)
  with self.assertRaises(FunctionalError):decode_stored_consent(dict(value,functionalDisclosureVersion=True))
 def test_exact_routes_and_no_base_scope_inference(self):
  self.assertTrue(authorize('GET','/v1/social/rooms/'+'a'*32,frozenset({'rooms:read'})))
  for method,path in [('POST','/v1/social/rooms/'+'a'*32),('GET','/v2/social/rooms/'+'a'*32),('GET','/v1/social/rooms/'+'a'*32+'/secret')]:
   with self.assertRaises(FunctionalError):authorize(method,path,frozenset({'rooms:read'}))
  with self.assertRaises(FunctionalError):authorize('GET','/v1/social/rooms/'+'a'*32,frozenset())
 def test_write_dependency_is_not_inferred(self):
  with self.assertRaises(FunctionalError):authorize('POST','/v1/social/friends/requests',frozenset({'friends:manage'}))
  self.assertTrue(authorize('POST','/v1/social/friends/requests',frozenset({'friends:manage','friends:read'})))
 def test_overview_is_partial_any_purpose(self):self.assertTrue(authorize('GET','/v1/social/overview',frozenset({'rooms:read'})))
 def test_snapshot_no_secret_extra(self):
  snapshot=dict(self.body(),deviceId='b'*32,expiresAt=1700000000);self.assertEqual(validate_snapshot(snapshot),snapshot)
  with self.assertRaises(FunctionalError):validate_snapshot(dict(snapshot,accessToken='secret'))
 def test_real_account_and_invite_identifiers(self):
  friend=frozenset({'friends:manage','friends:read'})
  self.assertTrue(authorize('DELETE','/v1/social/friends/team-'+'a'*40,friend))
  self.assertTrue(authorize('POST','/v1/social/friends/requests/team-'+'a'*40+'/respond',friend))
  self.assertTrue(authorize('GET','/v1/social/invites/ABCD2345',frozenset({'rooms:read'})))
  for verb,path,allowed in [('DELETE','/v1/social/friends/'+'a'*32,friend),('DELETE','/v1/social/friends/team-'+'a'*40+'/extra',friend),('GET','/v1/social/invites/ABCI2345',frozenset({'rooms:read'})),('GET','/v1/social/invites/'+'a'*32,frozenset({'rooms:read'}))]:
   with self.assertRaises(FunctionalError):authorize(verb,path,allowed)
if __name__=='__main__' :unittest.main()
