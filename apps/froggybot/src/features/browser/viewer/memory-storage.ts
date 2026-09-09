/** The AWS viewer may cache settings/data. Shadow storage only in its disposable
 * document, never clear or replace the parent app's signed-in storage. */
export function memoryStorage(): Storage {
  const values = new Map<string, string>();
  const methods: Storage = {
    get length() { return values.size; },
    clear: () => values.clear(),
    getItem: (key: string) => values.get(String(key)) ?? null,
    key: (index: number) => [...values.keys()][index] ?? null,
    removeItem: (key: string) => { values.delete(String(key)); },
    setItem: (key: string, value: string) => { values.set(String(key), String(value)); },
  };
  return new Proxy(methods, {
    get: (target, key) => key in target ? Reflect.get(target, key) : values.get(String(key)),
    set: (_target, key, value) => { values.set(String(key), String(value)); return true; },
    deleteProperty: (_target, key) => { values.delete(String(key)); return true; },
  });
}

export function installPrivateViewerStorage(viewer: Window): void {
  Object.defineProperties(viewer, {
    localStorage: { value: memoryStorage(), configurable: false },
    sessionStorage: { value: memoryStorage(), configurable: false },
  });
}
