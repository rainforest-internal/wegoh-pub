"""Reusable synthetic course feed on the owned loopback browser fixture."""

import sys
import unittest

import test_team_friends as friends


CREATORS = {'alice': '주말운전수첩 (데모)', 'eve': '골목길 아카이브 (데모)'}
VIEWER = 'bob'
COURSES = (
    ('alice', 'demo-river-sunrise', '강변에서 시작하는 아침',
     '이른 주말, 강변 전망과 아침 산책을 함께 즐기는 합성 코스.',
     ('서울', '강변', '일출'), (('강변 전망터', 37.530, 127.024), ('아침 산책길', 37.535, 127.033))),
    ('alice', 'demo-river-picnic', '한낮의 강변 피크닉',
     '도심에서 짧게 떠나는 피크닉을 주제로 만든 합성 코스.',
     ('서울', '강변', '피크닉'), (('강변 피크닉터', 37.529, 127.033),)),
    ('eve', 'demo-alley-coffee', '골목 커피와 작은 전시',
     '골목을 걷고 커피와 전시를 둘러보는 합성 코스.',
     ('서울', '카페', '전시'), (('골목 커피집', 37.542, 127.050), ('작은 전시관', 37.547, 127.051))),
    ('eve', 'demo-alley-evening', '노을이 내려앉는 골목',
     '해 질 무렵 골목 산책과 사진을 즐기는 합성 코스.',
     ('서울', '산책', '노을'), (('노을 골목길', 37.549, 127.057),)),
)


def seed_feed(helper):
    sessions = {who: helper.login(who) for who in (*CREATORS, VIEWER)}
    codes = []
    for who, course_id, title, description, tags, stops in COURSES:
        pack = dict(
            schemaVersion=1, id=course_id, version=1, title=title,
            author=CREATORS[who], description=description,
            stops=[
                dict(id=f'stop-{index}', name=name, latitude=latitude, longitude=longitude,
                     radiusMeters=100, action=dict(type='chime', message='데모 도착'))
                for index, (name, latitude, longitude) in enumerate(stops, 1)
            ],
        )
        code, _, published = helper.call(
            '/v1/packs', dict(rightsConfirmed=True, pack=pack, tags=list(tags)),
            'POST', who=who, session=sessions[who],
        )
        helper.assertIn(
            code, (200, 201),
            f'{course_id}: {published}. Use a checkout with course tag support (#6).',
        )
        helper.assertEqual(published['state'], 'approved')
        codes.append(code)
    # Opposite creators provide the stars. The demo visitor starts with no activity.
    for who, course_id in (
        ('alice', 'demo-alley-coffee'), ('alice', 'demo-alley-evening'),
        ('eve', 'demo-river-sunrise'),
    ):
        code, _, result = helper.call(
            f'/v1/studio/course-stars/{course_id}/versions/1', method='PUT',
            who=who, session=sessions[who],
        )
        helper.assertEqual(code, 200, result)
    return sessions[VIEWER], codes


def course_feed_fixture():
    # unittest should collect only the dedicated feed test, not the inherited
    # contracts that expect the standard synthetic account names and roles.
    class CourseFeedFixture(friends.FriendTests):
        @classmethod
        def setUpClass(cls):
            super().setUpClass()
            names = dict(CREATORS, bob='데모 방문자')
            roles = {'alice': 'admin', 'eve': 'creator', VIEWER: 'viewer'}
            cls.members_rows = [
                dict(email=who + '@example.invalid', name=name, role=roles[who])
                for who, name in names.items()
            ]
            cls.write_members(cls.members_rows)

        @classmethod
        def prepare_browser_fixture(cls, helper):
            viewer, _ = seed_feed(helper)
            cls.browser_fixture_metadata = dict(viewerId=viewer['user']['id'])

    return CourseFeedFixture


class CourseFeedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = course_feed_fixture()
        cls.fixture.setUpClass()
        cls.addClassCleanup(cls.fixture.tearDownClass)

    def test_friendless_feed_and_idempotent_seed(self):
        helper = self.fixture()
        helper.setUp()
        _, first = seed_feed(helper)
        viewer, second = seed_feed(helper)
        self.assertEqual(first, [201] * len(COURSES))
        self.assertEqual(second, [200] * len(COURSES))

        status, _, overview = helper.friend('/overview', who=VIEWER, session=viewer)
        self.assertEqual(status, 200, overview)
        self.assertEqual(overview['friends'], [])
        status, _, library = helper.call('/v1/studio/course-library', who=VIEWER, session=viewer)
        self.assertEqual(status, 200, library)
        self.assertEqual(library['following'], [])
        self.assertEqual(library['saved'], [])
        items = {item['id']: item for item in library['public']}
        self.assertEqual(len(items), len(COURSES))
        for who, course_id, title, _, tags, stops in COURSES:
            item = items[course_id]
            self.assertEqual((item['author'], item['title']), (CREATORS[who], title))
            self.assertEqual(item['stopCount'], len(stops))
            self.assertCountEqual(item['tags'], tags)
            self.assertEqual(item['creatorRank'], 1 if who == 'eve' else 2)
            self.assertFalse(item['starred'])
        self.assertEqual(sum(item['starCount'] for item in items.values()), 3)


if __name__ == '__main__':
    if len(sys.argv) != 3 or sys.argv[1] != '--serve-fixture':
        raise SystemExit('Usage: test_course_feed_browser_fixture.py --serve-fixture CONFIG.json')
    friends.serve_fixture(sys.argv[2], fixture_class=course_feed_fixture())
