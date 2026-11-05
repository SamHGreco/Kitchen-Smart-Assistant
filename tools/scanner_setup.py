"""Configure/verify/test Atomic QRCode2 Base. Close the GUI before running."""
from __future__ import annotations
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'src/ui')]
from Input_Validation import load_config
from product_id.barcode_reader import AtomicBarcodeReader


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('configure', 'verify', 'scan', 'stop'))
    parser.add_argument('--config', default=str(ROOT / 'src/ui/config.pi.json'))
    parser.add_argument('--apply', action='store_true', help='Required to write scanner configuration')
    args = parser.parse_args()
    settings = load_config(args.config)
    review = settings.get('hardware_review', {})
    required = ('gpio15_conflict_resolved', 'uart_voltage_compatibility_confirmed',
                'power_budget_and_connector_orientation_confirmed')
    missing = [key for key in required if review.get(key) is not True]
    if missing:
        parser.error('Review wiring before serial access: ' + ', '.join(missing))
    if args.command == 'configure' and not args.apply:
        parser.error('Use configure --apply after verifying the A133-B scanner and wiring.')
    serial = settings['serial']
    with AtomicBarcodeReader(serial['port'], int(serial['baud'])) as reader:
        try:
            if args.command == 'configure':
                reader.configure_for_groceries(tell=print)
            else:
                reader.stop_decode()
                if args.command == 'stop':
                    print('STOP acknowledged. Scanner remains powered, but decoding is stopped.')
                    return
                reader.verify_configuration()
                if args.command == 'verify':
                    print('Scanner settings verified; decoder stopped.')
                else:
                    print('Present one UPC/EAN barcode now.')
                    print(reader.scan_once(timeout=10.0) or 'No barcode received.')
        finally:
            reader.stop_decode()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        raise SystemExit('Scanner setup stopped: ' + str(exc))
