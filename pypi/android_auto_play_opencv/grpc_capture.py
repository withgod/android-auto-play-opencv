"""Synchronous EmulatorController screenshot capture.

The vendored stubs are generated from the Android Emulator 36.2.12.0
(build 14214601) SDK proto in emulator/lib/emulator_controller.proto.
"""

import configparser
import glob
import logging
import os
import platform

logger = logging.getLogger(__name__)
EXPECTED_SIZE = (1080, 2400)
CIRCUIT_BREAKER_THRESHOLD = 5


def _discovery_globs():
    """Candidate glob patterns for the emulator's pid_<PID>.ini discovery
    files, which live in a platform-specific temp location.

    Set AAPO_GRPC_DISCOVERY_DIR to override outright. The macOS path is
    confirmed against a live emulator; the other platforms are unverified
    best-effort guesses (this project's dev environment is macOS-only) - if
    discovery never finds anything, capture() just falls back to adb, so a
    wrong guess degrades safely rather than breaking anything.
    """
    override = os.environ.get('AAPO_GRPC_DISCOVERY_DIR')
    if override:
        return [os.path.join(override, 'pid_*.ini')]
    system = platform.system()
    if system == 'Darwin':
        return [os.path.expanduser('~/Library/Caches/TemporaryItems/avd/running/pid_*.ini')]
    if system == 'Linux':
        tmp = os.environ.get('TMPDIR', '/tmp')
        user = os.environ.get('USER', '*')
        return [os.path.join(tmp, 'android-%s' % user, 'avd', 'running', 'pid_*.ini')]
    # No known default for Windows (or anything else). This is deliberate,
    # not an oversight: the EmulatorController gRPC service this backend
    # talks to is specific to the official Android Emulator (AVD) - it is
    # not something third-party emulators such as NoxPlayer expose, and
    # this package is commonly used with those on Windows. Guessing a path
    # there would be actively misleading rather than just incomplete.
    # AAPO_CAPTURE_BACKEND=grpc always falls back to plain adb in that case;
    # set AAPO_GRPC_DISCOVERY_DIR explicitly if your setup does expose one.
    return []

# One channel per device, reused across calls in this process (para.sh runs
# one process per device, so a module-level cache is sufficient). Dropped
# and rebuilt on RpcError.
_channels = {}
# Consecutive capture() failures per device. Past CIRCUIT_BREAKER_THRESHOLD,
# capture() fails fast without touching the network: a grpc endpoint that is
# down/misconfigured for the whole process shouldn't cost 3 retries x 3s
# timeout on every single screencap() call for the rest of the run.
#
# Deliberately no half-open/reset-after-cooldown: once tripped, a device
# stays on adb for the rest of the process. Fine for the normal one-job-
# one-process model; a long-lived process (e.g. `pochi2 -n 360`) that hits
# 5 transient failures in a row will fall back to adb for its remainder
# too, which is the safe direction to fail in.
_consecutive_failures = {}


def _discovery(device):
    serial_port = device.rsplit('-', 1)[-1] if device.startswith('emulator-') else ''
    filenames = [f for pattern in _discovery_globs() for f in glob.glob(pattern)]
    for filename in filenames:
        try:
            pid = int(os.path.basename(filename)[4:-4])
            os.kill(pid, 0)
        except (ValueError, OSError):
            continue
        # These discovery files are flat key=value pairs with no [section]
        # header, which configparser.read() cannot parse directly (it raises
        # MissingSectionHeaderError). Synthesize one section to reuse it.
        try:
            with open(filename, encoding='utf-8') as fh:
                text = fh.read()
        except OSError:
            continue
        parser = configparser.ConfigParser(interpolation=None)
        try:
            parser.read_string('[discovery]\n' + text)
            values = dict(parser['discovery'])
        except configparser.Error:
            continue
        if values.get('port.serial', '') != serial_port:
            continue
        try:
            port = int(values['grpc.port'])
        except (KeyError, ValueError):
            continue
        token = values.get('grpc.token')
        if not token:
            logger.warning('gRPC discovery has no authentication token: %s', filename)
            return None
        return port, token
    return None


def _png_size(data):
    """Read width/height straight out of the PNG IHDR chunk.

    capture() only ever hands back PNG bytes, so a full cv2.imdecode just to
    validate the resolution would be a second decode of the same image for
    no reason (the caller decodes it again downstream) - the IHDR chunk is
    always the 8-byte PNG signature followed immediately by a 4-byte length,
    the 4-byte tag b"IHDR", then big-endian width/height, so this needs no
    decoding at all.
    """
    if len(data) < 24 or data[:8] != b'\x89PNG\r\n\x1a\n' or data[12:16] != b'IHDR':
        return None
    width = int.from_bytes(data[16:20], 'big')
    height = int.from_bytes(data[20:24], 'big')
    return width, height


def _get_channel(device, port):
    import grpc
    cached = _channels.get(device)
    if cached is not None and cached[0] == port:
        return cached[1]
    if cached is not None:
        cached[1].close()
    channel = grpc.insecure_channel('127.0.0.1:%d' % port)
    _channels[device] = (port, channel)
    return channel


def _drop_channel(device):
    cached = _channels.pop(device, None)
    if cached is not None:
        cached[1].close()


def capture(device):
    """Return a native-size PNG, or raise an ordinary capture exception."""
    import grpc  # Deliberately lazy: adb users need no grpcio installation.
    from . import emulator_controller_pb2 as pb2
    from . import emulator_controller_pb2_grpc as pb2_grpc

    if _consecutive_failures.get(device, 0) >= CIRCUIT_BREAKER_THRESHOLD:
        raise RuntimeError('EmulatorController capture disabled after repeated failures: %s' % device)

    discovery = _discovery(device)
    if discovery is None:
        _consecutive_failures[device] = _consecutive_failures.get(device, 0) + 1
        raise RuntimeError('EmulatorController discovery failed')

    # width=0/height=0 asks the emulator for the device's native resolution
    # with no scaling. A fixed width/height would silently letterbox/scale
    # the image if the AVD's actual resolution ever differs from what we
    # expect, which would break every one of the ~800 fixed-coordinate
    # templates without so much as a warning.
    request = pb2.ImageFormat(format=pb2.ImageFormat.PNG, width=0, height=0, display=0)
    last_exc = None
    for attempt in range(3):
        port, token = discovery
        channel = _get_channel(device, port)
        try:
            response = pb2_grpc.EmulatorControllerStub(channel).getScreenshot(
                request, metadata=(('authorization', 'Bearer ' + token),), timeout=3)
            data = bytes(response.image)
            if not data:
                raise ValueError('EmulatorController returned an empty screenshot')
            if _png_size(data) != EXPECTED_SIZE:
                raise ValueError('unexpected screenshot resolution: %r' % (_png_size(data),))
            _consecutive_failures[device] = 0
            return data
        except grpc.RpcError as e:
            last_exc = e
            _drop_channel(device)
            if attempt == 2:
                break
            logger.warning('EmulatorController screenshot RPC failed; rediscovering')
            discovery = _discovery(device) or discovery
        except ValueError:
            _consecutive_failures[device] = _consecutive_failures.get(device, 0) + 1
            raise
    _consecutive_failures[device] = _consecutive_failures.get(device, 0) + 1
    raise RuntimeError('EmulatorController screenshot failed') from last_exc
