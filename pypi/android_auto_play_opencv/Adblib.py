import os
import struct
import subprocess
import logging
from time import sleep

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# adbコマンドが端末側の一時的な無応答に巻き込まれて無期限にブロックしないための上限。
# 通常のinput/screencap系コマンドは1秒未満で完了する。3秒で応答が無い時点で既に異常なので、
# 1秒間隔で最大5回まで試し、それでも復帰しなければ諦めてAdbTimeoutErrorを投げる
# (合計待ち時間は3秒×5回+1秒×4回=約19秒で、単発20秒タイムアウトだった旧実装とほぼ同じ)。
ADB_ATTEMPT_TIMEOUT_SECONDS = 3
ADB_MAX_ATTEMPTS = 5
ADB_RETRY_INTERVAL_SECONDS = 1


class AdbTimeoutError(Exception):
    """adbコマンドがADB_MAX_ATTEMPTS回リトライしても応答しなかったことを示す。"""
    pass


class Adblib:

    adbpath: str = ''
    device: str = ''
    screenImg = []
    devices = []

    # コンストラクタ（引数なし）
    def __init__(self):
        pass

    # コンストラクタ
    def __init__(self, _adbpath: str):
        self.adbpath = _adbpath

        try:
            results = self._run([self.adbpath + 'adb', 'devices'], capture_output=True)
        except FileNotFoundError:
            logger.error('adb.exe が見つかりません。（' + self.adbpath + 'adb.exe' + '）')
            exit()

        # バイト列を文字列に変換
        results = str(results, 'utf-8')
        # 文字列を分割
        self.devices = results.splitlines()
        if len(self.devices) <= 2:
            return
        # 先頭行を削除（不要なメッセージのため）
        self.devices.pop(0)
        # とりあえず先頭のデバイスを設定（後で変更もできる）
        self.setdevice(self.devices[0])

    def _run(self, cmd, capture_output=False, extra_timeout=0):
        """adbコマンドを実行する。

        一時的な無応答(TimeoutExpired)はADB_MAX_ATTEMPTS回までADB_RETRY_INTERVAL_SECONDS
        間隔でリトライし、それでも復帰しなければAdbTimeoutErrorを投げる。
        FileNotFoundError(adb本体が無い)やCalledProcessError等はリトライせずそのまま伝播させる。
        """
        timeout = ADB_ATTEMPT_TIMEOUT_SECONDS + extra_timeout
        last_exc = None
        for attempt in range(1, ADB_MAX_ATTEMPTS + 1):
            try:
                if capture_output:
                    return subprocess.check_output(cmd, timeout=timeout)
                subprocess.call(cmd, timeout=timeout)
                return None
            except subprocess.TimeoutExpired as e:
                last_exc = e
                logger.warning('adb command timed out (attempt %d/%d, timeout=%.1fs): %s' % (attempt, ADB_MAX_ATTEMPTS, timeout, cmd))
                if attempt < ADB_MAX_ATTEMPTS:
                    sleep(ADB_RETRY_INTERVAL_SECONDS)
        logger.error('adb command failed after %d attempts: %s' % (ADB_MAX_ATTEMPTS, cmd))
        raise AdbTimeoutError('adb command timed out after %d attempts: %s' % (ADB_MAX_ATTEMPTS, cmd)) from last_exc

    def setdevice(self, _devise):
        self.device = _devise.split()[0]
        logger.info(self.device)

    def inputtext(self, _message):
        self._run([self.adbpath + 'adb', '-s', self.device, 'shell', 'input', 'text', _message])

    def inputkeyevent(self, _keyevent):
        self._run([self.adbpath + 'adb', '-s', self.device, 'shell', 'input', 'keyevent', str(_keyevent)])

    def touch(self, _x, _y):
        self._run([self.adbpath + 'adb', '-s', self.device, 'shell', 'input', 'touchscreen', 'tap', str(_x), str(_y)])

    def longTouch(self, _x, _y, _msec):
        self._run([self.adbpath + 'adb', '-s', self.device, 'shell', 'input', 'touchscreen', 'swipe', str(_x), str(_y), str(_x), str(_y), str(_msec)], extra_timeout=_msec / 1000)

    def swipeTouch(self, _x1, _y1, _x2, _y2, _msec):
        self._run([self.adbpath + 'adb', '-s', self.device, 'shell', 'input', 'touchscreen', 'swipe', str(_x1), str(_y1), str(_x2), str(_y2), str(_msec)], extra_timeout=_msec / 1000)

    def screencap(self):
        # 画面キャプチャ
        if os.environ.get('AAPO_RAW_SCREENCAP') == '1':
            try:
                self._screencap_raw()
                return
            except Exception as e:
                logger.warning('raw screencap failed (%s), falling back to PNG' % e)
        self._screencap_png()

    def _screencap_png(self):
        self.screenImg = self._run([self.adbpath + 'adb', '-s', self.device, 'exec-out', 'screencap', '-p'], capture_output=True)

    def _screencap_raw(self):
        buf = self._run([self.adbpath + 'adb', '-s', self.device, 'exec-out', 'screencap'], capture_output=True)
        w, h, fmt = struct.unpack_from('<III', buf, 0)
        if fmt != 1:
            raise ValueError('Unexpected screencap format: %d' % fmt)
        # Android バージョンによりヘッダが12/16バイト変わるため、バッファ長から逆算してオフセットを求める
        off = len(buf) - w * h * 4
        img = np.frombuffer(buf, np.uint8, count=w * h * 4, offset=off).reshape(h, w, 4)
        self.screenImg = cv2.cvtColor(img, cv2.COLOR_RGBA2BGR)

    def kill(self):
        self._run([self.adbpath + 'adb', 'kill-server'])

    def start(self, _package):
        self._run([self.adbpath + 'adb', '-s', self.device, 'shell', 'am', 'start', '-n', _package])

    def end(self, _package):
        self._run([self.adbpath + 'adb', '-s', self.device, 'shell', 'am', 'force-stop', _package])

    def clear(self, _package):
        # キャッシュ削除
        self._run([self.adbpath + 'adb', '-s', self.device, 'shell', 'pm', 'clear', _package])
