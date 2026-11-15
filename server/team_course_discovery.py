from course_publication import COURSE_AVAILABLE, available
from collections import Counter
import hashlib
import json
import re
import unicodedata

from fastapi import HTTPException, Query, Request, Response
import psycopg
from psycopg.rows import dict_row
from starlette.concurrency import run_in_threadpool

from native_access_codec import CodecError, decode_json
from studio import COVER_STORED_LIMIT, IDENTIFIER, normalize_course_tag, normalize_course_tags
from team_friends import blocked


ACCOUNT = re.compile(r'team-[a-f0-9]{40}\Z')


def fail(status=400, message='Invalid course request'):
    raise HTTPException(status, message)


def selectors(request):
    pairs = list(request.query_params.multi_items())
    if (any(key not in ('q', 'tag') for key, _ in pairs) or sum(key == 'q' for key, _ in pairs) > 1
            or sum(key == 'tag' for key, _ in pairs) > 8):
        fail()
    q = unicodedata.normalize('NFC', request.query_params.get('q', '').strip()).removeprefix('#')
    if len(q) > 100 or any(ord(char) < 32 for char in q):
        fail()
    try:
        tags = normalize_course_tags(request.query_params.getlist('tag'))
    except ValueError as error:
        fail(400, str(error))
    return q.casefold(), {tag.casefold() for tag in tags}


async def empty_body(request):
    from iphone_sessions import body
    raw = await body(request, 'application/json', maximum_bytes=4096)
    if not raw:
        return
    try:
        value = decode_json(bytes(raw), maximum_bytes=4096)
    except CodecError:
        fail()
    if value != {}:
        fail()


class CourseDiscovery:
    def __init__(self, auth, actor):
        self.auth, self.actor = auth, actor

    def visible(self, conn, account, creator):
        if not isinstance(creator, str) or not ACCOUNT.fullmatch(creator):
            return False
        if creator != account and blocked(conn, account, creator):
            return False
        try:
            self.auth.current_account(creator, connection=conn)
        except HTTPException as error:
            if error.status_code in (401, 403):
                return False
            raise
        return True

    def courses(self, conn, account):
        with conn.cursor(row_factory=dict_row) as cursor:
            rows = cursor.execute('SELECT p.pack_id AS id,p.version,p.title,p.author,p.description,p.stop_count AS "stopCount",'
                'p.tags,p.creator_id AS "creatorId",p.checksum,'
                'EXISTS(SELECT 1 FROM pack_course_covers c WHERE c.pack_id=p.pack_id AND c.version=p.version) AS "hasCover",'
                'EXISTS(SELECT 1 FROM team_course_stars s WHERE s.pack_id=p.pack_id AND s.version=p.version AND s.account_id=%s) AS starred,'
                '(SELECT count(*) FROM team_course_stars s WHERE s.pack_id=p.pack_id AND s.version=p.version) AS "starCount",'
                '(SELECT count(*) FROM team_course_stars s WHERE s.pack_id=p.pack_id AND s.version=p.version AND s.account_id<>p.creator_id) AS other_stars,'
                '(SELECT follow_id::text FROM team_creator_follows f WHERE f.follower_id=%s AND f.creator_id=p.creator_id) AS "followId" '
                f"FROM pack_versions p LEFT JOIN pack_reviews r USING(checksum) WHERE {COURSE_AVAILABLE} ORDER BY p.pack_id,p.version DESC",
                (account, account)).fetchall()
        names = getattr(self.auth, 'course_stop_names', None)
        if names is None:
            fail(503, 'Course storage unavailable')
        allowed, latest, result = {}, {}, []
        for row in rows:
            creator = row['creatorId']
            if creator not in allowed:
                allowed[creator] = self.visible(conn, account, creator)
            if not allowed[creator]:
                continue
            latest.setdefault(row['id'], row['version'])
            result.append(dict(row, stopNames=list(names(row['checksum'])), canFollow=creator != account, creatorRank=None))
        popularity = Counter()
        for row in result:
            if row['version'] == latest[row['id']] and row['other_stars']:
                popularity[row['creatorId']] += row['other_stars']
        ranks = {creator: rank for rank, creator in enumerate(sorted(popularity, key=lambda key: (-popularity[key], key))[:3], 1)}
        for row in result:
            row['creatorRank'] = ranks.get(row['creatorId'])
            row.pop('other_stars')
        return result, latest

    def feed(self, conn, account, courses):
        creators = dict(conn.execute('SELECT creator_id,followed_at FROM team_creator_follows WHERE follower_id=%s', (account,)))
        tags = dict(conn.execute('SELECT tag_key,followed_at FROM team_course_tag_follows WHERE account_id=%s', (account,)))
        if not creators and not tags:
            return []
        indexed = {(item['id'], item['version']): item for item in courses}
        rows = conn.execute('SELECT p.pack_id,p.version,e.event_id,e.created_at,'
            'EXISTS(SELECT 1 FROM team_course_discovery_reads r WHERE r.account_id=%s AND r.event_id=e.event_id) OR '
            'EXISTS(SELECT 1 FROM team_course_news_reads r JOIN team_creator_follows f USING(follow_id) '
            'WHERE f.follower_id=%s AND r.event_id=e.event_id) FROM pack_versions p '
            'JOIN LATERAL (SELECT event_id,p.created_at FROM pack_review_events WHERE checksum=p.checksum '
            'ORDER BY event_id LIMIT 1) e ON true ORDER BY e.event_id DESC', (account, account))
        result = []
        for pack, version, event, approved, read in rows:
            item = indexed.get((pack, version))
            if item is None:
                continue
            starts = ([creators[item['creatorId']]] if item['creatorId'] in creators else []) + [tags[tag.casefold()]
                for tag in item['tags'] if tag.casefold() in tags]
            if not starts or not any(approved > started for started in starts):
                continue
            result.append(dict(item, eventId=str(event), approvedAt=approved, read=read))
            if len(result) == 30:
                break
        return result

    def library(self, conn, account, q, tags):
        courses, latest = self.courses(conn, account)
        hidden = set(conn.execute('SELECT pack_id,version FROM team_course_hidden WHERE account_id=%s', (account,)))
        public = [item for item in courses if item['version'] == latest[item['id']] and (item['id'], item['version']) not in hidden]
        labels = {}
        counts = Counter()
        for item in public:
            for tag in item['tags']:
                labels.setdefault(tag.casefold(), tag)
                counts[tag.casefold()] += 1
        popular = [labels[key] for key in sorted(counts, key=lambda key: (-counts[key], key))[:1000]]
        public = [item for item in public if (not q or q in (' '.join(str(item[key]) for key in ('title', 'description', 'author')) + ' ' + ' '.join(item['tags'])).casefold())
            and tags <= {tag.casefold() for tag in item['tags']}]
        public.sort(key=lambda item: (-item['starCount'], item['creatorRank'] or 4, item['id']))
        following = []
        for follow, creator in conn.execute('SELECT follow_id::text,creator_id FROM team_creator_follows '
                'WHERE follower_id=%s ORDER BY followed_at DESC,follow_id', (account,)):
            visible = self.visible(conn, account, creator)
            following.append(dict(id=follow, name=self.auth.current_account(creator, connection=conn)['displayName'] if visible else None,
                creatorId=creator if visible else None))
        news = self.feed(conn, account, courses)
        return dict(public=public[:1000], saved=[item for item in courses if item['starred']][:1000], news=news[:30], following=following[:1000],
            popularTags=popular, followedTags=[row[0] for row in conn.execute('SELECT tag FROM team_course_tag_follows '
                'WHERE account_id=%s ORDER BY followed_at,tag_key LIMIT 1000', (account,))], unreadCount=sum(not item['read'] for item in news))

    def detail(self, conn, account, pack, version):
        if not IDENTIFIER.fullmatch(pack) or not 1 <= version <= 2147483647:
            fail(404, 'Course unavailable')
        with conn.cursor(row_factory=dict_row) as cursor:
            item = cursor.execute(
                'SELECT p.checksum,p.tags,p.creator_id AS "creatorId",'
                'EXISTS(SELECT 1 FROM pack_course_covers c WHERE c.pack_id=p.pack_id AND c.version=p.version) AS "hasCover",'
                'EXISTS(SELECT 1 FROM team_course_stars s WHERE s.pack_id=p.pack_id AND s.version=p.version AND s.account_id=%s) AS starred,'
                '(SELECT count(*) FROM team_course_stars s WHERE s.pack_id=p.pack_id AND s.version=p.version) AS "starCount",'
                '(SELECT follow_id::text FROM team_creator_follows f WHERE f.follower_id=%s AND f.creator_id=p.creator_id) AS "followId" '
                f'FROM pack_versions p WHERE p.pack_id=%s AND p.version=%s AND {COURSE_AVAILABLE}',
                (account, account, pack, version)).fetchone()
        if item is None or not self.visible(conn, account, item['creatorId']):
            fail(404, 'Course unavailable')
        reader = getattr(self.auth, 'course_pack_reader', None)
        if reader is None:
            fail(503, 'Course storage unavailable')
        raw = reader(item['checksum'])
        if hashlib.sha256(raw).hexdigest() != item['checksum']:
            fail(503, 'Course integrity check failed')
        return dict(pack=json.loads(raw), canFollow=item['creatorId'] != account, **item)


def install(router, auth, actor, star, follow, unfollow, old_read_news):
    service = CourseDiscovery(auth, actor)

    def connection():
        return psycopg.connect(auth.dsn)

    def with_card_stops(request, items):
        # iPhone cards draw a map per course; the vehicle feed does not.
        if not request.url.path.startswith('/v1/iphone/'):
            return items
        stops = getattr(auth, 'course_card_stops', None)
        if stops is None:
            fail(503, 'Course storage unavailable')
        return [dict(item, stops=stops(item['checksum'])) for item in items]

    def identity(request, conn, response, *, mutate=False):
        response.headers['Cache-Control'] = 'private, no-store'
        if request.query_params and not request.url.path.endswith('/library'):
            fail()
        account = actor(request, conn, mutate=mutate)
        if mutate:
            auth.rate('course-discovery-write:' + account, limit=60)
        return account

    @router.get('/v1/iphone/courses/library', include_in_schema=False)
    @router.get('/v1/native/courses/library')
    def library(request: Request, response: Response, q: str | None = Query(default=None, description='제목·설명·제작자·태그 검색. 최대100자.'),
                tag: list[str] | None = Query(default=None, description='최대8개. NFC·24자 태그를 대소문자 구분 없이 AND 적용.')):
        q, tags = selectors(request)
        with connection() as conn:
            value = service.library(conn, identity(request, conn, response), q, tags)
        for key in ('public', 'saved', 'news'):
            value[key] = with_card_stops(request, value[key])
        return value

    @router.get('/v1/iphone/courses/public/{pack_id}/versions/{version}', include_in_schema=False)
    @router.get('/v1/native/courses/public/{pack_id}/versions/{version}')
    def detail(pack_id: str, version: int, request: Request, response: Response):
        with connection() as conn:
            return service.detail(conn, identity(request, conn, response), pack_id, version)

    @router.get('/v1/iphone/courses/public/{pack_id}/versions/{version}/cover', include_in_schema=False)
    def cover(pack_id: str, version: int, request: Request, response: Response):
        with connection() as conn:
            service.detail(conn, identity(request, conn, response), pack_id, version)
            row = conn.execute('SELECT image FROM pack_course_covers WHERE pack_id=%s AND version=%s',
                               (pack_id, version)).fetchone()
            if row is None:
                fail(404, 'Course cover unavailable')
            image = bytes(row[0])
            if not image or len(image) > COVER_STORED_LIMIT:
                fail(503, 'Course cover storage unavailable')
            return Response(image, media_type='image/jpeg', headers={
                'Cache-Control': 'private, no-store, no-transform', 'X-Content-Type-Options': 'nosniff'})

    @router.get('/v1/iphone/courses/creators/{creator_id}', include_in_schema=False)
    @router.get('/v1/native/courses/creators/{creator_id}')
    def creator(creator_id: str, request: Request, response: Response):
        with connection() as conn:
            account = identity(request, conn, response)
            if not ACCOUNT.fullmatch(creator_id) or not service.visible(conn, account, creator_id):
                fail(404, 'Creator unavailable')
            courses, latest = service.courses(conn, account)
            public = [item for item in courses if item['creatorId'] == creator_id and item['version'] == latest[item['id']]]
            if not public:
                fail(404, 'Creator unavailable')
            follow_id = conn.execute('SELECT follow_id::text FROM team_creator_follows WHERE follower_id=%s AND creator_id=%s',
                (account, creator_id)).fetchone()
            followers = conn.execute('SELECT count(*) FROM team_creator_follows f JOIN team_accounts a ON a.account_id=f.follower_id '
                "WHERE f.creator_id=%s AND a.account_status='active'", (creator_id,)).fetchone()[0]
            return dict(creator=dict(id=creator_id, name=auth.current_account(creator_id, connection=conn)['displayName'],
                courseCount=len(public), starCount=sum(item['starCount'] for item in public), followerCount=followers,
                following=follow_id is not None, followId=follow_id[0] if follow_id else None),
                courses=with_card_stops(request, public[:1000]))

    @router.put('/v1/iphone/courses/stars/{pack_id}/versions/{version}', include_in_schema=False)
    @router.delete('/v1/iphone/courses/stars/{pack_id}/versions/{version}', include_in_schema=False)
    async def stars(pack_id: str, version: int, request: Request, response: Response):
        await empty_body(request)
        return await run_in_threadpool(star, pack_id, version, request, response)

    @router.put('/v1/iphone/courses/follows/{pack_id}/versions/{version}', include_in_schema=False)
    async def follows(pack_id: str, version: int, request: Request, response: Response):
        await empty_body(request)
        return await run_in_threadpool(follow, pack_id, version, request, response)

    @router.delete('/v1/iphone/courses/follows/{follow_id}', include_in_schema=False)
    async def unfollows(follow_id: str, request: Request, response: Response):
        from uuid import UUID
        await empty_body(request)
        try:
            identifier = UUID(follow_id)
        except ValueError:
            fail(404, 'Subscription unavailable')
        return await run_in_threadpool(unfollow, identifier, request, response)

    @router.put('/v1/iphone/courses/tag-follows/{tag}', include_in_schema=False)
    @router.delete('/v1/iphone/courses/tag-follows/{tag}', include_in_schema=False)
    async def tag_follow(tag: str, request: Request, response: Response):
        await empty_body(request)
        try:
            normalized = normalize_course_tag(tag)
        except ValueError as error:
            fail(400, str(error))
        enabled = request.method == 'PUT'
        def write(selected_tag=normalized):
            with connection() as conn:
                account = identity(request, conn, response, mutate=True)
                if enabled:
                    courses, latest = service.courses(conn, account)
                    available = {value.casefold(): value for item in courses if item['version'] == latest[item['id']] for value in item['tags']}
                    if selected_tag.casefold() not in available:
                        fail(404, 'Tag unavailable')
                    selected_tag = available[selected_tag.casefold()]
                    conn.execute('INSERT INTO team_course_tag_follows(account_id,tag_key,tag) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING',
                        (account, selected_tag.casefold(), selected_tag))
                else:
                    conn.execute('DELETE FROM team_course_tag_follows WHERE account_id=%s AND tag_key=%s', (account, selected_tag.casefold()))
                return dict(following=enabled, tag=selected_tag)
        return await run_in_threadpool(write)

    @router.put('/v1/iphone/courses/news/{event_id}/read', include_in_schema=False)
    async def read_news(event_id: int, request: Request, response: Response):
        await empty_body(request)
        if not 1 <= event_id <= 9223372036854775807:
            fail(404, 'Course news unavailable')
        def write():
            with connection() as conn:
                account = identity(request, conn, response, mutate=True)
                courses, _ = service.courses(conn, account)
                if str(event_id) not in {item['eventId'] for item in service.feed(conn, account, courses)}:
                    fail(404, 'Course news unavailable')
                conn.execute('INSERT INTO team_course_discovery_reads(account_id,event_id) VALUES(%s,%s) ON CONFLICT DO NOTHING', (account, event_id))
                conn.execute('INSERT INTO team_course_news_reads(follow_id,event_id) SELECT f.follow_id,%s FROM team_creator_follows f '
                    'JOIN pack_versions p ON p.creator_id=f.creator_id JOIN pack_review_events e ON e.checksum=p.checksum '
                    'WHERE f.follower_id=%s AND e.event_id=%s AND p.created_at>f.followed_at ON CONFLICT DO NOTHING',
                    (event_id, account, event_id))
                return dict(read=True)
        return await run_in_threadpool(write)

    @router.put('/v1/iphone/courses/hidden/{pack_id}/versions/{version}', include_in_schema=False)
    @router.delete('/v1/iphone/courses/hidden/{pack_id}/versions/{version}', include_in_schema=False)
    async def hidden(pack_id: str, version: int, request: Request, response: Response):
        await empty_body(request)
        if not IDENTIFIER.fullmatch(pack_id) or not 1 <= version <= 2147483647:
            fail(404, 'Course unavailable')
        enabled = request.method == 'PUT'
        def write():
            with connection() as conn:
                account = identity(request, conn, response, mutate=True)
                if enabled:
                    courses, _ = service.courses(conn, account)
                    if not any(item['id'] == pack_id and item['version'] == version for item in courses):
                        fail(404, 'Course unavailable')
                    conn.execute('INSERT INTO team_course_hidden(account_id,pack_id,version) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING',
                        (account, pack_id, version))
                else:
                    conn.execute('DELETE FROM team_course_hidden WHERE account_id=%s AND pack_id=%s AND version=%s', (account, pack_id, version))
                return dict(hidden=enabled)
        return await run_in_threadpool(write)

    @router.post('/v1/iphone/courses/public/{pack_id}/versions/{version}/reports', status_code=202, include_in_schema=False)
    async def report(pack_id: str, version: int, request: Request, response: Response):
        from iphone_sessions import body
        raw = await body(request, 'application/json', maximum_bytes=4096)
        try:
            data = decode_json(raw, maximum_bytes=4096)
        except CodecError:
            fail()
        if not isinstance(data, dict) or set(data) != {'reason'} or data['reason'] not in ('harmful', 'privacy', 'rights', 'other'):
            fail(400, 'Choose a report reason')
        def write():
            with connection() as conn:
                account = identity(request, conn, response, mutate=True)
                if not IDENTIFIER.fullmatch(pack_id) or not 1 <= version <= 2147483647:
                    fail(404, 'Course unavailable')
                conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', (pack_id,))
                source = conn.execute('SELECT p.creator_id,p.checksum,(SELECT x.report_id FROM content_reports x '
                    'WHERE x.checksum=p.checksum AND x.creator_id=%s AND x.reason=%s) FROM pack_versions p '
                    'LEFT JOIN pack_reviews r USING(checksum) WHERE p.pack_id=%s AND p.version=%s',
                    (account, data['reason'], pack_id, version)).fetchone()
                if not source or not service.visible(conn, account, source[0]) or not available(conn, source[1]) and not source[2]:
                    fail(404, 'Course unavailable')
                if source[2] is not None:
                    return dict(reportId=source[2], state='quarantined')
                reporter = getattr(auth, 'course_reporter', None)
                if reporter is None:
                    fail(503, 'Course reporting unavailable')
                return reporter(conn, account, pack_id, version, data['reason'])
        return await run_in_threadpool(write)
