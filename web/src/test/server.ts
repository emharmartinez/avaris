import { setupServer } from "msw/node";

// Component tests add their API responses with server.use(http.get(...))
export const server = setupServer();
