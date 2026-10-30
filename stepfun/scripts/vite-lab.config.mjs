import config from "../vite.config.ts";

export default { ...config, server: { ...config.server, hmr: false } };
