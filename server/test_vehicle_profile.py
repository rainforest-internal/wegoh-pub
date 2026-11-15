import unittest
import psycopg
from test_native_authorization_http import NativeAuthorizationHttpTests
from team_api_docs import build_schema

class VehicleProfileTests(NativeAuthorizationHttpTests):
 def test_vehicle_profile_current_installation_cas_and_clear(self):
  receipt=self.connected();token=receipt['accessToken'];path='/v1/device/vehicle-profile'
  self.assertEqual(self.native(path,token=token)[2],dict(deviceId=receipt['deviceId'],plateNumber='',name='',defaultName='alice의 차',revision=0))
  def save(plate,revision,name=''):return self.native(path,dict(plateNumber=plate,name=name,expectedRevision=revision),'PUT',token)
  for plate in ['a1234',' ', '123가4567\n', '가나다', '1'*17, None]:self.assertEqual(save(plate,0)[0],400)
  self.assertEqual(save('123가4567',True)[0],400)
  self.assertEqual(self.native(path,dict(plateNumber='123가4567',expectedRevision=0),'PUT',token)[0],400)
  self.assertEqual(save('123가4567',0)[0],200)
  self.assertEqual(save('456나7890',0)[0],409)
  self.assertEqual(self.native(path,token=token)[2]['plateNumber'],'123가4567')
  with psycopg.connect(self.auth.dsn) as conn:
   raw=conn.execute('SELECT protected FROM team_accounts WHERE account_id=%s',(receipt['accountId'],)).fetchone()[0]
   self.assertNotIn('123가4567'.encode(),bytes(raw))
  self.assertEqual(self.native('/v1/account',dict(displayName='새 이름',expectedDisplayName='alice'),'PUT',token)[0],200)
  self.assertEqual(self.native(path,token=token)[2]['plateNumber'],'123가4567')
  self.session=self.api.login()
  self.assertEqual(self.native(path,token=token)[2]['plateNumber'],'123가4567')
  self.assertEqual(self.native(path,token=token)[2]['defaultName'],'새 이름의 차')
  self.assertEqual(save('',1)[2]['revision'],2)
  self.assertEqual(self.native(path,token=token)[2]['plateNumber'],'')
  self.assertEqual(self.api.call(path,session=self.session)[0],404)
  self.assertEqual(self.native('/v1/device',method='DELETE',token=token)[0],200)
  self.assertEqual(self.native(path,token=token)[0],401)
  self.assertEqual(save('123가4567',2)[0],401)
  schema=build_schema(self.api.module.app,self.auth)
  self.assertEqual(schema['paths'][path]['put']['x-wegoh-surface'],'native')

 def test_replacement_installation_is_separate_and_cannot_choose_target(self):
  receipt=self.connected();first=receipt['accessToken'];first_certificate=self.fingerprint;path='/v1/device/vehicle-profile'
  self.assertEqual(self.native(path,dict(plateNumber='123가4567',name='출근 차',expectedRevision=0),'PUT',first)[0],200)
  self.assertEqual(self.native('/v1/device',method='DELETE',token=first)[0],200)
  from test_enrollment import make_csr
  from enrollment_crypto import digest,public_bytes,validate_csr
  import secrets
  from enrollment_crypto import challenge
  self.key,self.csr=make_csr();self.key_id=digest(public_bytes(validate_csr(self.csr).public_key()))
  self.verifier=secrets.token_urlsafe(32);self.challenge=challenge(self.verifier)
  second=self.connected();second_token=second['accessToken']
  self.assertEqual(self.native(path,token=second_token)[2]['plateNumber'],'')
  self.assertEqual(self.native(path,token=second_token)[2]['name'],'')
  self.assertEqual(self.native(path,dict(plateNumber='456나7890',name='',expectedRevision=0,deviceId=receipt['deviceId']),'PUT',second_token)[0],400)
  self.assertEqual(self.native(path,dict(plateNumber='456나7890',name='',expectedRevision=0),'PUT',second_token)[0],200)
  self.assertEqual(self.native(path,token=first,certificate=first_certificate)[0],401)
  self.assertEqual(self.native(path,token=second_token,certificate=first_certificate)[0],401)

 def test_browser_owns_device_csrf_and_native_reads_same_value(self):
  receipt=self.connected();native='/v1/device/vehicle-profile';path='/v1/devices/'+receipt['deviceId']+'/vehicle-profile'
  body=dict(plateNumber='123가4567',name='',expectedRevision=0)
  self.assertEqual(self.api.call(path,session=self.session)[0],200)
  self.assertEqual(self.api.call(path,body,'PUT',session=self.session,csrf=False)[0],403)
  bob=self.api.login('bob')
  self.assertEqual(self.api.call(path,session=bob,who='bob')[0],404)
  self.assertEqual(self.api.call(path,body,'PUT',session=bob,who='bob')[0],404)
  self.assertEqual(self.api.call(path,body,'PUT',session=self.session)[0],200)
  self.assertEqual(self.native(native,token=receipt['accessToken'])[2]['plateNumber'],'123가4567')
  self.assertEqual(self.api.call(path,body,'PUT',session=self.session)[0],409)
  self.assertEqual(self.native(path,token=receipt['accessToken'])[0],404)
  schema=build_schema(self.api.module.app,self.auth)
  self.assertEqual(schema['paths']['/v1/devices/{device}/vehicle-profile']['put']['x-wegoh-surface'],'browser')

 def test_owner_names_vehicle_everywhere_and_default_follows_account_name(self):
  receipt=self.connected();token=receipt['accessToken'];device=receipt['deviceId']
  native='/v1/device/vehicle-profile';path='/v1/devices/'+device+'/vehicle-profile'
  def listed():
   status,_,value=self.api.call('/v1/devices',session=self.session)
   self.assertEqual(status,200,value);return [row['name'] for row in value['devices']]
  def permissions():return self.api.call('/v1/devices/'+device+'/permissions',session=self.session)[2]['name']
  # The connection request label is not the vehicle name; unnamed vehicles follow the account name.
  self.assertEqual(listed(),['alice의 차']);self.assertEqual(permissions(),'alice의 차')
  body=lambda name,revision:dict(plateNumber='',name=name,expectedRevision=revision)
  for name in [' 출근 차','출근 차 ','가'*21,'출근\n차','출근\u200b차','출근\u2028차',None,1]:
   self.assertEqual(self.api.call(path,body(name,0),'PUT',session=self.session)[0],400,name)
  status,_,saved=self.api.call(path,body('가'*20,0),'PUT',session=self.session)
  self.assertEqual((status,saved['name'],saved['defaultName'],saved['revision']),(200,'가'*20,'alice의 차',1))
  status,_,saved=self.api.call(path,body('주말 🚗 차',1),'PUT',session=self.session)
  self.assertEqual((status,saved['name']),(200,'주말 🚗 차'))
  self.assertEqual(listed(),['주말 🚗 차']);self.assertEqual(permissions(),'주말 🚗 차')
  self.assertEqual(self.native(native,token=token)[2]['name'],'주말 🚗 차')
  with psycopg.connect(self.auth.dsn) as conn:
   raw=conn.execute('SELECT protected FROM team_accounts WHERE account_id=%s',(receipt['accountId'],)).fetchone()[0]
   self.assertNotIn('주말'.encode(),bytes(raw))
  # Clearing the name returns to the default, which tracks account renames.
  self.assertEqual(self.native(native,body('',2),'PUT',token)[2]['name'],'')
  self.assertEqual(listed(),['alice의 차'])
  self.assertEqual(self.native('/v1/account',dict(displayName='사용자A',expectedDisplayName='alice'),'PUT',token)[0],200)
  self.assertEqual(listed(),['사용자A의 차'])
  self.assertEqual(self.native(native,token=token)[2]['defaultName'],'사용자A의 차')
  # Another account cannot read or rename this vehicle.
  bob=self.api.login('bob')
  self.assertEqual(self.api.call(path,body('남의 차',3),'PUT',session=bob,who='bob')[0],404)

if __name__=='__main__':unittest.main()
