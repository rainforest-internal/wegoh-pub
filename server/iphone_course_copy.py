"""Owner-bound public course copies stored in the existing encrypted remix drafts."""
import secrets

from fastapi import HTTPException

from remix_sources import from_course
from team_friends import blocked


def _allowed_source(remix, conn, owner, pack_id, version):
    remix.history.rooms.graph_lock(conn)
    course = remix.source_course(conn, pack_id, version)
    if not course or not course['available'] or not course['authorAvailable']:
        raise HTTPException(404, 'Course unavailable')
    if owner == course['creatorId']:
        return course, None
    if blocked(conn, owner, course['creatorId']):
        raise HTTPException(404, 'Course unavailable')
    revision, permission = remix.reuse_permission(conn, course)
    if not (permission['consent'] and permission['rightsConfirmed']):
        raise HTTPException(403, 'Source course re-use permission required')
    return course, revision


def make_public_copy(remix, conn, actor, pack_id, version):
    owner = actor['id']
    course, revision = _allowed_source(remix, conn, owner, pack_id, version)
    if conn.execute('SELECT count(*) FROM team_remix_drafts WHERE account_id=%s',
                    (owner,)).fetchone()[0] >= 500:
        raise HTTPException(409, 'Re-creation draft limit reached')
    draft_id = secrets.token_hex(16)
    pack = from_course(remix.raw_course(course['checksum']), course['checksum'], draft_id, actor)
    tags, has_cover = conn.execute(
        'SELECT tags, EXISTS(SELECT 1 FROM pack_course_covers c WHERE c.pack_id=p.pack_id AND c.version=p.version) '
        'FROM pack_versions p WHERE p.pack_id=%s AND p.version=%s', (pack_id, version)).fetchone()
    source = dict(kind='course', courseId=pack_id, version=version, checksum=course['checksum'])
    saved = dict(draft=pack, source=source, publicCopy=True, reuseRevision=revision)
    conn.execute('INSERT INTO team_remix_drafts(draft_id,account_id,draft_pack_id,protected) VALUES(%s,%s,%s,%s)',
                 (draft_id, owner, pack['id'], remix.protect('draft', owner, draft_id, saved)))
    return dict(pack=pack, remixDraftId=draft_id, tags=tags, hasCover=has_cover)


def validate_public_copy(remix, conn, owner, saved):
    if saved.get('publicCopy') is not True:
        raise HTTPException(404, 'Re-creation unavailable')
    source = saved['source']
    course, revision = _allowed_source(remix, conn, owner, source['courseId'], source['version'])
    if course['checksum'] != source['checksum'] or revision != saved['reuseRevision']:
        raise HTTPException(409, 'Source course or re-use permission changed')
