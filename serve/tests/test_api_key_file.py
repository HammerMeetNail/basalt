"""--api-key-file: the API key read from a file, such as a mounted secret, and required on /v1/* like --api-key."""
from __future__ import annotations

import http.client
import json
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from serve.config import build_parser, load_config_file  # noqa: E402
from serve.security import api_key_from_file, api_key_of  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


class Files(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)

    def write(self, text: str, name: str = "key") -> str:
        path = self.dir / name
        path.write_text(text, encoding="utf-8")
        return str(path)


class FromFile(Files):
    def test_the_file_holds_the_key_with_or_without_a_line_end(self):
        for text in ("k3y", "k3y\n", "  k3y \r\n"):
            self.assertEqual(api_key_of(api_key_from_file(self.write(text))), "k3y")

    def test_a_file_without_a_key_is_refused(self):
        for text in ("", " \n"):
            with self.assertRaisesRegex(ValueError, "holds no key"):
                api_key_from_file(self.write(text))

    def test_a_missing_file_or_an_empty_path_is_refused(self):
        missing = str(self.dir / "none")
        with self.assertRaisesRegex(ValueError, re.escape(f"--api-key-file {missing}: ")):
            api_key_from_file(missing)
        with self.assertRaisesRegex(ValueError, "--api-key-file is empty"):
            api_key_from_file(" ")

    def test_the_config_cannot_name_the_file(self):
        path = self.write(json.dumps({"server": {"api-key-file": "/run/secrets/key"}}), "config.json")
        with self.assertRaisesRegex(ValueError, "api-key can't be set in a config file"):
            load_config_file(path, build_parser())


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Server(Files):
    def start(self, *argv):
        port = free_port()
        proc = subprocess.Popen([sys.executable, "-m", "serve.server", "--mock-engine", "--port", str(port), *argv],
                                cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        self.addCleanup(self.stop, proc)
        ready, lines = threading.Event(), []

        def read():
            for line in proc.stdout:
                lines.append(line)
                if line.startswith("[server] ready"):
                    ready.set()
        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        return proc, port, ready, lines, reader

    @staticmethod
    def stop(proc):
        if proc.poll() is None:
            proc.terminate()
        proc.wait(30)
        proc.stdout.close()

    @staticmethod
    def status(port: int, key: str | None = None) -> int:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        conn.request("GET", "/v1/models", headers={"Authorization": f"Bearer {key}"} if key else {})
        code = conn.getresponse().status
        conn.close()
        return code

    def test_the_key_in_the_file_is_required(self):
        proc, port, ready, lines, _ = self.start("--api-key-file", self.write("file-k3y\n"))
        self.assertTrue(ready.wait(60), "".join(lines))
        self.assertIn("api-key=on", next(x for x in lines if x.startswith("[server] ready")))
        self.assertEqual(self.status(port), 401)
        self.assertEqual(self.status(port, "wrong"), 401)
        self.assertEqual(self.status(port, "file-k3y"), 200)

    def test_a_file_and_a_key_together_stop_the_start(self):
        proc, port, ready, lines, reader = self.start("--api-key", "k", "--api-key-file", self.write("k"))
        self.assertEqual(proc.wait(60), 2)
        reader.join(10)
        self.assertIn("--api-key and --api-key-file both give a key", "".join(lines))

    def test_a_file_without_a_key_stops_the_start(self):
        proc, port, ready, lines, reader = self.start("--api-key-file", self.write("\n"))
        self.assertEqual(proc.wait(60), 2)
        reader.join(10)
        self.assertIn("holds no key", "".join(lines))


if __name__ == "__main__":
    unittest.main()
