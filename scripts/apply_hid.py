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
new = '''static int hid_function_init(struct android_usb_function *f,
\t\t\t\tstruct usb_composite_dev *cdev)
{
\treturn ghid_setup(cdev->gadget, 2);
}

static void hid_function_cleanup(struct android_usb_function *f)
{
\tghid_cleanup();
}

static int hid_function_bind_config(struct android_usb_function *f,
\t\t\t\t\tstruct usb_configuration *c)
{
\tint ret;

\tret = hidg_bind_config(c, &ghid_device_android_keyboard, 0);
\tif (ret) {
\t\tpr_err("%s: keyboard bind failed: %d\\n", __func__, ret);
\t\treturn ret;
\t}

\tret = hidg_bind_config(c, &ghid_device_android_mouse, 1);
\tif (ret) {
\t\tpr_err("%s: mouse bind failed: %d\\n", __func__, ret);
\t\treturn ret;
\t}

\treturn 0;
}

static struct android_usb_function hid_function = {
\t.name\t\t= "hid",
\t.init\t\t= hid_function_init,
\t.cleanup\t= hid_function_cleanup,
\t.bind_config\t= hid_function_bind_config,
};

''' + old
if old not in a:
    raise SystemExit("android.c: supported_functions anchor not found")
a = a.replace(old, new, 1)

old = '\t&uasp_function,\n\tNULL\n'
new = '\t&uasp_function,\n\t&hid_function,\n\tNULL\n'
if old not in a:
    raise SystemExit("android.c: supported_functions tail not found")
a = a.replace(old, new, 1)

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

# f_hid.c is compiled as a standalone object by g_android. The original
# source was text-included by hid.c, which supplied composite definitions
# indirectly. Make the standalone compilation self-contained.
old = '#include <linux/usb/g_hid.h>\n'
new = '#include <linux/usb/g_hid.h>\n#include <linux/usb/composite.h>\n'
if old not in f:
    raise SystemExit("f_hid.c: g_hid include anchor not found")
f = f.replace(old, new, 1)

# This old f_hid.c used free_ep_req() from a newer shared gadget helper that
# does not exist in this 3.10.108 tree. Keep the old allocation ownership
# semantics local to HID instead of importing an incompatible helper API.
helper_anchor = 'static int major, minors;\nstatic struct class *hidg_class;\n'
helper = helper_anchor + '''

static void hidg_free_ep_req(struct usb_ep *ep, struct usb_request *req)
{
\tif (!req)
\t\treturn;
\tkfree(req->buf);
\treq->buf = NULL;
\tusb_ep_free_request(ep, req);
}
'''
if helper_anchor not in f:
    raise SystemExit("f_hid.c: helper insertion anchor not found")
f = f.replace(helper_anchor, helper, 1)
if "free_ep_req(" not in f:
    raise SystemExit("f_hid.c: expected legacy free_ep_req calls not found")
f = f.replace("free_ep_req(", "hidg_free_ep_req(")

# The multi-instance pass gives each HID instance its own descriptor arrays.
# The original global arrays would therefore be dead objects and -Werror
# turns them into a hard build failure on this kernel.
for block in (
'''static struct usb_descriptor_header *hidg_hs_descriptors[] = {
\t(struct usb_descriptor_header *)&hidg_interface_desc,
\t(struct usb_descriptor_header *)&hidg_desc,
\t(struct usb_descriptor_header *)&hidg_hs_in_ep_desc,
\t(struct usb_descriptor_header *)&hidg_hs_out_ep_desc,
\tNULL,
};

''',
'''static struct usb_descriptor_header *hidg_fs_descriptors[] = {
\t(struct usb_descriptor_header *)&hidg_interface_desc,
\t(struct usb_descriptor_header *)&hidg_desc,
\t(struct usb_descriptor_header *)&hidg_fs_in_ep_desc,
\t(struct usb_descriptor_header *)&hidg_fs_out_ep_desc,
\tNULL,
};

'''):
    if block not in f:
        raise SystemExit("f_hid.c: global descriptor array block not found")
    f = f.replace(block, "", 1)

old = '''\tcase ((USB_DIR_IN | USB_TYPE_CLASS | USB_RECIP_INTERFACE) << 8
\t\t  | HID_REQ_GET_PROTOCOL):
\t\tVDBG(cdev, "get_protocol\\n");
\t\tgoto stall;
\t\tbreak;'''
new = '''\tcase ((USB_DIR_IN | USB_TYPE_CLASS | USB_RECIP_INTERFACE) << 8
\t\t  | HID_REQ_GET_PROTOCOL):
\t\tVDBG(cdev, "get_protocol\\n");
\t\tlength = min_t(unsigned, length, 1);
\t\tif (hidg->bInterfaceSubClass == USB_INTERFACE_SUBCLASS_BOOT)
\t\t\t((u8 *) req->buf)[0] = hidg->protocol;
\t\telse
\t\t\t((u8 *) req->buf)[0] = 1;
\t\tgoto respond;
\t\tbreak;'''
if old not in f:
    raise SystemExit("f_hid.c: GET_PROTOCOL block not found")
f = f.replace(old, new, 1)

old = '''\tcase ((USB_DIR_OUT | USB_TYPE_CLASS | USB_RECIP_INTERFACE) << 8
\t\t  | HID_REQ_SET_PROTOCOL):
\t\tVDBG(cdev, "set_protocol\\n");
\t\tgoto stall;
\t\tbreak;'''
new = '''\tcase ((USB_DIR_OUT | USB_TYPE_CLASS | USB_RECIP_INTERFACE) << 8
\t\t  | HID_REQ_SET_PROTOCOL):
\t\tVDBG(cdev, "set_protocol\\n");
\t\tif (hidg->bInterfaceSubClass != USB_INTERFACE_SUBCLASS_BOOT || value > 1)
\t\t\tgoto stall;
\t\thidg->protocol = value;
\t\tlength = 0;
\t\tgoto respond;
\t\tbreak;'''
if old not in f:
    raise SystemExit("f_hid.c: SET_PROTOCOL block not found")
f = f.replace(old, new, 1)

old = 'g_android-y\t\t\t:= android.o\n'
new = 'g_android-y\t\t\t:= android.o f_hid.o\n'
if old not in m:
    raise SystemExit("gadget Makefile: g_android rule not found")
m = m.replace(old, new, 1)

(gadget / "f_hid.h").write_text('''#ifndef _GADGET_F_HID_H
#define _GADGET_F_HID_H

#include <linux/hid.h>
#include <linux/usb/composite.h>
#include <linux/usb/gadget.h>
#include <linux/usb/g_hid.h>

int hidg_bind_config(struct usb_configuration *c,
\t\tstruct hidg_func_descriptor *fdesc, int index);
int ghid_setup(struct usb_gadget *g, int count);
void ghid_cleanup(void);

#endif
''')

(gadget / "f_hid_android_keyboard.c").write_text('''#include <linux/usb/g_hid.h>

static struct hidg_func_descriptor ghid_device_android_keyboard = {
\t.subclass = 1,
\t.protocol = 1,
\t.report_length = 8,
\t.report_desc_length = 63,
\t.report_desc = {
\t\t0x05, 0x01, 0x09, 0x06, 0xa1, 0x01,
\t\t0x05, 0x07, 0x19, 0xe0, 0x29, 0xe7,
\t\t0x15, 0x00, 0x25, 0x01, 0x75, 0x01,
\t\t0x95, 0x08, 0x81, 0x02, 0x95, 0x01,
\t\t0x75, 0x08, 0x81, 0x03, 0x95, 0x05,
\t\t0x75, 0x01, 0x05, 0x08, 0x19, 0x01,
\t\t0x29, 0x05, 0x91, 0x02, 0x95, 0x01,
\t\t0x75, 0x03, 0x91, 0x03, 0x95, 0x06,
\t\t0x75, 0x08, 0x15, 0x00, 0x25, 0x65,
\t\t0x05, 0x07, 0x19, 0x00, 0x29, 0x65,
\t\t0x81, 0x00, 0xc0
\t}
};
''')

(gadget / "f_hid_android_mouse.c").write_text('''#include <linux/usb/g_hid.h>

static struct hidg_func_descriptor ghid_device_android_mouse = {
\t.subclass = 1,
\t.protocol = 2,
\t.report_length = 3,
\t.report_desc_length = 50,
\t.report_desc = {
\t\t0x05, 0x01, 0x09, 0x02, 0xa1, 0x01,
\t\t0x09, 0x01, 0xa1, 0x00, 0x05, 0x09,
\t\t0x19, 0x01, 0x29, 0x03, 0x15, 0x00,
\t\t0x25, 0x01, 0x95, 0x03, 0x75, 0x01,
\t\t0x81, 0x02, 0x95, 0x01, 0x75, 0x05,
\t\t0x81, 0x01, 0x05, 0x01, 0x09, 0x30,
\t\t0x09, 0x31, 0x15, 0x81, 0x25, 0x7f,
\t\t0x75, 0x08, 0x95, 0x02, 0x81, 0x06,
\t\t0xc0, 0xc0
\t}
};
''')

android.write_text(a)
f_hid.write_text(f)
makefile.write_text(m)
print("HID integration applied")
