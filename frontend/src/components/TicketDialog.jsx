import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { fmtEUR, fmtDateTime } from "@/lib/api";
import { Citrus } from "lucide-react";

export default function TicketDialog({ sale, open, onClose }) {
  if (!sale) return null;
  return (
    <Dialog open={open} onOpenChange={onClose}>
      <DialogContent className="max-w-sm" data-testid="ticket-dialog">
        <DialogHeader>
          <DialogTitle className="font-display flex items-center gap-2">
            <Citrus className="w-5 h-5 text-amber-500" /> Ticket {sale.ticket_number}
          </DialogTitle>
        </DialogHeader>
        <div className="text-sm space-y-3">
          <div className="text-center border-b border-dashed border-slate-300 pb-3">
            <p className="font-display font-bold text-slate-900">Weed Lemon Social Club</p>
            <p className="text-xs text-slate-500">Demetrio de los Ríos, 5 · Sevilla</p>
            <p className="text-xs text-slate-500 mt-1">{fmtDateTime(sale.created_at)} · {sale.cajero_name}</p>
          </div>
          <div className="space-y-1.5">
            {sale.items.map((i, idx) => (
              <div key={idx} className="flex justify-between gap-2">
                <span className="text-slate-700">
                  {i.name} <span className="text-slate-400 text-xs">× {i.qty}{i.unit}</span>
                </span>
                <span className="font-mono-num text-slate-900">{fmtEUR(i.line_total)}</span>
              </div>
            ))}
          </div>
          {sale.socio_name && (
            <p className="text-xs text-slate-500 border-t border-dashed border-slate-300 pt-2">
              Socio: <span className="font-semibold text-slate-700">{sale.socio_name}</span>
              {sale.socio_member_number ? ` · ${sale.socio_member_number}` : ""}
            </p>
          )}
          <div className="border-t border-dashed border-slate-300 pt-3 flex justify-between items-center">
            <span className="text-xs uppercase tracking-wider font-semibold text-slate-500">
              Total · {sale.payment_method}
            </span>
            <span className="font-display text-2xl font-extrabold text-amber-600" data-testid="ticket-total">
              {fmtEUR(sale.total)}
            </span>
          </div>
          <p className="text-center text-xs text-slate-400 pt-1 flex items-center justify-center gap-1">
            Gracias por tu visita <Citrus className="w-3.5 h-3.5 text-amber-400" />
          </p>
        </div>
      </DialogContent>
    </Dialog>
  );
}
