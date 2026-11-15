from datetime import datetime
import unittest

import psycopg

from test_trip_merge_api import TripApiFixture


class TripChatTests(TripApiFixture):
    def test_authorization_retry_and_delete(self):
        self.h.befriend(self.a, self.b)
        trip = self.h.new_trip(self.a, members=(self.b,))
        path = '/' + trip + '/chat'
        chat = dict(id='a' * 32, text='  여기서 만나요\n점심 출발  ')
        self.assertEqual(self.h.trip(path)[0], 401)
        self.assertEqual(self.h.trip(path, session=self.b)[0], 404)
        self.assertEqual(self.h.trip(path, chat, 'POST', session=self.e)[0], 404)
        self.assertEqual(self.h.trip(path, chat, 'POST', session=self.a, csrf=False)[0], 403)
        self.assertEqual(self.h.trip(path, dict(chat, senderId='fake'), 'POST', session=self.a)[0], 400)
        self.assertEqual(self.h.trip(path, dict(chat, text=' ' * 2), 'POST', session=self.a)[0], 400)
        self.assertEqual(self.h.trip(path, dict(chat, text='x' * 401), 'POST', session=self.a)[0], 400)
        self.assertEqual(self.h.respond(trip, self.b)[0], 200)

        status, headers, posted = self.h.trip(path, chat, 'POST', session=self.a)
        self.assertEqual(status, 201, posted)
        self.assertEqual(headers['cache-control'], 'private, no-store')
        self.assertEqual(self.h.trip(path, chat, 'POST', session=self.a)[2], posted)
        self.assertEqual(self.h.trip(path, dict(chat, text='다른 내용'), 'POST', session=self.a)[0], 409)
        status, headers, feed = self.h.trip(path, session=self.b)
        self.assertEqual(status, 200, feed)
        self.assertEqual(headers['cache-control'], 'private, no-store')
        self.assertEqual(feed['messages'], [dict(posted, senderId=self.a['user']['id'],
            senderName=self.a['user']['displayName'], text=chat['text'].strip())])
        self.assertIsNotNone(datetime.fromisoformat(posted['createdAt']).tzinfo)
        with psycopg.connect(self.dsn) as conn:
            protected, = conn.execute('SELECT protected FROM team_trip_messages WHERE trip_id=%s', (trip,)).fetchone()
            self.assertNotIn(chat['text'].strip().encode(), bytes(protected))
            self.assertEqual(conn.execute("SELECT revision FROM team_resource_versions WHERE account_id=%s AND resource='rooms'",
                ('event-trip:' + trip + ':chat',)).fetchone(), (1,))

        self.assertEqual(self.h.trip('/' + trip + '/members/' + self.b['user']['id'], method='DELETE', session=self.b)[0], 200)
        self.assertEqual(self.h.trip(path, session=self.b)[0], 404)
        self.h.close_trip(trip, self.a)
        self.assertEqual(self.h.trip(path, dict(chat, id='b' * 32), 'POST', session=self.a)[0], 409)
        self.assertEqual(self.h.trip(path, session=self.a)[2], feed)
        self.assertEqual(self.h.trip('/' + trip, method='DELETE', session=self.a)[0], 200)
        self.assertEqual(self.h.trip(path, session=self.a)[0], 404)
        with psycopg.connect(self.dsn) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM team_trip_messages WHERE trip_id=%s', (trip,)).fetchone(), (0,))

    def test_block_hides_messages_in_both_directions(self):
        trip = self.h.new_trip(self.a)
        self.h.join(trip, self.a, self.b)
        self.h.join(trip, self.a, self.e)
        path = '/' + trip + '/chat'
        for index, session in enumerate((self.a, self.b, self.e)):
            payload = dict(id=f'{index:032x}', text=session['user']['displayName'])
            self.assertEqual(self.h.trip(path, payload, 'POST', session=session)[0], 201)
        self.assertEqual(self.h.social('/blocks', self.b, dict(targetId=self.e['user']['id']), 'POST')[0], 201)
        for reader, hidden in ((self.b, self.e), (self.e, self.b)):
            status, _, feed = self.h.trip(path, session=reader)
            self.assertEqual(status, 200, feed)
            self.assertEqual({row['senderId'] for row in feed['messages']}, {self.a['user']['id'], reader['user']['id']})
            self.assertNotIn(hidden['user']['displayName'], [row['text'] for row in feed['messages']])


if __name__ == '__main__':
    unittest.main()
