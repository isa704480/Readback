/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Origin of the Readback API. Empty string means same-origin, which routes
   *  through the dev proxy in vite.config.ts. */
  readonly VITE_READBACK_API?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

declare module '*.css';
