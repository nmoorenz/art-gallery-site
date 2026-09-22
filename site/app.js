import * as THREE from 'three';
import { MANIFEST_URL } from './config.js';

// ---------------------------------------------------------------------------
// DOM
// ---------------------------------------------------------------------------
const container = document.getElementById('scene-container');
const loadingOverlay = document.getElementById('loading-overlay');
const loadingFill = document.getElementById('loading-bar-fill');
const loadingStatus = document.getElementById('loading-status');
const enterOverlay = document.getElementById('enter-overlay');
const enterButton = document.getElementById('enter-button');
const hintBar = document.getElementById('hint-bar');
const infoPanel = document.getElementById('info-panel');
const infoImage = document.getElementById('info-image');
const infoTitle = document.getElementById('info-title');
const infoMeta = document.getElementById('info-meta');
const infoNotes = document.getElementById('info-notes');
const infoClose = document.getElementById('info-close');
const infoPrev = document.getElementById('info-prev');
const infoNext = document.getElementById('info-next');
const infoCounter = document.getElementById('info-image-counter');
const joystick = document.getElementById('joystick');
const joystickKnob = document.getElementById('joystick-knob');

const IS_TOUCH = ('ontouchstart' in window) || navigator.maxTouchPoints > 0;
if (IS_TOUCH) document.body.classList.add('touch');

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------
const EYE_HEIGHT = 1.6;
const WALK_SPEED = 3.0;          // metres/second
const TURN_SPEED = 2.2;          // radians/second, for the left/right arrow keys
const WALL_MARGIN = 0.55;        // how close to a wall the camera may get
const FRAME_MAX_W = 1.5;
const FRAME_MAX_H = 1.2;
const FRAME_DEPTH = 0.05;
const FRAME_BORDER = 0.07;
const PIECE_CENTER_Y = 1.6;      // hang height, metres off the floor
const WALL_THICKNESS = 0.2;
const LOOK_SPEED = 0.0045;       // radians per pixel of drag
const HUB_MIN_RADIUS = 4;
const DOORWAY_ARC = 7.5;         // metres of hub circumference reserved per corridor entrance

// ---------------------------------------------------------------------------
// Scene / camera / renderer
// ---------------------------------------------------------------------------
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x0a0a12);
scene.fog = new THREE.Fog(0x0a0a12, 9, 30);

const camera = new THREE.PerspectiveCamera(70, window.innerWidth / window.innerHeight, 0.1, 100);
camera.position.set(0, EYE_HEIGHT, 0);

const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.setSize(window.innerWidth, window.innerHeight);
container.appendChild(renderer.domElement);

window.addEventListener('resize', () => {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
});

scene.add(new THREE.AmbientLight(0x50506a, 1.1));
scene.add(new THREE.HemisphereLight(0x8895aa, 0x0e0e14, 0.45));

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
let wallHeight = 3.2;
let hubRadius = HUB_MIN_RADIUS;
// One entry per category/corridor: { category, angle, length, width, originX, originZ }
// -- the layout's "map": walking from the hub down corridor i means walking
// in direction `angle`. Used by clampPosition() to keep the camera inside
// whichever corridor (or the hub) it's currently in.
const corridors = [];
const raycastTargets = [];
let infoPanelOpen = false;
let entered = false;

// forward/back/strafeLeft/strafeRight move the camera; turnLeft/turnRight
// (left/right arrows) rotate it in place instead, like a mouse-look but on
// the keyboard -- A/D still strafe, only the arrow keys' behaviour differs.
const keys = { forward: false, back: false, strafeLeft: false, strafeRight: false, turnLeft: false, turnRight: false };

// look state (click-and-drag on desktop, touch-drag on mobile -- same code
// either way, the cursor/finger is never captured)
let lookYaw = 0, lookPitch = 0;
let dragActive = false, dragPointerId = null, dragLastX = 0, dragLastY = 0, dragDistance = 0;

// joystick (touch movement only -- desktop uses arrow keys)
let moveTouchId = null, moveCenterX = 0, moveCenterY = 0;
let moveVector = { x: 0, y: 0 };

const raycaster = new THREE.Raycaster();
const clock = new THREE.Clock();

// ---------------------------------------------------------------------------
// Load manifest, then build the gallery
// ---------------------------------------------------------------------------
init().catch((err) => {
  console.error(err);
  loadingStatus.textContent = 'Could not load the gallery: ' + err.message;
});

async function init() {
  const manifest = await fetchManifest();
  const pieces = manifest.pieces || [];
  const hallwayCfg = manifest.hallway || {};
  wallHeight = hallwayCfg.wallHeight || 3.2;

  const manager = new THREE.LoadingManager();
  manager.onProgress = (_url, loaded, total) => {
    const pct = total ? Math.round((loaded / total) * 100) : 0;
    loadingFill.style.width = pct + '%';
    loadingStatus.textContent = 'Loading artwork… ' + loaded + ' / ' + total;
  };
  manager.onError = (url) => console.warn('Failed to load', url);

  const textureLoader = new THREE.TextureLoader(manager);

  buildGallery(hallwayCfg, pieces, textureLoader);

  manager.onLoad = () => {
    loadingOverlay.classList.add('hidden');
    enterOverlay.classList.remove('hidden');
  };
  // If there are no pieces at all, onLoad may never fire (nothing queued).
  if (pieces.length === 0) {
    loadingOverlay.classList.add('hidden');
    enterOverlay.classList.remove('hidden');
  }

  setupControls();
  setupInfoPanel();
  animate();
}

async function fetchManifest() {
  const res = await fetch(MANIFEST_URL, { cache: 'no-store', credentials: 'same-origin' });
  const contentType = res.headers.get('content-type') || '';
  if (!res.ok || !contentType.includes('json')) {
    // In production this almost always means: not logged in, and CloudFront's
    // custom-error-response quietly swapped in login.html's HTML (with a 200
    // status) instead of the real manifest. Do a full navigation to the real
    // login page rather than trying to render HTML as data.
    window.location.href = 'login.html';
    throw new Error('not authenticated -- redirecting to login');
  }
  return res.json();
}

// ---------------------------------------------------------------------------
// Top-level layout: a circular hub, with one corridor per category radiating
// outward at an evenly spaced angle. The hub doubles as the "map" -- each
// corridor entrance carries a floating label with its category name, same
// idea as walking into a small museum's lobby and reading the signs.
// ---------------------------------------------------------------------------
function buildGallery(hallwayCfg, pieces, textureLoader) {
  const byCategory = new Map();
  for (const piece of pieces) {
    const category = piece.category || 'Uncategorised';
    if (!byCategory.has(category)) byCategory.set(category, []);
    byCategory.get(category).push(piece);
  }
  const categories = Array.from(byCategory.keys()).sort((a, b) => a.localeCompare(b));
  const n = categories.length;

  const width = hallwayCfg.width || 6;
  const neededCircumference = n * DOORWAY_ARC;
  hubRadius = Math.max(HUB_MIN_RADIUS, neededCircumference / (2 * Math.PI));

  buildHub(hubRadius);

  const angleStep = n > 0 ? (2 * Math.PI) / n : 0;
  categories.forEach((category, i) => {
    const angle = i * angleStep;
    const originX = hubRadius * -Math.sin(angle);
    const originZ = hubRadius * -Math.cos(angle);

    const { group, length } = buildCorridor(byCategory.get(category), hallwayCfg, textureLoader, category);
    group.position.set(originX, 0, originZ);
    group.rotation.y = angle;
    scene.add(group);

    corridors.push({ category, angle, length, width, originX, originZ });
  });
}

function buildHub(radius) {
  const floorMat = new THREE.MeshStandardMaterial({ color: 0x241f1b, roughness: 0.95 });
  const ceilingMat = new THREE.MeshStandardMaterial({ color: 0x15141a, roughness: 1 });

  const floor = new THREE.Mesh(new THREE.CylinderGeometry(radius, radius, 0.1, 48), floorMat);
  floor.position.set(0, -0.05, 0);
  scene.add(floor);

  const ceiling = new THREE.Mesh(new THREE.CylinderGeometry(radius, radius, 0.1, 48), ceilingMat);
  ceiling.position.set(0, wallHeight + 0.05, 0);
  scene.add(ceiling);

  const centerLight = new THREE.PointLight(0xfff2d8, 1.2, radius * 2.4, 2);
  centerLight.position.set(0, wallHeight - 0.4, 0);
  scene.add(centerLight);
}

// Builds one corridor (floor/ceiling/walls/art) entirely in LOCAL coordinates
// -- identical shape to a simple straight hallway starting at local (0,0,0)
// and extending away along local -Z. The caller positions/rotates the
// returned group to plug it into the hub at the right angle.
function buildCorridor(categoryPieces, hallwayCfg, textureLoader, categoryName) {
  const width = hallwayCfg.width || 6;
  const spacing = hallwayCfg.spacing || 2.4;
  const margin = hallwayCfg.margin || 2.2;
  const rows = Math.max(1, Math.ceil(categoryPieces.length / 2));
  const length = Math.max(margin * 2 + spacing * rows, 8);

  const group = new THREE.Group();

  const floorMat = new THREE.MeshStandardMaterial({ color: 0x241f1b, roughness: 0.95 });
  const ceilingMat = new THREE.MeshStandardMaterial({ color: 0x15141a, roughness: 1 });
  const wallMat = new THREE.MeshStandardMaterial({ color: 0xe9e6df, roughness: 0.85 });
  const fullSpanW = width + WALL_THICKNESS * 2;

  const floor = new THREE.Mesh(new THREE.BoxGeometry(fullSpanW, 0.1, length), floorMat);
  floor.position.set(0, -0.05, -length / 2);
  group.add(floor);

  const ceiling = new THREE.Mesh(new THREE.BoxGeometry(fullSpanW, 0.1, length), ceilingMat);
  ceiling.position.set(0, wallHeight + 0.05, -length / 2);
  group.add(ceiling);

  const leftWall = new THREE.Mesh(new THREE.BoxGeometry(WALL_THICKNESS, wallHeight, length), wallMat);
  leftWall.position.set(-width / 2 - WALL_THICKNESS / 2, wallHeight / 2, -length / 2);
  group.add(leftWall);

  const rightWall = new THREE.Mesh(new THREE.BoxGeometry(WALL_THICKNESS, wallHeight, length), wallMat);
  rightWall.position.set(width / 2 + WALL_THICKNESS / 2, wallHeight / 2, -length / 2);
  group.add(rightWall);

  const farWall = new THREE.Mesh(new THREE.BoxGeometry(fullSpanW, wallHeight, WALL_THICKNESS), wallMat);
  farWall.position.set(0, wallHeight / 2, -length - WALL_THICKNESS / 2);
  group.add(farWall);

  for (let z = -1.5; z > -length; z -= 4) {
    const bulb = new THREE.PointLight(0xfff2d8, 0.9, 7, 2);
    bulb.position.set(0, wallHeight - 0.3, z);
    group.add(bulb);
  }

  const label = makeLabelSprite(categoryName);
  label.position.set(0, wallHeight - 0.55, -0.6);
  group.add(label);

  placePieces(categoryPieces, group, width, textureLoader);

  return { group, length };
}

function makeLabelSprite(text) {
  const canvas = document.createElement('canvas');
  canvas.width = 640;
  canvas.height = 160;
  const ctx = canvas.getContext('2d');
  ctx.font = "700 78px Georgia, 'Times New Roman', serif";
  ctx.fillStyle = '#f0dfa8';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(text, canvas.width / 2, canvas.height / 2 + 4);

  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  const material = new THREE.SpriteMaterial({ map: texture, transparent: true, depthWrite: false });
  const sprite = new THREE.Sprite(material);
  sprite.scale.set(3.2, 0.8, 1);
  return sprite;
}

// ---------------------------------------------------------------------------
// Place artwork along a corridor's two walls, alternating sides
// ---------------------------------------------------------------------------
function piecesImages(piece) {
  if (Array.isArray(piece.images) && piece.images.length) return piece.images;
  // legacy manifest shape, from before pieces carried an images[] array
  return [{ id: piece.id, label: '', thumb: piece.thumb, full: piece.full || piece.thumb, aspect: piece.aspect }];
}

function placePieces(pieces, group, width, textureLoader) {
  const spacing = 2.4;
  const margin = 2.2;
  const frameMat = new THREE.MeshStandardMaterial({ color: 0x2b1d14, roughness: 0.6 });

  pieces.forEach((piece, i) => {
    const side = i % 2 === 0 ? 'left' : 'right';
    const row = Math.floor(i / 2);
    const z = -(margin + row * spacing);
    const images = piecesImages(piece);
    const cover = images[0];
    const aspect = cover.aspect && cover.aspect > 0 ? cover.aspect : 1.3;

    let imgW, imgH;
    if (aspect >= 1) { imgW = FRAME_MAX_W; imgH = FRAME_MAX_W / aspect; }
    else { imgH = FRAME_MAX_H; imgW = FRAME_MAX_H * aspect; }
    const frameW = imgW + FRAME_BORDER * 2;
    const frameH = imgH + FRAME_BORDER * 2;

    const wallX = side === 'left' ? -width / 2 : width / 2;
    const normalSign = side === 'left' ? 1 : -1; // +X for left wall, -X for right wall

    // backing frame (thin box flush against the wall)
    const backing = new THREE.Mesh(new THREE.BoxGeometry(FRAME_DEPTH, frameH, frameW), frameMat);
    backing.position.set(wallX + normalSign * (FRAME_DEPTH / 2 + 0.005), PIECE_CENTER_Y, z);
    group.add(backing);

    // picture plane
    const picMat = new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.9 });
    const picGeo = new THREE.PlaneGeometry(imgW, imgH);
    const pic = new THREE.Mesh(picGeo, picMat);
    pic.position.set(wallX + normalSign * (FRAME_DEPTH + 0.01), PIECE_CENTER_Y, z);
    pic.rotation.y = side === 'left' ? Math.PI / 2 : -Math.PI / 2;
    pic.userData = {
      id: piece.id,
      title: piece.name || 'Untitled',
      date: piece.date || '',
      category: piece.category || '',
      era: piece.era || '',
      medium: piece.medium || '',
      notes: piece.description || '',
      images,
    };
    group.add(pic);
    raycastTargets.push(pic);

    textureLoader.load(cover.thumb, (tex) => {
      tex.colorSpace = THREE.SRGBColorSpace;
      if (side === 'left') {
        // the left-wall plane is mirrored by its +90 deg rotation; flip the
        // texture's U axis back so text/signatures read the right way round.
        tex.wrapS = THREE.RepeatWrapping;
        tex.repeat.x = -1;
        tex.offset.x = 1;
      }
      picMat.map = tex;
      picMat.needsUpdate = true;
    });

    // small spotlight to make the piece feel lit/hung
    const spot = new THREE.PointLight(0xfff6e6, 0.6, 3.5, 2);
    spot.position.set(wallX + normalSign * 0.8, PIECE_CENTER_Y + 0.6, z);
    group.add(spot);
  });
}

// ---------------------------------------------------------------------------
// Controls: click-and-drag (or touch-drag) to look, arrow keys or a joystick
// to walk. The cursor/finger is never captured -- no pointer lock anywhere.
// ---------------------------------------------------------------------------
function setupControls() {
  enterButton.addEventListener('click', () => {
    enterOverlay.classList.add('hidden');
    entered = true;
    camera.position.set(0, EYE_HEIGHT, 0);
    lookYaw = 0;
    lookPitch = 0;
    hintBar.textContent = IS_TOUCH
      ? 'Drag to look around · use the joystick to walk · tap a piece to view it'
      : 'Click and drag to look around · WASD to walk, left/right arrows to turn · click a piece to view it';
    hintBar.classList.remove('hidden');
  });

  setupDragLook();
  if (IS_TOUCH) {
    joystick.classList.remove('hidden');
    setupTouchJoystick();
  }
  // Always listen for the keyboard, touch device or not -- some Windows
  // laptops report touch capability even without a touchscreen in use, so
  // gating this on IS_TOUCH silently broke the keyboard on those machines.
  document.addEventListener('keydown', (e) => setKey(e.code, true));
  document.addEventListener('keyup', (e) => setKey(e.code, false));
}

function setKey(code, down) {
  if (code === 'KeyW' || code === 'ArrowUp') keys.forward = down;
  if (code === 'KeyS' || code === 'ArrowDown') keys.back = down;
  if (code === 'KeyA') keys.strafeLeft = down;
  if (code === 'KeyD') keys.strafeRight = down;
  if (code === 'ArrowLeft') keys.turnLeft = down;
  if (code === 'ArrowRight') keys.turnRight = down;
}

// Pointer Events cover mouse + touch with one code path; touch movement
// (the joystick) is handled separately below since it needs its own
// dedicated screen region.
function setupDragLook() {
  const el = renderer.domElement;

  el.addEventListener('pointerdown', (e) => {
    if (!entered || infoPanelOpen) return;
    if (isOverJoystick(e)) return;
    dragActive = true;
    dragPointerId = e.pointerId;
    dragLastX = e.clientX;
    dragLastY = e.clientY;
    dragDistance = 0;
    el.setPointerCapture(e.pointerId);
    el.classList.add('dragging');
  });

  el.addEventListener('pointermove', (e) => {
    if (!dragActive || e.pointerId !== dragPointerId) return;
    const dx = e.clientX - dragLastX;
    const dy = e.clientY - dragLastY;
    dragDistance += Math.abs(dx) + Math.abs(dy);
    // Natural "grab and drag the scene" feel (like Street View or a photo
    // sphere), not FPS mouse-look -- the world follows your finger/cursor,
    // so dragging right/down should make the view pan as if you dragged the
    // image itself right/down (turn left/look up), not the opposite.
    lookYaw += dx * LOOK_SPEED;
    lookPitch += dy * LOOK_SPEED;
    lookPitch = Math.max(-1.3, Math.min(1.3, lookPitch));
    dragLastX = e.clientX;
    dragLastY = e.clientY;
  });

  const endDrag = (e) => {
    if (!dragActive || e.pointerId !== dragPointerId) return;
    dragActive = false;
    el.classList.remove('dragging');
    if (dragDistance < 8) {
      raycaster.setFromCamera(
        {
          x: (e.clientX / window.innerWidth) * 2 - 1,
          y: -(e.clientY / window.innerHeight) * 2 + 1,
        },
        camera
      );
      const hits = raycaster.intersectObjects(raycastTargets, false);
      if (hits.length) openInfoPanel(hits[0].object.userData);
    }
  };
  el.addEventListener('pointerup', endDrag);
  el.addEventListener('pointercancel', endDrag);
}

function isOverJoystick(e) {
  if (!IS_TOUCH) return false;
  const r = joystick.getBoundingClientRect();
  return e.clientX >= r.left && e.clientX <= r.right && e.clientY >= r.top && e.clientY <= r.bottom;
}

function setupTouchJoystick() {
  joystick.addEventListener('touchstart', (e) => {
    const t = e.changedTouches[0];
    moveTouchId = t.identifier;
    const r = joystick.getBoundingClientRect();
    moveCenterX = r.left + r.width / 2;
    moveCenterY = r.top + r.height / 2;
  }, { passive: true });

  joystick.addEventListener('touchmove', (e) => {
    for (const t of e.changedTouches) {
      if (t.identifier === moveTouchId) {
        const max = 40;
        let dx = t.clientX - moveCenterX;
        let dy = t.clientY - moveCenterY;
        const len = Math.hypot(dx, dy) || 1;
        const clamped = Math.min(len, max);
        dx = (dx / len) * clamped;
        dy = (dy / len) * clamped;
        joystickKnob.style.transform = 'translate(' + dx + 'px,' + dy + 'px)';
        moveVector = { x: dx / max, y: -dy / max };
      }
    }
  }, { passive: true });

  const reset = (e) => {
    for (const t of e.changedTouches) {
      if (t.identifier === moveTouchId) {
        moveTouchId = null;
        moveVector = { x: 0, y: 0 };
        joystickKnob.style.transform = 'translate(0,0)';
      }
    }
  };
  joystick.addEventListener('touchend', reset);
  joystick.addEventListener('touchcancel', reset);
}

// ---------------------------------------------------------------------------
// Info panel
// ---------------------------------------------------------------------------
function setupInfoPanel() {
  infoClose.addEventListener('click', closeInfoPanel);
  infoPanel.addEventListener('click', (e) => { if (e.target === infoPanel) closeInfoPanel(); });
  infoPrev.addEventListener('click', showPrevImage);
  infoNext.addEventListener('click', showNextImage);
  document.addEventListener('keydown', (e) => {
    if (!infoPanelOpen) return;
    if (e.code === 'Escape') closeInfoPanel();
    else if (e.code === 'ArrowLeft') showPrevImage();
    else if (e.code === 'ArrowRight') showNextImage();
  });
}

let currentImages = [];
let currentImageIndex = 0;

function openInfoPanel(data) {
  infoPanelOpen = true;
  infoTitle.textContent = data.title;
  const metaParts = [data.date, data.era, data.medium].filter(Boolean);
  infoMeta.textContent = metaParts.join(' · ');
  infoNotes.textContent = data.notes || '';
  currentImages = (data.images && data.images.length) ? data.images : [{ full: data.fullUrl, thumb: data.fullUrl, label: '' }];
  currentImageIndex = 0;
  updateInfoImage();
  infoPanel.classList.remove('hidden');
}

function updateInfoImage() {
  const image = currentImages[currentImageIndex];
  infoImage.src = (image && (image.full || image.thumb)) || '';
  infoImage.alt = infoTitle.textContent;
  const showNav = currentImages.length > 1;
  infoPrev.classList.toggle('hidden', !showNav);
  infoNext.classList.toggle('hidden', !showNav);
  infoCounter.classList.toggle('hidden', !showNav);
  if (showNav) {
    const parts = [`${currentImageIndex + 1} / ${currentImages.length}`];
    if (image.label) parts.push(image.label);
    infoCounter.textContent = parts.join(' · ');
  }
}

function showPrevImage() {
  if (currentImages.length < 2) return;
  currentImageIndex = (currentImageIndex - 1 + currentImages.length) % currentImages.length;
  updateInfoImage();
}

function showNextImage() {
  if (currentImages.length < 2) return;
  currentImageIndex = (currentImageIndex + 1) % currentImages.length;
  updateInfoImage();
}

function closeInfoPanel() {
  infoPanelOpen = false;
  infoPanel.classList.add('hidden');
}

// ---------------------------------------------------------------------------
// Render loop
// ---------------------------------------------------------------------------
function animate() {
  requestAnimationFrame(animate);
  const dt = Math.min(clock.getDelta(), 0.1);

  if (entered && !infoPanelOpen) {
    const turn = (keys.turnLeft ? 1 : 0) - (keys.turnRight ? 1 : 0);
    if (turn !== 0) lookYaw += turn * TURN_SPEED * dt;
    camera.rotation.set(lookPitch, lookYaw, 0, 'YXZ');

    let mx = (keys.strafeRight ? 1 : 0) - (keys.strafeLeft ? 1 : 0);
    let my = (keys.forward ? 1 : 0) - (keys.back ? 1 : 0);
    const keyLen = Math.hypot(mx, my);
    if (keyLen > 1) { mx /= keyLen; my /= keyLen; }
    if (moveVector.x !== 0 || moveVector.y !== 0) {
      // joystick overrides keys if both happen to be in use at once
      mx = moveVector.x;
      my = moveVector.y;
    }

    if (mx !== 0 || my !== 0) {
      const forward = { x: -Math.sin(lookYaw), z: -Math.cos(lookYaw) };
      const right = { x: Math.cos(lookYaw), z: -Math.sin(lookYaw) };
      const dist = WALK_SPEED * dt;
      camera.position.x += (forward.x * my + right.x * mx) * dist;
      camera.position.z += (forward.z * my + right.z * mx) * dist;
      clampPosition(camera.position);
    }
  }

  renderer.render(scene, camera);
}

function normalizeAngle(a) {
  while (a > Math.PI) a -= 2 * Math.PI;
  while (a < -Math.PI) a += 2 * Math.PI;
  return a;
}

// Keeps the camera inside whichever "room" it's currently in: a simple
// radial clamp inside the circular hub, or -- once past the hub's edge -- a
// clamp inside whichever corridor is angularly closest, done by rotating the
// camera's world position into that corridor's own local coordinate frame
// (the same frame buildCorridor() drew its walls in), clamping there exactly
// like a single straight hallway, then rotating back.
function clampPosition(pos) {
  pos.y = EYE_HEIGHT;
  const hubLimit = hubRadius - WALL_MARGIN;
  const r = Math.hypot(pos.x, pos.z);

  // Near (or past) the hub's edge, figure out whether this direction lines
  // up with a corridor doorway. Previously the radial clamp below always
  // pulled the camera back to hubLimit, which is strictly less than
  // hubRadius -- so r could never reach the corridor-clamp branch and every
  // doorway was silently blocked. Handing off to the corridor's own frame
  // as soon as we're heading through its doorway (rather than only once
  // r >= hubRadius) fixes that.
  if (corridors.length > 0 && r >= hubLimit) {
    const theta = Math.atan2(-pos.x, -pos.z);
    let best = corridors[0], bestDiff = Infinity;
    for (const c of corridors) {
      const diff = Math.abs(normalizeAngle(theta - c.angle));
      if (diff < bestDiff) { bestDiff = diff; best = c; }
    }
    const halfDoorway = (DOORWAY_ARC / 2) / hubRadius; // radians

    if (bestDiff <= halfDoorway) {
      const dx = pos.x - best.originX;
      const dz = pos.z - best.originZ;
      const cos = Math.cos(best.angle), sin = Math.sin(best.angle);
      let localX = dx * cos - dz * sin;
      let localZ = dx * sin + dz * cos;

      // Side walls and the far wall still block, same as before. The near
      // (hub-facing) side is deliberately left unclamped here so walking
      // through the doorway -- in either direction -- is never blocked.
      const xLimit = best.width / 2 - WALL_MARGIN;
      localX = Math.max(-xLimit, Math.min(xLimit, localX));
      localZ = Math.max(-(best.length - WALL_MARGIN), localZ);

      pos.x = localX * cos + localZ * sin + best.originX;
      pos.z = -localX * sin + localZ * cos + best.originZ;
      return;
    }
  }

  // Plain hub interior, or a stretch of the hub's round edge with no
  // doorway in this direction: simple radial clamp against the hub wall.
  if (r > hubLimit && r > 0) {
    const scale = hubLimit / r;
    pos.x *= scale;
    pos.z *= scale;
  }
}
