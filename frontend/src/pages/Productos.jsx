import { useEffect, useState } from "react";
import api, { fmtEUR, catLabel } from "@/lib/api";
import { Package, Search, LayoutGrid, List } from "lucide-react";

export default function Productos() {
  const [products, setProducts] = useState([]);
  const [categories, setCategories] = useState([]);
  const [q, setQ] = useState("");
  const [cat, setCat] = useState(null);
  const [view, setView] = useState("grid");

  const load = () => {
    // El catálogo solo muestra productos activos; los inactivos se gestionan desde Gestión.
    api.get("/products", { params: { active_only: true } }).then((r) => setProducts(r.data)).catch(() => {});
    api.get("/categories").then((r) => setCategories(r.data)).catch(() => {});
  };
  useEffect(() => { load(); }, []);

  const filtered = products.filter(
    (p) => (!cat || p.category === cat) && (!q || p.name.toLowerCase().includes(q.toLowerCase()))
  );

  return (
    <div className="space-y-5" data-testid="productos-page">
      <div>
        <h1 className="font-display text-3xl sm:text-4xl font-bold tracking-tight text-slate-900">Productos</h1>
        <p className="text-sm text-slate-500 mt-1">{products.length} referencias en el catálogo del club.</p>
      </div>

      <div className="flex items-center gap-3 flex-wrap">
        <div className="relative flex-1 min-w-[220px] max-w-sm">
          <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Buscar…" data-testid="products-search-input"
            className="w-full pl-10 pr-4 py-2.5 rounded-xl border border-slate-300 bg-white focus:outline-none focus:ring-2 focus:ring-amber-400" />
        </div>
        <div className="flex bg-white border border-slate-200 rounded-xl p-1" data-testid="products-view-toggle">
          <button onClick={() => setView("grid")} data-testid="view-grid-btn"
            className={`px-3.5 py-1.5 rounded-lg text-xs font-bold flex items-center gap-1.5 transition-colors ${view === "grid" ? "bg-slate-900 text-white" : "text-slate-500 hover:text-slate-800"}`}>
            <LayoutGrid className="w-3.5 h-3.5" /> Fotos
          </button>
          <button onClick={() => setView("table")} data-testid="view-table-btn"
            className={`px-3.5 py-1.5 rounded-lg text-xs font-bold flex items-center gap-1.5 transition-colors ${view === "table" ? "bg-slate-900 text-white" : "text-slate-500 hover:text-slate-800"}`}>
            <List className="w-3.5 h-3.5" /> Lista
          </button>
        </div>
      </div>

      <div className="flex gap-2 flex-wrap" data-testid="products-category-filters">
        {[{ key: null, label: "Todas" }, ...categories].map((c) => (
          <button
            key={c.label}
            onClick={() => setCat(c.key)}
            data-testid={`products-filter-${c.key || "todas"}`}
            className={`px-3.5 py-2 rounded-full text-xs font-bold border transition-colors ${
              cat === c.key ? "bg-slate-900 text-white border-slate-900" : "bg-white text-slate-600 border-slate-200 hover:border-slate-400"
            }`}
          >
            {c.label}
          </button>
        ))}
      </div>

      {view === "grid" ? (
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4" data-testid="products-grid">
        {filtered.map((p) => (
          <div key={p.id} className="card-soft overflow-hidden group flex flex-col" data-testid={`product-card-${p.id}`}>
            <div className="relative h-44 bg-gradient-to-br from-amber-50 to-emerald-50 overflow-hidden">
              {p.image_url ? (
                <img src={p.image_url} alt={p.name} loading="lazy"
                  className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300" />
              ) : (
                <div className="w-full h-full flex items-center justify-center">
                  <Package className="w-10 h-10 text-amber-300" />
                </div>
              )}
              <span className="absolute bottom-2.5 left-2.5 text-[10px] font-bold px-2 py-0.5 rounded-full bg-white/85 backdrop-blur-sm text-slate-700 border border-white">
                {catLabel(categories, p.category)}
              </span>
            </div>
            <div className="p-3.5 flex flex-col flex-1">
              <p className="font-display font-bold text-slate-900 leading-tight">{p.name}</p>
              <p className="text-xs text-slate-400 mt-0.5 truncate">
                {p.thc != null ? `THC ${p.thc}%${p.cbd ? ` · CBD ${p.cbd}%` : ""}` : (p.description || "")}
              </p>
              <div className="mt-auto pt-3">
                <p className="font-display text-xl font-extrabold text-amber-600">
                  {fmtEUR(p.price)}<span className="text-xs font-semibold text-slate-400">/{p.unit}</span>
                </p>
              </div>
            </div>
          </div>
        ))}
        {filtered.length === 0 && (
          <p className="col-span-full text-sm text-slate-400 py-10 text-center">No hay productos que mostrar.</p>
        )}
      </div>
      ) : (
      <div className="card-soft overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm" data-testid="products-table">
            <thead>
              <tr className="text-left text-xs uppercase tracking-wider text-slate-500 border-b border-slate-200 bg-slate-50/60">
                <th className="px-4 py-3">Producto</th>
                <th className="px-4 py-3">Categoría</th>
                <th className="px-4 py-3 text-right">Precio</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((p) => (
                <tr key={p.id} className="border-b border-slate-100 hover:bg-amber-50/40 transition-colors" data-testid={`product-row-${p.id}`}>
                  <td className="px-4 py-3">
                    <p className="font-semibold text-slate-900">{p.name}</p>
                    {p.thc != null && <p className="text-xs text-slate-400">THC {p.thc}%{p.cbd ? ` · CBD ${p.cbd}%` : ""}</p>}
                  </td>
                  <td className="px-4 py-3 capitalize text-slate-600">{catLabel(categories, p.category)}</td>
                  <td className="px-4 py-3 text-right font-mono-num font-bold text-slate-900">{fmtEUR(p.price)}/{p.unit}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {filtered.length === 0 && (
            <div className="py-16 text-center text-slate-400">
              <Package className="w-8 h-8 mx-auto mb-2 opacity-50" />
              <p className="text-sm">No hay productos que mostrar.</p>
            </div>
          )}
        </div>
      </div>
      )}
    </div>
  );
}
