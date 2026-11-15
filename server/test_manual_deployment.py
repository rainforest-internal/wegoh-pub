"""Real temporary PG, signed browser JWT/session and real Unix peer credentials.
The deployment worker is a held synthetic callback; no Git/systemd/VM mutation.
"""
import json
import os
from pathlib import Path
import socket
import sys
import threading
import unittest
import uuid
from unittest.mock import patch
from test_team_auth import TeamTests
sys.path.insert(0,str(Path(__file__).parent/'ops/live'))
import manual_deploy
import manual_deployment


class ManualDeploymentTests(TeamTests):
    @unittest.skipUnless(hasattr(socket,'SO_PEERCRED'),'Linux SO_PEERCRED is required for the real deployment-control Unix peer boundary')
    def test_manual_admin_browser_bridge_and_openapi(self):
        import tempfile
        with tempfile.TemporaryDirectory() as temporary:
            gate=threading.Event()
            controller=manual_deploy.Controller(Path(temporary)/'state',allowed_uid=os.getuid(),poll_lock=Path(temporary)/'release.lock',run=lambda job:(gate.wait(3) and 'succeeded'))
            listener=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
            endpoint=str(Path(temporary)/'control.sock');listener.bind(endpoint);listener.listen();listener.settimeout(.1)
            stopping=threading.Event()
            def serve():
                while not stopping.is_set():
                    try:connection,_=listener.accept()
                    except socket.timeout:continue
                    except OSError:return
                    controller.serve(connection)
            thread=threading.Thread(target=serve,daemon=True);thread.start()
            try:
                with patch.object(manual_deployment,'SOCKET_PATH',endpoint):
                    admin=self.login('alice');creator=self.login('bob');viewer=self.login('eve')
                    get='/v1/operations/deployment';post='/v1/operations/deployments'
                    self.assertEqual(self.call(get)[0],401)
                    for who,session in [('bob',creator),('eve',viewer)]:
                        self.assertEqual(self.call(get,who=who,session=session)[0],403)
                        self.assertEqual(self.call(post,{'requestId':str(uuid.uuid4())},'POST',who=who,session=session)[0],403)
                    for change in [{'csrf':False},{'origin':'https://evil.invalid'}]:
                        self.assertEqual(self.call(post,{'requestId':str(uuid.uuid4())},'POST',session=admin,**change)[0],403)
                    self.assertEqual(self.native(post,{'requestId':str(uuid.uuid4())},'POST')[0],404)
                    self.assertEqual(self.call(post,{'requestId':str(uuid.uuid4()),'ref':'other'},'POST',session=admin)[0],400)
                    self.assertEqual(self.call(get,session=admin)[2]['mode'],'manual')
                    request={'requestId':str(uuid.uuid4())}
                    code,headers,job=self.call(post,request,'POST',session=admin)
                    self.assertEqual(code,202,job);self.assertIn('no-store',headers['cache-control']);self.assertEqual(job['job']['state'],'running')
                    self.assertEqual(self.call(post,request,'POST',session=admin)[2]['job'],job['job'])
                    self.assertEqual(self.call(post,{'requestId':str(uuid.uuid4())},'POST',session=admin)[0],409)
                    gate.set()
                    import time
                    deadline=time.monotonic()+2
                    while self.call(get,session=admin)[2]['job']['state']=='running' and time.monotonic()<deadline:
                        time.sleep(.005)
                    self.assertEqual(self.call(get,session=admin)[2]['job']['state'],'succeeded')
                    with controller.mutex:
                        original=controller.latest();original['state']='unknown'
                        manual_deploy.atomic(controller.path(original['requestId']),original)
                    self.assertFalse(self.call(get,session=admin)[2]['retryAllowed'])
                    self.assertEqual(self.call(post,{'requestId':str(uuid.uuid4())},'POST',session=admin)[0],409)
                    with controller.mutex:
                        original['phase']='resolving'
                        manual_deploy.atomic(controller.path(original['requestId']),original)
                    original_bytes=controller.path(original['requestId']).read_bytes()
                    self.assertTrue(self.call(get,session=admin)[2]['retryAllowed'])
                    self.assertEqual(self.call(post,{'requestId':str(uuid.uuid4())},'POST',session=admin)[0],409)
                    retry={'requestId':str(uuid.uuid4()),'retryOf':original['requestId']}
                    self.assertEqual(self.call(post,{**retry,'retryOf':str(uuid.uuid4())},'POST',session=admin)[0],409)
                    code,_,accepted=self.call(post,retry,'POST',session=admin)
                    self.assertEqual(code,202,accepted)
                    self.assertEqual(accepted['job']['retryOf'],original['requestId'])
                    self.assertEqual(self.call(post,retry,'POST',session=admin)[2]['job']['requestId'],retry['requestId'])
                    self.assertEqual(controller.path(original['requestId']).read_bytes(),original_bytes)
                    code,_,looked=self.call(get+'?requestId='+original['requestId'],session=admin)
                    self.assertEqual(code,200,looked)
                    self.assertEqual(looked['requestedJob']['requestId'],original['requestId'])
                    self.assertEqual(looked['requestedJob']['state'],'unknown')
                    self.assertEqual(looked['job']['requestId'],retry['requestId'])
                    self.assertEqual(self.call(get+'?requestId=bad',session=admin)[0],400)
                    self.assertEqual(self.call(get+'?requestId='+original['requestId']+'&requestId='+retry['requestId'],session=admin)[0],400)
                    from team_api_docs import build_schema
                    schema=build_schema(self.module.app,self.module.TEAM_AUTH)
                    operation=schema['paths'][post]['post']
                    self.assertEqual(operation['security'],[{'CloudflareAccess':[],'TeamSession':[],'CurrentSessionCSRF':[]}])
                    self.assertFalse(operation['x-wegoh-native-access'])
                    self.assertIn('202',operation['responses']);self.assertIn('409',operation['responses'])
                    body=operation['requestBody']['content']['application/json']['schema'];self.assertFalse(body['additionalProperties']);self.assertEqual(body['required'],['requestId'])
                    self.assertIn('unknown',json.dumps(schema['paths'][get]))
            finally:
                gate.set();stopping.set();thread.join(2);listener.close();controller.lock.close()


    def test_manual_held_body_revalidates_session_role_and_times_out(self):
        import http.client
        import psycopg
        from starlette.requests import Request
        from team_auth import hashed
        original_stream=Request.stream
        for change,expected in [('session',401),('role',403),('timeout',408)]:
            with self.subTest(change=change):
                self.write_members(self.members_rows)
                admin=self.login('alice')
                received=threading.Event()
                async def observed(request):
                    async for part in original_stream(request):
                        yield part
                        if part:received.set()
                raw=json.dumps({'requestId':str(uuid.uuid4())}).encode()
                connection=http.client.HTTPConnection('127.0.0.1',self.port,timeout=8)
                with patch.object(Request,'stream',observed),patch.object(manual_deployment,'exchange')as bridge:
                    try:
                        connection.putrequest('POST','/v1/operations/deployments',skip_host=True)
                        for name,value in {'Host':'web.wegoh.invalid','Origin':'https://web.wegoh.invalid','Content-Type':'application/json','Content-Length':str(len(raw)),'Cookie':admin['cookie'],'X-WegoH-CSRF':admin['csrfToken'],'Cf-Access-Jwt-Assertion':self.assertion('alice')}.items():
                            connection.putheader(name,value)
                        connection.endheaders();connection.send(raw[:1])
                        self.assertTrue(received.wait(2),'Actual first body chunk was not observed')
                        if change=='session':
                            token=admin['cookie'].split('=',1)[1]
                            with psycopg.connect(self.dsn)as conn:conn.execute('DELETE FROM studio_sessions WHERE token_hash=%s',(hashed(token),))
                        elif change=='role':
                            rows=[dict(row)for row in self.members_rows]
                            rows[0]['role']='creator';self.write_members(rows)
                        if change!='timeout':connection.send(raw[1:])
                        response=connection.getresponse();body=response.read()
                        self.assertEqual(response.status,expected,body)
                        bridge.assert_not_called()
                    finally:connection.close()
        self.write_members(self.members_rows)


    @unittest.skipUnless(hasattr(socket,'SO_PEERCRED'),'Linux SO_PEERCRED is required for the real deployment-control Unix peer boundary')
    def test_installed_version_admin_api_target_binding(self):
        import tempfile,time
        with tempfile.TemporaryDirectory()as directory:
            gate=threading.Event();controller=manual_deploy.Controller(Path(directory)/'state',allowed_uid=os.getuid(),poll_lock=Path(directory)/'lock',run=lambda job:(gate.wait(3)and 'succeeded'))
            endpoint=str(Path(directory)/'socket');listener=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);listener.bind(endpoint);listener.listen();listener.settimeout(.1);stopping=threading.Event()
            def serve():
                while not stopping.is_set():
                    try:connection,_=listener.accept()
                    except socket.timeout:continue
                    except OSError:return
                    controller.serve(connection)
            thread=threading.Thread(target=serve,daemon=True);thread.start()
            rows=[dict(revision='b'*40,createdAt='2026-11-01T00:00:00Z',current=False,selectable=True,reason=None)]
            try:
                with patch.object(manual_deployment,'SOCKET_PATH',endpoint),patch('release_catalog.list_releases',return_value=rows):
                    admin=self.login('alice');creator=self.login('bob');path='/v1/operations/releases';post='/v1/operations/deployments'
                    self.assertEqual(self.call(path)[0],401);self.assertEqual(self.call(path,session=creator,who='bob')[0],403);self.assertEqual(self.native(path)[0],404)
                    self.assertEqual(self.call(path+'?revision=main',session=admin)[0],400)
                    code,_,value=self.call(path,session=admin);self.assertEqual(code,200,value);self.assertEqual(value['releases'],rows)
                    for target in ('main','../bad','c'*40):self.assertEqual(self.call(post,dict(requestId=str(uuid.uuid4()),targetRevision=target),'POST',session=admin)[0],400)
                    request=dict(requestId=str(uuid.uuid4()),targetRevision='b'*40);code,_,value=self.call(post,request,'POST',session=admin);self.assertEqual(code,202,value);self.assertEqual(value['job']['targetRevision'],'b'*40)
                    self.assertEqual(self.call(post,{**request,'targetRevision':'c'*40},'POST',session=admin)[0],409)
                    self.assertEqual(self.call(post,request,'POST',session=admin)[2]['job']['requestId'],request['requestId'])
                    gate.set();deadline=time.monotonic()+2
                    while controller.latest()['state']=='running'and time.monotonic()<deadline:time.sleep(.01)
            finally:gate.set();stopping.set();thread.join(2);listener.close();controller.lock.close()


    def test_installed_plan_is_admin_read_only_and_legacy_explicit(self):
        admin=self.login('alice');creator=self.login('bob')
        path='/v1/operations/deployment-plan';target='b'*40
        plan={'planId':'c'*64,'currentRevision':'a'*40,'targetRevision':target,
              'engineRevision':'d'*40,'migrations':[],'schema':{'from':'v1','to':'v1','rollbackFloor':'v1'},
              'authorizationCompatibility':{'compatible':True},'backupRequired':True,
              'canApply':True,'reason':None,'planDBVerified':False,'migrationHistory':'unknown'}
        with patch.object(manual_deployment,'exchange',return_value=plan) as bridge:
            self.assertEqual(self.call(path+'?targetRevision='+target)[0],401)
            self.assertEqual(self.call(path+'?targetRevision='+target,session=creator,who='bob')[0],403)
            self.assertEqual(self.native(path+'?targetRevision='+target)[0],404)
            for query in ('','?targetRevision=main','?targetRevision='+target+'&targetRevision='+target,
                          '?targetRevision='+target+'&operation=deploy'):
                self.assertEqual(self.call(path+query,session=admin)[0],400)
            bridge.assert_not_called()
            code,headers,value=self.call(path+'?targetRevision='+target,session=admin)
            self.assertEqual(code,200,value);self.assertEqual(value,plan)
            self.assertIn('no-store',headers['cache-control'])
            bridge.assert_called_once_with({'action':'plan','targetRevision':target})
        with patch.object(manual_deployment,'exchange',return_value={'error':'INVALID_REQUEST','stderr':'SECRET'}):
            code,_,value=self.call(path+'?targetRevision='+target,session=admin)
            self.assertEqual(code,503,value)
            self.assertEqual(value['diagnostic']['code'],'CONTROLLER_UNSUPPORTED')
            self.assertTrue(value['diagnostic']['operatorNeeded']);self.assertNotIn('SECRET',json.dumps(value))
        from team_api_docs import build_schema
        operation=build_schema(self.module.app,self.module.TEAM_AUTH)['paths'][path]['get']
        self.assertFalse(operation['x-wegoh-native-access']);self.assertIn('503',operation['responses'])

    def test_engine_operation_validation_and_legacy_payload(self):
        admin=self.login('alice');post='/v1/operations/deployments'
        with patch.object(manual_deployment,'exchange',return_value={'mode':'manual','job':None}) as bridge:
            for fields in ({'operation':'shell','targetRevision':'b'*40},{'operation':'engine-update'},
                           {'operation':{}},{'operation':'engine-update','targetRevision':'main'}):
                self.assertEqual(self.call(post,{'requestId':str(uuid.uuid4()),**fields},'POST',session=admin)[0],400)
            bridge.assert_not_called()
            old={'requestId':str(uuid.uuid4())}
            self.assertEqual(self.call(post,old,'POST',session=admin)[0],202)
            bridge.assert_called_once_with({'action':'start',**old})
            bridge.reset_mock()
            new={'requestId':str(uuid.uuid4()),'operation':'engine-update','targetRevision':'b'*40}
            self.assertEqual(self.call(post,new,'POST',session=admin,csrf=False)[0],403)
            bridge.assert_not_called()
            self.assertEqual(self.call(post,new,'POST',session=admin)[0],202)
            bridge.assert_called_once_with({'action':'start',**new})
        with patch.object(manual_deployment,'exchange',return_value={'error':'INVALID_REQUEST'}):
            explicit={'requestId':str(uuid.uuid4()),'operation':'deploy'}
            code,_,value=self.call(post,explicit,'POST',session=admin)
            self.assertEqual(code,503,value)
            self.assertEqual(value['diagnostic']['code'],'CONTROLLER_UNSUPPORTED')


    @unittest.skipUnless(hasattr(socket,'SO_PEERCRED'),'Linux SO_PEERCRED is required for the real deployment-control Unix peer boundary')
    def test_engine_operation_uses_real_unix_peer_and_durable_binding(self):
        import tempfile,time
        with tempfile.TemporaryDirectory() as directory:
            gate=threading.Event();runs=[]
            info=dict(protocol=1,revision='a'*40,manifestSha256='d'*64,state='ready',availableRevision='b'*40,updateAvailable=True,reason=None)
            plan=dict(planId='c'*64,currentRevision='a'*40,targetRevision='b'*40,engineRevision='a'*40,
                      migrations=[],schema={'from':'v1','to':'v1','rollbackFloor':'v1'},authorizationCompatibility={'compatible':True},
                      backupRequired=True,canApply=True,reason=None,planDBVerified=False,migrationHistory='unknown')
            def run(job):
                runs.append((job['requestId'],job['operation'],job['targetRevision']))
                if not gate.wait(3):return 'unknown'
                info.update(revision=job['targetRevision'],updateAvailable=False)
                return 'succeeded'
            controller=manual_deploy.Controller(Path(directory)/'state',allowed_uid=os.getuid(),poll_lock=Path(directory)/'lock',
                run=run,engine_status=lambda:dict(info),bootstrap_status=lambda:dict(revision='a'*40,receiptSha256='e'*64,verified=True),
                plan=lambda target,current:dict(plan) if target=='b'*40 else {'error':'INVALID_TARGET'})
            listener=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);endpoint=str(Path(directory)/'control.sock')
            listener.bind(endpoint);listener.listen();listener.settimeout(.1);stopping=threading.Event()
            def serve():
                while not stopping.is_set():
                    try:connection,_=listener.accept()
                    except socket.timeout:continue
                    except OSError:return
                    controller.serve(connection)
            worker=threading.Thread(target=serve,daemon=True);worker.start()
            try:
                with patch.object(manual_deployment,'SOCKET_PATH',endpoint),patch.object(manual_deploy,'current_revision',return_value='a'*40),patch.object(manual_deploy,'service_status',return_value={'ready':True,'revision':'a'*40}):
                    admin=self.login('alice');post='/v1/operations/deployments';status='/v1/operations/deployment'
                    code,_,value=self.call('/v1/operations/deployment-plan?targetRevision='+'b'*40,session=admin)
                    self.assertEqual(code,200,value);self.assertEqual(value,plan);self.assertEqual(runs,[])
                    request=dict(requestId=str(uuid.uuid4()),operation='engine-update',targetRevision='b'*40)
                    code,_,value=self.call(post,request,'POST',session=admin)
                    self.assertEqual(code,202,value);self.assertEqual(value['job']['operation'],'engine-update')
                    self.assertEqual(value['job']['previousRevision'],'a'*40)
                    self.assertEqual(self.call(post,request,'POST',session=admin)[2]['job'],value['job'])
                    self.assertEqual(self.call(post,{**request,'operation':'deploy'},'POST',session=admin)[0],409)
                    self.assertEqual(self.call(post,{**request,'targetRevision':'c'*40},'POST',session=admin)[0],409)
                    gate.set();deadline=time.monotonic()+2
                    while controller.latest()['state']=='running' and time.monotonic()<deadline:time.sleep(.005)
                    code,_,finished=self.call(status+'?requestId='+request['requestId'],session=admin)
                    self.assertEqual(code,200,finished)
                    self.assertEqual(finished['requestedJob']['state'],'succeeded')
                    self.assertEqual(finished['requestedJob']['resultRevision'],'b'*40)
                    self.assertEqual(finished['currentRevision'],'a'*40)
                    self.assertEqual(finished['service']['revision'],'a'*40)
                    self.assertEqual(finished['engine']['revision'],'b'*40)
                    self.assertEqual(runs,[(request['requestId'],'engine-update','b'*40)])
            finally:
                gate.set();stopping.set();worker.join(2);listener.close();controller.lock.close()


    def test_closed_gate_preserves_real_admin_diagnostic_authority_without_writes(self):
        import tempfile,time,hashlib,psycopg,uvicorn
        from deployment_gate import DeploymentGate
        from test_team_auth import free_port
        admin=self.login('alice');creator=self.login('bob')
        def protected_state():
            with psycopg.connect(self.dsn)as conn:
                sessions=conn.execute('SELECT token_hash,creator_id,expires_at FROM studio_sessions ORDER BY token_hash').fetchall()
                accounts=conn.execute('SELECT account_id,protected FROM team_accounts ORDER BY account_id').fetchall()
                limits=conn.execute('SELECT scope_hash,bucket,hits FROM team_rate_limits ORDER BY scope_hash,bucket').fetchall()
            return hashlib.sha256(repr((sessions,accounts,limits)).encode()).hexdigest()
        baseline=protected_state()
        with tempfile.TemporaryDirectory()as directory:
            path=Path(directory)/'gate.json';path.write_text(json.dumps(dict(format=1,state='closed',currentRevision='a'*40,targetRevision='b'*40,operationId=str(uuid.uuid4()))))
            guarded=DeploymentGate(self.module.app,path=path,source_revision='a'*40)
            port=free_port();server=uvicorn.Server(uvicorn.Config(guarded,host='127.0.0.1',port=port,proxy_headers=False,access_log=False,log_level='critical',lifespan='off'))
            worker=threading.Thread(target=server.run,daemon=True);worker.start()
            try:
                deadline=time.monotonic()+3
                while not server.started and worker.is_alive() and time.monotonic()<deadline:time.sleep(.01)
                self.assertTrue(server.started)
                original_port=self.port;self.port=port
                try:
                    with patch.object(manual_deployment,'exchange',return_value={'mode':'manual','currentRevision':'a'*40,'job':None})as bridge:
                        status='/v1/operations/deployment';releases='/v1/operations/releases';plan='/v1/operations/deployment-plan?targetRevision='+'b'*40
                        for target in (status,releases,plan):
                            self.assertEqual(self.call(target)[0],401)
                            self.assertEqual(self.call(target,who='bob',session=creator)[0],403)
                        bridge.assert_not_called()
                        self.assertEqual(self.call(status+'?requestId=invalid',session=admin)[0],400)
                        self.assertEqual(self.call(releases+'?unexpected=1',session=admin)[0],400)
                        self.assertEqual(self.call(plan+'&targetRevision='+'c'*40,session=admin)[0],400)
                        bridge.assert_not_called()
                        for target in (status,releases,plan):self.assertEqual(self.call(target,session=admin)[0],200)
                        self.assertEqual(bridge.call_count,3)
                        self.assertEqual([c.args[0]['action']for c in bridge.call_args_list],['status','releases','plan'])
                        self.assertEqual(self.call('/v1/operations/deployments',{'requestId':str(uuid.uuid4())},'POST',session=admin)[0],503)
                        self.assertEqual(self.call('/v1/auth/session',{},'POST',session=admin)[0],503)
                        self.assertEqual(self.call('/v1/auth/session',session=admin)[0],503)
                        self.assertEqual(self.call(status+'/',session=admin)[0],503)
                        self.assertEqual(bridge.call_count,3)
                    self.assertFalse(guarded.traffic_admitted)
                    self.assertEqual((0,0),(len(guarded.http),len(guarded.websockets)))
                    self.assertEqual(baseline,protected_state())
                finally:self.port=original_port
            finally:
                server.should_exit=True;worker.join(3)
                self.assertFalse(worker.is_alive())


    def test_management_location_and_retired_product_bridge(self):
        admin=self.login('alice');creator=self.login('bob');path='/v1/operations/management-location'
        with patch.dict(os.environ):
            os.environ.pop('WEGOH_MANAGEMENT_ORIGIN',None)
            self.assertEqual(self.call(path,session=admin)[2],{'configured':False,'origin':None})
            with patch.object(manual_deployment,'exchange',return_value={'mode':'manual','currentRevision':None,'job':None})as bridge:
                self.assertEqual(self.call('/v1/operations/deployment',session=admin)[0],200)
                bridge.assert_called_once_with({'action':'status'})
            os.environ['WEGOH_MANAGEMENT_ORIGIN']='https://management.wegoh.invalid'
            self.assertEqual(self.call(path)[0],401)
            self.assertEqual(self.call(path,who='bob',session=creator)[0],403)
            self.assertEqual(self.native(path)[0],404)
            self.assertEqual(self.call(path+'?redirect=https://evil.invalid',session=admin)[0],400)
            code,headers,value=self.call(path,session=admin)
            self.assertEqual((code,value),(200,{'configured':True,'origin':'https://management.wegoh.invalid'}))
            self.assertIn('no-store',headers['cache-control'])
            with patch.object(manual_deployment,'exchange')as bridge:
                for target in ('/v1/operations/deployment','/v1/operations/releases','/v1/operations/deployment-plan?targetRevision='+'a'*40):
                    code,headers,value=self.call(target,session=admin)
                    self.assertEqual(code,503,value);self.assertEqual(value['code'],'MANAGEMENT_SERVICE_REQUIRED')
                    self.assertEqual(value['managementOrigin'],'https://management.wegoh.invalid')
                    self.assertNotIn('location',headers)
                body={'requestId':str(uuid.uuid4())}
                self.assertEqual(self.call('/v1/operations/deployments',body,'POST',session=admin,csrf=False)[0],403)
                self.assertEqual(self.call('/v1/operations/deployments',body,'POST',session=admin)[0],503)
                bridge.assert_not_called()
            invalid=('http://management.wegoh.invalid','https://web.wegoh.invalid','https://api.wegoh.invalid',
                     'https://synthetic.cloudflareaccess.com','https://management.wegoh.invalid/path',
                     'https://management.wegoh.invalid:443','https://user@management.wegoh.invalid',
                     'https://127.0.0.1','https://localhost','https://management..wegoh.invalid')
            for origin in invalid:
                os.environ['WEGOH_MANAGEMENT_ORIGIN']=origin
                code,_,value=self.call(path,session=admin)
                self.assertEqual(code,503,value)
                self.assertNotIn(origin,json.dumps(value))


def load_tests(loader,tests,pattern):
    # This slice owns one method, not the inherited full TeamTests suite.
    return unittest.TestSuite([ManualDeploymentTests('test_manual_admin_browser_bridge_and_openapi'),ManualDeploymentTests('test_manual_held_body_revalidates_session_role_and_times_out'),ManualDeploymentTests('test_installed_version_admin_api_target_binding'),ManualDeploymentTests('test_installed_plan_is_admin_read_only_and_legacy_explicit'),ManualDeploymentTests('test_engine_operation_validation_and_legacy_payload'),ManualDeploymentTests('test_engine_operation_uses_real_unix_peer_and_durable_binding'),ManualDeploymentTests('test_closed_gate_preserves_real_admin_diagnostic_authority_without_writes'),ManualDeploymentTests('test_management_location_and_retired_product_bridge')])
