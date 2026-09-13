import * as THREE from "three";

const BG = 0x05080f;
const CYAN = 0x22d3ee;
const AMBER = 0xf59e0b;

// Building dimensions (meters, roughly to scale)
const W = 6; // footprint width  (x)
const D = 4.4; // footprint depth (z)
const WALL_H = 1.5;
const RIDGE_H = 1.05; // wall-top -> ridge
const RIDGE_HALF = 1.55; // half ridge length along x

function hipRoofGeometry() {
  const hw = W / 2;
  const hd = D / 2;
  const y = WALL_H;
  const ry = WALL_H + RIDGE_H;

  // eave corners: 1 back-left, 2 back-right, 3 front-right, 4 front-left
  const c1 = [-hw, y, -hd];
  const c2 = [hw, y, -hd];
  const c3 = [hw, y, hd];
  const c4 = [-hw, y, hd];
  // ridge ends
  const r1 = [-RIDGE_HALF, ry, 0];
  const r2 = [RIDGE_HALF, ry, 0];

  const tris = [
    // front slope
    c4, c3, r2, c4, r2, r1,
    // back slope
    c2, c1, r1, c2, r1, r2,
    // left hip
    c1, c4, r1,
    // right hip
    c3, c2, r2,
  ];

  const geo = new THREE.BufferGeometry();
  geo.setAttribute(
    "position",
    new THREE.Float32BufferAttribute(tris.flat(), 3)
  );
  geo.computeVertexNormals();
  return geo;
}

function makeLabel(text, scale = 1) {
  const pad = 24;
  const font = '600 44px "Space Grotesk", monospace';
  const cv = document.createElement("canvas");
  const ctx = cv.getContext("2d");
  ctx.font = font;
  cv.width = Math.ceil(ctx.measureText(text).width) + pad * 2;
  cv.height = 84;
  ctx.font = font;
  ctx.fillStyle = "#f5b14c";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(text, cv.width / 2, cv.height / 2 + 2);
  const tex = new THREE.CanvasTexture(cv);
  tex.anisotropy = 4;
  const sprite = new THREE.Sprite(
    new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false })
  );
  sprite.scale.set((cv.width / cv.height) * 0.42 * scale, 0.42 * scale, 1);
  return sprite;
}

function lineSegments(points, color, opacity) {
  const geo = new THREE.BufferGeometry().setFromPoints(
    points.map((p) => new THREE.Vector3(...p))
  );
  return new THREE.LineSegments(
    geo,
    new THREE.LineBasicMaterial({ color, transparent: true, opacity })
  );
}

function dimensionLines() {
  const g = new THREE.Group();
  const hw = W / 2;
  const hd = D / 2;
  const off = 1.0;
  const y = 0.02;
  const tick = 0.16;

  // front dimension (width) — offset toward +z
  const fz = hd + off;
  g.add(
    lineSegments(
      [
        // main line
        [-hw, y, fz], [hw, y, fz],
        // end ticks
        [-hw, y - tick, fz], [-hw, y + tick, fz],
        [hw, y - tick, fz], [hw, y + tick, fz],
        // extension lines from eave corners
        [-hw, y, hd], [-hw, y, fz + 0.15],
        [hw, y, hd], [hw, y, fz + 0.15],
      ],
      AMBER,
      0.9
    )
  );
  const wLabel = makeLabel("12.4 m");
  wLabel.position.set(0, y + 0.34, fz);
  g.add(wLabel);

  // right dimension (depth) — offset toward +x
  const rx = hw + off;
  g.add(
    lineSegments(
      [
        [rx, y, -hd], [rx, y, hd],
        [rx - tick, y, -hd], [rx + tick, y, -hd],
        [rx - tick, y, hd], [rx + tick, y, hd],
        [hw, y, -hd], [rx + 0.15, y, -hd],
        [hw, y, hd], [rx + 0.15, y, hd],
      ],
      AMBER,
      0.9
    )
  );
  const dLabel = makeLabel("8.6 m");
  dLabel.position.set(rx + 0.1, y + 0.34, 0);
  g.add(dLabel);

  return g;
}

function makeParticles() {
  const N = 260;
  const pos = new Float32Array(N * 3);
  const col = new Float32Array(N * 3);
  const speed = new Float32Array(N);
  const cyan = new THREE.Color(CYAN);
  const amber = new THREE.Color(AMBER);

  for (let i = 0; i < N; i++) {
    pos[i * 3] = (Math.random() - 0.5) * 14;
    pos[i * 3 + 1] = Math.random() * 5;
    pos[i * 3 + 2] = (Math.random() - 0.5) * 14;
    const c = Math.random() < 0.82 ? cyan : amber;
    col[i * 3] = c.r;
    col[i * 3 + 1] = c.g;
    col[i * 3 + 2] = c.b;
    speed[i] = 0.15 + Math.random() * 0.45;
  }

  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  geo.setAttribute("color", new THREE.BufferAttribute(col, 3));
  const pts = new THREE.Points(
    geo,
    new THREE.PointsMaterial({
      size: 0.045,
      vertexColors: true,
      transparent: true,
      opacity: 0.65,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    })
  );
  pts.userData.speed = speed;
  return pts;
}

function makeBuilding() {
  const group = new THREE.Group();

  // ground slab
  const slab = new THREE.Mesh(
    new THREE.BoxGeometry(W + 0.7, 0.12, D + 0.7),
    new THREE.MeshStandardMaterial({
      color: 0x0a1626,
      transparent: true,
      opacity: 0.5,
      roughness: 0.9,
    })
  );
  slab.position.y = 0.06;
  group.add(slab);
  group.add(
    new THREE.LineSegments(
      new THREE.EdgesGeometry(slab.geometry),
      new THREE.LineBasicMaterial({ color: CYAN, transparent: true, opacity: 0.35 })
    ).translateY(0.06)
  );

  // walls
  const walls = new THREE.Mesh(
    new THREE.BoxGeometry(W, WALL_H, D),
    new THREE.MeshStandardMaterial({
      color: 0x12324e,
      transparent: true,
      opacity: 0.14,
      roughness: 0.7,
    })
  );
  walls.position.y = WALL_H / 2;
  group.add(walls);
  group.add(
    new THREE.LineSegments(
      new THREE.EdgesGeometry(walls.geometry),
      new THREE.LineBasicMaterial({ color: CYAN, transparent: true, opacity: 0.5 })
    ).translateY(WALL_H / 2)
  );

  // hip roof
  const roofGeo = hipRoofGeometry();
  const roof = new THREE.Mesh(
    roofGeo,
    new THREE.MeshStandardMaterial({
      color: 0x0e4a5c,
      transparent: true,
      opacity: 0.28,
      roughness: 0.5,
      metalness: 0.2,
      side: THREE.DoubleSide,
    })
  );
  group.add(roof);
  group.add(
    new THREE.LineSegments(
      new THREE.EdgesGeometry(roofGeo, 1),
      new THREE.LineBasicMaterial({ color: CYAN, transparent: true, opacity: 0.95 })
    )
  );

  group.add(dimensionLines());
  return group;
}

function makeScanRing(maxRadius) {
  const geo = new THREE.RingGeometry(maxRadius - 0.05, maxRadius, 64);
  const ring = new THREE.Mesh(
    geo,
    new THREE.MeshBasicMaterial({
      color: CYAN,
      transparent: true,
      opacity: 0.0,
      side: THREE.DoubleSide,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    })
  );
  ring.rotation.x = -Math.PI / 2;
  return ring;
}

export function initHeroScene(canvas) {
  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({
      canvas,
      antialias: true,
      alpha: true,
      powerPreference: "high-performance",
    });
  } catch {
    canvas.style.display = "none";
    return;
  }

  renderer.setClearColor(0x000000, 0);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.75));

  const scene = new THREE.Scene();
  scene.fog = new THREE.Fog(BG, 16, 34);

  const camera = new THREE.PerspectiveCamera(38, 1, 0.1, 100);
  const camBase = new THREE.Vector3(8.2, 4.4, 8.6);
  const camTarget = new THREE.Vector3(0, 1.5, 0);
  camera.position.copy(camBase);

  scene.add(new THREE.AmbientLight(0x8fb8dd, 0.55));
  const key = new THREE.DirectionalLight(0xbfe9ff, 1.4);
  key.position.set(6, 9, 5);
  scene.add(key);
  const rim = new THREE.PointLight(CYAN, 14, 22);
  rim.position.set(-5, 3.5, -4);
  scene.add(rim);

  // ground grid
  const grid = new THREE.GridHelper(36, 36, 0x1d3a52, 0x12233a);
  grid.material.transparent = true;
  grid.material.opacity = 0.5;
  scene.add(grid);

  const building = makeBuilding();
  const spin = new THREE.Group();
  spin.add(building);
  scene.add(spin);

  const topY = WALL_H + RIDGE_H + 0.4;
  const scanRing = makeScanRing(Math.hypot(W, D) / 2 + 0.55);
  scene.add(scanRing);

  const particles = makeParticles();
  scene.add(particles);

  // pointer parallax
  const pointer = new THREE.Vector2(0, 0);
  const onPointer = (e) => {
    pointer.x = (e.clientX / window.innerWidth) * 2 - 1;
    pointer.y = (e.clientY / window.innerHeight) * 2 - 1;
  };
  window.addEventListener("pointermove", onPointer, { passive: true });

  function resize() {
    const { clientWidth: w, clientHeight: h } = canvas;
    if (canvas.width !== Math.floor(w * renderer.getPixelRatio())) {
      renderer.setSize(w, h, false);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    }
  }
  window.addEventListener("resize", resize, { passive: true });

  // run only while hero is visible and tab is active
  let inView = true;
  new IntersectionObserver(([e]) => (inView = e.isIntersecting), {
    threshold: 0.02,
  }).observe(canvas);

  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const clock = new THREE.Clock();
  const scanDuration = 4.5;

  function tick() {
    const dt = Math.min(clock.getDelta(), 0.05);
    const t = clock.elapsedTime;

    spin.rotation.y += dt * 0.14;

    // scan ring: rise through the building, then restart
    const p = (t % scanDuration) / scanDuration;
    scanRing.position.y = p * topY;
    scanRing.material.opacity = Math.sin(p * Math.PI) * 0.55;

    // particles drift upward
    const pos = particles.geometry.attributes.position;
    const speed = particles.userData.speed;
    for (let i = 0; i < speed.length; i++) {
      let y = pos.getY(i) + speed[i] * dt;
      if (y > 5.2) y = 0;
      pos.setY(i, y);
    }
    pos.needsUpdate = true;

    // camera parallax
    camera.position.x += (camBase.x + pointer.x * 0.9 - camera.position.x) * 0.04;
    camera.position.y += (camBase.y - pointer.y * 0.5 - camera.position.y) * 0.04;
    camera.lookAt(camTarget);

    resize();
    renderer.render(scene, camera);
  }

  if (reduced) {
    resize();
    renderer.render(scene, camera);
    return;
  }

  renderer.setAnimationLoop(() => {
    if (inView && !document.hidden) tick();
  });
}
