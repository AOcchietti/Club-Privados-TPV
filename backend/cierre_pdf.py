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


class Report(Pdf):
    """Documento con cursor vertical, saltos de página automáticos y pie con numeración."""

    def __init__(self, title: str, subtitle: str, club: str):
        super().__init__(title)
        self.club = club
        self.doc_title = title
        self.rect(0, PAGE_H - 92, PAGE_W, 92, AMBER)
        self.text(LEFT, PAGE_H - 40, club.upper(), 9, True, INK)
        self.text(LEFT, PAGE_H - 64, title, 20, True, INK)
        self.text(LEFT, PAGE_H - 80, subtitle, 10, False, INK)
        self.y = PAGE_H - 112

    def ensure(self, height):
        if self.y - height < BOTTOM:
            self.new_page()
            self.text(LEFT, PAGE_H - 40, f"{self.doc_title} (continuación)", 9, True, MUTED)
            self.line(LEFT, PAGE_H - 48, RIGHT, PAGE_H - 48)
            self.y = PAGE_H - 66

    def section(self, title):
        self.ensure(90)  # que el título no quede solo al final de la página
        self.y -= 16
        self.text(LEFT, self.y, title, 12, True)
        self.y -= 7
        self.line(LEFT, self.y, RIGHT, self.y, AMBER, 1.2)
        self.y -= 15

    def kv(self, label, value, bold=False, color=INK):
        self.ensure(15)
        self.text(LEFT, self.y, label, 10, False, MUTED)
        self.text_right(RIGHT, self.y, fit(value, (RIGHT - LEFT) * 0.6, 10, bold), 10, bold, color)
        self.y -= 15

    def highlight(self, label, value, color=INK):
        self.ensure(30)
        self.rect(LEFT, self.y - 9, RIGHT - LEFT, 24, AMBER_SOFT)
        self.text(LEFT + 8, self.y, label, 11, True)
        self.text_right(RIGHT - 8, self.y, value, 11, True, color)
        self.y -= 30

    def paragraph(self, text, size=9, color=MUTED):
        for line in wrap(text, RIGHT - LEFT, size):
            self.ensure(13)
            self.text(LEFT, self.y, line, size, False, color)
            self.y -= 12
        self.y -= 3

    def table(self, columns, rows, colors=None):
        """columns: [(cabecera, anchura relativa, 'l' | 'r')]."""
        total = sum(c[1] for c in columns)
        widths = [(RIGHT - LEFT) * c[1] / total for c in columns]

        def header():
            self.ensure(20)
            x = LEFT
            for (title, _, align), w in zip(columns, widths):
                if align == "r":
                    self.text_right(x + w - 2, self.y, title, 8, True, MUTED)
                else:
                    self.text(x, self.y, title, 8, True, MUTED)
                x += w
            self.y -= 5
            self.line(LEFT, self.y, RIGHT, self.y)
            self.y -= 12

        header()
        for i, row in enumerate(rows):
            if self.y - 14 < BOTTOM:
                self.ensure(10_000)  # fuerza salto de página
                header()
            x = LEFT
            for j, ((_, _, align), w) in enumerate(zip(columns, widths)):
                color = (colors[i][j] if colors and colors[i] and colors[i][j] else INK)
                cell = fit(row[j], w - 6, 9)
                if align == "r":
                    self.text_right(x + w - 2, self.y, cell, 9, False, color)
                else:
                    self.text(x, self.y, cell, 9, False, color)
                x += w
            self.y -= 5
            self.line(LEFT, self.y, RIGHT, self.y, (0.95, 0.96, 0.97), 0.4)
            self.y -= 10
        self.y -= 4

    def finish(self, footer_left: str) -> bytes:
        n = len(self.pages)
        for i, ops in enumerate(self.pages, start=1):
            self.ops = ops
            self.line(LEFT, 44, RIGHT, 44)
            self.text(LEFT, 32, footer_left, 8, False, MUTED)
            self.text_right(RIGHT, 32, f"Página {i} de {n}", 8, False, MUTED)
        return self.render()


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


# ---------- informe ----------

def _stocktake_section(rep: Report, title: str, st):
    rep.section(title)
    if not st:
        rep.paragraph("Este turno no tiene recuento registrado.")
        return
    lines = st.get("lines", [])
    diffs = [l for l in lines if l.get("difference") is not None and abs(l["difference"]) > 1e-9]
    rep.kv("Productos contados", str(len(lines)))
    rep.kv("Productos con diferencia", str(len(diffs)), color=RED if diffs else GREEN)
    if st.get("finalized_by"):
        rep.kv("Contado por", st["finalized_by"])
    if not diffs:
        rep.paragraph("Todo el stock contado coincide con el esperado.")
        return
    rep.y -= 4
    rows, colors = [], []
    for l in diffs:
        d = l["difference"]
        rows.append([l["name"], l.get("category_label") or "", fmt_qty(l["expected"], l["unit"]),
                     fmt_qty(l["counted"], l["unit"]), ("+" if d > 0 else "") + fmt_qty(d, l["unit"])])
        colors.append([None, MUTED, None, None, RED if d < 0 else GREEN])
    rep.table([("Producto", 34, "l"), ("Sección", 22, "l"), ("Esperado", 14, "r"), ("Contado", 14, "r"), ("Diferencia", 16, "r")],
              rows, colors)
    rep.paragraph("El stock contado pasó a ser el stock del sistema al confirmar el recuento.")


def build_closing_pdf(session: dict, sales: list, recharges: list, movements: list,
                      opening_st, closing_st, club: str = "Weed Lemon Social Club") -> bytes:
    closed_local = as_local(session.get("closed_at"))
    subtitle = f"Turno de {session.get('opened_by', '-')}"
    if closed_local:
        subtitle += f" · {closed_local.strftime('%d/%m/%Y')}"
    rep = Report("Resumen de cierre de turno", subtitle, club)

    # Turno
    rep.section("Turno")
    rep.kv("Responsable del turno", session.get("opened_by") or "-", bold=True)
    rep.kv("Apertura", fmt_dt(session.get("opened_at")))
    rep.kv("Cierre", fmt_dt(session.get("closed_at")))
    rep.kv("Duración", fmt_duration(session.get("opened_at"), session.get("closed_at")))
    closed_by = session.get("closed_by") or "-"
    if session.get("supervised"):
        closed_by += " (supervisión de administrador)"
    rep.kv("Cerrado por", closed_by)

    # Efectivo
    cc = session.get("cash_count") or {}
    starting = session.get("starting_amount", 0) or 0
    rec_cash = [r for r in recharges if r.get("method", "efectivo") == "efectivo"]
    rec_total = sum(r["amount"] for r in rec_cash)
    entradas = sum(m["amount"] for m in movements if m["type"] == "in")
    salidas = sum(m["amount"] for m in movements if m["type"] == "out")
    expected = cc.get("expected", session.get("expected_amount"))
    counted = cc.get("counted", session.get("counted_amount"))
    difference = cc.get("difference", session.get("difference"))
    rep.section("Arqueo de efectivo")
    rep.kv("Fondo inicial", fmt_cr(starting))
    rep.kv(f"Recargas de saldo en efectivo ({len(rec_cash)})", fmt_cr(rec_total))
    rep.kv("Entradas manuales", fmt_cr(entradas))
    rep.kv("Salidas manuales", fmt_cr(-salidas) if salidas else fmt_cr(0))
    if expected is not None:
        rep.kv("Efectivo esperado", fmt_cr(expected), bold=True)
    if counted is not None:
        rep.kv("Efectivo contado", fmt_cr(counted), bold=True)
    if difference is not None:
        label, color = diff_label(difference)
        rep.highlight(f"Diferencia de caja · {label}", fmt_cr(difference, sign=True), color)
    note = cc.get("reason") or session.get("notes")
    if note:
        rep.paragraph(f"Nota del arqueo: {note}", 9, INK)

    # Ventas
    total_sales = sum(s["total"] for s in sales)
    grams = sum(i["qty"] for s in sales for i in s["items"] if i.get("unit") == "g")
    units = sum(i["qty"] for s in sales for i in s["items"] if i.get("unit") != "g")
    oos = [s for s in sales if s.get("out_of_shift")]
    socios = {s.get("socio_id") for s in sales if s.get("socio_id")}
    rep.section("Ventas")
    rep.kv("Tickets", str(len(sales)))
    rep.kv("Total vendido (con saldo de socios)", fmt_cr(total_sales), bold=True)
    rep.kv("Socios atendidos", str(len(socios)))
    rep.kv("Gramos dispensados", fmt_qty(grams, "g"))
    rep.kv("Unidades vendidas", fmt_qty(units, "ud"))
    if oos:
        rep.kv(f"Ventas fuera de turno incorporadas ({len(oos)})", fmt_cr(sum(s["total"] for s in oos)))
    deuda = (session.get("totals") or {}).get("deuda_socios")
    if deuda is not None:
        rep.kv("Deuda total de socios al cierre", fmt_cr(deuda), color=RED if deuda > 0 else INK)
    rep.paragraph("Las ventas se cobran del saldo de los socios: no mueven efectivo. El efectivo entra con las recargas.")

    if sales:
        agg = {}
        for s in sales:
            for i in s["items"]:
                key = (i["name"], i.get("unit", "g"))
                row = agg.setdefault(key, {"qty": 0.0, "total": 0.0, "tickets": 0})
                row["qty"] += i["qty"]
                row["total"] += i["line_total"]
                row["tickets"] += 1
        rows = [[name, str(v["tickets"]), fmt_qty(v["qty"], unit), fmt_cr(v["total"])]
                for (name, unit), v in sorted(agg.items(), key=lambda kv: -kv[1]["total"])]
        rep.section("Productos vendidos")
        rep.table([("Producto", 46, "l"), ("Líneas", 12, "r"), ("Cantidad", 18, "r"), ("Total", 24, "r")], rows)

    if movements:
        rep.section("Movimientos manuales de caja")
        rows, colors = [], []
        for m in sorted(movements, key=lambda m: m["created_at"]):
            sign = 1 if m["type"] == "in" else -1
            rows.append([fmt_dt(m["created_at"], with_date=False), "Entrada" if sign > 0 else "Salida",
                         m.get("reason") or "", m.get("created_by") or "", fmt_cr(sign * m["amount"], sign=True)])
            colors.append([MUTED, None, None, MUTED, GREEN if sign > 0 else RED])
        rep.table([("Hora", 10, "l"), ("Tipo", 12, "l"), ("Motivo", 40, "l"), ("Por", 18, "l"), ("Importe", 20, "r")], rows, colors)

    _stocktake_section(rep, "Recuento de stock · apertura", opening_st)
    _stocktake_section(rep, "Recuento de stock · cierre", closing_st)

    generated = datetime.now(timezone.utc).astimezone(MADRID).strftime("%d/%m/%Y %H:%M")
    return rep.finish(f"{club} · Resumen de cierre · generado el {generated}")
