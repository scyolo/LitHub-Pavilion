export function readerError(message, status = 400, code = 'INVALID_PARAM') {
  return Object.assign(new Error(message), { status, code });
}
