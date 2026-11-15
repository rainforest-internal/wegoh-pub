"""Owned PG/TLS fixture prepared only through ordinary synthetic HTTP APIs.

No production DSN, legacy row seed, real GPS, key or certificate lifecycle.
The four public metadata IDs refer to actual synthetic saved resources.
"""
import os
from pathlib import Path
import secrets
import sys
import tempfile

import psycopg
import test_team_friends as friends


def prepare_records(api):
    """Two friends, one published source course, and two completed histories."""
    alice, bob = api.login(), api.login('bob')

    def call(path, data=None, method='GET', session=alice, who='alice', expected=200):
        status, _, value = api.call(path, data, method, session=session, who=who)
        api.assertEqual(status, expected, value)
        return value

    call('/v1/social/friends/requests', {'targetId': bob['user']['id']}, 'POST', expected=201)
    call('/v1/social/friends/requests/' + alice['user']['id'] + '/respond', {'accept': True}, 'POST', bob, 'bob')
    pack = api.pack()
    pack['title'] = ('합성 저장 원코스 '+ '긴코스이름'*30)[:99]+'끝'
    pack['stops'].append(dict(id='second', name='두 번째 합성 장소', latitude=37.51,
        longitude=127.02, radiusMeters=100, action=dict(type='chime', message='합성 도착 안내')))
    api.assertEqual(api.publish(pack, alice)[0], 201)
    api.assertEqual(api.approve(pack, alice)[0], 200)
    published = call('/v1/packs/' + pack['id'] + '/versions/' + str(pack['version']))
    api.assertEqual(published['title'], pack['title'])
    ids, titles = [], []
    for course in (True, False):
        title = (("합성 원코스 기록 " if course else "합성 방문 기록 ") + "긴기록이름"*30)[:99]+"끝"
        item = call('/v1/social/history', dict(title=title,
            startedAt='2026-01-02T01:00:00Z', endedAt='2026-01-02T04:00:00Z',
            courseId=pack['id'] if course else None, courseVersion=1 if course else None), 'POST', expected=201)['id']
        for index in range(2):
            current = call('/v1/social/history/' + item)
            call('/v1/social/history/' + item + '/visits', dict(revision=current['revision'],
                place=dict(name='실제 저장한 합성 장소 ' + str(index + 1), latitude=37.5 + index * .01,
                           longitude=127.0 + index * .02), visitedAt='2026-01-02T0' + str(index + 2) + ':00:00Z',
                review='복사하면 안 되는 합성 개인 후기 ' + str(index + 1), rating=4), 'POST', expected=201)
        if not course:
            current = call('/v1/social/history/' + item)
            call('/v1/social/history/' + item + '/permissions',
                dict(permissionRevision=current['permissionRevision'], collectTrace=True), 'PATCH')
            current = call('/v1/social/history/' + item)
            call('/v1/social/history/' + item + '/trace-batches', dict(revision=current['revision'],
                batchId=secrets.token_hex(16), streamId=secrets.token_hex(16), label='합성 이동 경로', points=[
                    dict(latitude=37.5, longitude=127.0, capturedAt='2026-01-02T02:00:00Z', accuracyMeters=10),
                    dict(latitude=37.501, longitude=127.001, capturedAt='2026-01-02T02:00:02Z', accuracyMeters=10),
                ]), 'POST', expected=201)
        current = call('/v1/social/history/' + item)
        request = call('/v1/social/history/' + item + '/review-request', dict(revision=current['revision'], consent=True), 'PATCH')
        call('/v1/moderation/content/history/' + item, dict(checksum=request['review']['checksum'],
            decision='approved', reviewer='Synthetic fixture administrator', reviewNote='Synthetic title and places reviewed'), 'POST')
        if course:
            current = call('/v1/social/history/' + item)
            call('/v1/social/history/' + item + '/shares/' + bob['user']['id'],
                dict(permissionRevision=current['permissionRevision'], visits=True, trace=False, photos=False), 'PUT')
        current = call('/v1/social/history/' + item)
        api.assertEqual(current['title'], title)
        ids.append(item); titles.append(current['title'])
    return dict(alice=alice, bob=bob, sourcePack=pack,
                metadata=dict(courseId=pack['id'], courseVersion=1, courseHistoryId=ids[0], visitsHistoryId=ids[1],
                    sourceCourseTitle=published['title'], courseHistoryTitle=titles[0], visitsHistoryTitle=titles[1],
                    sourceOwnerName=alice['user']['displayName'], receivingCreatorName=bob['user']['displayName']))


def serve_fixture(target):
    class HistoryRemixBrowserFixture(friends.FriendTests):
        @classmethod
        def write_members(cls, rows):
            names = {'alice': '가' * 64, 'bob': '나' * 64}
            super().write_members([dict(row, name=names.get(row['email'].split('@')[0], row['name'])) for row in rows])

        @classmethod
        def prepare_browser_fixture(cls, helper):
            if (cls.state.parent != Path(tempfile.gettempdir())
                    or not cls.state.name.startswith('wegoh-team-contract-')
                    or cls.state.stat().st_uid != os.getuid()):
                raise RuntimeError('Not an owned temporary fixture')
            with psycopg.connect(cls.dsn) as conn:
                if Path(conn.execute('SHOW data_directory').fetchone()[0]) != cls.state / 'postgres':
                    raise RuntimeError('Not the fixture-owned database')
            cls.browser_fixture_metadata = prepare_records(helper)['metadata']

    friends.serve_fixture(target, fixture_class=HistoryRemixBrowserFixture)


if __name__ == '__main__':
    if len(sys.argv) != 3 or sys.argv[1] != '--serve-fixture':
        raise SystemExit('Explicit isolated fixture path required')
    serve_fixture(sys.argv[2])
