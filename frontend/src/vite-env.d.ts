/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Absolute origin of the API when it is not same-origin (e.g. frontend on
   *  Vercel, backend on a Python host). Empty / unset means same-origin. */
  readonly VITE_API_BASE_URL?: string;
}
