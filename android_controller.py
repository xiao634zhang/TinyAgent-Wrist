"""USB Android control; no root, APK installation, or implicit emulator selection."""
from pathlib import Path
import logging
import os
import re
import shlex
import shutil
import subprocess
import time
import uuid
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent


class AndroidController:
    def __init__(self, adb=None, serial=None, log_dir=None):
        self.adb = str(adb or os.environ.get('ANDROID_ADB') or
                       (ROOT / 'tools/platform-tools/adb.exe' if
                        (ROOT / 'tools/platform-tools/adb.exe').exists() else
                        shutil.which('adb') or 'adb'))
        self.serial = serial
        self.connected = False
        self.log_dir = Path(log_dir or ROOT / 'logs')
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log = logging.getLogger(f'android.{id(self)}')
        self.log.setLevel(logging.INFO)
        self.log.propagate = False
        handler = logging.FileHandler(self.log_dir / 'controller.log', encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
        self.log.addHandler(handler)

    def _run(self, args, device=True, timeout=30):
        if device and not self.connected:
            raise RuntimeError('Call connect() first.')
        command = [self.adb] + (['-s', self.serial] if device else []) + list(args)
        # Do not log input text, screen contents or notification bodies.
        operation = ' '.join(args[:2]) if args[0] != 'shell' else 'shell operation'
        started = time.monotonic()
        try:
            result = subprocess.run(command, capture_output=True, timeout=timeout, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            self.log.error('%s: %s', operation, type(exc).__name__)
            raise RuntimeError(f'ADB {operation}: {type(exc).__name__}') from exc
        self.log.info('%s rc=%s seconds=%.2f', operation, result.returncode,
                      time.monotonic() - started)
        if result.returncode:
            error = result.stderr.decode('utf-8', errors='replace').strip()
            self.log.error('ADB error: %s', error[:1000])
            raise RuntimeError(f'ADB failed: {error}')
        return result.stdout

    def shell(self, *args, timeout=30):
        return self._run(['shell', shlex.join(str(x) for x in args)], timeout=timeout).decode('utf-8', 'replace').strip()

    def connect(self):
        self.connected = False
        output = self._run(['devices', '-l'], device=False).decode('utf-8', 'replace')
        (self.log_dir / 'devices.txt').write_text(output, encoding='utf-8')
        devices = []
        for line in output.splitlines():
            fields = line.split()
            if len(fields) >= 2 and fields[1] in ('device', 'offline', 'unauthorized', 'no'):
                devices.append((fields[0], fields[1], line))
        if self.serial:
            candidates = [d for d in devices if d[0] == self.serial]
        else:
            # Windows adb may omit usb: from devices -l. Confirm with -d below.
            candidates = [d for d in devices if not d[0].startswith('emulator-')
                          and ('usb:' in d[2] or (':' not in d[0] and '_adb' not in d[0]))]
        if not candidates:
            raise RuntimeError('No USB phone found. Connect a data cable, unlock the phone and enable USB debugging. Emulator excluded.')
        if len(candidates) != 1:
            raise RuntimeError('Multiple USB devices: specify serial explicitly.')
        serial, state, _ = candidates[0]
        if state != 'device':
            raise RuntimeError(f'Device state: {state}. For unauthorized, accept the USB debugging prompt on the phone.')
        if not self.serial:
            usb_serial = self._run(['-d', 'get-serialno'], device=False).decode('utf-8', 'replace').strip()
            if usb_serial != serial:
                raise RuntimeError('USB identity could not be confirmed; specify serial explicitly after checking devices.')
        self.serial = serial
        self.connected = True
        return self.device_info()

    def device_info(self):
        return {'manufacturer': self.shell('getprop', 'ro.product.manufacturer'),
                'model': self.shell('getprop', 'ro.product.model'),
                'android': self.shell('getprop', 'ro.build.version.release'),
                'screen': self.shell('wm', 'size')}

    def screenshot(self, path=None):
        path = Path(path or self.log_dir / f'screen-{time.time_ns()}.png')
        data = self._run(['exec-out', 'screencap', '-p'])
        if not data.startswith(b'\x89PNG\r\n\x1a\n'):
            raise RuntimeError('screencap did not return PNG data')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def tap(self, x, y):
        return self.shell('input', 'tap', int(x), int(y))

    def swipe(self, x1, y1, x2, y2, duration=300):
        if not 1 <= int(duration) <= 60000:
            raise ValueError('duration must be 1..60000 milliseconds')
        return self.shell('input', 'swipe', int(x1), int(y1), int(x2), int(y2), int(duration))

    def input_text(self, text):
        if not text.isascii() or any(ord(c) < 32 for c in text) or '%' in text:
            raise ValueError('Only printable ASCII without % is supported. Chinese requires a separately approved IME/clipboard solution.')
        return self.shell('input', 'text', text.replace(' ', '%s'))

    def press_back(self):
        return self.shell('input', 'keyevent', 4)

    def press_home(self):
        return self.shell('input', 'keyevent', 3)

    def launch_app(self, package_name):
        if not re.fullmatch(r'[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+', package_name):
            raise ValueError('Invalid package name')
        resolved = self.shell('cmd', 'package', 'resolve-activity', '--brief', '-a',
                              'android.intent.action.MAIN', '-c',
                              'android.intent.category.LAUNCHER', package_name)
        components = [x.strip() for x in resolved.splitlines() if '/' in x]
        if not components or not components[-1].startswith(package_name + '/'):
            raise RuntimeError(f'No launcher activity for {package_name}: {resolved}')
        result = self.shell('am', 'start', '-W', '-n', components[-1])
        if 'Error:' in result or 'Exception' in result:
            raise RuntimeError(result)
        return result

    def get_ui_hierarchy(self, path=None):
        remote = f'/data/local/tmp/codex-ui-{uuid.uuid4().hex}.xml'
        try:
            self.shell('uiautomator', 'dump', remote, timeout=45)
            xml = self.shell('cat', remote)
            ET.fromstring(xml)
            if path:
                Path(path).write_text(xml, encoding='utf-8')
            return xml
        finally:
            self.shell('rm', '-f', remote)
