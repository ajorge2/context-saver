(() => {
  const VERTEX_SHADER = `
    attribute vec2 a_position;
    void main() {
      gl_Position = vec4(a_position, 0.0, 1.0);
    }
  `;

  const FRAGMENT_SHADER = `
    #ifdef GL_FRAGMENT_PRECISION_HIGH
    precision highp float;
    #else
    precision mediump float;
    #endif

    uniform vec2 u_resolution;
    uniform float u_time;
    uniform vec3 u_colors[4];

    float hash21(vec2 p) {
      #ifndef GL_FRAGMENT_PRECISION_HIGH
      p = mod(p, 31.0);
      #endif
      p = fract(p * vec2(234.34, 435.345));
      p += dot(p, p + 34.23);
      return fract(p.x * p.y);
    }

    float grainHash(vec2 p) {
      vec3 p3 = fract(vec3(p.xyx) * 0.1031);
      p3 += dot(p3, p3.yzx + 33.33);
      return fract((p3.x + p3.y) * p3.z);
    }

    float noise(vec2 p) {
      vec2 i = floor(p);
      vec2 f = fract(p);
      vec2 u = f * f * (3.0 - 2.0 * f);
      return mix(
        mix(hash21(i), hash21(i + vec2(1.0, 0.0)), u.x),
        mix(hash21(i + vec2(0.0, 1.0)), hash21(i + vec2(1.0, 1.0)), u.x),
        u.y
      );
    }

    float fbm(vec2 p) {
      float value = 0.0;
      float amplitude = 0.5;
      for (int i = 0; i < 5; i++) {
        value += amplitude * noise(p);
        p = p * 2.03 + vec2(17.0, 9.2);
        amplitude *= 0.5;
      }
      return value;
    }

    vec3 palette(float x) {
      float value = clamp(x, 0.0, 1.0) * 3.0;
      if (value < 1.0) return mix(u_colors[0], u_colors[1], smoothstep(0.0, 1.0, value));
      if (value < 2.0) return mix(u_colors[1], u_colors[2], smoothstep(0.0, 1.0, value - 1.0));
      return mix(u_colors[2], u_colors[3], smoothstep(0.0, 1.0, value - 2.0));
    }

    vec3 shade(vec2 p, float time) {
      const float flutes = 24.15;
      float cell = fract((p.x + 1.0) * flutes) - 0.5;
      float prism = sin(cell * 3.1415926) * 0.134;
      vec2 samplePoint = p + vec2(prism, sin(p.x * flutes + time * 0.2) * prism * 0.35);
      float field = fbm(samplePoint * 2.2 + vec2(time * 0.035, -time * 0.025) + 1.0);
      field += 0.24 * sin(samplePoint.y * 3.0 + samplePoint.x * 1.3);
      float highlight = pow(1.0 - abs(cell) * 2.0, 6.8);
      float shadow = smoothstep(0.18, 0.5, abs(cell));
      vec3 glass = palette(clamp(field + highlight * 0.3, 0.0, 1.0));
      return glass * (0.72 + highlight * 0.42 - shadow * 0.12);
    }

    void main() {
      vec2 p = (gl_FragCoord.xy - 0.5 * u_resolution.xy)
        / min(u_resolution.x, u_resolution.y);
      p *= 1.48;
      float cosine = cos(0.6458);
      float sine = sin(0.6458);
      p = mat2(cosine, -sine, sine, cosine) * p;
      p += 0.186 * (vec2(
        fbm(p * 2.752 + 1.0),
        fbm(p * 2.752 + vec2(5.2, 1.3))
      ) - 0.5);
      vec3 color = shade(p, u_time);
      color = (color - 0.5) * 1.005 + 0.5;
      color += (grainHash(gl_FragCoord.xy + vec2(17.0, 31.0)) - 0.5) * 0.032;
      gl_FragColor = vec4(clamp(color, 0.0, 1.0), 1.0);
    }
  `;

  const COLORS = new Float32Array([
    0.02745, 0.10196, 0.14118,
    0.94118, 0.99216, 0.98039,
    0.40392, 0.90980, 0.97647,
    0.08235, 0.36863, 0.45882,
  ]);

  function compile(gl, type, source) {
    const shader = gl.createShader(type);
    gl.shaderSource(shader, source);
    gl.compileShader(shader);
    if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
      gl.deleteShader(shader);
      return null;
    }
    return shader;
  }

  function mount(canvas) {
    if (!canvas || canvas.dataset.shaderMounted === "true") return () => {};
    const gl = canvas.getContext("webgl", {
      antialias: false,
      alpha: false,
      powerPreference: "low-power",
      // The Puck editor mirrors this canonical canvas after DOM layers have
      // been surfaced. Preserve the completed frame so drawImage can copy it.
      preserveDrawingBuffer: true,
    });
    if (!gl) return () => {};

    const vertex = compile(gl, gl.VERTEX_SHADER, VERTEX_SHADER);
    const fragment = compile(gl, gl.FRAGMENT_SHADER, FRAGMENT_SHADER);
    if (!vertex || !fragment) return () => {};
    const program = gl.createProgram();
    gl.attachShader(program, vertex);
    gl.attachShader(program, fragment);
    gl.linkProgram(program);
    gl.deleteShader(vertex);
    gl.deleteShader(fragment);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
      gl.deleteProgram(program);
      return () => {};
    }

    canvas.dataset.shaderMounted = "true";
    gl.useProgram(program);
    const buffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
    const position = gl.getAttribLocation(program, "a_position");
    gl.enableVertexAttribArray(position);
    gl.vertexAttribPointer(position, 2, gl.FLOAT, false, 0, 0);
    gl.uniform3fv(gl.getUniformLocation(program, "u_colors"), COLORS);
    const resolution = gl.getUniformLocation(program, "u_resolution");
    const time = gl.getUniformLocation(program, "u_time");

    let frame = 0;
    let visible = document.visibilityState === "visible";
    let inView = true;
    let disposed = false;
    const started = performance.now();
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    const resize = () => {
      const bounds = canvas.getBoundingClientRect();
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const rawWidth = Math.max(1, Math.round(bounds.width * dpr));
      const rawHeight = Math.max(1, Math.round(bounds.height * dpr));
      const pixelScale = Math.min(1, Math.sqrt(2_000_000 / Math.max(1, rawWidth * rawHeight)));
      const width = Math.max(1, Math.round(rawWidth * pixelScale));
      const height = Math.max(1, Math.round(rawHeight * pixelScale));
      if (canvas.width !== width || canvas.height !== height) {
        canvas.width = width;
        canvas.height = height;
        gl.viewport(0, 0, width, height);
      }
    };

    const draw = (now) => {
      frame = 0;
      if (disposed || !visible || !inView) return;
      resize();
      gl.uniform2f(resolution, canvas.width, canvas.height);
      gl.uniform1f(time, reducedMotion ? 0 : ((now - started) / 1000) * 0.822);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
      if (!reducedMotion) frame = requestAnimationFrame(draw);
    };
    const requestDraw = () => {
      if (!disposed && visible && inView && frame === 0) frame = requestAnimationFrame(draw);
    };

    const resizeObserver = new ResizeObserver(requestDraw);
    resizeObserver.observe(canvas);
    const intersectionObserver = new IntersectionObserver(([entry]) => {
      inView = entry?.isIntersecting ?? true;
      if (inView) requestDraw();
      else if (frame) {
        cancelAnimationFrame(frame);
        frame = 0;
      }
    });
    intersectionObserver.observe(canvas);
    const onVisibility = () => {
      visible = document.visibilityState === "visible";
      if (visible) requestDraw();
      else if (frame) {
        cancelAnimationFrame(frame);
        frame = 0;
      }
    };
    document.addEventListener("visibilitychange", onVisibility);
    requestDraw();

    return () => {
      disposed = true;
      cancelAnimationFrame(frame);
      resizeObserver.disconnect();
      intersectionObserver.disconnect();
      document.removeEventListener("visibilitychange", onVisibility);
      gl.deleteBuffer(buffer);
      gl.deleteProgram(program);
      gl.getExtension("WEBGL_lose_context")?.loseContext();
    };
  }

  window.ThreadTreeShaderBackground = { mount };
})();
