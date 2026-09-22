// Browser-local recognition only. Never silently fall back to a cloud service.
interface Recognition {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  processLocally: boolean;
  onresult: ((event: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
  start(): void;
  abort(): void;
}
type VoiceWindow = Window & {
  SpeechRecognition?: new () => Recognition;
  webkitSpeechRecognition?: new () => Recognition;
};
export function voiceReason(): string | null {
  if (!globalThis.isSecureContext) {
    return "El micrófono requiere HTTPS de confianza. Puedes escribir tu solicitud.";
  }
  const w = window as VoiceWindow;
  const Constructor = w.SpeechRecognition ?? w.webkitSpeechRecognition;
  if (!Constructor || !("processLocally" in Constructor.prototype)) {
    return "Este navegador no ofrece dictado local compatible. Usa el texto; la voz se validará en F9.";
  }
  return null;
}
export function listen(
  onText: (text: string) => void,
  onEnd: () => void,
  onError: (message: string) => void,
): () => void {
  const reason = voiceReason();
  if (reason) throw new Error(reason);
  const w = window as VoiceWindow;
  const Constructor = w.SpeechRecognition ?? w.webkitSpeechRecognition!;
  const recognition = new Constructor();
  recognition.lang = "es-ES";
  recognition.processLocally = true;
  recognition.continuous = false;
  recognition.interimResults = false;
  recognition.onresult = (event) =>
    onText(Array.from(event.results, (r) => r[0].transcript).join(" "));
  recognition.onend = onEnd;
  recognition.onerror = (e) =>
    onError(
      "No se pudo transcribir localmente (" + e.error + "). Puedes escribir o corregir el texto.",
    );
  recognition.start();
  return () => recognition.abort();
}
