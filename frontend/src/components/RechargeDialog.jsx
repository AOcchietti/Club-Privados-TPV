import { useEffect, useState } from "react";
import { toast } from "sonner";
import api, { fmtEUR, apiError } from "@/lib/api";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Banknote, CreditCard, Loader2 } from "lucide-react";

const QUICK = [10, 20, 50, 100];

export default function RechargeDialog({ socio, open, onClose, onDone }) {
  const [amount, setAmount] = useState("20");
  const [method, setMethod] = useState("efectivo");
  const [saving, setSaving] = useState(false);
  const [cash, setCash] = useState(undefined); // undefined = cargando, null = sin turno abierto

  useEffect(() => {
    if (open) {
      setAmount("20");
      setMethod("efectivo");
      setCash(undefined);
      api.get("/cash/current").then((r) => setCash(r.data.session)).catch(() => setCash(null));
    }
  }, [open]);

  const paused = cash && cash.status !== "open";

  if (!socio) return null;

  const recharge = async () => {
    setSaving(true);
    try {
      const res = await api.post(`/users/${socio.id}/recharge`, { amount: parseFloat(amount) || 0, method });
      toast.success(
        res.data.recharge_out_of_shift
          ? `Saldo recargado (fuera de turno) · ${socio.name} ahora tiene ${fmtEUR(res.data.balance)}. El efectivo se sumará al próximo turno.`
          : `Saldo recargado · ${socio.name} ahora tiene ${fmtEUR(res.data.balance)}`
      );
      onDone?.(res.data);
      onClose();
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setSaving(false);
    }
  };

  const newBalance = (socio.balance || 0) + (parseFloat(amount) || 0);

  return (
    <Dialog open={open} onOpenChange={onClose}>
      <DialogContent className="max-w-xs" data-testid="recharge-dialog">
        <DialogHeader>
          <DialogTitle className="font-display">Recargar saldo</DialogTitle>
        </DialogHeader>
        <p className="text-sm text-slate-600 -mt-1">
          {socio.name} · saldo actual{" "}
          <span className={`font-mono-num font-bold ${(socio.balance || 0) < 0 ? "text-red-600" : "text-emerald-700"}`}>{fmtEUR(socio.balance || 0)}</span>
        </p>
        <div className="grid grid-cols-4 gap-2">
          {QUICK.map((a) => (
            <button
              key={a}
              onClick={() => setAmount(String(a))}
              data-testid={`recharge-quick-${a}`}
              className={`py-2 rounded-xl text-sm font-bold border transition-colors ${
                parseFloat(amount) === a
                  ? "bg-emerald-600 text-white border-emerald-600"
                  : "bg-white text-slate-600 border-slate-200 hover:border-emerald-400"
              }`}
            >
              {a}
            </button>
          ))}
        </div>
        <input
          type="number"
          min="0"
          step="0.5"
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
          data-testid="recharge-amount-input"
          className="w-full px-4 py-3 rounded-xl border border-slate-300 focus:outline-none focus:ring-2 focus:ring-emerald-400 font-mono-num font-bold text-lg text-center"
        />
        {cash === null ? (
          <p className="text-xs text-sky-800 bg-sky-50 border border-sky-200 rounded-xl px-3 py-2 flex items-start gap-2" data-testid="recharge-out-of-shift-note">
            <Banknote className="w-4 h-4 text-sky-600 shrink-0 mt-0.5" />
            <span>No hay turno abierto: el saldo se carga ya y el efectivo se sumará a la caja del <b>próximo turno</b>. Guárdalo aparte, sin mezclarlo con el fondo.</span>
          </p>
        ) : paused ? (
          <p className="text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded-xl px-3 py-2 flex items-center gap-2" data-testid="recharge-paused-note">
            <Banknote className="w-4 h-4 text-amber-600 shrink-0" /> La caja está en {cash.status === "opening" ? "apertura" : "cierre"}: espera a que termine para recargar.
          </p>
        ) : (
          <p className="text-xs text-slate-500 bg-slate-50 border border-slate-200 rounded-xl px-3 py-2 flex items-center gap-2">
            <Banknote className="w-4 h-4 text-emerald-600 shrink-0" /> Las recargas se hacen siempre en efectivo y entran en la caja del turno abierto.
          </p>
        )}
        <div className="bg-emerald-50 border border-emerald-200 rounded-xl px-4 py-2.5 text-sm flex justify-between">
          <span className="text-emerald-800">Nuevo saldo</span>
          <span className="font-mono-num font-bold text-emerald-700" data-testid="recharge-new-balance">
            {fmtEUR(newBalance)}
          </span>
        </div>
        <button
          onClick={recharge}
          disabled={saving || paused || cash === undefined || !(parseFloat(amount) > 0)}
          className="btn-secondary w-full"
          data-testid="recharge-confirm-btn"
        >
          {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
          Confirmar recarga
        </button>
      </DialogContent>
    </Dialog>
  );
}
