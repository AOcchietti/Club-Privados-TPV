import { useEffect, useState } from "react";
import { toast } from "sonner";
import api, { fmtEUR, fmtDateTime, apiError } from "@/lib/api";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Wallet, ArrowUpRight, ArrowDownLeft, Lock, LockOpen, Scale, Coins, ShoppingBag, AlertTriangle } from "lucide-react";

export default function Caja() {
  const [data, setData] = useState(null);
  const [history, setHistory] = useState([]);
  const [openDialog, setOpenDialog] = useState(false);
  const [closeDialog, setCloseDialog] = useState(false);
  const [movDialog, setMovDialog] = useState(null); // 'in' | 'out'
  const [starting, setStarting] = useState("100");
  const [counted, setCounted] = useState("");
  const [notes, setNotes] = useState("");
  const [movAmount, setMovAmount] = useState("");
  const [movReason, setMovReason] = useState("");

  const load = () => {
    api.get("/cash/current").then((r) => setData(r.data)).catch(() => {});
    api.get("/cash/sessions").then((r) => setHistory(r.data)).catch(() => {});
  };
  useEffect(() => { load(); }, []);

  const session = data?.session;
  const totals = data?.totals;

  const doOpen = async () => {
    try {
      await api.post("/cash/open", { starting_amount: parseFloat(starting) || 0 });
      toast.success("Caja abierta con éxito");
      setOpenDialog(false);
      load();
    } catch (e) { toast.error(apiError(e)); }
  };

  const doClose = async () => {
    try {
      await api.post("/cash/close", { counted_amount: parseFloat(counted) || 0, notes });
      toast.success("Caja cerrada. Arqueo registrado.");
      setCloseDialog(false);
      setCounted("");
      setNotes("");
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

  return (
    <div className="space-y-5" data-testid="caja-page">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <h1 className="font-display text-3xl sm:text-4xl font-bold tracking-tight text-slate-900">Caja</h1>
          <p className="text-sm text-slate-500 mt-1">Apertura, movimientos y arqueo del turno.</p>
        </div>
        {session ? (
          <div className="flex gap-2">
            <button onClick={() => setMovDialog("in")} className="btn-outline text-emerald-700 border-emerald-300 bg-emerald-50" data-testid="cash-in-btn">
              <ArrowDownLeft className="w-4 h-4" /> Entrada
            </button>
            <button onClick={() => setMovDialog("out")} className="btn-outline text-red-600 border-red-200 bg-red-50" data-testid="cash-out-btn">
              <ArrowUpRight className="w-4 h-4" /> Salida
            </button>
            <button onClick={() => setCloseDialog(true)} className="btn-primary" data-testid="cash-close-shift-btn">
              <Lock className="w-4 h-4" /> Cerrar caja
            </button>
          </div>
        ) : (
          <button onClick={() => setOpenDialog(true)} className="btn-secondary" data-testid="cash-open-shift-btn">
            <LockOpen className="w-4 h-4" /> Abrir caja
          </button>
        )}
      </div>

      {!session ? (
        <div className="card-soft p-14 text-center" data-testid="cash-closed-state">
          <div className="w-16 h-16 rounded-2xl bg-slate-100 flex items-center justify-center mx-auto mb-4">
            <Wallet className="w-8 h-8 text-slate-400" />
          </div>
          <h2 className="font-display text-xl font-bold text-slate-900">La caja está cerrada</h2>
          <p className="text-sm text-slate-500 mt-1 mb-6">Abre un turno para empezar a registrar ventas y movimientos.</p>
          <button onClick={() => setOpenDialog(true)} className="btn-secondary mx-auto">
            <LockOpen className="w-4 h-4" /> Abrir turno de caja
          </button>
        </div>
      ) : (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4">
            {[
              { label: "Esperado en caja", value: totals.esperado, icon: Scale, bg: "bg-amber-100", fg: "text-amber-700", testid: "cash-expected" },
              { label: "Recargas del turno", value: totals.recargas, icon: Coins, bg: "bg-emerald-100", fg: "text-emerald-700", testid: "cash-recargas" },
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
            <div className="flex items-center justify-between mb-3">
              <h2 className="font-display text-lg font-semibold text-slate-900">Movimientos del turno</h2>
              <span className="text-xs text-slate-400">Abierta por {session.opened_by} · {fmtDateTime(session.opened_at)} · Recargas de saldo: {fmtEUR(totals.recargas || 0)}</span>
            </div>
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
      )}

      <div className="card-soft p-5" data-testid="cash-history">
        <h2 className="font-display text-lg font-semibold text-slate-900 mb-3">Arqueos anteriores</h2>
        {history.length === 0 ? (
          <p className="text-sm text-slate-400 py-4 text-center">Todavía no hay turnos cerrados.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs uppercase tracking-wider text-slate-500 border-b border-slate-200">
                  <th className="py-2 pr-4">Turno</th>
                  <th className="py-2 pr-4">Cajero</th>
                  <th className="py-2 pr-4 text-right">Ventas</th>
                  <th className="py-2 pr-4 text-right">Esperado</th>
                  <th className="py-2 pr-4 text-right">Contado</th>
                  <th className="py-2 text-right">Diferencia</th>
                </tr>
              </thead>
              <tbody>
                {history.map((s) => (
                  <tr key={s.id} className="border-b border-slate-100" data-testid={`cash-session-${s.id}`}>
                    <td className="py-2.5 pr-4 text-slate-600">{fmtDateTime(s.opened_at)} → {fmtDateTime(s.closed_at)}</td>
                    <td className="py-2.5 pr-4 text-slate-700 font-medium">{s.closed_by}</td>
                    <td className="py-2.5 pr-4 text-right font-mono-num">{fmtEUR((s.totals?.efectivo || 0) + (s.totals?.tarjeta || 0))}</td>
                    <td className="py-2.5 pr-4 text-right font-mono-num">{fmtEUR(s.expected_amount)}</td>
                    <td className="py-2.5 pr-4 text-right font-mono-num">{fmtEUR(s.counted_amount)}</td>
                    <td className={`py-2.5 text-right font-mono-num font-bold ${Math.abs(s.difference) < 0.01 ? "text-emerald-600" : "text-red-500"}`}>
                      {s.difference > 0 ? "+" : ""}{fmtEUR(s.difference)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Diálogo abrir */}
      <Dialog open={openDialog} onOpenChange={setOpenDialog}>
        <DialogContent className="max-w-xs">
          <DialogHeader><DialogTitle className="font-display">Abrir caja</DialogTitle></DialogHeader>
          <label className="text-xs font-semibold uppercase tracking-wider text-slate-500">Fondo inicial (créditos)</label>
          <input type="number" min="0" value={starting} onChange={(e) => setStarting(e.target.value)} data-testid="cash-open-amount-input"
            className="w-full px-4 py-3 rounded-xl border border-slate-300 focus:outline-none focus:ring-2 focus:ring-amber-400" />
          <button onClick={doOpen} className="btn-primary w-full" data-testid="cash-open-confirm-btn">Abrir turno</button>
        </DialogContent>
      </Dialog>

      {/* Diálogo cerrar */}
      <Dialog open={closeDialog} onOpenChange={setCloseDialog}>
        <DialogContent className="max-w-xs" data-testid="cash-close-dialog">
          <DialogHeader><DialogTitle className="font-display">Cerrar caja · Arqueo</DialogTitle></DialogHeader>
          <div className="bg-amber-50 border border-amber-200 rounded-xl px-4 py-3 text-sm">
            Esperado en caja: <span className="font-mono-num font-bold text-amber-700">{fmtEUR(totals?.esperado)}</span>
          </div>
          <label className="text-xs font-semibold uppercase tracking-wider text-slate-500">Efectivo contado (créditos)</label>
          <input type="number" min="0" step="0.01" value={counted} onChange={(e) => setCounted(e.target.value)} data-testid="cash-counted-input"
            className="w-full px-4 py-3 rounded-xl border border-slate-300 focus:outline-none focus:ring-2 focus:ring-amber-400" />
          <label className="text-xs font-semibold uppercase tracking-wider text-slate-500">Notas (opcional)</label>
          <input value={notes} onChange={(e) => setNotes(e.target.value)}
            className="w-full px-4 py-3 rounded-xl border border-slate-300 focus:outline-none focus:ring-2 focus:ring-amber-400" />
          <button onClick={doClose} className="btn-primary w-full" data-testid="cash-close-confirm-btn">Confirmar cierre</button>
        </DialogContent>
      </Dialog>

      {/* Diálogo movimiento */}
      <Dialog open={!!movDialog} onOpenChange={() => setMovDialog(null)}>
        <DialogContent className="max-w-xs" data-testid="cash-movement-dialog">
          <DialogHeader>
            <DialogTitle className="font-display">{movDialog === "in" ? "Entrada de efectivo" : "Salida de efectivo"}</DialogTitle>
          </DialogHeader>
          <label className="text-xs font-semibold uppercase tracking-wider text-slate-500">Importe (créditos)</label>
          <input type="number" min="0" step="0.01" value={movAmount} onChange={(e) => setMovAmount(e.target.value)} data-testid="cash-movement-amount-input"
            className="w-full px-4 py-3 rounded-xl border border-slate-300 focus:outline-none focus:ring-2 focus:ring-amber-400" />
          <label className="text-xs font-semibold uppercase tracking-wider text-slate-500">Motivo</label>
          <input value={movReason} onChange={(e) => setMovReason(e.target.value)} placeholder="Ej: compra de papel, ingreso banco…" data-testid="cash-movement-reason-input"
            className="w-full px-4 py-3 rounded-xl border border-slate-300 focus:outline-none focus:ring-2 focus:ring-amber-400" />
          <button onClick={doMovement} disabled={!movAmount || !movReason} className={`w-full ${movDialog === "in" ? "btn-secondary" : "btn-primary"}`} data-testid="cash-movement-confirm-btn">
            Registrar movimiento
          </button>
        </DialogContent>
      </Dialog>
    </div>
  );
}
