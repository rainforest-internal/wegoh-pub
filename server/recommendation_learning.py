"""Current-consent, owner-encrypted learning of available public course features."""
from course_publication import COURSE_AVAILABLE, available
import math
import re
import secrets

from private_records import VisitCipher
from recommendation_model import fit, score, MODEL_VERSION
from team_data import changed
from team_recommendations import unavailable


def public_features(pack):
    """Only immutable public course places; never a query anchor/history/identity."""
    stops = pack['stops']
    if not 1 <= len(stops) <= 3:
        unavailable(503, 'Public course features unavailable')
    for stop in stops:
        for key, low, high in (('latitude', -90, 90), ('longitude', -180, 180)):
            value = stop[key]
            if type(value) not in (int, float) or not low <= value <= high or not math.isfinite(value):
                unavailable(503, 'Public course features unavailable')
    span = 0.0
    for first in stops:
        for second in stops:
            a, b = math.radians(first['latitude']), math.radians(second['latitude'])
            dlat = b - a
            dlon = math.radians(second['longitude'] - first['longitude'])
            hav = math.sin(dlat / 2) ** 2 + math.cos(a) * math.cos(b) * math.sin(dlon / 2) ** 2
            span = max(span, 2 * 6371000 * math.asin(math.sqrt(min(1, max(0, hav)))))
    # Clipped public pairwise straight-line span, not road distance or time.
    return [1.0, (len(stops) - 1) / 2, min(span, 100000) / 100000]


class RecommendationLearning:
    def __init__(self, recommendations):
        self.recommendations = recommendations

    @staticmethod
    def empty():
        return dict(schemaVersion=1, enabled=False, epoch=secrets.token_hex(16), samples={})

    def load(self, conn, owner):
        # Caller first takes the existing recommendations:<owner> advisory lock.
        row = conn.execute('SELECT revision,protected FROM team_recommendation_learning '
                           'WHERE account_id=%s FOR UPDATE', (owner,)).fetchone()
        if row is None:
            return 0, self.empty()
        value = VisitCipher().restore('team-recommendation-learning', owner, row[1])
        if (not isinstance(value, dict) or set(value) != {'schemaVersion','enabled','epoch','samples'}
                or type(value['schemaVersion']) is not int or value['schemaVersion'] != 1 or type(value['enabled']) is not bool
                or not isinstance(value['epoch'], str) or len(value['epoch']) != 32
                or any(ch not in '0123456789abcdef' for ch in value['epoch'])
                or not isinstance(value['samples'], dict) or len(value['samples']) > 200):
            unavailable(503, 'Personal learning state unavailable')
        for key, sample in value['samples'].items():
            if (not isinstance(sample, dict) or set(sample) != {'courseId','version','checksum','features','label','epoch'}
                    or not isinstance(sample['courseId'], str) or not re.fullmatch('[a-z0-9][a-z0-9_-]{0,79}', sample['courseId'])
                    or type(sample['version']) is not int or not 1 <= sample['version'] <= 2147483647
                    or not isinstance(sample['checksum'], str) or not re.fullmatch('[0-9a-f]{64}', sample['checksum'])
                    or type(sample['label']) is not int or sample['label'] not in (0, 1)
                    or not isinstance(sample['features'], list) or len(sample['features']) != 3
                    or any(type(v) not in (int, float) or not -1 <= v <= 1 or not math.isfinite(v) for v in sample['features'])
                    or key != sample['courseId'] + ':' + str(sample['version'])
                    or sample['epoch'] != value['epoch']):
                unavailable(503, 'Personal learning sample unavailable')
        return row[0], value

    @staticmethod
    def save(conn, owner, revision, value):
        raw = VisitCipher().protect('team-recommendation-learning', owner, value)
        conn.execute('INSERT INTO team_recommendation_learning(account_id,revision,protected) VALUES(%s,%s,%s) '
            'ON CONFLICT(account_id) DO UPDATE SET revision=excluded.revision,protected=excluded.protected,updated_at=now()',
            (owner, revision + 1, raw))
        return revision + 1

    def allow(self, conn, owner, settings_revision, settings, learning_revision):
        if not settings['permissions']['useFeedback']:
            unavailable(403, 'Enable separate feedback use before learning')
        revision, previous = self.load(conn, owner)
        self.recommendations.expected(revision, learning_revision)
        if previous['enabled']:
            return dict(self.view(conn, owner, settings), settingsRevision=settings_revision)
        value = self.empty(); value['enabled'] = True
        # A new consent starts with zero samples; old no-training feedback is not imported.
        revision = self.save(conn, owner, revision, value)
        current = self.recommendations.save(conn, owner, settings_revision, settings)
        return dict(enabled=True, learningRevision=revision, settingsRevision=current['revision'],
                    modelVersion=MODEL_VERSION, status='collecting-feedback', eligibleSamples=0)

    def clear(self, conn, owner):
        revision, _ = self.load(conn, owner)
        # Keep a revision tombstone even if never enabled. Clear only live model data.
        revision = self.save(conn, owner, revision, self.empty())
        return dict(enabled=False, learningRevision=revision, modelVersion=MODEL_VERSION,
                    status='disabled', eligibleSamples=0)

    def view(self, conn, owner, settings):
        revision, value = self.load(conn, owner)
        enabled = bool(value['enabled'] and settings['permissions']['useFeedback'])
        eligible = self.eligible(conn, value) if enabled else []
        status = fit(eligible)['status'] if enabled else 'disabled'
        return dict(enabled=enabled, learningRevision=revision, modelVersion=MODEL_VERSION,
                    status=status, eligibleSamples=len(eligible))

    def eligible(self, conn, value):
        samples = []
        for sample in sorted(value['samples'].values(), key=lambda s: (s['courseId'], s['version'])):
            row = conn.execute("SELECT p.checksum FROM pack_versions p LEFT JOIN pack_reviews r USING(checksum) "
                f"WHERE p.pack_id=%s AND p.version=%s AND {COURSE_AVAILABLE} FOR SHARE OF p",
                (sample['courseId'], sample['version'])).fetchone()
            if row is None or row[0] != sample['checksum'] or not available(conn, row[0], lock=True):
                continue
            # Re-derive features from available exact bytes; no stale stored-weight shortcut.
            features = public_features(self.recommendations.course(row[0]))
            if features != sample['features']:
                unavailable(503, 'Personal learning sample integrity unavailable')
            samples.append((features, sample['label']))
        return samples

    def label(self, conn, owner, settings, learning_revision, data):
        revision, value = self.load(conn, owner)
        self.recommendations.expected(revision, learning_revision)
        if not value['enabled'] or not settings['permissions']['useFeedback']:
            unavailable(403, 'Separate current learning consent required')
        if data['kind'] != 'course':
            unavailable(400, 'Learning feedback supports public courses only')
        row = conn.execute("SELECT p.checksum FROM pack_versions p LEFT JOIN pack_reviews r USING(checksum) "
            f"WHERE p.pack_id=%s AND p.version=%s AND {COURSE_AVAILABLE} FOR SHARE OF p",
            (data['id'], data['version'])).fetchone()
        if row is None or not available(conn, row[0], lock=True):
            unavailable(404, 'Learning course unavailable')
        key = data['id'] + ':' + str(data['version'])
        if key not in value['samples'] and len(value['samples']) >= 200:
            unavailable(409, 'Learning sample limit reached; withdraw before starting afresh')
        value['samples'][key] = dict(courseId=data['id'], version=data['version'], checksum=row[0],
            features=public_features(self.recommendations.course(row[0])),
            label=1 if data['response'] == 'like' else 0, epoch=value['epoch'])
        # Same item/version replaces its label; duplicate clicks do not multiply reward.
        return self.save(conn, owner, revision, value)

    def rerank(self, conn, owner, settings, learning_revision, candidates):
        revision, value = self.load(conn, owner)
        self.recommendations.expected(revision, learning_revision)
        if not value['enabled'] or not settings['permissions']['useFeedback']:
            unavailable(403, 'Separate current learning consent required')
        eligible = self.eligible(conn, value)
        model = fit(eligible)
        if model['status'] != 'trained' or not candidates:
            return candidates[:12], dict(learningRevision=revision, modelVersion=MODEL_VERSION,
                status=model['status'], eligibleSamples=len(eligible), aiUsed=False)
        scored = [(score(model, public_features(self.recommendations.course(item['checksum']))), order, item)
                  for order, item in enumerate(candidates)]
        scored.sort(key=lambda row: (-row[0], row[1]))
        output = [dict(item, personalModelScore=round(probability, 6),
                       reasons=item['reasons'] + ['learnedFromExplicitCourseFeedback'])
                  for probability, _, item in scored[:12]]
        return output, dict(learningRevision=revision, modelVersion=MODEL_VERSION, status='trained',
            eligibleSamples=len(eligible), aiUsed=True,
            scoreMeaning='Personal model ranking value, not accuracy, safety or real-world improvement')
