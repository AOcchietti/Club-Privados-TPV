import { useEffect, useMemo, useState } from "react";
import { useSearchParams, Link } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import { toast } from "sonner";
import api, { fmtEUR, apiError, catLabel, catStyle, fmtQty } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import TicketDialog from "@/components/TicketDialog";
import RechargeDialog from "@/components/RechargeDialog";
import { Search, ShoppingCart, Trash2, Plus, Minus, UserRound, Wallet, X, Loader2, Coins, Hourglass } from "lucide-react";

export default function POS() {
  const { user } = useAuth();
  const [products, setProducts] = useState([]);
  const [categories, setCategories] = useState([]);
  const [socios, setSocios] = useState([]);
  const [cartMode, setCartMode] = useState({});
  const [q, setQ] = useState("");
  const [cat, setCat] = useState(null);
  const [cart, setCart] = useState({});
  const [socio, setSocio] = useState(null);
  const [socioQ, setSocioQ] = useState("");
  const [showSocioList, setShowSocioList] = useState(false);
  const [cash, setCash] = useState(null);
  const [pendingOut, setPendingOut] = useState({ count: 0, total: 0 });
  const [checkingOut, setCheckingOut] = useState(false);
  const [lastSale, setLastSale] = useState(null);

  const [searchParams] = useSearchParams();
  const [rechargeOpen, setRechargeOpen] = useState(false);

  const load = () => {
    api.get("/products", { params: { active_only: true } }).then((r) => setProducts(r.data)).catch(() => {});
    api.get("/categories").then((r) => setCategories(r.data)).catch(() => {});
    api.get("/users", { params: { role: "socio" } }).then((r) => setSocios(r.data)).catch(() => {});
    api.get("/cash/current").then((r) => {
      setCash(r.data.session);
      setPendingOut(r.data.out_of_shift_pending || { count: 0, total: 0 });
    }).catch(() => setCash(null));
  };
  useEffect(load, []);

  useEffect(() => {
    const sid = searchParams.get("socio");
    if (sid) {
      api.get(`/users/${sid}`).then((r) => {
        if (r.data?.role === "socio") {
          setSocio(r.data);
          toast.success(`Venta asignada a ${r.data.name}`);
        }
      }).catch(() => {});
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const filtered = useMemo(
    () =>
      products.filter(
        (p) =>
          (!cat || p.category === cat) &&
          (!q || p.name.toLowerCase().includes(q.toLowerCase()))
      ),
    [products, q, cat]
  );

  const filteredSocios = useMemo(
    () =>
      socios.filter(
        (s) =>
          !socioQ ||
          s.name.toLowerCase().includes(socioQ.toLowerCase()) ||
          (s.member_number || "").toLowerCase().includes(socioQ.toLowerCase())
      ).slice(0, 6),
    [socios, socioQ]
  );

  const cartItems = Object.entries(cart)
    .map(([id, qty]) => ({ product: products.find((p) => p.id === id), qty }))
    .filter((i) => i.product);
  const total = cartItems.reduce((acc, i) => acc + i.product.price * i.qty, 0);

  const addToCart = (p) => {
    if (p.stock <= (cart[p.id] || 0)) {
      toast.warning(`Sin más stock de «${p.name}»`);
      return;
    }
    setCart((c) => ({ ...c, [p.id]: (c[p.id] || 0) + 1 }));
  };

  const addCredits = (p, credits) => {
    const grams = Math.round((credits / p.price) * 1000) / 1000;
    if (p.stock < (cart[p.id] || 0) + grams) {
      toast.warning(`Sin más stock de «${p.name}»`);
      return;
    }
    setCart((c) => ({ ...c, [p.id]: Math.round(((c[p.id] || 0) + grams) * 1000) / 1000 }));
    setCartMode((m) => ({ ...m, [p.id]: "cr" }));
  };

  const changeQty = (id, delta) => {
    setCart((c) => {
      const next = { ...c };
      const val = (next[id] || 0) + delta;
      if (val <= 0) delete next[id];
      else next[id] = Math.round(val * 1000) / 1000;
      return next;
    });
  };

  const [qtyDraft, setQtyDraft] = useState({});

  const setQtyManual = (p, raw, mode) => {
    if (raw === "" || isNaN(parseFloat(raw))) return;
    const val = parseFloat(raw);
    if (val < 0) return;
    const grams = mode === "cr" ? val / p.price : val;
    if (grams <= 0) return;
    if (grams > p.stock) {
      toast.warning(`Stock máximo de «${p.name}»: ${p.stock}${p.unit}`);
      setCart((c) => ({ ...c, [p.id]: p.stock }));
      return;
    }
    setCart((c) => ({ ...c, [p.id]: Math.round(grams * 1000) / 1000 }));
  };

  const commitQtyDraft = (p) => {
    const raw = qtyDraft[p.id];
    setQtyDraft((d) => { const n = { ...d }; delete n[p.id]; return n; });
    if (raw !== undefined && (raw === "" || isNaN(parseFloat(raw)) || parseFloat(raw) <= 0)) {
      setCart((c) => { const n = { ...c }; delete n[p.id]; return n; });
    }
  };

  const checkout = async () => {
    setCheckingOut(true);
    try {
      const res = await api.post("/sales", {
        items: cartItems.map((i) => ({ product_id: i.product.id, qty: i.qty })),
        payment_method: "saldo",
        socio_id: socio?.id || null,
      });
      setLastSale(res.data);
      setCart({});
      if (socio) {
        api.get(`/users/${socio.id}`).then((r) => setSocio(r.data)).catch(() => setSocio(null));
      }
      setSocioQ("");
      toast.success(
        res.data.out_of_shift
          ? `Ticket ${res.data.ticket_number} · ${fmtEUR(res.data.total)} · FUERA DE TURNO: se incorporará a la próxima caja`
          : `Ticket ${res.data.ticket_number} · ${fmtEUR(res.data.total)}`
      );
      load();
    } catch (e) {
      toast.error(apiError(e, "No se pudo registrar la venta"));
    } finally {
      setCheckingOut(false);
    }
  };

  return (
    <div className="space-y-4" data-testid="pos-page">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <h1 className="font-display text-3xl sm:text-4xl font-bold tracking-tight text-slate-900">Terminal de venta</h1>
          <p className="text-sm text-slate-500 mt-1">Toca un producto para añadirlo al ticket.</p>
        </div>
        {cash ? (
          cash.status === "closing" ? (
            <span className="badge-inactive" data-testid="pos-cash-status">Caja en proceso de cierre · ventas en pausa</span>
          ) : cash.status === "opening" ? (
            <span className="badge-inactive" data-testid="pos-cash-status">Caja en apertura (recuento de stock) · ventas en pausa</span>
          ) : (
            <span className="badge-active" data-testid="pos-cash-status">Caja abierta · fondo {fmtEUR(cash.starting_amount)}</span>
          )
        ) : (
          <div className="flex items-center gap-2 flex-wrap">
            <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-bold bg-sky-100 text-sky-800 border border-sky-200" data-testid="pos-cash-status">
              <Hourglass className="w-3.5 h-3.5" /> Sin turno abierto · las ventas quedan fuera de turno
            </span>
            <Link to="/caja" className="btn-outline text-amber-700 border-amber-300 bg-amber-50 py-1.5 text-xs" data-testid="pos-goto-cash-btn">
              <Wallet className="w-3.5 h-3.5" /> Abrir turno en Caja
            </Link>
          </div>
        )}
      </div>

      <div className="flex flex-col xl:flex-row gap-4 items-start">
        {/* Catálogo */}
        <div className="flex-1 w-full space-y-3">
          <div className="relative">
            <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Buscar producto…"
              data-testid="pos-search-input"
              className="w-full pl-10 pr-4 py-3 rounded-xl border border-slate-300 bg-white focus:outline-none focus:ring-2 focus:ring-amber-400"
            />
          </div>
          <div className="flex gap-2 flex-wrap" data-testid="pos-category-filters">
            {[{ key: null, label: "Todo" }, ...categories].map((c) => (
              <button
                key={c.label}
                onClick={() => setCat(c.key)}
                data-testid={`pos-filter-${c.key || "todo"}`}
                className={`px-3.5 py-2 rounded-full text-xs font-bold transition-colors border ${
                  cat === c.key
                    ? "bg-slate-900 text-white border-slate-900"
                    : "bg-white text-slate-600 border-slate-200 hover:border-slate-400"
                }`}
              >
                {c.label}
              </button>
            ))}
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
            {filtered.map((p) => {
              const out = p.stock <= 0;
              return (
                <motion.div
                  key={p.id}
                  layout
                  whileTap={{ scale: 0.98 }}
                  onClick={() => !out && addToCart(p)}
                  role="button"
                  data-testid={`pos-product-card-${p.id}`}
                  className={`pos-card text-left min-h-[110px] overflow-hidden ${out ? "opacity-45 cursor-not-allowed" : "hover:-translate-y-0.5"}`}
                >
                  {p.image_url && (
                    <div className="h-20 -mx-3 -mt-3 mb-2.5 overflow-hidden rounded-t-xl">
                      <img src={p.image_url} alt={p.name} className="w-full h-full object-cover" loading="lazy" />
                    </div>
                  )}
                  <div>
                    <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full border ${catStyle(categories, p.category)}`}>
                      {catLabel(categories, p.category)}
                    </span>
                    <p className="font-display font-bold text-slate-900 mt-2 leading-tight">{p.name}</p>
                    <p className="text-[11px] text-slate-400 mt-0.5">
                      {p.thc ? `THC ${p.thc}% · ` : ""}stock {fmtQty(p.stock)}{p.unit}
                    </p>
                  </div>
                  <p className="font-display text-xl font-extrabold text-amber-600 mt-2">
                    {fmtEUR(p.price)}<span className="text-xs font-semibold text-slate-400">/{p.unit}</span>
                  </p>
                  {p.unit === "g" && (
                    <div className="mt-2 pt-2 border-t border-amber-100/80" onClick={(e) => e.stopPropagation()}>
                      <p className="text-[10px] text-slate-400 mb-1.5">10 Cr ≈ {Math.round((10 / p.price) * 100) / 100} g</p>
                      <div className="flex gap-1">
                        {[5, 10, 20].map((cr) => (
                          <button
                            key={cr}
                            onClick={(e) => { e.stopPropagation(); addCredits(p, cr); }}
                            data-testid={`pos-quick-${cr}-${p.id}`}
                            className="flex-1 text-[10px] font-bold py-1 rounded-md bg-amber-100 text-amber-800 hover:bg-amber-200 border border-amber-200 transition-colors"
                          >
                            +{cr} Cr
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
                </motion.div>
              );
            })}
            {filtered.length === 0 && (
              <p className="col-span-full text-sm text-slate-400 py-10 text-center">Ningún producto coincide con la búsqueda.</p>
            )}
          </div>
        </div>

        {/* Carrito */}
        <div className="w-full xl:w-[380px] xl:sticky xl:top-6 bg-white/90 backdrop-blur rounded-2xl border border-amber-200/70 shadow-xl p-5 space-y-4" data-testid="pos-cart">
          <h2 className="font-display text-lg font-bold text-slate-900 flex items-center gap-2">
            <ShoppingCart className="w-5 h-5 text-amber-500" /> Ticket actual
          </h2>

          {/* Selector de socio */}
          <div className="relative">
            {socio ? (
              <div className="bg-emerald-50 border border-emerald-200 rounded-xl px-3.5 py-2.5 space-y-2" data-testid="pos-selected-socio">
                <div className="flex items-center justify-between">
                  <span className="text-sm font-semibold text-emerald-900 flex items-center gap-2">
                    <UserRound className="w-4 h-4" /> {socio.name}
                    <span className="text-xs text-emerald-600 font-mono-num">{socio.member_number}</span>
                  </span>
                  <button onClick={() => setSocio(null)} className="text-emerald-500 hover:text-emerald-700" data-testid="pos-clear-socio-btn">
                    <X className="w-4 h-4" />
                  </button>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-xs text-emerald-700 font-medium">
                    Saldo: <span className="font-mono-num font-bold" data-testid="pos-socio-balance">{fmtEUR(socio.balance || 0)}</span>
                  </span>
                  <button onClick={() => setRechargeOpen(true)} className="text-xs font-bold text-emerald-700 hover:text-emerald-900 flex items-center gap-1 bg-white/70 border border-emerald-200 rounded-lg px-2 py-1" data-testid="pos-recharge-btn">
                    <Coins className="w-3.5 h-3.5" /> Recargar
                  </button>
                </div>
              </div>
            ) : (
              <>
                <input
                  value={socioQ}
                  onChange={(e) => { setSocioQ(e.target.value); setShowSocioList(true); }}
                  onFocus={() => setShowSocioList(true)}
                  placeholder="Asignar socio (opcional)…"
                  data-testid="pos-socio-search-input"
                  className="w-full px-3.5 py-2.5 rounded-xl border border-slate-300 bg-white text-sm focus:outline-none focus:ring-2 focus:ring-emerald-400"
                />
                {showSocioList && socioQ && (
                  <div className="absolute z-20 mt-1 w-full bg-white border border-slate-200 rounded-xl shadow-lg overflow-hidden">
                    {filteredSocios.map((s) => (
                      <button
                        key={s.id}
                        onClick={() => { setSocio(s); setShowSocioList(false); }}
                        data-testid={`pos-socio-option-${s.id}`}
                        className="w-full text-left px-3.5 py-2.5 text-sm hover:bg-emerald-50 flex justify-between"
                      >
                        <span className="font-medium text-slate-800">{s.name}</span>
                        <span className="text-xs text-slate-400 font-mono-num">{s.member_number}</span>
                      </button>
                    ))}
                    {filteredSocios.length === 0 && <p className="px-3.5 py-2.5 text-xs text-slate-400">Sin resultados</p>}
                  </div>
                )}
              </>
            )}
          </div>

          <div className="space-y-2 max-h-64 overflow-y-auto pr-1">
            <AnimatePresence>
              {cartItems.map(({ product: p, qty }) => {
                const mode = p.unit === "g" ? cartMode[p.id] || "g" : "ud";
                const credits = Math.round(qty * p.price * 100) / 100;
                const step = mode === "cr" ? 5 / p.price : mode === "g" ? 0.5 : 1;
                return (
                  <motion.div
                    key={p.id}
                    initial={{ opacity: 0, x: 12 }}
                    animate={{ opacity: 1, x: 0 }}
                    exit={{ opacity: 0, x: -12 }}
                    className="bg-amber-50/70 border border-amber-100 rounded-xl px-3 py-2"
                    data-testid={`cart-item-${p.id}`}
                  >
                    <div className="flex items-center gap-2">
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-semibold text-slate-800 truncate">{p.name}</p>
                        <p className="text-xs text-slate-400 font-mono-num">
                          {mode === "cr" ? `≈ ${qty} g` : `${fmtEUR(p.price)}/${p.unit}`}
                        </p>
                      </div>
                      <div className="flex items-center gap-1">
                        <button onClick={() => changeQty(p.id, -step)} className="w-7 h-7 rounded-lg bg-white border border-slate-200 flex items-center justify-center hover:bg-slate-50" data-testid={`cart-minus-${p.id}`}>
                          <Minus className="w-3.5 h-3.5" />
                        </button>
                        <div className="relative">
                          <input
                            type="number"
                            min="0"
                            step="any"
                            value={qtyDraft[p.id] !== undefined ? qtyDraft[p.id] : (mode === "cr" ? credits : qty)}
                            onFocus={() => setQtyDraft((d) => ({ ...d, [p.id]: String(mode === "cr" ? credits : qty) }))}
                            onChange={(e) => {
                              setQtyDraft((d) => ({ ...d, [p.id]: e.target.value }));
                              setQtyManual(p, e.target.value, mode);
                            }}
                            onBlur={() => commitQtyDraft(p)}
                            data-testid={`cart-qty-input-${p.id}`}
                            className="w-20 text-center text-sm font-bold font-mono-num bg-white border border-slate-200 rounded-lg py-1 pr-7 focus:outline-none focus:ring-2 focus:ring-amber-400"
                          />
                          <span className="absolute right-1.5 top-1/2 -translate-y-1/2 text-[10px] font-bold text-slate-400 pointer-events-none">
                            {mode === "cr" ? "Cr" : p.unit}
                          </span>
                        </div>
                        <button onClick={() => changeQty(p.id, step)} className="w-7 h-7 rounded-lg bg-white border border-slate-200 flex items-center justify-center hover:bg-slate-50" data-testid={`cart-plus-${p.id}`}>
                          <Plus className="w-3.5 h-3.5" />
                        </button>
                      </div>
                      <button onClick={() => setCart((c) => { const n = { ...c }; delete n[p.id]; return n; })} className="text-slate-300 hover:text-red-500" data-testid={`cart-remove-${p.id}`}>
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </div>
                    {p.unit === "g" && (
                      <div className="flex gap-1 mt-1.5">
                        {["g", "cr"].map((m) => (
                          <button
                            key={m}
                            onClick={() => setCartMode((prev) => ({ ...prev, [p.id]: m }))}
                            data-testid={`cart-mode-${m}-${p.id}`}
                            className={`text-[10px] font-bold px-2 py-0.5 rounded-md border transition-colors ${
                              mode === m ? "bg-slate-900 text-white border-slate-900" : "bg-white text-slate-500 border-slate-200 hover:border-slate-400"
                            }`}
                          >
                            {m === "g" ? "por gramos" : "por Cr"}
                          </button>
                        ))}
                        {mode === "g" && <span className="text-[10px] text-slate-400 ml-auto self-center font-mono-num">= {fmtEUR(credits)}</span>}
                      </div>
                    )}
                  </motion.div>
                );
              })}
            </AnimatePresence>
            {cartItems.length === 0 && (
              <p className="text-sm text-slate-400 text-center py-6">El ticket está vacío. Añade productos del catálogo.</p>
            )}
          </div>

          {!socio ? (
            <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-xl px-3 py-2" data-testid="pos-socio-required">
              Asigna un socio arriba para cobrar: el importe se descuenta de su saldo.
            </p>
          ) : (
            <div
              className={`text-xs rounded-xl px-3 py-2 border flex justify-between ${
                (socio.balance || 0) - total < 0
                  ? "bg-red-50 border-red-200 text-red-600"
                  : "bg-emerald-50 border-emerald-200 text-emerald-700"
              }`}
              data-testid="pos-balance-after"
            >
              <span>Saldo de {socio.name} tras la compra{(socio.balance || 0) - total < 0 ? " (quedará en negativo)" : ""}</span>
              <span className="font-mono-num font-bold">{fmtEUR(Math.round(((socio.balance || 0) - total) * 100) / 100)}</span>
            </div>
          )}

          <div className="border-t border-dashed border-slate-300 pt-3 flex justify-between items-center">
            <span className="text-xs uppercase tracking-wider font-semibold text-slate-500">Total</span>
            <span className="font-display text-3xl font-extrabold text-amber-600" data-testid="pos-cart-total">{fmtEUR(total)}</span>
          </div>

          {!cash && (
            <p className="text-xs text-sky-800 bg-sky-50 border border-sky-200 rounded-xl px-3 py-2 flex items-center gap-2" data-testid="pos-out-of-shift-note">
              <Hourglass className="w-3.5 h-3.5 shrink-0" />
              Venta fuera de turno: no se descuenta stock ahora; se incorporará a la próxima caja al abrirla.
              {pendingOut.count > 0 && ` Ya hay ${pendingOut.count} pendientes (${fmtEUR(pendingOut.total)}).`}
            </p>
          )}

          <button
            onClick={checkout}
            disabled={cartItems.length === 0 || checkingOut || !socio}
            className="btn-secondary w-full py-3.5 text-base"
            data-testid="cart-checkout-button"
          >
            {checkingOut ? <Loader2 className="w-5 h-5 animate-spin" /> : null}
            {socio ? `Cobrar del saldo ${total > 0 ? `· ${fmtEUR(total)}` : ""}` : "Asigna un socio para cobrar"}
          </button>
        </div>
      </div>

      <TicketDialog sale={lastSale} open={!!lastSale} onClose={() => setLastSale(null)} />
      <RechargeDialog socio={socio} open={rechargeOpen} onClose={() => setRechargeOpen(false)} onDone={(u) => setSocio(u)} />
    </div>
  );
}
