import os
import struct
import subprocess
import logging

import cv2
import numpy as np

logger = logging.getLogger(__name__)

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
            results = subprocess.check_output([self.adbpath + 'adb', 'devices'])
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
    
    def setdevice(self, _devise):
        self.device = _devise.split()[0]
        logger.info(self.device)

    def inputtext(self, _message):
        subprocess.call([self.adbpath + 'adb', '-s', self.device, 'shell', 'input', 'text', _message])

    def inputkeyevent(self, _keyevent):
        subprocess.call([self.adbpath + 'adb', '-s', self.device, 'shell', 'input', 'keyevent', str(_keyevent)])

    def touch(self, _x, _y):
        subprocess.call([self.adbpath + 'adb', '-s', self.device, 'shell', 'input', 'touchscreen', 'tap', str(_x), str(_y)])

    def longTouch(self, _x, _y, _msec):
        subprocess.call([self.adbpath + 'adb', '-s', self.device, 'shell', 'input', 'touchscreen', 'swipe', str(_x), str(_y), str(_x), str(_y), str(_msec)])

    def swipeTouch(self, _x1, _y1, _x2, _y2, _msec):
        subprocess.call([self.adbpath + 'adb', '-s', self.device, 'shell', 'input', 'touchscreen', 'swipe', str(_x1), str(_y1), str(_x2), str(_y2), str(_msec)])

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
        self.screenImg = subprocess.check_output([self.adbpath + 'adb', '-s', self.device, 'exec-out', 'screencap', '-p'])

    def _screencap_raw(self):
        buf = subprocess.check_output([self.adbpath + 'adb', '-s', self.device, 'exec-out', 'screencap'])
        w, h, fmt = struct.unpack_from('<III', buf, 0)
        if fmt != 1:
            raise ValueError('Unexpected screencap format: %d' % fmt)
        # Android バージョンによりヘッダが12/16バイト変わるため、バッファ長から逆算してオフセットを求める
        off = len(buf) - w * h * 4
        img = np.frombuffer(buf, np.uint8, count=w * h * 4, offset=off).reshape(h, w, 4)
        self.screenImg = cv2.cvtColor(img, cv2.COLOR_RGBA2BGR)

    def kill(self):
        subprocess.call([self.adbpath + 'adb', 'kill-server'])

    def start(self, _package):
        subprocess.call([self.adbpath + 'adb', '-s', self.device, 'shell', 'am', 'start', '-n', _package])

    def end(self, _package):
        subprocess.call([self.adbpath + 'adb', '-s', self.device, 'shell', 'am', 'force-stop', _package])

    def clear(self, _package):
        # キャッシュ削除
        subprocess.call([self.adbpath + 'adb', '-s', self.device, 'shell', 'pm', 'clear', _package])
