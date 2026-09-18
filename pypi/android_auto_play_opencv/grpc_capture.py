"""Synchronous EmulatorController screenshot capture.

The vendored stubs are generated from the Android Emulator 36.2.12.0
(build 14214601) SDK proto in emulator/lib/emulator_controller.proto.
"""

import configparser
import glob
import logging
import os

import cv2
import numpy as np

logger = logging.getLogger(__name__)
EXPECTED_SIZE = (1080, 2400)
DISCOVERY_GLOB = os.path.expanduser('~/Library/Caches/TemporaryItems/avd/running/pid_*.ini')


def _discovery(device):
    serial_port = device.rsplit('-', 1)[-1] if device.startswith('emulator-') else ''
    for filename in glob.glob(DISCOVERY_GLOB):
        try:
            pid = int(os.path.basename(filename)[4:-4])
            os.kill(pid, 0)
        except (ValueError, OSError):
            continue
        parser = configparser.ConfigParser()
        try:
            parser.read(filename)
            values = dict(parser.defaults())
            for section in parser.sections():
                values.update(parser[section])
        except (OSError, configparser.Error):
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


def capture(device):
    """Return a native-size PNG, or raise an ordinary capture exception."""
    import grpc  # Deliberately lazy: adb users need no grpcio installation.
    from . import emulator_controller_pb2 as pb2
    from . import emulator_controller_pb2_grpc as pb2_grpc

    discovery = _discovery(device)
    if discovery is None:
        raise RuntimeError('EmulatorController discovery failed')
    request = pb2.ImageFormat(format=pb2.ImageFormat.PNG, width=1080, height=2400, display=0)
    for attempt in range(3):
        port, token = discovery
        channel = grpc.insecure_channel('127.0.0.1:%d' % port)
        try:
            response = pb2_grpc.EmulatorControllerStub(channel).getScreenshot(
                request, metadata=(('authorization', 'Bearer ' + token),), timeout=3)
            data = bytes(response.image)
            if not data:
                raise ValueError('EmulatorController returned an empty screenshot')
            image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
            if image is None or image.shape[:2] != (2400, 1080):
                actual = None if image is None else image.shape[:2]
                raise ValueError('unexpected screenshot resolution: %r' % (actual,))
            return data
        except grpc.RpcError:
            if attempt == 2:
                raise
            logger.warning('EmulatorController screenshot RPC failed; rediscovering')
            discovery = _discovery(device) or discovery
        finally:
            channel.close()
    raise RuntimeError('EmulatorController screenshot failed')
