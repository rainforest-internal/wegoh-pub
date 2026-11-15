"""Authenticated Browser fuel snapshots. Native, URLs and coordinates are not inputs."""
import asyncio
import json
import os
import psycopg
from fastapi import APIRouter,HTTPException,Request,Response
from starlette.concurrency import run_in_threadpool
from fuel_prices import FuelPrices,FuelError,query

def strict_pairs(pairs):
    value={}
    for key,item in pairs:
        if key in value:raise ValueError('Duplicate key')
        value[key]=item
    return value

class TeamFuel:
    def __init__(self,auth,cache=None):
        self.auth=auth
        self.cache=cache if cache is not None else FuelPrices(auth.dsn,mode=os.environ.get('WEGOH_FUEL_MODE','off'),daily_limit=int(os.environ.get('WEGOH_FUEL_DAILY_BUDGET','240')))
        if auth.enabled and self.cache.mode!='off':self.cache.initialize()
    def router(self):
        router=APIRouter()
        if not self.auth.enabled:return router
        @router.post('/v1/fuel/quotes')
        async def quotes(request:Request,response:Response):
            identity=await run_in_threadpool(self.auth.browser,request,mutate=True,roles=('admin','creator'))
            if request.query_params:raise HTTPException(400,'FUEL_QUERY_INVALID')
            await run_in_threadpool(self.auth.rate,'fuel-quotes:'+identity['id'],limit=30)
            raw=bytearray()
            try:
                async with asyncio.timeout(5):
                    async for chunk in request.stream():
                        raw.extend(chunk)
                        if len(raw)>1024:raise HTTPException(413,'FUEL_QUERY_INVALID')
                value=json.loads(raw,object_pairs_hook=strict_pairs,parse_constant=lambda _:(_ for _ in()).throw(ValueError()))
                query(value)
            except TimeoutError:raise HTTPException(408,'FUEL_QUERY_INVALID')from None
            except(ValueError,UnicodeError,RecursionError):raise HTTPException(400,'FUEL_QUERY_INVALID')from None
            current=await run_in_threadpool(self.auth.browser,request,mutate=True,roles=('admin','creator'))
            if current['id']!=identity['id']:raise HTTPException(401,'Authentication changed')
            try:result=await run_in_threadpool(self.cache.quotes,value)
            except FuelError as error:raise HTTPException(error.status,error.code)from None
            except psycopg.Error:raise HTTPException(503,'FUEL_PROVIDER_UNAVAILABLE')from None
            current=await run_in_threadpool(self.auth.browser,request,mutate=True,roles=('admin','creator'))
            if current['id']!=identity['id']:raise HTTPException(401,'Authentication changed')
            response.headers['Cache-Control']='private, no-store'
            return result
        return router
