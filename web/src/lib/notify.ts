// Browser notification + sound helper for @mentions.
//
// - `ensureNotificationPermission()` requests permission once.
// - `playBeep()` synthesises a short tone via WebAudio (no asset).
// - `notifyMention()` fires a browser notification + plays the beep.

let audioCtx: AudioContext | null = null;

function getAudioCtx(): AudioContext | null {
  if (typeof window === "undefined") return null;
  if (audioCtx) return audioCtx;
  const w = window as unknown as {
    AudioContext?: typeof AudioContext;
    webkitAudioContext?: typeof AudioContext;
  };
  const Ctor: typeof AudioContext | undefined = w.AudioContext ?? w.webkitAudioContext;
  if (!Ctor) return null;
  audioCtx = new Ctor();
  return audioCtx;
}

export function playBeep(): void {
  const ctx = getAudioCtx();
  if (!ctx) return;
  const now = ctx.currentTime;
  const osc = ctx.createOscillator();
  const gain = ctx.createGain();
  osc.type = "sine";
  osc.frequency.setValueAtTime(880, now);
  gain.gain.setValueAtTime(0.0001, now);
  gain.gain.exponentialRampToValueAtTime(0.2, now + 0.02);
  gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.25);
  osc.connect(gain).connect(ctx.destination);
  osc.start(now);
  osc.stop(now + 0.3);
}

export async function ensureNotificationPermission(): Promise<NotificationPermission | null> {
  if (typeof window === "undefined" || !("Notification" in window)) return null;
  if (Notification.permission === "granted") return "granted";
  if (Notification.permission === "denied") return "denied";
  try {
    const perm = await Notification.requestPermission();
    return perm;
  } catch {
    return null;
  }
}

export function notifyMention(opts: { title: string; body: string }): void {
  playBeep();
  if (typeof window === "undefined" || !("Notification" in window)) return;
  if (Notification.permission !== "granted") return;
  try {
    const n = new Notification(opts.title, {
      body: opts.body,
      icon: "/favicon.ico",
      silent: true, // we already played our own beep
    });
    n.onclick = () => {
      window.focus();
      n.close();
    };
  } catch {
    /* swallow */
  }
}

/** Quick body scan: returns true if this message mentions the current
 * user OR fires a broadcast token (`@everyone`/`@channel`/`@here`). */
export function bodyMentionsMe(opts: {
  body: string;
  myUserId: string | undefined;
  myHandle: string | undefined;
}): boolean {
  if (!opts.body) return false;
  const lower = opts.body.toLowerCase();
  if (/@(everyone|channel|here)\b/.test(lower)) return true;
  if (opts.myHandle) {
    const re = new RegExp(`(?<![A-Za-z0-9_])@${opts.myHandle.toLowerCase()}\\b`);
    if (re.test(lower)) return true;
  }
  if (opts.myUserId && lower.includes(`@${opts.myUserId.toLowerCase()}`)) return true;
  return false;
}
