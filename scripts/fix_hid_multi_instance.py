#!/usr/bin/env python3
"""Make the legacy 3.10 f_hid implementation safe for two HID instances.

The Android integration creates keyboard and mouse as separate HID functions.
The stock driver keeps mutable descriptors globally, so the second bind can
overwrite the first instance. This transformation gives every f_hidg instance
private descriptor storage and makes control-request descriptor replies use it.
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

# Add per-instance descriptor storage to struct f_hidg.
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
"""
if anchor not in s:
    raise SystemExit("f_hid.c: f_hidg endpoint anchor not found")
s = s.replace(anchor, insert, 1)

# Make HID control-request descriptor responses instance-local.
s = s.replace("\t\t\t\t\t   hidg_desc.bLength);", "\t\t\t\t\t   hidg->desc.bLength);", 1)
s = s.replace("\t\t\tmemcpy(req->buf, &hidg_desc, length);", "\t\t\tmemcpy(req->buf, &hidg->desc, length);", 1)

bind = s.index("static int hidg_bind(struct usb_configuration *c, struct usb_function *f)")
end = s.index("static void hidg_unbind", bind)
b = s[bind:end]

anchor = "\t/* allocate instance-specific interface IDs, and patch descriptors */\n"
init = """\t/* Copy the immutable templates into this instance before patching. */
	hidg->interface_desc = hidg_interface_desc;
	hidg->desc = hidg_desc;
	hidg->hs_in_ep_desc = hidg_hs_in_ep_desc;
	hidg->hs_out_ep_desc = hidg_hs_out_ep_desc;
	hidg->fs_in_ep_desc = hidg_fs_in_ep_desc;
	hidg->fs_out_ep_desc = hidg_fs_out_ep_desc;

	hidg->fs_descriptors[0] =
		(struct usb_descriptor_header *)&hidg->interface_desc;
	hidg->fs_descriptors[1] =
		(struct usb_descriptor_header *)&hidg->desc;
	hidg->fs_descriptors[2] =
		(struct usb_descriptor_header *)&hidg->fs_in_ep_desc;
	hidg->fs_descriptors[3] =
		(struct usb_descriptor_header *)&hidg->fs_out_ep_desc;
	hidg->fs_descriptors[4] = NULL;

	hidg->hs_descriptors[0] =
		(struct usb_descriptor_header *)&hidg->interface_desc;
	hidg->hs_descriptors[1] =
		(struct usb_descriptor_header *)&hidg->desc;
	hidg->hs_descriptors[2] =
		(struct usb_descriptor_header *)&hidg->hs_in_ep_desc;
	hidg->hs_descriptors[3] =
		(struct usb_descriptor_header *)&hidg->hs_out_ep_desc;
	hidg->hs_descriptors[4] = NULL;

	/* allocate instance-specific interface IDs, and patch descriptors */
"""
if anchor not in b:
    raise SystemExit("hidg_bind: descriptor initialization anchor not found")
b = b.replace(anchor, init, 1)

# Only identifiers that actually occur in this bind function are replaced.
repls = {
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
    "usb_assign_descriptors(f, hidg_fs_descriptors,\n\t\t\thidg_hs_descriptors, NULL)": "usb_assign_descriptors(f, hidg->fs_descriptors,\n\t\t\thidg->hs_descriptors, NULL)",
}
for old, new in repls.items():
    if old in b:
        b = b.replace(old, new)

# Verify the critical per-instance references were actually produced.
required = [
    "usb_ep_autoconfig(c->cdev->gadget, &hidg->fs_in_ep_desc)",
    "usb_ep_autoconfig(c->cdev->gadget, &hidg->fs_out_ep_desc)",
    "usb_assign_descriptors(f, hidg->fs_descriptors,",
    "hidg->interface_desc.bInterfaceNumber = status;",
]
for text in required:
    if text not in b:
        raise SystemExit(f"hidg_bind: required transformed text missing: {text}")

s = s[:bind] + b + s[end:]
p.write_text(s)
print("multi-instance HID descriptor fix applied")
