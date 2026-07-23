const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

export async function api(path, { method = "GET", adminToken, body } = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method,
    headers: {
      "Content-Type": "application/json",
      ...(adminToken ? { "x-yuno-admin-token": adminToken } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });

  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || "Falha ao falar com a API do Yuno.");
  }
  return data;
}

export const modules = [
  { id: "set", label: "Set" },
  { id: "meta", label: "Metas semanais" },
  { id: "ticket", label: "Tickets" },
  { id: "parceria", label: "Parcerias" },
  { id: "encomenda", label: "Encomendas" },
  { id: "ausencia", label: "Ausencia" },
  { id: "radio", label: "Radio" },
  { id: "producao", label: "Producao" },
];
