"""Render the Claude usage face and upload it to the cube as the custom face.

usage: .venv/bin/python push_face.py                 # fetch usage, render, upload
       .venv/bin/python push_face.py --if-changed    # upload only when the picture would change
       .venv/bin/python push_face.py --find          # forget the saved cube and look for it again

The first run looks for the cube's JieLi chip (the Bluetooth side that stores files) and saves
its address in cube.json, so later runs only talk to your own cube.
"""
import asyncio
import hashlib
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import cube_proto as cp          # noqa: E402
import face_styles               # noqa: E402
import usage_source              # noqa: E402
from bleak import BleakScanner   # noqa: E402

CONF = os.path.join(HERE, "cube.json")         # {"mac": "AA:BB:CC:DD:EE:FF"}
PNG = os.path.join(HERE, "face_preview.png")    # last picture sent, for a look on the Mac
STAMP = os.path.join(HERE, ".last_face_sha")    # sha of the last picture sent
COMPANY_ID = 0xB1B1   # manufacturer id in the cube's JieLi-side advertisement
NOT_FOUND = ("cube not found: switch it on, keep it close to the Mac, "
             "and close the MikuCube phone app if it is connected")


def saved_mac():
    try:
        return bytes.fromhex(json.load(open(CONF))["mac"].replace(":", ""))
    except (OSError, ValueError, KeyError):
        return None


def _save(mac: bytes) -> bytes:
    text = ":".join("%02X" % b for b in mac)
    json.dump({"mac": text}, open(CONF, "w"))
    print("found cube, saved to cube.json:", text, flush=True)
    return mac


async def discover_mac():
    print("looking for your cube...", flush=True)
    for _ in range(3):
        found = await BleakScanner.discover(timeout=10, return_adv=True)
        # 1) the JieLi side advertises manufacturer id 0xB1B1 with its own address in the last 6 bytes
        for dev, adv in found.values():
            md = adv.manufacturer_data.get(COMPANY_ID)
            if md and len(md) >= 6:
                return _save(bytes(md[-6:]))
        # 2) otherwise ask the named "Hatsune Miku CUBEFACE" side for it (characteristic d106)
        for dev, adv in found.values():
            if "CUBEFACE" in (adv.local_name or dev.name or "").upper():
                mac = await cp.read_headphone_mac(dev)
                if mac:
                    return _save(bytes.fromhex(mac.replace(":", "")))
    raise SystemExit(NOT_FOUND)


async def find(mac, tries=3):
    """The JieLi side advertises without a name; it carries its address in the manufacturer data."""
    for _ in range(tries):
        found = await BleakScanner.discover(timeout=15, return_adv=True)
        for dev, adv in found.values():
            if mac in b"".join(bytes(v) for v in adv.manufacturer_data.values()):
                return dev
    raise SystemExit(NOT_FOUND)


async def main():
    only_changed = "--if-changed" in sys.argv
    if "--find" in sys.argv and os.path.exists(CONF):
        os.remove(CONF)
    usage = usage_source.get_usage()
    now = time.time()
    face_styles.render(usage, now).save(PNG)
    data = cp.encode_image_file(PNG)
    sha = hashlib.sha256(data).hexdigest()
    try:
        last_sha = open(STAMP).read().split()[0]
    except (OSError, IndexError):
        last_sha = ""
    if only_changed and sha == last_sha:
        print("unchanged:", usage_source.format_text(usage))
        return
    mac = saved_mac() or await discover_mac()
    quiet = lambda s: None if s.startswith(("->", "<-", "block")) else print(s, flush=True)
    async with cp.CubeClient(await find(mac), log=quiet) as c:
        await c.write_file("10000001.RES", data)
        ba = await c.read_file("BA.JSN")
        if not ba or b"10000001.RES" not in ba:
            await c.set_face("10000001.RES",
                             json_text='{"name":"自定义背景","id":"10000001.RES","md5":"","rcnt":1,"edly":0}')
    open(STAMP, "w").write(sha)
    print(time.strftime("uploaded %H:%M:", time.localtime(now)), usage_source.format_text(usage))


if __name__ == "__main__":
    asyncio.run(main())
