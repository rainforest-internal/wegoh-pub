import base64
import socket
import time
import unittest
from unittest.mock import Mock, patch
from fastapi import HTTPException, Request, Response
from music_link_preview import (HOSTS, HTML_LIMIT, IMAGE_LIMIT, Metadata, MusicLinkPreview,
    PreviewError, create_router, fetch, image_data, normalize, public_address)


class MusicLinkPreviewTests(unittest.TestCase):
    def test_allowlisted_hosts_and_normalization(self):
        for host in HOSTS:
            self.assertEqual(normalize('https://' + host + '/song?x=1#part'), 'https://' + host + '/song?x=1')
        self.assertEqual(normalize('https://OPEN.SPOTIFY.COM:443/track/a'), 'https://open.spotify.com/track/a')
        for url in ('http://melon.com/a', 'https://melon.com.evil.invalid/a', 'https://melon.com@evil.invalid/',
                    'https://melon.com:8443/', 'https://127.0.0.1/', 'https://evil.invalid/', 'https://melon.com/\n'):
            with self.subTest(url=url), self.assertRaises(PreviewError) as error:
                normalize(url)
            self.assertEqual(error.exception.status, 400)

    def test_dns_rejects_private_loopback_link_local_and_mixed_answers(self):
        for addresses in (['127.0.0.1'], ['10.0.0.1'], ['169.254.169.254'], ['::1'], ['224.0.0.1'], ['ff02::1'], ['100.64.0.1'], ['8.8.8.8', '192.168.1.1']):
            rows = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (ip, 443)) for ip in addresses]
            with patch('music_link_preview.socket.getaddrinfo', return_value=rows):
                with self.assertRaises(PreviewError):
                    public_address('melon.com', time.monotonic()+5)
        with patch('music_link_preview.socket.getaddrinfo', return_value=[(2, 1, 6, '', ('8.8.8.8', 443))]):
            self.assertEqual(public_address('melon.com', time.monotonic()+5), '8.8.8.8')

    def test_redirect_to_unapproved_host_rejected_before_connecting_again(self):
        connection = Mock();response = Mock(status=302)
        response.getheader.side_effect = lambda name, default=None: 'https://evil.invalid/private' if name == 'Location' else default
        connection.getresponse.return_value = response
        with patch('music_link_preview.public_address', return_value='8.8.8.8'), patch('music_link_preview.PublicHTTPSConnection', return_value=connection) as opened:
            with self.assertRaises(PreviewError) as error:
                fetch('https://spotify.link/song', HTML_LIMIT, time.monotonic()+5)
        self.assertEqual(error.exception.status, 400)
        self.assertEqual(opened.call_count, 1)
        response.close.assert_called_once()

    def test_og_title_and_image_data_url_and_lru_cache(self):
        image = b'\x89PNG\r\n\x1a\nimage'
        calls = []
        def read(url, limit, deadline, image=False):
            calls.append((url,limit,image))
            if image:return url, 'image/png', b'\x89PNG\r\n\x1a\nimage'
            return 'https://open.spotify.com/track/song', 'text/html', b'<title>fallback</title><meta property="og:title" content="Song &amp; Artist | Spotify"><meta property="og:image" content="https://cdn.example.com/cover.png">'
        clock = Mock(return_value=1)
        service = MusicLinkPreview(read, clock)
        result = service.preview('https://spotify.link/song#share')
        self.assertEqual(result, dict(title='Song & Artist', provider='spotify', image='data:image/png;base64,'+base64.b64encode(image).decode()))
        self.assertEqual(calls[1][1], IMAGE_LIMIT)
        self.assertEqual(service.preview('https://spotify.link/song'), result)
        self.assertEqual(len(calls), 2)
        clock.return_value = 3602
        service.preview('https://spotify.link/song')
        self.assertEqual(len(calls), 4)
        for i in range(260):service.preview('https://open.spotify.com/track/'+str(i))
        self.assertEqual(len(service.cache), 256)

    def test_title_fallback_suffixes_and_korean_charset(self):
        for url, text, expected, category in (
            ('https://music.youtube.com/watch?v=a', '노래 - YouTube Music', '노래', 'youtube-music'),
            ('https://youtu.be/a', 'Song - YouTube', 'Song', 'youtube'),
            ('https://m2.melon.com/song', '노래 - 멜론', '노래', 'melon'),
            ('https://melon.com/song', 'A - B', 'A - B', 'melon')):
            service = MusicLinkPreview(lambda *args, **kw: (url, 'text/html; charset=euc-kr', ('<title>'+text+'</title>').encode('euc-kr')))
            result = service.preview(url)
            self.assertEqual((result['title'], result['provider']), (expected, category))
            self.assertIsNone(result['image'])

    def test_images_are_size_capped_typed_and_public_only(self):
        self.assertIsNone(image_data('image/png', b'\x89PNG\r\n\x1a\n'+b'x'*IMAGE_LIMIT))
        self.assertIsNone(image_data('image/svg+xml', b'<svg/>'))
        self.assertIsNone(image_data('image/jpeg', b'<html/>'))
        self.assertTrue(image_data('image/webp', b'RIFFxxxxWEBPxxx').startswith('data:image/webp;base64,'))
        for image in ('http://cdn.example.com/a.jpg', 'https://cdn.example.com/a.jpg'):
            def read(url, limit, deadline, **kw):
                if kw.get('image'):raise PreviewError('size_limit')
                return url, 'text/html', ('<title>Song</title><meta property="og:image" content="'+image+'">').encode()
            self.assertIsNone(MusicLinkPreview(read).preview('https://youtube.com/watch?v=a')['image'])
        with patch('music_link_preview.socket.getaddrinfo', return_value=[(2,1,6,'',('127.0.0.1',443))]):
            with self.assertRaises(PreviewError):fetch('https://cdn.example.com/a.png', IMAGE_LIMIT, time.monotonic()+5, image=True)

    def test_download_reads_at_most_limit_plus_one_truncates_html_and_rejects_large_images(self):
        import io
        for image,limit in ((False,HTML_LIMIT),(True,IMAGE_LIMIT)):
            stream=io.BytesIO(b'x'*(limit+1));response=Mock(status=200)
            response.getheader.side_effect=lambda name,default=None: 'image/png' if name=='Content-Type' else default
            response.read1.side_effect=stream.read
            connection=Mock();connection.getresponse.return_value=response
            with patch('music_link_preview.public_address',return_value='8.8.8.8'),patch('music_link_preview.PublicHTTPSConnection',return_value=connection):
                if image:
                    with self.assertRaises(PreviewError)as error:fetch('https://melon.com/a',limit,time.monotonic()+5,image=image)
                    self.assertEqual(error.exception.reason,'size_limit')
                else:
                    self.assertEqual(len(fetch('https://melon.com/a',limit,time.monotonic()+5,image=image)[2]),limit)
            self.assertEqual(stream.tell(),limit+1)
            response.close.assert_called_once()

    def test_html_size_title_and_total_timeout_failures(self):
        for body in (b'x'*(HTML_LIMIT+1), b'<html>no title</html>'):
            with self.assertRaises(PreviewError):MusicLinkPreview(lambda *a, **kw: (a[0], 'text/html', body)).preview('https://melon.com/')
        with self.assertRaises(PreviewError):fetch('https://melon.com/', HTML_LIMIT, time.monotonic()-1)

    def test_router_requires_browser_session_rates_and_maps_errors_without_url_logs(self):
        auth=Mock(enabled=True);auth.browser.return_value=dict(id='owner');service=Mock()
        endpoint=create_router(auth,service).routes[0].endpoint
        request=Request(dict(type='http',method='GET',headers=[],query_string=b'url=https%3A%2F%2Fmelon.com%2Fsong%3Fsecret%3Dprivate'))
        service.preview.return_value=dict(title='Song',image=None,provider='melon')
        self.assertEqual(endpoint(request,Response()),service.preview.return_value)
        auth.rate.assert_called_with('music-link-preview:owner',limit=60)
        self.assertEqual(auth.browser.call_count,2)
        service.preview.side_effect=PreviewError('page_unavailable')
        with self.assertLogs('wegoh',level='WARNING') as logged, self.assertRaises(HTTPException) as error:
            endpoint(request,Response())
        self.assertEqual((error.exception.status_code,error.exception.detail),(502,'MUSIC_LINK_UNAVAILABLE'))
        self.assertNotIn('secret',str(logged.output));self.assertNotIn('private',str(logged.output))
        auth.browser.side_effect=HTTPException(401,'Start a team session first')
        with self.assertRaises(HTTPException):endpoint(request,Response())


if __name__ == '__main__':unittest.main()
