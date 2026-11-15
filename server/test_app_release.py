"""Isolated publication boundary; synthetic signing tools are not release evidence."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import urllib.request
import urllib.error
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'server'))
from app_release import app_release,load_release,validate_release
from fastapi import HTTPException

spec=importlib.util.spec_from_file_location('register_release',ROOT/'server/ops/register_release.py')
register=importlib.util.module_from_spec(spec);spec.loader.exec_module(register)


class ReleaseCatalogTests(unittest.TestCase):
    def value(self):
        return dict(schemaVersion=1,packageName='io.wegoh.app',versionCode=5,versionName='0.5.0',
            apkSha256='a'*64,signingCertificatesSha256=['b'*64])

    def test_absent_offline_invalid_are_not_latest(self):
        with patch.dict(os.environ,{},clear=True):
            with self.assertRaises(HTTPException) as caught:app_release()
            self.assertEqual(404,caught.exception.status_code)
        with patch.dict(os.environ,{'WEGOH_APP_RELEASE_FILE':'missing-synthetic-release.json'},clear=True):
            with self.assertRaises(HTTPException) as caught:app_release()
            self.assertEqual(503,caught.exception.status_code)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'release.json';path.write_text(json.dumps(self.value()))
            self.assertEqual(5,load_release(path)['versionCode'])
            path.write_bytes(b' '*8193)
            with self.assertRaises(ValueError):load_release(path)

    def test_package_redirect_and_coercions_rejected(self):
        for key,bad in [('schemaVersion',True),('packageName','other.app'),('versionCode',True),('versionCode','5'),
                        ('versionCode',0),('versionName','a\nb'),('apkSha256','https://other'),
                        ('signingCertificatesSha256',[]),('signingCertificatesSha256',[{}]),('signingCertificatesSha256',['b'*64]*2),
                        ('downloadUrl','https://other/evil.apk')]:
            value=self.value();value[key]=bad
            with self.subTest(key=key,bad=bad),self.assertRaises(ValueError):validate_release(value)

    def test_registration_requires_verified_nondebuggable_apk(self):
        with tempfile.TemporaryDirectory() as tmp:
            apk=Path(tmp)/'synthetic.apk';apk.write_bytes(b'synthetic not a real release')
            def completed(args,**kwargs):
                if args[0]=='apksigner':
                    self.assertEqual(['verify','--verbose','--print-certs'],args[1:4])
                    return subprocess.CompletedProcess(args,0,'Signer #1 certificate SHA-256 digest: '+'b'*64+'\n')
                return subprocess.CompletedProcess(args,0,"package: name='io.wegoh.app' versionCode='5' versionName='0.5.0'\n")
            with patch.object(register.subprocess,'run',side_effect=completed) as run:
                self.assertEqual(5,register.inspect_release(apk,'aapt','apksigner')['versionCode'])
                self.assertTrue(all(call.kwargs['timeout']==60 and call.kwargs['check'] for call in run.call_args_list))
            with patch.object(register.subprocess,'run',side_effect=subprocess.CalledProcessError(1,['verify'])):
                with self.assertRaises(subprocess.CalledProcessError):register.inspect_release(apk,'aapt','apksigner')
            with patch.object(register.subprocess,'run',side_effect=[
                subprocess.CompletedProcess([],0,'Signer #1 certificate SHA-256 digest: '+'b'*64+'\n'),
                subprocess.CompletedProcess([],0,"package: name='io.wegoh.app' versionCode='5' versionName='0.5.0'\napplication-debuggable\n")]):
                with self.assertRaises(ValueError):register.inspect_release(apk,'aapt','apksigner')
            def mutate(args,**kwargs):
                if args[0]=='apksigner':
                    apk.write_bytes(b'changed source during signature verification')
                    return subprocess.CompletedProcess(args,0,'Signer #1 certificate SHA-256 digest: '+'b'*64+'\n')
                return subprocess.CompletedProcess(args,0,"package: name='io.wegoh.app' versionCode='5' versionName='0.5.0'\n")
            with patch.object(register.subprocess,'run',side_effect=mutate):
                with self.assertRaisesRegex(ValueError,'changed during verification'):register.inspect_release(apk,'aapt','apksigner')

    @unittest.skipUnless(os.environ.get('WEGOH_STUDIO_TEST_URL'),'Requires the isolated Studio HTTP fixture')
    def test_actual_unregistered_release_http_is_not_a_current_version(self):
        origin=os.environ['WEGOH_STUDIO_TEST_URL']
        self.assertTrue(origin.startswith('http://127.0.0.1:'))
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(origin+'/v1/app-release',timeout=5)
        self.assertEqual(404,caught.exception.code)
        self.assertEqual('nosniff',caught.exception.headers['X-Content-Type-Options'])
        self.assertEqual({'detail':'App release unavailable'},json.load(caught.exception))


if __name__=='__main__':unittest.main()

