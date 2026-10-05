import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import api, { fmtEUR, fmtDateTime, apiError, fmtQty, downloadClosingPdf } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger } from "@/components/ui/alert-dialog";
import {
  Wallet, ArrowUpRight, ArrowDownLeft, Lock, LockOpen, Scale, Coins, ShoppingBag,
  AlertTriangle, ClipboardCheck, PackageSearch, ListChecks, Search, Undo2, Loader2,
  Check, Square, CheckSquare, Hourglass, FileText,
} from "lucide-react";

const CLOSING_STEPS = ["Efectivo", "Stock por secciones", "Revisión"];
const OPENING_STEPS = ["Fondo", "Stock por secciones", "Confirmar"];

function Stepper({ step, steps, testid }) {
  return (
    <div className="flex items-center gap-2 flex-wrap" data-testid={testid}>
      {steps.map((label, i) => {
        const n = i + 1;
        const active = n === step;
        const done = n < step;
        return (
          <div key={label} className="flex items-center gap-2">
            <span className={`w-7 h-7 rounded-full text-xs font-bold flex items-center justify-center border ${
              done ? "bg-emerald-500 text-white border-emerald-500" : active ? "bg-amber-400 text-slate-950 border-amber-400" : "bg-white text-slate-400 border-slate-200"
            }`}>{n}</span>
            <span className={`text-xs font-bold ${active ? "text-slate-900" : "text-slate-400"}`}>{label}</span>
            {n < steps.length && <span className="w-6 h-px bg-slate-200" />}
          </div>
        );
      })}
    </div>
  );
}

/* Colores de diferencia: unidades → rojo/verde; gramos → neutro (los desfases suelen estar justificados) */
function diffTone(line, diff) {
  if (diff === null || Math.abs(diff) <= 1e-9) return "neutral";
  if (line.unit === "ud") return diff < 0 ? "red" : "green";
  return "gramos";
}

const TONE_CARD = {
  neutral: "border-slate-200 bg-white",
  red: "border-red-300 bg-red-50",
  green: "border-emerald-300 bg-emerald-50",
  gramos: "border-amber-200 bg-amber-50/60",
};
const TONE_TEXT = {
  neutral: "text-slate-400",
  red: "text-red-600",
  green: "text-emerald-600",
  gramos: "text-amber-700",
};

function ArqueoStep({ totals, onSaved }) {
  const [counted, setCounted] = useState("");
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const countedNum = counted === "" ? null : parseFloat(counted);
  const diff = countedNum === null || isNaN(countedNum) ? null : Math.round((countedNum - totals.esperado) * 100) / 100;

  const save = async () => {
    setSaving(true);
    try {
      await api.post("/cash/closing/cash", { counted: countedNum, reason });
      toast.success("Arqueo de efectivo guardado");
      onSaved();
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="card-soft p-6 max-w-lg space-y-4" data-testid="arqueo-step">
      <h2 className="font-display text-xl font-bold text-slate-900 flex items-center gap-2">
        <Scale className="w-5 h-5 text-amber-500" /> Recuento de efectivo
      </h2>
      <div className="bg-amber-50 border border-amber-200 rounded-xl px-4 py-3 text-sm flex justify-between">
        <span className="text-amber-800">Efectivo esperado según el sistema</span>
        <span className="font-mono-num font-bold text-amber-700" data-testid="arqueo-expected">{fmtEUR(totals.esperado)}</span>
      </div>
      <p className="text-xs text-slate-400">
        Fondo + recargas en efectivo + entradas − devoluciones − salidas. Las ventas con saldo no ingresan efectivo.
      </p>
      <div>
        <label className="text-xs font-semibold uppercase tracking-wider text-slate-500 block mb-1">Efectivo contado (Cr)</label>
        <input
          type="number" min="0" step="0.01" value={counted} onChange={(e) => setCounted(e.target.value)}
          placeholder="Escribe lo contado (0 si no hay nada)"
          data-testid="arqueo-counted-input"
          className="w-full px-4 py-3 rounded-xl border border-slate-300 font-mono-num font-bold text-lg focus:outline-none focus:ring-2 focus:ring-amber-400"
        />
      </div>
      {diff !== null && (
        <div className={`rounded-xl px-4 py-2.5 text-sm flex justify-between border ${Math.abs(diff) < 0.005 ? "bg-emerald-50 border-emerald-200 text-emerald-700" : "bg-red-50 border-red-200 text-red-600"}`} data-testid="arqueo-diff-preview">
          <span>{diff > 0 ? "Sobrante" : diff < 0 ? "Faltante" : "Cuadra"}</span>
          <span className="font-mono-num font-bold">{diff > 0 ? "+" : ""}{fmtEUR(diff)}</span>
        </div>
      )}
      <div>
        <label className="text-xs font-semibold uppercase tracking-wider text-slate-500 block mb-1">Nota sobre la diferencia (opcional)</label>
        <input value={reason} onChange={(e) => setReason(e.target.value)} data-testid="arqueo-reason-input"
          placeholder="Puedes dejarlo vacío aunque haya diferencia"
          className="w-full px-4 py-3 rounded-xl border border-slate-300 focus:outline-none focus:ring-2 focus:ring-amber-400" />
      </div>
      <button onClick={save} disabled={saving || countedNum === null || isNaN(countedNum)}
        className="btn-primary w-full" data-testid="arqueo-save-btn">
        {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
        Guardar arqueo y continuar al stock
      </button>
    </div>
  );
}

/* Recuento de stock en cuadrícula, compartido por apertura y cierre */
function StocktakeGrid({ stocktake, onUpdated, onNext, nextLabel }) {
  const [counts, setCounts] = useState({});
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState("todas");
  const [savingLine, setSavingLine] = useState(null);
  const [filling, setFilling] = useState(null);

  useEffect(() => {
    const c = {};
    for (const l of stocktake.lines) {
      c[l.product_id] = l.counted === null || l.counted === undefined ? "" : String(l.counted);
    }
    setCounts(c);
  }, [stocktake.id]);

  const saveLine = async (line) => {
    const raw = counts[line.product_id];
    const current = line.counted === null || line.counted === undefined ? "" : String(line.counted);
    if (raw === current) return;
    setSavingLine(line.product_id);
    try {
      const res = await api.patch("/cash/stocktake/line", {
        product_id: line.product_id,
        counted: raw === "" ? null : parseFloat(raw),
        version: stocktake.version,
      });
      onUpdated(res.data);
    } catch (e) {
      toast.error(apiError(e, "No se pudo guardar la línea"));
      onUpdated(null);
    } finally {
      setSavingLine(null);
    }
  };

  const autofill = async (payload, key) => {
    setFilling(key);
    try {
      const res = await api.post("/cash/stocktake/autofill", { ...payload, version: stocktake.version });
      toast.success("Contado rellenado con el esperado del sistema");
      const c = {};
      for (const l of res.data.lines) {
        c[l.product_id] = l.counted === null || l.counted === undefined ? "" : String(l.counted);
      }
      setCounts(c);
      onUpdated(res.data);
    } catch (e) {
      toast.error(apiError(e, "No se pudo autorrellenar"));
      onUpdated(null);
    } finally {
      setFilling(null);
    }
  };

  const lines = useMemo(() => {
    return stocktake.lines.filter((l) => {
      if (q && !l.name.toLowerCase().includes(q.toLowerCase())) return false;
      if (filter === "pendientes") return l.counted === null || l.counted === undefined;
      if (filter === "diferencias") return l.difference !== null && l.difference !== undefined && Math.abs(l.difference) > 1e-9;
      return true;
    });
  }, [stocktake, q, filter]);

  const sections = useMemo(() => {
    const map = {};
    for (const l of lines) {
      (map[l.category_label] = map[l.category_label] || []).push(l);
    }
    const order = stocktake.sections || [];
    const rank = (s) => (order.indexOf(s) === -1 ? order.length : order.indexOf(s));
    return Object.entries(map).sort((a, b) => rank(a[0]) - rank(b[0]) || a[0].localeCompare(b[0]));
  }, [lines, stocktake.sections]);

  const pendientes = stocktake.lines.filter((l) => l.counted === null || l.counted === undefined).length;
  const discrepancias = stocktake.lines.filter((l) => l.difference !== null && l.difference !== undefined && Math.abs(l.difference) > 1e-9).length;

  return (
    <div className="space-y-4" data-testid="stocktake-step">
      <div className="card-soft p-4 flex flex-wrap items-center gap-3">
        <p className="text-xs text-slate-500 flex-1 min-w-[220px]">
          Alcance: {stocktake.scope}. Al confirmar, lo que cuentes pasa a ser el stock del sistema.
        </p>
        <span className="badge-inactive" data-testid="stocktake-progress">
          {stocktake.lines.length - pendientes}/{stocktake.lines.length} contados · {discrepancias} con diferencia
        </span>
      </div>

      <div className="flex gap-2 flex-wrap items-center">
        <div className="relative flex-1 min-w-[200px] max-w-sm">
          <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Localizar producto…" data-testid="stocktake-search"
            className="w-full pl-10 pr-4 py-2.5 rounded-xl border border-slate-300 bg-white focus:outline-none focus:ring-2 focus:ring-amber-400" />
        </div>
        {["todas", "pendientes", "diferencias"].map((f) => (
          <button key={f} onClick={() => setFilter(f)} data-testid={`stocktake-filter-${f}`}
            className={`px-3.5 py-2 rounded-full text-xs font-bold border transition-colors capitalize ${filter === f ? "bg-slate-900 text-white border-slate-900" : "bg-white text-slate-600 border-slate-200 hover:border-slate-400"}`}>
            {f === "todas" ? "Todas" : f === "pendientes" ? `Pendientes (${pendientes})` : `Con diferencia (${discrepancias})`}
          </button>
        ))}
      </div>

      {sections.map(([section, sectionLines]) => {
        const allFilled = sectionLines.every((l) => l.counted !== null && l.counted !== undefined && Math.abs((l.counted ?? 0) - l.expected) <= 1e-9);
        return (
          <div key={section} className="card-soft overflow-hidden" data-testid={`stocktake-section-${section}`}>
            <div className="px-4 py-2.5 bg-slate-50/80 border-b border-slate-200 flex items-center justify-between gap-3 flex-wrap">
              <span className="text-xs font-bold uppercase tracking-wider text-slate-500">
                {section} · {sectionLines.length}
              </span>
              <button
                onClick={() => autofill({ section }, `sec-${section}`)}
                disabled={filling !== null}
                data-testid={`stocktake-autofill-section-${section}`}
                className={`flex items-center gap-1.5 text-[11px] font-bold px-2.5 py-1.5 rounded-lg border transition-colors ${
                  allFilled ? "bg-emerald-100 text-emerald-700 border-emerald-200" : "bg-white text-slate-600 border-slate-200 hover:border-amber-400 hover:text-amber-700"
                }`}
              >
                {filling === `sec-${section}` ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : allFilled ? <CheckSquare className="w-3.5 h-3.5" /> : <Square className="w-3.5 h-3.5" />}
                Contado = esperado en toda la sección
              </button>
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3 p-3">
              {sectionLines.map((l) => {
                const raw = counts[l.product_id] ?? "";
                const countedNum = raw === "" ? null : parseFloat(raw);
                const diff = countedNum === null || isNaN(countedNum) ? null : Math.round((countedNum - l.expected) * 1000) / 1000;
                const hasDiff = diff !== null && Math.abs(diff) > 1e-9;
                const tone = diffTone(l, diff);
                const isExpected = diff !== null && !hasDiff;
                return (
                  <div key={l.product_id} className={`rounded-xl border p-3 space-y-2 transition-colors ${raw === "" ? "border-dashed border-slate-300 bg-slate-50/60" : TONE_CARD[tone]}`}
                    data-testid={`stock-line-${l.product_id}`}>
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <p className="text-sm font-bold text-slate-900 leading-tight truncate">{l.name}</p>
                        <p className="text-[11px] text-slate-400 font-mono-num mt-0.5">esperado: {fmtQty(l.expected)}{l.unit}</p>
                      </div>
                      <button
                        onClick={() => autofill({ product_id: l.product_id }, `prod-${l.product_id}`)}
                        disabled={filling !== null}
                        title="Rellenar con el esperado del sistema"
                        data-testid={`stock-line-autofill-${l.product_id}`}
                        className={`shrink-0 w-6 h-6 rounded-md border flex items-center justify-center transition-colors ${
                          isExpected ? "bg-emerald-500 border-emerald-500 text-white" : "bg-white border-slate-300 text-transparent hover:border-amber-400"
                        }`}
                      >
                        {filling === `prod-${l.product_id}` ? <Loader2 className="w-3.5 h-3.5 animate-spin text-slate-400" /> : <Check className="w-4 h-4" />}
                      </button>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <input
                        type="number" min="0" step="any" value={raw}
                        onChange={(e) => setCounts((c) => ({ ...c, [l.product_id]: e.target.value }))}
                        onBlur={() => saveLine(l)}
                        placeholder="contar…"
                        data-testid={`stock-line-input-${l.product_id}`}
                        className="w-full min-w-0 px-2.5 py-1.5 rounded-lg border border-slate-300 bg-white text-sm font-mono-num font-bold text-center focus:outline-none focus:ring-2 focus:ring-amber-400"
                      />
                      <span className="text-[11px] text-slate-400">{l.unit}</span>
                      {savingLine === l.product_id && <Loader2 className="w-3.5 h-3.5 animate-spin text-slate-400" />}
                    </div>
                    {hasDiff && (
                      <p className={`text-[11px] font-mono-num font-bold text-right ${TONE_TEXT[tone]}`} data-testid={`stock-line-diff-${l.product_id}`}>
                        {diff > 0 ? "+" : ""}{fmtQty(diff)}{l.unit}
                      </p>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        );
      })}
      {sections.length === 0 && <p className="text-sm text-slate-400 text-center py-8">Nada que mostrar con este filtro.</p>}

      {onNext && (
        <div className="flex justify-end">
          <button onClick={onNext} className="btn-primary" data-testid="stocktake-review-btn">
            {nextLabel || "Ir a revisión"} <ListChecks className="w-4 h-4" />
          </button>
        </div>
      )}
    </div>
  );
}

function ReviewStep({ session, stocktake, onFinalized }) {
  const [saving, setSaving] = useState(false);
  const pendientes = stocktake.lines.filter((l) => l.counted === null || l.counted === undefined);
  const discrepancias = stocktake.lines.filter((l) => l.difference !== null && l.difference !== undefined && Math.abs(l.difference) > 1e-9);
  const cc = session.cash_count;
  const canClose = pendientes.length === 0;

  const finalize = async () => {
    setSaving(true);
    try {
      const res = await api.post("/cash/closing/finalize");
      toast.success("Turno cerrado definitivamente. Descargando el resumen en PDF…");
      onFinalized();
      downloadClosingPdf(res.data).catch(() => toast.error("No se pudo descargar el PDF; puedes bajarlo desde el histórico de turnos"));
    } catch (e) {
      toast.error(apiError(e));
      onFinalized(true);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-4 max-w-2xl" data-testid="review-step">
      <div className="card-soft p-5">
        <h3 className="font-display text-lg font-bold text-slate-900 mb-3 flex items-center gap-2">
          <Scale className="w-4 h-4 text-amber-500" /> Arqueo de efectivo
        </h3>
        <div className="grid grid-cols-3 gap-3 text-center">
          <div><p className="text-xs text-slate-400 uppercase font-semibold">Esperado</p><p className="font-mono-num font-bold text-slate-900">{fmtEUR(cc.expected)}</p></div>
          <div><p className="text-xs text-slate-400 uppercase font-semibold">Contado</p><p className="font-mono-num font-bold text-slate-900">{fmtEUR(cc.counted)}</p></div>
          <div>
            <p className="text-xs text-slate-400 uppercase font-semibold">Diferencia</p>
            <p className={`font-mono-num font-bold ${Math.abs(cc.difference) < 0.005 ? "text-emerald-600" : "text-red-600"}`}>{cc.difference > 0 ? "+" : ""}{fmtEUR(cc.difference)}</p>
          </div>
        </div>
        {cc.reason && <p className="text-xs text-slate-500 mt-2">Nota: {cc.reason}</p>}
      </div>

      <div className="card-soft p-5">
        <h3 className="font-display text-lg font-bold text-slate-900 mb-3 flex items-center gap-2">
          <PackageSearch className="w-4 h-4 text-amber-500" /> Recuento de stock
        </h3>
        {pendientes.length > 0 && (
          <div className="bg-red-50 border border-red-200 rounded-xl p-3 mb-3" data-testid="review-pendientes">
            <p className="text-sm font-bold text-red-700">{pendientes.length} productos pendientes de contar:</p>
            <p className="text-xs text-red-600 mt-1">{pendientes.map((l) => l.name).join(", ")}</p>
          </div>
        )}
        {discrepancias.length === 0 ? (
          <p className="text-sm text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-xl p-3">Todo el stock cuadra con el sistema.</p>
        ) : (
          <div className="space-y-2" data-testid="review-discrepancias">
            <p className="text-xs text-slate-500">Al confirmar el cierre, el stock del sistema se actualiza con lo contado y las diferencias quedan en el informe.</p>
            {discrepancias.map((l) => {
              const tone = diffTone(l, l.difference);
              return (
                <div key={l.product_id} className={`rounded-xl border p-3 text-sm ${TONE_CARD[tone]}`} data-testid={`review-diff-${l.product_id}`}>
                  <div className="flex justify-between">
                    <span className="font-semibold text-slate-800">{l.name}</span>
                    <span className={`font-mono-num font-bold ${TONE_TEXT[tone]}`}>{l.difference > 0 ? "+" : ""}{fmtQty(l.difference)}{l.unit}</span>
                  </div>
                  <p className="text-xs text-slate-500">esperado {fmtQty(l.expected)}{l.unit} · contado {fmtQty(l.counted)}{l.unit}</p>
                </div>
              );
            })}
          </div>
        )}
      </div>

      <button onClick={finalize} disabled={!canClose || saving} className="btn-secondary w-full py-3.5 text-base" data-testid="finalize-close-btn">
        {saving ? <Loader2 className="w-5 h-5 animate-spin" /> : <Lock className="w-5 h-5" />}
        {canClose ? "Confirmar cierre definitivo del turno" : "No se puede cerrar: quedan productos pendientes de contar"}
      </button>
    </div>
  );
}

function StocktakeDiffList({ st, title }) {
  if (!st) return null;
  const diffs = st.lines.filter((l) => l.difference !== null && l.difference !== undefined && Math.abs(l.difference) > 1e-9);
  return (
    <div className="border border-slate-200 rounded-xl p-3.5">
      <p className="font-bold text-slate-900 mb-1">{title} · {st.lines.length} productos contados</p>
      <p className="text-xs text-slate-500 mb-2">Secciones: {st.sections.join(", ")}</p>
      {diffs.length === 0 ? (
        <p className="text-xs text-emerald-700">Sin diferencias de inventario.</p>
      ) : (
        <div className="space-y-1.5">
          {diffs.map((l) => {
            const tone = diffTone(l, l.difference);
            return (
              <p key={l.product_id} className="text-xs flex justify-between gap-2">
                <span className="text-slate-700">{l.name} <span className="text-slate-400">({l.category_label})</span></span>
                <span className={`font-mono-num font-bold ${TONE_TEXT[tone]}`}>{l.difference > 0 ? "+" : ""}{fmtQty(l.difference)}{l.unit}</span>
              </p>
            );
          })}
        </div>
      )}
    </div>
  );
}

function ReportDialog({ sessionId, open, onClose }) {
  const [report, setReport] = useState(null);
  useEffect(() => {
    if (open && sessionId) {
      setReport(null);
      api.get(`/cash/sessions/${sessionId}`).then((r) => setReport(r.data)).catch(() => {});
    }
  }, [open, sessionId]);

  const s = report?.session;
  const [downloading, setDownloading] = useState(false);
  const download = async () => {
    setDownloading(true);
    try {
      await downloadClosingPdf(s);
    } catch (e) {
      toast.error(apiError(e, "No se pudo generar el PDF"));
    } finally {
      setDownloading(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onClose}>
      <DialogContent className="max-w-lg max-h-[85vh] overflow-y-auto" data-testid="cash-report-dialog">
        <DialogHeader>
          <DialogTitle className="font-display">Informe de turno</DialogTitle>
        </DialogHeader>
        {!report ? (
          <p className="text-sm text-slate-400 py-8 text-center">Cargando informe…</p>
        ) : (
          <div className="space-y-4 text-sm">
            <div className="flex items-start justify-between gap-3">
              <div className="text-xs text-slate-500">
                <p>Responsable: <b>{s.opened_by}</b> · abierto {fmtDateTime(s.opened_at)}</p>
                <p>Cerrado por: <b>{s.closed_by}</b> · {fmtDateTime(s.closed_at)}{s.supervised ? " · con supervisión de administrador" : ""}</p>
              </div>
              <button onClick={download} disabled={downloading} className="btn-outline py-2 text-xs shrink-0" data-testid="cash-report-pdf-btn">
                {downloading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <FileText className="w-3.5 h-3.5" />}
                Descargar PDF
              </button>
            </div>
            {report.out_of_shift_sales?.length > 0 && (
              <div className="bg-sky-50 border border-sky-200 rounded-xl p-3.5" data-testid="report-out-of-shift">
                <p className="font-bold text-slate-900 mb-1">Ventas fuera de turno incorporadas ({report.out_of_shift_sales.length})</p>
                {report.out_of_shift_sales.map((v) => (
                  <p key={v.id} className="text-xs text-slate-600 flex justify-between">
                    <span>{v.ticket_number} · {v.socio_name}</span>
                    <span className="font-mono-num font-bold">{fmtEUR(v.total)}</span>
                  </p>
                ))}
              </div>
            )}
            <StocktakeDiffList st={report.opening_stocktake} title="Recuento de apertura" />
            {s.cash_count && (
              <div className="bg-amber-50 border border-amber-200 rounded-xl p-3.5">
                <p className="font-bold text-slate-900 mb-1">Efectivo</p>
                <p className="font-mono-num text-xs">esperado {fmtEUR(s.cash_count.expected)} · contado {fmtEUR(s.cash_count.counted)} · diferencia {s.cash_count.difference > 0 ? "+" : ""}{fmtEUR(s.cash_count.difference)}</p>
                {s.cash_count.reason && <p className="text-xs text-slate-500 mt-1">Nota: {s.cash_count.reason}</p>}
              </div>
            )}
            {report.stocktake ? (
              <StocktakeDiffList st={report.stocktake} title="Recuento de cierre" />
            ) : (
              <p className="text-xs text-slate-400">Este turno se cerró antes de existir el recuento de stock.</p>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

export default function Caja() {
  const { user } = useAuth();
  const [data, setData] = useState(null);
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(true);
  const [starting, setStarting] = useState("100");
  const [movDialog, setMovDialog] = useState(null);
  const [movAmount, setMovAmount] = useState("");
  const [movReason, setMovReason] = useState("");
  const [step, setStep] = useState(1);
  const [reportId, setReportId] = useState(null);
  const [opening, setOpening] = useState(false);
  const [confirmingOpen, setConfirmingOpen] = useState(false);

  const load = async () => {
    try {
      const r = await api.get("/cash/current");
      setData(r.data);
      if (user.role === "admin") {
        const h = await api.get("/cash/sessions");
        setHistory(h.data);
      }
    } catch (e) {
      // silencioso; la pantalla muestra el estado vacío
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const session = data?.session;
  const totals = data?.totals;
  const stocktake = data?.stocktake;
  const pendingOut = data?.out_of_shift_pending || { count: 0, total: 0 };
  const isOwner = session && session.opened_by_id === user.id;
  const canOperate = session && (isOwner || user.role === "admin");

  useEffect(() => {
    if (session?.status === "closing") {
      setStep(session.cash_count ? 2 : 1);
    }
  }, [session?.status, session?.cash_count]);

  const startOpening = async () => {
    setOpening(true);
    try {
      await api.post("/cash/open", { starting_amount: parseFloat(starting) || 0 });
      toast.success("Apertura iniciada: ahora toca el recuento de stock");
      load();
    } catch (e) { toast.error(apiError(e)); }
    finally { setOpening(false); }
  };

  const confirmOpening = async () => {
    setConfirmingOpen(true);
    try {
      await api.post("/cash/opening/confirm");
      toast.success("Turno de caja abierto. ¡A vender!");
      load();
    } catch (e) {
      toast.error(apiError(e));
      load();
    } finally {
      setConfirmingOpen(false);
    }
  };

  const cancelOpening = async () => {
    try {
      await api.post("/cash/opening/cancel");
      toast.success("Apertura cancelada; las ventas fuera de turno vuelven a estar pendientes");
      load();
    } catch (e) { toast.error(apiError(e)); }
  };

  const doMovement = async () => {
    try {
      await api.post("/cash/movements", { type: movDialog, amount: parseFloat(movAmount) || 0, reason: movReason });
      toast.success("Movimiento registrado");
      setMovDialog(null);
      setMovAmount("");
      setMovReason("");
      load();
    } catch (e) { toast.error(apiError(e)); }
  };

  const startClosing = async () => {
    try {
      await api.post("/cash/closing/start");
      toast.success("Cierre iniciado: la caja queda reservada hasta terminar");
      setStep(1);
      load();
    } catch (e) { toast.error(apiError(e)); }
  };

  const cancelClosing = async () => {
    try {
      await api.post("/cash/closing/cancel");
      toast.success("Cierre cancelado; el turno vuelve a estar abierto");
      load();
    } catch (e) { toast.error(apiError(e)); }
  };

  const ensureStocktake = async () => {
    try {
      await api.post("/cash/closing/stocktake/start");
    } catch (e) {
      toast.error(apiError(e));
    }
    load();
  };

  const onStocktakeUpdated = (st) => {
    if (st) {
      setData((d) => ({ ...d, stocktake: st }));
    } else {
      load();
    }
  };

  const openingPendientes = stocktake ? stocktake.lines.filter((l) => l.counted === null || l.counted === undefined).length : 0;

  if (loading) {
    return <div className="text-sm text-slate-500 py-20 text-center">Cargando caja…</div>;
  }

  return (
    <div className="space-y-5" data-testid="caja-page">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <h1 className="font-display text-3xl sm:text-4xl font-bold tracking-tight text-slate-900">Caja</h1>
          <p className="text-sm text-slate-500 mt-1">Un único turno activo por local, con recuento de stock al abrir y al cerrar.</p>
        </div>
        {session?.status === "open" && canOperate && (
          <div className="flex gap-2">
            <button onClick={() => setMovDialog("in")} className="btn-outline text-emerald-700 border-emerald-300 bg-emerald-50" data-testid="cash-in-btn">
              <ArrowDownLeft className="w-4 h-4" /> Entrada
            </button>
            <button onClick={() => setMovDialog("out")} className="btn-outline text-red-600 border-red-200 bg-red-50" data-testid="cash-out-btn">
              <ArrowUpRight className="w-4 h-4" /> Salida
            </button>
            <button onClick={startClosing} className="btn-primary" data-testid="closing-start-btn">
              <Lock className="w-4 h-4" /> Iniciar cierre de turno
            </button>
          </div>
        )}
      </div>

      {!session ? (
        <div className="card-soft p-10 sm:p-14 text-center" data-testid="cash-closed-state">
          <div className="w-16 h-16 rounded-2xl bg-slate-100 flex items-center justify-center mx-auto mb-4">
            <Wallet className="w-8 h-8 text-slate-400" />
          </div>
          <h2 className="font-display text-xl font-bold text-slate-900">No hay ningún turno abierto</h2>
          <p className="text-sm text-slate-500 mt-1">Abrir un turno exige contar el stock, igual que al cerrar.</p>
          {pendingOut.count > 0 && (
            <div className="max-w-md mx-auto mt-4 bg-sky-50 border border-sky-200 rounded-xl px-4 py-3 text-sm text-sky-800 flex items-center gap-3 text-left" data-testid="pending-out-of-shift-banner">
              <Hourglass className="w-5 h-5 shrink-0 text-sky-500" />
              <p>
                Hay <b>{pendingOut.count} ventas fuera de turno</b> por <b className="font-mono-num">{fmtEUR(pendingOut.total)}</b>.
                Se incorporarán obligatoriamente a este turno al abrirlo y su stock se descontará antes del recuento.
              </p>
            </div>
          )}
          <div className="max-w-xs mx-auto space-y-3 mt-6">
            <input type="number" min="0" value={starting} onChange={(e) => setStarting(e.target.value)} data-testid="cash-open-amount-input"
              className="w-full px-4 py-3 rounded-xl border border-slate-300 font-mono-num font-bold text-center focus:outline-none focus:ring-2 focus:ring-amber-400" />
            <button onClick={startOpening} disabled={opening} className="btn-secondary w-full" data-testid="cash-open-shift-btn">
              {opening ? <Loader2 className="w-4 h-4 animate-spin" /> : <LockOpen className="w-4 h-4" />}
              Iniciar apertura de turno
            </button>
          </div>
        </div>
      ) : session.status === "opening" ? (
        <div className="space-y-5" data-testid="opening-wizard">
          <div className="card-soft p-4 flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-sm font-bold text-slate-900 flex items-center gap-2">
                <ClipboardCheck className="w-4 h-4 text-amber-500" /> Apertura en curso · turno de {session.opened_by}
              </p>
              <p className="text-xs text-slate-500 mt-0.5">La caja queda reservada: ventas y recargas en pausa hasta confirmar la apertura.</p>
              {(session.out_of_shift_count || 0) > 0 && (
                <p className="text-xs text-sky-700 font-semibold mt-1" data-testid="opening-absorbed-note">
                  {session.out_of_shift_count} ventas fuera de turno incorporadas ({fmtEUR(session.out_of_shift_total || 0)}); su stock ya está descontado en el esperado.
                </p>
              )}
            </div>
            <div className="flex items-center gap-3">
              <Stepper step={2} steps={OPENING_STEPS} testid="opening-stepper" />
              {user.role === "admin" && (
                <AlertDialog>
                  <AlertDialogTrigger asChild>
                    <button className="btn-outline text-red-600 border-red-200 py-2 text-xs" data-testid="opening-cancel-btn">
                      <Undo2 className="w-3.5 h-3.5" /> Cancelar apertura
                    </button>
                  </AlertDialogTrigger>
                  <AlertDialogContent>
                    <AlertDialogHeader>
                      <AlertDialogTitle>¿Cancelar la apertura en curso?</AlertDialogTitle>
                      <AlertDialogDescription>
                        Acción administrativa auditada: el turno se descarta, el recuento queda invalidado y las ventas fuera de turno incorporadas vuelven a estar pendientes (con su stock restaurado).
                      </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                      <AlertDialogCancel>Volver</AlertDialogCancel>
                      <AlertDialogAction onClick={cancelOpening} className="bg-red-500 hover:bg-red-600" data-testid="opening-cancel-confirm">Cancelar la apertura</AlertDialogAction>
                    </AlertDialogFooter>
                  </AlertDialogContent>
                </AlertDialog>
              )}
            </div>
          </div>

          {!canOperate ? (
            <div className="card-soft p-10 text-center text-sm text-slate-500">
              Esta apertura pertenece a <b>{session.opened_by}</b>. Solo esa persona o un administrador pueden completarla.
            </div>
          ) : !stocktake ? (
            <div className="card-soft p-10 text-center max-w-lg space-y-3">
              <Loader2 className="w-8 h-8 mx-auto animate-spin text-amber-400" />
              <p className="text-sm text-slate-500">Preparando el recuento de apertura…</p>
            </div>
          ) : (
            <>
              <StocktakeGrid stocktake={stocktake} onUpdated={onStocktakeUpdated} onNext={null} />
              <div className="card-soft p-4 flex flex-wrap items-center justify-between gap-3">
                <p className="text-xs text-slate-500">
                  {openingPendientes > 0
                    ? `Quedan ${openingPendientes} productos pendientes de contar.`
                    : "Todo contado. Al confirmar, lo contado pasa a ser el stock del sistema."}
                </p>
                <button onClick={confirmOpening} disabled={confirmingOpen || openingPendientes > 0} className="btn-secondary" data-testid="opening-confirm-btn">
                  {confirmingOpen ? <Loader2 className="w-4 h-4 animate-spin" /> : <LockOpen className="w-4 h-4" />}
                  Confirmar apertura del turno
                </button>
              </div>
            </>
          )}
        </div>
      ) : session.status === "open" ? (
        <>
          <div className="flex items-center gap-2 text-xs text-slate-500 flex-wrap">
            <span className="badge-active">Turno abierto</span>
            <span>Responsable: <b>{session.opened_by}</b> · desde {fmtDateTime(session.opened_at)}</span>
            {!isOwner && user.role === "admin" && <span className="badge-inactive">supervisión de administrador</span>}
            {!canOperate && <span className="badge-inactive">solo lectura: turno de otro voluntario</span>}
            {(session.out_of_shift_count || 0) > 0 && (
              <span className="badge-inactive" data-testid="session-out-of-shift-note">
                incluye {session.out_of_shift_count} ventas fuera de turno ({fmtEUR(session.out_of_shift_total || 0)})
              </span>
            )}
          </div>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4">
            {[
              { label: "Esperado en caja", value: totals.esperado, icon: Scale, bg: "bg-amber-100", fg: "text-amber-700", testid: "cash-expected" },
              { label: "Recargas del turno (efectivo)", value: totals.recargas_efectivo, icon: Coins, bg: "bg-emerald-100", fg: "text-emerald-700", testid: "cash-recargas" },
              { label: `Ventas con saldo (${totals.ventas_count} tickets)`, value: totals.ventas_saldo, icon: ShoppingBag, bg: "bg-purple-100", fg: "text-purple-700", testid: "cash-ventas-saldo" },
              { label: "Deuda de socios", value: totals.deuda_socios, icon: AlertTriangle, bg: "bg-red-100", fg: "text-red-600", testid: "cash-deuda" },
            ].map((c) => (
              <div key={c.label} className="card-soft p-4 sm:p-5" data-testid={c.testid}>
                <div className={`w-9 h-9 rounded-xl ${c.bg} ${c.fg} flex items-center justify-center mb-3`}>
                  <c.icon style={{ width: 18, height: 18 }} />
                </div>
                <p className="font-display text-2xl font-extrabold text-slate-900">{fmtEUR(c.value)}</p>
                <p className="text-xs font-semibold uppercase tracking-wider text-slate-500 mt-1">{c.label}</p>
              </div>
            ))}
          </div>

          <div className="card-soft p-5" data-testid="cash-movements-list">
            <h2 className="font-display text-lg font-semibold text-slate-900 mb-3">Movimientos manuales del turno</h2>
            {totals.movements.length === 0 ? (
              <p className="text-sm text-slate-400 py-4 text-center">Sin movimientos manuales todavía.</p>
            ) : (
              <div className="divide-y divide-slate-100">
                {totals.movements.map((m) => (
                  <div key={m.id} className="py-2.5 flex items-center gap-3" data-testid={`movement-${m.id}`}>
                    <span className={`w-8 h-8 rounded-lg flex items-center justify-center ${m.type === "in" ? "bg-emerald-100 text-emerald-600" : "bg-red-100 text-red-500"}`}>
                      {m.type === "in" ? <ArrowDownLeft className="w-4 h-4" /> : <ArrowUpRight className="w-4 h-4" />}
                    </span>
                    <div className="flex-1">
                      <p className="text-sm font-semibold text-slate-800">{m.reason}</p>
                      <p className="text-xs text-slate-400">{m.created_by} · {fmtDateTime(m.created_at)}</p>
                    </div>
                    <span className={`font-mono-num font-bold ${m.type === "in" ? "text-emerald-600" : "text-red-500"}`}>
                      {m.type === "in" ? "+" : "−"}{fmtEUR(m.amount)}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </>
      ) : (
        <div className="space-y-5" data-testid="closing-wizard">
          <div className="card-soft p-4 flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-sm font-bold text-slate-900 flex items-center gap-2">
                <ClipboardCheck className="w-4 h-4 text-amber-500" /> Cierre en curso · turno de {session.opened_by}
              </p>
              <p className="text-xs text-slate-500 mt-0.5">La caja sigue ocupada: ventas, recargas y ajustes de stock están bloqueados hasta terminar.</p>
            </div>
            <div className="flex items-center gap-3">
              <Stepper step={step} steps={CLOSING_STEPS} testid="closing-stepper" />
              {user.role === "admin" && (
                <AlertDialog>
                  <AlertDialogTrigger asChild>
                    <button className="btn-outline text-red-600 border-red-200 py-2 text-xs" data-testid="closing-cancel-btn">
                      <Undo2 className="w-3.5 h-3.5" /> Cancelar cierre
                    </button>
                  </AlertDialogTrigger>
                  <AlertDialogContent>
                    <AlertDialogHeader>
                      <AlertDialogTitle>¿Cancelar el cierre en curso?</AlertDialogTitle>
                      <AlertDialogDescription>
                        Acción administrativa auditada: el turno vuelve a estar abierto y el borrador de arqueo y recuento queda invalidado. Nunca convierte un recuento incompleto en cierre.
                      </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                      <AlertDialogCancel>Volver</AlertDialogCancel>
                      <AlertDialogAction onClick={cancelClosing} className="bg-red-500 hover:bg-red-600" data-testid="closing-cancel-confirm">Cancelar el cierre</AlertDialogAction>
                    </AlertDialogFooter>
                  </AlertDialogContent>
                </AlertDialog>
              )}
            </div>
          </div>

          {!canOperate ? (
            <div className="card-soft p-10 text-center text-sm text-slate-500">
              Este cierre pertenece a <b>{session.opened_by}</b>. Solo esa persona o un administrador pueden completarlo.
            </div>
          ) : !session.cash_count ? (
            <ArqueoStep totals={totals} onSaved={load} />
          ) : !stocktake ? (
            <div className="card-soft p-10 text-center max-w-lg space-y-3" data-testid="stocktake-prepare">
              <PackageSearch className="w-10 h-10 mx-auto text-amber-400" />
              <h2 className="font-display text-xl font-bold text-slate-900">Efectivo listo. Ahora toca el stock.</h2>
              <p className="text-sm text-slate-500">Se creará un recuento con todos los productos activos y cualquiera con existencias, agrupado por secciones (categorías actuales).</p>
              <button onClick={ensureStocktake} className="btn-primary mx-auto" data-testid="stocktake-start-btn">Preparar recuento de stock</button>
            </div>
          ) : step === 2 ? (
            <StocktakeGrid stocktake={stocktake} onUpdated={onStocktakeUpdated} onNext={() => setStep(3)} />
          ) : (
            <div className="space-y-4">
              <button onClick={() => setStep(2)} className="btn-outline py-2 text-sm" data-testid="review-back-btn">Volver al recuento</button>
              <ReviewStep session={session} stocktake={stocktake} onFinalized={() => load()} />
            </div>
          )}
        </div>
      )}

      {user.role === "admin" && (
        <div className="card-soft p-5" data-testid="cash-history">
          <h2 className="font-display text-lg font-semibold text-slate-900 mb-3">Turnos cerrados</h2>
          {history.length === 0 ? (
            <p className="text-sm text-slate-400 py-4 text-center">Todavía no hay turnos cerrados.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-xs uppercase tracking-wider text-slate-500 border-b border-slate-200">
                    <th className="py-2 pr-4">Turno</th>
                    <th className="py-2 pr-4">Responsable</th>
                    <th className="py-2 pr-4">Cerrado por</th>
                    <th className="py-2 pr-4 text-right">Esperado</th>
                    <th className="py-2 pr-4 text-right">Contado</th>
                    <th className="py-2 text-right">Diferencia</th>
                    <th className="py-2 w-10"></th>
                  </tr>
                </thead>
                <tbody>
                  {history.map((s) => (
                    <tr key={s.id} onClick={() => setReportId(s.id)} className="border-b border-slate-100 hover:bg-amber-50/40 cursor-pointer transition-colors" data-testid={`cash-session-${s.id}`}>
                      <td className="py-2.5 pr-4 text-slate-600">{fmtDateTime(s.opened_at)} → {fmtDateTime(s.closed_at)}</td>
                      <td className="py-2.5 pr-4 text-slate-700 font-medium">{s.opened_by}</td>
                      <td className="py-2.5 pr-4 text-slate-600">{s.closed_by}{s.supervised ? " (supervisado)" : ""}</td>
                      <td className="py-2.5 pr-4 text-right font-mono-num">{s.expected_amount !== undefined ? fmtEUR(s.expected_amount) : "—"}</td>
                      <td className="py-2.5 pr-4 text-right font-mono-num">{s.counted_amount !== undefined ? fmtEUR(s.counted_amount) : "—"}</td>
                      <td className={`py-2.5 text-right font-mono-num font-bold ${Math.abs(s.difference || 0) < 0.005 ? "text-emerald-600" : "text-red-500"}`}>
                        {s.difference > 0 ? "+" : ""}{fmtEUR(s.difference || 0)}
                      </td>
                      <td className="py-2.5 text-right">
                        <button
                          onClick={(e) => { e.stopPropagation(); downloadClosingPdf(s).catch((err) => toast.error(apiError(err, "No se pudo generar el PDF"))); }}
                          title="Descargar resumen en PDF"
                          data-testid={`cash-session-pdf-${s.id}`}
                          className="p-1.5 rounded-lg text-slate-400 hover:text-amber-700 hover:bg-amber-50 transition-colors"
                        >
                          <FileText className="w-4 h-4" />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* Diálogo movimiento manual */}
      <Dialog open={!!movDialog} onOpenChange={() => setMovDialog(null)}>
        <DialogContent className="max-w-xs" data-testid="cash-movement-dialog">
          <DialogHeader>
            <DialogTitle className="font-display">{movDialog === "in" ? "Entrada de efectivo" : "Salida de efectivo"}</DialogTitle>
          </DialogHeader>
          {movDialog === "out" && totals && (
            <p className="text-xs text-slate-500">Disponible en caja: <span className="font-mono-num font-bold">{fmtEUR(totals.esperado)}</span></p>
          )}
          <label className="text-xs font-semibold uppercase tracking-wider text-slate-500">Importe (Cr)</label>
          <input type="number" min="0" step="0.01" value={movAmount} onChange={(e) => setMovAmount(e.target.value)} data-testid="cash-movement-amount-input"
            className="w-full px-4 py-3 rounded-xl border border-slate-300 focus:outline-none focus:ring-2 focus:ring-amber-400" />
          <label className="text-xs font-semibold uppercase tracking-wider text-slate-500">Motivo (obligatorio)</label>
          <input value={movReason} onChange={(e) => setMovReason(e.target.value)} placeholder="Ej: compra de papel, ingreso banco…" data-testid="cash-movement-reason-input"
            className="w-full px-4 py-3 rounded-xl border border-slate-300 focus:outline-none focus:ring-2 focus:ring-amber-400" />
          <button onClick={doMovement} disabled={!movAmount || !movReason.trim()} className={`w-full ${movDialog === "in" ? "btn-secondary" : "btn-primary"}`} data-testid="cash-movement-confirm-btn">
            Registrar movimiento
          </button>
        </DialogContent>
      </Dialog>

      <ReportDialog sessionId={reportId} open={!!reportId} onClose={() => setReportId(null)} />
    </div>
  );
}
