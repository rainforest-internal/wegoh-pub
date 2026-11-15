"""Database-free production action, argument and ACK contract tests."""
import unittest
from device_command_registry import DRIVER_AREA, ProductionCommandRegistry, SEATS

CONTRACTS = (
 ('hvac.temperature','설정 온도','hvac-celsius','TARGET_CELSIUS',dict(seat='ROW_1_RIGHT',value=22.5)),
 ('hvac.fan','풍량','hvac-fan','FAN_LEVEL',dict(seat='ROW_1_RIGHT',value=2)),
 ('hvac.power','공조 전원','seat-switch','GLOBAL_POWER',dict(seat='ROW_1_RIGHT',value=True)),
 ('hvac.ac','에어컨','seat-switch','AC',dict(seat='ROW_1_RIGHT',value=True)),
 ('hvac.air_cleaner','공기청정','seat-switch','AIR_CLEANER',dict(seat='ROW_1_RIGHT',value=True)),
 ('seat.heat','시트 열선','seat-level','SEAT_HEAT',dict(seat='ROW_1_RIGHT',value=1)),
 ('seat.ventilation','시트 통풍','seat-level','SEAT_VENTILATION',dict(seat='ROW_1_RIGHT',value=1)),
 ('window.position','창문 열림','window-position','WINDOW_POSITION',dict(window='ROW_1_RIGHT',value=1)),
 ('light.cabin','실내등','switch','CABIN_LIGHT',dict(value=True)),
 ('light.reading','독서등','seat-switch','READING_LIGHT',dict(seat='ROW_1_RIGHT',value=True)),
 ('light.ambient','무드등','seat-switch','AMBIENT_LIGHT',dict(seat='ROW_1_RIGHT',value=True)),
)

class RegistryContractTests(unittest.TestCase):
 def setUp(self):self.registry=ProductionCommandRegistry()

 def test_exact_eleven_action_contracts_and_revision(self):
  self.assertEqual(len(self.registry.describe()),11)
  self.assertEqual(self.registry.describe(),[dict(id=row[0],revision=1)for row in CONTRACTS])
  for identifier,label,kind,prop,arguments in CONTRACTS:
   with self.subTest(action=identifier):
    action=self.registry.lookup(identifier,1)
    self.assertEqual((action.display_label,action.argument_kind,action.property_name),(label,kind,prop))
    self.assertTrue(action.validate_arguments(arguments))
    for revision in (True,False,0,2,1.0,'1',None):self.assertIsNone(self.registry.lookup(identifier,revision))
  for identifier in ('door.lock','window.lock','roof.position','light.high_beam','wiper','ev.charging','glove_box','smart_glass','light.ambient.color'):
   self.assertIsNone(self.registry.lookup(identifier,1))

 def test_argument_types_bounds_and_exact_keys(self):
  valid={'hvac-celsius':(0,22,22.5,50),'hvac-fan':(0,1,100),
   'seat-switch':(False,True),'seat-level':(0,1,10),'window-position':(0,1,100),
   'switch':(False,True)}
  invalid={'hvac-celsius':(True,False,-1,50.1,10**400,float('nan'),float('inf')),
   'hvac-fan':(True,False,0.0,1.0,1.5,-1,101),
   'seat-switch':(0,1,0.0,1.0,'true'),'seat-level':(True,False,0.0,1.0,1.5,-1,11),
   'window-position':(True,False,0.0,1.0,1.5,-1,101),
   'switch':(0,1,0.0,1.0,'false')}
  for identifier,_,kind,_,arguments in CONTRACTS:
   action=self.registry.lookup(identifier,1)
   for value in valid[kind]:
    with self.subTest(action=identifier,valid=value):self.assertTrue(action.validate_arguments(dict(arguments,value=value)))
   for value in (*invalid[kind],None,'1',[],{}):
    with self.subTest(action=identifier,invalid=value):self.assertFalse(action.validate_arguments(dict(arguments,value=value)))
   for missing in arguments:
    with self.subTest(action=identifier,missing=missing):
     self.assertFalse(action.validate_arguments({k:v for k,v in arguments.items()if k!=missing}))
   for extra in ('seat','window','area','extra'):
    if extra not in arguments:
     with self.subTest(action=identifier,extra=extra):self.assertFalse(action.validate_arguments(dict(arguments,**{extra:'ROW_1_LEFT'})))
   for value in (None,[],True,1,'value'):self.assertFalse(action.validate_arguments(value))

 def test_area_allowlists_and_json_types(self):
  for identifier,_,kind,_,arguments in CONTRACTS:
   key='seat'if 'seat'in arguments else'window'if 'window'in arguments else None
   if key is None:continue
   allowed=SEATS if key=='seat'else ('ROW_1_LEFT','ROW_1_RIGHT','ROW_2_LEFT','ROW_2_RIGHT')
   action=self.registry.lookup(identifier,1)
   for area in (*SEATS,'FRONT_WINDSHIELD','REAR_WINDSHIELD','ROOF','ANY','',True,1,None,[],{}):
    with self.subTest(action=identifier,area=area):
     self.assertEqual(action.validate_arguments(dict(arguments,**{key:area})),area in allowed and area!=DRIVER_AREA)

 def test_driver_seat_and_window_are_rejected_for_every_area_action(self):
  self.assertEqual(DRIVER_AREA,'ROW_1_LEFT')
  for identifier,_,_,_,arguments in CONTRACTS:
   key='seat'if 'seat'in arguments else'window'if 'window'in arguments else None
   if key is None:continue
   with self.subTest(action=identifier):
    self.assertFalse(self.registry.lookup(identifier,1).validate_arguments(dict(arguments,**{key:'ROW_1_LEFT'})))

 def test_rejected_ack_may_only_carry_the_driving_reason(self):
  for identifier,*_ in CONTRACTS:
   action=self.registry.lookup(identifier,1)
   with self.subTest(action=identifier):
    self.assertTrue(action.validate_ack('rejected',{},{}))
    self.assertTrue(action.validate_ack('rejected',{'reason':'driving-restricted'},{}))
    for evidence in ({'reason':'other'},{'reason':None},{'reason':'driving-restricted','extra':1}):
     self.assertFalse(action.validate_ack('rejected',evidence,{}))
    for stage in ('received','unknown'):
     self.assertFalse(action.validate_ack(stage,{'reason':'driving-restricted'},{}))

 def test_ack_exact_fields_area_value_and_property_for_every_action(self):
  for identifier,_,kind,prop,arguments in CONTRACTS:
   action=self.registry.lookup(identifier,1);context=dict(requestId='request',arguments=arguments)
   for stage,tag in (('sdk-accepted','pleos-vehicle-setter-v1'),('state-confirmed','pleos-vehicle-getter-v1')):
    proof=dict(kind=tag,requestId='request',property=prop,**arguments)
    if stage=='state-confirmed':proof.update(receivedAtElapsedMillis=0,capturedAtMillis=None)
    with self.subTest(action=identifier,stage=stage):
     self.assertTrue(action.validate_ack(stage,proof,context))
     for missing in proof:self.assertFalse(action.validate_ack(stage,{k:v for k,v in proof.items()if k!=missing},context))
     for extra in ('seat','window','area','extra','receivedAtElapsedMillis','capturedAtMillis'):
      if extra not in proof:self.assertFalse(action.validate_ack(stage,dict(proof,**{extra:None}),context))
     for key,value in (('requestId','other'),('property','WRONG'),('kind','wrong'),('value',None),('value','AUTOMATIC'),('value','DAYTIME_RUNNING'),('value',999)):
      self.assertFalse(action.validate_ack(stage,dict(proof,**{key:value}),context))
     for key in ('seat','window'):
      if key in proof:
       for value in ('ROW_2_RIGHT','ROOF','REAR_WINDSHIELD',True,None):
        self.assertFalse(action.validate_ack(stage,dict(proof,**{key:value}),context))
     self.assertFalse(action.validate_ack(stage,proof,dict(context,arguments=dict(arguments,extra=True))))
     if kind not in ('hvac-celsius','hvac-fan'):
      for value in (1,1.0)if type(arguments['value'])is bool else (True,1.0):
       self.assertFalse(action.validate_ack(stage,dict(proof,value=value),context))
     if stage=='state-confirmed':
      for value in (True,False,-1,0.0,'0',None):
       self.assertFalse(action.validate_ack(stage,dict(proof,receivedAtElapsedMillis=value),context))
      for value in (0,False,'0'):self.assertFalse(action.validate_ack(stage,dict(proof,capturedAtMillis=value),context))
   for stage in ('received','unknown','rejected'):
    self.assertTrue(action.validate_ack(stage,{},context))
    for evidence in (proof,dict(value=arguments['value']),[],None):self.assertFalse(action.validate_ack(stage,evidence,context))
   for stage in ('queued','delivered','cancelled','invalid'):self.assertFalse(action.validate_ack(stage,proof,context))

 def test_temperature_and_fan_keep_numeric_ack_compatibility(self):
  for identifier,prop in (('hvac.temperature','TARGET_CELSIUS'),('hvac.fan','FAN_LEVEL')):
   action=self.registry.lookup(identifier,1)
   for requested,reported in ((1,1.0),(0,0.0),(22,22.0)):
    context=dict(requestId='request',arguments=dict(seat='ROW_1_RIGHT',value=requested))
    for stage in ('sdk-accepted','state-confirmed'):
     proof=dict(kind='pleos-vehicle-setter-v1',requestId='request',property=prop,seat='ROW_1_RIGHT',value=reported)
     if stage=='state-confirmed':proof.update(kind='pleos-vehicle-getter-v1',receivedAtElapsedMillis=1,capturedAtMillis=None)
     self.assertTrue(action.validate_ack(stage,proof,context))
     self.assertFalse(action.validate_ack(stage,dict(proof,value=bool(reported)),context))

 def test_display_exposes_all_eleven_and_unknown_kinds_stay_hidden(self):
  from team_device_commands import TeamDeviceCommands
  from unittest.mock import patch
  service=TeamDeviceCommands.__new__(TeamDeviceCommands);service.registry=self.registry
  options=service.display_actions()
  self.assertEqual(options,sorted([dict(id=i,revision=1,label=l,argumentKind=k)for i,l,k,_,_ in CONTRACTS],key=lambda x:x['id']))
  self.assertEqual(service.actions(self.registry.describe()),[dict(id=x['id'],revision=x['revision'])for x in options])
  for kind in ('unknown','level','window-switch'):
   with self.subTest(kind=kind),patch.object(self.registry.lookup('light.cabin',1),'argument_kind',kind):
    self.assertNotIn('light.cabin',[a['id']for a in service.display_actions()])

 def test_documentation_covers_kinds_properties_and_friend_options(self):
  from api_doc_device_commands import ARGUMENTS,PROPERTIES,OPTION,EVIDENCE
  from api_doc_friend_remotes import FRIEND_IDS,FRIEND_KINDS
  self.assertEqual(set(ARGUMENTS),{row[2]for row in CONTRACTS})
  self.assertEqual(set(OPTION['properties']['argumentKind']['enum']),set(ARGUMENTS)|{'empty-object'})
  self.assertEqual(set(FRIEND_IDS),{row[0]for row in CONTRACTS})
  self.assertEqual(set(FRIEND_KINDS),set(ARGUMENTS))
  for _,_,kind,prop,arguments in CONTRACTS:
   self.assertEqual(set(ARGUMENTS[kind]['properties']),set(arguments))
   self.assertIn(prop,PROPERTIES[kind])
  # empty, driving-restricted rejection, then setter/getter proof per argument kind
  self.assertEqual(len(EVIDENCE['anyOf']),2+2*len(ARGUMENTS))
  self.assertEqual(EVIDENCE['anyOf'][1]['properties']['reason']['const'],'driving-restricted')

if __name__=='__main__':unittest.main()
