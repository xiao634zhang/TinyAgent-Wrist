"""Explicit UI operations. Use coordinates verified from a current screenshot."""
import argparse
from android_controller import AndroidController


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--serial')
    p.add_argument('--launch', help='Package, e.g. io.heckel.ntfy')
    p.add_argument('--tap', type=int, nargs=2, metavar=('X', 'Y'))
    p.add_argument('--swipe', type=int, nargs=5, metavar=('X1', 'Y1', 'X2', 'Y2', 'MS'))
    p.add_argument('--text')
    p.add_argument('--back', action='store_true')
    p.add_argument('--home', action='store_true')
    p.add_argument('--execute', action='store_true', help='Perform the requested actions')
    a = p.parse_args()
    if not a.execute:
        p.error('Review the current screen and add --execute for intentional UI operations.')
    phone = AndroidController(serial=a.serial)
    phone.connect()
    if a.launch:
        print(phone.launch_app(a.launch))
    if a.tap:
        phone.tap(*a.tap)
    if a.swipe:
        phone.swipe(*a.swipe)
    if a.text is not None:
        phone.input_text(a.text)
    if a.back:
        phone.press_back()
    if a.home:
        phone.press_home()
    phone.get_ui_hierarchy(phone.log_dir / 'ui-after.xml')
    print(phone.screenshot())


if __name__ == '__main__':
    main()
