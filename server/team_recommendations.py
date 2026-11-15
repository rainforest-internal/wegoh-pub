"""Explicit, explainable first recommendation vertical; no external model call.

Only adapters may supply current available course/catalog facts. User history and
persisted feedback require separate purpose checks in the router. The ordering
below is rules, not ML, inferred health, fuel telemetry, route time or price.
"""
from course_publication import COURSE_AVAILABLE, available
import math
from fastapi import HTTPException

FACILITIES = ('toilet', 'nursing', 'evCharger', 'gasStation', 'lpg')
PRIORITIES = ('nearby', 'fewStops', 'manyStops')


def unavailable(code=400, detail='Invalid recommendation preferences'):
    raise HTTPException(code, detail)


def explicit_preferences(value):
    if not isinstance(value, dict) or set(value) != {'coursePriority', 'facilities', 'hideVisited', 'maxDistanceKm'}:
        unavailable()
    if value['coursePriority'] not in PRIORITIES or type(value['hideVisited']) is not bool:
        unavailable()
    needs = value['facilities']
    if not isinstance(needs, list) or len(needs) > len(FACILITIES) or any(type(key) is not str or key not in FACILITIES for key in needs) or len(set(needs)) != len(needs):
        unavailable()
    distance = value['maxDistanceKm']
    if type(distance) not in (int, float) or not 1 <= distance <= 150 or not math.isfinite(distance):
        unavailable()
    return dict(coursePriority=value['coursePriority'], facilities=sorted(needs), hideVisited=value['hideVisited'], maxDistanceKm=distance)


def rank_courses(candidates, preferences, *, visited=frozenset(), hidden=frozenset(), liked=frozenset(), limit=12):
    """Rank normalized available facts; no mutable DB/network work or location log."""
    key = preferences['coursePriority']
    ranked = []
    for candidate in candidates:
        identifier = candidate['id']
        if identifier in hidden or (preferences['hideVisited'] and identifier in visited):
            continue
        if candidate['straightLineMeters'] > preferences['maxDistanceKm'] * 1000:
            continue
        reason = ['nearbyStart' if key == 'nearby' else 'fewerPlaces' if key == 'fewStops' else 'morePlaces']
        if visited and identifier not in visited:
            reason.append('notInPermittedHistory')
        if identifier in liked:
            reason.append('likedByYou')
        ranked.append(dict(candidate, reasons=reason))
    def order(item):
        amount = item['placeCount'] if key == 'fewStops' else -item['placeCount'] if key == 'manyStops' else item['straightLineMeters']
        return (0 if item['id'] in liked else 1), amount, item['straightLineMeters'], item['id'], item['version']
    return sorted(ranked, key=order)[:limit]


import asyncio
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
import psycopg
from fastapi import APIRouter, Request, Response
from starlette.concurrency import run_in_threadpool
from private_records import VisitCipher
from team_discovery import anchor, distance
from native_functional_identity import request_actor,transaction_actor,business_json
from native_principal import is_native_principal
from rest_stop_data import DATASET
from studio import IDENTIFIER, validate_pack
from team_data import changed

DEFAULTS = dict(coursePriority='nearby', facilities=[], hideVisited=False, maxDistanceKm=50)
SOURCE_KEYS = ('datasetId','name','publisher','catalogUrl','license','catalogModifiedAt','downloadObservedAt','csvSha256','dataAsOf','rowCount','unknownDirectionCount','foodNameCount')


class TeamRecommendations:
    def __init__(self, auth, history, content):
        self.auth, self.history, self.content = auth, history, Path(content)
        self.dsn, self.enabled = auth.dsn, auth.enabled
        from recommendation_learning import RecommendationLearning
        self.learning = RecommendationLearning(self)

    @staticmethod
    def empty():
        return dict(configured=False, preferences=dict(DEFAULTS, facilities=[]), permissions=dict(useHistory=False, useFeedback=False), feedback={})

    def load(self, conn, owner, *, write=False):
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ('recommendations:'+owner,))
        row = conn.execute('SELECT revision,protected FROM team_recommendations WHERE account_id=%s' + (' FOR UPDATE' if write else ' FOR SHARE'), (owner,)).fetchone()
        if row is None:
            return 0, self.empty()
        value = VisitCipher().restore('team-recommendations', owner, row[1])
        if not isinstance(value, dict) or set(value) != {'configured','preferences','permissions','feedback'} or type(value['configured']) is not bool:
            unavailable(503,'Recommendation settings unavailable')
        explicit_preferences(value['preferences'])
        if not isinstance(value['permissions'],dict) or set(value['permissions']) != {'useHistory','useFeedback'} or any(type(v) is not bool for v in value['permissions'].values()) or not isinstance(value['feedback'], dict) or len(value['feedback']) > 200:
            unavailable(503,'Recommendation permissions unavailable')
        if any(not isinstance(k,str)or len(k)>100 or v not in ('like','notInterested') for k,v in value['feedback'].items()):
            unavailable(503,'Recommendation feedback unavailable')
        return row[0], value

    def save(self, conn, owner, revision, value):
        encrypted = VisitCipher().protect('team-recommendations', owner, value)
        conn.execute('INSERT INTO team_recommendations(account_id,revision,protected)VALUES(%s,%s,%s) ON CONFLICT(account_id)DO UPDATE SET revision=excluded.revision,protected=excluded.protected,updated_at=now()', (owner,revision+1,encrypted))
        changed(conn, owner, 'recommendations')
        return self.public(revision+1, value)

    @staticmethod
    def public(revision, value):
        return dict(revision=revision, configured=value['configured'], preferences=value['preferences'], permissions=value['permissions'], feedbackCount=len(value['feedback']), algorithm='explicit-rules-v1', aiUsed=False)

    def course(self, checksum):
        if not isinstance(checksum,str) or not re.fullmatch('[a-f0-9]{64}',checksum):
            unavailable(503,'Approved course unavailable')
        path = self.content/checksum
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 262144:
            unavailable(503,'Approved course unavailable')
        with path.open('rb') as source:
            raw = source.read(262145)
        if len(raw)>262144 or hashlib.sha256(raw).hexdigest()!=checksum:
            unavailable(503,'Approved course integrity changed')
        try:
            return validate_pack(json.loads(raw))
        except (ValueError,KeyError,TypeError,OverflowError):
            unavailable(503,'Approved course unavailable')

    def query(self, conn, owner, data, *, native=False):
        if set(data) not in ({'settingsRevision','anchor','preferences','dismissed'}, {'settingsRevision','anchor','preferences','dismissed','learningRevision'}):
            unavailable()
        learning_requested = 'learningRevision' in data
        preferences = explicit_preferences(data['preferences'])
        revision,value = self.load(conn,owner)
        self.expected(revision,data['settingsRevision'])
        dismissed = data['dismissed']
        if not isinstance(dismissed,list) or len(dismissed)>200 or any(not isinstance(v,str)or len(v)>100 for v in dismissed):
            unavailable(400,'Invalid dismissed candidates')
        now = datetime.now(timezone.utc)
        point=data['anchor']
        if native:
            if type(point)is not dict or point.get('kind')not in('selected-place','device-location'):
                unavailable(400,'Choose a supported place or explicit device location')
            if point.get('kind')=='device-location':
                # Reuse numeric/age validation only, never Browser provenance or consent.
                lat,lon,reported=anchor(dict(point,kind='browser-location'),now)
                reported=dict(reported,kind='device-reported')
            else:lat,lon,reported=anchor(point,now)
        else:lat,lon,reported=anchor(point,now)
        visited = set();history_count = 0
        if value['permissions']['useHistory']:
            for item,raw in conn.execute('SELECT history_id,protected FROM team_histories WHERE owner_id=%s ORDER BY updated_at DESC,history_id DESC LIMIT 100',(owner,)):
                record = self.history.restore('record',owner,item,raw)
                history_count += 1
                if record['courseId'] is not None:
                    visited.add(record['courseId'])
        elif preferences['hideVisited']:
            unavailable(409,'Allow personal history use before hiding visited courses')
        feedback = value['feedback'] if value['permissions']['useFeedback'] else {}
        hidden = set(dismissed)|{key for key,label in feedback.items()if label=='notInterested'}
        liked = {key for key,label in feedback.items()if label=='like'}
        candidates = []
        rows = conn.execute(f"SELECT DISTINCT ON(p.pack_id)p.pack_id,p.version,p.title,p.author,p.description,p.stop_count,p.checksum FROM pack_versions p LEFT JOIN pack_reviews r USING(checksum) WHERE {COURSE_AVAILABLE} ORDER BY p.pack_id,p.version DESC LIMIT 100").fetchall()
        for identifier,version,title,author,description,count,checksum in rows:
            if not available(conn, checksum, lock=True):
                continue
            pack = self.course(checksum)
            if pack['id']!=identifier or pack['version']!=version or len(pack['stops'])!=count:
                unavailable(503,'Approved course identity changed')
            candidates.append(dict(id=identifier,version=version,title=title,author=author,description=description,checksum=checksum,placeCount=count,straightLineMeters=round(distance(lat,lon,pack['stops'][0])),visitedBefore=(identifier in visited)if value['permissions']['useHistory']else None))
        courses = rank_courses(candidates,preferences,visited=visited,hidden={key[7:]for key in hidden if key.startswith('course:')},liked={key[7:]for key in liked if key.startswith('course:')},limit=100 if learning_requested else 12)
        learning_status = None
        if learning_requested:
            courses, learning_status = self.learning.rerank(conn,owner,value,data['learningRevision'],courses)
        stops = []
        for item in DATASET['items']:
            if 'rest:'+item['id'] in hidden or any(item['facilities'][key]is not True for key in preferences['facilities']):
                continue
            meters = distance(lat,lon,item)
            if meters>preferences['maxDistanceKm']*1000:
                continue
            reasons=['nearbyFacilities']
            if preferences['facilities']:reasons.append('requiredFacilities')
            if 'rest:'+item['id'] in liked:reasons.append('likedByYou')
            stops.append(dict(id=item['id'],place=dict(id=item['id'],provider='official-rest-snapshot',name=item['name'],address='',latitude=item['latitude'],longitude=item['longitude']),facilities=dict(item['facilities']),road=dict(routeName=item['routeName'],reportedDirection=item['reportedDirection'],direction=item['direction']),dataAsOf=item['dataAsOf'],straightLineMeters=round(meters),routeDistanceMeters=None,travelSeconds=None,currentOpen=None,price=None,chargerAvailable=None,coordinateVerifiedAt=None,reasons=reasons))
        stops.sort(key=lambda item:(0 if 'rest:'+item['id']in liked else 1,item['straightLineMeters'],item['id']))
        return dict(settingsRevision=revision,courses=courses,restStops=stops[:12],source={k:DATASET['source'][k]for k in SOURCE_KEYS},preferences=preferences,anchor=reported,queriedAt=now.isoformat(),algorithm='personal-logistic-v1' if learning_status and learning_status['aiUsed'] else 'explicit-rules-v1',aiUsed=bool(learning_status and learning_status['aiUsed']),**({'learning':learning_status} if learning_requested else {}),historyUsed=value['permissions']['useHistory'],historyLimit=100,historyConsidered=history_count,feedbackUsed=value['permissions']['useFeedback'],courseCatalogLimit=100,unsupported=dict(roadRouting=True,routeTime=True,livePrice=True,fuelHabitInference=True,namedFood=True,modelTraining=not learning_requested))

    @staticmethod
    def expected(revision, expected):
        if type(expected)is not int or not 0<=expected<=2147483647:
            unavailable(400,'Invalid recommendation revision')
        if revision!=expected:
            unavailable(409,'Recommendation settings changed; reload')

    def router(self):
        router=APIRouter()
        if not self.enabled:return router
        async def body(request):
            raw=bytearray()
            try:
                async with asyncio.timeout(5):
                    async for chunk in request.stream():
                        raw.extend(chunk)
                        if len(raw)>16384:unavailable(413,'Recommendation request too large')
            except TimeoutError:unavailable(408,'Recommendation request timed out')
            try:
                value=business_json(request,raw,maximum=16384)
            except (ValueError,UnicodeError,RecursionError):unavailable()
            if not isinstance(value,dict):unavailable()
            return value
        async def begin(request,limit):
            identity=await run_in_threadpool(request_actor,self.auth,request,mutate=True)
            await run_in_threadpool(self.auth.rate,('recommendation-query:' if limit==60 else 'recommendation-write:')+identity['id'],limit=limit)
            return identity['id']
        def fresh(conn,request,expected):
            owner=transaction_actor(self.auth,request,conn,mutate=True)['id']
            if owner!=expected:unavailable(401,'Recommendation account changed')
            return owner
        @router.get('/v1/recommendations/learning')
        def learning_status(request:Request):
            with psycopg.connect(self.dsn) as conn:
                owner=self.auth.browser(request,connection=conn)['id']
                revision,value=self.load(conn,owner)
                return dict(self.learning.view(conn,owner,value),settingsRevision=revision)
        @router.put('/v1/recommendations/learning')
        async def learning_consent(request:Request):
            actor=await begin(request,30);data=await body(request)
            if set(data)!={'revision','recommendationRevision','consent'} or data['consent'] is not True:unavailable()
            def enable():
                with psycopg.connect(self.dsn) as conn:
                    owner=fresh(conn,request,actor)
                    revision,value=self.load(conn,owner,write=True)
                    self.expected(revision,data['recommendationRevision'])
                    return self.learning.allow(conn,owner,revision,value,data['revision'])
            return await run_in_threadpool(enable)
        @router.delete('/v1/recommendations/learning')
        def learning_withdraw(request:Request):
            with psycopg.connect(self.dsn) as conn:
                owner=self.auth.browser(request,mutate=True,connection=conn)['id']
                self.auth.rate('recommendation-write:'+owner,limit=30)
                revision,value=self.load(conn,owner,write=True)
                result=self.learning.clear(conn,owner)
                result['settingsRevision']=self.save(conn,owner,revision,value)['revision']
                return result
        @router.get('/v1/recommendations/settings')
        def settings(request:Request):
            with psycopg.connect(self.dsn)as conn:
                native=is_native_principal(getattr(request.state,'device_identity',None))
                if native:conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
                owner=transaction_actor(self.auth,request,conn)['id']
                revision,value=self.load(conn,owner)
                result=self.public(revision,value)
                if native:result['learning']=dict(self.learning.view(conn,owner,value),settingsRevision=revision)
                return result
        @router.put('/v1/recommendations/settings')
        async def save_settings(request:Request):
            actor=await begin(request,30);data=await body(request)
            if set(data)!={'revision','preferences','permissions'}:unavailable()
            preferences=explicit_preferences(data['preferences']);permissions=data['permissions']
            if not isinstance(permissions,dict)or set(permissions)!={'useHistory','useFeedback'}or any(type(v)is not bool for v in permissions.values()):unavailable()
            if preferences['hideVisited']and not permissions['useHistory']:unavailable(400,'History filter needs explicit history permission')
            def write():
                with psycopg.connect(self.dsn)as conn:
                    owner=fresh(conn,request,actor)
                    revision,value=self.load(conn,owner,write=True);self.expected(revision,data['revision'])
                    value.update(configured=True,preferences=preferences,permissions=permissions)
                    if not permissions['useFeedback']:
                        value['feedback']={}
                        self.learning.clear(conn,owner)
                    return self.save(conn,owner,revision,value)
            return await run_in_threadpool(write)
        @router.delete('/v1/recommendations/settings')
        def withdraw(request:Request):
            with psycopg.connect(self.dsn)as conn:
                owner=self.auth.browser(request,mutate=True,connection=conn)['id'];self.auth.rate('recommendation-write:'+owner,limit=30)
                revision,_=self.load(conn,owner,write=True)
                self.learning.clear(conn,owner)
                return self.save(conn,owner,revision,self.empty())
        @router.post('/v1/recommendations/query')
        async def recommend(request:Request,response:Response):
            actor=await begin(request,60);data=await body(request)
            def calculate():
                with psycopg.connect(self.dsn)as conn:return self.query(conn,fresh(conn,request,actor),data,native=is_native_principal(getattr(request.state,'device_identity',None)))
            response.headers['Cache-Control']='private, no-store'
            return await run_in_threadpool(calculate)
        @router.post('/v1/recommendations/feedback')
        async def feedback(request:Request):
            actor=await begin(request,30);data=await body(request)
            if set(data)not in ({'revision','kind','id','version','response'}, {'revision','kind','id','version','response','learningRevision'})or data['kind']not in('course','rest')or data['response']not in('like','notInterested')or not isinstance(data['id'],str):unavailable()
            def record():
                with psycopg.connect(self.dsn)as conn:
                    owner=fresh(conn,request,actor)
                    revision,value=self.load(conn,owner,write=True);self.expected(revision,data['revision'])
                    if not value['permissions']['useFeedback']:unavailable(403,'Explicit recommendation feedback permission required')
                    if data['kind']=='course':
                        if not IDENTIFIER.fullmatch(data['id'])or type(data['version'])is not int or not 1<=data['version']<=2147483647 or not conn.execute(f"SELECT 1 FROM pack_versions p LEFT JOIN pack_reviews r USING(checksum)WHERE p.pack_id=%s AND p.version=%s AND {COURSE_AVAILABLE}",(data['id'],data['version'])).fetchone():unavailable(404,'Recommendation unavailable')
                    elif data['version']is not None or data['id']not in{item['id']for item in DATASET['items']}:
                        unavailable(404,'Recommendation unavailable')
                    key=data['kind']+':'+data['id']
                    if key not in value['feedback']and len(value['feedback'])>=200:unavailable(409,'Recommendation feedback limit reached; clear settings')
                    learned = None
                    if 'learningRevision' in data:
                        learned = self.learning.label(conn,owner,value,data['learningRevision'],data)
                    value['feedback'][key]=data['response']
                    result = self.save(conn,owner,revision,value)
                    if learned is not None:result['learningRevision']=learned
                    return result
            return await run_in_threadpool(record)
        return router
