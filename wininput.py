"""Native SendInput ABI. Structure alignment follows the calling Python process."""
import ctypes
import logging

WORD = ctypes.c_uint16
DWORD = ctypes.c_uint32
LONG = ctypes.c_int32
ULONG_PTR = ctypes.c_size_t
INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", LONG), ("dy", LONG), ("mouseData", DWORD),
                ("dwFlags", DWORD), ("time", DWORD), ("dwExtraInfo", ULONG_PTR)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", WORD), ("wScan", WORD), ("dwFlags", DWORD),
                ("time", DWORD), ("dwExtraInfo", ULONG_PTR)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", DWORD), ("wParamL", WORD), ("wParamH", WORD)]


class INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("payload",)
    _fields_ = [("type", DWORD), ("payload", INPUTUNION)]


def validate_layout():
    width = ctypes.sizeof(ctypes.c_void_p)
    expected = {4: (28, 16, 24, 4), 8: (40, 24, 32, 8)}[width]
    actual = (ctypes.sizeof(INPUT), ctypes.sizeof(KEYBDINPUT),
              ctypes.sizeof(MOUSEINPUT), INPUT.payload.offset)
    if actual != expected:
        raise RuntimeError(f"SendInput ABI mismatch: {actual}, expected {expected}")
    return actual


def _user32():
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.SendInput.argtypes = [ctypes.c_uint, ctypes.POINTER(INPUT), ctypes.c_int]
    user32.SendInput.restype = ctypes.c_uint
    user32.MapVirtualKeyW.argtypes = [ctypes.c_uint, ctypes.c_uint]
    user32.MapVirtualKeyW.restype = ctypes.c_uint
    return user32


def send_inputs(events):
    validate_layout()
    if not events:
        return
    inputs = (INPUT * len(events))(*events)
    ctypes.set_last_error(0)
    sent = _user32().SendInput(len(inputs), inputs, ctypes.sizeof(INPUT))
    if sent != len(inputs):
        error = ctypes.get_last_error()
        raise OSError(error, f"SendInput inserted {sent}/{len(inputs)} events; last_error={error}")


def keyboard_event(*, scan=0, vk=0, flags=0):
    return INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(vk, scan, flags, 0, 0))


def send_scancode(scancode, down):
    if not 0 < scancode <= 0xFFFF:
        raise ValueError("Invalid or unmapped scan code")
    flags = KEYEVENTF_SCANCODE | (0 if down else KEYEVENTF_KEYUP)
    prefix = scancode >> 8
    if prefix == 0xE0:
        flags |= KEYEVENTF_EXTENDEDKEY
    elif prefix:
        raise ValueError(f"Unsupported scan-code prefix: 0x{prefix:X}")
    send_inputs([keyboard_event(scan=scancode & 0xFF, flags=flags)])


def vk_to_scancode(vk):
    # MAPVK_VK_TO_VSC_EX preserves E0 for arrows, Insert, Delete, etc.
    return _user32().MapVirtualKeyW(vk, 4)


def send_mouse_button(down):
    flags = MOUSEEVENTF_LEFTDOWN if down else MOUSEEVENTF_LEFTUP
    send_inputs([INPUT(type=INPUT_MOUSE, mi=MOUSEINPUT(0, 0, 0, flags, 0, 0))])


def sendinput_selftest():
    """Explicit debug action only: send an F24 press/release, without changing focus."""
    log = logging.getLogger("pokebot.inputbus")
    try:
        send_inputs([keyboard_event(vk=0x87), keyboard_event(vk=0x87, flags=KEYEVENTF_KEYUP)])
    except OSError:
        # A partial batch may have inserted only the down event: attempt release.
        try:
            send_inputs([keyboard_event(vk=0x87, flags=KEYEVENTF_KEYUP)])
        except OSError:
            log.exception("SendInput self-test: F24 release also failed")
        log.exception("SendInput self-test failed")
        return False
    log.info("SendInput self-test OK: F24 down/up accepted by Windows")
    return True


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="SendInput debug entry point")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    if args.selftest:
        raise SystemExit(0 if sendinput_selftest() else 1)
    parser.print_help()
