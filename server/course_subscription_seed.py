"""Synthetic course-subscription data for testing the 코스 → 구독 tab.

Operator command, never an HTTP route. It runs with the API's own environment
(WEGOH_DATABASE_DSN, WEGOH_CONTENT_DIR, WEGOH_VISIT_KEY_FILE or systemd
credentials) and only touches rows it can prove are synthetic:

* creators are accounts whose IDs are derived from SEED and whose encrypted
  identity carries ``syntheticSeed``; their names end with ``(데모)``;
* courses belong to those creators and use the ``demo-subscription-`` prefix;
* tags start with ``데모-``.

``apply`` is idempotent and makes each named account follow every synthetic
creator and tag. ``remove`` deletes the synthetic creators, their courses and
the synthetic tag follows. Other accounts, courses and follows are preserved.
"""
import argparse
from datetime import timedelta
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys
import tempfile

import psycopg

from account_handles import create_account
from private_records import VisitCipher
from runtime_credentials import apply_runtime_credentials
from studio import COVER_STORED_LIMIT, normalize_course_tags, validate_pack
from team_data import changed


SEED = 'course-subscriptions-v1'
PACK_PREFIX = 'demo-subscription-'
TAG_PREFIX = '데모-'
REVIEWER = 'synthetic-seed'
REVIEW_NOTE = '코스 구독 시험용 합성 데이터'

# key, display name, cover colour
CREATORS = (
    ('weekend', '주말운전수첩 (데모)', (76, 119, 156)),
    ('alley', '골목길 아카이브 (데모)', (156, 119, 80)),
    ('coast', '숲과 바다 수첩 (데모)', (80, 129, 107)),
)
# creator key, id suffix, title, description, tags, stops, recent
COURSES = (
    ('weekend', 'river-sunrise', '강변에서 시작하는 아침', '강변 전망과 아침 산책을 함께 즐기는 합성 코스입니다.',
     ('서울', '강변', '일출'), (('강변 전망터', 37.530, 127.024), ('아침 산책길', 37.535, 127.033)), False),
    ('weekend', 'river-picnic', '한낮의 강변 피크닉', '도심에서 짧게 떠나는 피크닉을 주제로 만든 합성 코스입니다.',
     ('서울', '강변', '피크닉'), (('강변 피크닉터', 37.529, 127.033),), False),
    ('alley', 'alley-coffee', '골목 커피와 작은 전시', '골목을 걷고 커피와 전시를 둘러보는 합성 코스입니다.',
     ('서울', '카페', '전시'), (('골목 커피집', 37.542, 127.050), ('작은 전시관', 37.547, 127.051)), False),
    ('alley', 'alley-evening', '노을이 내려앉는 골목', '해 질 무렵 골목 산책과 사진을 즐기는 합성 코스입니다.',
     ('서울', '산책', '노을'), (('노을 골목길', 37.549, 127.057),), False),
    ('coast', 'forest-morning', '숲에서 맞는 아침', '숲길을 천천히 걷는 합성 코스입니다.',
     ('숲', '산책'), (('숲 입구', 37.600, 127.100), ('숲 전망터', 37.610, 127.110)), False),
    ('coast', 'sea-evening', '바다에서 맞는 노을', '해변을 걸으며 노을을 보는 합성 코스입니다.',
     ('바다', '노을'), (('해변 전망터', 37.700, 128.900),), False),
    ('weekend', 'new-river-night', '새 코스 · 강변 야경 드라이브', '구독 탭의 새 코스 표시를 확인하는 합성 코스입니다.',
     ('서울', '강변', '야경'), (('강변 야경 전망대', 37.517, 126.996), ('다리 아래 쉼터', 37.512, 127.004)), True),
    ('alley', 'new-alley-bakery', '새 코스 · 골목 빵집 산책', '구독 탭의 새 코스 표시를 확인하는 합성 코스입니다.',
     ('카페', '산책'), (('골목 빵집', 37.556, 126.923),), True),
    ('coast', 'new-coast-sunrise', '새 코스 · 바닷가 일출', '구독 탭의 새 코스 표시를 확인하는 합성 코스입니다.',
     ('바다', '일출', '숲'), (('일출 전망터', 37.795, 128.920), ('솔숲 산책로', 37.790, 128.912)), True),
)
TAGS = tuple(dict.fromkeys(TAG_PREFIX + tag for course in COURSES for tag in course[4]))


class SeedError(RuntimeError):
    """The database holds something the seed does not own; nothing was changed."""


def creator_id(key):
    # Real IDs hash the Access issuer URL and subject; this namespace cannot collide with one.
    return 'team-' + hashlib.sha256(f'wegoh-synthetic\0{SEED}\0{key}'.encode()).hexdigest()[:40]


CREATOR_IDS = {key: creator_id(key) for key, _, _ in CREATORS}
NAMES = {key: name for key, name, _ in CREATORS}


def identity(key):
    # Self-enrolled shape keeps the creator visible without a roster entry; it can
    # never sign in because no Access issuer/subject hashes to this account ID.
    return dict(email=f'{key}@synthetic.wegoh.invalid', subject=f'wegoh-synthetic:{SEED}:{key}',
                displayName=NAMES[key], accessSelfEnrolled=True, syntheticSeed=SEED)


def course_pack(course):
    key, suffix, title, description, _, stops, _ = course
    return validate_pack(dict(
        schemaVersion=1, id=PACK_PREFIX + suffix, version=1, title=title, author=NAMES[key],
        description=description,
        stops=[dict(id=f'stop-{index}', name=name, latitude=latitude, longitude=longitude,
                    radiusMeters=100, action=dict(type='chime', message='데모 코스 장소에 도착했어요'))
               for index, (name, latitude, longitude) in enumerate(stops, 1)]))


def encoded(pack):
    # Same canonical bytes as POST /v1/packs, so the checksum identifies the content.
    return json.dumps(pack, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def course_tags(course):
    return normalize_course_tags([TAG_PREFIX + tag for tag in course[4]])


def cover(key):
    from PIL import Image
    colour = next(value for name, _, value in CREATORS if name == key)
    image = Image.new('RGB', (640, 360), colour)
    stream = io.BytesIO()
    image.save(stream, 'JPEG', quality=85)
    raw = stream.getvalue()
    if len(raw) > COVER_STORED_LIMIT:
        raise SeedError('Synthetic cover exceeds the stored cover limit')
    return raw


def content_directory():
    value = os.environ.get('WEGOH_CONTENT_DIR', '')
    path = Path(value)
    if not value or not path.is_absolute() or path.is_symlink() or not path.is_dir():
        raise SeedError('WEGOH_CONTENT_DIR must be the API content directory')
    return path


def store_pack(content, raw, checksum):
    target = content / checksum
    if target.exists():
        if hashlib.sha256(target.read_bytes()).hexdigest() != checksum:
            raise SeedError('Stored course bytes differ from their checksum; existing file preserved')
        return
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=content, delete=False, prefix='.pack-') as stream:
            temporary = Path(stream.name)
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        try:
            os.link(temporary, target)
        except FileExistsError:
            pass
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def lock(conn):
    # Same order as the follow API: social graph first, then each course.
    conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('social-membership',0))")
    conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', ('wegoh-synthetic:' + SEED,))
    for course in COURSES:
        conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', (PACK_PREFIX + course[1],))


def owned_creators(conn, cipher):
    found = []
    for account, protected in conn.execute('SELECT account_id,protected FROM team_accounts WHERE account_id=ANY(%s)',
                                           (list(CREATOR_IDS.values()),)).fetchall():
        if cipher.restore('team-account:' + account, 'identity', protected).get('syntheticSeed') != SEED:
            raise SeedError('A non-synthetic account uses a synthetic creator ID; existing data preserved')
        found.append(account)
    return found


def ensure_creators(conn, cipher):
    existing = set(owned_creators(conn, cipher))
    for key, _, _ in CREATORS:
        account = CREATOR_IDS[key]
        if account not in existing:
            create_account(conn, account, cipher.protect('team-account:' + account, 'identity', identity(key)))
        elif conn.execute("SELECT account_status FROM team_accounts WHERE account_id=%s", (account,)).fetchone()[0] != 'active':
            raise SeedError('A synthetic creator is not active; run remove, then apply')


def ensure_courses(conn, content):
    created = 0
    planned = []
    for course in COURSES:
        pack = course_pack(course)
        raw = encoded(pack)
        planned.append((course, pack, raw, hashlib.sha256(raw).hexdigest(), course_tags(course)))
    for course, pack, raw, checksum, tags in planned:
        rows = conn.execute('SELECT version,creator_id,checksum,tags FROM pack_versions WHERE pack_id=%s',
                            (pack['id'],)).fetchall()
        if any(row[1] != CREATOR_IDS[course[0]] for row in rows):
            raise SeedError(f"Course ID {pack['id']} belongs to another creator; existing data preserved")
        if rows and [tuple(row[2:]) for row in rows] != [(checksum, tags)]:
            raise SeedError(f"Synthetic course {pack['id']} differs from this seed; run remove, then apply")
    # One timestamp anchors the feed: existing courses are days old, new ones are hours old,
    # and subscriptions start between them so only the new ones are 구독 소식.
    now = conn.execute('SELECT clock_timestamp()').fetchone()[0]
    base_index = recent_index = 0
    for course, pack, raw, checksum, tags in planned:
        recent = course[6]
        if recent:
            recent_index += 1
            created_at = now - timedelta(hours=4) + timedelta(minutes=30 * recent_index)
        else:
            base_index += 1
            created_at = now - timedelta(days=3) + timedelta(minutes=10 * base_index)
        if conn.execute('SELECT 1 FROM pack_versions WHERE pack_id=%s', (pack['id'],)).fetchone():
            if not conn.execute('SELECT 1 FROM pack_course_covers WHERE pack_id=%s AND version=1', (pack['id'],)).fetchone():
                conn.execute('INSERT INTO pack_course_covers(pack_id,version,image) VALUES(%s,1,%s)', (pack['id'], cover(course[0])))
            store_pack(content, raw, checksum)
            continue
        store_pack(content, raw, checksum)
        conn.execute('INSERT INTO pack_versions(pack_id,version,creator_id,checksum,title,author,description,stop_count,tags,created_at) '
                     'VALUES(%s,1,%s,%s,%s,%s,%s,%s,%s,%s)',
                     (pack['id'], CREATOR_IDS[course[0]], checksum, pack['title'], pack['author'], pack['description'],
                      len(pack['stops']), tags, created_at))
        conn.execute('INSERT INTO pack_course_covers(pack_id,version,image) VALUES(%s,1,%s)', (pack['id'], cover(course[0])))
        conn.execute("INSERT INTO pack_reviews(checksum,state,reviewer,review_note) VALUES(%s,'approved',%s,%s) "
                     'ON CONFLICT(checksum) DO NOTHING', (checksum, REVIEWER, REVIEW_NOTE))
        conn.execute("INSERT INTO pack_review_events(checksum,state,reviewer,review_note) VALUES(%s,'approved',%s,%s)",
                     (checksum, REVIEWER, REVIEW_NOTE))
        created += 1
    return created


def subscription_start(conn):
    row = conn.execute('SELECT min(created_at) FROM pack_versions WHERE creator_id=ANY(%s) AND pack_id=ANY(%s)',
                       (list(CREATOR_IDS.values()), [PACK_PREFIX + course[1] for course in COURSES if course[6]])).fetchone()
    return row[0] - timedelta(days=1)


def resolve_accounts(conn, handles, accounts):
    resolved = []
    for handle in handles:
        value = handle.removeprefix('@').lower()
        row = conn.execute("SELECT account_id FROM team_accounts WHERE lower(handle)=%s AND account_status='active'",
                           (value,)).fetchone()
        if not row:
            raise SeedError(f'No active account has the handle @{value}')
        resolved.append(row[0])
    for account in accounts:
        if not re.fullmatch(r'team-[a-f0-9]{40}', account) or not conn.execute(
                "SELECT 1 FROM team_accounts WHERE account_id=%s AND account_status='active'", (account,)).fetchone():
            raise SeedError('No active account has that account ID')
        resolved.append(account)
    resolved = list(dict.fromkeys(resolved))
    if set(resolved) & set(CREATOR_IDS.values()):
        raise SeedError('A synthetic creator cannot be a subscription target')
    return resolved


def apply(dsn, content, *, handles=(), accounts=()):
    """Create the synthetic creators/courses and subscribe each target account."""
    if not handles and not accounts:
        raise SeedError('Name at least one target account with --handle or --account')
    cipher = VisitCipher()
    with psycopg.connect(dsn) as conn:
        lock(conn)
        targets = resolve_accounts(conn, handles, accounts)
        ensure_creators(conn, cipher)
        created = ensure_courses(conn, content)
        started = subscription_start(conn)
        follows = tags = 0
        for account in targets:
            added = 0
            for creator in CREATOR_IDS.values():
                added += conn.execute('INSERT INTO team_creator_follows(follower_id,creator_id,followed_at) VALUES(%s,%s,%s) '
                                      'ON CONFLICT DO NOTHING', (account, creator, started)).rowcount
            follows += added
            for tag in TAGS:
                inserted = conn.execute('INSERT INTO team_course_tag_follows(account_id,tag_key,tag,followed_at) VALUES(%s,%s,%s,%s) '
                                        'ON CONFLICT DO NOTHING', (account, tag.casefold(), tag, started)).rowcount
                tags += inserted
                added += inserted
            if added:
                changed(conn, account, 'courses')
        if created:
            changed(conn, '*', 'courses')
    return dict(targets=len(targets), creators=len(CREATORS), courses=len(COURSES), createdCourses=created,
                followedTags=len(TAGS), newCreatorFollows=follows, newTagFollows=tags)


def remove(dsn, content):
    """Delete only the seed's creators, courses and tag follows."""
    cipher = VisitCipher()
    with psycopg.connect(dsn) as conn:
        lock(conn)
        creators = owned_creators(conn, cipher)
        packs = conn.execute('SELECT pack_id,checksum FROM pack_versions WHERE creator_id=ANY(%s)', (creators,)).fetchall()
        pack_ids = [row[0] for row in packs]
        checksums = [row[1] for row in packs]
        used = conn.execute('SELECT count(*) FROM team_trip_courses WHERE pack_id=ANY(%s)', (pack_ids,)).fetchone()[0]
        if used:
            raise SeedError(f'{used} trip course(s) use synthetic courses; remove them from those trips first. Nothing deleted')
        conn.execute('DELETE FROM content_reports WHERE checksum=ANY(%s)', (checksums,))
        conn.execute('DELETE FROM pack_review_events WHERE checksum=ANY(%s)', (checksums,))
        conn.execute('DELETE FROM pack_reviews WHERE checksum=ANY(%s)', (checksums,))
        courses = conn.execute('DELETE FROM pack_versions WHERE creator_id=ANY(%s)', (creators,)).rowcount
        # A seed tag stays followed if someone else's course still carries it.
        tags = conn.execute('DELETE FROM team_course_tag_follows f WHERE f.tag_key=ANY(%s) AND NOT EXISTS ('
                            'SELECT 1 FROM pack_versions p, unnest(p.tags) t WHERE lower(t)=f.tag_key)',
                            ([tag.casefold() for tag in TAGS],)).rowcount
        try:
            with conn.transaction():
                accounts = conn.execute('DELETE FROM team_accounts WHERE account_id=ANY(%s)', (creators,)).rowcount
        except psycopg.errors.ForeignKeyViolation:
            raise SeedError('Other data still refers to a synthetic creator; nothing deleted') from None
        if courses or tags or accounts:
            changed(conn, '*', 'courses')
    for checksum in checksums:
        with psycopg.connect(dsn) as conn:
            if conn.execute('SELECT 1 FROM pack_versions WHERE checksum=%s', (checksum,)).fetchone():
                continue
        (content / checksum).unlink(missing_ok=True)
    return dict(creators=accounts, courses=courses, tagFollows=tags)


def main(argv=None):
    parser = argparse.ArgumentParser(description='코스 → 구독 탭 시험용 합성 데이터를 넣거나 지운다.')
    commands = parser.add_subparsers(dest='command', required=True)
    put = commands.add_parser('apply', help='합성 창작자·코스를 만들고 지정 계정이 구독하게 한다 (반복 실행 가능)')
    put.add_argument('--handle', action='append', default=[], help='구독 상태를 넣을 계정 핸들 (@ 생략 가능, 여러 번 지정 가능)')
    put.add_argument('--account', action='append', default=[], help='구독 상태를 넣을 계정 ID (team-…)')
    commands.add_parser('remove', help='합성 창작자·코스·태그 구독을 모두 지운다')
    args = parser.parse_args(argv)
    apply_runtime_credentials()
    if os.environ.get('WEGOH_AUTH_MODE') != 'cloudflare' or os.environ.get('WEGOH_LOCAL_STUDIO') == '1':
        raise SeedError('Course subscriptions exist only with shared accounts (WEGOH_AUTH_MODE=cloudflare). '
                        'Use test_course_subscriptions_fixture.py for an isolated local server')
    dsn = os.environ.get('WEGOH_DATABASE_DSN', '')
    if not dsn:
        raise SeedError('WEGOH_DATABASE_DSN is required')
    content = content_directory()
    if args.command == 'apply':
        result = apply(dsn, content, handles=args.handle, accounts=args.account)
    else:
        result = remove(dsn, content)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return result


if __name__ == '__main__':
    try:
        main()
    except SeedError as error:
        print('course_subscription_seed: ' + str(error), file=sys.stderr)
        raise SystemExit(1)
