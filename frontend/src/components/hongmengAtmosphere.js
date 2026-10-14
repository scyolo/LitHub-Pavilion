// A quiet, procedural cloud sea. No buildings, image downloads or render library.
// The fixed noise seed keeps the composition stable across theme changes.
const VERTEX = `
attribute vec2 aPosition;
void main() { gl_Position = vec4(aPosition, 0.0, 1.0); }
`;

export const ATMOSPHERE_FRAGMENT = `
precision highp float;
uniform vec2 uResolution;
uniform float uTime;
uniform vec2 uPointer;
uniform sampler2D uNoise;

float noise(vec2 p) {
  vec2 f = fract(p);
  f = f * f * (3.0 - 2.0 * f);
  return texture2D(uNoise, (floor(p) + f + 0.5) / 256.0).r;
}
float fbm(vec2 p) {
  float value = 0.0;
  float amplitude = 0.52;
  mat2 turn = mat2(1.64, -1.14, 1.14, 1.64);
  for (int i = 0; i < 5; i++) {
    value += amplitude * noise(p);
    p = turn * p + vec2(7.3, 3.1);
    amplitude *= 0.48;
  }
  return value;
}
vec2 cloudAndLight(vec2 p) {
  vec2 warp = vec2(fbm(p * 0.68 + vec2(1.0, uTime * 0.038)),
                   fbm(p * 0.73 + vec2(15.0, 2.0 - uTime * 0.030)));
  vec2 field = p + warp * 2.3;
  float body = fbm(field);
  return vec2(body, fbm(field + vec2(-0.12, -0.17)) - body);
}
void main() {
  vec2 uv = gl_FragCoord.xy / uResolution;
  uv.y = 1.0 - uv.y;
  float aspect = uResolution.x / uResolution.y;
  float portrait = 1.0 - smoothstep(0.80, 1.22, aspect);
  vec2 focus = mix(vec2(0.75, 0.48), vec2(0.60, 0.64), portrait);
  vec2 p = (uv - focus) * vec2(aspect, 1.0) + uPointer * vec2(0.018, 0.012);
  float radius = length(p * vec2(0.91, 1.08));
  float angle = atan(p.y, p.x);
  float turn = -0.76 / (radius + 0.34) + sin(uTime * 0.12) * 0.018;
  vec2 q = mat2(cos(turn), -sin(turn), sin(turn), cos(turn)) * p;
  q.y *= 1.18;
  q += vec2(1.7, 4.3);

  vec2 cloudLight = cloudAndLight(q * 4.4 + vec2(uTime * 0.028, 0.0));
  float cloud = cloudLight.x;
  float broad = fbm(q * 1.8 + vec2(7.0, 3.0));
  float edge = cloudLight.y;
  float body = smoothstep(0.19, 0.63, cloud + broad * 0.16);
  float wall = exp(-pow((radius - 0.34 - (broad - 0.5) * 0.13) / 0.155, 2.0));
  float fine = fbm(q * 19.0);
  cloud += (fine - 0.5) * 0.07;
  float illumination = clamp(0.59 + edge * 3.5 + (cloud - 0.45) * 0.85 - wall * 0.045, 0.0, 1.0);
  vec3 shade = vec3(0.35, 0.42, 0.465);
  vec3 ivory = vec3(0.985, 0.977, 0.945);
  vec3 color = mix(vec3(0.94, 0.949, 0.94), vec3(0.76, 0.815, 0.839), uv.y * 0.45);
  vec3 cloudColor = mix(shade, ivory, illumination);
  float outside = smoothstep(0.075, 0.29, radius);
  color = mix(color, cloudColor, body * outside * (0.80 + wall * 0.20));

  // Light is part of the cloud field, not a separate set of graphic lines.
  // Its highlights travel inward along the same density contours as the mist.
  float reach = smoothstep(0.06, 0.22, radius) * (1.0 - smoothstep(0.8, 1.55, radius));
  float contour = exp(-pow((cloud - 0.545) / 0.032, 2.0));
  float sunward = smoothstep(-0.005, 0.065, edge);
  float tide = pow(0.5 + 0.5 * sin(radius * 34.0 + uTime * 1.45 - broad * 4.0), 3.0);
  float filament = contour * reach * (0.25 + sunward * 0.75);
  color = mix(color, vec3(0.85, 0.737, 0.512), filament * 0.15);
  color += vec3(0.16, 0.127, 0.054) * filament * (0.2 + tide * 0.8);
  vec2 dustSpace = q * 42.0 + vec2(0.0, uTime * 0.32);
  vec2 dustCell = floor(dustSpace);
  vec2 dustLocal = fract(dustSpace) - 0.5;
  float seed = noise(dustCell + vec2(27.0, 3.0));
  float mote = exp(-dot(dustLocal, dustLocal) * 290.0) * step(0.82, seed);
  float flicker = 0.25 + 0.75 * pow(0.5 + 0.5 * sin(uTime * 0.8 + seed * 31.0), 2.0);
  color += vec3(0.29, 0.236, 0.118) * mote * flicker * reach;

  // Vast, diffused daylight emerges from the confluence.
  float glow = exp(-radius * radius * 12.0);
  float heart = exp(-radius * radius * 87.0);
  color = mix(color, vec3(1.0, 0.945, 0.795), glow * 0.34);
  color = mix(color, vec3(1.0, 0.993, 0.940), heart * (0.88 + 0.025 * sin(uTime * 0.62)));
  float upper = (1.0 - smoothstep(-0.45, 0.04, p.y));
  float shaft = exp(-pow(p.x / (0.018 + max(0.0, -p.y) * 0.30), 2.0));
  color += vec3(0.12, 0.10, 0.057) * shaft * upper * (0.75 + broad * 0.25);
  float air = (1.0 - smoothstep(-0.45, 0.43, p.y)) * 0.13;
  color = mix(color, ivory, air);
  float vignette = smoothstep(0.3, 1.4, radius) * smoothstep(0.50, 1.0, uv.y);
  color *= 1.0 - vignette * 0.08;
  float film = fract(sin(dot(gl_FragCoord.xy, vec2(12.9898, 78.233))) * 43758.5453);
  color += (film - 0.5) * 0.012;
  gl_FragColor = vec4(clamp(color, 0.0, 1.0), 1.0);
}
`;

export function atmosphereSize(width, height, pixelRatio = 1) {
  const w = Math.max(1, Number.isFinite(width) ? width : 1);
  const h = Math.max(1, Number.isFinite(height) ? height : 1);
  const dpr = Math.min(1.5, Math.max(1, Number.isFinite(pixelRatio) ? pixelRatio : 1));
  const scale = Math.min(dpr, Math.sqrt(480000 / (w * h)), 1440 / Math.max(w, h));
  return { width: Math.max(1, Math.floor(w * scale)), height: Math.max(1, Math.floor(h * scale)) };
}

export function atmosphereNoise(seed = 31627) {
  const pixels = new Uint8Array(256 * 256 * 4);
  let value = seed >>> 0;
  for (let index = 0; index < pixels.length; index += 4) {
    value = (Math.imul(value, 1664525) + 1013904223) >>> 0;
    const level = value >>> 24;
    pixels[index] = pixels[index + 1] = pixels[index + 2] = level;
    pixels[index + 3] = 255;
  }
  return pixels;
}

const ACTIVE_ATMOSPHERES = new WeakMap();

export function createAtmosphere(canvas, onState = () => {}) {
  if (typeof globalThis.WebGLRenderingContext !== "function") return null;
  let gl;
  try { gl = canvas.getContext("webgl", { alpha: false, antialias: false, depth: false, stencil: false, powerPreference: "low-power" }); }
  catch { return null; }
  if (!gl || gl.isContextLost()) return null;
  const owner = {};
  ACTIVE_ATMOSPHERES.set(canvas, owner);
  // StrictMode reuses the DOM canvas during its effect setup/cleanup probe.
  // Retire only after a replacement renderer has had a chance to claim it.
  const retireContext = () => queueMicrotask(() => {
    if (ACTIVE_ATMOSPHERES.get(canvas) !== owner) return;
    ACTIVE_ATMOSPHERES.delete(canvas);
    if (!gl.isContextLost()) gl.getExtension("WEBGL_lose_context")?.loseContext();
  });
  const resources = [];
  let disposed = false, paused = true, frame = null, elapsed = 0, last = null;
  const pointer = { x: 0, y: 0 };
  const pointerTarget = { x: 0, y: 0 };
  const release = () => {
    for (const [kind, object] of resources.splice(0)) gl[kind](object);
  };
  const compile = (type, source) => {
    const shader = gl.createShader(type);
    if (!shader) throw new Error("No shader available");
    resources.push(["deleteShader", shader]);
    gl.shaderSource(shader, source);
    gl.compileShader(shader);
    if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) throw new Error("Atmosphere shader unavailable");
    return shader;
  };
  let draw;
  try {
    const program = gl.createProgram();
    if (!program) throw new Error("No program available");
    resources.push(["deleteProgram", program]);
    gl.attachShader(program, compile(gl.VERTEX_SHADER, VERTEX));
    gl.attachShader(program, compile(gl.FRAGMENT_SHADER, ATMOSPHERE_FRAGMENT));
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw new Error("Atmosphere program unavailable");
    gl.useProgram(program);
    const buffer = gl.createBuffer();
    if (!buffer) throw new Error("No buffer available");
    resources.push(["deleteBuffer", buffer]);
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, -1, 1, 1, -1, 1, 1]), gl.STATIC_DRAW);
    const position = gl.getAttribLocation(program, "aPosition");
    gl.enableVertexAttribArray(position);
    gl.vertexAttribPointer(position, 2, gl.FLOAT, false, 0, 0);
    const texture = gl.createTexture();
    if (!texture) throw new Error("No texture available");
    resources.push(["deleteTexture", texture]);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, texture);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 256, 256, 0, gl.RGBA, gl.UNSIGNED_BYTE, atmosphereNoise());
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.REPEAT);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.REPEAT);
    gl.uniform1i(gl.getUniformLocation(program, "uNoise"), 0);
    const time = gl.getUniformLocation(program, "uTime");
    const drift = gl.getUniformLocation(program, "uPointer");
    const resolution = gl.getUniformLocation(program, "uResolution");
    draw = () => {
      if (disposed || gl.isContextLost()) return;
      gl.viewport(0, 0, canvas.width, canvas.height);
      gl.uniform2f(resolution, canvas.width, canvas.height);
      gl.uniform1f(time, elapsed);
      gl.uniform2f(drift, pointer.x, pointer.y);
      gl.drawArrays(gl.TRIANGLES, 0, 6);
    };
  } catch {
    release();
    retireContext();
    return null;
  }
  const stop = () => {
    if (frame !== null) cancelAnimationFrame(frame);
    frame = null;
    last = null;
  };
  const tick = timestamp => {
    frame = null;
    if (disposed || paused) return;
    if (last === null || timestamp - last >= 1000 / 30) {
      elapsed += last === null ? 0 : Math.min(timestamp - last, 160) / 1000;
      last = timestamp;
      pointer.x += (pointerTarget.x - pointer.x) * 0.065;
      pointer.y += (pointerTarget.y - pointer.y) * 0.065;
      draw();
    }
    frame = requestAnimationFrame(tick);
  };
  const resize = () => {
    if (disposed) return;
    const box = canvas.getBoundingClientRect();
    const size = atmosphereSize(box.width, box.height, globalThis.devicePixelRatio);
    if (canvas.width !== size.width || canvas.height !== size.height) {
      canvas.width = size.width;
      canvas.height = size.height;
    }
    draw();
  };
  const lost = event => {
    event.preventDefault();
    paused = true;
    stop();
    onState("fallback");
  };
  const observer = typeof ResizeObserver === "function" ? new ResizeObserver(resize) : null;
  observer?.observe(canvas);
  if (!observer) globalThis.addEventListener?.("resize", resize);
  canvas.addEventListener("webglcontextlost", lost);
  resize();
  onState("webgl");
  return {
    setPointer(x, y) {
      pointerTarget.x = Number.isFinite(x) ? Math.max(-1, Math.min(1, x)) : 0;
      pointerTarget.y = Number.isFinite(y) ? Math.max(-1, Math.min(1, y)) : 0;
    },
    setPaused(value) {
      if (disposed) return;
      paused = value;
      if (paused) stop();
      else if (frame === null && !gl.isContextLost()) frame = requestAnimationFrame(tick);
    },
    dispose() {
      if (disposed) return;
      disposed = true;
      stop();
      observer?.disconnect();
      if (!observer) globalThis.removeEventListener?.("resize", resize);
      canvas.removeEventListener("webglcontextlost", lost);
      release();
      retireContext();
    },
  };
}
