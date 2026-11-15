"""Pure editable-course planning from verified source bytes or explicitly selected visits.
Authorization belongs to TeamHistoryRemix before these functions are called.
No trace/photo/review content, inferred visit, or external URL retrieval is used.
"""
import copy
import hashlib
import json
import math
import re
from fastapi import HTTPException

IDENT = re.compile(r'[a-f0-9]{32}')


def unavailable(detail='Re-creation source unavailable'):
    raise HTTPException(409, detail)


def source_fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def identity(draft_id, actor):
    if not isinstance(draft_id, str) or not IDENT.fullmatch(draft_id):
        raise ValueError('Server draft identity required')
    return dict(id='remix-' + draft_id, version=1, author=actor['displayName'])


def from_course(raw, checksum, draft_id, actor):
    # Raw approved immutable JSON is loaded locally by the service, not fetched
    # from a caller-provided external URL. Never clone an unchecked changed file.
    if hashlib.sha256(raw).hexdigest() != checksum:
        raise HTTPException(503, 'Source course integrity unavailable')
    try:
        original = json.loads(raw)
    except (ValueError, UnicodeError):
        raise HTTPException(503, 'Source course integrity unavailable') from None
    if not isinstance(original, dict) or not isinstance(original.get('stops'), list) or not 1 <= len(original['stops']) <= 3:
        raise HTTPException(503, 'Source course integrity unavailable')
    draft = copy.deepcopy(original)
    draft.update(identity(draft_id, actor))
    return draft


def from_visits(visits, visit_ids, draft_id, actor):
    # Caller supplies only currently authorized stored visits in canonical order.
    # Choosing a subset is explicit. Never truncate, sort by guessed geography,
    # substitute a coordinate, or fill an empty record with invented places.
    if (not isinstance(visit_ids, list) or not 1 <= len(visit_ids) <= 3
            or any(not isinstance(value, str) or not IDENT.fullmatch(value) for value in visit_ids)
            or len(set(visit_ids)) != len(visit_ids)):
        raise HTTPException(400, 'Choose one to three stored visits')
    chosen = [visit for visit in visits if visit['id'] in visit_ids]
    if [visit['id'] for visit in chosen] != visit_ids:
        unavailable('Stored visit selection or order changed')
    stops = []
    for visit in chosen:
        place = visit['place']
        name = place.get('name')
        if not isinstance(name, str) or not name.strip() or len(name.encode('utf-16-le')) // 2 > 80:
            unavailable('Stored visit name cannot be represented by the course contract')
        for field, low, high in [('latitude', -90, 90), ('longitude', -180, 180)]:
            value = place.get(field)
            if type(value) not in (int, float) or not low <= value <= high or not math.isfinite(value):
                unavailable('Stored visit position unavailable')
        stops.append(dict(id='visit-' + visit['id'], name=name,
            latitude=place['latitude'], longitude=place['longitude'], radiusMeters=100,
            action=dict(type='chime', message='장소에 도착했습니다')))
    # Radius/chime are new editable course defaults, never claimed as source
    # measurements or proof that the new trip already reached these places.
    return dict(schemaVersion=1, **identity(draft_id, actor), title='방문한 장소',
                description='방문한 장소로 만든 경로', stops=stops)
