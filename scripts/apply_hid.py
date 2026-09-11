#!/usr/bin/env python3
"""Apply the tblte legacy android_usb HID integration to a 3.10.108 tree.

The script intentionally refuses to patch an unexpected source layout. It is
idempotence-aware: a second run stops instead of silently stacking changes.
"""
from pathlib import Path
import sys

root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
gadget = root / "drivers/usb/gadget"
android = gadget / "android.c"
f_hid = gadget / "f_hid.c"
makefile = gadget / "Makefile"

for p in (root / "Makefile", android, f_hid, makefile):
    if not p.is_file():
        raise SystemExit(f"missing expected kernel file: {p}")

mk = (root / "Makefile").read_text()
if not all(x in mk for x in ("VERSION = 3", "PATCHLEVEL = 10", "SUBLEVEL = 108")):
    raise SystemExit("refusing to patch: expected Linux 3.10.108 source")

a = android.read_text()
f = f_hid.read_text()
m = makefile.read_text()

if '"hid"' in a and "hid_function_bind_config" in a:
    raise SystemExit("HID integration already appears to be applied")

old = '#include "u_ether.c"\n'
new = old + '#include "f_hid.h"\n#include "f_hid_android_keyboard.c"\n#include "f_hid_android_mouse.c"\n'
if old not in a:
    raise SystemExit("android.c: USB include anchor not found")
a = a.replace(old, new, 1)

old = 'static struct android_usb_function *supported_functions[] = {\n'
new = '''static int hid_function_init(struct android_usb_function *f,\n\t\t\t\tstruct usb_composite_dev *cdev)\n{\n\treturn ghid_setup(cdev->gadget, 2);\n}\n\nstatic void hid_function_cleanup(struct android_usb_function *f)\n{\n\tghid_cleanup();\n}\n\nstatic int hid_function_bind_config(struct android_usb_function *f,\n\t\t\t\t\tstruct usb_configuration *c)\n{\n\tint ret;\n\n\tret = hidg_bind_config(c, &ghid_device_android_keyboard, 0);\n\tif (ret) {\n\t\tpr_err("%s: keyboard bind failed: %d\\n", __func__, ret);\n\t\treturn ret;\n\t}\n\n\tret = hidg_bind_config(c, &ghid_device_android_mouse, 1);\n\tif (ret) {\n\t\tpr_err("%s: mouse bind failed: %d\\n", __func__, ret);\n\t\treturn ret;\n\t}\n\n\treturn 0;\n}\n\nstatic struct android_usb_function hid_function = {\n\t.name\t\t= "hid",\n\t.init\t\t= hid_function_init,\n\t.cleanup\t= hid_function_cleanup,\n\t.bind_config\t= hid_function_bind_config,\n};\n\n''' + old
if old not in a:
    raise SystemExit("android.c: supported_functions anchor not found")
a = a.replace(old, new, 1)

old = '\t&uasp_function,\n\tNULL\n'
new = '\t&uasp_function,\n\t&hid_function,\n\tNULL\n'
if old not in a:
    raise SystemExit("android.c: supported_functions tail not found")
a = a.replace(old, new, 1)

# The Android gadget calls these routines during normal gadget enable/disable,
# so they cannot be restricted to the module-init section.
for old, new in (
    ('static int __init hidg_bind(struct usb_configuration *c, struct usb_function *f)',
     'static int hidg_bind(struct usb_configuration *c, struct usb_function *f)'),
    ('int __init hidg_bind_config(struct usb_configuration *c,',
     'int hidg_bind_config(struct usb_configuration *c,'),
    ('int __init ghid_setup(struct usb_gadget *g, int count)',
     'int ghid_setup(struct usb_gadget *g, int count)'),
):
    if old not in f:
        raise SystemExit(f"f_hid.c: expected signature not found: {old}")
    f = f.replace(old, new, 1)

# Implement the HID boot-protocol requests expected by many hosts.
old = '''\tcase ((USB_DIR_IN | USB_TYPE_CLASS | USB_RECIP_INTERFACE) << 8\n\t\t  | HID_REQ_GET_PROTOCOL):\n\t\tVDBG(cdev, "get_protocol\\n");\n\t\tgoto stall;\n\t\tbreak;'''
new = '''\tcase ((USB_DIR_IN | USB_TYPE_CLASS | USB_RECIP_INTERFACE) << 8\n\t\t  | HID_REQ_GET_PROTOCOL):\n\t\tVDBG(cdev, "get_protocol\\n");\n\t\tlength = min_t(unsigned, length, 1);\n\t\tif (hidg->bInterfaceSubClass == USB_INTERFACE_SUBCLASS_BOOT)\n\t\t\t((u8 *) req->buf)[0] = 0;\n\t\telse\n\t\t\t((u8 *) req->buf)[0] = 1;\n\t\tgoto respond;\n\t\tbreak;'''
if old not in f:
    raise SystemExit("f_hid.c: GET_PROTOCOL block not found")
f = f.replace(old, new, 1)

old = '''\tcase ((USB_DIR_OUT | USB_TYPE_CLASS | USB_RECIP_INTERFACE) << 8\n\t\t  | HID_REQ_SET_PROTOCOL):\n\t\tVDBG(cdev, "set_protocol\\n");\n\t\tgoto stall;\n\t\tbreak;'''
new = '''\tcase ((USB_DIR_OUT | USB_TYPE_CLASS | USB_RECIP_INTERFACE) << 8\n\t\t  | HID_REQ_SET_PROTOCOL):\n\t\tVDBG(cdev, "set_protocol\\n");\n\t\tlength = 0;\n\t\tif (hidg->bInterfaceSubClass == USB_INTERFACE_SUBCLASS_BOOT) {\n\t\t\tif (value == 0)\n\t\t\t\tgoto respond;\n\t\t} else {\n\t\t\tif (value == 1)\n\t\t\t\tgoto respond;\n\t\t}\n\t\tgoto stall;\n\t\tbreak;'''
if old not in f:
    raise SystemExit("f_hid.c: SET_PROTOCOL block not found")
f = f.replace(old, new, 1)

old = 'g_android-y\t\t\t:= android.o\n'
new = 'g_android-y\t\t\t:= android.o f_hid.o\n'
if old not in m:
    raise SystemExit("gadget Makefile: g_android rule not found")
m = m.replace(old, new, 1)

(gadget / "f_hid.h").write_text('''#ifndef _GADGET_F_HID_H\n#define _GADGET_F_HID_H\n\n#include <linux/hid.h>\n#include <linux/usb/composite.h>\n#include <linux/usb/gadget.h>\n#include <linux/usb/g_hid.h>\n\nint hidg_bind_config(struct usb_configuration *c,\n\t\tstruct hidg_func_descriptor *fdesc, int index);\nint ghid_setup(struct usb_gadget *g, int count);\nvoid ghid_cleanup(void);\n\n#endif\n''')

(gadget / "f_hid_android_keyboard.c").write_text('''#include <linux/usb/g_hid.h>\n\nstatic struct hidg_func_descriptor ghid_device_android_keyboard = {\n\t.subclass = 1,\n\t.protocol = 1,\n\t.report_length = 8,\n\t.report_desc_length = 63,\n\t.report_desc = {\n\t\t0x05, 0x01, 0x09, 0x06, 0xa1, 0x01,\n\t\t0x05, 0x07, 0x19, 0xe0, 0x29, 0xe7,\n\t\t0x15, 0x00, 0x25, 0x01, 0x75, 0x01,\n\t\t0x95, 0x08, 0x81, 0x02, 0x95, 0x01,\n\t\t0x75, 0x08, 0x81, 0x03, 0x95, 0x05,\n\t\t0x75, 0x01, 0x05, 0x08, 0x19, 0x01,\n\t\t0x29, 0x05, 0x91, 0x02, 0x95, 0x01,\n\t\t0x75, 0x03, 0x91, 0x03, 0x95, 0x06,\n\t\t0x75, 0x08, 0x15, 0x00, 0x25, 0x65,\n\t\t0x05, 0x07, 0x19, 0x00, 0x29, 0x65,\n\t\t0x81, 0x00, 0xc0\n\t}\n};\n''')

(gadget / "f_hid_android_mouse.c").write_text('''#include <linux/usb/g_hid.h>\n\nstatic struct hidg_func_descriptor ghid_device_android_mouse = {\n\t.subclass = 1,\n\t.protocol = 2,\n\t.report_length = 4,\n\t.report_desc_length = 52,\n\t.report_desc = {\n\t\t0x05, 0x01, 0x09, 0x02, 0xa1, 0x01,\n\t\t0x09, 0x01, 0xa1, 0x00, 0x05, 0x09,\n\t\t0x19, 0x01, 0x29, 0x05, 0x15, 0x00,\n\t\t0x25, 0x01, 0x95, 0x05, 0x75, 0x01,\n\t\t0x81, 0x02, 0x95, 0x01, 0x75, 0x03,\n\t\t0x81, 0x01, 0x05, 0x01, 0x09, 0x30,\n\t\t0x09, 0x31, 0x09, 0x38, 0x15, 0x81,\n\t\t0x25, 0x7f, 0x75, 0x08, 0x95, 0x03,\n\t\t0x81, 0x06, 0xc0, 0xc0\n\t}\n};\n''')

android.write_text(a)
f_hid.write_text(f)
makefile.write_text(m)
print("HID integration applied")
