import { useEffect, useState } from "react";
import { toast } from "sonner";
import api, { fmtEUR, apiError, catLabel, catStyle, CATEGORY_DOTS, uploadPhoto, fmtQty } from "@/lib/api";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger } from "@/components/ui/alert-dialog";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Package, Plus, Pencil, Trash2, Power, Search, Upload, Tag, Loader2, LayoutGrid, List, PackageSearch } from "lucide-react";

const EMPTY = { name: "", category: "", price: "", unit: "g", stock: "", thc: "", cbd: "", description: "", image_url: "", active: true };

function ProductDialog({ open, onClose, product, categories, onSaved }) {
  const [form, setForm] = useState(EMPTY);
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState(false);

  useEffect(() => {
    if (open) {
      setForm(
        product
          ? { ...EMPTY, ...product, thc: product.thc ?? "", cbd: product.cbd ?? "", image_url: product.image_url || "" }
          : { ...EMPTY, category: categories[0]?.key || "" }
      );
    }
  }, [open, product, categories]);

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const handleFile = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      const url = await uploadPhoto(file);
      setForm((f) => ({ ...f, image_url: url }));
      toast.success("Foto subida correctamente");
    } catch (err) {
      toast.error(apiError(err, "No se pudo subir la foto"));
    } finally {
      setUploading(false);
      e.target.value = "";
    }
  };

  const save = async () => {
    setSaving(true);
    const base = {
      name: form.name,
      category: form.category,
      price: parseFloat(form.price) || 0,
      thc: form.thc === "" ? null : parseFloat(form.thc),
      cbd: form.cbd === "" ? null : parseFloat(form.cbd),
      description: form.description || null,
      image_url: form.image_url || null,
      active: form.active !== false,
    };
    try {
      if (product) {
        await api.patch(`/products/${product.id}`, base);
        toast.success("Producto actualizado");
      } else {
        await api.post("/products", { ...base, unit: form.unit, initial_stock: parseFloat(form.stock) || 0 });
        toast.success("Producto creado");
      }
      onSaved();
      onClose();
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onClose}>
      <DialogContent className="max-w-md max-h-[90vh] overflow-y-auto" data-testid="product-dialog">
        <DialogHeader>
          <DialogTitle className="font-display">{product ? "Editar producto" : "Nuevo producto"}</DialogTitle>
        </DialogHeader>
        <div className="grid grid-cols-2 gap-3">
          <div className="col-span-2">
            <label className="text-xs font-semibold uppercase tracking-wider text-slate-500 block mb-1">Nombre</label>
            <input value={form.name} onChange={set("name")} data-testid="product-name-input" className="w-full px-3.5 py-2.5 rounded-xl border border-slate-300 focus:outline-none focus:ring-2 focus:ring-amber-400" />
          </div>
          <div>
            <label className="text-xs font-semibold uppercase tracking-wider text-slate-500 block mb-1">Categoría</label>
            <select value={form.category} onChange={set("category")} data-testid="product-category-select" className="w-full px-3.5 py-2.5 rounded-xl border border-slate-300 bg-white focus:outline-none focus:ring-2 focus:ring-amber-400">
              {categories.map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}
            </select>
          </div>
          <div>
            <label className="text-xs font-semibold uppercase tracking-wider text-slate-500 block mb-1">Se vende por</label>
            <select value={form.unit} onChange={set("unit")} disabled={!!product} data-testid="product-unit-select" className="w-full px-3.5 py-2.5 rounded-xl border border-slate-300 bg-white focus:outline-none focus:ring-2 focus:ring-amber-400 disabled:bg-slate-50 disabled:text-slate-400">
              <option value="g">Gramos</option>
              <option value="ud">Unidades</option>
            </select>
            {product && <p className="text-[11px] text-slate-400 mt-1">La unidad no se puede cambiar tras el alta.</p>}
          </div>
          <div>
            <label className="text-xs font-semibold uppercase tracking-wider text-slate-500 block mb-1">Precio (créditos/{form.unit})</label>
            <input type="number" step="0.5" min="0" value={form.price} onChange={set("price")} data-testid="product-price-input" className="w-full px-3.5 py-2.5 rounded-xl border border-slate-300 focus:outline-none focus:ring-2 focus:ring-amber-400" />
          </div>
          {product ? (
            <div>
              <label className="text-xs font-semibold uppercase tracking-wider text-slate-500 block mb-1">Stock actual</label>
              <div className="w-full px-3.5 py-2.5 rounded-xl border border-slate-200 bg-slate-50 text-slate-600 font-mono-num font-bold" data-testid="product-stock-readonly">
                {fmtQty(product.stock)}{product.unit}
              </div>
              <p className="text-[11px] text-slate-400 mt-1">Se modifica con entradas, mermas o ajustes.</p>
            </div>
          ) : (
            <div>
              <label className="text-xs font-semibold uppercase tracking-wider text-slate-500 block mb-1">Stock inicial ({form.unit})</label>
              <input type="number" step="0.5" min="0" value={form.stock} onChange={set("stock")} data-testid="product-stock-input" className="w-full px-3.5 py-2.5 rounded-xl border border-slate-300 focus:outline-none focus:ring-2 focus:ring-amber-400" />
            </div>
          )}
          <div>
            <label className="text-xs font-semibold uppercase tracking-wider text-slate-500 block mb-1">THC %</label>
            <input type="number" step="0.1" min="0" value={form.thc} onChange={set("thc")} className="w-full px-3.5 py-2.5 rounded-xl border border-slate-300 focus:outline-none focus:ring-2 focus:ring-amber-400" />
          </div>
          <div>
            <label className="text-xs font-semibold uppercase tracking-wider text-slate-500 block mb-1">CBD %</label>
            <input type="number" step="0.1" min="0" value={form.cbd} onChange={set("cbd")} className="w-full px-3.5 py-2.5 rounded-xl border border-slate-300 focus:outline-none focus:ring-2 focus:ring-amber-400" />
          </div>
          <div className="col-span-2">
            <label className="text-xs font-semibold uppercase tracking-wider text-slate-500 block mb-1">Descripción</label>
            <input value={form.description || ""} onChange={set("description")} className="w-full px-3.5 py-2.5 rounded-xl border border-slate-300 focus:outline-none focus:ring-2 focus:ring-amber-400" />
          </div>
          <div className="col-span-2">
            <label className="text-xs font-semibold uppercase tracking-wider text-slate-500 block mb-1">Foto del producto</label>
            <label className={`btn-outline w-full cursor-pointer ${uploading ? "opacity-60 pointer-events-none" : ""}`} data-testid="product-photo-upload-btn">
              {uploading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Upload className="w-4 h-4" />}
              {uploading ? "Subiendo foto…" : "Subir foto desde el dispositivo"}
              <input type="file" accept="image/*" className="hidden" onChange={handleFile} data-testid="product-photo-input" />
            </label>
          </div>
          <div className="col-span-2">
            <label className="text-xs font-semibold uppercase tracking-wider text-slate-500 block mb-1">…o pega una URL</label>
            <input value={form.image_url || ""} onChange={set("image_url")} placeholder="https://…" data-testid="product-image-input" className="w-full px-3.5 py-2.5 rounded-xl border border-slate-300 focus:outline-none focus:ring-2 focus:ring-amber-400" />
          </div>
          {form.image_url && (
            <img src={form.image_url} alt="Vista previa" className="col-span-2 h-32 w-full object-cover rounded-xl border border-slate-200" data-testid="product-image-preview" />
          )}
        </div>
        <button onClick={save} disabled={saving || !form.name || !form.category} className="btn-primary w-full mt-2" data-testid="product-save-button">
          {saving ? "Guardando…" : product ? "Guardar cambios" : "Crear producto"}
        </button>
      </DialogContent>
    </Dialog>
  );
}

function CategoryDialog({ open, onClose, category, onSaved }) {
  const [label, setLabel] = useState("");
  const [color, setColor] = useState("emerald");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open) {
      setLabel(category?.label || "");
      setColor(category?.color || "emerald");
    }
  }, [open, category]);

  const save = async () => {
    setSaving(true);
    try {
      if (category) {
        await api.patch(`/categories/${category.id}`, { label, color });
        toast.success("Categoría actualizada");
      } else {
        await api.post("/categories", { label, color });
        toast.success("Categoría creada");
      }
      onSaved();
      onClose();
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onClose}>
      <DialogContent className="max-w-xs" data-testid="category-dialog">
        <DialogHeader>
          <DialogTitle className="font-display">{category ? "Editar categoría" : "Nueva categoría"}</DialogTitle>
        </DialogHeader>
        <label className="text-xs font-semibold uppercase tracking-wider text-slate-500">Nombre</label>
        <input value={label} onChange={(e) => setLabel(e.target.value)} data-testid="category-name-input" className="w-full px-3.5 py-2.5 rounded-xl border border-slate-300 focus:outline-none focus:ring-2 focus:ring-amber-400" />
        <label className="text-xs font-semibold uppercase tracking-wider text-slate-500">Color</label>
        <div className="flex gap-2 flex-wrap" data-testid="category-color-picker">
          {Object.keys(CATEGORY_DOTS).map((c) => (
            <button
              key={c}
              onClick={() => setColor(c)}
              data-testid={`category-color-${c}`}
              className={`w-8 h-8 rounded-full ${CATEGORY_DOTS[c]} transition-transform ${color === c ? "ring-2 ring-offset-2 ring-slate-800 scale-110" : "hover:scale-105"}`}
            />
          ))}
        </div>
        <button onClick={save} disabled={saving || !label.trim()} className="btn-primary w-full" data-testid="category-save-button">
          {saving ? "Guardando…" : category ? "Guardar cambios" : "Crear categoría"}
        </button>
      </DialogContent>
    </Dialog>
  );
}

function StockDialog({ product, open, onClose, onSaved }) {
  const [type, setType] = useState("entrada");
  const [qty, setQty] = useState("");
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open) {
      setType("entrada");
      setQty("");
      setReason("");
    }
  }, [open]);

  if (!product) return null;

  const val = parseFloat(qty) || 0;
  const signed = type === "ajuste" ? Math.round((val - (product.stock || 0)) * 1000) / 1000 : type === "merma" ? -val : val;
  const newStock = Math.round(((product.stock || 0) + signed) * 1000) / 1000;

  const save = async () => {
    setSaving(true);
    try {
      await api.post(`/products/${product.id}/stock`, { type, qty: type === "ajuste" ? signed : val, reason });
      toast.success("Movimiento de inventario registrado");
      onSaved();
      onClose();
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onClose}>
      <DialogContent className="max-w-xs" data-testid="stock-dialog">
        <DialogHeader>
          <DialogTitle className="font-display">Movimiento de inventario</DialogTitle>
        </DialogHeader>
        <p className="text-sm text-slate-600 -mt-1">
          {product.name} · stock actual{" "}
          <span className="font-mono-num font-bold text-slate-900">{fmtQty(product.stock)}{product.unit}</span>
        </p>
        <div className="flex gap-2">
          {["entrada", "merma", "ajuste"].map((t) => (
            <button key={t} onClick={() => setType(t)} data-testid={`stock-type-${t}`}
              className={`flex-1 py-2 rounded-xl text-xs font-bold capitalize border transition-colors ${type === t ? "bg-slate-900 text-white border-slate-900" : "bg-white text-slate-600 border-slate-200 hover:border-slate-400"}`}>
              {t}
            </button>
          ))}
        </div>
        <label className="text-xs font-semibold uppercase tracking-wider text-slate-500">
          {type === "entrada" ? `Cantidad que entra (${product.unit})` : type === "merma" ? `Cantidad que sale (${product.unit})` : `Stock real contado (${product.unit})`}
        </label>
        <input type="number" min="0" step="any" value={qty} onChange={(e) => setQty(e.target.value)} data-testid="stock-qty-input"
          className="w-full px-4 py-3 rounded-xl border border-slate-300 font-mono-num font-bold text-center focus:outline-none focus:ring-2 focus:ring-amber-400" />
        <label className="text-xs font-semibold uppercase tracking-wider text-slate-500">
          {type === "entrada" ? "Motivo (opcional)" : "Motivo (obligatorio)"}
        </label>
        <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder={type === "entrada" ? "Ej: entrada de proveedor" : "Ej: producto dañado, recuento…"} data-testid="stock-reason-input"
          className="w-full px-4 py-3 rounded-xl border border-slate-300 focus:outline-none focus:ring-2 focus:ring-amber-400" />
        {qty !== "" && (
          <div className="bg-slate-50 border border-slate-200 rounded-xl px-4 py-2.5 text-sm flex justify-between">
            <span className="text-slate-600">Stock resultante</span>
            <span className={`font-mono-num font-bold ${newStock < 0 ? "text-red-600" : "text-slate-900"}`} data-testid="stock-new-preview">{newStock}{product.unit}</span>
          </div>
        )}
        <button onClick={save} disabled={saving || qty === "" || (type !== "entrada" && !reason.trim()) || newStock < 0} className="btn-primary w-full" data-testid="stock-save-btn">
          {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
          Registrar movimiento
        </button>
      </DialogContent>
    </Dialog>
  );
}

export default function Gestion() {
  const [products, setProducts] = useState([]);
  const [categories, setCategories] = useState([]);
  const [q, setQ] = useState("");
  const [cat, setCat] = useState(null);
  const [view, setView] = useState("table");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [catDialogOpen, setCatDialogOpen] = useState(false);
  const [editingCat, setEditingCat] = useState(null);
  const [stockFor, setStockFor] = useState(null);

  const load = () => {
    api.get("/products").then((r) => setProducts(r.data)).catch(() => {});
    api.get("/categories").then((r) => setCategories(r.data)).catch(() => {});
  };
  useEffect(() => { load(); }, []);

  const toggle = async (p) => {
    try {
      await api.patch(`/products/${p.id}/toggle`);
      toast.success(`«${p.name}» ${p.active ? "desactivado" : "activado"}`);
      load();
    } catch (e) {
      toast.error(apiError(e));
    }
  };

  const remove = async (p) => {
    try {
      await api.delete(`/products/${p.id}`);
      toast.success(`«${p.name}» eliminado`);
      load();
    } catch (e) {
      toast.error(apiError(e));
    }
  };

  const removeCat = async (c) => {
    try {
      await api.delete(`/categories/${c.id}`);
      toast.success(`Categoría «${c.label}» eliminada`);
      load();
    } catch (e) {
      toast.error(apiError(e));
    }
  };

  const filtered = products
    .filter((p) => (!cat || p.category === cat) && (!q || p.name.toLowerCase().includes(q.toLowerCase())))
    .sort((a, b) => (a.active === b.active ? 0 : a.active ? -1 : 1));
  const productCount = (key) => products.filter((p) => p.category === key).length;

  return (
    <div className="space-y-5" data-testid="gestion-page">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <h1 className="font-display text-3xl sm:text-4xl font-bold tracking-tight text-slate-900">Gestión</h1>
          <p className="text-sm text-slate-500 mt-1">Crea y administra productos y categorías del catálogo.</p>
        </div>
        <div className="flex gap-2">
          <button onClick={() => { setEditingCat(null); setCatDialogOpen(true); }} className="btn-outline" data-testid="category-new-button">
            <Tag className="w-4 h-4" /> Nueva categoría
          </button>
          <button onClick={() => { setEditing(null); setDialogOpen(true); }} className="btn-primary" data-testid="product-new-button">
            <Plus className="w-4 h-4" /> Nuevo producto
          </button>
        </div>
      </div>

      <Tabs defaultValue="productos">
        <TabsList className="bg-white border border-slate-200 rounded-xl p-1">
          <TabsTrigger value="productos" data-testid="tab-gestion-productos" className="rounded-lg">Productos ({products.length})</TabsTrigger>
          <TabsTrigger value="categorias" data-testid="tab-gestion-categorias" className="rounded-lg">Categorías ({categories.length})</TabsTrigger>
        </TabsList>

        <TabsContent value="productos" className="mt-4 space-y-4">
          <div className="flex items-center gap-3 flex-wrap">
            <div className="relative flex-1 min-w-[220px] max-w-sm">
              <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
              <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Buscar…" data-testid="gestion-search-input"
                className="w-full pl-10 pr-4 py-2.5 rounded-xl border border-slate-300 bg-white focus:outline-none focus:ring-2 focus:ring-amber-400" />
            </div>
            <div className="flex bg-white border border-slate-200 rounded-xl p-1" data-testid="gestion-view-toggle">
              <button onClick={() => setView("grid")} data-testid="gestion-view-grid-btn"
                className={`px-3.5 py-1.5 rounded-lg text-xs font-bold flex items-center gap-1.5 transition-colors ${view === "grid" ? "bg-slate-900 text-white" : "text-slate-500 hover:text-slate-800"}`}>
                <LayoutGrid className="w-3.5 h-3.5" /> Fotos
              </button>
              <button onClick={() => setView("table")} data-testid="gestion-view-table-btn"
                className={`px-3.5 py-1.5 rounded-lg text-xs font-bold flex items-center gap-1.5 transition-colors ${view === "table" ? "bg-slate-900 text-white" : "text-slate-500 hover:text-slate-800"}`}>
                <List className="w-3.5 h-3.5" /> Lista
              </button>
            </div>
          </div>

          <div className="flex gap-2 flex-wrap" data-testid="gestion-category-filters">
            {[{ key: null, label: "Todas" }, ...categories].map((c) => (
              <button
                key={c.label}
                onClick={() => setCat(c.key)}
                data-testid={`gestion-filter-${c.key || "todas"}`}
                className={`px-3.5 py-2 rounded-full text-xs font-bold border transition-colors ${
                  cat === c.key ? "bg-slate-900 text-white border-slate-900" : "bg-white text-slate-600 border-slate-200 hover:border-slate-400"
                }`}
              >
                {c.label}
              </button>
            ))}
          </div>

          {view === "grid" ? (
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4" data-testid="gestion-products-grid">
            {filtered.map((p) => (
              <div key={p.id} className={`card-soft overflow-hidden group flex flex-col ${p.active ? "" : "opacity-60"}`} data-testid={`gestion-product-card-${p.id}`}>
                <div className="relative h-40 bg-gradient-to-br from-amber-50 to-emerald-50 overflow-hidden">
                  {p.image_url ? (
                    <img src={p.image_url} alt={p.name} loading="lazy" className={`w-full h-full object-cover group-hover:scale-105 transition-transform duration-300 ${p.active ? "" : "grayscale"}`} />
                  ) : (
                    <div className="w-full h-full flex items-center justify-center">
                      <Package className="w-10 h-10 text-amber-300" />
                    </div>
                  )}
                  {!p.active && (
                    <span className="absolute top-2.5 right-2.5 badge-inactive" data-testid={`gestion-product-status-${p.id}`}>
                      Inactivo · no sale en el catálogo
                    </span>
                  )}
                  <span className={`absolute bottom-2.5 left-2.5 text-[10px] font-bold px-2 py-0.5 rounded-full border ${catStyle(categories, p.category)}`}>
                    {catLabel(categories, p.category)}
                  </span>
                </div>
                <div className="p-3.5 flex flex-col flex-1">
                  <p className="font-display font-bold text-slate-900 leading-tight">{p.name}</p>
                  <p className="text-xs text-slate-400 mt-0.5 truncate">
                    {p.thc != null ? `THC ${p.thc}%${p.cbd ? ` · CBD ${p.cbd}%` : ""}` : (p.description || "")}
                  </p>
                  <div className="mt-auto pt-3 flex items-end justify-between">
                    <p className="font-display text-xl font-extrabold text-amber-600">
                      {fmtEUR(p.price)}<span className="text-xs font-semibold text-slate-400">/{p.unit}</span>
                    </p>
                    <p className={`font-mono-num text-sm font-bold ${p.stock <= 0 ? "text-red-600" : p.stock < 10 ? "text-amber-600" : "text-slate-700"}`}>
                      {fmtQty(p.stock)}{p.unit}
                    </p>
                  </div>
                  <div className="flex gap-1 mt-3 pt-3 border-t border-slate-100">
                    <button onClick={() => { setEditing(p); setDialogOpen(true); }} data-testid={`product-edit-${p.id}`}
                      className="flex-1 text-xs font-bold text-slate-600 hover:text-amber-700 hover:bg-amber-50 rounded-lg py-1.5 transition-colors flex items-center justify-center gap-1">
                      <Pencil className="w-3.5 h-3.5" /> Editar
                    </button>
                    <button onClick={() => setStockFor(p)} title="Ajustar stock" data-testid={`product-stock-${p.id}`}
                      className="px-2.5 rounded-lg text-slate-400 hover:text-emerald-600 hover:bg-emerald-50 transition-colors">
                      <PackageSearch className="w-3.5 h-3.5" />
                    </button>
                    <button onClick={() => toggle(p)} title={p.active ? "Desactivar" : "Activar"} data-testid={`product-toggle-${p.id}`}
                      className={`px-2.5 rounded-lg transition-colors ${p.active ? "text-slate-400 hover:text-slate-600 hover:bg-slate-100" : "text-emerald-500 hover:bg-emerald-50"}`}>
                      <Power className="w-3.5 h-3.5" />
                    </button>
                    <AlertDialog>
                      <AlertDialogTrigger asChild>
                        <button title="Eliminar" data-testid={`product-delete-${p.id}`} className="px-2.5 rounded-lg text-slate-400 hover:text-red-500 hover:bg-red-50 transition-colors">
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </AlertDialogTrigger>
                      <AlertDialogContent>
                        <AlertDialogHeader>
                          <AlertDialogTitle>¿Eliminar «{p.name}»?</AlertDialogTitle>
                          <AlertDialogDescription>Esta acción no se puede deshacer. El histórico de ventas se conserva.</AlertDialogDescription>
                        </AlertDialogHeader>
                        <AlertDialogFooter>
                          <AlertDialogCancel>Cancelar</AlertDialogCancel>
                          <AlertDialogAction onClick={() => remove(p)} className="bg-red-500 hover:bg-red-600" data-testid="product-delete-confirm">Eliminar</AlertDialogAction>
                        </AlertDialogFooter>
                      </AlertDialogContent>
                    </AlertDialog>
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
              <table className="w-full text-sm" data-testid="gestion-products-table">
                <thead>
                  <tr className="text-left text-xs uppercase tracking-wider text-slate-500 border-b border-slate-200 bg-slate-50/60">
                    <th className="px-4 py-3">Producto</th>
                    <th className="px-4 py-3">Categoría</th>
                    <th className="px-4 py-3 text-right">Precio</th>
                    <th className="px-4 py-3 text-right">Stock</th>
                    <th className="px-4 py-3 text-right">Acciones</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((p) => (
                    <tr key={p.id} className={`border-b border-slate-100 hover:bg-amber-50/40 transition-colors ${p.active ? "" : "opacity-60"}`} data-testid={`gestion-product-row-${p.id}`}>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-3">
                          <div className="w-10 h-10 rounded-lg overflow-hidden bg-amber-50 shrink-0 flex items-center justify-center">
                            {p.image_url ? (
                              <img src={p.image_url} alt="" className="w-full h-full object-cover" loading="lazy" />
                            ) : (
                              <Package className="w-4 h-4 text-amber-300" />
                            )}
                          </div>
                          <div>
                            <p className="font-semibold text-slate-900">
                              {p.name}
                              {!p.active && <span className="ml-2 badge-inactive align-middle" data-testid={`product-status-${p.id}`}>Inactivo</span>}
                            </p>
                            {p.thc != null && <p className="text-xs text-slate-400">THC {p.thc}%{p.cbd ? ` · CBD ${p.cbd}%` : ""}</p>}
                          </div>
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <span className={`text-xs font-medium px-2.5 py-0.5 rounded-full border ${catStyle(categories, p.category)}`}>
                          {catLabel(categories, p.category)}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-right font-mono-num font-bold text-slate-900">{fmtEUR(p.price)}/{p.unit}</td>
                      <td className={`px-4 py-3 text-right font-mono-num font-bold ${p.stock <= 0 ? "text-red-600" : p.stock < 10 ? "text-amber-600" : "text-slate-900"}`}>
                        {fmtQty(p.stock)}{p.unit}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex justify-end gap-1">
                          <button onClick={() => setStockFor(p)} title="Ajustar stock" data-testid={`product-stock-${p.id}`}
                            className="p-2 rounded-lg text-slate-400 hover:text-emerald-600 hover:bg-emerald-50 transition-colors">
                            <PackageSearch className="w-4 h-4" />
                          </button>
                          <button onClick={() => { setEditing(p); setDialogOpen(true); }} title="Editar" data-testid={`product-edit-${p.id}`}
                            className="p-2 rounded-lg text-slate-400 hover:text-amber-600 hover:bg-amber-50 transition-colors">
                            <Pencil className="w-4 h-4" />
                          </button>
                          <button onClick={() => toggle(p)} title={p.active ? "Desactivar" : "Activar"} data-testid={`product-toggle-${p.id}`}
                            className={`p-2 rounded-lg transition-colors ${p.active ? "text-slate-400 hover:text-slate-600 hover:bg-slate-100" : "text-emerald-500 hover:bg-emerald-50"}`}>
                            <Power className="w-4 h-4" />
                          </button>
                          <AlertDialog>
                            <AlertDialogTrigger asChild>
                              <button title="Eliminar" data-testid={`product-delete-${p.id}`} className="p-2 rounded-lg text-slate-400 hover:text-red-500 hover:bg-red-50 transition-colors">
                                <Trash2 className="w-4 h-4" />
                              </button>
                            </AlertDialogTrigger>
                            <AlertDialogContent>
                              <AlertDialogHeader>
                                <AlertDialogTitle>¿Eliminar «{p.name}»?</AlertDialogTitle>
                                <AlertDialogDescription>Esta acción no se puede deshacer. El histórico de ventas se conserva.</AlertDialogDescription>
                              </AlertDialogHeader>
                              <AlertDialogFooter>
                                <AlertDialogCancel>Cancelar</AlertDialogCancel>
                                <AlertDialogAction onClick={() => remove(p)} className="bg-red-500 hover:bg-red-600" data-testid="product-delete-confirm">Eliminar</AlertDialogAction>
                              </AlertDialogFooter>
                            </AlertDialogContent>
                          </AlertDialog>
                        </div>
                      </td>
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
        </TabsContent>

        <TabsContent value="categorias" className="mt-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3" data-testid="categories-grid">
            {categories.map((c) => (
              <div key={c.id} className="card-soft p-4 flex items-center gap-3" data-testid={`category-card-${c.id}`}>
                <span className={`w-4 h-4 rounded-full shrink-0 ${CATEGORY_DOTS[c.color] || "bg-slate-300"}`} />
                <div className="flex-1 min-w-0">
                  <p className="font-semibold text-slate-900">{c.label}</p>
                  <p className="text-xs text-slate-400">{productCount(c.key)} productos · {c.key}</p>
                </div>
                <button onClick={() => { setEditingCat(c); setCatDialogOpen(true); }} title="Editar" data-testid={`category-edit-${c.id}`}
                  className="p-2 rounded-lg text-slate-400 hover:text-amber-600 hover:bg-amber-50 transition-colors">
                  <Pencil className="w-4 h-4" />
                </button>
                <AlertDialog>
                  <AlertDialogTrigger asChild>
                    <button title="Eliminar" data-testid={`category-delete-${c.id}`} className="p-2 rounded-lg text-slate-400 hover:text-red-500 hover:bg-red-50 transition-colors">
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </AlertDialogTrigger>
                  <AlertDialogContent>
                    <AlertDialogHeader>
                      <AlertDialogTitle>¿Eliminar la categoría «{c.label}»?</AlertDialogTitle>
                      <AlertDialogDescription>Solo se puede eliminar si ningún producto la está usando.</AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                      <AlertDialogCancel>Cancelar</AlertDialogCancel>
                      <AlertDialogAction onClick={() => removeCat(c)} className="bg-red-500 hover:bg-red-600" data-testid="category-delete-confirm">Eliminar</AlertDialogAction>
                    </AlertDialogFooter>
                  </AlertDialogContent>
                </AlertDialog>
              </div>
            ))}
          </div>
        </TabsContent>
      </Tabs>

      <ProductDialog open={dialogOpen} onClose={() => setDialogOpen(false)} product={editing} categories={categories} onSaved={load} />
      <CategoryDialog open={catDialogOpen} onClose={() => setCatDialogOpen(false)} category={editingCat} onSaved={load} />
      <StockDialog product={stockFor} open={!!stockFor} onClose={() => setStockFor(null)} onSaved={load} />
    </div>
  );
}
