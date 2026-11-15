"""Shared deadline, transport and worker limits for uncached web providers."""
from contextvars import copy_context
from http.client import HTTPSConnection, HTTPException
from queue import Queue, Empty
import socket
from threading import Thread, Timer
import time
from urllib.parse import urlsplit

from api_tracing import traced_operation


def remaining_time(deadline, clock):
    remaining = deadline - clock()
    if remaining <= 0:
        raise TimeoutError()
    return remaining


def bounded_get(url, headers, timeout, max_bytes, *, error, connection_factory=HTTPSConnection, clock=time.monotonic):
    deadline = clock() + timeout
    target = urlsplit(url)
    if target.scheme != 'https' or not target.hostname or target.username or target.password:
        raise error()
    connection = connection_factory(target.hostname, target.port, timeout=remaining_time(deadline, clock))
    transport_socket = None

    def expire():
        active_socket = transport_socket or connection.sock
        if active_socket is not None:
            try:
                active_socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    expiry = Timer(remaining_time(deadline, clock), expire)
    expiry.daemon = True
    try:
        expiry.start()
        connection.connect()
        transport_socket = connection.sock
        transport_socket.settimeout(remaining_time(deadline, clock))
        connection.request('GET', target.path + ('?' + target.query if target.query else ''), headers=headers)
        transport_socket.settimeout(remaining_time(deadline, clock))
        with connection.getresponse() as response:
            remaining_time(deadline, clock)
            if response.status != 200:
                raise error()
            raw = bytearray()
            while True:
                transport_socket.settimeout(remaining_time(deadline, clock))
                chunk = response.read1(min(16 * 1024, max_bytes + 1 - len(raw)))
                remaining_time(deadline, clock)
                if not chunk:
                    return bytes(raw)
                raw.extend(chunk)
                if len(raw) > max_bytes:
                    raise error()
                if response.isclosed():
                    return bytes(raw)
    except TimeoutError:
        raise TimeoutError() from None
    except (OSError, HTTPException):
        remaining_time(deadline, clock)
        raise error() from None
    finally:
        expiry.cancel()
        if expiry.ident is not None:
            expiry.join()
        connection.close()



def rate_attempt(account, attempts, lock, clock, limit, error):
    from collections import deque
    now = clock()
    with lock:
        stale = [key for key, hits in attempts.items() if not hits or hits[-1] <= now - 60]
        for key in stale:
            del attempts[key]
        hits = attempts.setdefault(account, deque())
        while hits and hits[0] <= now - 60:
            hits.popleft()
        if len(hits) >= limit:
            raise error()
        hits.append(now)


def bounded_call(action, slots, timeout, error_type, prefix, *, name, thread_factory=Thread):
    operation = 'places.provider.wait' if prefix == 'PLACE_SEARCH' else 'route.provider.wait'
    with traced_operation(operation):
        return _bounded_call(action, slots, timeout, error_type, prefix, name, thread_factory)


def _bounded_call(action, slots, timeout, error_type, prefix, name, thread_factory):
    if not slots.acquire(blocking=False):
        raise error_type(prefix + '_BUSY', 503)
    output = Queue(maxsize=1)
    deadline = time.monotonic() + timeout

    def run():
        try:
            result = action(remaining_time(deadline, time.monotonic))
            remaining_time(deadline, time.monotonic)
            output.put((True, result))
        except error_type as error:
            output.put((False, (error.code, error.status)))
        except TimeoutError:
            output.put((False, (prefix + '_TIMEOUT', 504)))
        except Exception:
            output.put((False, (prefix + '_PROVIDER_UNAVAILABLE', 502)))
        finally:
            slots.release()

    try:
        # The worker joins the request's trace so provider HTTP spans keep their parent.
        context = copy_context()
        thread_factory(target=lambda: context.run(run), daemon=True, name=name).start()
    except Exception:
        slots.release()
        raise error_type(prefix + '_BUSY', 503) from None
    try:
        success, value = output.get(timeout=max(0, deadline - time.monotonic()) + .05)
    except Empty:
        raise error_type(prefix + '_TIMEOUT', 504) from None
    if not success:
        raise error_type(*value)
    return value
