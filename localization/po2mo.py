#!/usr/bin/env python3
"""Compile gettext .po catalogs to .mo without gettext installed.

This machine has no msgfmt binary and no Babel, so localization/manage.py
(which needs both) cannot compile catalogs here. This script implements the
GNU MO binary format directly, so editing locale/<lang>/LC_MESSAGES/*.po and
re-running it is enough to see new translations.

Usage:
    python3 localization/po2mo.py                    # every locale, both domains
    python3 localization/po2mo.py locale/zh_Hans/LC_MESSAGES/django.po
"""

import pathlib
import re
import struct
import sys


def _unquote(chunk):
    chunk = chunk.strip()
    body = chunk[1:-1] if len(chunk) >= 2 and chunk[0] == '"' and chunk[-1] == '"' else chunk
    out = []
    i = 0
    while i < len(body):
        char = body[i]
        if char == "\\" and i + 1 < len(body):
            nxt = body[i + 1]
            if nxt == "n":
                out.append("\n"); i += 2
            elif nxt == "t":
                out.append("\t"); i += 2
            elif nxt == "r":
                out.append("\r"); i += 2
            elif nxt == '"':
                out.append('"'); i += 2
            elif nxt == "\\":
                out.append("\\"); i += 2
            elif nxt == "u" and i + 5 < len(body):
                out.append(chr(int(body[i + 2:i + 6], 16))); i += 6
            else:
                out.append(nxt); i += 2
        else:
            out.append(char); i += 1
    return "".join(out)


def parse_po(text):
    entries = []
    cur = {"ctxt": None, "id": None, "id_plural": None, "str": None, "str_plural": {}}
    field = None

    def flush():
        if cur["id"] is not None:
            entries.append(dict(cur))

    for raw in text.split("\n"):
        line = raw.rstrip()
        if not line.strip() or line.startswith("#"):
            continue
        if line.startswith("msgctxt "):
            flush()
            cur = {"ctxt": _unquote(line[8:]), "id": None, "id_plural": None, "str": None, "str_plural": {}}
            field = "ctxt"
        elif line.startswith("msgid_plural "):
            cur["id_plural"] = _unquote(line[13:])
            field = "id_plural"
        elif line.startswith("msgid "):
            if cur["id"] is not None:
                flush()
                cur = {"ctxt": None, "id": None, "id_plural": None, "str": None, "str_plural": {}}
            cur["id"] = _unquote(line[6:])
            field = "id"
        elif line.startswith("msgstr["):
            index = int(re.match(r"msgstr\[(\d+)\]", line).group(1))
            cur["str_plural"][index] = _unquote(line.split("]", 1)[1])
            field = ("plural", index)
        elif line.startswith("msgstr "):
            cur["str"] = _unquote(line[7:])
            field = "str"
        elif line.startswith('"'):
            value = _unquote(line)
            if field == "id":
                cur["id"] += value
            elif field == "ctxt":
                cur["ctxt"] = (cur["ctxt"] or "") + value
            elif field == "id_plural":
                cur["id_plural"] = (cur["id_plural"] or "") + value
            elif field == "str":
                cur["str"] = (cur["str"] or "") + value
            elif isinstance(field, tuple):
                cur["str_plural"][field[1]] = cur["str_plural"].get(field[1], "") + value
    flush()
    return entries


def compile_po(po_path, mo_path):
    pairs = []
    for entry in parse_po(pathlib.Path(po_path).read_text()):
        key = entry["id"] if not entry["ctxt"] else entry["ctxt"] + "\x04" + entry["id"]
        if entry["id_plural"] is not None:
            key = key + "\x00" + entry["id_plural"]
        if entry["str_plural"]:
            value = "\x00".join(entry["str_plural"][i] for i in sorted(entry["str_plural"]))
        else:
            value = entry["str"] or ""
        pairs.append((key.encode("utf-8"), value.encode("utf-8")))
    pairs.sort(key=lambda pair: pair[0])

    count = len(pairs)
    key_start = 28 + 16 * count
    keys = b""
    key_table = []
    for key, _value in pairs:
        key_table.append((len(key), key_start + len(keys)))
        keys += key + b"\x00"
    value_start = key_start + len(keys)
    values = b""
    value_table = []
    for _key, value in pairs:
        value_table.append((len(value), value_start + len(values)))
        values += value + b"\x00"

    out = struct.pack("<7I", 0x950412DE, 0, count, 28, 28 + 8 * count, 0, 28 + 16 * count)
    for length, offset in key_table:
        out += struct.pack("<2I", length, offset)
    for length, offset in value_table:
        out += struct.pack("<2I", length, offset)
    out += keys + values
    pathlib.Path(mo_path).write_bytes(out)
    print(f"{mo_path}: {count} entries, {len(out)} bytes")


def main():
    root = pathlib.Path(__file__).resolve().parent.parent
    if len(sys.argv) > 1:
        targets = [pathlib.Path(arg) for arg in sys.argv[1:]]
    else:
        targets = sorted(root.glob("locale/*/LC_MESSAGES/*.po"))
    for po_path in targets:
        compile_po(po_path, po_path.with_suffix(".mo"))


if __name__ == "__main__":
    main()
