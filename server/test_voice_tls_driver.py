"""Run the original Voice8 with deterministic owned TLS transport cleanup.

Installed websockets and product handlers are unchanged. Handshake failures keep
and re-raise their original exception; no timeout, retry, or assertion changes.
"""
import datetime,json,socket,unittest
from websockets.sync.client import ClientConnection
import test_team_voice as target

class OwnedTLSConnection(ClientConnection):
    def handshake(self,*args,**kwargs):
        try:return super().handshake(*args,**kwargs)
        except BaseException as error:
            print(json.dumps({'stage':'original-handshake-error','at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'exceptionType':type(error).__name__,'httpStatus':getattr(getattr(error,'response',None),'status_code',None)}),flush=True)
            raise
    def close_socket(self):
        # Wake an owned TLS recv before upstream's otherwise unbounded join.
        # Python close() notes shutdown() for timely connection termination:
        # https://docs.python.org/3.12/library/socket.html#socket.socket.close
        try:self.socket.shutdown(socket.SHUT_RDWR)
        except OSError:pass
        super().close_socket()

def main():
    original=target.connect
    def owned_connect(*args,**kwargs):
        kwargs['create_connection']=OwnedTLSConnection
        return original(*args,**kwargs)
    target.connect=owned_connect
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(target.VoiceTests))
    raise SystemExit(0 if result.wasSuccessful()else 1)

if __name__=='__main__':main()
