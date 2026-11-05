// The front door's film: one job, live as you scroll. The test is locked (Resolve), the bid waits (Price), the check
// runs on two agents' work (Settle), and the money moves to the agent that passed, never the other (Work).
// Real-time three.js, after the template of prompt-motion.com/templates/realtime (prompt by Prompt Motion, curated by
// @p4nthera_, x.com/p4nthera_): physical materials, an environment map, soft shadows, ACES tone mapping and fog, a film
// camera instead of orbit controls, springs instead of linear tweens, and ?t=<seconds> draws any frame from time alone.
// The parts come apart with the exploded view of Open 3D Skills (web/brand/explode.js, MIT, exploraX).
// three.js (MIT) loads only after the first paint; phones and a reader who asks for no motion get the still.
const film = document.getElementById("k-film");
const still = !film || matchMedia("(max-width: 760px), (prefers-reduced-motion: reduce)").matches;
const params = new URLSearchParams(location.search);
const atT = params.has("t");
const DURATION = 24;
const STAGES = [[0.0, 0.25, "Resolve", "The test is locked before money moves."], [0.25, 0.5, "Price", "The bid waits against that test."],
  [0.5, 0.75, "Settle", "The check runs on each agent's work."], [0.75, 1.01, "Work", "Only the agent that passed is paid."]];

async function start() {
  const THREE = await import("../near/story/vendor/three.module.min.js");
  const { Exploder } = await import("./explode.js");
  const canvas = film.querySelector("canvas");
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, preserveDrawingBuffer: atT });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  const css = getComputedStyle(document.documentElement);
  const tok = (n, f) => (css.getPropertyValue(n).trim() || f);
  const PAPER = tok("--paper", "#07080c"), ACCENT = tok("--accent", "#93a5ff"), OK = tok("--ok", "#5fd28f"), BAD = tok("--bad", "#ff8a80"), WARN = tok("--warn", "#e0b354"), SOFT = tok("--soft", "#151822");
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(PAPER);
  scene.fog = new THREE.Fog(PAPER, 9, 22);
  // the environment: a soft room made of lit panels, prefiltered (PMREM), so the physical materials have light to show
  const room = new THREE.Scene();
  const panel = (c, x, y, z, s) => { const m = new THREE.Mesh(new THREE.PlaneGeometry(s, s), new THREE.MeshBasicMaterial({ color: c, side: THREE.DoubleSide })); m.position.set(x, y, z); m.lookAt(0, 0, 0); room.add(m); };
  panel("#ffffff", 0, 6, 0, 8); panel(ACCENT, -6, 2, 2, 5); panel("#ffe2b0", 6, 2, -2, 5); panel("#30344a", 0, -6, 0, 10);
  const pmrem = new THREE.PMREMGenerator(renderer);
  scene.environment = pmrem.fromScene(room, 0.04).texture;
  const key = new THREE.DirectionalLight("#ffffff", 2.4);
  key.position.set(-3, 6, 4); key.castShadow = true; key.shadow.mapSize.set(1024, 1024); key.shadow.radius = 6;
  Object.assign(key.shadow.camera, { left: -5, right: 5, top: 5, bottom: -5 });
  scene.add(key);
  const mat = (c, o = {}) => new THREE.MeshPhysicalMaterial({ color: c, roughness: 0.32, metalness: 0.15, clearcoat: 0.6, clearcoatRoughness: 0.25, ...o });
  const shadowed = (m) => { m.castShadow = true; m.receiveShadow = true; return m; };
  const floor = new THREE.Mesh(new THREE.CircleGeometry(9, 96), mat(SOFT, { roughness: 0.9, clearcoat: 0 }));
  floor.rotation.x = -Math.PI / 2; floor.position.y = -1.1; floor.receiveShadow = true; scene.add(floor);

  // the job, assembled: the check (a gate) with the locked test on top and the bid inside
  const job = new THREE.Group(); scene.add(job);
  const part = (mesh, explode) => { const g = new THREE.Group(); g.add(mesh); g.userData = { explode }; job.add(g); return g; };
  const gate = part(shadowed(new THREE.Mesh(new THREE.TorusGeometry(0.75, 0.16, 48, 128), mat(ACCENT, { metalness: 0.35 }))), [0, 0, 0]);
  const plate = shadowed(new THREE.Mesh(new THREE.BoxGeometry(1.2, 0.08, 0.8), mat(OK)));
  plate.position.y = 1.05;
  const test = part(plate, [0, 1.1, 0]);
  const coin = shadowed(new THREE.Mesh(new THREE.CylinderGeometry(0.28, 0.28, 0.08, 64), mat(WARN, { metalness: 0.85, roughness: 0.2 })));
  coin.rotation.x = Math.PI / 2;
  const bid = part(coin, [0, -0.2, 1.1]);
  // two agents' work, on either side; the scan light shows which passes
  const agent = (x, c) => { const m = shadowed(new THREE.Mesh(new THREE.IcosahedronGeometry(0.34, 2), mat(c, { roughness: 0.4 }))); m.position.set(x, -0.6, 0); scene.add(m); return m; };
  const passing = agent(-2.4, "#e9ebef"), failing = agent(2.4, "#e9ebef");
  const ex = new Exploder(job);

  // springs: each value chases its target with a little give, the same at any frame rate (fixed 1/120 s steps)
  const spring = (k = 90, c = 16) => ({ x: 0, v: 0, step(target, dt) { for (let t = 0; t < dt; t += 1 / 120) { const a = -k * (this.x - target) - c * this.v; this.v += a / 120; this.x += this.v / 120; } return this.x; } });
  const sx = spring(), sy = spring(), sd = spring(70, 14), se = spring(60, 13), sc = spring(50, 12);
  const clamp = (v) => Math.min(1, Math.max(0, v));
  const cap = film.querySelector("[data-stage]"), capLine = film.querySelector("[data-line]");
  const resize = () => { const w = canvas.clientWidth, h = canvas.clientHeight; renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix(); };
  const camera = new THREE.PerspectiveCamera(32, 1, 0.1, 60);
  // each part named on screen next to it, so no shape has to be guessed and pass or fail is said in words
  const layer = canvas.parentElement, v = new THREE.Vector3();
  const tag = (obj, text) => { const s = document.createElement("span"); s.className = "k-film-tag"; s.setAttribute("aria-hidden", "true"); s.textContent = text; layer.append(s); return { obj, s }; };
  const tags = [tag(plate, "Test, locked"), tag(coin, "Bid, held"), tag(gate.children[0], "Check"), tag(passing, "Agent A"), tag(failing, "Agent B")];
  const place = () => {
    const w = canvas.clientWidth, h = canvas.clientHeight;
    for (const { obj, s } of tags) {
      obj.getWorldPosition(v); v.y += obj === plate ? 0.25 : obj === coin ? -0.35 : obj.geometry?.type === "TorusGeometry" ? 0.98 : -0.6; v.project(camera);
      const half = s.offsetWidth / 2 + 12, x = Math.min(w - half, Math.max(half, (v.x + 1) / 2 * w));   // the whole name stays in frame
      s.style.transform = `translate(${Math.round(x)}px, ${Math.round((1 - v.y) / 2 * h)}px) translate(-50%, -50%)`;
    }
  };
  let last = 0, warm = false;
  function frame(p, dt) {
    if (!warm) { for (const s of [sx, sy, sd, se, sc]) { s.x = s === sd ? 9 : 0; } warm = true; }
    // film camera: a slow push in, a crane up at Settle, a dolly to the passing agent at Work
    const shotX = p < 0.75 ? 0 : -0.8 * clamp((p - 0.75) / 0.2), shotY = 1.2 + (p > 0.5 ? 1.3 * clamp((p - 0.5) / 0.2) : 0);
    // Price: the camera swings round the job, about 40 degrees out and back, so the bid can be seen waiting inside
    const orbit = 0.7 * Math.sin(Math.PI * clamp((p - 0.18) / 0.42));
    const cx = shotX + 1.2 * (1 - p), cz = 8.6 - 2.2 * p;
    camera.position.set(sx.step(cx * Math.cos(orbit) + cz * Math.sin(orbit), dt), sy.step(shotY, dt), sd.step(cz * Math.cos(orbit) - cx * Math.sin(orbit), dt));
    camera.lookAt(shotX * 0.6, 0, 0);
    ex.set(se.step(p < 0.25 ? clamp(p / 0.25) : p < 0.75 ? 1 : 1 - clamp((p - 0.75) / 0.15) * 0.6, dt));
    // Settle: the scan; Work: the coin travels to the passing agent, the other turns red and gets nothing
    const scan = clamp((p - 0.5) / 0.2), pay = sc.step(clamp((p - 0.78) / 0.18), dt);
    passing.material.color.set(scan > 0.5 ? OK : "#e9ebef");
    failing.material.color.set(scan > 0.9 ? BAD : "#e9ebef");
    gate.rotation.z = scan * Math.PI * 2;
    coin.position.set(-2.4 * pay, Math.sin(pay * Math.PI) * 1.3 - 0.2 * pay, -1.1 * pay);
    const stage = STAGES.find(([a, b]) => p >= a && p < b) || STAGES[STAGES.length - 1];
    if (cap.textContent !== stage[2]) { cap.textContent = stage[2]; capLine.textContent = stage[3]; }
    const said = (t, text) => { if (t.s.textContent !== text) t.s.textContent = text; };
    said(tags[3], scan > 0.5 ? (pay > 0.9 ? "Agent A: passed, paid" : "Agent A: passed") : "Agent A");
    said(tags[4], scan > 0.9 ? "Agent B: failed, paid 0" : "Agent B");
    said(tags[1], pay > 0.9 ? "Bid, paid to A" : "Bid, held");
    renderer.render(scene, camera);
    place();
  }
  resize();
  addEventListener("resize", resize);
  // the video's clock: a frame from t alone (springs settled by stepping from 0 to t)
  window.renderAt = (t) => { warm = false; const p = clamp(t / DURATION); for (let s = 0; s < t; s += 0.1) frame(clamp(s / DURATION), 0.1); frame(p, 0.016); return true; };
  if (atT) { window.renderAt(+params.get("t")); film.dataset.ready = "1"; return; }
  let target = 0;
  const read = () => { const r = film.getBoundingClientRect(); target = clamp(-r.top / Math.max(1, r.height - innerHeight)); };
  addEventListener("scroll", read, { passive: true });
  read();
  const loop = (now) => { const dt = Math.min(0.05, (now - last) / 1000 || 0.016); last = now; frame(target, dt); requestAnimationFrame(loop); };
  requestAnimationFrame(loop);
  film.dataset.ready = "1";
}

if (!still || atT) {
  const go = () => start().catch((e) => { console.error(e); film.classList.add("k-film-still"); });
  // the scene starts only when the film nears the viewport, so the first screen's main thread stays free
  const near = () => { const io = new IntersectionObserver((es) => { if (es.some((e) => e.isIntersecting)) { io.disconnect(); go(); } }, { rootMargin: "200px" }); io.observe(film); };
  if (atT) go(); else addEventListener("load", near, { once: true });
}
