#!/usr/bin/env python3
"""Make the legacy f_hid implementation safe for multiple HID instances.

The Android integration binds keyboard and mouse as two HID functions. The
stock 3.10 f_hid.c keeps interface/endpoint descriptors in global mutable
objects, so the second bind overwrites the first function's descriptors.
This transformation gives each f_hid instance its own descriptor storage.
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

anchor = "\tstruct usb_ep\t\t\t*out_ep;\n"
insert = anchor + "\n\t/* Each HID function needs private mutable descriptors.  The original\n\t * driver used globals, which breaks when keyboard and mouse are both\n\t * bound to the same Android configuration. */\n\tstruct usb_interface_descriptor interface_desc;\n\tstruct hid_descriptor desc;\n\tstruct usb_endpoint_descriptor hs_in_ep_desc;\n\tstruct usb_endpoint_descriptor hs_out_ep_desc;\n\tstruct usb_endpoint_descriptor fs_in_ep_desc;\n\tstruct usb_endpoint_descriptor fs_out_ep_desc;\n\tstruct usb_descriptor_header *hs_descriptors[5];\n\tstruct usb_descriptor_header *fs_descriptors[5];\n"
if anchor not in s:
    raise SystemExit("f_hid.c: f_hidg endpoint anchor not found")
s = s.replace(anchor, insert, 1)

bind = s.index("static int hidg_bind(struct usb_configuration *c, struct usb_function *f)")
end = s.index("static void hidg_unbind", bind)
b = s[bind:end]

old = "\t/* allocate instance-specific interface IDs, and patch descriptors */\n"
new = """\t/* Copy the mutable descriptor templates into this HID instance. */
\thidg->interface_desc = hidg_interface_desc;
\thidg->desc = hidg_desc;
\thidg->hs_in_ep_desc = hidg_hs_in_ep_desc;
\thidg->hs_out_ep_desc = hidg_hs_out_ep_desc;
\thidg->fs_in_ep_desc = hidg_fs_in_ep_desc;
\thidg->fs_out_ep_desc = hidg_fs_out_ep_desc;
\thidg->fs_descriptors[0] =
\t\t(struct usb_descriptor_header *)&hidg->interface_desc;
\thidg->fs_descriptors[1] =
\t\t(struct usb_descriptor_header *)&hidg->desc;
\thidg->fs_descriptors[2] =
\t\t(struct usb_descriptor_header *)&hidg->fs_in_ep_desc;
\thidg->fs_descriptors[3] =
\t\t(struct usb_descriptor_header *)&hidg->fs_out_ep_desc;
\thidg->fs_descriptors[4] = NULL;
\thidg->hs_descriptors[0] =
\t\t(struct usb_descriptor_header *)&hidg->interface_desc;
\thidg->hs_descriptors[1] =
\t\t(struct usb_descriptor_header *)&hidg->desc;
\thidg->hs_descriptors[2] =
\t\t(struct usb_descriptor_header *)&hidg->hs_in_ep_desc;
\thidg->hs_descriptors[3] =
\t\t(struct usb_descriptor_header *)&hidg->hs_out_ep_desc;
\thidg->hs_descriptors[4] = NULL;

\t/* allocate instance-specific interface IDs, and patch descriptors */
"""
if old not in b:
    raise SystemExit("hidg_bind: descriptor initialization anchor not found")
b = b.replace(old, new, 1)

repls = {
    "&hidg_fs_in_ep_desc": "&hidg->fs_in_ep_desc",
    "&hidg_fs_out_ep_desc": "&hidg->fs_out_ep_desc",
    "&hidg_hs_in_ep_desc": "&hidg->hs_in_ep_desc",
    "&hidg_hs_out_ep_desc": "&hidg->hs_out_ep_desc",
    "hidg_interface_desc.bInterfaceNumber": "hidg->interface_desc.bInterfaceNumber",
    "hidg_interface_desc.bInterfaceSubClass": "hidg->interface_desc.bInterfaceSubClass",
    "hidg_interface_desc.bInterfaceProtocol": "hidg->interface_desc.bInterfaceProtocol",
    "hidg_fs_in_ep_desc.wMaxPacketSize": "hidg->fs_in_ep_desc.wMaxPacketSize",
    "hidg_hs_in_ep_desc.wMaxPacketSize": "hidg->hs_in_ep_desc.wMaxPacketSize",
    "hidg_fs_out_ep_desc.wMaxPacketSize": "hidg->fs_out_ep_desc.wMaxPacketSize",
    "hidg_hs_out_ep_desc.wMaxPacketSize": "hidg->hs_out_ep_desc.wMaxPacketSize",
    "hidg_hs_in_ep_desc.bEndpointAddress": "hidg->hs_in_ep_desc.bEndpointAddress",
    "hidg_fs_in_ep_desc.bEndpointAddress": "hidg->fs_in_ep_desc.bEndpointAddress",
    "hidg_hs_out_ep_desc.bEndpointAddress": "hidg->hs_out_ep_desc.bEndpointAddress",
    "hidg_fs_out_ep_desc.bEndpointAddress": "hidg->fs_out_ep_desc.bEndpointAddress",
    "hidg_desc.desc[0].bDescriptorType": "hidg->desc.desc[0].bDescriptorType",
    "hidg_desc.desc[0].wDescriptorLength": "hidg->desc.desc[0].wDescriptorLength",
    "usb_assign_descriptors(f, hidg_fs_descriptors,\n\t\thidg_hs_descriptors, NULL)": "usb_assign_descriptors(f, hidg->fs_descriptors,\n\t\thidg->hs_descriptors, NULL)",
}
for old, new in repls.items():
    if old not in b:
        raise SystemExit(f"hidg_bind: expected text not found: {old}")
    b = b.replace(old, new)

s = s[:bind] + b + s[end:]
p.write_text(s)
print("multi-instance HID descriptor fix applied")
