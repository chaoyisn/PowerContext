/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** ResearchFlow backend base URL. Empty string = use the Vite dev-server /api proxy. */
  readonly VITE_API_BASE_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
