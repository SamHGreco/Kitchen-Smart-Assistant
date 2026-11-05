#!/usr/bin/env python3
"""Non-installing HX711 reset/clock-phase comparison for the patched project.

Run from Kitchen-Smart-Assistant-fixed, with its virtual environment active:
    python ~/Downloads/diagnose_hx711_link.py

Close the GUI and every other HX711 program. Keep the scanner unpowered.
This reads config.pi.json and uses its BCM pins. It does NOT edit application
code, calibration, configuration, or databases. It writes a timestamped report.
The alternative clock reader is diagnostic, NOT a guaranteed hardware fix.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib
import json
import math
from pathlib import Path
from statistics import median
import sys
import time


def load_settings(project: Path) -> tuple[int, int, float]:
    path = project / 'src' / 'ui' / 'config.pi.json'
    settings = json.loads(path.read_text(encoding='utf-8'))
    pins = settings['gpio']
    dout, sck = pins['scale_data'], pins['scale_clock']
    if any(type(pin) is not int or not 0 <= pin <= 27 for pin in (dout, sck)):
        raise ValueError('scale_data and scale_clock must be BCM integers 0..27.')
    if dout == sck:
        raise ValueError('DOUT and SCK cannot share a GPIO.')
    limit = settings.get('scale', {}).get('max_raw_spread', 2000.0)
    if isinstance(limit, bool) or not math.isfinite(float(limit)) or float(limit) <= 0:
        raise ValueError('Invalid scale.max_raw_spread.')
    return dout, sck, float(limit)


def describe(values: list[int], limit: float) -> dict:
    if len(values) != 9 or any(type(v) is not int or not -(1 << 23) <= v < (1 << 23)
                               for v in values):
        raise ValueError('Expected nine signed 24-bit integer readings.')
    spread = max(values) - min(values)
    suffix_count = sum((v & 0xFFFF) == 0xFFFF for v in values)
    saturated = any(v in (-8388608, 8388607) for v in values)
    suspect = suffix_count == len(values)
    status = ('SATURATED' if saturated else 'SUSPECT BITS' if suspect else
              'WITHIN LIMIT' if spread <= limit else 'OVER LIMIT')
    return dict(status=status, spread=spread, center=median(values),
                suffix_count=suffix_count, passed=(status == 'WITHIN LIMIT'))


def low_phase_driver(module):
    """Keep the same 24+1 framing, signed conversion, timeouts and timing guard.

    Difference: sample DOUT while SCK is LOW, after a 5 us minimum settling
    interval, rather than while SCK is HIGH. See HX711 timing Fig. 2.
    """
    class LowPhaseDriver(module.HX711Driver):
        def _pulse(self, read_bit=True):
            gpio = module.GPIO
            started = time.perf_counter_ns()
            try:
                gpio.output(self._sck_pin, gpio.HIGH)
                until = time.perf_counter_ns() + 1000
                while time.perf_counter_ns() < until:
                    pass
            finally:
                gpio.output(self._sck_pin, gpio.LOW)
            # This includes GPIO/Python overhead; it is NOT an oscilloscope
            # measurement. Keep the original conservative 50 us rejection.
            if time.perf_counter_ns() - started > 50000:
                raise module.ClockTimingError('Clock timing overrun; sample discarded.')
            until = time.perf_counter_ns() + 5000
            while time.perf_counter_ns() < until:
                pass
            return gpio.input(self._dout_pin) if read_bit else 0
    return LowPhaseDriver


def run_mode(label, factory, dout, sck, limit, emit):
    emit('\n' + label)
    driver = None
    result = {'passing': 0, 'errors': 0, 'suspect': 0, 'samples': 0, 'ff': 0}
    try:
        driver = factory(dout, sck)
        # Resynchronization is attempted in BOTH modes. No electrical power
        # rail is changed: this is only the HX711 clock-controlled reset.
        driver._reset()
        driver.raw_read(retries=1, timeout_seconds=2.0)  # select A/128; discard
        time.sleep(0.5)  # allow channel/gain settling before the comparisons
        for batch in range(1, 3):
            try:
                deadline = time.monotonic() + 3.0
                values = []
                for index in range(10):
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError('Sample group timed out.')
                    value = driver.raw_read(retries=1, timeout_seconds=remaining)
                    if index:  # identical first-conversion discard per batch
                        values.append(value)
                info = describe(values, limit)
                result['passing'] += int(info['passed'])
                result['suspect'] += int(info['status'] == 'SUSPECT BITS')
                result['samples'] += len(values)
                result['ff'] += info['suffix_count']
                emit(f'Batch {batch}: {info["status"]}  spread={info["spread"]}  '
                     f'limit={limit:g}  median={info["center"]:g}  '
                     f'last16_all_ones={info["suffix_count"]}/9')
                emit('  raw=' + ', '.join(str(v) for v in values))
                emit('  hex=' + ', '.join(f'{v & 0xFFFFFF:06X}' for v in values))
            except Exception as exc:
                result['errors'] += 1
                emit(f'Batch {batch}: ERROR {type(exc).__name__}: {exc}')
            if batch == 1:
                time.sleep(2.0)
    except Exception as exc:
        result['errors'] += 1
        emit(f'Mode ERROR {type(exc).__name__}: {exc}')
    finally:
        if driver is not None:
            driver.close()
    emit(f'SUMMARY {label}: within_limit={result["passing"]}/2; '
         f'errors={result["errors"]}; '
         f'last16_all_ones={result["ff"]}/{result["samples"]}')
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--project', type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    project = args.project.expanduser().resolve()
    lines = []

    def emit(text):
        lines.append(text)
        print(text, flush=True)

    try:
        dout, sck, limit = load_settings(project)
        emit('HX711 reset/clock comparison -- no application files are changed.')
        emit('UTC: ' + datetime.now(timezone.utc).isoformat())
        emit(f'PROJECT={project}\nBCM pins: DOUT={dout}; SCK={sck}; limit={limit:g}')
        emit('Close the GUI and ALL other scale programs. Keep the scanner unpowered.')
        emit('Keep the normal platform mounted, empty and untouched. Do not change wiring live.')
        if input('Type READY to confirm and start: ').strip() != 'READY':
            emit('Cancelled. No GPIO pins were opened.')
            return 2
        sys.path.insert(0, str(project / 'src'))
        module = importlib.import_module('scale.hx711_driver')
        path = Path(module.__file__).resolve()
        emit(f'READER={path}')
        emit('READER_SHA256=' + hashlib.sha256(path.read_bytes()).hexdigest())
        if not hasattr(module, 'ClockTimingError') or not hasattr(module.HX711Driver, '_reset'):
            raise RuntimeError('This is not the expected patched driver. No test started.')
        a = run_mode('A: EXISTING READER + RESET', module.HX711Driver,
                     dout, sck, limit, emit)
        b = run_mode('B: CLOCK-LOW READER + RESET', low_phase_driver(module),
                     dout, sck, limit, emit)
        emit('\nINTERPRETATION (diagnostic clues, not proof of cause):')
        if a['passing'] == 2 and b['passing'] == 2:
            emit('Both modes meet the unchanged spread limit. Reset or an intermittent '
                 'condition may matter; verify again before calibrating.')
        elif a['passing'] < 2 and b['passing'] == 2:
            emit('Clock-low sampling helped in this run. Timing or signal settling is '
                 'a candidate; this does not prove the wiring is electrically safe.')
        elif a['passing'] == 2:
            emit('Existing reader met the limit. The alternative did not improve it; '
                 'do not replace your production reader with this test.')
        else:
            emit('Neither mode meets the criteria. Check pins, connections, logic voltage '
                 'and clock integrity. Do not raise the limit or save calibration.')
        emit('Repeated FFFF suffixes remain suspicious even if the numeric spread is small.')
        emit('A software timeout/timing check cannot verify wire-level timing or voltage.')
        emit('No calibration or production code was changed. Send the report and a clear '
             'photo of the HX711 board and Pi-side wiring.')
        return 0
    except KeyboardInterrupt:
        emit('\nInterrupted. No calibration or production code was changed.')
        return 130
    except Exception as exc:
        emit(f'ERROR {type(exc).__name__}: {exc}')
        emit('Run from the patched project folder, inside its virtual environment, without sudo.')
        return 2
    finally:
        if project.is_dir() and lines:
            stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')
            report = project / f'hx711_link_report_{stamp}.txt'
            try:
                with report.open('x', encoding='utf-8') as out:
                    out.write('\n'.join(lines) + '\n')
                print(f'REPORT={report}', flush=True)
            except OSError as exc:
                print(f'Report could not be saved: {exc}. Copy terminal output.', file=sys.stderr)


if __name__ == '__main__':
    raise SystemExit(main())
