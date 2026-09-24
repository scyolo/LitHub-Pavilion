import { createSnapshotStore } from "./snapshot-store.js";

const baseUrl = new URL(`${import.meta.env.BASE_URL}snapshot/`, self.location.origin).href;
const store = createSnapshotStore({ baseUrl, onState: (state) => self.postMessage({ type: "state", state }) });
self.addEventListener("message", async ({ data }) => {
  try {
    const result = data.method === "refresh" ? await store.refresh() : await store.call(data.method, data.params);
    self.postMessage({ id: data.id, result });
  } catch (error) {
    self.postMessage({ id: data.id, error: { message: error.message, name: error.name, status: error.status, code: error.code } });
  }
});
