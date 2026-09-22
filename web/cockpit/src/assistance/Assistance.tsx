import { useEffect, useRef, useState } from "react";
import {
  ageSeconds,
  type AssistanceState,
  clearCommand,
  type Command,
  type Destination,
  DESTINATIONS,
  newId,
  postCommand,
  savedCommand,
  STATE_LABELS,
} from "./api.ts";
import { listen, voiceReason } from "./voice.ts";
import styles from "./Assistance.module.css";

export function Assistance() {
  const [state, setState] = useState<AssistanceState | null>(null);
  const [online, setOnline] = useState(false);
  const [text, setText] = useState(() =>
    sessionStorage.getItem("assistance-text") ??
      "Lleva la botella de la sala a la mesa del dormitorio"
  );
  const [destination, setDestination] = useState<Destination>("mesa_dormitorio");
  const [error, setError] = useState("");
  const [answer, setAnswer] = useState("");
  const [sending, setSending] = useState(false);
  const [listening, setListening] = useState(false);
  const [tick, setTick] = useState(0);
  const [pending, setPending] = useState<Command | null>(savedCommand);
  const inFlight = useRef(false);
  const abortVoice = useRef<(() => void) | null>(null);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    let timer: ReturnType<typeof setTimeout>;
    const controller = new AbortController();
    const poll = async () => {
      try {
        const response = await fetch("/api/assistance/state", {
          cache: "no-store",
          signal: AbortSignal.any([controller.signal, AbortSignal.timeout(2500)]),
        });
        if (!response.ok) throw new Error("connection");
        const next = await response.json() as AssistanceState;
        if (!alive.current) return;
        setState(next);
        setOnline(true);
        setTick((v) => v + 1);
        const saved = savedCommand();
        if (saved && saved.session !== next.session) {
          clearCommand();
          setPending(null);
          setError("El servidor se reinició. La orden anterior no se reenviará; revisa la misión.");
        }
      } catch {
        if (alive.current) setOnline(false);
      } finally {
        if (alive.current) timer = setTimeout(poll, 500);
      }
    };
    void poll();
    return () => {
      alive.current = false;
      controller.abort();
      clearTimeout(timer);
      abortVoice.current?.();
    };
  }, []);
  useEffect(() => {
    sessionStorage.setItem("assistance-text", text);
  }, [text]);

  async function send(kind: string, extra: Partial<Command> = {}, retry?: Command) {
    if (!state || !online || inFlight.current) return;
    inFlight.current = true;
    setSending(true);
    setError("");
    const command = retry ??
      {
        id: newId(),
        session: state.session,
        version: state.version,
        kind,
        revision: state.mission.revision,
        ...extra,
      };
    try {
      await postCommand(command);
      setPending(null);
    } catch (e) {
      setError((e as Error).message);
      setPending(savedCommand());
    } finally {
      inFlight.current = false;
      setSending(false);
    }
  }
  function microphone() {
    if (listening) {
      abortVoice.current?.();
      setListening(false);
      return;
    }
    try {
      abortVoice.current = listen(setText, () => setListening(false), (message) => {
        setError(message);
        setListening(false);
      });
      setListening(true);
    } catch (e) {
      setError((e as Error).message);
    }
  }
  const mission = state?.mission;
  const active = mission && !["idle", "cancelled", "failed", "succeeded"].includes(mission.state);
  const staleImage = !online || !state || ageSeconds(state.server_at, state.image_at) > 2;
  const disabled = !online || sending || !state?.world_fresh || !!pending;
  const micReason = voiceReason();
  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div>
          <p className={styles.eyebrow}>ALOHA · ASISTENCIA DOMÉSTICA</p>
          <h1>Una ayuda, a tu alcance.</h1>
        </div>
        <span className={online ? styles.connected : styles.disconnected}>
          {online ? "Conectado" : "Reconectando…"}
        </span>
      </header>
      <p className={styles.notice}>
        Entorno de simulación ·{" "}
        {state?.mode === "vlm" ? "Supervisor visual local" : "Prueba de interacción guiada"}{" "}
        · Los agarres y las identidades de objetos son de prueba.
      </p>
      {!online && (
        <p role="alert" className={styles.warning}>
          Conexión perdida. El estado mostrado puede estar desactualizado. La desconexión no
          confirma una parada y no reenvía órdenes automáticamente.
        </p>
      )}
      {state && !state.world_fresh && (
        <p role="alert" className={styles.warning}>
          Los datos del robot están obsoletos. Esperando observaciones actuales.
        </p>
      )}
      {error && <p role="alert" className={styles.warning}>{error}</p>}
      {pending && (
        <div className={styles.warning}>
          No se confirmó la recepción de la última orden.
          <button disabled={!online || sending} onClick={() => send(pending.kind, {}, pending)}>
            Comprobar / reenviar la misma orden
          </button>
        </div>
      )}
      <div className={styles.grid}>
        <section className={styles.card} aria-label="Solicitar asistencia">
          <h2>¿Qué necesitas?</h2>
          <label htmlFor="request">Tu solicitud</label>
          <textarea
            id="request"
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={3}
            maxLength={1000}
            disabled={!!active}
          />
          <div className={styles.voice}>
            <button
              onClick={microphone}
              disabled={!!micReason || !!active}
              aria-pressed={listening}
            >
              {listening ? "Terminar dictado" : "Dictar solicitud"}
            </button>
            <small>
              {listening
                ? "Escuchando… El texto se podrá corregir antes de enviarlo."
                : micReason ?? "Dictado local. Revisa la transcripción antes de enviar."}
            </small>
          </div>
          <label htmlFor="destination">Lugar de entrega</label>
          <select
            id="destination"
            value={destination}
            onChange={(e) => setDestination(e.target.value as Destination)}
          >
            {Object.entries(DESTINATIONS).map(([id, name]) => (
              <option key={id} value={id}>{name}</option>
            ))}
          </select>
          {!active
            ? (
              <button
                className={styles.primary}
                disabled={disabled || !text.trim()}
                onClick={() => send("draft", { instruction: text, destination })}
              >
                Revisar solicitud
              </button>
            )
            : (
              <button
                disabled={disabled || mission?.state === "stopping"}
                onClick={() => send("redirect", { destination })}
              >
                Pausar y cambiar destino
              </button>
            )}
          {state?.draft && (
            <div className={styles.confirm}>
              <h3>Revisa antes de iniciar</h3>
              <p>{state.draft.instruction}</p>
              <p>Botella pequeña · Sala → {DESTINATIONS[state.draft.destination]}</p>
              <p>{state.message}</p>
              {state.draft.ready && (
                <button
                  className={styles.primary}
                  disabled={disabled}
                  onClick={() => send("confirm")}
                >
                  Confirmar e iniciar
                </button>
              )}
            </div>
          )}
          {state?.redirect_to && (
            <div className={styles.confirm}>
              <p>Nuevo destino: {DESTINATIONS[state.redirect_to]}</p>
              <button
                className={styles.primary}
                disabled={disabled || mission?.state !== "paused"}
                onClick={() => send("confirm_redirect")}
              >
                Confirmar nuevo destino y continuar
              </button>
              {mission?.state !== "paused" && <p>Esperando confirmación de parada…</p>}
            </div>
          )}
        </section>
        <section className={styles.card} aria-label="Estado de la misión">
          <p className={styles.eyebrow}>TU MISIÓN</p>
          <h2 data-testid="mission-state" role="status" aria-live="polite">
            {mission ? STATE_LABELS[mission.state] ?? mission.state : "Conectando con el robot…"}
          </h2>
          {state?.busy && (
            <p className={styles.thinking}>
              Analizando la escena en CPU… Puede tardar hasta 60 segundos. Puedes pausar o cancelar.
            </p>
          )}
          <p>{state?.message}</p>
          {state?.request && (
            <p>
              Entrega: <strong>{DESTINATIONS[state.request.destination_id]}</strong>
            </p>
          )}
          {mission?.held_object_id && <p>Objeto confirmado en la pinza (simulación).</p>}
          {mission?.state === "asking" && (
            <div className={styles.confirm}>
              <h3>Necesito tu ayuda</h3>
              {state?.mode === "fixture" && (
                <p>
                  Las opciones de este ensayo son artificiales; no representan dos objetos
                  detectados en la cámara.
                </p>
              )}
              <p>
                {state?.candidates.length
                  ? "Hay más de una opción o falta confirmar el objetivo. Elige la botella que deseas."
                  : "No hay un objeto confirmado para elegir. Puedes pausar y revisar la escena."}
              </p>
              {state?.candidates.map((c) => (
                <button
                  key={c.id}
                  disabled={disabled}
                  onClick={() => send("select", { object_id: c.id })}
                >
                  Elegir {c.label}
                </button>
              ))}
              <label htmlFor="answer">Aclarar la solicitud</label>
              <input
                id="answer"
                value={answer}
                maxLength={500}
                onChange={(e) => setAnswer(e.target.value)}
              />
              <button
                disabled={disabled || !answer.trim()}
                onClick={() => send("answer", { instruction: answer })}
              >
                Enviar aclaración
              </button>
            </div>
          )}
          <div className={styles.controls}>
            <button
              disabled={!online || sending || !active || mission?.state === "paused" ||
                mission?.state === "stopping"}
              onClick={() => send("pause")}
            >
              Pausar
            </button>
            <button
              disabled={disabled || mission?.state !== "paused" || !!state?.redirect_to}
              onClick={() => send("resume")}
            >
              Reanudar
            </button>
            <button
              className={styles.cancel}
              disabled={!online || sending || (!active && !state?.draft)}
              onClick={() => send("cancel")}
            >
              Cancelar tarea
            </button>
          </div>
          <details>
            <summary>Conversación y progreso</summary>
            {state?.history.map((line, i) => (
              <p key={i}>
                <strong>{line.role === "user" ? "Tú" : "Asistente"}:</strong> {line.text}
              </p>
            ))}
            <p>Etapas comprobadas: {mission?.completed_actions.length ?? 0}</p>
          </details>
        </section>
        <section className={styles.card} aria-label="Cámara">
          <h2>Lo que ve el robot</h2>
          <div className={styles.camera}>
            {state?.image_at
              ? (
                <img
                  alt="Cámara frontal del AlohaMini1 en la vivienda simulada"
                  src={"/api/assistance/camera?frame=" + tick}
                />
              )
              : <p>Esperando cámara…</p>}
          </div>
          <p className={staleImage ? styles.stale : styles.fresh}>
            {staleImage ? "Imagen obsoleta o no disponible" : "Imagen reciente"}
          </p>
        </section>
        <section className={styles.card} aria-label="Mapa">
          <h2>Ubicación</h2>
          <HouseMap state={state} online={online} />
          <p>Esquema de la vivienda simulada. La posición proviene de la simulación.</p>
        </section>
      </div>
      <footer>
        Una orden cada vez. La tarea solo se completa cuando el gestor verifica el resultado.
      </footer>
    </div>
  );
}

function HouseMap({ state, online }: { state: AssistanceState | null; online: boolean }) {
  const pose = state?.pose;
  const fresh = online && state && ageSeconds(state.server_at, state.pose_at) <= 2;
  return (
    <svg
      className={styles.map}
      viewBox="0 0 500 240"
      role="img"
      aria-label={fresh ? "Mapa con posición reciente del robot" : "Mapa sin posición reciente"}
    >
      <rect x="12" y="12" width="232" height="214" rx="12" fill="#edf1e9" />
      <rect x="256" y="12" width="232" height="214" rx="12" fill="#e6eef0" />
      <text x="35" y="44">SALA</text>
      <text x="278" y="44">DORMITORIO</text>
      <rect x="106" y="80" width="55" height="26" rx="4" fill="#afbdad" />
      <rect x="338" y="80" width="55" height="26" rx="4" fill="#aabdc4" />
      <text x="104" y="73" fontSize="12">Mesa</text>
      <text x="337" y="73" fontSize="12">Mesa</text>
      <path d="M244 142H256" stroke="#bcc6c4" strokeWidth="42" />
      {pose && fresh && (
        <g
          transform={`translate(${250 + pose.x * 45},${142 - pose.y * 45}) rotate(${
            -pose.yaw * 180 / Math.PI
          })`}
        >
          <circle r="13" fill="#135d52" />
          <path d="M8 0L-3 -5L-3 5Z" fill="white" />
        </g>
      )}
      {!fresh && <text x="125" y="197" fontSize="13">Posición no disponible / obsoleta</text>}
    </svg>
  );
}
