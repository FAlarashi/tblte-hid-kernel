#!/usr/bin/env python3
"""Make the legacy 3.10 f_hid implementation safe for two HID instances.

The Android integration creates keyboard and mouse as separate HID functions.
The stock driver keeps mutable descriptors globally, so the second bind can
overwrite the first instance. This transformation gives every f_hidg instance
private descriptor storage and makes control-request descriptor replies use it.
It also implements real HID boot-protocol state instead of stalling the
GET_PROTOCOL/SET_PROTOCOL requests used by hosts during enumeration.
"""
from pathlib import Path
import sys

root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
p = root / "drivers/usb/gadget/f_hid.c"
if not p.is_file():
    raise SystemExit(f"missing expected kernel file: {p}")
s = p.read_text()

if "struct usb_interface_descriptor interface_desc;" in s:
    raise SystemExit("multi-instance HID fix already applied")

# Add per-instance descriptor storage and protocol state to struct f_hidg.
anchor = "\tstruct usb_ep\t\t\t*out_ep;\n"
insert = anchor + """

	/* Private mutable descriptors: keyboard and mouse must not share them. */
	struct usb_interface_descriptor interface_desc;
	struct hid_descriptor desc;
	struct usb_endpoint_descriptor hs_in_ep_desc;
	struct usb_endpoint_descriptor hs_out_ep_desc;
	struct usb_endpoint_descriptor fs_in_ep_desc;
	struct usb_endpoint_descriptor fs_out_ep_desc;
	struct usb_descriptor_header *hs_descriptors[5];
	struct usb_descriptor_header *fs_descriptors[5];
	unsigned char protocol;
"""
if anchor not in s:
    raise SystemExit("f_hid.c: f_hidg endpoint anchor not found")
s = s.replace(anchor, insert, 1)

# Make HID control-request descriptor responses instance-local.
old = "hidg_desc.bLength"
if old not in s:
    raise SystemExit("f_hid.c: HID descriptor length reference not found")
s = s.replace(old, "hidg->desc.bLength", 1)
old = "memcpy(req->buf, &hidg_desc, length);"
if old not in s:
    raise SystemExit("f_hid.c: HID descriptor copy reference not found")
s = s.replace(old, "memcpy(req->buf, &hidg->desc, length);", 1)

# Implement HID boot protocol requests. The state is per HID instance.
old = '''\tcase ((USB_DIR_IN | USB_TYPE_CLASS | USB_RECIP_INTERFACE) << 8
\t\t  | HID_REQ_GET_PROTOCOL):
\t\tVDBG(cdev, "get_protocol\\n");
\t\tgoto stall;
\t\tbreak;'''
new = '''\tcase ((USB_DIR_IN | USB_TYPE_CLASS | USB_RECIP_INTERFACE) << 8
\t\t  | HID_REQ_GET_PROTOCOL):
\t\tVDBG(cdev, "get_protocol\\n");
\t\tif (hidg->bInterfaceSubClass != USB_INTERFACE_SUBCLASS_BOOT)
\t\t\tgoto stall;
\t\tlength = min_t(unsigned, length, 1);
\t\t((u8 *)req->buf)[0] = hidg->protocol;
\t\tgoto respond;
\t\tbreak;'''
if old not in s:
    raise SystemExit("f_hid.c: GET_PROTOCOL block not found")
s = s.replace(old, new, 1)

old = '''\tcase ((USB_DIR_OUT | USB_TYPE_CLASS | USB_RECIP_INTERFACE) << 8
\t\t  | HID_REQ_SET_PROTOCOL):
\t\tVDBG(cdev, "set_protocol\\n");
\t\tgoto stall;
\t\tbreak;'''
new = '''\tcase ((USB_DIR_OUT | USB_TYPE_CLASS | USB_RECIP_INTERFACE) << 8
\t\t  | HID_REQ_SET_PROTOCOL):
\t\tVDBG(cdev, "set_protocol\\n");
\t\tif (hidg->bInterfaceSubClass != USB_INTERFACE_SUBCLASS_BOOT)
\t\t\tgoto stall;
\t\tif (value > 1)
\t\t\tgoto stall;
\t\thidg->protocol = value;
\t\tlength = 0;
\t\tgoto respond;
\t\tbreak;'''
if old not in s:
    raise SystemExit("f_hid.c: SET_PROTOCOL block not found")
s = s.replace(old, new, 1)

bind = s.index("static int hidg_bind(struct usb_configuration *c, struct usb_function *f)")
end = s.index("static void hidg_unbind", bind)
b = s[bind:end]

anchor = "\t/* allocate instance-specific interface IDs, and patch descriptors */\n"
init = """\t/* Copy the descriptor templates into this instance before patching. */
\thidg->interface_desc = hidg_interface_desc;
\thidg->desc = hidg_desc;
\thidg->hs_in_ep_desc = hidg_hs_in_ep_desc;
\thidg->hs_out_ep_desc = hidg_hs_out_ep_desc;
\thidg->fs_in_ep_desc = hidg_fs_in_ep_desc;
\thidg->fs_out_ep_desc = hidg_fs_out_ep_desc;
\n\thidg->fs_descriptors[0] =
\t\t(struct usb_descriptor_header *)&hidg->interface_desc;
\thidg->fs_descriptors[1] =
\t\t(struct usb_descriptor_header *)&hidg->desc;
\thidg->fs_descriptors[2] =
\t\t(struct usb_descriptor_header *)&hidg->fs_in_ep_desc;
\thidg->fs_descriptors[3] =
\t\t(struct usb_descriptor_header *)&hidg->fs_out_ep_desc;
\thidg->fs_descriptors[4] = NULL;
\n\thidg->hs_descriptors[0] =
\t\t(struct usb_descriptor_header *)&hidg->interface_desc;
\thidg->hs_descriptors[1] =
\t\t(struct usb_descriptor_header *)&hidg->desc;
\thidg->hs_descriptors[2] =
\t\t(struct usb_descriptor_header *)&hidg->hs_in_ep_desc;
\thidg->hs_descriptors[3] =
\t\t(struct usb_descriptor_header *)&hidg->hs_out_ep_desc;
\thidg->hs_descriptors[4] = NULL;
\n\t/* Start in report protocol; hosts may switch boot interfaces to boot. */
\thidg->protocol = 1;
\n\t/* allocate instance-specific interface IDs, and patch descriptors */
"""
if anchor not in b:
    raise SystemExit("hidg_bind: descriptor initialization anchor not found")
b = b.replace(anchor, init, 1)

# Replace descriptor identifiers only inside hidg_bind. Bare identifier
# replacement is intentional: autoconfig also needs the private endpoint
# descriptor, not just its mutable fields.
repls = {
    "hidg_interface_desc": "hidg->interface_desc",
    "hidg_desc": "hidg->desc",
    "hidg_hs_in_ep_desc": "hidg->hs_in_ep_desc",
    "hidg_hs_out_ep_desc": "hidg->hs_out_ep_desc",
    "hidg_fs_in_ep_desc": "hidg->fs_in_ep_desc",
    "hidg_fs_out_ep_desc": "hidg->fs_out_ep_desc",
    "hidg_hs_descriptors": "hidg->hs_descriptors",
    "hidg_fs_descriptors": "hidg->fs_descriptors",
}
for old, new in repls.items():
    b = b.replace(old, new)

# No global mutable HID descriptor may remain in the bind function.
for name in repls:
    if name in b:
        raise SystemExit(f"hidg_bind: global descriptor reference remains: {name}")

required = [
    "usb_ep_autoconfig(c->cdev->gadget, &hidg->fs_in_ep_desc)",
    "usb_ep_autoconfig(c->cdev->gadget, &hidg->fs_out_ep_desc)",
    "usb_assign_descriptors(f, hidg->fs_descriptors,",
    "hidg->interface_desc.bInterfaceNumber = status;",
    "hidg->desc.desc[0].wDescriptorLength =",
]
for text in required:
    if text not in b:
        raise SystemExit(f"hidg_bind: required transformed text missing: {text}")

s = s[:bind] + b + s[end:]
p.write_text(s)
print("multi-instance HID descriptor fix applied")
