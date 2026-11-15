"""Loopback synthetic API contract boundaries, not a real-road availability claim."""
import json
import threading
import time
import urllib.error
from unittest.mock import patch
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from road_provider import Coordinate, GraphSource, ValhallaRoadProvider, RoadProviderError

SOURCE = GraphSource('synthetic-test', 'a'*64, '2026-01-01T00:00:00Z', (1., 42., 2., 43.))
ORIGIN = Coordinate(42.5, 1.5)
TARGET = Coordinate(42.51, 1.51)

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def do_POST(self):
        value = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.server.requests.append((self.path, value))
        if self.server.mode == 'redirect':
            self.send_response(302); self.send_header('Location', 'http://public.example.invalid/route'); self.end_headers(); return
        if self.server.mode == 'forbidden':
            self.send_response(403); self.end_headers(); self.wfile.write(b'private upstream body'); return
        if self.server.mode == 'timeout':
            # Real loopback transport timeout, no external service or private data.
            time.sleep(0.15)
            return
        if self.server.mode == 'malformed-chunk':
            self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Transfer-Encoding','chunked');self.end_headers()
            self.wfile.write(b'not-a-chunk-size\r\n');self.wfile.flush();return
        if self.server.mode in ('slow-body','slow-headers','slow-chunked'):
            try:
                if self.server.mode == 'slow-headers':
                    self.wfile.write(b'HTTP/1.1 200 OK\r\nX-Drip: ');self.wfile.flush()
                else:
                    self.send_response(200);self.send_header('Content-Type','application/json')
                    if self.server.mode == 'slow-chunked':self.send_header('Transfer-Encoding','chunked')
                    self.end_headers()
                    if self.server.mode == 'slow-chunked':self.wfile.write(b'20\r\n');self.wfile.flush()
                for _ in range(32):
                    self.wfile.write(b' ');self.wfile.flush();time.sleep(0.01)
            except (BrokenPipeError,ConnectionResetError):pass
            return
        origin = value['sources'][0]
        cells = [{'from_index':0, 'to_index':i, 'distance':1.25, 'time':180,
                  'begin_lat':origin['lat'], 'begin_lon':origin['lon'],
                  'end_lat':point['lat'], 'end_lon':point['lon']}
                 for i,point in enumerate(value['targets'])]
        result = {'id':value['id'], 'units':'kilometers', 'sources_to_targets':[cells]}
        mode = self.server.mode
        if mode == 'unreachable': cells[0].update(distance=None, time=None)
        if mode == 'half-null': cells[0]['time'] = None
        if mode == 'bool-distance': cells[0]['distance'] = True
        if mode == 'huge-distance': cells[0]['distance'] = 1e308
        if mode == 'bool-index': cells[0]['from_index'] = False
        if mode == 'negative-time': cells[0]['time'] = -1
        if mode == 'wrong-unit': result['units'] = 'miles'
        if mode == 'wrong-id': result['id'] = 'not-this-request'
        if mode == 'missing-cell': cells.pop()
        if mode == 'snap': cells[0]['end_lon'] += 0.1
        raw = json.dumps(result).encode()
        if mode == 'duplicate': raw = raw[:-1]+b',"units":"kilometers"}'
        if mode == 'oversized': raw = b' '*1048577
        self.send_response(200); self.send_header('Content-Type','application/json'); self.end_headers(); self.wfile.write(raw)

class RoadProviderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1',0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True); cls.thread.start()
        cls.endpoint = 'http://127.0.0.1:'+str(cls.server.server_address[1])
    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join()
    def setUp(self):
        self.server.mode = ''; self.server.requests = []
        self.provider = ValhallaRoadProvider(self.endpoint, SOURCE)
    def test_actual_schema_units_and_every_candidate_without_topn(self):
        metrics = self.provider.matrix(ORIGIN, [TARGET]*65)
        self.assertEqual(len(metrics),65)
        self.assertTrue(all(m.reachable and m.distance_meters == 1250 and m.estimated_duration_seconds == 180 for m in metrics))
        self.assertTrue(all(not m.live_traffic and not m.globally_shortest for m in metrics))
        self.assertEqual(sum(len(x[1]['targets']) for x in self.server.requests),65)
        self.assertTrue(all(len(value['targets']) <= 4 for _,value in self.server.requests))
        self.assertTrue(all(path == '/sources_to_targets' and value['units']=='kilometers' and value['costing']=='auto' for path,value in self.server.requests))
        self.assertEqual(self.provider.matrix(ORIGIN, []),())
    def test_unreachable_is_explicit_not_straight_fallback(self):
        self.server.mode = 'unreachable'; result = self.provider.matrix(ORIGIN,[TARGET])[0]
        self.assertFalse(result.reachable); self.assertIsNone(result.distance_meters); self.assertIsNone(result.estimated_duration_seconds)
    def test_malformed_partial_redirect_and_snap_fail_closed(self):
        for mode in ['half-null','bool-distance','huge-distance','bool-index','negative-time','wrong-unit','wrong-id','missing-cell','duplicate','oversized','redirect','snap']:
            with self.subTest(mode=mode):
                self.server.mode=mode
                with self.assertRaises(RoadProviderError): self.provider.matrix(ORIGIN,[TARGET])
    def test_source_forbidden_and_actual_transport_timeout_are_closed_and_bounded(self):
        self.server.mode = 'forbidden'
        with self.assertRaises(RoadProviderError) as denied:
            self.provider.matrix(ORIGIN,[TARGET])
        self.assertEqual(denied.exception.code,'ROAD_PROVIDER_UNAVAILABLE')
        self.assertNotIn('private',str(denied.exception))
        self.server.mode = 'timeout'
        self.provider.timeout_seconds = 0.03
        started=time.monotonic()
        with self.assertRaises(RoadProviderError) as timed_out:
            self.provider.matrix(ORIGIN,[TARGET])
        self.assertEqual(timed_out.exception.code,'ROAD_PROVIDER_TIMEOUT')
        self.assertLess(time.monotonic()-started,1)
        self.assertEqual(len(self.server.requests),2)
        with patch.object(self.provider._opener,'open',side_effect=urllib.error.URLError(TimeoutError())):
            with self.assertRaises(RoadProviderError) as connect_timeout:
                self.provider.matrix(ORIGIN,[TARGET])
        self.assertEqual(connect_timeout.exception.code,'ROAD_PROVIDER_TIMEOUT')

    def test_total_deadline_interrupts_slow_drip_headers_and_body(self):
        for mode in ('slow-body','slow-headers','slow-chunked'):
            with self.subTest(mode=mode):
                self.server.mode=mode
                provider=ValhallaRoadProvider(self.endpoint,SOURCE,query_seconds=0.05,timeout_seconds=0.03)
                started=time.monotonic()
                with self.assertRaises(RoadProviderError) as timed_out:
                    provider.matrix(ORIGIN,[TARGET])
                elapsed=time.monotonic()-started
                print('DEADLINE_PROBE',mode,'elapsedSeconds='+str(elapsed),flush=True)
                self.assertEqual(timed_out.exception.code,'ROAD_PROVIDER_TIMEOUT')
                # Original body read took ~0.315s despite a 0.05s whole budget.
                # This margin allows scheduler jitter while detecting that defect.
                self.assertLess(elapsed,0.15)
                self.assertGreaterEqual(elapsed,0.04)
        self.assertEqual(len(self.server.requests),3)
        self.server.mode='malformed-chunk'
        with self.assertRaises(RoadProviderError) as malformed:
            self.provider.matrix(ORIGIN,[TARGET])
        self.assertEqual(malformed.exception.code,'ROAD_PROVIDER_RESPONSE_INVALID')

    def test_external_endpoint_invalid_coordinate_and_coverage_never_call(self):
        for endpoint in ['https://127.0.0.1:9','http://router.example:8002','http://127.0.0.1:8/path','http://user:pass@127.0.0.1:8']:
            with self.subTest(endpoint=endpoint), self.assertRaises(RoadProviderError): ValhallaRoadProvider(endpoint,SOURCE)
        for latitude,longitude in [(True,1.5),(float('nan'),1.5),(91,0)]:
            with self.assertRaises(RoadProviderError): Coordinate(latitude,longitude)
        with self.assertRaises(RoadProviderError): self.provider.matrix(Coordinate(35,127),[TARGET])
        with self.assertRaises(RoadProviderError): self.provider.matrix(ORIGIN,[TARGET]*1001)
        self.assertEqual(self.server.requests,[])
        self.assertNotIn('42.5',repr(ORIGIN))
if __name__=='__main__': unittest.main()
