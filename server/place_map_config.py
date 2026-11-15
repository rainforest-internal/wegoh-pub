"""Public browser map configuration and the SDK's explicit CSP origins."""
import os
import re


def public_map_config():
    key = os.environ.get('WEGOH_KAKAO_JS_KEY', '').strip()
    return dict(kakaoJsKey=key if re.fullmatch(r'[a-fA-F0-9]{32}', key) else None)


def studio_csp(connect_sources="'self'", *, preview=False):
    script = image = connect = ''
    if public_map_config()['kakaoJsKey']:
        script = ' https://dapi.kakao.com https://t1.kakaocdn.net'
        image = ' https://t1.kakaocdn.net https://mts.kakaocdn.net https://map.kakaocdn.net https://ctt-image.kakaocdn.net https://ssl.kakaocdn.net'
        connect = ' https://mts.kakaocdn.net'
    media = " media-src 'self' blob:;" if not preview else ''
    image_blob = ' blob:' if not preview else ''
    return ("default-src 'self'; script-src 'self'" + script + "; style-src 'self';" + media
            + " img-src 'self' data:" + image_blob + ' https://tile.openstreetmap.org' + image
            + '; connect-src ' + connect_sources + connect
            + "; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
