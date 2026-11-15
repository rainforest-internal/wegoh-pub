"""Browser-only public course discovery, personal stars and creator news."""
from course_publication import COURSE_AVAILABLE
from collections import Counter
import re
from uuid import UUID

import psycopg
from fastapi import APIRouter, HTTPException, Query, Request, Response
from studio import IDENTIFIER, normalize_course_tag
from team_friends import blocked
from team_rooms import TeamRooms
from native_principal import is_native_principal
from psycopg.rows import dict_row


NEWS = f"""
    SELECT p.pack_id,p.version,p.title,p.author,p.description,p.stop_count,
           own.account_id IS NOT NULL,
           (SELECT count(*) FROM team_course_stars s
            WHERE s.pack_id=p.pack_id AND s.version=p.version),p.tags,
           f.creator_id,f.follow_id::text,e.event_id,e.created_at,n.event_id IS NOT NULL
    FROM team_creator_follows f
    JOIN team_accounts a ON a.account_id=f.creator_id AND a.account_status='active'
    JOIN pack_versions p ON p.creator_id=f.creator_id
    JOIN LATERAL (
        SELECT event_id,p.created_at FROM pack_review_events
        WHERE checksum=p.checksum
        ORDER BY event_id LIMIT 1
    ) e ON e.created_at>f.followed_at
    LEFT JOIN team_course_stars own ON (own.pack_id,own.version,own.account_id)=(p.pack_id,p.version,f.follower_id)
    LEFT JOIN team_course_news_reads n ON (n.follow_id,n.event_id)=(f.follow_id,e.event_id)
    WHERE f.follower_id=%s AND {COURSE_AVAILABLE}
"""
COURSE_FIELDS = ('id', 'version', 'title', 'author', 'description', 'stopCount', 'starred', 'starCount', 'tags')


def create_course_library_router(auth):
    router = APIRouter()
    if not auth.enabled:
        return router
    dsn = auth.dsn

    def current_browser(request, conn, *, mutate=False):
        if request.url.path.startswith('/v1/iphone/courses/'):
            TeamRooms.graph_lock(conn)
            identity = auth.iphone_sessions.authenticate(request, 'courses:write' if mutate else 'courses:read',
                connection=conn, lock=mutate)
            return identity['id']
        if request.url.path.startswith('/v1/native/courses/'):
            initial = getattr(request.state, 'device_identity', None)
            if mutate or not is_native_principal(initial):
                raise HTTPException(404, 'Not found')
            TeamRooms.graph_lock(conn)
            row = conn.execute('SELECT installation_key_id FROM native_v2_grants WHERE grant_id=%s', (initial['grantId'],)).fetchone()
            if not row:
                raise HTTPException(401, 'INVALID_CREDENTIAL')
            auth.native_authorization.lock(conn, row[0])
            factory = conn.row_factory
            try:
                conn.row_factory = dict_row
                current = auth.device(request, connection=conn)
            finally:
                conn.row_factory = factory
            if any(current[key] != initial[key] for key in ('id', 'grantId', 'credentialEpoch', 'slotRevision')):
                raise HTTPException(401, 'INVALID_CREDENTIAL')
            return current['id']
        if getattr(request.state, 'device_identity', None) is not None:
            raise HTTPException(404, 'Not found')
        return auth.browser(request, mutate=mutate, connection=conn)['id']

    def can_follow(conn, actor, creator):
        if not isinstance(creator, str) or not re.fullmatch(r'team-[a-f0-9]{40}', creator):
            return False
        if actor == creator or blocked(conn, actor, creator):
            return False
        try:
            auth.current_account(creator)
        except HTTPException as error:
            if error.status_code not in (401, 403):
                raise
            return False
        return True

    def private(response):
        response.headers['Cache-Control'] = 'private, no-store'

    @router.get('/v1/studio/course-library')
    def course_library(request: Request, response: Response, tag: str | None = Query(
            default=None, description='공개 코스에만 적용하는 태그입니다. 앞의 #과 대소문자를 무시하고 정확히 일치하는 태그를 찾습니다.')):
        with psycopg.connect(dsn) as conn:
            account = current_browser(request, conn)
            try:
                tag_key = normalize_course_tag(tag).casefold() if tag else None
            except ValueError as error:
                raise HTTPException(400, str(error)) from None
            rows = conn.execute(f"""
                WITH published AS (
                    SELECT p.*, max(p.version) OVER (PARTITION BY p.pack_id) AS latest
                    FROM pack_versions p LEFT JOIN pack_reviews r USING(checksum)
                    WHERE {COURSE_AVAILABLE}
                )
                SELECT p.pack_id,p.version,p.title,p.author,p.description,p.stop_count,
                       own.account_id IS NOT NULL,
                       (SELECT count(*) FROM team_course_stars s
                        WHERE s.pack_id=p.pack_id AND s.version=p.version),p.tags,
                       p.version=p.latest,p.creator_id,
                       a.account_status='active',f.follow_id::text,
                       (SELECT count(*) FROM team_course_stars s
                        WHERE s.pack_id=p.pack_id AND s.version=p.version AND s.account_id<>p.creator_id)
                FROM published p
                LEFT JOIN team_course_stars own
                    ON (own.pack_id,own.version,own.account_id)=(p.pack_id,p.version,%s)
                LEFT JOIN team_accounts a ON a.account_id=p.creator_id
                LEFT JOIN team_creator_follows f ON f.creator_id=p.creator_id AND f.follower_id=%s
                WHERE p.version=p.latest OR own.account_id IS NOT NULL
                ORDER BY p.pack_id,p.version DESC
            """, (account, account)).fetchall()
            subscriptions = conn.execute(f"""
                SELECT f.follow_id::text,f.creator_id,(
                    SELECT p.author FROM pack_versions p LEFT JOIN pack_reviews r USING(checksum)
                    WHERE p.creator_id=f.creator_id AND {COURSE_AVAILABLE}
                    ORDER BY p.created_at DESC,p.pack_id,p.version DESC LIMIT 1
                ) FROM team_creator_follows f WHERE f.follower_id=%s
                ORDER BY f.followed_at DESC,f.follow_id
            """, (account,)).fetchall()
            allowed = {}
            def visible(creator):
                if creator not in allowed:
                    allowed[creator] = can_follow(conn, account, creator)
                return allowed[creator]

            popularity = Counter()
            for *_, latest, creator, active, _, other_stars in rows:
                if latest and active and other_stars:
                    popularity[creator] += other_stars
            leaders = sorted(popularity, key=lambda creator: (-popularity[creator], creator))[:3]
            ranks = {creator: rank for rank, creator in enumerate(leaders, 1)}
            public, saved = [], []
            for row in rows:
                latest, creator, active, follow_id, _ = row[len(COURSE_FIELDS):]
                followable = bool(active and visible(creator))
                item = dict(zip(COURSE_FIELDS, row), canFollow=followable,
                            followId=follow_id if followable else None, creatorRank=ranks.get(creator))
                if latest and (tag_key is None or any(value.casefold() == tag_key for value in item['tags'])):
                    public.append(item)
                if item['starred']:
                    saved.append(item)
            news = []
            # Limit after checking the encrypted block state of each followed creator.
            cursor = conn.execute(NEWS + ' ORDER BY e.event_id DESC', (account,))
            for row in cursor:
                creator, follow_id, event_id, approved_at, read = row[len(COURSE_FIELDS):]
                if not visible(creator):
                    continue
                news.append(dict(zip(COURSE_FIELDS, row), canFollow=True, followId=follow_id,
                                 creatorRank=ranks.get(creator), eventId=str(event_id),
                                 approvedAt=approved_at, read=read))
                if len(news) == 30:
                    break
            following = [dict(id=follow_id, name=name if visible(creator) else None)
                         for follow_id, creator, name in subscriptions]
        private(response)
        return dict(public=public, saved=saved, news=news, following=following)

    @router.put('/v1/studio/course-stars/{pack_id}/versions/{version}')
    @router.delete('/v1/studio/course-stars/{pack_id}/versions/{version}')
    def update_course_star(pack_id: str, version: int, request: Request, response: Response):
        if getattr(request.state, 'device_identity', None) is not None:
            raise HTTPException(404, 'Not found')
        if not IDENTIFIER.fullmatch(pack_id) or not 1 <= version <= 2147483647:
            raise HTTPException(404, 'Course unavailable')
        starred = request.method == 'PUT'
        with psycopg.connect(dsn) as conn:
            account = current_browser(request, conn, mutate=True)
            auth.rate('course-star:' + account)
            if starred:
                # The same lock serializes publication and moderation for this course.
                conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', (pack_id,))
                approved = conn.execute(
                    'SELECT p.creator_id FROM pack_versions p LEFT JOIN pack_reviews r USING(checksum) '
                    f"WHERE p.pack_id=%s AND p.version=%s AND {COURSE_AVAILABLE}",
                    (pack_id, version)).fetchone()
                if not approved:
                    raise HTTPException(404, 'Course unavailable')
                if request.url.path.startswith('/v1/iphone/'):
                    from team_course_discovery import CourseDiscovery
                    if not CourseDiscovery(auth, current_browser).visible(conn, account, approved[0]):
                        raise HTTPException(404, 'Course unavailable')
                conn.execute('INSERT INTO team_course_stars(pack_id,version,account_id) '
                             'VALUES(%s,%s,%s) ON CONFLICT DO NOTHING', (pack_id, version, account))
            else:
                conn.execute('DELETE FROM team_course_stars WHERE pack_id=%s AND version=%s AND account_id=%s',
                             (pack_id, version, account))
        response.headers['Cache-Control'] = 'private, no-store'
        return dict(starred=starred)

    @router.put('/v1/studio/course-follows/{pack_id}/versions/{version}')
    def follow_creator(pack_id: str, version: int, request: Request, response: Response):
        if not IDENTIFIER.fullmatch(pack_id) or not 1 <= version <= 2147483647:
            raise HTTPException(404, 'Course unavailable')
        with psycopg.connect(dsn) as conn:
            actor = current_browser(request, conn, mutate=True)
            auth.rate('creator-follow:' + actor)
            TeamRooms.graph_lock(conn)
            conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', (pack_id,))
            course = conn.execute(
                'SELECT p.creator_id FROM pack_versions p LEFT JOIN pack_reviews r USING(checksum) '
                f"WHERE p.pack_id=%s AND p.version=%s AND {COURSE_AVAILABLE}", (pack_id, version)).fetchone()
            if not course or not can_follow(conn, actor, course[0]):
                raise HTTPException(404, 'Creator unavailable')
            creator = course[0]
            conn.execute('INSERT INTO team_creator_follows(follower_id,creator_id) VALUES(%s,%s) '
                         'ON CONFLICT DO NOTHING', (actor, creator))
            follow_id = conn.execute('SELECT follow_id::text FROM team_creator_follows '
                                     'WHERE follower_id=%s AND creator_id=%s', (actor, creator)).fetchone()[0]
        private(response)
        return dict(followId=follow_id)

    @router.delete('/v1/studio/course-follows/{follow_id}')
    def unfollow_creator(follow_id: UUID, request: Request, response: Response):
        with psycopg.connect(dsn) as conn:
            actor = current_browser(request, conn, mutate=True)
            auth.rate('creator-follow:' + actor)
            TeamRooms.graph_lock(conn)
            conn.execute('DELETE FROM team_creator_follows WHERE follower_id=%s AND follow_id=%s',
                         (actor, follow_id))
        private(response)
        return dict(following=False)

    @router.put('/v1/studio/course-news/{event_id}/read')
    def read_news(event_id: int, request: Request, response: Response):
        if not 1 <= event_id <= 9223372036854775807:
            raise HTTPException(404, 'Course news unavailable')
        with psycopg.connect(dsn) as conn:
            actor = current_browser(request, conn, mutate=True)
            auth.rate('course-news:' + actor)
            TeamRooms.graph_lock(conn)
            row = conn.execute(NEWS + ' AND e.event_id=%s', (actor, event_id)).fetchone()
            if not row or not can_follow(conn, actor, row[len(COURSE_FIELDS)]):
                raise HTTPException(404, 'Course news unavailable')
            follow_id = row[len(COURSE_FIELDS)+1]
            conn.execute('INSERT INTO team_course_news_reads(follow_id,event_id) VALUES(%s,%s) '
                         'ON CONFLICT DO NOTHING', (follow_id, event_id))
        private(response)
        return dict(read=True)

    from team_course_discovery import install
    install(router, auth, current_browser, update_course_star, follow_creator, unfollow_creator, read_news)
    return router
