"""Four bounded cleanup fault transitions; not a real transport race simulation."""
import unittest
from fastapi import WebSocketDisconnect
from team_data import close_socket

class ClosingTransport:
    def __init__(self,error=None):self.error=error;self.codes=[]
    async def close(self,code):
        self.codes.append(code)
        if self.error:raise self.error

class NativeCleanupTests(unittest.IsolatedAsyncioTestCase):
    async def verify_cleanup(self,error):
        transport=ClosingTransport(error);await close_socket(transport);self.assertEqual(transport.codes,[1008])
    async def test_01_normal_close_and_unrelated_errors(self):
        await self.verify_cleanup(None)
        with self.assertRaises(ValueError):await close_socket(ClosingTransport(ValueError('Unexpected programming error')))
    async def test_02_disconnected_transport(self):await self.verify_cleanup(WebSocketDisconnect(code=1006))
    async def test_03_already_closed_state(self):await self.verify_cleanup(RuntimeError('Already closed transport'))
    async def test_04_os_transport_error(self):await self.verify_cleanup(OSError('Disconnected transport'))

if __name__=='__main__':unittest.main(verbosity=2)
