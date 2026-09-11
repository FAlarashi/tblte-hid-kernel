# HID integration design

## Target kernel

The running phone reports Linux 3.10.108. The public APQ8084 kernel source family has the same `3.10.108` Makefile version and a `tblte` EUR defconfig. The `lineage-18.1` branch is therefore the current public source baseline, but the exact byte-for-byte provenance of the May 2024 `/e/OS` build must still be verified before a kernel image is considered flashable.

## Why the existing standalone HID driver is not enough

The source already contains the old HID gadget implementation (`drivers/usb/gadget/hid.c` + `f_hid.c`) and its Makefile rule, but the phone's runtime uses Samsung's legacy `android_usb` composite gadget (`sys.usb.configfs=0`). The missing piece is integration of HID as an Android USB function so that keyboard and mouse interfaces can coexist with the normal legacy USB composition.

## Planned implementation

1. Build `f_hid.c` into the Android gadget module rather than enabling the unrelated standalone `g_hid` composite driver.
2. Expose the HID helper entry points through `f_hid.h`.
3. Remove `__init` from HID bind/setup functions because Android invokes them during normal gadget configuration, not only at module initialization.
4. Add standard boot-protocol keyboard and relative mouse report descriptors.
5. Register a legacy Android USB function named `hid` which creates two HID interfaces: keyboard (`hidg0`) and mouse (`hidg1`).
6. Keep HID available but **do not force it into every normal USB composition**. This prevents breaking ordinary MTP/ADB operation. HID is enabled on demand through the legacy `android_usb` function list.
7. Validate HID class protocol requests and endpoint operation before producing a flashable image.

## Expected runtime result

After the modified kernel is booted and the `hid` function is enabled, the target should expose:

- `/dev/hidg0` — 8-byte boot keyboard reports
- `/dev/hidg1` — 4-byte mouse reports

The PC should enumerate the phone as a standard USB HID keyboard and mouse while the phone remains the USB device/peripheral.

## Testing policy

Initial validation will be harmless: enumerate the HID interfaces, send a single benign keyboard character to an authorized test PC, release it, then exercise a small mouse movement/click. No credential capture, persistence, destructive commands, or unauthorized-device testing is part of this project.

## Flash gate

No kernel image will be presented as ready to flash until all of the following are true:

- source provenance is sufficiently matched to the running 3.10.108 build;
- the baseline defconfig/config is reproduced;
- the HID changes compile cleanly;
- the resulting kernel image is structurally checked;
- the boot-image format/offsets for this `tblte` build are verified;
- a recovery path to the current known-good boot image is established.
