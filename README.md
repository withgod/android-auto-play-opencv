# android-auto-play-opencv

Automate Android with OpenCV template matching over [adb](https://developer.android.com/studio/command-line/adb), so you keep control of your mouse cursor while it runs. Works with Android emulators (including NoxPlayer) as well as physical devices.

See [README-ja.md](README-ja.md) for the full documentation (Japanese only).

## Install

This fork isn't published to PyPI (the `android_auto_play_opencv` package there is the unmaintained original), so install straight from this repository:

```
pip install "git+https://github.com/withgod/android-auto-play-opencv.git#egg=android_auto_play_opencv&subdirectory=pypi"
```

Requires [Android SDK Platform-Tools](https://developer.android.com/studio/releases/platform-tools) (`adb`/`adb.exe`) on your `PATH` or passed in explicitly.

### Optional: gRPC screenshot backend

An opt-in faster screenshot path is available for the official Android Emulator (AVD), using its built-in EmulatorController gRPC service instead of `adb exec-out screencap`. It is not available for third-party emulators (e.g. NoxPlayer), which don't run the official emulator at all and so don't expose this service regardless of OS; those always use the default `adb` path.

```
pip install "android_auto_play_opencv[grpc] @ git+https://github.com/withgod/android-auto-play-opencv.git#subdirectory=pypi"
```

Enable it with the `AAPO_CAPTURE_BACKEND=grpc` environment variable. If it can't find or reach the emulator's gRPC endpoint, it automatically falls back to `adb`.

## Quick start

```python
import android_auto_play_opencv as am

aapo = am.AapoManager('..\\platform-tools\\')

while True:
    aapo.screencap()
    if aapo.touchImg('./template/some_button.png'):
        aapo.sleep(1)
```

See [README-ja.md](README-ja.md) for the full API reference and more examples.

## License

MIT (see [LICENSE](LICENSE)). The vendored gRPC/protobuf files under `pypi/android_auto_play_opencv/emulator_controller_pb2*.py` are generated from Google's Android Emulator SDK proto and are separately licensed Apache-2.0 (license header included in each file).
