import { afterEach, describe, expect, it, vi } from "vitest";
import { atmosphereNoise, atmosphereSize, createAtmosphere } from "./hongmengAtmosphere.js";

afterEach(() => vi.unstubAllGlobals());

describe("bounded atmospheric rendering", () => {
  it("bounds GPU work at desktop, mobile, high-DPI and degenerate sizes", () => {
    for (const [width, height, dpr] of [[1440, 800, 2], [390, 790, 3], [7680, 4320, 4], [1, 9000, 2], [0, 0, 0], [NaN, Infinity, NaN]]) {
      const size = atmosphereSize(width, height, dpr);
      expect(size.width).toBeGreaterThanOrEqual(1);
      expect(size.height).toBeGreaterThanOrEqual(1);
      expect(size.width * size.height).toBeLessThanOrEqual(480000);
      expect(Math.max(size.width, size.height)).toBeLessThanOrEqual(1440);
    }
  });

  it("keeps the noise texture deterministic, opaque and non-uniform", () => {
    const first = atmosphereNoise();
    expect(first).toEqual(atmosphereNoise());
    expect(first).not.toEqual(atmosphereNoise(42));
    expect(first).toHaveLength(256 * 256 * 4);
    const levels = new Set();
    for (let index = 0; index < first.length; index += 4) {
      levels.add(first[index]);
      if (first[index + 3] !== 255) throw new Error("Noise must stay opaque");
    }
    expect(levels.size).toBeGreaterThan(200);
  });

  it("leaves the static scene available when WebGL is unavailable or denied", () => {
    vi.stubGlobal("WebGLRenderingContext", undefined);
    const canvas = { getContext: vi.fn() };
    expect(createAtmosphere(canvas)).toBeNull();
    expect(canvas.getContext).not.toHaveBeenCalled();
    vi.stubGlobal("WebGLRenderingContext", class {});
    canvas.getContext.mockReturnValue(null);
    expect(createAtmosphere(canvas)).toBeNull();
    canvas.getContext.mockImplementation(() => { throw new Error("GPU blocked"); });
    expect(createAtmosphere(canvas)).toBeNull();
  });
});

function graphicsHarness({ compilable = true, linkable = true } = {}) {
  vi.stubGlobal("WebGLRenderingContext", class {});
  const gl = {};
  for (const name of ["createProgram", "createShader", "createBuffer", "createTexture"]) gl[name] = vi.fn(() => ({}));
  for (const name of ["shaderSource", "compileShader", "attachShader", "linkProgram", "useProgram", "bindBuffer", "bufferData", "enableVertexAttribArray", "vertexAttribPointer", "activeTexture", "bindTexture", "texImage2D", "texParameteri", "uniform1i", "viewport", "uniform2f", "uniform1f", "drawArrays", "deleteShader", "deleteProgram", "deleteTexture", "deleteBuffer"]) gl[name] = vi.fn();
  gl.getShaderParameter = vi.fn(() => compilable);
  gl.getProgramParameter = vi.fn(() => linkable);
  gl.getUniformLocation = vi.fn((_, name) => name);
  gl.getAttribLocation = vi.fn(() => 0);
  gl.isContextLost = vi.fn(() => false);
  const loseContext = vi.fn();
  gl.getExtension = vi.fn(() => ({ loseContext }));
  const listeners = new Map();
  const canvas = {
    width: 300, height: 150,
    getContext: vi.fn(() => gl),
    getBoundingClientRect: vi.fn(() => ({ width: 640, height: 480 })),
    addEventListener: vi.fn((name, callback) => listeners.set(name, callback)),
    removeEventListener: vi.fn((name) => listeners.delete(name)),
  };
  const observer = { observe: vi.fn(), disconnect: vi.fn() };
  vi.stubGlobal("ResizeObserver", class { constructor() { return observer; } });
  const frames = new Map();
  let id = 0;
  vi.stubGlobal("requestAnimationFrame", vi.fn(callback => { frames.set(++id, callback); return id; }));
  vi.stubGlobal("cancelAnimationFrame", vi.fn(key => frames.delete(key)));
  const advance = timestamp => {
    const [key, callback] = frames.entries().next().value;
    frames.delete(key);
    callback(timestamp);
  };
  return { gl, canvas, frames, advance, listeners, observer, loseContext };
}

describe("atmosphere lifecycle", () => {
  it("renders a still frame first and schedules no work until explicitly resumed", () => {
    const { canvas, gl, frames, advance } = graphicsHarness();
    const renderer = createAtmosphere(canvas);
    expect(gl.drawArrays).toHaveBeenCalledTimes(1);
    expect(frames.size).toBe(0);
    renderer.setPaused(false);
    expect(frames.size).toBe(1);
    advance(100);
    expect(gl.drawArrays).toHaveBeenCalledTimes(2);
    renderer.setPaused(true);
    expect(frames.size).toBe(0);
    const count = gl.drawArrays.mock.calls.length;
    renderer.setPaused(true);
    expect(gl.drawArrays).toHaveBeenCalledTimes(count);
    renderer.dispose();
  });

  it("caps frame frequency and does not jump forward by time spent paused", () => {
    const { canvas, gl, advance } = graphicsHarness();
    const renderer = createAtmosphere(canvas);
    renderer.setPaused(false);
    advance(100);
    advance(116);
    expect(gl.drawArrays).toHaveBeenCalledTimes(2);
    advance(180);
    expect(gl.drawArrays).toHaveBeenCalledTimes(3);
    const before = gl.uniform1f.mock.lastCall[1];
    renderer.setPaused(true);
    renderer.setPaused(false);
    advance(60000);
    expect(gl.uniform1f.mock.lastCall[1]).toBe(before);
    renderer.dispose();
  });

  it("falls back on context loss and cancels animation", () => {
    const { canvas, frames, listeners } = graphicsHarness();
    const onState = vi.fn();
    const renderer = createAtmosphere(canvas, onState);
    renderer.setPaused(false);
    const preventDefault = vi.fn();
    listeners.get("webglcontextlost")({ preventDefault });
    expect(preventDefault).toHaveBeenCalledOnce();
    expect(frames.size).toBe(0);
    expect(onState).toHaveBeenLastCalledWith("fallback");
    renderer.dispose();
  });

  it("allows StrictMode to remount on the same canvas without losing its new context", async () => {
    const { canvas, frames, loseContext } = graphicsHarness();
    const first = createAtmosphere(canvas);
    first.dispose();
    const second = createAtmosphere(canvas);
    await Promise.resolve();
    expect(loseContext).not.toHaveBeenCalled();
    second.setPaused(false);
    expect(frames.size).toBe(1);
    second.dispose();
    await Promise.resolve();
    expect(loseContext).toHaveBeenCalledOnce();
  });

  it("eases bounded pointer input without scheduling a frame while paused", () => {
    const { canvas, gl, frames, advance } = graphicsHarness();
    const renderer = createAtmosphere(canvas);
    renderer.setPointer(10, -10);
    expect(frames.size).toBe(0);
    renderer.setPaused(false);
    advance(100);
    const pointer = gl.uniform2f.mock.calls.filter(call => call[0] === "uPointer").at(-1);
    expect(pointer[1]).toBeGreaterThan(0);
    expect(pointer[1]).toBeLessThan(1);
    expect(pointer[2]).toBeGreaterThan(-1);
    expect(pointer[2]).toBeLessThan(0);
    renderer.setPointer(Infinity, NaN);
    advance(180);
    const neutral = gl.uniform2f.mock.calls.filter(call => call[0] === "uPointer").at(-1);
    expect(neutral.slice(1).every(Number.isFinite)).toBe(true);
    renderer.dispose();
  });

  it("releases observers, callbacks and all GPU resources exactly once", async () => {
    const { canvas, gl, frames, listeners, observer, loseContext } = graphicsHarness();
    const renderer = createAtmosphere(canvas);
    renderer.setPaused(false);
    renderer.dispose();
    renderer.dispose();
    renderer.setPaused(false);
    expect(frames.size).toBe(0);
    expect(listeners.size).toBe(0);
    expect(observer.disconnect).toHaveBeenCalledOnce();
    expect(gl.deleteProgram).toHaveBeenCalledOnce();
    expect(gl.deleteShader).toHaveBeenCalledTimes(2);
    expect(gl.deleteTexture).toHaveBeenCalledOnce();
    expect(gl.deleteBuffer).toHaveBeenCalledOnce();
    await Promise.resolve();
    expect(loseContext).toHaveBeenCalledOnce();
  });

  it.each([{ compilable: false }, { linkable: false }])("releases partial resources after a GPU compilation failure: %j", settings => {
    const { canvas, gl, frames } = graphicsHarness(settings);
    expect(createAtmosphere(canvas)).toBeNull();
    expect(gl.deleteProgram).toHaveBeenCalledOnce();
    expect(gl.deleteShader).toHaveBeenCalled();
    expect(frames.size).toBe(0);
  });
});
