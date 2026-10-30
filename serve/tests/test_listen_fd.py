"""--listen-fd: the server takes a listening socket already open on a descriptor, as systemd socket activation passes
one, instead of binding its own."""
from __future__ import annotations

import http.client
import os
import socket
import subprocess
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from serve.handler import listen_socket  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


def listener(kind=socket.SOCK_STREAM, listen=True) -> socket.socket:
    s = socket.socket(socket.AF_INET, kind)
    s.bind(("127.0.0.1", 0))
    if listen:
        s.listen()
    return s


def listening_is_readable() -> bool:
    """Whether this system reports a socket's listening state; where it does not, any TCP socket passes."""
    with listener() as s:
        try:
            s.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN)
            return True
        except OSError:
            return False


@unittest.skipIf(os.name == "nt", "a descriptor is not a socket handle on Windows")
class ListenSocket(unittest.TestCase):
    def test_a_listening_tcp_socket_is_taken(self):
        with listener() as s:
            got = listen_socket(os.dup(s.fileno()))
            try:
                self.assertEqual(got.getsockname(), s.getsockname())
            finally:
                got.close()

    def test_anything_else_is_refused(self):
        refused = [listener(socket.SOCK_DGRAM, listen=False)]
        if listening_is_readable():
            refused.append(listener(listen=False))
        for sock in refused:
            with sock:
                fd = os.dup(sock.fileno())
                try:
                    with self.assertRaisesRegex(ValueError, f"--listen-fd {fd}: not a listening TCP socket"):
                        listen_socket(fd)
                finally:
                    os.close(fd)
        r, w = os.pipe()
        try:
            with self.assertRaisesRegex(ValueError, f"--listen-fd {r}: not a socket"):
                listen_socket(r)
        finally:
            os.close(r)
            os.close(w)


@unittest.skipIf(os.name == "nt", "the test passes a descriptor to the server process")
class ServerOnAPassedSocket(unittest.TestCase):
    def test_the_server_answers_on_the_socket_and_binds_nothing(self):
        with listener() as s, listener() as busy:
            port = busy.getsockname()[1]                # --port is taken: a server that binds would refuse it
            proc = subprocess.Popen([sys.executable, "-m", "serve.server", "--mock-engine", "--port", str(port),
                                     "--listen-fd", str(s.fileno())], cwd=ROOT, pass_fds=(s.fileno(),),
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            try:
                ready = threading.Event()
                lines = []

                def read():
                    for line in proc.stdout:
                        lines.append(line)
                        if line.startswith("[server] ready"):
                            ready.set()
                threading.Thread(target=read, daemon=True).start()
                self.assertTrue(ready.wait(60), "".join(lines))
                ready_line = next(x for x in lines if x.startswith("[server] ready"))
                self.assertIn(f"127.0.0.1:{s.getsockname()[1]}/v1", ready_line)
                self.assertIn(f"listen-fd={s.fileno()}", ready_line)
                conn = http.client.HTTPConnection("127.0.0.1", s.getsockname()[1], timeout=10)
                conn.request("GET", "/health")
                self.assertEqual(conn.getresponse().status, 200)
                conn.close()
            finally:
                proc.terminate()
                proc.wait(30)
                proc.stdout.close()

    def test_a_descriptor_that_is_no_socket_stops_the_start(self):
        proc = subprocess.run([sys.executable, "-m", "serve.server", "--mock-engine", "--listen-fd", "0"], cwd=ROOT,
                              stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("--listen-fd 0: not a socket", proc.stderr)


if __name__ == "__main__":
    unittest.main()
