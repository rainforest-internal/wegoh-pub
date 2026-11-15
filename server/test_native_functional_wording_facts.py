"""Narrow public-registry token/character facts, never a readability approval."""
import json,re,unittest
from pathlib import Path
FIELDS=('label','purpose','dataCategories','retention','withdrawal','refusal')
INTERNAL=re.compile(r'(?<![A-Za-z0-9_])(?:claim|ACK|metadata)(?![A-Za-z0-9_])',re.I)
BASE_FIELDS=('purpose','dataCategories','retention','refusalEffect','withdrawalEffect')
def violations(rows,fields=FIELDS):
 result=[]
 for index,row in enumerate(rows):
  for key in fields:
   value=row.get(key,[]);values=value if type(value)is list else[value]
   for n,text in enumerate(values):
    if type(text)is str and INTERNAL.search(text):result.append((index,key,n))
 return result
class FunctionalWordingFactsTests(unittest.TestCase):
 def test_public_fixed_fields_have_no_reported_internal_tokens(self):
  wire=json.loads(Path(__file__).with_name('native_access_wire.json').read_text())
  self.assertEqual(violations(wire['functional']['purposeRegistry']),[], 'Fixed public wording contains an internal token; qualified meaning review remains separate.')
 def test_actual_base_policy_display_fields_are_checked(self):
  wire=json.loads(Path(__file__).with_name('native_access_wire.json').read_text())
  self.assertEqual(violations(wire['disclosureRegistry']['scopePolicies'],BASE_FIELDS),[])
 def test_identifier_route_ugc_and_partial_word_are_outside_scope(self):
  self.assertEqual(violations([dict(id='claim',route='/ACK',ugc='metadata ·',label='BLACK',purpose='unclaimed',dataCategories=['PACK'])]),[])
 def test_exact_internal_token_detection(self):
  for value in ['claim','ACK','metadata','(Claim)']:
   self.assertEqual(violations([dict(label=value)]),[(0,'label',0)])
 def test_confirmed_public_copy_may_use_middle_dot_separators(self):
  self.assertEqual(violations([dict(label='공조 · 조명 · 시트',purpose='픽업 · 공유 코스 · 드랍')]),[])
if __name__=='__main__':unittest.main()
