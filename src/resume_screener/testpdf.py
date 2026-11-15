"""Write a minimal, real PDF from plain text, with no extra dependency.

Lets the whole pipeline be exercised on made-up resumes, so nobody's actual
resume is ever needed for a test. One page, built-in Helvetica: enough for
pdftotext to read back, which is all the pipeline needs.
"""
from pathlib import Path


def _esc(s: str) -> str:
    return s.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def text_to_pdf(text: str, out_path: Path, font_size: int = 10, leading: int = 13) -> Path:
    lines = text.replace("\t", "    ").split("\n")
    parts = [f"BT /F1 {font_size} Tf {leading} TL 50 790 Td"]
    parts += [f"({_esc(ln[:110])}) Tj T*" for ln in lines]
    parts.append("ET")
    stream = "\n".join(parts).encode("latin-1", "replace")

    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]

    buf = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(len(buf))
        buf += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"

    xref_at = len(buf)
    buf += f"xref\n0 {len(objs) + 1}\n".encode() + b"0000000000 65535 f \n"
    for off in offsets:
        buf += f"{off:010d} 00000 n \n".encode()
    buf += (f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_at}\n%%EOF\n").encode()

    out_path = Path(out_path)
    out_path.write_bytes(bytes(buf))
    return out_path
