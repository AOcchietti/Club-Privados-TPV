"""Catálogo de bebidas y dulces para la demo, con ilustraciones propias (SVG genéricos, sin marcas)."""
from urllib.parse import quote

FOOD_DRINK_CATEGORIES = [
    {"key": "refrescos", "label": "Refrescos", "color": "emerald"},
    {"key": "dulces", "label": "Dulces y snacks", "color": "rose"},
]


def _shade(hex_color: str, factor: float) -> str:
    """Aclara (factor > 1) u oscurece (factor < 1) un color hexadecimal."""
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    if factor >= 1:
        r, g, b = (int(c + (255 - c) * (factor - 1)) for c in (r, g, b))
    else:
        r, g, b = (int(c * factor) for c in (r, g, b))
    return "#%02x%02x%02x" % (r, g, b)


def _uri(svg: str) -> str:
    return "data:image/svg+xml;utf8," + quote(svg)


def _frame(body: str, bg: str) -> str:
    return ("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 400 300'>"
            "<defs><linearGradient id='bg' x1='0' y1='0' x2='1' y2='1'>"
            f"<stop offset='0' stop-color='{_shade(bg, 1.85)}'/><stop offset='1' stop-color='{_shade(bg, 1.55)}'/></linearGradient></defs>"
            "<rect width='400' height='300' fill='url(#bg)'/>"
            # reducido y centrado para que no se corte en tarjetas más anchas que 4:3
            "<g transform='translate(200 155) scale(.8) translate(-200 -155)'>"
            "<ellipse cx='200' cy='266' rx='78' ry='10' fill='#0f172a' opacity='.12'/>"
            f"{body}</g></svg>")


def can(color: str) -> str:
    light, dark = _shade(color, 1.35), _shade(color, 0.7)
    body = ("<defs><linearGradient id='m' x1='0' x2='1'>"
            f"<stop offset='0' stop-color='{dark}'/><stop offset='.4' stop-color='{light}'/><stop offset='1' stop-color='{dark}'/>"
            "</linearGradient></defs>"
            "<rect x='150' y='46' width='100' height='16' rx='7' fill='#cbd5e1'/>"
            "<rect x='143' y='56' width='114' height='204' rx='16' fill='url(#m)'/>"
            "<rect x='150' y='252' width='100' height='12' rx='6' fill='#94a3b8'/>"
            "<rect x='143' y='118' width='114' height='62' fill='#ffffff' opacity='.85'/>"
            f"<circle cx='200' cy='149' r='18' fill='{color}'/>"
            "<rect x='158' y='70' width='10' height='170' rx='5' fill='#ffffff' opacity='.25'/>")
    return _uri(_frame(body, color))


def bottle(color: str) -> str:
    body = ("<rect x='184' y='34' width='32' height='22' rx='5' fill='#2563eb'/>"
            f"<path d='M188 56 h24 v24 q36 18 36 60 v110 q0 14 -14 14 h-68 q-14 0 -14 -14 v-110 q0 -42 36 -60z' fill='{_shade(color, 1.3)}' opacity='.9'/>"
            "<rect x='152' y='150' width='96' height='54' fill='#ffffff' opacity='.8'/>"
            f"<path d='M168 186 q16 -20 32 0 t32 0' stroke='{color}' stroke-width='6' fill='none'/>"
            "<rect x='164' y='100' width='9' height='140' rx='4' fill='#ffffff' opacity='.4'/>")
    return _uri(_frame(body, color))


def bar(color: str, stripe: str = "#ffffff") -> str:
    dark = _shade(color, 0.75)
    body = ("<g transform='rotate(-14 200 155)'>"
            f"<polygon points='92,112 104,104 104,206 92,198 100,180 92,163 100,146 92,129' fill='{dark}'/>"
            f"<polygon points='308,112 296,104 296,206 308,198 300,180 308,163 300,146 308,129' fill='{dark}'/>"
            f"<rect x='102' y='104' width='196' height='102' rx='10' fill='{color}'/>"
            f"<rect x='102' y='138' width='196' height='26' fill='{stripe}' opacity='.9'/>"
            f"<circle cx='200' cy='151' r='22' fill='{_shade(color, 1.25)}' stroke='{stripe}' stroke-width='4'/>"
            "</g>")
    return _uri(_frame(body, color))


def lollipop(color: str) -> str:
    body = ("<rect x='194' y='150' width='12' height='112' rx='6' fill='#f8fafc' stroke='#cbd5e1' stroke-width='2'/>"
            f"<circle cx='200' cy='120' r='62' fill='{color}'/>"
            f"<path d='M200 120 m-44 0 a44 44 0 1 1 88 0 a30 30 0 1 1 -60 0 a18 18 0 1 1 36 0' stroke='{_shade(color, 1.5)}' stroke-width='9' fill='none'/>")
    return _uri(_frame(body, color))


def _drink(name, price, color, desc="Lata 33 cl", stock=24, img=None):
    return {"name": name, "category": "refrescos", "price": price, "unit": "ud", "stock": stock, "thc": None, "cbd": None,
            "description": desc, "active": True, "image_url": img or can(color)}


def _sweet(name, price, color, desc, stock=20, stripe="#ffffff", img=None):
    return {"name": name, "category": "dulces", "price": price, "unit": "ud", "stock": stock, "thc": None, "cbd": None,
            "description": desc, "active": True, "image_url": img or bar(color, stripe)}


FOOD_DRINK_PRODUCTS = [
    _drink("Coca-Cola", 2.0, "#dc2626"),
    _drink("Coca-Cola Zero", 2.0, "#1f2937"),
    _drink("Fanta Naranja", 2.0, "#f97316"),
    _drink("Fanta Limón", 2.0, "#eab308"),
    _drink("Sprite", 2.0, "#16a34a"),
    _drink("Aquarius Limón", 2.0, "#0ea5e9"),
    _drink("Nestea Limón", 2.0, "#b45309"),
    _drink("Agua mineral", 1.0, "#38bdf8", desc="Botella 50 cl", img=bottle("#38bdf8")),
    _sweet("Kinder Bueno", 2.0, "#7c2d12", "Barrita de chocolate con avellana"),
    _sweet("Kinder Bueno White", 2.0, "#f5f5f4", "Barrita de chocolate blanco", stripe="#7c2d12"),
    _sweet("Kinder Country", 1.0, "#d6b88a", "Barrita de chocolate con cereales", stripe="#7c2d12"),
    _sweet("Kinder Delice", 1.5, "#92400e", "Bizcocho con chocolate"),
    _sweet("Twix", 1.5, "#ca8a04", "Galleta con caramelo y chocolate", stripe="#7c2d12"),
    _sweet("Snickers", 1.5, "#78350f", "Chocolate con cacahuete y caramelo", stripe="#1d4ed8"),
    _sweet("KitKat", 1.5, "#b91c1c", "Barquillo con chocolate"),
    _sweet("Chupa Chups", 0.5, "#ec4899", "Caramelo con palo", stock=50, img=lollipop("#ec4899")),
]
