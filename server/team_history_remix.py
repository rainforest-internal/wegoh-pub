"""Revocable history-to-course purposes; editable drafts are not publication.

Only available original course bytes or currently permitted stored visit places
are reused. Photos, reviews, trace, names of other people and audio are not copied.
"""
import asyncio
import hashlib
import json
import os
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
import psycopg
from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool
from private_records import VisitCipher
from team_friends import ACCOUNT, linked
from studio import IDENTIFIER
from remix_sources import source_fingerprint, from_course, from_visits

KINDS = ('course', 'visits')
HEX = re.compile(r'[a-f0-9]{32}')
CHECKSUM = re.compile(r'[a-f0-9]{64}')


def fail(status=404, detail='Re-creation unavailable'):
    raise HTTPException(status, detail)


def revision(value, minimum=0):
    if type(value) is not int or not minimum <= value <= 2147483647:
        fail(400, 'Invalid re-creation revision')
    return value


class TeamHistoryRemix:
    def __init__(self, auth, history, content):
        self.auth, self.history, self.content = auth, history, Path(content)
        self.dsn, self.enabled = auth.dsn, auth.enabled

    @staticmethod
    def protect(kind, owner, key, value):
        return VisitCipher().protect('team-remix-' + kind + ':' + owner, key, value)

    @staticmethod
    def restore(kind, owner, key, raw):
        return VisitCipher().restore('team-remix-' + kind + ':' + owner, key, raw)

    def source_course(self, conn, identifier, version):
        if not isinstance(identifier, str) or not IDENTIFIER.fullmatch(identifier) or type(version) is not int or not 1 <= version <= 2147483647:
            return None
        row = conn.execute('SELECT p.creator_id,p.checksum,r.state FROM pack_versions p '
            'LEFT JOIN pack_reviews r USING(checksum) WHERE p.pack_id=%s AND p.version=%s FOR SHARE OF p',
            (identifier, version)).fetchone()
        if not row:
            return None
        from course_publication import available
        return dict(courseId=identifier, version=version, creatorId=row[0], checksum=row[1],
                    available=available(conn, row[1], lock=True), authorAvailable=bool(self.history.person(row[0])))

    def reuse_permission(self, conn, course):
        key = course['courseId'] + ':' + str(course['version'])
        row = conn.execute('SELECT revision,protected FROM team_course_reuse_permissions '
            'WHERE pack_id=%s AND version=%s FOR SHARE', (course['courseId'], course['version'])).fetchone()
        if not row:
            return 0, dict(consent=False, rightsConfirmed=False, checksum=course['checksum'])
        value = self.restore('source', course['creatorId'], key, row[1])
        if (not isinstance(value, dict) or set(value) != {'consent','rightsConfirmed','checksum'}
                or type(value['consent']) is not bool or type(value['rightsConfirmed']) is not bool
                or value['checksum'] != course['checksum']):
            fail(503, 'Source re-use permission integrity unavailable')
        return row[0], value

    def record_grant(self, conn, item, owner, target, kind):
        row = conn.execute('SELECT revision,protected FROM team_history_remix_permissions '
            'WHERE history_id=%s AND account_id=%s AND kind=%s FOR SHARE', (item, target, kind)).fetchone()
        if not row:
            return 0, dict(consent=False, rightsConfirmed=False, sourceFingerprint=None)
        value = self.restore('grant', owner, item + ':' + target + ':' + kind, row[1])
        if (not isinstance(value, dict) or set(value) != {'consent','rightsConfirmed','sourceFingerprint'}
                or type(value['consent']) is not bool or type(value['rightsConfirmed']) is not bool):
            fail(503, 'Record re-use permission integrity unavailable')
        return row[0], value

    def stored_visits(self, conn, item, row, actor, own, grant):
        if not own and not grant['visits']:
            return []
        rows = conn.execute('SELECT visit_id,protected,created_at FROM team_history_visits '
                            'WHERE history_id=%s ORDER BY created_at,visit_id', (item,)).fetchall()
        reviewed = None
        if not own:
            shared = self.history.content.shared(conn, 'history', item, row[1], self.history.projection(conn, item, row[1]))
            if shared is None:
                fail()
            ids = sorted(visit[0] for visit in rows)
            if len(ids) != len(shared['places']):
                fail(503, 'Shared visit projection unavailable')
            reviewed = dict(zip(ids, shared['places']))
        visits = []
        for identifier, raw, created in rows:
            value = self.history.restore('visit', row[1], item + ':' + identifier, raw)
            place = {key: value['place'][key] for key in ('name','latitude','longitude')}
            if reviewed is not None:
                place['name'] = reviewed[identifier]
            visits.append(dict(id=identifier, place=place, visitedAt=value['visitedAt'], storedAt=created.isoformat()))
        # Reported visit time first, then actual storage order for equal times;
        # this is not a GPS-certified route or a guessed geographic sequence.
        visits.sort(key=lambda v: (datetime.fromisoformat(v['visitedAt']), datetime.fromisoformat(v['storedAt']), v['id']))
        return visits

    def snapshot(self, conn, item, actor):
        self.history.rooms.graph_lock(conn)
        row, value, own, read_grant = self.history.row(conn, item, actor, stable=True)
        course = self.source_course(conn, value['courseId'], value['courseVersion'])
        source = None
        reuse_revision = 0
        if course:
            reuse_revision, reuse = self.reuse_permission(conn, course)
            source = {key: course[key] for key in ('courseId','version','checksum')}
            source.update(reuseRevision=reuse_revision, reuseConsent=reuse['consent'],
                          canManageReuse=actor == course['creatorId'], ownSource=actor == course['creatorId'])
        visits = self.stored_visits(conn, item, row, actor, own, read_grant)
        course_facts = dict(kind='course', historyId=item, revision=row[3], source=source and {key: source[key] for key in ('courseId','version','checksum','reuseRevision')})
        visit_facts = dict(kind='visits', historyId=item, revision=row[3], visits=visits)
        fingerprints = dict(course=source_fingerprint(course_facts), visits=source_fingerprint(visit_facts))
        paths = []
        creator_allowed = self.auth.current_account(actor)['role'] in ('creator','admin')
        for kind in KINDS:
            number, saved = self.record_grant(conn, item, row[1], actor, kind)
            reason = None
            if kind == 'course':
                if not course:
                    reason = 'no-source-course'
                elif not course['available'] or not course['authorAvailable']:
                    reason = 'source-unavailable'
                elif actor != course['creatorId'] and not (reuse['consent'] and reuse['rightsConfirmed']):
                    reason = 'source-reuse-denied'
            elif not own and not read_grant['visits']:
                reason = 'visits-sharing-required'
            elif not visits:
                reason = 'no-saved-visits'
            if reason is None and not own and not (saved['consent'] and saved['rightsConfirmed'] and saved['sourceFingerprint'] == fingerprints[kind]):
                reason = 'remix-not-allowed'
            if reason is None and not creator_allowed:
                reason = 'creator-required'
            path = dict(kind=kind, allowed=reason is None, reason=reason, fingerprint=fingerprints[kind])
            if kind == 'course':
                path['source'] = source
            else:
                path['visits'] = [dict(id=v['id'], name=v['place']['name'], visitedAt=v['visitedAt'], ordinal=i + 1) for i, v in enumerate(visits)]
                path['orderBasis'] = 'reported-visit-time-then-stored-order'
            paths.append(path)
        grants = []
        targets = sorted({target for target, in conn.execute('SELECT DISTINCT account_id FROM team_history_remix_permissions WHERE history_id=%s', (item,))}) if own else [actor]
        for target in targets:
            for kind in KINDS:
                number, saved = self.record_grant(conn, item, row[1], target, kind)
                readable = own or target == actor
                active = saved['consent'] and saved['rightsConfirmed'] and saved['sourceFingerprint'] == fingerprints[kind]
                if own:
                    shared = conn.execute('SELECT protected FROM team_history_shares WHERE history_id=%s AND account_id=%s', (item, target)).fetchone()
                    active = bool(active and self.history.person(target) and linked(conn, row[1], target) and shared
                        and self.history.content.allowed(conn, 'history', item, row[1], self.history.projection(conn, item, row[1])))
                    if active and kind == 'visits':
                        access = self.history.restore('share', row[1], item + ':' + target, shared[0])
                        active = bool(access['visits'] and visits)
                    if active and kind == 'course':
                        active = bool(course and course['available'] and course['authorAvailable']
                            and (target == course['creatorId'] or (reuse['consent'] and reuse['rightsConfirmed'])))
                if readable:
                    grants.append(dict(accountId=target, kind=kind, revision=number, consent=saved['consent'], active=bool(active)))
        public = dict(revision=row[3], permissionRevision=row[4], own=own, paths=paths, grants=grants, serverNow=datetime.now(timezone.utc))
        return public, row, value, course, visits

    def revoke_context(self, conn, item, target=None, kind=None):
        # Called while the existing history row is locked. Never acquire the
        # graph lock here: existing history writes may already hold that row.
        query = 'DELETE FROM team_history_remix_permissions WHERE history_id=%s'
        args = [item]
        if target is not None:
            query += ' AND account_id=%s';args.append(target)
        if kind is not None:
            query += ' AND kind=%s';args.append(kind)
        conn.execute(query, args)

    def raw_course(self, checksum):
        if not isinstance(checksum, str) or not CHECKSUM.fullmatch(checksum):
            fail(503, 'Source course integrity unavailable')
        try:
            descriptor = os.open(self.content / checksum, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(descriptor, 'rb') as source:
                raw = source.read(262145)
        except OSError:
            fail(503, 'Source course integrity unavailable')
        if len(raw) > 262144:
            fail(503, 'Source course integrity unavailable')
        return raw

    def write_reuse(self, conn, actor, pack_id, version, data):
        self.history.rooms.graph_lock(conn)
        course = self.source_course(conn, pack_id, version)
        if not course or course['creatorId'] != actor['id']:
            fail()
        revision(data['revision'])
        if type(data['consent']) is not bool or type(data['rightsConfirmed']) is not bool:
            fail(400, 'Explicit source re-use purpose required')
        number, old = self.reuse_permission(conn, course)
        if data['checksum'] != course['checksum']:
            fail(409, 'Source checksum changed')
        if data['consent']:
            if data['revision'] != number:
                fail(409, 'Source re-use permission changed')
            if not data['rightsConfirmed'] or not course['available'] or not course['authorAvailable']:
                fail(409, 'Current available source rights required')
        value = dict(consent=data['consent'], rightsConfirmed=data['consent'] and data['rightsConfirmed'], checksum=course['checksum'])
        key = pack_id + ':' + str(version)
        conn.execute('INSERT INTO team_course_reuse_permissions(pack_id,version,revision,protected) VALUES(%s,%s,%s,%s) '
            'ON CONFLICT(pack_id,version) DO UPDATE SET revision=excluded.revision,protected=excluded.protected',
            (pack_id, version, number + 1, self.protect('source', actor['id'], key, value)))
        from team_data import changed
        changed(conn, actor['id'], 'courses')
        # Course references stay encrypted. Inspect them only inside this server
        # transaction; the event carries the history resource name, never IDs,
        # coordinates or the decrypted record. Current REST rights remain final.
        for item, owner, protected in conn.execute(
                'SELECT history_id,owner_id,protected FROM team_histories ORDER BY history_id').fetchall():
            record = self.history.restore('record', owner, item, protected)
            if record['courseId'] == pack_id and record['courseVersion'] == version:
                self.history.notify(conn, item, owner)
        return dict(revision=number + 1, checksum=course['checksum'], consent=value['consent'],
                    active=bool(value['consent'] and value['rightsConfirmed'] and course['available'] and course['authorAvailable']), serverNow=datetime.now(timezone.utc))

    def write_grant(self, conn, actor, item, target, data):
        self.history.rooms.graph_lock(conn)
        row, record, _, _ = self.history.row(conn, item, actor['id'], write=True)
        if not isinstance(target, str) or not ACCOUNT.fullmatch(target) or target == actor['id'] or data['kind'] not in KINDS:
            fail(400, 'Choose a friend and re-use kind')
        # Revoking a previously known but now unavailable account stays allowed;
        # an unknown well-formed ID must not become a foreign-key server error.
        if not conn.execute('SELECT 1 FROM team_accounts WHERE account_id=%s', (target,)).fetchone():
            fail()
        for name in ('revision','historyRevision','permissionRevision'):
            revision(data[name])
        if type(data['consent']) is not bool or type(data['rightsConfirmed']) is not bool:
            fail(400, 'Explicit itinerary re-use purpose required')
        kind = data['kind'];number, old = self.record_grant(conn, item, actor['id'], target, kind)
        fingerprint = None
        if data['consent']:
            if data['revision'] != number or data['historyRevision'] != row[3] or data['permissionRevision'] != row[4]:
                fail(409, 'Record re-use permission changed')
            if not data['rightsConfirmed']:
                fail(400, 'Confirm rights to the selected itinerary metadata')
            if not self.history.person(target) or not linked(conn, actor['id'], target):
                fail()
            # Read sharing/moderation and original source rights are evaluated
            # as this recipient. A record owner cannot license someone else work.
            state, _, _, _, _ = self.snapshot(conn, item, target)
            path = next(value for value in state['paths'] if value['kind'] == kind)
            if path['reason'] not in (None, 'remix-not-allowed'):
                fail(409, 'Current source and visit sharing rights required')
            if data['sourceFingerprint'] != path['fingerprint']:
                fail(409, 'Re-creation source changed')
            fingerprint = path['fingerprint']
        value = dict(consent=data['consent'], rightsConfirmed=data['consent'] and data['rightsConfirmed'], sourceFingerprint=fingerprint)
        conn.execute('INSERT INTO team_history_remix_permissions(history_id,account_id,kind,revision,protected) VALUES(%s,%s,%s,%s,%s) '
            'ON CONFLICT(history_id,account_id,kind) DO UPDATE SET revision=excluded.revision,protected=excluded.protected',
            (item, target, kind, number + 1, self.protect('grant', actor['id'], item + ':' + target + ':' + kind, value)))
        self.history.save(conn, row, record, permission=True)
        self.history.notify(conn, item, actor['id'], (target,))
        return dict(accountId=target, kind=kind, revision=number + 1, consent=data['consent'], permissionRevision=row[4] + 1)

    def generate(self, conn, actor, item, data):
        state, row, record, course, visits = self.snapshot(conn, item, actor['id'])
        if data['kind'] not in KINDS or data['rightsConfirmed'] is not True:
            fail(400, 'Choose a source and confirm re-creation rights')
        revision(data['revision'], 1);revision(data['permissionRevision'], 1)
        if data['revision'] != row[3] or data['permissionRevision'] != row[4]:
            fail(409, 'Record or re-use permission changed')
        path = next(value for value in state['paths'] if value['kind'] == data['kind'])
        if not path['allowed']:
            fail(403, 'Explicit current re-creation permission required')
        if data['sourceFingerprint'] != path['fingerprint']:
            fail(409, 'Re-creation source changed')
        if conn.execute('SELECT count(*) FROM team_remix_drafts WHERE account_id=%s', (actor['id'],)).fetchone()[0] >= 500:
            fail(409, 'Re-creation draft limit reached')
        draft_id = secrets.token_hex(16)
        if data['kind'] == 'course':
            if data['visitIds'] != []:
                fail(400, 'Course re-creation does not select private visits')
            draft = from_course(self.raw_course(course['checksum']), course['checksum'], draft_id, actor)
            source = dict(kind='course', historyId=item, courseId=course['courseId'], version=course['version'], checksum=course['checksum'])
        else:
            draft = from_visits(visits, data['visitIds'], draft_id, actor)
            source = dict(kind='visits', historyId=item, visitIds=list(data['visitIds']))
        value = dict(draft=draft, source=source, revision=row[3], permissionRevision=row[4], sourceFingerprint=path['fingerprint'])
        conn.execute('INSERT INTO team_remix_drafts(draft_id,account_id,history_id,draft_pack_id,protected) VALUES(%s,%s,%s,%s,%s)',
            (draft_id, actor['id'], item, draft['id'], self.protect('draft', actor['id'], draft_id, value)))
        return dict(draft=draft, remixDraftId=draft_id, source=source)

    def current_draft(self, conn, owner, draft_id):
        if not isinstance(draft_id, str) or not HEX.fullmatch(draft_id):
            fail()
        # Peek at the immutable identity, then acquire history before draft locks;
        # existing record deletion holds the history row first.
        row = conn.execute('SELECT history_id,protected,state,draft_pack_id FROM team_remix_drafts '
                           'WHERE draft_id=%s AND account_id=%s', (draft_id, owner)).fetchone()
        if not row:
            fail()
        value = self.restore('draft', owner, draft_id, row[1])
        if row[0] is None:
            if value.get('tripCopy') is True:
                from iphone_trip_history import validate_trip_draft
                validate_trip_draft(self, conn, owner, value)
            else:
                from iphone_course_copy import validate_public_copy
                validate_public_copy(self, conn, owner, value)
        else:
            state, current, _, _, _ = self.snapshot(conn, row[0], owner)
            if value['revision'] != current[3] or value['permissionRevision'] != current[4]:
                fail(409, 'Record or permission changed; create a current draft')
            path = next(item for item in state['paths'] if item['kind'] == value['source']['kind'])
            if not path['allowed'] or path['fingerprint'] != value['sourceFingerprint']:
                fail(403, 'Re-creation rights withdrawn or changed')
        stable = conn.execute('SELECT protected,state,draft_pack_id FROM team_remix_drafts WHERE draft_id=%s '
                              'AND account_id=%s FOR SHARE', (draft_id, owner)).fetchone()
        if not stable or bytes(stable[0]) != bytes(row[1]):
            fail(409, 'Re-creation draft changed')
        return value, stable[2]

    def authorize_publication(self, conn, owner, pack, draft_id):
        self.history.rooms.graph_lock(conn)
        reserved = conn.execute('SELECT draft_id FROM team_remix_drafts WHERE draft_pack_id=%s', (pack['id'],)).fetchone()
        if not reserved:
            if draft_id is not None:
                fail(409, 'Re-creation draft does not match this course')
            return None
        if draft_id != reserved[0]:
            fail(403, 'Known re-creation course requires its original draft receipt')
        value, pack_id = self.current_draft(conn, owner, draft_id)
        if pack_id != pack['id']:
            fail(409, 'Re-creation draft identity changed')
        return value['source']

    def published(self, conn, owner, draft_id):
        if draft_id is not None:
            conn.execute("UPDATE team_remix_drafts SET state='published' WHERE draft_id=%s AND account_id=%s", (draft_id, owner))

    @staticmethod
    def public_source(source):
        if source is None:
            return None
        if source['kind'] == 'course':
            return {key: source[key] for key in ('kind','courseId','version','checksum')}
        if source['kind'] == 'trip':
            return {key: source[key] for key in ('kind','courses')}
        return dict(kind='visits', placeCount=len(source['visitIds']))

    def router(self):
        router = APIRouter()
        if not self.enabled:
            return router
        async def body(request, fields):
            raw = bytearray()
            try:
                async with asyncio.timeout(5):
                    async for chunk in request.stream():
                        raw.extend(chunk)
                        if len(raw) > 8192:
                            fail(413, 'Re-creation request too large')
            except TimeoutError:
                fail(408, 'Re-creation request timed out')
            try:
                value = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
            except (ValueError, UnicodeError, RecursionError):
                fail(400, 'Invalid re-creation JSON')
            if not isinstance(value, dict) or set(value) != set(fields):
                fail(400, 'Invalid re-creation fields')
            return value
        def actor(conn, request, mutate=False, creator=False):
            return self.auth.browser(request, mutate=mutate, roles=('creator','admin') if creator else None, connection=conn)
        @router.get('/v1/social/history/{item}/remix-permissions')
        def permissions(item: str, request: Request):
            with psycopg.connect(self.dsn) as conn:
                who = actor(conn, request)
                return self.snapshot(conn, item, who['id'])[0]
        @router.put('/v1/social/history/{item}/remix-permissions/{target}')
        async def grant(item: str, target: str, request: Request):
            data = await body(request, ('revision','historyRevision','permissionRevision','kind','sourceFingerprint','consent','rightsConfirmed'))
            def write():
                with psycopg.connect(self.dsn) as conn:
                    who = actor(conn, request, True)
                    self.auth.rate('history-remix-grant:' + who['id'], limit=30)
                    return self.write_grant(conn, who, item, target, data)
            return await run_in_threadpool(write)
        @router.get('/v1/studio/packs/{pack_id}/versions/{version}/reuse-permission')
        def reuse(pack_id: str, version: int, request: Request):
            with psycopg.connect(self.dsn) as conn:
                who = actor(conn, request)
                course = self.source_course(conn, pack_id, version)
                if not course or who['id'] != course['creatorId']:
                    fail()
                number, value = self.reuse_permission(conn, course)
                return dict(revision=number, checksum=course['checksum'], consent=value['consent'],
                            active=bool(value['consent'] and value['rightsConfirmed'] and course['available'] and course['authorAvailable']), serverNow=datetime.now(timezone.utc))
        @router.put('/v1/studio/packs/{pack_id}/versions/{version}/reuse-permission')
        async def update_reuse(pack_id: str, version: int, request: Request):
            data = await body(request, ('revision','checksum','consent','rightsConfirmed'))
            def write():
                with psycopg.connect(self.dsn) as conn:
                    who = actor(conn, request, True)
                    self.auth.rate('course-reuse:' + who['id'], limit=30)
                    return self.write_reuse(conn, who, pack_id, version, data)
            return await run_in_threadpool(write)
        @router.post('/v1/social/history/{item}/remix', status_code=201)
        async def generate(item: str, request: Request):
            data = await body(request, ('revision','permissionRevision','kind','sourceFingerprint','visitIds','rightsConfirmed'))
            def write():
                with psycopg.connect(self.dsn) as conn:
                    who = actor(conn, request, True, True)
                    self.auth.rate('history-remix:' + who['id'], limit=20)
                    return self.generate(conn, who, item, data)
            return await run_in_threadpool(write)
        @router.get('/v1/studio/packs/{pack_id}/versions/{version}/remix-source')
        def published_source(pack_id: str, version: int, request: Request):
            with psycopg.connect(self.dsn) as conn:
                who = actor(conn, request)
                if not conn.execute('SELECT 1 FROM pack_versions WHERE pack_id=%s AND version=%s AND creator_id=%s',
                                    (pack_id, version, who['id'])).fetchone():
                    fail()
                row = conn.execute('SELECT draft_id FROM team_remix_drafts WHERE draft_pack_id=%s AND account_id=%s',
                                   (pack_id, who['id'])).fetchone()
                if not row:
                    fail()
                value, _ = self.current_draft(conn, who['id'], row[0])
                return dict(remixDraftId=row[0], source=value['source'])
        @router.get('/v1/social/remix-drafts/{draft_id}')
        def draft(draft_id: str, request: Request):
            with psycopg.connect(self.dsn) as conn:
                who = actor(conn, request)
                value, _ = self.current_draft(conn, who['id'], draft_id)
                return dict(draft=value['draft'], remixDraftId=draft_id, source=value['source'])
        return router
