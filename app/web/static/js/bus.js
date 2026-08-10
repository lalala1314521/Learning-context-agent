export function emit(event, detail) {
  document.dispatchEvent(new CustomEvent(event, { detail }));
}

export function on(event, handler) {
  document.addEventListener(event, (e) => handler(e.detail));
}
