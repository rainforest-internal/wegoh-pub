import base64
from contextlib import suppress
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from html.parser import HTMLParser
import http.client
import ipaddress
import logging
import re
import socket
import ssl
from threading import Lock, Timer
import time
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

from fastapi import APIRouter, HTTPException, Query, Request, Response

HOSTS = frozenset(('melon.com', 'www.melon.com', 'm.melon.com', 'm2.melon.com', 'kko.to', 'kko.kakao.com',
    'open.spotify.com', 'spotify.link', 'music.youtube.com', 'www.youtube.com', 'youtube.com', 'm.youtube.com', 'youtu.be'))
HTML_LIMIT, IMAGE_LIMIT = 1536 * 1024, 150 * 1024
LOGGER = logging.getLogger('wegoh')
DNS_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix='music-preview-dns')


class PreviewError(Exception):
    def __init__(self, reason, status=502):
        self.reason, self.status = reason, status
        super().__init__(reason)


def normalize(value, *, image=False):
    try:
        if not isinstance(value, str) or not 1 <= len(value) <= 2048 or any(ord(c) < 33 for c in value):
            raise ValueError()
        parsed = urlsplit(value)
        host = (parsed.hostname or '').encode('idna').decode('ascii').lower()
        if parsed.scheme != 'https' or parsed.username is not None or parsed.password is not None or parsed.port not in (None, 443):
            raise ValueError()
        if not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?', host) or (not image and host not in HOSTS):
            raise ValueError()
        return urlunsplit(('https', host, quote(parsed.path or '/', safe="/%:@!$&'()*+,;=-._~"),
            quote(parsed.query, safe="%/?@!$&'()*+,;=:-._~"), ''))
    except (ValueError, UnicodeError):
        raise PreviewError('invalid_url', 400) from None


def remaining(deadline):
    value = deadline - time.monotonic()
    if value <= 0:
        raise PreviewError('timeout')
    return value


def public_address(host, deadline):
    remaining(deadline)
    task = DNS_POOL.submit(socket.getaddrinfo, host, 443, type=socket.SOCK_STREAM)
    try:
        answers = task.result(timeout=remaining(deadline))
    except (socket.gaierror, OSError, FutureTimeout):
        task.cancel()
        raise PreviewError('dns_unavailable') from None
    addresses = list(dict.fromkeys(row[4][0] for row in answers))
    if not addresses or any(not ipaddress.ip_address(address).is_global or ipaddress.ip_address(address).is_multicast for address in addresses):
        raise PreviewError('private_address', 400)
    return addresses[0]


class PublicHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host, address, deadline):
        super().__init__(host, timeout=min(3, remaining(deadline)), context=ssl.create_default_context())
        self.address, self.deadline = address, deadline

    def connect(self):
        sock = socket.create_connection((self.address, 443), timeout=min(3, remaining(self.deadline)))
        try:
            sock.settimeout(min(3, remaining(self.deadline)))
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        except BaseException:
            sock.close()
            raise


def fetch(url, limit, deadline, *, image=False):
    current = url
    for hop in range(4):
        current = normalize(current, image=image)
        parsed = urlsplit(current)
        address = public_address(parsed.hostname, deadline)
        connection = PublicHTTPSConnection(parsed.hostname, address, deadline)
        response, timer = None, None
        try:
            connection.connect()
            transport = connection.sock
            def expire():
                with suppress(OSError):
                    transport.shutdown(socket.SHUT_RDWR)
            timer = Timer(remaining(deadline), expire)
            timer.daemon = True
            timer.start()
            transport.settimeout(remaining(deadline))
            path = urlunsplit(('', '', parsed.path, parsed.query, ''))
            connection.request('GET', path, headers={'User-Agent': 'Mozilla/5.0 (compatible; WegoHLinkPreview/1.0)',
                'Accept': 'image/jpeg,image/png,image/webp' if image else 'text/html,application/xhtml+xml', 'Accept-Encoding': 'identity'})
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader('Location')
                if not location or hop == 3:
                    raise PreviewError('redirect_limit')
                current = urljoin(current, location)
                continue
            if response.status != 200:
                raise PreviewError('page_unavailable')
            length = response.getheader('Content-Length')
            if image and length and (not length.isdigit() or int(length) > limit):
                raise PreviewError('size_limit')
            result = bytearray()
            while True:
                transport.settimeout(remaining(deadline))
                chunk = response.read1(min(16384, limit + 1 - len(result)))
                if not chunk:
                    break
                result.extend(chunk)
                if len(result) > limit:
                    if not image:
                        del result[limit:]
                        break
                    raise PreviewError('size_limit')
            return current, response.getheader('Content-Type', '').strip().lower(), bytes(result)
        except (OSError, http.client.HTTPException, ValueError):
            raise PreviewError('fetch_unavailable') from None
        finally:
            if timer:
                timer.cancel()
            if response:
                response.close()
            connection.close()
    raise PreviewError('redirect_limit')


class Metadata(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.og_title, self.image, self.title = None, None, []
        self.in_title = False

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == 'meta':
            key = (values.get('property') or values.get('name') or '').lower()
            if key == 'og:title' and self.og_title is None:
                self.og_title = values.get('content')
            if key == 'og:image' and self.image is None:
                self.image = values.get('content')
        elif tag == 'title':
            self.in_title = True

    def handle_endtag(self, tag):
        if tag == 'title':
            self.in_title = False

    def handle_data(self, data):
        if self.in_title:
            self.title.append(data)


def provider(url):
    host = urlsplit(url).hostname
    if host in ('melon.com', 'www.melon.com', 'm.melon.com', 'm2.melon.com', 'kko.to', 'kko.kakao.com'):
        return 'melon'
    if host in ('open.spotify.com', 'spotify.link'):
        return 'spotify'
    if host == 'music.youtube.com':
        return 'youtube-music'
    if host in ('www.youtube.com', 'youtube.com', 'm.youtube.com', 'youtu.be'):
        return 'youtube'
    return 'link'


def image_data(mime, data):
    valid = (mime == 'image/jpeg' and data.startswith(b'\xff\xd8\xff') or
        mime == 'image/png' and data.startswith(b'\x89PNG\r\n\x1a\n') or
        mime == 'image/webp' and data.startswith(b'RIFF') and data[8:12] == b'WEBP')
    return 'data:' + mime + ';base64,' + base64.b64encode(data).decode('ascii') if valid and len(data) <= IMAGE_LIMIT else None


class MusicLinkPreview:
    def __init__(self, fetcher=fetch, clock=time.monotonic):
        self.fetcher, self.clock = fetcher, clock
        self.cache, self.lock = OrderedDict(), Lock()

    def preview(self, value):
        url = normalize(value)
        with self.lock:
            saved = self.cache.get(url)
            if saved and self.clock() - saved[0] < 3600:
                self.cache.move_to_end(url)
                return dict(saved[1])
        deadline = time.monotonic() + 5
        final, mime, body = self.fetcher(url, HTML_LIMIT, deadline)
        if mime.split(';')[0].strip() not in ('text/html', 'application/xhtml+xml') or len(body) > HTML_LIMIT:
            raise PreviewError('invalid_html')
        document = Metadata()
        try:
            charset = re.search(r'''charset\s*=\s*['"]?([a-z0-9_-]+)''', mime + ' ' + body[:4096].decode('ascii', errors='ignore'), re.I)
            encoding = charset[1].lower() if charset and charset[1].lower() in ('euc-kr', 'cp949') else 'utf-8'
            document.feed(body.decode(encoding, errors='replace'))
        except (ValueError, RecursionError):
            raise PreviewError('invalid_html') from None
        title = re.sub(r'\s+', ' ', ''.join(' ' if ord(c) < 32 else c for c in (document.og_title or ''.join(document.title)))).strip()
        for suffix in (' - YouTube Music', ' - YouTube', ' | Spotify', ' - Spotify', ' - 멜론', ' | 멜론'):
            if title.endswith(suffix) and len(title) > len(suffix):
                title = title[:-len(suffix)].strip()
                break
        if not title:
            raise PreviewError('title_unavailable')
        image = None
        if document.image:
            try:
                image_url = normalize(urljoin(final, document.image), image=True)
                _, image_mime, data = self.fetcher(image_url, IMAGE_LIMIT, deadline, image=True)
                image = image_data(image_mime.split(';')[0].strip(), data)
            except PreviewError:
                pass
        result = dict(title=title[:120], image=image, provider=provider(final))
        with self.lock:
            self.cache[url] = (self.clock(), result)
            self.cache.move_to_end(url)
            while len(self.cache) > 256:
                self.cache.popitem(last=False)
        return dict(result)


def create_router(auth, service=None):
    router = APIRouter()
    if not auth.enabled:
        return router
    preview = service if service is not None else MusicLinkPreview()

    @router.get('/v1/music/link-preview')
    def link_preview(request: Request, response: Response, url: str = Query('', description='허용된 음악 서비스의 HTTPS 공유 링크.')):
        identity = auth.browser(request)
        response.headers['Cache-Control'] = 'private, no-store'
        auth.rate('music-link-preview:' + identity['id'], limit=60)
        if set(request.query_params) != {'url'} or len(request.query_params.getlist('url')) != 1:
            LOGGER.warning('music.link_preview: failed reason=invalid_query')
            raise HTTPException(400, 'MUSIC_LINK_INVALID')
        try:
            result = preview.preview(request.query_params['url'])
        except PreviewError as error:
            LOGGER.warning('music.link_preview: failed reason=%s', error.reason)
            raise HTTPException(error.status, 'MUSIC_LINK_INVALID' if error.status == 400 else 'MUSIC_LINK_UNAVAILABLE') from None
        if auth.browser(request)['id'] != identity['id']:
            raise HTTPException(401, 'Authentication changed')
        LOGGER.info('music.link_preview: loaded provider=%s', result['provider'])
        return result

    return router
