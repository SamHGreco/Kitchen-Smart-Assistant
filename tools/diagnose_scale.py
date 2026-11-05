#!/usr/bin/env python3
"""Diagnose the existing Kitchen Smart Assistant HX711 stability check.

Run from the extracted patched project, with the GUI and other scale programs
closed and the scanner physically disconnected. Uses the project's existing
HX711 reader, including its timing checks and first-conversion discard.
Does not change application code, configuration, calibration, or databases.
Writes scale_diagnostic.txt in the project directory.

Example:
    python ~/Downloads/diagnose_scale.py
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from statistics import median
import sys
import time
from typing import Any, Callable, Protocol


class RawReader(Protocol):
    def read_raw(self, samples: int = 9, timeout: float = 3.0) -> list[int]: ...
    def close(self) -> None: ...


def load_settings(project: Path) -> tuple[dict[str, Any], float]:
    config = project / 'src' / 'ui' / 'config.pi.json'
    if not config.is_file():
        raise ValueError('Run this command from Kitchen-Smart-Assistant-fixed, '
                         'or pass --project /path/to/your/project.')
    settings = json.loads(config.read_text(encoding='utf-8'))
    pins = settings['gpio']
    for name in ('scale_data', 'scale_clock'):
        pin = pins[name]
        if type(pin) is not int or not 0 <= pin <= 27:
            raise ValueError(f'Invalid BCM GPIO pin: {name}={pin!r}.')
    if pins['scale_data'] == pins['scale_clock']:
        raise ValueError('Scale data and clock cannot use the same GPIO pin.')
    value = settings.get('scale', {}).get('max_raw_spread', 2000.0)
    if isinstance(value, bool):
        raise ValueError('max_raw_spread must be a positive finite number.')
    limit = float(value)
    if not math.isfinite(limit) or limit <= 0:
        raise ValueError('max_raw_spread must be a positive finite number.')
    return settings, limit


def sample_report(reader: RawReader, limit: float,
                  emit: Callable[[str], None], *, batches: int = 5,
                  wait: Callable[[float], None] = time.sleep) -> int:
    """Report identical nine-sample stability windows, without relaxing limits."""
    passing = 0
    failed_spread = 0
    read_errors = 0
    centers: list[float] = []
    for index in range(1, batches + 1):
        try:
            values = list(reader.read_raw(samples=9, timeout=3.0))
            if len(values) != 9:
                raise ValueError(f'Expected 9 raw samples; got {len(values)}.')
            # Match the production checked_samples validity limits.
            if any(type(v) is not int or not -8388607 < v < 8388607
                   for v in values):
                raise ValueError(f'Invalid or saturated HX711 samples: {values!r}')
            low, high = min(values), max(values)
            spread = high - low
            center = float(median(values))
            centers.append(center)
            passed = spread <= limit
            passing += int(passed)
            failed_spread += int(not passed)
            status = 'PASS' if passed else 'FAIL'
            emit(f'Batch {index}: {status}  spread={spread}  limit={limit:g}  '
                 f'median={center:g}  min={low}  max={high}')
            emit('  raw=' + ', '.join(str(v) for v in values))
        except Exception as exc:
            read_errors += 1
            emit(f'Batch {index}: ERROR {type(exc).__name__}: {exc}')
        if index < batches:
            # Match the default application's pause between acquisitions.
            wait(2.0)
    emit('')
    emit('RESULT: ' + f'{passing}/{batches} batches passed the current raw limit; '
         f'{failed_spread} exceeded it; {read_errors} had read errors.')
    if centers:
        emit(f'Between-batch median range: {max(centers) - min(centers):g} counts.')
    emit('Raw counts are NOT grams. Large/negative empty-platform values alone '
         'are not a failure.')
    emit('Passing this test does not verify accuracy or rule out GUI-related '
         'timing problems. No calibration limits were changed.')
    return 0 if passing == batches else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--project', type=Path, default=Path.cwd(),
                        help='Project directory (default: current directory).')
    args = parser.parse_args(argv)
    project = args.project.expanduser().resolve()
    report = project / 'scale_diagnostic.txt'
    lines = ['Kitchen Smart Assistant - EMPTY PLATFORM raw scale diagnostic',
             'UTC: ' + datetime.now(timezone.utc).isoformat()]

    def emit(text: str) -> None:
        lines.append(text)
        print(text, flush=True)

    reader = None
    exit_code = 2
    try:
        settings, limit = load_settings(project)
        pins = settings['gpio']
        emit(f'Config: {project / "src/ui/config.pi.json"}')
        emit(f'BCM pins: DOUT={pins["scale_data"]}; SCK={pins["scale_clock"]}. '
             f'Raw spread limit: {limit:g} counts.')
        emit('Before continuing: close the GUI and ALL other scale programs; '
             'keep the scanner physically disconnected.')
        emit('Keep the normal weighing platform mounted and empty. '
             'Do not touch the platform or its cables during sampling.')
        answer = input('Type READY to confirm these checks and start: ').strip()
        if answer != 'READY':
            emit('Cancelled. No GPIO pins were opened.')
            return 2
        # Imports are intentionally delayed until after confirmation. No project
        # launcher, sensor monitor, database, or UART connection is opened.
        sys.path.insert(0, str(project / 'src'))
        sys.path.insert(0, str(project / 'src' / 'ui'))
        from app.shared.scanner_scale_gate import ScannerScaleGate
        from scale.coordinated_scale import GuardedRawScale
        from scale.hx711_driver import HX711Driver
        gate = ScannerScaleGate(serial_enabled=False, auto_pause=False,
                                settle_seconds=0.2)
        reader = GuardedRawScale(
            HX711Driver(pins['scale_data'], pins['scale_clock']), gate)
        # Allow settling after GPIO initialization. Per-batch acquisition then
        # discards its first conversion, exactly as the app does.
        time.sleep(1.0)
        exit_code = sample_report(reader, limit, emit)
    except KeyboardInterrupt:
        emit('\nInterrupted. No calibration was saved.')
        exit_code = 130
    except (Exception, EOFError) as exc:
        emit(f'ERROR {type(exc).__name__}: {exc}')
        emit('Run inside the project virtual environment on the Pi, without sudo.')
        exit_code = 2
    finally:
        if reader is not None:
            try:
                reader.close()
            except Exception as exc:
                emit(f'GPIO close error: {exc}')
                exit_code = 2
        # Do not clobber previous diagnostic reports.
        if project.is_dir():
            try:
                if report.exists():
                    stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')
                    report = project / f'scale_diagnostic_{stamp}.txt'
                with report.open('x', encoding='utf-8') as output:
                    output.write('\n'.join(lines) + '\n')
                print(f'Report saved: {report}', flush=True)
            except OSError as exc:
                print(f'Could not save report: {exc}. Copy the terminal output.',
                      file=sys.stderr)
    return exit_code


if __name__ == '__main__':
    raise SystemExit(main())
