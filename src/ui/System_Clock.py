#Sets system time
from __future__ import annotations
import shutil
import subprocess
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

class ClockError(RuntimeError):
    pass

def local_to_epoch(date_text, time_text, zone):
    try:
        dt = datetime.strptime(date_text + ' ' + time_text, '%Y-%m-%d %H:%M:%S')
        if not 2020 <= dt.year <= 2100:
            raise ValueError('Use a year between 2020 and 2100.')
        tz = ZoneInfo(zone)
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise ClockError('Use a valid date, 24-hour time HH:MM:SS and IANA time zone.') from exc
    instants = set()
    for fold in (0, 1):
        aware = dt.replace(tzinfo=tz, fold=fold)
        if datetime.fromtimestamp(aware.timestamp(), tz).replace(tzinfo=None) == dt:
            instants.add(int(aware.timestamp()))
    if not instants:
        raise ClockError('daylight-saving error.')
    if len(instants) != 1:
        raise ClockError('daylight-saving error. Time occurs twice during the daylight-saving transition.')
    return instants.pop()

class SystemClock:

    def __init__(self, runner=subprocess.run, binary=None):
        self.runner = runner
        self.binary = binary or shutil.which('timedatectl')
        self.supported = bool(self.binary)

    def _run(self, *args):
        if not self.supported:
            raise ClockError('')
        try:
            result = self.runner(
                [self.binary, '--no-ask-password', *args],
                capture_output=True,
                text=True,
                timeout=15,
                check=False
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ClockError(f'Clock command failed: {exc}') from exc
        if result.returncode:
            msg = (result.stderr or result.stdout or 'Command rejected').strip()
            raise ClockError(msg + '\nDo not run the whole app as root.') #Made this mistake a few too many times
        return result.stdout.strip()

    def status(self):
        if not self.supported:
            return {
                'supported': False,
                'timezone': str(datetime.now().astimezone().tzinfo),
                'ntp': None,
                'synchronized': None,
                'message': 'System clock is read-only in this preview.'
            }
        lines = self._run('show', '--property=Timezone', '--property=NTP', '--property=NTPSynchronized')
        d = dict((line.split('=', 1) for line in lines.splitlines() if '=' in line))
        return {
            'supported': True,
            'timezone': d.get('Timezone', 'UTC'),
            'ntp': d.get('NTP') == 'yes',
            'synchronized': d.get('NTPSynchronized') == 'yes',
        }

    def now(self):
        return datetime.now(timezone.utc)

    def apply(self, *, zone, ntp, date_text='', time_text=''):
        if type(ntp) is not bool:
            raise ClockError('Network time either enabled or disabled.')
        try:
            ZoneInfo(zone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ClockError('Select a valid time zone.') from exc
        epoch = None if ntp else local_to_epoch(date_text, time_text, zone)
        completed = []
        try:
            self._run('set-timezone', zone)
            completed.append('time zone')
            self._run('set-ntp', 'true' if ntp else 'false')
            completed.append('network-time setting')
            if epoch is not None:
                self._run('set-time', '@' + str(epoch))
                completed.append('system time')
        except ClockError as exc:
            raise ClockError(str(exc) + ('\nAlready changed: ' + ', '.join(completed) + '.' if completed else '')) from exc
        time.tzset()
        return self.status()

class MockClock:
    supported = True

    def __init__(self):
        self.zone = 'UTC'
        self.ntp = False
        self.base = datetime.now(timezone.utc).timestamp()
        self.mark = time.monotonic()

    def now(self):
        return datetime.fromtimestamp(self.base + time.monotonic() - self.mark, timezone.utc)

    def status(self):
        return {
            'supported': True,
            'timezone': self.zone,
            'ntp': self.ntp,
            'synchronized': False,
            'message': 'DEMO clock.'
        }

    def apply(self, *, zone, ntp, date_text='', time_text=''):
        ZoneInfo(zone)
        if not ntp:
            self.base = local_to_epoch(date_text, time_text, zone)
            self.mark = time.monotonic()
        self.zone = zone
        self.ntp = ntp
        return self.status()
