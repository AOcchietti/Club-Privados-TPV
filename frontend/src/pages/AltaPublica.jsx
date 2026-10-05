import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import api, { apiError, uploadPublicPhoto, BACKEND } from "@/lib/api";
import { Citrus, Loader2, UploadCloud, Eraser, CheckCircle2, FileText, Camera, IdCard, PenLine } from "lucide-react";

const DOC_TYPES = ["DNI", "NIE", "Pasaporte", "Otro"];

function PhotoField({ label, hint, icon: Icon, value, onUploaded, testid }) {
  const [uploading, setUploading] = useState(false);
  const [preview, setPreview] = useState(null);

  const pick = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      const path = await uploadPublicPhoto(file);
      onUploaded(path);
      setPreview(URL.createObjectURL(file));
    } catch (err) {
      toast.error(apiError(err, "No se pudo subir la imagen"));
    } finally {
      setUploading(false);
    }
  };

  return (
    <div>
      <label className="text-xs font-semibold uppercase tracking-wider text-slate-500 block mb-1">{label}</label>
      <label
        className={`flex items-center gap-3 rounded-xl border-2 border-dashed px-3.5 py-3 cursor-pointer transition-colors ${
          value ? "border-emerald-300 bg-emerald-50/60" : "border-slate-300 bg-white hover:border-amber-400"
        }`}
        data-testid={testid}
      >
        {preview ? (
          <img src={preview} alt={label} className="w-12 h-12 rounded-lg object-cover" />
        ) : (
          <span className="w-12 h-12 rounded-lg bg-slate-100 flex items-center justify-center text-slate-400">
            {uploading ? <Loader2 className="w-5 h-5 animate-spin" /> : <Icon className="w-5 h-5" />}
          </span>
        )}
        <span className="text-xs text-slate-500 flex-1">
          {value ? <b className="text-emerald-700">Imagen lista ✓ (toca para cambiar)</b> : hint}
        </span>
        <input type="file" accept="image/*" capture="environment" className="hidden" onChange={pick} data-testid={`${testid}-input`} />
      </label>
    </div>
  );
}

function SignaturePad({ onChange }) {
  const ref = useRef(null);
  const drawing = useRef(false);
  const [hasInk, setHasInk] = useState(false);

  useEffect(() => {
    const canvas = ref.current;
    const ratio = window.devicePixelRatio || 1;
    canvas.width = canvas.offsetWidth * ratio;
    canvas.height = canvas.offsetHeight * ratio;
    const ctx = canvas.getContext("2d");
    ctx.scale(ratio, ratio);
    ctx.lineWidth = 2.5;
    ctx.lineCap = "round";
    ctx.strokeStyle = "#0f172a";
  }, []);

  const pos = (e) => {
    const rect = ref.current.getBoundingClientRect();
    const p = e.touches ? e.touches[0] : e;
    return { x: p.clientX - rect.left, y: p.clientY - rect.top };
  };
  const start = (e) => {
    e.preventDefault();
    drawing.current = true;
    const { x, y } = pos(e);
    const ctx = ref.current.getContext("2d");
    ctx.beginPath();
    ctx.moveTo(x, y);
  };
  const move = (e) => {
    if (!drawing.current) return;
    e.preventDefault();
    const { x, y } = pos(e);
    const ctx = ref.current.getContext("2d");
    ctx.lineTo(x, y);
    ctx.stroke();
    setHasInk(true);
  };
  const end = () => {
    if (drawing.current && hasInk) onChange(ref.current);
    drawing.current = false;
  };
  const clear = () => {
    const canvas = ref.current;
    canvas.getContext("2d").clearRect(0, 0, canvas.width, canvas.height);
    setHasInk(false);
    onChange(null);
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <label className="text-xs font-semibold uppercase tracking-wider text-slate-500">Firma (dibuja con el dedo)</label>
        <button type="button" onClick={clear} className="text-xs font-bold text-slate-400 hover:text-red-500 flex items-center gap-1" data-testid="alta-signature-clear">
          <Eraser className="w-3.5 h-3.5" /> Borrar
        </button>
      </div>
      <canvas
        ref={ref}
        className="w-full h-36 rounded-xl border-2 border-dashed border-slate-300 bg-white touch-none cursor-crosshair"
        onMouseDown={start} onMouseMove={move} onMouseUp={end} onMouseLeave={end}
        onTouchStart={start} onTouchMove={move} onTouchEnd={end}
        data-testid="alta-signature-canvas"
      />
      {!hasInk && <p className="text-[11px] text-slate-400 mt-1 flex items-center gap-1"><PenLine className="w-3 h-3" /> La firma es obligatoria.</p>}
    </div>
  );
}

export default function AltaPublica() {
  const [form, setForm] = useState({
    name: "", apellidos: "", doc_type: "DNI", doc_number: "",
    nationality: "", birthdate: "", phone: "", email: "",
  });
  const [docPhoto, setDocPhoto] = useState(null);
  const [facePhoto, setFacePhoto] = useState(null);
  const [signCanvas, setSignCanvas] = useState(null);
  const [legal, setLegal] = useState({ available: false });
  const [accepted, setAccepted] = useState(false);
  const [sending, setSending] = useState(false);
  const [done, setDone] = useState(null);

  useEffect(() => {
    api.get("/public/legal").then((r) => setLegal(r.data)).catch(() => {});
  }, []);

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const submit = async () => {
    if (!signCanvas) {
      toast.error("Falta la firma: dibújala en el recuadro");
      return;
    }
    setSending(true);
    try {
      const blob = await new Promise((res) => signCanvas.toBlob(res, "image/png"));
      const signature = await uploadPublicPhoto(new File([blob], "firma.png", { type: "image/png" }));
      const res = await api.post("/public/alta", {
        ...form,
        doc_photo: docPhoto,
        face_photo: facePhoto,
        signature,
        legal_accepted: accepted,
      });
      setDone(res.data);
    } catch (e) {
      toast.error(apiError(e, "No se pudo enviar la solicitud"));
    } finally {
      setSending(false);
    }
  };

  const ready =
    form.name && form.apellidos && form.doc_number && form.nationality &&
    form.birthdate && form.phone && docPhoto && facePhoto && signCanvas && accepted;

  if (done) {
    return (
      <div className="min-h-screen bg-[#FDFBF3] flex items-center justify-center p-6">
        <div className="card-soft max-w-md w-full p-8 text-center space-y-4" data-testid="alta-success">
          <CheckCircle2 className="w-14 h-14 text-emerald-500 mx-auto" />
          <h1 className="font-display text-2xl font-bold text-slate-900">¡Solicitud recibida, {done.name}!</h1>
          <p className="text-sm text-slate-500">
            Tu número de socio es <b className="font-mono-num text-slate-900">{done.member_number}</b>.
            El equipo del club revisará tus datos y activará tu alta. Te avisaremos cuando puedas entrar.
          </p>
          <p className="text-xs text-slate-400">Weed Lemon Social Club · Demetrio de los Ríos 5, Sevilla</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#FDFBF3]" data-testid="alta-page">
      <div className="max-w-xl mx-auto px-4 py-8 space-y-6">
        <div className="flex items-center gap-3">
          <div className="w-11 h-11 rounded-2xl bg-amber-400 flex items-center justify-center">
            <Citrus className="w-6 h-6 text-slate-950" />
          </div>
          <div>
            <h1 className="font-display text-2xl font-bold tracking-tight text-slate-900">Alta de socio</h1>
            <p className="text-xs text-slate-500">Weed Lemon Social Club · Sevilla</p>
          </div>
        </div>

        <div className="card-soft p-5 space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-semibold uppercase tracking-wider text-slate-500 block mb-1">Nombre</label>
              <input value={form.name} onChange={set("name")} data-testid="alta-name-input"
                className="w-full px-3.5 py-2.5 rounded-xl border border-slate-300 focus:outline-none focus:ring-2 focus:ring-amber-400" />
            </div>
            <div>
              <label className="text-xs font-semibold uppercase tracking-wider text-slate-500 block mb-1">Apellidos</label>
              <input value={form.apellidos} onChange={set("apellidos")} data-testid="alta-apellidos-input"
                className="w-full px-3.5 py-2.5 rounded-xl border border-slate-300 focus:outline-none focus:ring-2 focus:ring-amber-400" />
            </div>
            <div>
              <label className="text-xs font-semibold uppercase tracking-wider text-slate-500 block mb-1">Tipo de documento</label>
              <select value={form.doc_type} onChange={set("doc_type")} data-testid="alta-doc-type-select"
                className="w-full px-3.5 py-2.5 rounded-xl border border-slate-300 bg-white focus:outline-none focus:ring-2 focus:ring-amber-400">
                {DOC_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
            </div>
            <div>
              <label className="text-xs font-semibold uppercase tracking-wider text-slate-500 block mb-1">Nº de documento</label>
              <input value={form.doc_number} onChange={set("doc_number")} data-testid="alta-doc-number-input"
                className="w-full px-3.5 py-2.5 rounded-xl border border-slate-300 focus:outline-none focus:ring-2 focus:ring-amber-400" />
            </div>
            <div>
              <label className="text-xs font-semibold uppercase tracking-wider text-slate-500 block mb-1">Nacionalidad</label>
              <input value={form.nationality} onChange={set("nationality")} placeholder="Española…" data-testid="alta-nationality-input"
                className="w-full px-3.5 py-2.5 rounded-xl border border-slate-300 focus:outline-none focus:ring-2 focus:ring-amber-400" />
            </div>
            <div>
              <label className="text-xs font-semibold uppercase tracking-wider text-slate-500 block mb-1">Fecha de nacimiento</label>
              <input type="date" value={form.birthdate} onChange={set("birthdate")} data-testid="alta-birthdate-input"
                className="w-full px-3.5 py-2.5 rounded-xl border border-slate-300 bg-white focus:outline-none focus:ring-2 focus:ring-amber-400" />
            </div>
            <div>
              <label className="text-xs font-semibold uppercase tracking-wider text-slate-500 block mb-1">Teléfono</label>
              <input type="tel" value={form.phone} onChange={set("phone")} data-testid="alta-phone-input"
                className="w-full px-3.5 py-2.5 rounded-xl border border-slate-300 focus:outline-none focus:ring-2 focus:ring-amber-400" />
            </div>
            <div>
              <label className="text-xs font-semibold uppercase tracking-wider text-slate-500 block mb-1">Email (opcional)</label>
              <input type="email" value={form.email} onChange={set("email")} data-testid="alta-email-input"
                className="w-full px-3.5 py-2.5 rounded-xl border border-slate-300 focus:outline-none focus:ring-2 focus:ring-amber-400" />
            </div>
          </div>

          <PhotoField label="Foto del documento" hint="Sube una foto clara de tu DNI/NIE/pasaporte" icon={IdCard}
            value={docPhoto} onUploaded={setDocPhoto} testid="alta-doc-photo" />
          <PhotoField label="Foto facial" hint="Un selfie con buena luz, cara descubierta" icon={Camera}
            value={facePhoto} onUploaded={setFacePhoto} testid="alta-face-photo" />

          <SignaturePad onChange={setSignCanvas} />
        </div>

        <div className="card-soft p-5 space-y-3">
          <h2 className="font-display text-lg font-bold text-slate-900 flex items-center gap-2">
            <FileText className="w-5 h-5 text-amber-500" /> Acuerdo legal
          </h2>
          {legal.available ? (
            <a href={`${BACKEND}/api/public/legal.pdf`} target="_blank" rel="noreferrer"
              className="btn-outline w-full text-sm" data-testid="alta-legal-link">
              <FileText className="w-4 h-4" /> Leer el acuerdo legal (PDF)
            </a>
          ) : (
            <p className="text-xs text-slate-400" data-testid="alta-legal-pending">
              El documento del acuerdo está disponible en el club; el equipo te lo enseñará en tu primera visita.
            </p>
          )}
          <label className="flex items-start gap-3 cursor-pointer select-none">
            <input type="checkbox" checked={accepted} onChange={(e) => setAccepted(e.target.checked)}
              className="mt-0.5 w-5 h-5 rounded border-slate-300 accent-amber-500" data-testid="alta-legal-checkbox" />
            <span className="text-sm text-slate-600">
              He leído y acepto el acuerdo legal del club y consiento el tratamiento de mis datos y fotos para mi alta como socio.
            </span>
          </label>
        </div>

        <button onClick={submit} disabled={!ready || sending} className="btn-secondary w-full py-4 text-base" data-testid="alta-submit-btn">
          {sending ? <Loader2 className="w-5 h-5 animate-spin" /> : <UploadCloud className="w-5 h-5" />}
          Enviar solicitud de alta
        </button>
        <p className="text-[11px] text-slate-400 text-center pb-6">
          Tus datos se envían de forma segura y solo los verá el equipo del club para tramitar tu alta.
        </p>
      </div>
    </div>
  );
}
