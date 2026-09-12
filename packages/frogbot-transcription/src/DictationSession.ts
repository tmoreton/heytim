/** Discard late native results and pending permission requests after Send/cancel. */
export class DictationSession {
  private generation = 0;
  private accepting = false;
  private base = '';
  private scope = '';

  begin(base: string, scope: string) {
    this.cancel();
    this.base = base.trimEnd();
    this.scope = scope;
    return this.generation;
  }

  current(token: number, scope: string) {
    return token === this.generation && scope === this.scope;
  }

  start(token: number, scope: string) {
    if (!this.current(token, scope)) return false;
    this.accepting = true;
    return true;
  }

  result(transcript: string | undefined, scope: string) {
    if (!this.active(scope) || !transcript?.trim()) return undefined;
    return [this.base, transcript.trim()].filter(Boolean).join(' ');
  }

  active(scope: string) { return this.accepting && scope === this.scope; }

  cancel() {
    this.generation++;
    this.accepting = false;
    this.base = '';
  }
}
