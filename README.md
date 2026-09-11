# tblte HID Kernel

Samsung Galaxy Note Edge SM-N915F (`tblte`) HID-gadget kernel project.

## Objective
Add reliable USB HID gadget support to the existing device-specific Linux 3.10.108 kernel used by the current Android 11 /e/OS build, while preserving the existing USB, DWC3, Qualcomm, and Samsung gadget stack.

## Baseline
- Device: SM-N915F (`tblte`)
- SoC: APQ8084 / Snapdragon 805
- Android: 11 /e/OS R 1.21
- Kernel: Linux 3.10.108
- Build lineage: `eng.ronnz.20240503.143544`
- UDC: `f9200000.dwc3`
- `CONFIG_USB_GADGET=y`
- `CONFIG_CONFIGFS_FS=y`
- `CONFIG_HID=y`
- `CONFIG_HIDRAW=y`
- `CONFIG_UHID=y`
- `CONFIG_USB_HID=y`
- `CONFIG_USB_G_HID` currently disabled

## Engineering plan
1. Identify the exact source revision and defconfig matching the running kernel.
2. Reproduce the current configuration before changing anything.
3. Audit the legacy Samsung `android_usb` gadget path (`sys.usb.configfs=0`).
4. Compare the existing `f_hid.c`/`g_hid` implementation with the Android legacy composite gadget.
5. Implement the smallest compatible HID integration, rather than replacing the kernel with an unrelated historical NetHunter kernel.
6. Build and verify the kernel and configuration.
7. Verify boot-image structure before any flashing operation.
8. Test only on authorized hardware with harmless HID reports.

## Safety
No kernel image should be flashed until source/config/toolchain/boot-image compatibility and a recovery path have been verified. The known-good boot/kernel remains the fallback.

This project is for authorized USB HID testing and development, not credential theft, persistence, or malicious BadUSB payloads.
