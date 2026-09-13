#!/usr/bin/env python3
"""Make the legacy 3.10 f_hid implementation safe for two HID instances.

apply_hid.py already installs the HID GET_PROTOCOL/SET_PROTOCOL handlers.
This second pass only supplies the per-instance descriptor storage that the
Android integration needs. The stock driver keeps mutable descriptors
globally, so the second HID bind can overwrite the first instance.
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

# apply_hid.py is deliberately responsible for protocol handling. Confirm
# that pass ran before adding the protocol state field it depends on.
if "hidg->protocol" not in s:
    raise SystemExit("f_hid.c: expected HID protocol handlers from apply_hid.py are missing")

# The original f_hid.c was text-included by hid.c. That compilation context
# supplied this helper indirectly. Android now builds f_hid.o standalone, so
# provide the exact request-buffer cleanup helper locally.
if "static void free_ep_req(struct usb_ep *ep, struct usb_request *req)" not in s:
    anchor = "static int major, minors;\nstatic struct class *hidg_class;\n"
    helper = anchor + """

static void free_ep_req(struct usb_ep *ep, struct usb_request *req)
{
	if (req->buf)
		kfree(req->buf);
	usb_ep_free_request(ep, req);
}
"""
    if anchor not in s:
        raise SystemExit("f_hid.c: cleanup helper insertion anchor not found")
    s = s.replace(anchor, helper, 1)

# These are legacy template arrays. Multi-instance HID now builds descriptor
# arrays inside each f_hidg instance, so the templates are intentionally kept
# only as initialization sources and must not trigger -Werror unused warnings.
s = s.replace(
    "static struct usb_descriptor_header *hidg_hs_descriptors[] = {",
    "static struct usb_descriptor_header *hidg_hs_descriptors[] __maybe_unused = {",
    1,
)
s = s.replace(
    "static struct usb_descriptor_header *hidg_fs_descriptors[] = {",
    "static struct usb_descriptor_header *hidg_fs_descriptors[] __maybe_unused = {",
    1,
)

# Add per-instance descriptor storage and protocol state to struct f_hidg.
anchor = "\tstruct usb_ep\t\t\t*out_ep;\n"
insert = anchor + """

\t/* Private mutable descriptors: keyboard and mouse must not share them. */
\tstruct usb_interface_descriptor interface_desc;
\tstruct hid_descriptor desc;
\tstruct usb_endpoint_descriptor hs_in_ep_desc;
\tstruct usb_endpoint_descriptor hs_out_ep_desc;
\tstruct usb_endpoint_descriptor fs_in_ep_desc;
\tstruct usb_endpoint_descriptor fs_out_ep_desc;
\tstruct usb_descriptor_header *hs_descriptors[5];
\tstruct usb_descriptor_header *fs_descriptors[5];
\tunsigned char protocol;
"""
if anchor not in s:
    raise SystemExit("f_hid.c: f_hidg endpoint anchor not found")
s = s.replace(anchor, insert, 1)

# Make HID descriptor control replies instance-local. apply_hid.py leaves the
# descriptor request itself otherwise unchanged.
old = "hidg_desc.bLength"
if old not in s:
    raise SystemExit("f_hid.c: HID descriptor length reference not found")
s = s.replace(old, "hidg->desc.bLength", 1)
old = "memcpy(req->buf, &hidg_desc, length);"
if old not in s:
    raise SystemExit("f_hid.c: HID descriptor copy reference not found")
s = s.replace(old, "memcpy(req->buf, &hidg->desc, length);", 1)

bind = s.index("static int hidg_bind(struct usb_configuration *c, struct usb_function *f)")
end = s.index("static void hidg_unbind", bind)
b = s[bind:end]

# Initialize private descriptors before any per-instance mutation.
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
# replacement is required because endpoint autoconfiguration needs the private
# endpoint descriptor object, not merely its fields.
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

# Ensure no global mutable descriptor symbol remains in bind().
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