"""USBTMC char-device client for supplies that enumerate as /dev/usbtmc*
(ITECH/AKIP units often use USBTMC instead of a virtual COM port).

Mimics the small pyserial surface used by main.py:
    .timeout (get/set)  .write()  .readline()  .reset_input_buffer()  .close()

The Linux usbtmc driver leaves EOM (End Of Message) OFF by default, so a plain
write("...") never terminates the transfer and the instrument silently waits.
We enable it with USBTMC_IOCTL_EOM_ENABLE (see include/uapi/linux/usb/tmc.h).
"""
import fcntl
import os
import select
import time

# ioctl numbers from include/uapi/linux/usb/tmc.h
_USBTMC_IOC_NR = 91
_IOC_EOM_ENABLE = 11    # _IOW(91, 11, __u8)
_IOC_SET_TIMEOUT = 10   # _IOW(91, 10, __u32)
_IOC_CLEAR = 2          # _IO(91, 2)
_IOC_CLEAR_OUT_HALT = 6 # _IO(91, 6)
_IOC_CLEAR_IN_HALT = 7  # _IO(91, 7)


def _iow(nr: int, size: int) -> int:
    return (1 << 30) | (size << 16) | (_USBTMC_IOC_NR << 8) | nr


def _io(nr: int) -> int:
    return _USBTMC_IOC_NR << 8 | nr


class UsbTmcSerial:
    def __init__(self, path: str = "/dev/usbtmc0", timeout: float = 2.0):
        self.fd = os.open(path, os.O_RDWR)
        self._timeout = timeout
        try:
            fcntl.ioctl(self.fd, _iow(_IOC_EOM_ENABLE, 1), 1)
            fcntl.ioctl(self.fd, _iow(_IOC_SET_TIMEOUT, 4), int(timeout * 1000))
        except OSError:
            pass  # very old kernel without these ioctls: plain read/write still works

    @property
    def timeout(self) -> float:
        return self._timeout

    @timeout.setter
    def timeout(self, value: float) -> None:
        self._timeout = value
        try:
            fcntl.ioctl(self.fd, _iow(_IOC_SET_TIMEOUT, 4), int(value * 1000))
        except OSError:
            pass

    def reset_input_buffer(self) -> None:
        pass  # nothing to drain between queries; CLEAR would abort a pending response

    def write(self, data: bytes) -> int:
        return os.write(self.fd, data)

    def readline(self) -> bytes:
        """Read until newline (like pyserial) or timeout."""
        deadline = time.monotonic() + self._timeout
        buf = b""
        while b"\n" not in buf:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            r, _, _ = select.select([self.fd], [], [], remaining)
            if not r:
                break
            chunk = os.read(self.fd, 4096)
            if not chunk:
                break
            buf += chunk
        return buf

    def clear_halts(self) -> None:
        for nr in (_IOC_CLEAR_OUT_HALT, _IOC_CLEAR_IN_HALT):
            try:
                fcntl.ioctl(self.fd, _io(nr))
            except OSError:
                pass

    def close(self) -> None:
        try:
            os.close(self.fd)
        finally:
            self.fd = None
