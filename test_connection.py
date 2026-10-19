"""Read-only connection/PNG/XML validation against a USB phone."""
import argparse
import json
from android_controller import AndroidController


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--serial')
    parser.add_argument('--capture', action='store_true')
    parser.add_argument('--show', action='store_true')
    args = parser.parse_args()
    phone = AndroidController(serial=args.serial)
    try:
        info = phone.connect()
        print(json.dumps(info, ensure_ascii=False, indent=2))
        if args.capture or args.show:
            from PIL import Image
            path = phone.screenshot()
            with Image.open(path) as image:
                image.load()
                print(f'PNG decoded by Python: {image.size}, {path}')
                if args.show:
                    image.show()
            phone.get_ui_hierarchy(phone.log_dir / 'ui.xml')
            print('UI XML parsed successfully')
        return 0
    except Exception as exc:
        print(f'Connection test incomplete: {exc}')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
