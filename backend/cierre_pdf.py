"""PDF con el resumen del cierre de un turno de caja.

Generador de PDF mínimo y sin dependencias externas (PDF 1.4, fuentes estándar Helvetica
con codificación WinAnsi, que cubre tildes, ñ, €, «» y ·).
"""
import unicodedata
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

MADRID = ZoneInfo("Europe/Madrid")
PAGE_W, PAGE_H = 595.28, 841.89  # A4
LEFT, RIGHT = 48.0, PAGE_W - 48.0
TOP, BOTTOM = PAGE_H - 48.0, 64.0

INK = (0.06, 0.09, 0.16)       # slate-900
MUTED = (0.39, 0.45, 0.55)     # slate-500
RULE = (0.89, 0.91, 0.94)      # slate-200
AMBER = (0.98, 0.75, 0.14)     # amber-400
AMBER_SOFT = (1.0, 0.98, 0.92)
RED = (0.86, 0.15, 0.15)
GREEN = (0.02, 0.59, 0.41)

# Anchuras (1/1000 em) de Helvetica y Helvetica-Bold para ASCII 32..126.
_HELV = [278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278,
         556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 278, 278, 584, 584, 584, 556,
         1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778,
         667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556,
         333, 556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556,
         556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 334, 260, 334, 584]
_HELV_B = [278, 333, 474, 556, 556, 889, 722, 238, 333, 333, 389, 584, 278, 333, 278, 278,
           556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 333, 333, 584, 584, 584, 611,
           975, 722, 722, 722, 722, 667, 611, 778, 722, 278, 556, 722, 611, 833, 722, 778,
           667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 333, 278, 333, 584, 556,
           333, 556, 611, 556, 611, 556, 333, 611, 611, 278, 278, 556, 278, 889, 611, 611,
           611, 611, 389, 556, 333, 611, 556, 778, 556, 556, 500, 389, 280, 389, 584]

_REPLACEMENTS = {"−": "-", "→": "->", "≈": "~", " ": " ", " ": " "}


def _clean(text) -> str:
    text = "" if text is None else str(text)
    for a, b in _REPLACEMENTS.items():
        text = text.replace(a, b)
    return text


def text_width(text: str, size: float, bold: bool = False) -> float:
    table = _HELV_B if bold else _HELV
    total = 0
    for ch in _clean(text):
        code = ord(ch)
        if code > 126:  # letras con tilde, ñ…: misma anchura que la letra base
            base = unicodedata.normalize("NFKD", ch)[:1]
            code = ord(base) if base and ord(base) <= 126 else 0
        total += table[code - 32] if 32 <= code <= 126 else 556
    return total * size / 1000.0


def _escape(text: str) -> str:
    out = []
    for b in _clean(text).encode("cp1252", errors="replace"):
        if b in (0x28, 0x29, 0x5C):
            out.append("\\" + chr(b))
        elif b < 32 or b > 126:
            out.append("\\%03o" % b)
        else:
            out.append(chr(b))
    return "".join(out)


def _rgb(c) -> str:
    return "%.3f %.3f %.3f" % c


def fit(text: str, width: float, size: float, bold: bool = False) -> str:
    text = _clean(text)
    if text_width(text, size, bold) <= width:
        return text
    while text and text_width(text + "...", size, bold) > width:
        text = text[:-1]
    return text.rstrip() + "..."


def wrap(text: str, width: float, size: float, bold: bool = False):
    lines, current = [], ""
    for word in _clean(text).split():
        candidate = f"{current} {word}".strip()
        if text_width(candidate, size, bold) <= width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [""]


class Pdf:
    def __init__(self, title: str):
        self.title = title
        self.pages = []
        self.new_page()

    def new_page(self):
        self.ops = []
        self.pages.append(self.ops)

    def text(self, x, y, s, size=10.0, bold=False, color=INK):
        self.ops.append("BT /%s %.2f Tf %s rg %.2f %.2f Td (%s) Tj ET"
                        % ("F2" if bold else "F1", size, _rgb(color), x, y, _escape(s)))

    def text_right(self, x_right, y, s, size=10.0, bold=False, color=INK):
        self.text(x_right - text_width(s, size, bold), y, s, size, bold, color)

    def rect(self, x, y, w, h, color):
        self.ops.append("%s rg %.2f %.2f %.2f %.2f re f" % (_rgb(color), x, y, w, h))

    def line(self, x1, y1, x2, y2, color=RULE, width=0.6):
        self.ops.append("%s RG %.2f w %.2f %.2f m %.2f %.2f l S" % (_rgb(color), width, x1, y1, x2, y2))

    def render(self) -> bytes:
        objects = [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            None,  # páginas, se rellena al final
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>",
            ("<< /Title (%s) /Producer (Weed Lemon TPV) >>" % _escape(self.title)).encode("latin-1"),
        ]
        page_ids = []
        for ops in self.pages:
            stream = "\n".join(ops).encode("latin-1")
            objects.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
            content_id = len(objects)
            objects.append(("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %.2f %.2f] "
                            "/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents %d 0 R >>"
                            % (PAGE_W, PAGE_H, content_id)).encode("latin-1"))
            page_ids.append(len(objects))
        objects[1] = ("<< /Type /Pages /Kids [%s] /Count %d >>"
                      % (" ".join("%d 0 R" % i for i in page_ids), len(page_ids))).encode("latin-1")

        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = []
        for num, body in enumerate(objects, start=1):
            offsets.append(len(out))
            out += b"%d 0 obj\n" % num + body + b"\nendobj\n"
        xref = len(out)
        out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
        for off in offsets:
            out += b"%010d 00000 n \n" % off
        out += b"trailer\n<< /Size %d /Root 1 0 R /Info 5 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
        return bytes(out)


# ---------- formato ----------

def as_local(value):
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(MADRID)


def fmt_dt(value, with_date=True) -> str:
    local = as_local(value)
    if not local:
        return "-"
    return local.strftime("%d/%m/%Y %H:%M" if with_date else "%H:%M")


def fmt_cr(value, sign=False) -> str:
    value = round(value or 0, 2)
    txt = f"{abs(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    prefix = "-" if value < 0 else ("+" if sign and value > 0 else "")
    return f"{prefix}{txt} Cr"


def fmt_qty(value, unit="") -> str:
    value = round(value or 0, 3)
    txt = f"{value:.3f}".rstrip("0").rstrip(".").replace(".", ",")
    return f"{txt} {unit}".strip()


def fmt_duration(start, end) -> str:
    a, b = as_local(start), as_local(end)
    if not a or not b:
        return "-"
    minutes = max(0, int((b - a).total_seconds() // 60))
    return f"{minutes // 60} h {minutes % 60:02d} min"


def diff_label(diff):
    if abs(diff) < 0.005:
        return "Cuadra", GREEN
    return ("Sobrante", GREEN) if diff > 0 else ("Faltante", RED)


# ---------- informe en una sola página ----------

MARGIN = 40.0
L0, R1 = MARGIN, PAGE_W - MARGIN
GAP = 20.0
COL_W = (R1 - L0 - GAP) / 2
LEFT_COL = (L0, L0 + COL_W)
RIGHT_COL = (L0 + COL_W + GAP, R1)
ROW = 13.0          # alto de una línea de datos
FOOTER_Y = 30.0
CONTENT_BOTTOM = 62.0


def _section_title(pdf: Pdf, x0, x1, y, title):
    pdf.text(x0, y, title, 10.5, True, INK)
    pdf.line(x0, y - 5, x1, y - 5, AMBER, 1.1)
    return y - 18


def _kv(pdf: Pdf, x0, x1, y, label, value, bold=False, color=INK, size=9.0):
    width = x1 - x0
    value = fit(value, width * 0.55, size, bold)
    label = fit(label, width - text_width(value, size, bold) - 8, size)
    pdf.text(x0, y, label, size, False, MUTED)
    pdf.text_right(x1, y, value, size, bold, color)
    return y - ROW


def _rows_budget(available, needs, per_row):
    """Reparte filas entre bloques (movimientos, recuentos) para que todo quepa en la página."""
    alloc = list(needs)
    while sum(a * pr for a, pr in zip(alloc, per_row)) > available and any(alloc):
        i = max(range(len(alloc)), key=lambda k: alloc[k])
        alloc[i] -= 1
    return alloc


def _diffs(st):
    if not st:
        return []
    return [l for l in st.get("lines", []) if l.get("difference") is not None and abs(l["difference"]) > 1e-9]


def build_closing_pdf(session: dict, sales: list, recharges: list, movements: list,
                      opening_st, closing_st, club: str = "Weed Lemon Social Club") -> bytes:
    pdf = Pdf("Resumen de cierre de turno")
    closed_local = as_local(session.get("closed_at"))

    # Cabecera
    pdf.rect(0, PAGE_H - 74, PAGE_W, 74, AMBER)
    pdf.text(L0, PAGE_H - 26, club.upper(), 8, True, INK)
    pdf.text(L0, PAGE_H - 48, "Resumen de cierre de turno", 18, True, INK)
    sub = f"Turno de {session.get('opened_by', '-')}"
    if closed_local:
        sub += f" · {closed_local.strftime('%d/%m/%Y')}"
    pdf.text(L0, PAGE_H - 63, sub, 9.5, False, INK)
    top = PAGE_H - 96

    # ----- Fila 1: Turno | Ventas -----
    y = _section_title(pdf, *LEFT_COL, top, "Turno")
    y = _kv(pdf, *LEFT_COL, y, "Responsable", session.get("opened_by") or "-", bold=True)
    y = _kv(pdf, *LEFT_COL, y, "Apertura", fmt_dt(session.get("opened_at")))
    y = _kv(pdf, *LEFT_COL, y, "Cierre", fmt_dt(session.get("closed_at")))
    y = _kv(pdf, *LEFT_COL, y, "Duración", fmt_duration(session.get("opened_at"), session.get("closed_at")))
    y = _kv(pdf, *LEFT_COL, y, "Cerrado por", session.get("closed_by") or "-")
    if session.get("supervised"):
        y = _kv(pdf, *LEFT_COL, y, "Supervisión", "Administrador")
    y_left = y

    total_sales = sum(s["total"] for s in sales)
    grams = sum(i["qty"] for s in sales for i in s["items"] if i.get("unit") == "g")
    units = sum(i["qty"] for s in sales for i in s["items"] if i.get("unit") != "g")
    oos = [s for s in sales if s.get("out_of_shift")]
    socios = {s.get("socio_id") for s in sales if s.get("socio_id")}
    deuda = (session.get("totals") or {}).get("deuda_socios")
    y = _section_title(pdf, *RIGHT_COL, top, "Ventas (con saldo de socios)")
    y = _kv(pdf, *RIGHT_COL, y, "Tickets", str(len(sales)))
    y = _kv(pdf, *RIGHT_COL, y, "Total vendido", fmt_cr(total_sales), bold=True)
    y = _kv(pdf, *RIGHT_COL, y, "Socios atendidos", str(len(socios)))
    y = _kv(pdf, *RIGHT_COL, y, "Gramos / unidades", f"{fmt_qty(grams, 'g')} · {fmt_qty(units, 'ud')}")
    if oos:
        y = _kv(pdf, *RIGHT_COL, y, f"Fuera de turno incorporadas ({len(oos)})", fmt_cr(sum(s['total'] for s in oos)))
    if deuda is not None:
        y = _kv(pdf, *RIGHT_COL, y, "Deuda de socios al cierre", fmt_cr(deuda), color=RED if deuda > 0 else INK)
    y_right = y
    top = min(y_left, y_right) - 8

    # ----- Fila 2: Arqueo | Diferencia -----
    cc = session.get("cash_count") or {}
    starting = session.get("starting_amount", 0) or 0
    rec_cash = [r for r in recharges if r.get("method", "efectivo") == "efectivo"]
    rec_oos = [r for r in rec_cash if r.get("out_of_shift")]
    entradas = sum(m["amount"] for m in movements if m["type"] == "in")
    salidas = sum(m["amount"] for m in movements if m["type"] == "out")
    expected = cc.get("expected", session.get("expected_amount"))
    counted = cc.get("counted", session.get("counted_amount"))
    difference = cc.get("difference", session.get("difference"))

    y = _section_title(pdf, *LEFT_COL, top, "Arqueo de efectivo")
    y = _kv(pdf, *LEFT_COL, y, "Fondo inicial", fmt_cr(starting))
    y = _kv(pdf, *LEFT_COL, y, f"Recargas en efectivo ({len(rec_cash)})", fmt_cr(sum(r['amount'] for r in rec_cash)))
    if rec_oos:
        y = _kv(pdf, *LEFT_COL, y, f"  de ellas fuera de turno ({len(rec_oos)})", fmt_cr(sum(r['amount'] for r in rec_oos)))
    y = _kv(pdf, *LEFT_COL, y, "Entradas manuales", fmt_cr(entradas))
    y = _kv(pdf, *LEFT_COL, y, "Salidas manuales", fmt_cr(-salidas) if salidas else fmt_cr(0))
    if expected is not None:
        y = _kv(pdf, *LEFT_COL, y, "Efectivo esperado", fmt_cr(expected), bold=True)
    if counted is not None:
        y = _kv(pdf, *LEFT_COL, y, "Efectivo contado", fmt_cr(counted), bold=True)
    y_left = y

    y = _section_title(pdf, *RIGHT_COL, top, "Resultado de caja")
    x0, x1 = RIGHT_COL
    if difference is not None:
        label, color = diff_label(difference)
        pdf.rect(x0, y - 34, x1 - x0, 46, AMBER_SOFT)
        pdf.text(x0 + 10, y - 2, label.upper(), 8.5, True, MUTED)
        pdf.text(x0 + 10, y - 24, fmt_cr(difference, sign=True), 18, True, color)
        y -= 56
    note = cc.get("reason") or session.get("notes")
    if note:
        lines = wrap(f"Nota: {note}", x1 - x0, 8.5)
        if len(lines) > 3:
            lines = lines[:2] + [fit(lines[2] + " " + lines[3], x1 - x0, 8.5)]
            if not lines[2].endswith("..."):
                lines[2] = fit(lines[2] + " ...", x1 - x0, 8.5)
        for line in lines:
            pdf.text(x0, y, line, 8.5, False, INK)
            y -= 11
    pdf.text(x0, y - 2, "Esperado = fondo + recargas en efectivo + entradas - salidas.", 7.5, False, MUTED)
    y -= 14
    y_right = y
    top = min(y_left, y_right) - 8

    # ----- Reparto del espacio restante -----
    open_diffs, close_diffs = _diffs(opening_st), _diffs(closing_st)
    mov_overhead = 18 + 14 + (12 if movements else 0)      # título + cabecera + posible "y N más"
    stock_overhead = 18 + 26 + 12 + 12                      # título + resumen + cabecera + posible "y N más"
    footnote = 14
    available = top - CONTENT_BOTTOM - mov_overhead - stock_overhead - footnote
    mov_rows, stock_rows = _rows_budget(available, [len(movements), max(len(open_diffs), len(close_diffs))], [12, 11])

    # ----- Fila 3: Movimientos manuales -----
    y = _section_title(pdf, L0, R1, top, f"Movimientos manuales de caja ({len(movements)})")
    if not movements:
        pdf.text(L0, y, "Sin movimientos manuales en este turno.", 8.5, False, MUTED)
        y -= 14
    else:
        cols = [(L0, "Hora", "l"), (L0 + 46, "Tipo", "l"), (L0 + 100, "Motivo", "l"), (L0 + 330, "Por", "l"), (R1, "Importe", "r")]
        for x, title, al in cols:
            (pdf.text_right if al == "r" else pdf.text)(x, y, title, 7.5, True, MUTED)
        y -= 12
        ordered = sorted(movements, key=lambda m: m["created_at"])
        for m in ordered[:mov_rows]:
            sign = 1 if m["type"] == "in" else -1
            pdf.text(L0, y, fmt_dt(m["created_at"], with_date=False), 8.5, False, MUTED)
            pdf.text(L0 + 46, y, "Entrada" if sign > 0 else "Salida", 8.5)
            pdf.text(L0 + 100, y, fit(m.get("reason") or "", 222, 8.5), 8.5)
            pdf.text(L0 + 330, y, fit(m.get("created_by") or "", 110, 8.5), 8.5, False, MUTED)
            pdf.text_right(R1, y, fmt_cr(sign * m["amount"], sign=True), 8.5, True, GREEN if sign > 0 else RED)
            y -= 12
        if len(ordered) > mov_rows:
            pdf.text(L0, y, f"... y {len(ordered) - mov_rows} movimientos más (detalle completo en el informe del turno de la aplicación).", 7.5, False, MUTED)
            y -= 12
    top = y - 6

    # ----- Fila 4: Recuentos de stock (apertura | cierre) -----
    def stock_block(col, title, st, diffs):
        x0, x1 = col
        yy = _section_title(pdf, x0, x1, top, title)
        if not st:
            pdf.text(x0, yy, "Sin recuento registrado.", 8.5, False, MUTED)
            return
        n = len(st.get("lines", []))
        pdf.text(x0, yy, f"{n} productos contados · {len(diffs)} con diferencia", 8.5, True, RED if diffs else GREEN)
        yy -= 11
        if st.get("finalized_by"):
            pdf.text(x0, yy, f"Contado por {st['finalized_by']}", 8, False, MUTED)
        yy -= 15
        if not diffs:
            pdf.text(x0, yy, "Todo coincide con el esperado.", 8.5, False, MUTED)
            return
        w = x1 - x0
        pdf.text(x0, yy, "Producto", 7.5, True, MUTED)
        pdf.text_right(x0 + w * 0.66, yy, "Esperado", 7.5, True, MUTED)
        pdf.text_right(x0 + w * 0.83, yy, "Contado", 7.5, True, MUTED)
        pdf.text_right(x1, yy, "Dif.", 7.5, True, MUTED)
        yy -= 11
        for l in diffs[:stock_rows]:
            d = l["difference"]
            pdf.text(x0, yy, fit(l["name"], w * 0.46, 8.5), 8.5)
            pdf.text_right(x0 + w * 0.66, yy, fmt_qty(l["expected"], l["unit"]), 8.5, False, MUTED)
            pdf.text_right(x0 + w * 0.83, yy, fmt_qty(l["counted"], l["unit"]), 8.5)
            pdf.text_right(x1, yy, ("+" if d > 0 else "") + fmt_qty(d, l["unit"]), 8.5, True, RED if d < 0 else GREEN)
            yy -= 11
        if len(diffs) > stock_rows:
            pdf.text(x0, yy, f"... y {len(diffs) - stock_rows} diferencias más", 7.5, False, MUTED)

    stock_block(LEFT_COL, "Recuento de stock · apertura", opening_st, open_diffs)
    stock_block(RIGHT_COL, "Recuento de stock · cierre", closing_st, close_diffs)

    # Nota y pie
    pdf.text(L0, CONTENT_BOTTOM - 8,
             "Lo contado pasa a ser el stock del sistema al confirmar cada recuento. Las ventas se cobran del saldo; el efectivo entra por las recargas.",
             7, False, MUTED)
    generated = datetime.now(timezone.utc).astimezone(MADRID).strftime("%d/%m/%Y %H:%M")
    pdf.line(L0, FOOTER_Y + 12, R1, FOOTER_Y + 12)
    pdf.text(L0, FOOTER_Y, f"{club} · Resumen de cierre · generado el {generated}", 7.5, False, MUTED)
    pdf.text_right(R1, FOOTER_Y, "Página 1 de 1", 7.5, False, MUTED)
    return pdf.render()
