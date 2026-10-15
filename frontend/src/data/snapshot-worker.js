import { createOverviewCache } from './overview-cache.js';
import { createSnapshotStore } from './snapshot-store.js';
import { createSnapshotDispatcher } from './snapshot-dispatcher.js';

const baseUrl = new URL(`${import.meta.env.BASE_URL}snapshot/`, self.location.origin).href;
const store = createSnapshotStore({ baseUrl, overviewCache: createOverviewCache(baseUrl), onState: state => self.postMessage({ type: 'state', state }) });
const dispatch = createSnapshotDispatcher(store, data => self.postMessage(data));
self.addEventListener('message', ({ data }) => dispatch(data));
