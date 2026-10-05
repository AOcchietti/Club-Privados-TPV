import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import api, { apiError, fmtDate, fmtEUR, BACKEND, fileUrl, uploadPublicPhoto } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import RechargeDialog from "@/components/RechargeDialog";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger } from "@/components/ui/alert-dialog";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Users, Plus, Pencil, Trash2, Search, UserRound, Coins, ShoppingBag, Eye, QrCode, Copy, FileText, UploadCloud, Loader2 } from "lucide-react";

const EMPTY_SOCIO = { name: "", apellidos: "", doc_type: "DNI", doc_number: "", nationality: "", birthdate: "", phone: "", email: "", role: "socio", status: "activa" };
const EMPTY_STAFF = { name: "", email: "", password: "", role: "cajero", status: "activa" };
const DOC_TYPES = ["DNI", "NIE", "Pasaporte", "Otro"];

const ROLE_BADGE = {
  admin: "bg-purple-100 text-purple-800 border-purple-200",
  cajero: "bg-amber-100 text-amber-800 border-amber-200",
  socio: "bg-emerald-100 text-emerald-800 border-emerald-200",
};

function KycPhotoUpload({ label, value, onUploaded, testid }) {
  const [uploading, setUploading] = useState(false);
  const pick = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      onUploaded(await uploadPublicPhoto(file));
    } catch (err) {
      toast.error(apiError(err, "No se pudo subir la imagen"));
    } finally {
      setUploading(false);
    }
  };
  return (
    <label className={`flex items-center gap-2 rounded-xl border px-3 py-2 cursor-pointer text-xs transition-colors ${value ? "border-emerald-300 bg-emerald-50 text-emerald-700 font-bold" : "border-slate-300 bg-white text-slate-500 hover:border-amber-400"}`} data-testid={testid}>
      {uploading ? <Loader2 className="w-4 h-4 animate-spin" /> : value ? <Eye className="w-4 h-4" /> : <UploadCloud className="w-4 h-4" />}
      {value ? `${label} ✓` : label}
      <input type="file" accept="image/*" className="hidden" onChange={pick} data-testid={`${testid}-input`} />
    </label>
  );
}

function AltaQrCard({ isAdmin }) {
  const [legal, setLegal] = useState(null);
  const [uploading, setUploading] = useState(false);
  const altaUrl = `${window.location.origin}/alta`;
  const load = () => api.get("/public/legal").then((r) => setLegal(r.data)).catch(() => {});
  useEffect(() => { load(); }, []);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(altaUrl);
      toast.success("Enlace del formulario copiado");
    } catch {
      toast.info(altaUrl);
    }
  };

  const uploadLegal = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      await api.post("/settings/legal-pdf", fd, { headers: { "Content-Type": "multipart/form-data" } });
      toast.success("Acuerdo legal actualizado: ya está disponible en el formulario");
      load();
    } catch (err) {
      toast.error(apiError(err));
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="card-soft p-5 flex flex-col sm:flex-row gap-5 items-start" data-testid="alta-qr-card">
      <img src={`${BACKEND}/api/alta/qr.png?url=${encodeURIComponent(altaUrl)}`} alt="QR de alta"
        className="w-32 h-32 rounded-xl border border-slate-200 bg-white p-1.5" data-testid="alta-qr-image" />
      <div className="flex-1 space-y-2">
        <h2 className="font-display text-lg font-bold text-slate-900 flex items-center gap-2">
          <QrCode className="w-5 h-5 text-amber-500" /> Alta de socios con QR
        </h2>
        <p className="text-xs text-slate-500">
          Imprime este QR y pégalo en el club: quien lo escanee rellena el formulario completo (datos, fotos, firma y acuerdo legal)
          y su solicitud llegará aquí con estado <b>pendiente</b> hasta que la actives.
        </p>
        <div className="flex gap-2 flex-wrap">
          <button onClick={copy} className="btn-outline py-2 text-xs" data-testid="alta-copy-link-btn">
            <Copy className="w-3.5 h-3.5" /> Copiar enlace del formulario
          </button>
          <a href={altaUrl} target="_blank" rel="noreferrer" className="btn-outline py-2 text-xs" data-testid="alta-open-form-btn">
            Abrir formulario
          </a>
          {isAdmin && (
            <label className="btn-outline py-2 text-xs cursor-pointer" data-testid="legal-upload-btn">
              {uploading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <FileText className="w-3.5 h-3.5" />}
              {legal?.available ? "Actualizar acuerdo legal (PDF)" : "Subir acuerdo legal (PDF)"}
              <input type="file" accept="application/pdf" className="hidden" onChange={uploadLegal} data-testid="legal-upload-input" />
            </label>
          )}
        </div>
        <p className={`text-[11px] font-semibold ${legal?.available ? "text-emerald-600" : "text-amber-600"}`} data-testid="legal-status">
          {legal?.available
            ? `Acuerdo legal publicado · actualizado ${fmtDate(legal.updated_at)}`
            : "Todavía no hay acuerdo legal en PDF: el formulario lo indica y permite enviar igualmente."}
        </p>
      </div>
    </div>
  );
}

function UserDialog({ open, onClose, editing, defaultRole, isAdmin, onSaved }) {
  const isStaffForm = (editing ? editing.role : defaultRole) !== "socio";
  const [form, setForm] = useState(EMPTY_SOCIO);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open) {
      if (editing) setForm({ ...editing, password: "" });
      else setForm(defaultRole === "socio" ? EMPTY_SOCIO : EMPTY_STAFF);
    }
  }, [open, editing, defaultRole]);

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const save = async () => {
    setSaving(true);
    try {
      const payload = { ...form };
      if (!payload.password) delete payload.password;
      if (!payload.email) delete payload.email;
      if (editing) {
        await api.patch(`/users/${editing.id}`, payload);
        toast.success("Ficha actualizada");
      } else {
        await api.post("/users", payload);
        toast.success(isStaffForm ? "Miembro del equipo creado" : "Socio dado de alta");
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
      <DialogContent className="max-w-md" data-testid="user-dialog">
        <DialogHeader>
          <DialogTitle className="font-display">
            {editing ? "Editar ficha" : isStaffForm ? "Nuevo miembro del equipo" : "Alta de socio"}
          </DialogTitle>
        </DialogHeader>
        <div className="grid grid-cols-2 gap-3">
          <div className="col-span-2">
            <label className="text-xs font-semibold uppercase tracking-wider text-slate-500 block mb-1">Nombre completo</label>
            <input value={form.name} onChange={set("name")} data-testid="user-name-input" className="w-full px-3.5 py-2.5 rounded-xl border border-slate-300 focus:outline-none focus:ring-2 focus:ring-amber-400" />
          </div>
          {isStaffForm ? (
            <>
              <div>
                <label className="text-xs font-semibold uppercase tracking-wider text-slate-500 block mb-1">Email</label>
                <input type="email" value={form.email || ""} onChange={set("email")} data-testid="user-email-input" className="w-full px-3.5 py-2.5 rounded-xl border border-slate-300 focus:outline-none focus:ring-2 focus:ring-amber-400" />
              </div>
              <div>
                <label className="text-xs font-semibold uppercase tracking-wider text-slate-500 block mb-1">{editing ? "Nueva contraseña (opcional)" : "Contraseña"}</label>
                <input type="password" value={form.password || ""} onChange={set("password")} data-testid="user-password-input" className="w-full px-3.5 py-2.5 rounded-xl border border-slate-300 focus:outline-none focus:ring-2 focus:ring-amber-400" />
              </div>
              {isAdmin && (
                <div>
                  <label className="text-xs font-semibold uppercase tracking-wider text-slate-500 block mb-1">Rol</label>
                  <select value={form.role} onChange={set("role")} data-testid="user-role-select" className="w-full px-3.5 py-2.5 rounded-xl border border-slate-300 bg-white focus:outline-none focus:ring-2 focus:ring-amber-400">
                    <option value="cajero">Cajero</option>
                    <option value="admin">Administrador</option>
                  </select>
                </div>
              )}
              {editing?.member_number && (
                <div>
                  <label className="text-xs font-semibold uppercase tracking-wider text-slate-500 block mb-1">Nº de socio vinculado</label>
                  <input value={editing.member_number} disabled className="w-full px-3.5 py-2.5 rounded-xl border border-slate-200 bg-slate-50 font-mono-num text-slate-500" />
                </div>
              )}
            </>
          ) : (
            <>
              <div>
                <label className="text-xs font-semibold uppercase tracking-wider text-slate-500 block mb-1">Apellidos</label>
                <input value={form.apellidos || ""} onChange={set("apellidos")} data-testid="user-apellidos-input" className="w-full px-3.5 py-2.5 rounded-xl border border-slate-300 focus:outline-none focus:ring-2 focus:ring-amber-400" />
              </div>
              <div>
                <label className="text-xs font-semibold uppercase tracking-wider text-slate-500 block mb-1">Tipo de documento</label>
                <select value={form.doc_type || "DNI"} onChange={set("doc_type")} data-testid="user-doc-type-select" className="w-full px-3.5 py-2.5 rounded-xl border border-slate-300 bg-white focus:outline-none focus:ring-2 focus:ring-amber-400">
                  {DOC_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
                </select>
              </div>
              <div>
                <label className="text-xs font-semibold uppercase tracking-wider text-slate-500 block mb-1">Nº de documento</label>
                <input value={form.doc_number || ""} onChange={set("doc_number")} data-testid="user-doc-number-input" className="w-full px-3.5 py-2.5 rounded-xl border border-slate-300 focus:outline-none focus:ring-2 focus:ring-amber-400" />
              </div>
              <div>
                <label className="text-xs font-semibold uppercase tracking-wider text-slate-500 block mb-1">Nacionalidad</label>
                <input value={form.nationality || ""} onChange={set("nationality")} data-testid="user-nationality-input" className="w-full px-3.5 py-2.5 rounded-xl border border-slate-300 focus:outline-none focus:ring-2 focus:ring-amber-400" />
              </div>
              <div>
                <label className="text-xs font-semibold uppercase tracking-wider text-slate-500 block mb-1">Fecha de nacimiento</label>
                <input type="date" value={form.birthdate || ""} onChange={set("birthdate")} data-testid="user-birthdate-input" className="w-full px-3.5 py-2.5 rounded-xl border border-slate-300 bg-white focus:outline-none focus:ring-2 focus:ring-amber-400" />
              </div>
              <div>
                <label className="text-xs font-semibold uppercase tracking-wider text-slate-500 block mb-1">Teléfono</label>
                <input value={form.phone || ""} onChange={set("phone")} className="w-full px-3.5 py-2.5 rounded-xl border border-slate-300 focus:outline-none focus:ring-2 focus:ring-amber-400" />
              </div>
              <div className="col-span-2">
                <label className="text-xs font-semibold uppercase tracking-wider text-slate-500 block mb-1">Email (opcional)</label>
                <input type="email" value={form.email || ""} onChange={set("email")} className="w-full px-3.5 py-2.5 rounded-xl border border-slate-300 focus:outline-none focus:ring-2 focus:ring-amber-400" />
              </div>
              <div className="col-span-2 grid grid-cols-3 gap-2">
                <KycPhotoUpload label="Foto documento" value={form.doc_photo} onUploaded={(p) => setForm((f) => ({ ...f, doc_photo: p }))} testid="user-doc-photo-upload" />
                <KycPhotoUpload label="Foto facial" value={form.face_photo} onUploaded={(p) => setForm((f) => ({ ...f, face_photo: p }))} testid="user-face-photo-upload" />
                <KycPhotoUpload label="Firma" value={form.signature} onUploaded={(p) => setForm((f) => ({ ...f, signature: p }))} testid="user-signature-upload" />
              </div>
            </>
          )}
          <div>
            <label className="text-xs font-semibold uppercase tracking-wider text-slate-500 block mb-1">Estado</label>
            <select value={form.status} onChange={set("status")} data-testid="user-status-select" className="w-full px-3.5 py-2.5 rounded-xl border border-slate-300 bg-white focus:outline-none focus:ring-2 focus:ring-amber-400">
              <option value="activa">Activa</option>
              <option value="pendiente">Pendiente</option>
              <option value="expirada">Expirada</option>
              <option value="suspendida">Suspendida</option>
            </select>
          </div>
        </div>
        <button onClick={save} disabled={saving || !form.name} className="btn-primary w-full mt-2" data-testid="user-save-button">
          {saving ? "Guardando…" : editing ? "Guardar cambios" : "Dar de alta"}
        </button>
      </DialogContent>
    </Dialog>
  );
}

export default function Usuarios() {
  const { user } = useAuth();
  const isAdmin = user.role === "admin";
  const [users, setUsers] = useState([]);
  const [q, setQ] = useState("");
  const [tab, setTab] = useState("socios");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [recharging, setRecharging] = useState(null);
  const navigate = useNavigate();

  const load = () => api.get("/users").then((r) => setUsers(r.data)).catch(() => {});
  useEffect(() => { load(); }, []);

  const remove = async (u) => {
    try {
      await api.delete(`/users/${u.id}`);
      toast.success(`«${u.name}» eliminado`);
      load();
    } catch (e) {
      toast.error(apiError(e));
    }
  };

  const socios = users.filter((u) => u.role === "socio");
  const staff = users.filter((u) => u.role !== "socio");
  const filterQ = (list) =>
    list.filter((u) => !q || u.name.toLowerCase().includes(q.toLowerCase()) ||
      (u.apellidos || "").toLowerCase().includes(q.toLowerCase()) ||
      (u.dni || "").toLowerCase().includes(q.toLowerCase()) ||
      (u.doc_number || "").toLowerCase().includes(q.toLowerCase()) ||
      (u.member_number || "").toLowerCase().includes(q.toLowerCase()) ||
      (u.email || "").toLowerCase().includes(q.toLowerCase()));

  const renderTable = (list, isSocio) => (
    <div className="overflow-x-auto">
      <table className="w-full text-sm" data-testid={isSocio ? "socios-table" : "staff-table"}>
        <thead>
          <tr className="text-left text-xs uppercase tracking-wider text-slate-500 border-b border-slate-200 bg-slate-50/60">
            <th className="px-4 py-3">{isSocio ? "Socio" : "Miembro"}</th>
            {isSocio ? <th className="px-4 py-3">Nº socio</th> : <th className="px-4 py-3">Rol · Nº socio</th>}
            <th className="px-4 py-3 text-right">Saldo</th>
            <th className="px-4 py-3">Contacto</th>
            <th className="px-4 py-3">Alta</th>
            <th className="px-4 py-3 text-center">Estado</th>
            <th className="px-4 py-3 text-right">Acciones</th>
          </tr>
        </thead>
        <tbody>
          {filterQ(list).map((u) => (
            <tr key={u.id} className="border-b border-slate-100 hover:bg-amber-50/40 transition-colors" data-testid={`user-row-${u.id}`}>
              <td className="px-4 py-3">
                <div className="flex items-center gap-2.5">
                  <div className="w-8 h-8 rounded-full bg-amber-100 text-amber-700 flex items-center justify-center font-bold text-xs overflow-hidden">
                    {u.face_photo ? (
                      <img src={fileUrl(u.face_photo)} alt={u.name} className="w-full h-full object-cover" />
                    ) : (
                      u.name.charAt(0).toUpperCase()
                    )}
                  </div>
                  <span className="font-semibold text-slate-900">{u.name}{u.apellidos ? ` ${u.apellidos}` : ""}</span>
                </div>
              </td>
              <td className="px-4 py-3">
                {isSocio ? (
                  <span className="font-mono-num text-xs font-bold text-slate-600">{u.member_number}</span>
                ) : (
                  <span className="flex items-center gap-2 flex-wrap">
                    <span className={`text-xs font-medium px-2.5 py-0.5 rounded-full border ${ROLE_BADGE[u.role]}`} data-testid={`user-role-badge-${u.id}`}>{u.role}</span>
                    <span className="font-mono-num text-xs font-bold text-slate-600">{u.member_number}</span>
                  </span>
                )}
              </td>
              <td className={`px-4 py-3 text-right font-mono-num font-bold ${(u.balance || 0) < 0 ? "text-red-600" : "text-emerald-700"}`} data-testid={`user-balance-${u.id}`}>{fmtEUR(u.balance || 0)}</td>
              <td className="px-4 py-3 text-slate-500 text-xs">
                {(u.doc_number || u.dni) && <p>{u.doc_type ? `${u.doc_type} ` : ""}{u.doc_number || u.dni}</p>}
                {u.phone && <p>{u.phone}</p>}
                {u.email && <p>{u.email}</p>}
                {!u.doc_number && !u.dni && !u.phone && !u.email && "—"}
              </td>
              <td className="px-4 py-3 text-slate-500 text-xs">{fmtDate(u.created_at)}</td>
              <td className="px-4 py-3 text-center">
                <span className={
                  u.status === "activa" ? "badge-active"
                  : u.status === "pendiente" ? "inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-bold bg-amber-100 text-amber-800 border border-amber-300"
                  : "badge-inactive"
                } data-testid={`user-status-${u.id}`}>
                  {u.status}
                </span>
              </td>
              <td className="px-4 py-3">
                <div className="flex justify-end gap-1">
                  <button onClick={() => navigate(`/socios/${u.id}`)} title="Ver ficha" data-testid={`user-view-${u.id}`}
                    className="p-2 rounded-lg text-slate-400 hover:text-sky-600 hover:bg-sky-50 transition-colors">
                    <Eye className="w-4 h-4" />
                  </button>
                  <button onClick={() => setRecharging(u)} title="Recargar saldo" data-testid={`user-recharge-${u.id}`}
                    className="p-2 rounded-lg text-slate-400 hover:text-emerald-600 hover:bg-emerald-50 transition-colors">
                    <Coins className="w-4 h-4" />
                  </button>
                  <button onClick={() => navigate(`/tpv?socio=${u.id}`)} title="Vender con su saldo" data-testid={`user-sell-${u.id}`}
                    className="p-2 rounded-lg text-slate-400 hover:text-amber-600 hover:bg-amber-50 transition-colors">
                    <ShoppingBag className="w-4 h-4" />
                  </button>
                  <button onClick={() => { setEditing(u); setDialogOpen(true); }} title="Editar" data-testid={`user-edit-${u.id}`}
                    className="p-2 rounded-lg text-slate-400 hover:text-amber-600 hover:bg-amber-50 transition-colors">
                    <Pencil className="w-4 h-4" />
                  </button>
                  {isAdmin && (
                    <AlertDialog>
                      <AlertDialogTrigger asChild>
                        <button title="Eliminar" data-testid={`user-delete-${u.id}`} className="p-2 rounded-lg text-slate-400 hover:text-red-500 hover:bg-red-50 transition-colors">
                          <Trash2 className="w-4 h-4" />
                        </button>
                      </AlertDialogTrigger>
                      <AlertDialogContent>
                        <AlertDialogHeader>
                          <AlertDialogTitle>¿Eliminar a «{u.name}»?</AlertDialogTitle>
                          <AlertDialogDescription>Se eliminará su ficha del sistema. Esta acción no se puede deshacer.</AlertDialogDescription>
                        </AlertDialogHeader>
                        <AlertDialogFooter>
                          <AlertDialogCancel>Cancelar</AlertDialogCancel>
                          <AlertDialogAction onClick={() => remove(u)} className="bg-red-500 hover:bg-red-600" data-testid="user-delete-confirm">Eliminar</AlertDialogAction>
                        </AlertDialogFooter>
                      </AlertDialogContent>
                    </AlertDialog>
                  )}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {filterQ(list).length === 0 && (
        <div className="py-16 text-center text-slate-400">
          <UserRound className="w-8 h-8 mx-auto mb-2 opacity-50" />
          <p className="text-sm">Nadie por aquí todavía.</p>
        </div>
      )}
    </div>
  );

  return (
    <div className="space-y-5" data-testid="usuarios-page">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <h1 className="font-display text-3xl sm:text-4xl font-bold tracking-tight text-slate-900">Socios y equipo</h1>
          <p className="text-sm text-slate-500 mt-1">{socios.length} socios · {staff.length} miembros del equipo.</p>
        </div>
        <button
          onClick={() => { setEditing(null); setDialogOpen(true); }}
          className="btn-primary"
          data-testid="user-new-button"
        >
          <Plus className="w-4 h-4" /> {tab === "socios" ? "Alta de socio" : "Añadir al equipo"}
        </button>
      </div>

      <div className="relative max-w-sm">
        <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Buscar por nombre, documento o nº de socio…" data-testid="users-search-input"
          className="w-full pl-10 pr-4 py-2.5 rounded-xl border border-slate-300 bg-white focus:outline-none focus:ring-2 focus:ring-amber-400" />
      </div>

      <AltaQrCard isAdmin={isAdmin} />

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList className="bg-white border border-slate-200 rounded-xl p-1">
          <TabsTrigger value="socios" data-testid="tab-socios" className="rounded-lg">Socios ({socios.length})</TabsTrigger>
          {isAdmin && <TabsTrigger value="equipo" data-testid="tab-equipo" className="rounded-lg">Equipo ({staff.length})</TabsTrigger>}
        </TabsList>
        <TabsContent value="socios" className="card-soft mt-3 overflow-hidden">{renderTable(socios, true)}</TabsContent>
        {isAdmin && <TabsContent value="equipo" className="card-soft mt-3 overflow-hidden">{renderTable(staff, false)}</TabsContent>}
      </Tabs>

      <UserDialog
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
        editing={editing}
        defaultRole={tab === "socios" ? "socio" : "cajero"}
        isAdmin={isAdmin}
        onSaved={load}
      />
      <RechargeDialog socio={recharging} open={!!recharging} onClose={() => setRecharging(null)} onDone={load} />
    </div>
  );
}
