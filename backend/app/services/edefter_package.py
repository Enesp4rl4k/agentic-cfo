"""e-Defter yükleme paketi — ancak iki imza da varsa ve birbirini tutuyorsa.

GİB's web service takes one zip per call, named
`[VKN]-[YILAY]-[YB|KB]-[parça].zip`, holding the defter part and its berat.
This module builds that zip and refuses every package GİB would refuse for a
reason we can see before sending it:

- either file unsigned (a HashValue where the XAdES signature should be),
- the berat's `ds:SignatureValue` not equal to the defter's — the berat
  belongs to another file, or to an earlier version of this one,
- names that disagree on VKN, period, ledger or part.

A package that would bounce is not built at all. Error 111 ("daha önce
yüklenmiş") and the rest are GİB's to say; these are ours.
"""
from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass

from app.services.edefter_berat import DEFTER_NAME, NS, BeratError, _parse, signature_value

BERAT_NAME = re.compile(r"^(?P<vkn>\d{10,11})-(?P<period>\d{6})-(?P<kind>YB|KB)-(?P<part>\d{6})\.xml$")

# Fixed so the same two files always make byte-identical zips; a package's
# hash should not depend on the second it was built in.
_ZIP_TIME = (1980, 1, 1, 0, 0, 0)


class PackageError(ValueError):
    """These two files do not make a package GİB would accept."""


@dataclass
class EDefterPackage:
    file_name: str        # 1234567808-201804-YB-000000.zip
    paket_id: str         # the same, without .zip — what getBatchStatus takes
    zip_bytes: bytes


def _berat_signature_value(root_xml: bytes) -> str | None:
    root = _parse(root_xml)
    node = root.find(f"{{{NS['ds']}}}SignatureValue")
    if node is None or not (node.text or "").strip():
        return None
    return "".join((node.text or "").split())


def build_package(
    *, defter_xml: bytes, defter_file_name: str, berat_xml: bytes, berat_file_name: str
) -> EDefterPackage:
    d = DEFTER_NAME.match(defter_file_name)
    b = BERAT_NAME.match(berat_file_name)
    if not d:
        raise PackageError(f"defter adı GİB biçiminde değil: {defter_file_name!r}")
    if not b:
        raise PackageError(f"berat adı GİB biçiminde değil: {berat_file_name!r}")
    for key in ("vkn", "period", "part"):
        if d[key] != b[key]:
            raise PackageError(
                f"defter ve berat farklı {key} taşıyor ({d[key]} / {b[key]}) — aynı parçaya ait olmalı"
            )
    if b["kind"] != f"{d['kind']}B":
        raise PackageError(f"{d['kind']} defterinin beratı {d['kind']}B olmalı, {b['kind']} verildi")

    try:
        defter_root = _parse(defter_xml)
        berat_root = _parse(berat_xml)
    except BeratError as exc:
        raise PackageError(str(exc)) from exc

    defter_sig = signature_value(defter_root)
    if defter_sig is None:
        raise PackageError("defter imzasız (HashValue taşıyor) — GİB yalnızca mali mühürlü defter kabul eder")
    if berat_root.find(f"{{{NS['ds']}}}Signature") is None:
        raise PackageError("berat imzasız — ds:Signature zorunlu")
    berat_ref = _berat_signature_value(berat_xml)
    if berat_ref != defter_sig:
        raise PackageError(
            "beratın ds:SignatureValue değeri defterin imzasıyla aynı değil — "
            "bu berat başka bir dosyaya (ya da bu dosyanın eski bir sürümüne) ait"
        )

    paket_id = f"{d['vkn']}-{d['period']}-{b['kind']}-{d['part']}"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, data in ((defter_file_name, defter_xml), (berat_file_name, berat_xml)):
            info = zipfile.ZipInfo(name, date_time=_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, data)
    return EDefterPackage(file_name=f"{paket_id}.zip", paket_id=paket_id, zip_bytes=buf.getvalue())
