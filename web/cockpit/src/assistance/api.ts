export type Destination = "mesa_sala" | "mesa_dormitorio";
export interface AssistanceState {
  session: string;
  version: number;
  server_at: number;
  world_fresh: boolean;
  mode: string;
  busy: boolean;
  message: string;
  draft: { instruction: string; destination: Destination; ready: boolean } | null;
  redirect_to: Destination | null;
  request: { instruction: string; destination_id: Destination } | null;
  mission: {
    state: string;
    reason: string;
    revision: number;
    held_object_id: string | null;
    completed_actions: string[];
    action: { skill_id: string } | null;
  };
  candidates: { id: string; label: string }[];
  history: { role: string; text: string }[];
  image_at: number | null;
  pose: { x: number; y: number; yaw: number; ts: number } | null;
  pose_at: number | null;
}
export interface Command {
  id: string;
  session: string;
  version: number;
  kind: string;
  instruction?: string;
  destination?: Destination;
  object_id?: string;
  revision?: number;
}
const KEY = "dimos-assistance-pending";
export function newId(): string {
  // getRandomValues works on LAN HTTP; randomUUID requires a secure context.
  return Array.from(
    crypto.getRandomValues(new Uint8Array(16)),
    (b) => b.toString(16).padStart(2, "0"),
  ).join("");
}
export function savedCommand(): Command | null {
  try {
    return JSON.parse(sessionStorage.getItem(KEY) ?? "null");
  } catch {
    return null;
  }
}
export function clearCommand(): void {
  sessionStorage.removeItem(KEY);
}
export async function postCommand(command: Command): Promise<void> {
  sessionStorage.setItem(KEY, JSON.stringify(command));
  const response = await fetch("/api/assistance/command", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Dimos-Session": command.session },
    body: JSON.stringify(command),
    signal: AbortSignal.timeout(5000),
  });
  if (!response.ok) {
    clearCommand();
    const result = await response.json();
    throw new Error(result.detail ?? "La orden no fue aceptada.");
  }
  clearCommand();
}
export function ageSeconds(serverAt: number, captured: number | null): number {
  return captured === null ? Infinity : Math.max(0, serverAt - captured);
}
export const STATE_LABELS: Record<string, string> = {
  idle: "Listo para ayudarte",
  preparing: "Preparando la tarea",
  searching: "Buscando el objeto",
  navigating: "Desplazándose",
  manipulating: "Manipulando en simulación",
  verifying: "Comprobando el resultado",
  asking: "Necesito tu ayuda",
  stopping: "Deteniendo · esperando confirmación",
  stop_unconfirmed: "Parada sin confirmar",
  paused: "En pausa · parada confirmada",
  cancelled: "Cancelada · parada confirmada",
  failed: "Tarea interrumpida",
  succeeded: "Entrega verificada en simulación",
};
export const DESTINATIONS: Record<Destination, string> = {
  mesa_sala: "Mesa de la sala",
  mesa_dormitorio: "Mesa del dormitorio",
};
