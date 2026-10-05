import axios from "axios";

const api = axios.create({
  baseURL: `${process.env.REACT_APP_BACKEND_URL}/api`,
  withCredentials: true,
});

export function apiError(e, fallback = "Algo salió mal. Inténtalo de nuevo.") {
  const detail = e?.response?.data?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((d) => d?.msg || "").filter(Boolean).join(" ");
  return fallback;
}

export const fmtEUR = (n) =>
  `${new Intl.NumberFormat("es-ES", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(n ?? 0)} Cr`;

export const CATEGORY_COLORS = {
  amber: "bg-amber-100 text-amber-800 border-amber-200",
  purple: "bg-purple-100 text-purple-800 border-purple-200",
  orange: "bg-orange-100 text-orange-800 border-orange-200",
  pink: "bg-pink-100 text-pink-800 border-pink-200",
  sky: "bg-sky-100 text-sky-800 border-sky-200",
  emerald: "bg-emerald-100 text-emerald-800 border-emerald-200",
  lime: "bg-lime-100 text-lime-800 border-lime-200",
  rose: "bg-rose-100 text-rose-800 border-rose-200",
  slate: "bg-slate-100 text-slate-600 border-slate-200",
};

export const CATEGORY_DOTS = {
  amber: "bg-amber-400",
  purple: "bg-purple-400",
  orange: "bg-orange-400",
  pink: "bg-pink-400",
  sky: "bg-sky-400",
  emerald: "bg-emerald-400",
  lime: "bg-lime-400",
  rose: "bg-rose-400",
  slate: "bg-slate-400",
};

export const catLabel = (cats, key) => cats.find((c) => c.key === key)?.label || key;

export const catStyle = (cats, key) =>
  CATEGORY_COLORS[cats.find((c) => c.key === key)?.color] || CATEGORY_COLORS.slate;

export const fmtQty = (n) => Math.round((n ?? 0) * 1000) / 1000;

export async function uploadPhoto(file) {
  const fd = new FormData();
  fd.append("file", file);
  const res = await api.post("/upload", fd, { headers: { "Content-Type": "multipart/form-data" } });
  return `${process.env.REACT_APP_BACKEND_URL}/api/files/${res.data.path}`;
}

export const BACKEND = process.env.REACT_APP_BACKEND_URL;

// Enlace directo al PDF del cierre: es una descarga normal del navegador (con la sesión por cookie).
// Si algo falla, el motivo se ve en la pestaña que se abre.
export const closingPdfUrl = (sessionId) => `${BACKEND}/api/cash/sessions/${sessionId}/report.pdf`;

export const fileUrl = (path) => (path ? `${BACKEND}/api/files/${path}` : null);

export async function uploadPublicPhoto(file) {
  const fd = new FormData();
  fd.append("file", file);
  const res = await api.post("/public/upload", fd, { headers: { "Content-Type": "multipart/form-data" } });
  return res.data.path;
}

export const fmtDateTime = (iso) =>
  iso
    ? new Date(iso).toLocaleString("es-ES", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })
    : "-";

export const fmtDate = (iso) =>
  iso
    ? new Date(iso).toLocaleDateString("es-ES", { day: "2-digit", month: "short", year: "numeric" })
    : "-";

export default api;
