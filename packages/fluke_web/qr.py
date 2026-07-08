from __future__ import annotations


def render_qr_ascii(text: str) -> str | None:
    """Render ``text`` as an ASCII QR code, or return ``None`` if unavailable.

    The ``qrcode`` dependency is an optional nicety (part of the ``.[web]``
    extra). When it is not installed we return ``None`` so callers can fall back
    to simply printing the URL.
    """
    try:
        import qrcode
    except ModuleNotFoundError:
        return None

    try:
        qr = qrcode.QRCode(border=1)
        qr.add_data(text)
        qr.make(fit=True)
        matrix = qr.get_matrix()
    except Exception:
        return None

    return _matrix_to_ascii(matrix)


def _matrix_to_ascii(matrix: list[list[bool]]) -> str:
    # Use half-block characters so two rows collapse into one terminal line,
    # keeping the code roughly square in a typical monospace terminal.
    full = "██"
    top = "▀▀"
    bottom = "▄▄"
    blank = "  "

    lines: list[str] = []
    for row in range(0, len(matrix), 2):
        upper = matrix[row]
        lower = matrix[row + 1] if row + 1 < len(matrix) else [False] * len(upper)
        line = []
        for u, l in zip(upper, lower):
            # A "dark" module must show as background-on-light for scanners;
            # terminals are dark, so invert: dark module -> space, light -> block.
            if not u and not l:
                line.append(full)
            elif not u and l:
                line.append(top)
            elif u and not l:
                line.append(bottom)
            else:
                line.append(blank)
        lines.append("".join(line))
    return "\n".join(lines)
