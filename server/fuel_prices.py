"""Public fuel snapshots, shared PG cache and bounded upstream attempts. No user location."""
import copy
from datetime import datetime,timedelta,timezone
from queue import Queue,Empty
import re
import secrets
from threading import Thread
from typing import Protocol
from zoneinfo import ZoneInfo
import psycopg
from psycopg.types.json import Jsonb

KST=ZoneInfo('Asia/Seoul')
UPDATE_HOURS=(1,2,9,12,16,19)
REGIONS={'01':'서울'}  # Confirmed PDF area example0101=종로구; no guessed administrative codes.
FUELS=('gasoline','diesel','lpg')
CACHE_SCHEMA='''-- Shared nonpersonal public/mock fuel snapshots. No account, coordinate or key data.
CREATE TABLE IF NOT EXISTS fuel_quote_cache (
    namespace varchar(96) NOT NULL,
    region varchar(4) NOT NULL CHECK(region ~ '^[0-9]{2}([0-9]{2})?$'),
    fuel varchar(16) NOT NULL CHECK(fuel IN ('gasoline','diesel','lpg')),
    payload jsonb,
    fetched_at timestamptz,
    fresh_until timestamptz,
    retry_after timestamptz,
    last_error varchar(64),
    PRIMARY KEY(namespace,region,fuel),
    CHECK((payload IS NULL AND fetched_at IS NULL AND fresh_until IS NULL) OR
          (payload IS NOT NULL AND fetched_at IS NOT NULL AND fresh_until>fetched_at))
);
CREATE TABLE IF NOT EXISTS fuel_upstream_attempts (
    attempt_id char(32) PRIMARY KEY,
    budget_key varchar(80) NOT NULL,
    attempted_at timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS fuel_attempts_rolling_budget ON fuel_upstream_attempts(budget_key,attempted_at);
'''

HARD_LIMIT=300
DEFAULT_LIMIT=240

class FuelError(ValueError):
    def __init__(self,code,status=503):self.code,self.status=code,status;super().__init__(code)

class FuelProvider(Protocol):
    # Future real adapters must use a fixed trusted endpoint, protected key and
    # bounded transport; provider identity/budget_key must never contain the key.
    mode:str
    identity:str
    budget_key:str
    def fetch(self,region:str,fuel:str,now:datetime,timeout:float)->list[dict]:...

class MockFuelProvider:
    mode='mock';identity='wegoh-fictional-fuel-v1';budget_key='mock-fuel'
    def fetch(self,region,fuel,now,timeout):
        base={'gasoline':1687,'diesel':1534,'lpg':987}[fuel]
        return [dict(id=f'mock-{region}-{fuel}-{index}',name='가상 '+name+' 주유소',
            address=REGIONS[region]+' 지역 가상 주소 '+str(index)+' (실제 주소 아님)',
            priceWonPerLiter=base+index*13,reportedAt=now.isoformat())
            for index,name in enumerate(('솔바람','별빛','강가'),1)]

def utc(value):
    if not isinstance(value,datetime)or value.utcoffset()is None:raise ValueError('Aware UTC clock required')
    return value.astimezone(timezone.utc)

def next_update(value):
    local=utc(value).astimezone(KST)
    for day in (0,1):
        date=local+timedelta(days=day)
        for hour in UPDATE_HOURS:
            candidate=date.replace(hour=hour,minute=0,second=0,microsecond=0)
            if candidate>local:return candidate.astimezone(timezone.utc)
    raise AssertionError('Update schedule unavailable')

def query(value):
    if type(value)is not dict or set(value)!={'region','fuel'}:raise FuelError('FUEL_QUERY_INVALID',400)
    region,fuel=value['region'],value['fuel']
    if type(region)is not str or region not in REGIONS or fuel not in FUELS or type(fuel)is not str:
        raise FuelError('FUEL_QUERY_INVALID',400)
    return region,fuel

def checked_stations(value,now):
    if type(value)is not list or not 1<=len(value)<=20:raise FuelError('FUEL_PROVIDER_UNAVAILABLE')
    ids=set();result=[]
    for station in value:
        if type(station)is not dict or set(station)!={'id','name','address','priceWonPerLiter','reportedAt'}:raise FuelError('FUEL_PROVIDER_UNAVAILABLE')
        for key,maximum in [('id',80),('name',120),('address',240)]:
            text=station[key]
            if type(text)is not str or not text.strip()or len(text)>maximum or any(ord(c)<32 for c in text):raise FuelError('FUEL_PROVIDER_UNAVAILABLE')
        price=station['priceWonPerLiter']
        if type(price)is not int or not 1<=price<=100000 or station['id']in ids:raise FuelError('FUEL_PROVIDER_UNAVAILABLE')
        try:reported=utc(datetime.fromisoformat(station['reportedAt'].replace('Z','+00:00')))
        except(ValueError,TypeError,AttributeError):raise FuelError('FUEL_PROVIDER_UNAVAILABLE')from None
        if reported>utc(now)+timedelta(minutes=5):raise FuelError('FUEL_PROVIDER_UNAVAILABLE')
        ids.add(station['id']);result.append(dict(station,reportedAt=reported.isoformat()))
    return result

class FuelPrices:
    def __init__(self,dsn,*,mode='off',provider=None,clock=None,daily_limit=DEFAULT_LIMIT,timeout=3,max_stale=86400,retry_seconds=60):
        if mode not in ('off','mock','live')or type(daily_limit)is not int or not 1<=daily_limit<=HARD_LIMIT:raise ValueError('Invalid fuel configuration')
        if not 0<timeout<=10 or not 1<=max_stale<=172800 or not 1<=retry_seconds<=3600:raise ValueError('Invalid fuel timeout/cache configuration')
        self.dsn,self.mode,self.clock=dsn,mode,clock or (lambda:datetime.now(timezone.utc))
        self.daily_limit,self.reserve= daily_limit,HARD_LIMIT-daily_limit
        self.timeout,self.max_stale,self.retry_seconds=timeout,max_stale,retry_seconds
        self.provider=provider if provider is not None else MockFuelProvider()if mode=='mock'else None
        if self.provider is not None:
            if self.provider.mode!=mode or not all(re.fullmatch(r'[a-z0-9_-]{1,80}',getattr(self.provider,key,''))for key in ('identity','budget_key')):raise ValueError('Invalid fuel provider identity/mode')
        self.namespace=mode+':'+(self.provider.identity if self.provider else 'disabled')
    def initialize(self):
        with psycopg.connect(self.dsn,connect_timeout=3)as conn:
            conn.execute("SET LOCAL lock_timeout='5s'")
            conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('fuel-cache-schema',0))")
            conn.execute(CACHE_SCHEMA)
    def now(self):return utc(self.clock())
    def reserve_attempt(self,region,fuel):
        # Separate committed transaction: exceptions/timeouts never refund an attempt.
        now=self.now()
        with psycopg.connect(self.dsn,connect_timeout=3)as conn:
            conn.execute("SET LOCAL lock_timeout='4s'")
            conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',('fuel-budget:'+self.provider.budget_key,))
            used=conn.execute('SELECT count(*) FROM fuel_upstream_attempts WHERE budget_key=%s AND attempted_at>%s',(self.provider.budget_key,now-timedelta(hours=24))).fetchone()[0]
            if used>=self.daily_limit:raise FuelError('FUEL_BUDGET_EXHAUSTED',429)
            conn.execute('INSERT INTO fuel_upstream_attempts(attempt_id,budget_key,attempted_at)VALUES(%s,%s,%s)',(secrets.token_hex(16),self.provider.budget_key,now))
    def fetch(self,region,fuel):
        output=Queue(maxsize=1);now=self.now()
        def run():
            try:output.put((True,self.provider.fetch(region,fuel,now,self.timeout)))
            except TimeoutError:output.put((False,'timeout'))
            except Exception:output.put((False,None))
        # A late adapter result is discarded. The attempt remains counted; failed
        # keys back off centrally, so browser retries cannot launch another call.
        Thread(target=run,daemon=True,name='fuel-provider').start()
        try:success,value=output.get(timeout=self.timeout)
        except Empty:raise FuelError('FUEL_UPSTREAM_TIMEOUT',504)from None
        if not success:raise FuelError('FUEL_UPSTREAM_TIMEOUT',504)if value=='timeout'else FuelError('FUEL_PROVIDER_UNAVAILABLE')
        return checked_stations(value,self.now())
    def response(self,region,fuel,row,*,status,reason=None):
        payload,fetched,fresh_until=row[:3];now=self.now()
        if payload is None or fetched is None:raise FuelError(reason or 'FUEL_UNAVAILABLE')
        result=copy.deepcopy(payload)
        result['cache']=dict(fetchedAt=utc(fetched).isoformat(),freshUntil=utc(fresh_until).isoformat(),
            stale=status=='stale',status=status,ageSeconds=max(0,int((now-utc(fetched)).total_seconds())),fallbackReason=reason)
        return result
    def fallback(self,region,fuel,row,error):
        if row and row[0]is not None and row[1]is not None and 0<=(self.now()-utc(row[1])).total_seconds()<=self.max_stale:
            return self.response(region,fuel,row,status='stale',reason=error.code)
        raise error
    def quotes(self,value):
        region,fuel=query(value)
        if self.mode=='off'or self.provider is None:raise FuelError('FUEL_UNAVAILABLE')
        key='fuel-cache:'+self.namespace+':'+region+':'+fuel
        with psycopg.connect(self.dsn,autocommit=True,connect_timeout=3)as conn:
            conn.execute("SET lock_timeout='5s'")
            conn.execute('SELECT pg_advisory_lock(hashtextextended(%s,0))',(key,))
            try:
                row=conn.execute('SELECT payload,fetched_at,fresh_until,retry_after,last_error FROM fuel_quote_cache WHERE namespace=%s AND region=%s AND fuel=%s',(self.namespace,region,fuel)).fetchone()
                now=self.now()
                if row and row[0]is not None and utc(row[2])>now:return self.response(region,fuel,row,status='hit')
                if row and row[3]is not None and utc(row[3])>now:
                    status=429 if row[4]=='FUEL_BUDGET_EXHAUSTED'else 504 if row[4]=='FUEL_UPSTREAM_TIMEOUT'else 503
                    return self.fallback(region,fuel,row,FuelError(row[4],status))
                try:
                    self.reserve_attempt(region,fuel);stations=self.fetch(region,fuel)
                except FuelError as error:
                    conn.execute('INSERT INTO fuel_quote_cache(namespace,region,fuel,retry_after,last_error)VALUES(%s,%s,%s,%s,%s) ON CONFLICT(namespace,region,fuel)DO UPDATE SET retry_after=excluded.retry_after,last_error=excluded.last_error',
                        (self.namespace,region,fuel,self.now()+timedelta(seconds=self.retry_seconds),error.code))
                    return self.fallback(region,fuel,row,error)
                fetched=self.now();fresh=next_update(fetched)
                payload=dict(region=region,fuel=fuel,currency='KRW',unit='L',stations=stations,
                    source=dict(mode=self.mode,live=False,provider=self.provider.identity,label='가상 유가'if self.mode=='mock'else'공급자 가격 자료',
                        reference='Opinet_API_Free.pdf (2026.10) lowTop10.do 형식 참고. 값과 업체는 모두 가상입니다.'if self.mode=='mock'else'명시 설정한 공급자 스냅샷. 현재 거래 가격을 보증하지 않습니다.'))
                conn.execute('INSERT INTO fuel_quote_cache(namespace,region,fuel,payload,fetched_at,fresh_until,retry_after,last_error)VALUES(%s,%s,%s,%s,%s,%s,NULL,NULL) ON CONFLICT(namespace,region,fuel)DO UPDATE SET payload=excluded.payload,fetched_at=excluded.fetched_at,fresh_until=excluded.fresh_until,retry_after=NULL,last_error=NULL',
                    (self.namespace,region,fuel,Jsonb(payload),fetched,fresh))
                return self.response(region,fuel,(payload,fetched,fresh),status='fetched')
            finally:conn.execute('SELECT pg_advisory_unlock(hashtextextended(%s,0))',(key,))
    def bake(self,regions=('01',),fuels=FUELS):
        # Explicit backend preparation only, using the identical locks/budget.
        # No timer, alternate quota or browser-specific upstream cache is created.
        return [self.quotes(dict(region=region,fuel=fuel))for region in regions for fuel in fuels]
