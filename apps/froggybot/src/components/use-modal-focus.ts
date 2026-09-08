import { useEffect, useRef } from 'react';
import { Platform, type View } from 'react-native';

const focusableSelector = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'textarea:not([disabled])',
  'select:not([disabled])',
  '[role="button"]:not([aria-disabled="true"])',
  '[role="tab"]:not([aria-disabled="true"])',
  '[role="radio"]:not([aria-disabled="true"])',
  '[role="checkbox"]:not([aria-disabled="true"])',
  '[role="switch"]:not([aria-disabled="true"])',
  '[tabindex]:not([tabindex="-1"])',
].join(',');

/** Keeps web keyboard focus inside the currently presented native-style sheet. */
export function useModalFocus(onClose: () => void, active = true) {
  const modalRef = useRef<View>(null);
  const closeRef = useRef(onClose);

  useEffect(() => {
    closeRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    if (!active || Platform.OS !== 'web' || typeof document === 'undefined') return;
    const root = modalRef.current as unknown as HTMLElement | null;
    if (!root) return;
    const previous = document.activeElement as HTMLElement | null;
    const focusable = () => Array.from(root.querySelectorAll<HTMLElement>(focusableSelector))
      .filter((element) => element.getAttribute('aria-label') !== 'Close menu' && !element.closest('[aria-hidden="true"]'));
    const focusFrame = requestAnimationFrame(() => {
      const first = focusable()[0];
      if (first) first.focus();
      else {
        root.setAttribute('tabindex', '-1');
        root.focus();
      }
    });
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        closeRef.current();
        return;
      }
      if (event.key !== 'Tab') return;
      const items = focusable();
      if (!items.length) {
        event.preventDefault();
        root.focus();
        return;
      }
      const first = items[0];
      const last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      } else if (!root.contains(document.activeElement)) {
        event.preventDefault();
        first.focus();
      }
    };
    root.addEventListener('keydown', handleKeyDown);
    return () => {
      cancelAnimationFrame(focusFrame);
      root.removeEventListener('keydown', handleKeyDown);
      if (previous?.isConnected) requestAnimationFrame(() => previous.focus());
    };
  }, [active]);

  return modalRef;
}
