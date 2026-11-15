import psycopg

import test_trip_merge_api as api_fixture


class TripMergePlaceTests(api_fixture.TripApiFixture):
    def place(self, trip, author, category='food', **extra):
        data = dict(category=category, **extra)
        if 'sourceSignalId' not in extra:
            data['place'] = api_fixture.PLACE
        return self.api(trip, '/places', author, data, 'POST')

    def prepared(self):
        trip = self.h.new_trip(self.a)
        self.h.join(trip, self.a, self.b)
        self.h.join(trip, self.a, self.e)
        for member in (self.a, self.b, self.e):
            self.sharing(trip, member)
            self.h.vehicle(member)
            self.h.new_car(trip, member)
        self.role(trip, self.a, self.b, 'food')
        return trip

    def test_category_manager_and_schedule_editor_are_separate(self):
        trip = self.prepared()
        self.assertEqual(self.place(trip, self.a)[0], 403)
        self.assertEqual(self.place(trip, self.b, 'rest')[0], 403)
        status, _, candidate = self.place(trip, self.b)
        self.assertEqual(status, 201, candidate)
        path = '/places/' + candidate['id']
        selection = dict(revision=1, state='selected')
        self.assertEqual(self.api(trip, path, self.b, selection, 'PATCH')[0], 403)
        self.assertEqual(self.h.rights(trip, self.a, self.e, edit=True)[0], 200)
        self.assertEqual(self.api(trip, path, self.e, selection, 'PATCH')[0], 200)
        result = self.api(trip, '/places', self.a)[2]['places'][0]
        self.assertEqual(result['state'], 'selected')
        self.assertEqual(result['selectedBy'], self.e['user']['id'])
        self.assertEqual(result['place'], api_fixture.PLACE)
        self.assertEqual(self.api(trip, path, self.b, dict(revision=2, place=dict(api_fixture.PLACE, name='수정')), 'PATCH')[0], 409)
        self.assertEqual(self.api(trip, path, self.a, dict(revision=2, state='proposed'), 'PATCH')[0], 200)
        self.assertEqual(self.api(trip, path, self.b, dict(revision=3, place=dict(api_fixture.PLACE, name='수정')), 'PATCH')[0], 200)

    def test_same_category_can_curate_other_candidate_but_cannot_edit_original(self):
        trip = self.prepared()
        self.role(trip, self.a, self.e, 'food')
        candidate = self.place(trip, self.b)[2]
        path = '/places/' + candidate['id']
        self.assertEqual(self.api(trip, path, self.e, dict(revision=1, place=api_fixture.PLACE), 'PATCH')[0], 403)
        self.assertEqual(self.api(trip, path, self.e, dict(revision=1, recommended=False), 'PATCH')[0], 200)
        self.assertEqual(self.api(trip, path, self.e, dict(revision=2), 'DELETE')[0], 403)
        self.assertEqual(self.api(trip, path, self.b, dict(revision=1, recommended=True), 'PATCH')[0], 409)
        self.role(trip, self.a, self.b, 'member')
        self.assertEqual(self.api(trip, path, self.b, dict(revision=2, recommended=True), 'PATCH')[0], 403)
        self.assertEqual(self.api(trip, path, self.b, dict(revision=2), 'DELETE')[0], 200)
        self.assertEqual(self.api(trip, '/places', self.a)[2]['places'], [])
        self.assertNotIn(candidate['sourceSignalId'], [item['id'] for item in self.signals(trip)])

    def test_cross_trip_source_candidate_and_revision_inputs(self):
        trip = self.prepared()
        candidate = self.place(trip, self.b)[2]
        other = self.h.new_trip(self.a)
        self.h.join(other, self.a, self.b)
        self.sharing(other, self.b)
        self.role(other, self.a, self.b, 'food')
        self.assertEqual(self.api(other, '/places/' + candidate['id'], self.b, dict(revision=1), 'DELETE')[0], 404)
        self.assertEqual(self.place(other, self.b, sourceSignalId=candidate['sourceSignalId'])[0], 404)
        self.role(trip, self.a, self.e, 'food')
        imported = self.place(trip, self.e, sourceSignalId=candidate['sourceSignalId'])
        self.assertEqual(imported[0], 201)
        self.assertEqual(imported[2]['accountId'], self.b['user']['id'])
        self.assertEqual(self.api(trip, '/places/' + candidate['id'], self.b, dict(revision=True, recommended=False), 'PATCH')[0], 400)
        self.assertEqual(self.api(trip, '/places/' + candidate['id'], self.b, dict(revision=1), 'PATCH')[0], 400)

    def test_manager_curates_general_signal_without_copying_its_authority(self):
        trip = self.prepared()
        self.transition(trip, 'start')
        source = self.signal(trip, self.e)
        response = self.place(trip, self.b, sourceSignalId=source)
        self.assertEqual(response[0], 201, response[2])
        candidate = response[2]
        self.assertEqual(candidate['accountId'], self.e['user']['id'])
        path = '/places/' + candidate['id']
        self.assertEqual(self.api(trip, path, self.b, dict(revision=1, place=api_fixture.PLACE), 'PATCH')[0], 403)
        self.assertEqual(self.api(trip, path, self.b, dict(revision=1, recommended=False), 'PATCH')[0], 200)
        self.sharing(trip, self.e, location=False)
        self.assertEqual(self.api(trip, '/places', self.a)[2]['places'], [])
        self.sharing(trip, self.e)
        self.assertEqual(self.api(trip, '/places', self.a)[2]['places'], [])
        self.assertIn(source, [signal['id'] for signal in self.signals(trip)])

    def test_location_period_withdraws_only_its_authors_curated_place(self):
        trip = self.prepared()
        self.transition(trip, 'start')
        share = '/location-sharing'
        enabled = self.api(trip, share, self.e, dict(locationConsent=True), 'PATCH')
        self.assertEqual(enabled[0], 200)
        source = self.signal(trip, self.e)
        candidate = self.place(trip, self.b, sourceSignalId=source)[2]
        selected = self.api(trip, '/places/' + candidate['id'], self.a, dict(revision=1, state='selected'), 'PATCH')
        self.assertEqual(selected[0], 200)
        other = self.place(trip, self.b)[2]
        with psycopg.connect(self.dsn) as conn:
            stored = conn.execute('SELECT protected,revision FROM team_trip_place_proposals WHERE proposal_id=%s',
                (other['id'],)).fetchone()
        disabled = self.api(trip, share, self.e, dict(locationConsent=False), 'PATCH')
        self.assertEqual(disabled[0], 200)
        renewed = self.api(trip, share, self.e, dict(locationConsent=True), 'PATCH')
        self.assertEqual(renewed[0], 200)
        self.assertNotEqual(enabled[2]['locationShareId'], renewed[2]['locationShareId'])
        self.assertEqual([item['id'] for item in self.api(trip, '/places', self.a)[2]['places']], [other['id']])
        self.assertIn(source, [signal['id'] for signal in self.signals(trip)])
        with psycopg.connect(self.dsn) as conn:
            self.assertEqual(conn.execute('SELECT protected,revision FROM team_trip_place_proposals WHERE proposal_id=%s',
                (other['id'],)).fetchone(), stored)
            service = self.h.module.TEAM_AUTH.trip_places_service
            owner, saved, revision, _ = service.row(conn, trip, candidate['id'])
            self.assertEqual((owner, saved['state'], saved['selectedBy'], revision),
                (self.e['user']['id'], 'withdrawn', None, 3))

    def test_new_location_period_retires_legacy_candidate_left_under_disabled_sharing(self):
        trip = self.prepared()
        self.transition(trip, 'start')
        source = self.signal(trip, self.e)
        candidate = self.place(trip, self.b, sourceSignalId=source)[2]
        with psycopg.connect(self.dsn) as conn:
            legacy = conn.execute('SELECT protected,revision FROM team_trip_place_proposals WHERE proposal_id=%s',
                (candidate['id'],)).fetchone()
        self.sharing(trip, self.e, location=False)
        with psycopg.connect(self.dsn) as conn:
            conn.execute('UPDATE team_trip_place_proposals SET protected=%s,revision=%s WHERE proposal_id=%s',
                (*legacy, candidate['id']))
        self.assertEqual(self.api(trip, '/places', self.a)[2]['places'], [])
        enabled = self.api(trip, '/location-sharing', self.e, dict(locationConsent=True), 'PATCH')
        self.assertEqual(enabled[0], 200)
        self.assertEqual(self.api(trip, '/places', self.a)[2]['places'], [])
        self.assertIn(source, [signal['id'] for signal in self.signals(trip)])

    def test_withdrawn_sharing_and_rejoin_do_not_restore_place(self):
        trip = self.prepared()
        self.place(trip, self.b)
        self.sharing(trip, self.b, location=False)
        self.assertEqual(self.api(trip, '/places', self.a)[2]['places'], [])
        self.sharing(trip, self.b)
        self.assertEqual(self.api(trip, '/places', self.a)[2]['places'], [])
        self.place(trip, self.b)
        self.assertEqual(self.api(trip, '/members/' + self.b['user']['id'], self.b, method='DELETE')[0], 200)
        self.h.join(trip, self.a, self.b)
        self.sharing(trip, self.b)
        self.assertEqual(self.api(trip, '/places', self.a)[2]['places'], [])

    def test_closed_result_reader_checks_current_sharing_without_live_access(self):
        trip = self.prepared()
        candidate = self.place(trip, self.b)[2]
        self.assertEqual(self.api(trip, '/places/' + candidate['id'], self.a, dict(revision=1, state='selected'), 'PATCH')[0], 200)
        self.transition(trip, 'start')
        signal = self.signal(trip)
        self.vote(trip, signal, self.b)
        self.vote(trip, signal, self.e)
        self.transition(trip, 'finish')
        reader = self.h.module.TEAM_AUTH.trip_places_service
        with psycopg.connect(self.dsn) as conn:
            values = reader.result_reader(conn, trip, self.a['user']['id'])['places']
        self.assertEqual({item['id'] for item in values}, {candidate['id'], signal})
        self.assertEqual(self.api(trip, '/places', self.a)[0], 409)
        self.sharing(trip, self.b, location=False)
        with psycopg.connect(self.dsn) as conn:
            values = reader.result_reader(conn, trip, self.a['user']['id'])['places']
        self.assertEqual(values, [])

    def test_block_hides_other_authors_places_and_selection_identity(self):
        trip = self.prepared()
        candidate = self.place(trip, self.b)[2]
        self.h.rights(trip, self.a, self.e, edit=True)
        self.api(trip, '/places/' + candidate['id'], self.e, dict(revision=1, state='selected'), 'PATCH')
        self.assertEqual(self.h.social('/blocks', self.b, dict(targetId=self.e['user']['id']), 'POST')[0], 201)
        self.assertEqual(self.api(trip, '/places', self.e)[2]['places'], [])
        result = self.api(trip, '/places', self.b)[2]['places'][0]
        self.assertIsNone(result['selectedBy'])
