"""USBTMC char-device client for supplies that enumerate as /dev/usbtmc*
(ITECH/AKIP units often use USBTMC instead of a virtual COM port).

Mimics the small pyserial surface used by main.py:
    .timeout (get/set)  .write()  .readline()  .reset_input_buffer()  .close()

Kernel-driver quirks handled here (learned on IT6726G / AKIP-1144):
- EOM must be enabled with USBTMC_IOCTL_EOM_ENABLE (ioctls want a pointer to
  the value, hence ctypes).
- read() itself initiates the exchange (it sends REQUEST_DEV_DEP_MSG_IN and
  waits) — never select() first: the device stays invisible to poll/select.
- The instrument stalls the bulk endpoints when message tags (bTag) desync,
  e.g. after a read timeout. The only reliable recovery is unbind+bind of the
  usbtmc driver, which resets the tag sequence on both sides.
"""
import ctypes
import fcntl
import glob
import os
import subprocess
import time

# ioctl numbers from include/uapi/linux/usb/tmc.h
_USBTMC_IOC_NR = 91
_IOC_EOM_ENABLE = 11     # _IOW(91, 11, __u8)
_IOC_SET_TIMEOUT = 10    # _IOW(91, 10, __u32)
_IOC_CLEAR = 2           # _IO(91, 2)
_IOC_CLEAR_OUT_HALT = 6  # _IO(91, 6)
_IOC_CLEAR_IN_HALT = 7   # _IO(91, 7)


def _iow(nr: int, size: int) -> int:
    return (1 << 30) | (size << 16) | (_USBTMC_IOC_NR << 8) | nr


def _io(nr: int) -> int:
    return _USBTMC_IOC_NR << 8 | nr


def _rebind_driver() -> bool:
    """unbind+bind usbtmc (resets bTag on both sides). Needs the sudo rule
    for /usr/local/bin/usbtmc-rebind.sh; returns True only on success."""
    try:
        subprocess.run(
            ["sudo", "-n", "/usr/local/bin/usbtmc-rebind.sh"],
            check=True, capture_output=True, timeout=15,
        )
        return os.path.exists("/dev/usbtmc0")
    except Exception:
        return False


class UsbTmcSerial:
    def __init__(self, path: str = "/dev/usbtmc0", timeout: float = 2.0):
        self.path = path
        self.fd = None
        self._timeout = timeout
        self._dead = False
        self._open_device()

    # -- lifecycle -----------------------------------------------------
    def _open_device(self) -> None:
        if self.fd is not None:
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.fd = None
        self.fd = os.open(self.path, os.O_RDWR)
        self._setup()

    def _setup(self) -> None:
        try:
            fcntl.ioctl(self.fd, _iow(_IOC_EOM_ENABLE, 1), ctypes.c_uint8(1))
            fcntl.ioctl(self.fd, _iow(_IOC_SET_TIMEOUT, 4),
                        ctypes.c_uint32(int(self._timeout * 1000)))
        except OSError:
            pass  # very old kernels: plain read/write still works
        self._clear_halts()

    def _clear_halts(self) -> None:
        for nr in (_IOC_CLEAR_OUT_HALT, _IOC_CLEAR_IN_HALT):
            try:
                fcntl.ioctl(self.fd, _io(nr))
            except OSError:
                pass

    def _recover(self) -> bool:
        """Called after an I/O error: aborts, clears halts; if the next probe
        still fails, rebinds the driver and reopens."""
        if self.fd is None:
            return False
        for nr in (_IOC_CLEAR_IN_HALT, _IOC_CLEAR_OUT_HALT):
            try:
                fcntl.ioctl(self.fd, _io(nr))
            except OSError:
                pass
        try:
            os.write(self.fd, b"*IDN?\n")
            os.read(self.fd, 4096)
            return True   # recovered without rebind
        except OSError:
            pass
        _rebind_driver()
        time.sleep(0.5)
        try:
            self._open_device()
            return True
        except OSError:
            self._dead = True
            return False

    # -- pyserial-like surface ------------------------------------------
    @property
    def timeout(self) -> float:
        return self._timeout

    @timeout.setter
    def timeout(self, value: float) -> None:
        self._timeout = value
        if self.fd is not None:
            try:
                fcntl.ioctl(self.fd, _iow(_IOC_SET_TIMEOUT, 4),
                            ctypes.c_uint32(int(value * 1000)))
            except OSError:
                pass

    def reset_input_buffer(self) -> None:
        pass  # nothing to drain between queries; CLEAR would drop a pending response

    def write(self, data: bytes) -> int:
        try:
            return os.write(self.fd, data)
        except OSError:
            if self._recover():
                return os.write(self.fd, data)
            raise OSError(19, "device went away — replug the USB cable and reconnect")

    def readline(self) -> bytes:
        """read() starts the exchange itself; a single call returns the whole
        response or raises on timeout (no select/poll — they never fire)."""
        try:
            return os.read(self.fd, 4096)
        except OSError:
            self._recover()
            return b""
    def close(self) -> None:
        try:
            os.close(self.fd)
        except OSError:
            pass
        finally:
            self.fd = None


def usbtmc_ports() -> list:
    return sorted(glob.glob("/dev/usbtmc[0-9]*"))
