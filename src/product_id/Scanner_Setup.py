#Checks scanner
import argparse
from pathlib import Path
from Barcode_Reader import AtomicBarcodeReader
from Input_Validation import load_config

def main():
    parser = argparse.ArgumentParser(description='Checks the Atomic reader')
    parser.add_argument('action', choices=['probe', 'verify', 'configure', 'scan'])
    parser.add_argument('--config', default=str(Path(__file__).parent / 'config.pi.json'))
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    config = load_config(args.config)
    review = config.get('hardware_review', {})
    keys = (
        'gpio15_conflict_resolved',
        'uart_voltage_compatibility_confirmed',
        'power_budget_and_connector_orientation_confirmed'
    )
    if not all((review.get(key) is True for key in keys)):
        raise ValueError('Complete the hardware-review checks before serial access.')
    if args.action == 'configure' and (not args.apply):
        raise ValueError('Configuration is persistent. Add --apply only after reviewing the settings.')
    serial = config['serial']
    with AtomicBarcodeReader(serial['port'], serial.get('baud', 115200)) as reader:
        if args.action == 'probe':
            print('Trigger mode reply:', reader.read_configuration(97, 65).hex())
        elif args.action == 'configure':
            reader.configure_for_groceries(tell=print)
        else:
            reader.stop_decode()
            reader.verify_configuration()
            if args.action == 'scan':
                print('Present one barcode within 10 seconds.')
                print('Read:', repr(reader.scan_once(timeout=10)))
            else:
                print('Scanner settings verified.')
if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        raise SystemExit('Scanner: ' + str(error))
