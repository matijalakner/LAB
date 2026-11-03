THORLABS_VENDOR_ID = 0x1313


class ThorlabsUSBDriver:
    """Temporarily detach the Linux kernel driver from a Thorlabs USB device.

    pyusb is imported lazily, so the package imports fine without it; it is
    only needed when this context manager is actually entered.
    """

    def __init__(self, product_id=None):
        self.product_id = product_id
        self.device = None
        self.detached = False
        self._util = None

    def __enter__(self):
        try:
            import usb.core
            import usb.util
        except ImportError as e:
            raise RuntimeError(
                "pyusb is required to talk to Thorlabs devices: pip install pyusb"
            ) from e
        self._util = usb.util

        kwargs = {"idVendor": THORLABS_VENDOR_ID}
        if self.product_id is not None:
            kwargs["idProduct"] = self.product_id
        self.device = usb.core.find(**kwargs)

        if self.device is None:
            if self.product_id is not None:
                raise RuntimeError(
                    f"Thorlabs USB device (Vendor ID: {hex(THORLABS_VENDOR_ID)}, "
                    f"Product ID: {hex(self.product_id)}) not found")
            raise RuntimeError(
                f"No Thorlabs USB devices found (Vendor ID: {hex(THORLABS_VENDOR_ID)})")

        try:
            if self.device.is_kernel_driver_active(0):
                self.device.detach_kernel_driver(0)
                self.detached = True
        except Exception:
            # Ownership is uncertain: release our handle and do not proceed.
            self._util.dispose_resources(self.device)
            self.device = None
            raise
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.device is not None:
            try:
                if self.detached:
                    self.device.attach_kernel_driver(0)
            finally:
                self.detached = False
                self._util.dispose_resources(self.device)
                self.device = None
        return False
