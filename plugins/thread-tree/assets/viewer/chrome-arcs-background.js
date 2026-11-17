(() => {
  const LOOP = 10;
  const TAU = Math.PI * 2;
  const REF_W = 1179;
  const VIEW_X = 590;
  const VIEW_Y = 984;
  const SWAY = 26;
  const MAX_PIXELS = 1100000;

  const vertexSource = `
    attribute vec2 aPos;
    void main() { gl_Position = vec4(aPos, 0.0, 1.0); }
  `;

  const fragmentSource = `
    precision highp float;
    uniform vec2 uRes;
    uniform vec4 uView;
    uniform vec3 uMotion;
    uniform mat3 uTint;
    uniform float uSeed;

    const vec2 C = vec2(3777.39, 2674.21);
    const float R0 = 6657.9;
    const float D1 = 2264.66;
    const float LNQ = 0.0670042;
    const float CORE = 0.24;
    const vec2 TAIL_R = vec2(0.40033, 0.33513);
    const vec2 TAIL_G = vec2(0.38067, 0.32096);
    const vec2 TAIL_B = vec2(0.35736, 0.32278);
    const float BLOOM = 2.2;

    float sq(float x) { return x * x; }
    float hash(vec2 p) { return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453); }

    float nudge(vec2 p) {
      vec2 q = clamp(p, vec2(0.0), vec2(1179.0, 1967.0)) / 1000.0 - vec2(0.6, 1.0);
      float X = q.x, Y = q.y;
      return -0.01066 + Y * (-0.0588 + Y * (0.02479 + Y * 0.12054))
        + X * (0.00943 + Y * (0.08212 + Y * 0.05649))
        + X * X * (0.06149 - 0.00377 * Y) - 0.01411 * X * X * X;
    }

    float envelope(vec2 q, float a, float bx, float by, float bxx, float byy, float bxy, float cap) {
      return exp(min(a + bx * q.x + by * q.y + bxx * q.x * q.x + byy * q.y * q.y + bxy * q.x * q.y, cap));
    }

    vec2 meet(float ra, float x0, float sx) {
      float A = x0 - 1000.0 * sx - C.x;
      float a = sx * sx + 1.0;
      float b = 2.0 * (A * sx - C.y);
      float c = A * A + C.y * C.y - ra * ra;
      float y = (-b - sqrt(max(b * b - 4.0 * a * c, 0.0))) / (2.0 * a);
      return vec2(atan(y - C.y, x0 + sx * (y - 1000.0) - C.x), y);
    }

    float radius(float k) { return R0 - D1 * exp(LNQ * (k - 1.0)); }

    float lobe(float d, float outer, float inner) {
      return exp(-sq(d / CORE)) + 0.31106 * exp(-abs(d) / (d > 0.0 ? outer : inner));
    }

    vec3 sheen(float phi) {
      return vec3(
        16.614 * lobe(phi - 0.11247, TAIL_R.x, TAIL_R.y),
        16.018 * lobe(phi + 0.040111, TAIL_G.x, TAIL_G.y),
        16.169 * lobe(phi + 0.17831, TAIL_B.x, TAIL_B.y)
      );
    }

    vec3 band(float kp, float t, float th, float r, float w, float aa, vec4 env) {
      float m = uView.w;
      float flow = uMotion.x;
      float kc = 4.5 + (kp + 0.5 - flow - 4.5) / m;
      float crest = 0.46263 + 0.070742 * (kc - 4.0) - 0.0040818 * (degrees(th) + 150.0);
      float spread = t < crest ? max(0.38553 - 0.071703 * (kc - 4.0), 0.03) : 0.12301;
      vec3 col = vec3(env.x * exp(-sq((t - crest) / spread)));
      col += env.y * exp(-sq((1.0 - t) / 0.16965)) * vec3(0.55, 0.7, 1.0);

      float t0 = 0.26151 + 0.032207 * (kc - 4.5);
      float ta = meet(radius(4.5 + (kp + t0 - flow - 4.5) / m), 536.54 + uMotion.y, 0.014062).x;
      float u = (th - ta) * r / w;
      float dt = t - t0;
      float bend = dt < 0.0 ? 8.3036 : 3.5178 - 0.021064 * (kc - 4.5);
      float phi = (-u + bend * dt * dt - 0.37954) * (1.0471 - 0.14429 * (kc - 4.5));
      col += uTint * sheen(phi) * env.w;
      col += BLOOM * env.w * exp(-sq((phi - 0.12) / 0.42) - sq(dt / 0.2)) * vec3(1.0, 0.9, 0.78);

      float rw = sqrt(0.000144 + aa * aa * 0.35);
      float prof = 0.012 / rw * exp(-sq(t / rw));
      if (prof > 0.0001) {
        float rk = radius(4.5 + (kp - flow - 4.5) / m);
        vec2 g = meet(rk, 613.43 + uMotion.y, 0.0);
        float s = (th - g.x) * rk;
        float hl = max(137.51 + 0.37297 * (g.y - 1000.0), 10.0);
        float o = -s - hl, i = s - hl;
        vec3 glint = exp(-max(max(vec3(o - 20.938, o, o + 31.302), vec3(i + 20.938, i, i - 31.302)), 0.0) / 76.225);
        col += prof * (vec3(env.z) + uTint * (25.0 * env.w * glint));
      }
      return col;
    }

    vec3 encode(vec3 c) {
      c = clamp(c, 0.0, 1.0);
      return mix(c * 12.92, 1.055 * pow(c, vec3(1.0 / 2.4)) - 0.055, step(0.0031308, c));
    }

    void main() {
      vec2 fc = vec2(gl_FragCoord.x, uRes.y - gl_FragCoord.y);
      vec2 p = uView.xy + (fc - 0.5 * uRes) * uView.z;
      vec2 d = p - C;
      float r = length(d);
      float th = atan(d.y, d.x);
      float gap = max(R0 - r, 1.0);
      float m = uView.w;
      float K = 4.5 + (1.0 + log(gap / D1) / LNQ + nudge(p) - 4.5) * m + uMotion.x;
      float w = gap * LNQ / m;
      float aa = uView.z / w;

      vec2 q = clamp(p, vec2(0.0), vec2(1179.0, 1967.0)) / 1000.0 - vec2(0.6, 1.0);
      float body = envelope(q, -3.7092, 2.4996, -4.3156, -4.975, -1.6414, 0.77581, 0.5);
      vec4 env = vec4(
        body,
        min(sqrt(body) * exp(-2.9914), 1.65),
        envelope(q, -9.7404, 26.18, -13.223, -19.901, -6.2186, 16.602, 1.0),
        envelope(q, -1.8032, -1.5862, -0.34234, -12.467, -1.9718, 7.467, 1.0) * uMotion.z
      );

      float kp = floor(K);
      float t = K - kp;
      vec3 col = band(kp, t, th, r, w, aa, env);
      if (t < aa * 0.5) col = mix(band(kp - 1.0, t + 1.0, th, r, w, aa, env), col, 0.5 + t / aa);
      else if (t > 1.0 - aa * 0.5) col = mix(band(kp + 1.0, t - 1.0, th, r, w, aa, env), col, 0.5 + (1.0 - t) / aa);

      col = encode(1.0 - exp(-col * 0.69504));
      col += (hash(fc + uSeed) - 0.5) * (3.0 / 255.0);
      gl_FragColor = vec4(clamp(col, 0.0, 1.0), 1.0);
    }
  `;

  function compile(gl, type, source) {
    const shader = gl.createShader(type);
    gl.shaderSource(shader, source);
    gl.compileShader(shader);
    if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
      const message = gl.getShaderInfoLog(shader);
      gl.deleteShader(shader);
      throw new Error(message || "Chrome Arcs shader compilation failed");
    }
    return shader;
  }

  function viewScale(width, height) {
    const aspect = width / Math.max(height, 1);
    return aspect >= 1 ? (REF_W * Math.sqrt(aspect)) / width : REF_W / width;
  }

  function showFallback(canvas) {
    canvas.hidden = true;
    const fallback = document.createElement("div");
    fallback.className = "chrome-arcs-fallback";
    canvas.after(fallback);
    return { setPlaybackRate() {}, destroy() { fallback.remove(); } };
  }

  window.createChromeArcsBackground = (canvas) => {
    if (!canvas) return { setPlaybackRate() {}, destroy() {} };
    const gl = canvas.getContext("webgl", {
      alpha: false,
      antialias: false,
      depth: false,
      stencil: false,
      powerPreference: "high-performance",
    });
    if (!gl) return showFallback(canvas);

    let program;
    let vertexShader;
    let fragmentShader;
    let buffer;
    try {
      program = gl.createProgram();
      vertexShader = compile(gl, gl.VERTEX_SHADER, vertexSource);
      fragmentShader = compile(gl, gl.FRAGMENT_SHADER, fragmentSource);
      gl.attachShader(program, vertexShader);
      gl.attachShader(program, fragmentShader);
      gl.linkProgram(program);
      if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(program));
    } catch (_error) {
      return showFallback(canvas);
    }

    gl.useProgram(program);
    buffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
    const position = gl.getAttribLocation(program, "aPos");
    gl.enableVertexAttribArray(position);
    gl.vertexAttribPointer(position, 2, gl.FLOAT, false, 0, 0);

    const uRes = gl.getUniformLocation(program, "uRes");
    const uView = gl.getUniformLocation(program, "uView");
    const uMotion = gl.getUniformLocation(program, "uMotion");
    const uTint = gl.getUniformLocation(program, "uTint");
    const uSeed = gl.getUniformLocation(program, "uSeed");
    gl.uniformMatrix3fv(uTint, false, new Float32Array([1, 0, 0, 0, 1, 0, 0, 0, 1]));

    let canvasWidth = 1;
    let canvasHeight = 1;
    let referenceScale = 1;
    let playbackRate = 0;
    let clock = 0;
    let raf = 0;
    let lastFrame = performance.now();
    let visible = true;
    let needsFrame = true;

    const requestFrame = () => {
      if (visible && !raf) raf = requestAnimationFrame(draw);
    };

    const resize = () => {
      const rect = canvas.getBoundingClientRect();
      const dpr = Math.min(window.devicePixelRatio || 1, 1.5, Math.sqrt(MAX_PIXELS / Math.max(rect.width * rect.height, 1)));
      canvasWidth = Math.max(1, Math.round(rect.width * dpr));
      canvasHeight = Math.max(1, Math.round(rect.height * dpr));
      if (canvas.width !== canvasWidth || canvas.height !== canvasHeight) {
        canvas.width = canvasWidth;
        canvas.height = canvasHeight;
      }
      referenceScale = (viewScale(rect.width, rect.height) * rect.width) / canvasWidth;
      gl.viewport(0, 0, canvasWidth, canvasHeight);
      needsFrame = true;
      requestFrame();
    };

    function draw(now) {
      raf = 0;
      const elapsed = Math.min(0.05, Math.max(0, (now - lastFrame) / 1000));
      lastFrame = now;
      clock += elapsed * playbackRate;
      const lap = ((clock / LOOP) % 1 + 1) % 1;
      const sway = SWAY * Math.sin(TAU * lap);
      gl.uniform2f(uRes, canvasWidth, canvasHeight);
      gl.uniform4f(uView, VIEW_X, VIEW_Y, referenceScale, 1);
      gl.uniform3f(uMotion, lap, sway, 1);
      gl.uniform1f(uSeed, playbackRate > 0.001 ? Math.floor(clock * 30) % 97 : 0);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
      needsFrame = false;
      if (playbackRate > 0.001) requestFrame();
    }

    const resizeObserver = new ResizeObserver(resize);
    resizeObserver.observe(canvas);
    const intersectionObserver = new IntersectionObserver(([entry]) => {
      visible = entry.isIntersecting;
      if (visible) requestFrame();
    });
    intersectionObserver.observe(canvas);
    resize();

    const contextLost = (event) => {
      event.preventDefault();
      showFallback(canvas);
    };
    canvas.addEventListener("webglcontextlost", contextLost);

    return {
      setPlaybackRate(rate) {
        const nextRate = Math.max(0, Number(rate) || 0);
        if (Math.abs(nextRate - playbackRate) < 0.0001 && !needsFrame) return;
        playbackRate = nextRate;
        needsFrame = true;
        requestFrame();
      },
      destroy() {
        cancelAnimationFrame(raf);
        resizeObserver.disconnect();
        intersectionObserver.disconnect();
        canvas.removeEventListener("webglcontextlost", contextLost);
        gl.deleteProgram(program);
        gl.deleteShader(vertexShader);
        gl.deleteShader(fragmentShader);
        gl.deleteBuffer(buffer);
      },
    };
  };
})();
