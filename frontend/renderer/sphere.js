// frontend/renderer/sphere.js
// ============================================================
// NEXON 3D Neural Sphere
// Three.js particle network that rotates slowly and reacts
// to speaking state (color shifts, speed changes).
// ============================================================

class NeuralSphere {
  /**
   * Initializes and animates the 3D neural sphere.
   * @param {string} canvasId - ID of the canvas element to render into.
   */
  constructor(canvasId) {
    this.canvas    = document.getElementById(canvasId);
    this.state     = 'idle';      // 'idle' | 'user' | 'assistant'
    this.animFrame = null;

    this._initThree();
    this._createParticles();
    this._createConnections();
    this._animate();

    // Resize handler
    window.addEventListener('resize', () => this._onResize());
    this._onResize();
  }

  /** Initialize Three.js scene, camera, renderer. */
  _initThree() {
    this.scene    = new THREE.Scene();
    this.camera   = new THREE.PerspectiveCamera(60, 1, 0.1, 1000);
    this.camera.position.z = 220;

    this.renderer = new THREE.WebGLRenderer({
      canvas           : this.canvas,
      alpha            : true,
      antialias        : true,
    });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.setClearColor(0x000000, 0);  // Transparent bg

    // Ambient light
    const ambientLight = new THREE.AmbientLight(0x00d4ff, 0.3);
    this.scene.add(ambientLight);

    // Point lights for glow effect
    this.pointLight1 = new THREE.PointLight(0x00d4ff, 1.5, 300);
    this.pointLight1.position.set(100, 100, 100);
    this.scene.add(this.pointLight1);

    this.pointLight2 = new THREE.PointLight(0x8a2be2, 1.0, 300);
    this.pointLight2.position.set(-100, -100, 50);
    this.scene.add(this.pointLight2);
  }

  /** Create ~250 particles arranged in a sphere. */
  _createParticles() {
    const COUNT    = 250;
    const RADIUS   = 100;
    const geometry = new THREE.BufferGeometry();
    const positions= new Float32Array(COUNT * 3);
    const colors   = new Float32Array(COUNT * 3);

    // Fibonacci sphere distribution for uniform spread
    const goldenAngle = Math.PI * (3 - Math.sqrt(5));

    for (let i = 0; i < COUNT; i++) {
      const y     = 1 - (i / (COUNT - 1)) * 2;  // -1 to 1
      const r     = Math.sqrt(1 - y * y);
      const theta = goldenAngle * i;
      const x     = Math.cos(theta) * r;
      const z     = Math.sin(theta) * r;

      positions[i * 3]     = x * RADIUS;
      positions[i * 3 + 1] = y * RADIUS;
      positions[i * 3 + 2] = z * RADIUS;

      // Color: gradient from cyan to purple based on position
      const t           = (y + 1) / 2;  // 0 to 1
      colors[i * 3]     = t * 0.0 + (1 - t) * 0.0;       // R
      colors[i * 3 + 1] = t * 0.83 + (1 - t) * 0.17;     // G
      colors[i * 3 + 2] = t * 1.0 + (1 - t) * 0.88;      // B
    }

    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    geometry.setAttribute('color',    new THREE.BufferAttribute(colors, 3));

    const material = new THREE.PointsMaterial({
      size          : 2.2,
      vertexColors  : true,
      transparent   : true,
      opacity       : 0.9,
      sizeAttenuation: true,
    });

    this.particles     = new THREE.Points(geometry, material);
    this.particleCount = COUNT;
    this.particlePositions = positions;
    this.scene.add(this.particles);
  }

  /** Draw connection lines between nearby particles. */
  _createConnections() {
    const MAX_DIST  = 40;
    const positions = this.particlePositions;
    const lineVerts = [];

    for (let i = 0; i < this.particleCount; i++) {
      for (let j = i + 1; j < this.particleCount; j++) {
        const dx = positions[i*3]   - positions[j*3];
        const dy = positions[i*3+1] - positions[j*3+1];
        const dz = positions[i*3+2] - positions[j*3+2];
        const dist = Math.sqrt(dx*dx + dy*dy + dz*dz);

        if (dist < MAX_DIST) {
          lineVerts.push(
            positions[i*3],   positions[i*3+1], positions[i*3+2],
            positions[j*3],   positions[j*3+1], positions[j*3+2]
          );
        }
      }
    }

    const lineGeo = new THREE.BufferGeometry();
    lineGeo.setAttribute(
      'position',
      new THREE.BufferAttribute(new Float32Array(lineVerts), 3)
    );

    const lineMat = new THREE.LineBasicMaterial({
      color      : 0x00d4ff,
      transparent: true,
      opacity    : 0.12,
    });

    this.connections = new THREE.LineSegments(lineGeo, lineMat);
    this.scene.add(this.connections);
  }

  /** Main animation loop. */
  _animate() {
    this.animFrame = requestAnimationFrame(() => this._animate());

    const t    = Date.now() * 0.001;
    const mode = this.state;

    // Rotation speed depends on state
    const speedY = mode === 'user'      ? 0.008
                 : mode === 'assistant' ? 0.012
                 : 0.003;
    const speedX = speedY * 0.4;

    this.particles.rotation.y    += speedY;
    this.particles.rotation.x    += speedX;
    this.connections.rotation.y  = this.particles.rotation.y;
    this.connections.rotation.x  = this.particles.rotation.x;

    // Color shift based on state
    if (mode === 'user') {
      // Cyan/blue — user speaking
      this.particles.material.color.setHex(0x00d4ff);
      this.connections.material.color.setHex(0x00d4ff);
      this.connections.material.opacity = 0.2 + Math.sin(t * 4) * 0.05;
    } else if (mode === 'assistant') {
      // Purple/pink — assistant speaking
      const r = 0.5 + Math.sin(t * 3) * 0.2;
      this.particles.material.color.setRGB(r, 0.17, 0.88);
      this.connections.material.color.setHex(0x8a2be2);
      this.connections.material.opacity = 0.2 + Math.sin(t * 6) * 0.08;
    } else {
      // Idle — slow gentle pulse
      this.connections.material.opacity = 0.08 + Math.sin(t * 0.8) * 0.04;
    }

    // Pulse particle size on voice activity
    if (mode !== 'idle') {
      this.particles.material.size = 2.2 + Math.sin(t * 8) * 0.5;
    } else {
      this.particles.material.size = 2.0 + Math.sin(t * 1.5) * 0.3;
    }

    // Orbit lights
    this.pointLight1.position.x = Math.sin(t * 0.5) * 120;
    this.pointLight1.position.y = Math.cos(t * 0.3) * 80;
    this.pointLight2.position.x = Math.cos(t * 0.4) * 100;
    this.pointLight2.position.z = Math.sin(t * 0.6) * 100;

    this.renderer.render(this.scene, this.camera);
  }

  /**
   * Set sphere state to change visual mode.
   * @param {'idle'|'user'|'assistant'} state
   */
  setState(state) {
    this.state = state;
  }

  /** Handle canvas resize to fill container. */
  _onResize() {
    const container = this.canvas.parentElement;
    if (!container) return;
    const w = container.clientWidth;
    const h = container.clientHeight;
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(w, h);
  }

  /** Destroy and clean up. */
  destroy() {
    if (this.animFrame) cancelAnimationFrame(this.animFrame);
    this.renderer.dispose();
  }
}

// Instantiate — available globally as window.sphere
window.nexonSphere = new NeuralSphere('sphere-canvas');