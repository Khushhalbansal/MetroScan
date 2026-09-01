"""HTML to PDF, through whichever engine this host can actually run.

WeasyPrint is the intended engine and the one the deployment image installs: it has real
CSS support and proper text shaping, which matters for the Devanagari half of a
bilingual report. It also binds to Pango/GObject, which are native libraries absent from
a stock Windows development machine — so on such a host `import weasyprint` raises
OSError at import time, not ImportError, and not until the shared object is dlopened.

Rather than make the report unbuildable wherever those libraries are missing, this
module picks an engine at call time and reports which one it used. The fallback is
xhtml2pdf, which is pure Python and renders the conservative subset of CSS the report
template is written in.

That constraint is why `templates/report.html` uses tables and background colours rather
than flexbox or grid: one template has to render identically in both engines, and the
subset both agree on is the one from about 2005. For a printed compliance report that is
not a real loss — it is a document of tables and rules.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

FONTS = Path(__file__).parent / "fonts"

# The PDF base-14 fonts (Helvetica, Courier) predate the rupee sign by decades and have
# no glyph at U+20B9, so every MRP in a report rendered with them prints as a tofu box.
# On a document about maximum retail price that is not a cosmetic problem — the amount
# stops being legible and the quoted evidence stops matching the pack.
#
# DejaVu is vendored beside this module (see fonts/LICENSE.txt) because it covers ₹, ²,
# the em dash and the typographic quotes the report uses, and because depending on a
# font that happens to be installed on the host makes the report look different on the
# developer's Windows machine and the Linux server it is deployed to.
#
# It does NOT cover Devanagari. A bilingual report needs a face that does — IBM Plex
# Sans Devanagari, per docs/design-direction.md — and that is not yet vendored.
FONT_FACES = (
    ("MetroScan Sans", "DejaVuSans.ttf", "normal", "normal"),
    ("MetroScan Sans", "DejaVuSans-Bold.ttf", "bold", "normal"),
    ("MetroScan Mono", "DejaVuSansMono.ttf", "normal", "normal"),
    ("MetroScan Mono", "DejaVuSansMono-Bold.ttf", "bold", "normal"),
)


def font_css() -> str:
    """@font-face rules both engines understand, with absolute paths.

    Returns an empty string when the fonts are not present, so a checkout without them
    still produces a report — one that cannot print a rupee sign, but a report.
    """
    rules = []
    for family, filename, weight, style in FONT_FACES:
        path = FONTS / filename
        if not path.is_file():
            continue
        # A file:// URI, not a bare path: xhtml2pdf hands the src to urllib, which
        # reads "C:/..." as a URL with the scheme "c" and raises.
        rules.append(
            f'@font-face {{ font-family: "{family}"; '
            f'src: url("{path.as_uri()}"); '
            f"font-weight: {weight}; font-style: {style}; }}"
        )
    if not rules:
        log.warning(
            "No report fonts vendored in %s; the rupee sign will not render in PDFs.",
            FONTS,
        )
    return "\n".join(rules)


def fonts_available() -> bool:
    return (FONTS / "DejaVuSans.ttf").is_file()


@dataclass(frozen=True)
class Rendered:
    pdf: bytes
    engine: str


class PdfError(RuntimeError):
    """No engine on this host could turn the report into a PDF."""


def _weasyprint(html: str, base_url: str | None) -> bytes | None:
    """Returns None when WeasyPrint is unavailable, rather than raising.

    The import is attempted on every call and the failure caught broadly: WeasyPrint
    signals a missing Pango by raising OSError from a C library loader, and catching
    only ImportError here would turn a recoverable "use the other engine" into a 500.
    """
    try:
        from weasyprint import HTML
    except Exception as exc:  # noqa: BLE001 - see docstring; the failure mode is native
        log.debug("WeasyPrint unavailable (%s); falling back.", exc)
        return None

    try:
        return HTML(string=html, base_url=base_url).write_pdf()
    except Exception:
        # A rendering failure is different from an unavailable engine and is worth
        # seeing in full, but it must still not lose the report: fall through.
        log.exception("WeasyPrint failed to render the report; falling back.")
        return None


_registered = False


def _register_with_reportlab() -> None:
    """Make the vendored faces resolvable by xhtml2pdf, without an @font-face fetch.

    Two steps, both needed. reportlab has to hold the TTFs so it can draw with them,
    and xhtml2pdf has to know that the family name in the stylesheet maps to one of
    them — it resolves font-family against its own `DEFAULT_FONT` table, not against
    reportlab's registry.

    The alternative, letting xhtml2pdf fetch the @font-face src itself, does not work
    here: it downloads the file to a temp path and then fails to reopen it on Windows
    ("Cannot open resource ...tmpXXXX.ttf"). Registering directly avoids the fetch.
    """
    global _registered
    if _registered or not fonts_available():
        return

    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    try:
        for family, filename, weight, _style in FONT_FACES:
            name = family if weight == "normal" else f"{family} Bold"
            pdfmetrics.registerFont(TTFont(name, str(FONTS / filename)))
        from xhtml2pdf.default import DEFAULT_FONT

        for family in ("MetroScan Sans", "MetroScan Mono"):
            pdfmetrics.registerFontFamily(
                family, normal=family, bold=f"{family} Bold",
                italic=family, boldItalic=f"{family} Bold",
            )
            # xhtml2pdf lowercases the family name from the CSS before looking it up.
            DEFAULT_FONT[family.lower()] = family
        _registered = True
    except Exception:
        # A report in the wrong face beats no report; the rupee sign is the only
        # visible loss and the failure is worth seeing in the log.
        log.exception("Could not register the vendored report fonts.")


def _xhtml2pdf(html: str) -> bytes | None:
    try:
        from xhtml2pdf import pisa
    except ImportError as exc:  # pragma: no cover
        log.debug("xhtml2pdf unavailable (%s).", exc)
        return None

    _register_with_reportlab()

    buffer = io.BytesIO()
    result = pisa.CreatePDF(html, dest=buffer, encoding="utf-8")
    if result.err:
        log.error("xhtml2pdf reported %s error(s) rendering the report.", result.err)
        return None
    return buffer.getvalue()


def render(html: str, *, base_url: str | None = None) -> Rendered:
    """Render `html`, preferring WeasyPrint. Raises PdfError if neither engine works."""
    pdf = _weasyprint(html, base_url)
    if pdf:
        return Rendered(pdf=pdf, engine="weasyprint")

    pdf = _xhtml2pdf(html)
    if pdf:
        return Rendered(pdf=pdf, engine="xhtml2pdf")

    raise PdfError(
        "No PDF engine on this host could render the report. Install WeasyPrint's "
        "Pango/GObject libraries, or xhtml2pdf, and try again."
    )


def available_engine() -> str:
    """Which engine a render would use right now. For /health and for diagnostics."""
    try:
        import weasyprint  # noqa: F401

        return "weasyprint"
    except Exception:  # noqa: BLE001
        pass
    try:
        import xhtml2pdf  # noqa: F401

        return "xhtml2pdf"
    except ImportError:  # pragma: no cover
        return "none"
