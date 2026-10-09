"""Execute privileged APT commands without captured pipes that can remain open.

pkexec may return after apt completes while a descendant still owns stdout or stderr.
subprocess.run(capture_output=True) waits for *pipe EOF*, not only process exit.
A regular temporary log file lets us wait for the real pkexec process instead.
"""
import os
import subprocess
import tempfile
from dataclasses import dataclass


@dataclass
class AptResult:
    returncode: int
    stdout: str
    stderr: str


def elevated_apt(args, timeout=1800):
    """Wait for the privileged command process; never block waiting for pipe EOF.

    The caller controls the strict argument allowlist and simulates the plan first.
    Output is kept in a seekable temporary file, not exposed as a pipe.
    """
    if not isinstance(args, (list, tuple)) or args[:2] != ['pkexec', '/usr/bin/apt-get']:
        raise ValueError('Nur geprüfte APT-Kommandos sind erlaubt.')
    with tempfile.TemporaryFile(mode='w+b') as log:
        with subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT,
                              stdin=subprocess.DEVNULL,
                              env={**os.environ, 'LC_ALL': 'C'}) as proc:
            # Does not depend on any descendant closing an inherited descriptor.
            code = proc.wait(timeout=timeout)
        log.seek(0)
        data = log.read().decode('utf-8', errors='replace')
    return AptResult(code, data, '')
