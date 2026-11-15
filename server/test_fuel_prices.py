"""Small actual PG/cache/auth tests; synthetic provider/clock, no keys or network prices."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
import threading
import hashlib
import time
import unittest
import psycopg
import test_team_auth as fixture
from fuel_prices import FuelPrices,FuelError,MockFuelProvider,next_update
from team_fuel import TeamFuel

class Clock:
    def __init__(self):self.value=datetime(2026,11,1,0,30,tzinfo=timezone.utc)
    def __call__(self):return self.value

class Counting(MockFuelProvider):
    def __init__(self):self.calls=0;self.failure=False;self.delay=0;self.lock=threading.Lock()
    def fetch(self,*args):
        with self.lock:self.calls+=1
        if self.delay:time.sleep(self.delay)
        if self.failure:raise TimeoutError('Synthetic provider timeout')
        return super().fetch(*args)

class FuelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.TeamTests.setUpClass()
        cls.service=fixture.TeamTests.module.TEAM_FUEL
        cls.previous_cache=cls.service.cache
    @classmethod
    def tearDownClass(cls):
        cls.service.cache=cls.previous_cache
        fixture.TeamTests.tearDownClass()
    def setUp(self):
        self.h=fixture.TeamTests('test_01_jwt_verification_and_exact_hosts');self.h.setUp()
        with psycopg.connect(self.h.dsn)as conn:conn.execute('TRUNCATE fuel_quote_cache,fuel_upstream_attempts')
        self.clock=Clock();self.provider=Counting();self.cache=FuelPrices(self.h.dsn,mode='mock',provider=self.provider,clock=self.clock)
        self.service.cache=self.cache
    def count(self):
        with psycopg.connect(self.h.dsn)as conn:return conn.execute('SELECT count(*)FROM fuel_upstream_attempts').fetchone()[0]
    def test_auth_role_origin_csrf_defaultoff_and_shared_browser_cache(self):
        a,b,e=self.h.login(),self.h.login('bob'),self.h.login('eve');path='/v1/fuel/quotes';body=dict(region='01',fuel='gasoline')
        for options,status in [(dict(who=None),401),(dict(who='eve',session=e),403),(dict(session=a,csrf=False),403),(dict(session=a,origin='https://other.invalid'),403)]:
            self.assertEqual(self.h.call(path,body,'POST',**options)[0],status)
        self.assertEqual(self.h.native(path,body,'POST')[0],404);self.assertEqual(self.provider.calls,0)
        self.service.cache=FuelPrices(self.h.dsn)
        self.assertEqual(self.h.call(path,body,'POST',session=a)[0],503)
        self.service.cache=self.cache
        for bad in [dict(region='11',fuel='gasoline'),dict(body,latitude=37),dict(region='01',fuel='other')]:
            self.assertEqual(self.h.call(path,bad,'POST',session=a)[0],400)
        duplicate=b'{"region":"01","region":"01","fuel":"gasoline"}'
        self.assertEqual(self.h.call(path,method='POST',session=a,raw=duplicate)[0],400)
        self.assertEqual(self.h.call(path+'?url=https://other.invalid',body,'POST',session=a)[0],400)
        code,headers,first=self.h.call(path,body,'POST',session=a);self.assertEqual(code,200,first)
        self.assertEqual(headers['cache-control'],'private, no-store');self.assertEqual(first['cache']['status'],'fetched')
        code,_,second=self.h.call(path,body,'POST',session=b,who='bob');self.assertEqual(code,200)
        self.assertEqual(second['cache']['status'],'hit');self.assertEqual(first['stations'],second['stations']);self.assertEqual(self.provider.calls,1)
        self.assertEqual(first['source']['mode'],'mock');self.assertFalse(first['source']['live'])
        from api_doc_fuel import MODELS
        for name,value in [('FuelQuotes',first),('FuelSource',first['source']),('FuelCache',first['cache']),('FuelStation',first['stations'][0])]:
            self.assertEqual(set(value),set(MODELS[name]['required']))
            self.assertFalse(MODELS[name]['additionalProperties'])
        self.assertTrue(all('가상'in x['name']for x in first['stations']));self.assertNotIn('latitude',str(first));self.assertEqual(self.count(),1)
    def test_enabled_startup_adds_cache_without_reprovision_or_existing_state_loss(self):
        owner=self.h.login();key_sha=hashlib.sha256((self.h.state/'visits.key').read_bytes()).hexdigest()
        status,_,playlist=self.h.call('/v1/playlists',dict(name='Existing synthetic playlist',tracks=[]),'POST',session=owner);self.assertEqual(status,201,playlist)
        with psycopg.connect(self.h.dsn)as conn:
            before=bytes(conn.execute('SELECT protected FROM team_playlists WHERE playlist_id=%s',(playlist['id'],)).fetchone()[0])
            conn.execute('DROP TABLE fuel_quote_cache,fuel_upstream_attempts')
        started=TeamFuel(self.h.module.TEAM_AUTH,self.cache)
        self.assertEqual(started.cache.quotes(dict(region='01',fuel='gasoline'))['source']['mode'],'mock')
        started.cache.initialize()
        with psycopg.connect(self.h.dsn)as conn:
            self.assertEqual(bytes(conn.execute('SELECT protected FROM team_playlists WHERE playlist_id=%s',(playlist['id'],)).fetchone()[0]),before)
        self.assertEqual(hashlib.sha256((self.h.state/'visits.key').read_bytes()).hexdigest(),key_sha)
        self.assertEqual(self.h.call('/v1/auth/session',session=owner)[0],200)

    def test_two_service_instances_singleflight_and_persistent_cache(self):
        self.provider.delay=.04
        services=[FuelPrices(self.h.dsn,mode='mock',provider=self.provider,clock=self.clock)for _ in range(8)]
        with ThreadPoolExecutor(max_workers=8)as pool:values=list(pool.map(lambda service:service.quotes(dict(region='01',fuel='diesel')),services))
        self.assertEqual(self.provider.calls,1);self.assertEqual(self.count(),1)
        self.assertEqual(sum(x['cache']['status']=='fetched'for x in values),1)
        fresh_provider=Counting();fresh=FuelPrices(self.h.dsn,mode='mock',provider=fresh_provider,clock=self.clock)
        self.assertEqual(fresh.quotes(dict(region='01',fuel='diesel'))['cache']['status'],'hit');self.assertEqual(fresh_provider.calls,0)
    def test_rolling_budget_counts_failures_and_central_backoff(self):
        self.provider.failure=True;cache=FuelPrices(self.h.dsn,mode='mock',provider=self.provider,clock=self.clock,daily_limit=2)
        for fuel,code in [('gasoline','FUEL_UPSTREAM_TIMEOUT'),('gasoline','FUEL_UPSTREAM_TIMEOUT'),('diesel','FUEL_UPSTREAM_TIMEOUT'),('lpg','FUEL_BUDGET_EXHAUSTED')]:
            with self.assertRaises(FuelError)as failed:cache.quotes(dict(region='01',fuel=fuel))
            self.assertEqual(failed.exception.code,code)
        self.assertEqual(self.provider.calls,2);self.assertEqual(self.count(),2)
        self.clock.value+=timedelta(hours=24,seconds=1);self.provider.failure=False
        self.assertEqual(cache.quotes(dict(region='01',fuel='gasoline'))['cache']['status'],'fetched');self.assertEqual(self.provider.calls,3)
        self.assertEqual(self.cache.daily_limit,240);self.assertEqual(self.cache.reserve,60)
        with self.assertRaises(ValueError):FuelPrices(self.h.dsn,daily_limit=301)
    def test_schedule_stale_fallback_bound_and_no_mode_mixing(self):
        body=dict(region='01',fuel='gasoline');first=self.cache.quotes(body)
        self.assertEqual(first['cache']['freshUntil'],'2026-11-01T03:00:00+00:00')
        self.clock.value=datetime(2026,11,1,3,0,tzinfo=timezone.utc);self.provider.failure=True
        stale=self.cache.quotes(body);self.assertTrue(stale['cache']['stale']);self.assertEqual(stale['cache']['fallbackReason'],'FUEL_UPSTREAM_TIMEOUT')
        self.assertEqual(stale['cache']['fetchedAt'],first['cache']['fetchedAt']);self.assertEqual(stale['stations'],first['stations'])
        class LiveFailure(Counting):mode='live';budget_key='opinet-free'
        live=LiveFailure();live.failure=True
        with self.assertRaises(FuelError):FuelPrices(self.h.dsn,mode='live',provider=live,clock=self.clock).quotes(body)
        self.assertEqual(live.calls,1)
        self.clock.value+=timedelta(days=2)
        with self.assertRaises(FuelError):self.cache.quotes(body)
        self.assertEqual(next_update(datetime(2026,11,1,10,0,tzinfo=timezone.utc)),datetime(2026,11,1,16,0,tzinfo=timezone.utc))
    def test_real_timeout_counts_and_never_publishes_late_result(self):
        self.provider.delay=.2;cache=FuelPrices(self.h.dsn,mode='mock',provider=self.provider,clock=self.clock,timeout=.03)
        started=time.monotonic()
        with self.assertRaises(FuelError)as failed:cache.quotes(dict(region='01',fuel='lpg'))
        self.assertEqual(failed.exception.code,'FUEL_UPSTREAM_TIMEOUT');self.assertLess(time.monotonic()-started,1)
        time.sleep(.22)
        with psycopg.connect(self.h.dsn)as conn:
            row=conn.execute('SELECT payload,last_error FROM fuel_quote_cache').fetchone();self.assertIsNone(row[0]);self.assertEqual(row[1],'FUEL_UPSTREAM_TIMEOUT')
        self.assertEqual(self.count(),1)
        with self.assertRaises(FuelError):cache.quotes(dict(region='01',fuel='lpg'))
        self.assertEqual(self.provider.calls,1)

if __name__=='__main__':unittest.main()
