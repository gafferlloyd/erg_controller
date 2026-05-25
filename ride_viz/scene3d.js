import * as THREE from 'three';

const ROAD_HALF_W  = 5.0;   // metres — 10m total, two lanes
const LANE_HALF_W  = ROAD_HALF_W / 2;
const TREE_HEIGHT  = 8;
const HOUSE_HEIGHT = 6;

// Convert route local coords to Three.js world coords (Y-up)
function t3(lx, ly, lz) {
  return new THREE.Vector3(lx, lz, -ly);
}

export class Scene3D {
  constructor(container) {
    this._container = container;
    this._route     = null;
    this._wps       = null;   // cached waypoints array
    this._cameraMode = 'chase';
    this._dummy       = new THREE.Object3D();
    this._lateralOff  = LANE_HALF_W;        // 3/4 from left = 2.5m right of centre
    this._smoothCurve = 0;

    // Renderer — logarithmicDepthBuffer prevents z-fighting with large far/near ratio
    this._renderer = new THREE.WebGLRenderer({ antialias: true, logarithmicDepthBuffer: true });
    this._renderer.shadowMap.enabled = true;
    this._renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this._renderer.setPixelRatio(window.devicePixelRatio);
    container.appendChild(this._renderer.domElement);

    // Scene
    this._scene = new THREE.Scene();
    this._scene.background = new THREE.Color(0x87ceeb);
    this._scene.fog = new THREE.Fog(0x87ceeb, 2000, 16000);

    // Camera
    this._camera = new THREE.PerspectiveCamera(60, 1, 0.5, 20000);

    // Lights
    const ambient = new THREE.AmbientLight(0xffffff, 0.7);
    this._scene.add(ambient);
    const sun = new THREE.DirectionalLight(0xfff5e0, 1.2);
    sun.position.set(200, 400, -100);
    sun.castShadow = true;
    sun.shadow.mapSize.set(2048, 2048);
    sun.shadow.camera.near = 0.5;
    sun.shadow.camera.far  = 1500;
    sun.shadow.camera.left = sun.shadow.camera.bottom = -1500;
    sun.shadow.camera.right = sun.shadow.camera.top   =  1500;
    this._scene.add(sun);

    // Avatar group (built once, repositioned each frame)
    this._avatar = this._buildAvatar();
    this._scene.add(this._avatar);

    // Resize
    this._ro = new ResizeObserver(() => this._onResize());
    this._ro.observe(container);
    this._onResize();

    // Render loop
    this._renderer.setAnimationLoop(() => this._renderer.render(this._scene, this._camera));
  }

  _onResize() {
    const w = this._container.clientWidth;
    const h = this._container.clientHeight;
    if (!w || !h) return;
    this._renderer.setSize(w, h);
    this._camera.aspect = w / h;
    this._camera.updateProjectionMatrix();
  }

  toggleCamera() {
    this._cameraMode = this._cameraMode === 'chase' ? 'iso' : 'chase';
  }

  // Called once when a route JSON is loaded.
  // onPhase(name, fraction) is called before each build step (fraction = 0..1 within build).
  async load(route, onPhase) {
    if (this._routeGroup) {
      this._scene.remove(this._routeGroup);
      this._routeGroup.traverse(o => {
        if (o.geometry) o.geometry.dispose();
        if (o.material) o.material.dispose();
      });
    }
    this._roadMesh = null;
    this._roadEdgeMesh = null;
    this._vergeMesh = null;
    this._nRoadSegs = 0;

    this._route = route;
    this._wps   = route.waypoints;

    const group = new THREE.Group();
    this._routeGroup = group;

    const steps = [
      ['vista terrain', () => this._buildVistaTerrain(group, route.vista_terrain_grid, route.terrain_grid)],
      ['terrain',    () => this._buildTerrain(group, route.terrain_grid)],
      ['verge',      () => this._buildVerge(group, route.terrain_grid)],
      ['water',      () => this._buildWater(group, route.water)],
      ...(route.land_cover?.length
        ? [['land cover', () => this._buildLandCover(group, route.land_cover, route.terrain_grid)]]
        : []),
      ...(route.rivers?.length
        ? [['rivers', () => this._buildRivers(group, route.rivers, route.terrain_grid)]]
        : []),
      ['road',       () => this._buildRoad(group)],
      ...(route.junctions?.length
        ? [['junctions',  () => this._buildJunctions(group, route.junctions)]]
        : []),
      ['scenery',    () => this._buildScenery(group, route.scenery, route.terrain_grid)],
    ];

    for (let i = 0; i < steps.length; i++) {
      const [name, fn] = steps[i];
      onPhase?.(name, i / steps.length);
      await new Promise(r => setTimeout(r, 0));
      fn();
    }

    this._scene.add(group);
    this._updateRoadWindow(0);
    this._moveCamera(0);
  }

  // Called every frame by player.js
  update(state) {
    if (!this._route) return;
    const i = this._wpIndex(state.dist_m);
    const curve = this._wps[i].curve_dpm ?? 0;
    this._smoothCurve += (curve - this._smoothCurve) * 0.05;
    const norm = Math.max(-1, Math.min(1, this._smoothCurve / 3.0));
    this._lateralOff = LANE_HALF_W - norm * LANE_HALF_W * 0.9;
    // Crank angle from distance: ~6.5m per revolution (typical road gearing)
    this._animLegs((state.dist_m / 6.5) * Math.PI * 2);
    this._moveAvatar(state.dist_m);
    this._moveCamera(state.dist_m);
    this._updateRoadWindow(state.dist_m);
  }

  // ---------------------------------------------------------------------------
  // Geometry builders
  // ---------------------------------------------------------------------------

  _terrainHeight(lx, ly, tg) {
    if (!tg) return 0;
    const ix = (lx - tg.origin_x) / (tg.step_x_m ?? tg.step_m);
    const iy = (ly - tg.origin_y) / (tg.step_y_m ?? tg.step_m);
    const ix0 = Math.max(0, Math.min(tg.nx - 2, Math.floor(ix)));
    const iy0 = Math.max(0, Math.min(tg.ny - 2, Math.floor(iy)));
    const tx = ix - ix0, ty = iy - iy0;
    const h = tg.heights;
    return h[iy0*tg.nx+ix0]*(1-tx)*(1-ty) + h[iy0*tg.nx+ix0+1]*tx*(1-ty)
         + h[(iy0+1)*tg.nx+ix0]*(1-tx)*ty  + h[(iy0+1)*tg.nx+ix0+1]*tx*ty;
  }

  _buildLandCover(group, landCover, terrainGrid) {
    const COVER_COLOR = {
      forest: 0x3a2010, meadow: 0x7db34a, farmland: 0xc4a45a,
      residential: 0xccbbaa, orchard: 0x4a7a2a, vineyard: 0x7a5a20,
      heath: 0x8a8a4a, water: 0x1a9988,
    };

    // Spatial hash of waypoints — built once and reused for polygon filtering AND tree clamping.
    const wps = this._wps || [];
    const clampR2 = terrainGrid ? terrainGrid.step_m * terrainGrid.step_m : 0;
    const WP_CELL = clampR2 > 0 ? Math.sqrt(clampR2) : 100;
    const wpHash = new Map();
    for (const wp of wps) {
      const kx = Math.floor(wp.local_x / WP_CELL);
      const ky = Math.floor(wp.local_y / WP_CELL);
      const key = kx * 200003 + ky;
      if (!wpHash.has(key)) wpHash.set(key, []);
      wpHash.get(key).push(wp);
    }
    const nearestWpClamp = (lx, ly) => {
      const cx = Math.floor(lx / WP_CELL), cy = Math.floor(ly / WP_CELL);
      let minD2 = Infinity, nearZ = 0;
      for (let dx = -1; dx <= 1; dx++) {
        for (let dy = -1; dy <= 1; dy++) {
          const cell = wpHash.get((cx + dx) * 200003 + (cy + dy));
          if (!cell) continue;
          for (const wp of cell) {
            const d2 = (wp.local_x - lx) ** 2 + (wp.local_y - ly) ** 2;
            if (d2 < minD2) { minD2 = d2; nearZ = wp.local_z; }
          }
        }
      }
      return { minD2, nearZ };
    };

    // Batch polygon vertices by type → one draw call per land cover type
    const byType = {};
    const byTypeColors = {};  // vertex colour arrays for types that need them (water)
    const CENTROID_SKIP_R2 = (ROAD_HALF_W + 13) ** 2;  // matches compile-time _ROAD_MASK_M=13
    const MID_SKIP_R2 = (ROAD_HALF_W + 3) ** 2;
    const FAN_CLEAR_R2 = (ROAD_HALF_W + 2) ** 2;  // fan edge must clear this from any road wp
    const segDist2 = (ax, ay, bx, by, px, py) => {
      const dx = bx - ax, dy = by - ay, len2 = dx * dx + dy * dy;
      if (len2 === 0) return (px - ax) ** 2 + (py - ay) ** 2;
      const t = Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / len2));
      return (px - (ax + t * dx)) ** 2 + (py - (ay + t * dy)) ** 2;
    };
    for (const lc of landCover) {
      const pts = lc.points;
      if (!pts || pts.length < 3) continue;
      // Use the vertex farthest from the road as fan origin — guarantees fan centre is off-road.
      let cx = 0, cy = 0, bestD2 = -1;
      let crossesRoad = false;
      for (let k = 0; k < pts.length; k++) {
        const p = pts[k];
        const { minD2 } = nearestWpClamp(p.lx, p.ly);
        if (minD2 > bestD2) { bestD2 = minD2; cx = p.lx; cy = p.ly; }
        // Edge midpoint check — catches thin strips whose vertices straddle the road
        const q = pts[(k + 1) % pts.length];
        const { minD2: mD2 } = nearestWpClamp((p.lx + q.lx) / 2, (p.ly + q.ly) / 2);
        if (mD2 < MID_SKIP_R2) crossesRoad = true;
      }
      if (bestD2 < CENTROID_SKIP_R2 || crossesRoad) continue;
      // Filter vertices whose fan edge (centre → vertex) passes within FAN_CLEAR_R2 of road
      const clearR = Math.sqrt(FAN_CLEAR_R2) + 1;
      const filteredPts = pts.filter(p => {
        const minX = Math.min(cx, p.lx) - clearR, maxX = Math.max(cx, p.lx) + clearR;
        const minY = Math.min(cy, p.ly) - clearR, maxY = Math.max(cy, p.ly) + clearR;
        const gx0 = Math.floor(minX / WP_CELL), gx1 = Math.floor(maxX / WP_CELL);
        const gy0 = Math.floor(minY / WP_CELL), gy1 = Math.floor(maxY / WP_CELL);
        for (let gx = gx0; gx <= gx1; gx++)
          for (let gy = gy0; gy <= gy1; gy++) {
            const cell = wpHash.get(gx * 200003 + gy);
            if (!cell) continue;
            for (const wp of cell)
              if (segDist2(cx, cy, p.lx, p.ly, wp.local_x, wp.local_y) < FAN_CLEAR_R2) return false;
          }
        return true;
      });
      if (filteredPts.length < 3) continue;
      if (!byType[lc.type]) byType[lc.type] = { verts: [], indices: [] };
      const { verts, indices } = byType[lc.type];
      const base = verts.length / 3;
      const clz = this._terrainHeight(cx, cy, terrainGrid) + 0.12;
      verts.push(cx, clz, -cy);   // vertex 0 = fan centre
      for (const p of filteredPts) {
        const lz = this._terrainHeight(p.lx, p.ly, terrainGrid) + 0.12;
        verts.push(p.lx, lz, -p.ly);
      }
      for (let i = 1; i <= filteredPts.length; i++) {
        indices.push(base, base + i, base + (i < filteredPts.length ? i + 1 : 1));
      }
      if (lc.type === 'water') {
        if (!byTypeColors['water']) byTypeColors['water'] = [];
        const cols = byTypeColors['water'];
        cols.push(0.10, 0.60, 0.53);  // fan centre — base turquoise
        for (let k = 0; k < filteredPts.length; k++) {
          if (Math.random() < 0.15) {
            cols.push(0.53, 0.87, 0.87);  // ripple: pale cyan
          } else {
            cols.push(0.10, 0.60, 0.53);  // base turquoise
          }
        }
      }
    }
    for (const [type, { verts, indices }] of Object.entries(byType)) {
      const geo = new THREE.BufferGeometry();
      geo.setAttribute('position', new THREE.Float32BufferAttribute(verts, 3));
      geo.setIndex(indices);
      geo.computeVertexNormals();
      const mat = new THREE.MeshLambertMaterial({
        color: COVER_COLOR[type] ?? 0x888888,
        side: THREE.DoubleSide,
      });
      if (type === 'water' && byTypeColors['water']) {
        geo.setAttribute('color', new THREE.Float32BufferAttribute(byTypeColors['water'], 3));
        mat.vertexColors = true;
      }
      group.add(new THREE.Mesh(geo, mat));
    }

    // 4 tree species — canopy + trunk InstancedMesh per variant
    // Canopy geometries: base at y=0, apex/centre translated up
    const treeVariantDefs = [
      { geo: (() => { const g = new THREE.ConeGeometry(3.8, 20.0, 7); g.translate(0, 10.5, 0); return g; })(), color: 0x1a5e0a },  // spruce — 20 m cone, base at 0.5 m
      { geo: (() => { const g = new THREE.ConeGeometry(3.5, 15.0, 7); g.translate(0, 12.5, 0); return g; })(), color: 0x227722 }, // pine — 15 m cone, base at 5 m
      { geo: (() => { const g = new THREE.SphereGeometry(7.0, 8, 6);  g.translate(0, 13.0, 0); return g; })(), color: 0x4a9a18 }, // broadleaf — r=7, centre 13 m
      { geo: (() => { const g = new THREE.SphereGeometry(4.5, 7, 5);  g.translate(0, 11.0, 0); return g; })(), color: 0x88cc44 },  // birch — r=4.5, centre 11 m
    ];
    const trunkDefs = [
      { geo: (() => { const g = new THREE.CylinderGeometry(0.25, 0.40, 2.5, 6); g.translate(0, 1.25, 0); return g; })(), color: 0x5a3010 },
      { geo: (() => { const g = new THREE.CylinderGeometry(0.30, 0.50, 5.5, 6); g.translate(0, 2.75, 0); return g; })(), color: 0x5a3010 },
      { geo: (() => { const g = new THREE.CylinderGeometry(0.50, 0.70, 5.0, 6); g.translate(0, 2.50, 0); return g; })(), color: 0x6b3c11 },
      { geo: (() => { const g = new THREE.CylinderGeometry(0.12, 0.20, 6.0, 6); g.translate(0, 3.00, 0); return g; })(), color: 0xb0a090 },
    ];
    const treesByVariant = [[], [], [], []];
    for (const lc of landCover) {
      if (lc.type === 'forest') for (const t of (lc.interior || [])) treesByVariant[t.v ?? 0].push(t);
    }
    let totalTrees = 0;
    for (let v = 0; v < 4; v++) {
      const trees = treesByVariant[v];
      if (!trees.length) continue;
      const canopy = new THREE.InstancedMesh(treeVariantDefs[v].geo,
          new THREE.MeshLambertMaterial({ color: treeVariantDefs[v].color, flatShading: true }), trees.length);
      canopy.castShadow = true;
      const trunk = new THREE.InstancedMesh(trunkDefs[v].geo,
          new THREE.MeshLambertMaterial({ color: trunkDefs[v].color, flatShading: true }), trees.length);
      trees.forEach((t, i) => {
        let treeY = t.lz;
        if (clampR2 > 0) {
          const { minD2, nearZ } = nearestWpClamp(t.lx, t.ly);
          if (minD2 < clampR2 && treeY > nearZ) treeY = nearZ;
        }
        const scale = 1.0 + ((Math.sin(t.lx * 7.3 + t.ly * 11.7) + 1) * 0.5) * 0.55;
        this._dummy.position.set(t.lx, treeY, -t.ly);
        this._dummy.rotation.y = (t.lx * 11.3 + t.ly * 5.7) % (Math.PI * 2);
        this._dummy.scale.set(1, scale, 1);
        this._dummy.updateMatrix();
        canopy.setMatrixAt(i, this._dummy.matrix);
        trunk.setMatrixAt(i, this._dummy.matrix);
      });
      group.add(canopy, trunk);
      totalTrees += trees.length;
    }

    // 4 crop types — one InstancedMesh per variant
    const cropVariantDefs = [
      { geo: (() => { const g = new THREE.CylinderGeometry(0.4, 0.5, 0.8, 5); g.translate(0, 0.4, 0);  return g; })(), color: 0xd4b84a },  // wheat
      { geo: (() => { const g = new THREE.CylinderGeometry(0.5, 0.6, 2.5, 5); g.translate(0, 1.25, 0); return g; })(), color: 0x44aa22 },  // corn
      { geo: (() => { const g = new THREE.SphereGeometry(0.5, 5, 4);           g.translate(0, 1.8, 0);  return g; })(), color: 0xf0c020 },  // sunflower
      { geo: (() => { const g = new THREE.CylinderGeometry(1.0, 1.2, 0.3, 5); g.translate(0, 0.15, 0); return g; })(), color: 0x99cc66 },  // grass
    ];
    const cropsByVariant = [[], [], [], []];
    for (const lc of landCover) {
      if (lc.type === 'farmland') for (const c of (lc.interior || [])) cropsByVariant[c.v ?? 0].push(c);
    }
    let totalCrops = 0;
    for (let v = 0; v < 4; v++) {
      const crops = cropsByVariant[v];
      if (!crops.length) continue;
      const { geo, color } = cropVariantDefs[v];
      const mesh = new THREE.InstancedMesh(geo, new THREE.MeshLambertMaterial({ color, flatShading: true }), crops.length);
      crops.forEach((c, i) => {
        this._dummy.position.set(c.lx, c.lz, -c.ly);
        this._dummy.rotation.y = (c.lx * 9.1 + c.ly * 4.3) % (Math.PI * 2);
        this._dummy.updateMatrix();
        mesh.setMatrixAt(i, this._dummy.matrix);
      });
      group.add(mesh);
      totalCrops += crops.length;
    }

    console.log(`Land cover: ${landCover.length} polygons, ${totalTrees} trees (4 species), ${totalCrops} crops (4 types)`);
  }

  _buildVerge(group, tg) {
    if (!tg || !this._wps) return;
    const VERGE_W = 14.0;
    const wps = this._wps;
    const verts = [], indices = [];

    // Loop order: i outer, side inner — 12 indices per segment → setDrawRange(12*iA, 12*cnt)
    for (let i = 0; i < wps.length - 1; i++) {
      const p  = t3(wps[i].local_x,   wps[i].local_y,   wps[i].local_z);
      const pn = t3(wps[i+1].local_x, wps[i+1].local_y, wps[i+1].local_z);
      const dx = pn.x - p.x, dz = pn.z - p.z;
      const len = Math.sqrt(dx*dx + dz*dz) || 1;
      const px = -dz/len, pz = dx/len;

      for (const side of [-1, 1]) {
        const ro = side * ROAD_HALF_W;
        const vo = side * (ROAD_HALF_W + VERGE_W);

        const ix0 = p.x  + px*ro, iz0 = p.z  + pz*ro, iy0 = wps[i].local_z   + 0.05;
        const ix1 = pn.x + px*ro, iz1 = pn.z + pz*ro, iy1 = wps[i+1].local_z + 0.05;
        const ox0 = p.x  + px*vo, oz0 = p.z  + pz*vo;
        const ox1 = pn.x + px*vo, oz1 = pn.z + pz*vo;
        // Cap outer verge edge at road level — the terrain mesh within 100 m of
        // any waypoint is clamped to road elevation, so a verge rising above road
        // level would protrude through the rendered terrain mesh beside it.
        const oy0 = Math.min(this._terrainHeight(ox0, -oz0, tg), iy0);
        const oy1 = Math.min(this._terrainHeight(ox1, -oz1, tg), iy1);

        const base = verts.length / 3;
        verts.push(ix0, iy0, iz0,  ox0, oy0, oz0,  ix1, iy1, iz1,  ox1, oy1, oz1);
        indices.push(base, base+1, base+2,  base+1, base+3, base+2);
      }
    }
    if (!verts.length) return;
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.Float32BufferAttribute(verts, 3));
    geo.setIndex(indices);
    geo.computeVertexNormals();
    const mesh = new THREE.Mesh(geo, new THREE.MeshLambertMaterial({ color: 0x5a8a2a, side: THREE.DoubleSide }));
    this._vergeMesh = mesh;
    group.add(mesh);
  }

  _buildWater(group, water) {
    if (!water || !water.length) return;
    const mat = new THREE.MeshLambertMaterial({ color: 0x4488cc, transparent: true, opacity: 0.85 });
    for (const body of water) {
      const pts = body.points;
      if (!pts || pts.length < 3) continue;
      // Centroid for fan triangulation (works for convex / near-convex lakes)
      const cx = pts.reduce((s, p) => s + p.lx, 0) / pts.length;
      const cy = pts.reduce((s, p) => s + p.ly, 0) / pts.length;
      const verts = [cx, -0.05, -cy];
      for (const p of pts) verts.push(p.lx, -0.05, -p.ly);
      const indices = [];
      for (let i = 1; i <= pts.length; i++) {
        indices.push(0, i, i < pts.length ? i + 1 : 1);
      }
      const geo = new THREE.BufferGeometry();
      geo.setAttribute('position', new THREE.Float32BufferAttribute(verts, 3));
      geo.setIndex(indices);
      geo.computeVertexNormals();
      group.add(new THREE.Mesh(geo, mat));
    }
  }

  _buildRivers(group, rivers, tg) {
    if (!rivers || !rivers.length) return;
    const RIVER_HALF_W = 2.0;
    const mat = new THREE.MeshLambertMaterial({ color: 0x4488cc, transparent: true, opacity: 0.82,
      polygonOffset: true, polygonOffsetFactor: -1, polygonOffsetUnits: -2 });
    for (const river of rivers) {
      const pts = river.points;
      if (!pts || pts.length < 2) continue;
      const verts = [];
      const indices = [];
      let vi = 0;
      for (let i = 0; i < pts.length - 1; i++) {
        const ax = pts[i].lx,   ay = pts[i].ly;
        const bx = pts[i+1].lx, by = pts[i+1].ly;
        // Three.js coords: x=lx, z=-ly
        const dx = bx - ax, dz = -(by - ay);
        const len = Math.sqrt(dx*dx + dz*dz) || 1;
        const px = -dz / len * RIVER_HALF_W;
        const pz =  dx / len * RIVER_HALF_W;
        const ya = this._terrainHeight(ax, ay, tg) + 0.15;
        const yb = this._terrainHeight(bx, by, tg) + 0.15;
        verts.push(ax - px, ya, -ay - pz);
        verts.push(ax + px, ya, -ay + pz);
        verts.push(bx - px, yb, -by - pz);
        verts.push(bx + px, yb, -by + pz);
        indices.push(vi, vi+1, vi+2,  vi+1, vi+3, vi+2);
        vi += 4;
      }
      const geo = new THREE.BufferGeometry();
      geo.setAttribute('position', new THREE.Float32BufferAttribute(verts, 3));
      geo.setIndex(indices);
      geo.computeVertexNormals();
      group.add(new THREE.Mesh(geo, mat));
    }
  }

  // Build a MeshLambertMaterial that colours terrain by elevation + slope in the
  // fragment shader.  This avoids any vertex-colour buffer issues and works
  // correctly with logarithmicDepthBuffer.
  // Elevation bands are anchored to a latitude-derived treeline so the palette
  // adapts automatically (lower treeline in Bavaria than in the high Alps).
  _makeTerrainMaterial() {
    const base_ele   = this._route?.base_ele   ?? 0;
    const origin_lat = this._route?.origin_lat ?? 47;
    const TL = 4550 - 60 * origin_lat;   // treeline m ASL (~1730 at 47°N, ~1790 at 46°N)

    const mat = new THREE.MeshLambertMaterial();
    mat.onBeforeCompile = shader => {
      shader.uniforms.uBaseEle = { value: base_ele };
      shader.uniforms.uTL      = { value: TL };

      // Pass vertex Y (= local_z = elevation above route start) and a slope
      // proxy (1 − |objectNormal.y|; 0=flat, 1=vertical) to the fragment shader.
      shader.vertexShader = shader.vertexShader
        .replace('#include <common>', `
          #include <common>
          varying float vTerrainEle;
          varying float vTerrainSlope;
        `)
        .replace('#include <begin_vertex>', `
          #include <begin_vertex>
          vTerrainEle   = position.y;
          vTerrainSlope = 1.0 - abs(normal.y);
        `);

      shader.fragmentShader = shader.fragmentShader
        .replace('#include <common>', `
          #include <common>
          uniform float uBaseEle;
          uniform float uTL;
          varying float vTerrainEle;
          varying float vTerrainSlope;

          vec3 terrainDiffuse(float ele, float sl) {
            vec3 F = vec3(0.20, 0.40, 0.13);
            vec3 M = vec3(0.45, 0.60, 0.27);
            vec3 R = vec3(0.55, 0.52, 0.46);
            vec3 S = vec3(0.90, 0.91, 0.94);
            if (ele >= uTL + 1250.0) return S;
            if (ele >= uTL +  750.0) return mix(R, S, clamp((ele-(uTL+750.0))/500.0, 0.0, 1.0));
            if (ele >= uTL +  250.0) return R;
            if (ele >= uTL) {
              float t = max(clamp((ele-uTL)/250.0,0.0,1.0), clamp(sl/0.5,0.0,1.0));
              return mix(M, R, t);
            }
            if (ele >= uTL - 400.0) {
              vec3 base = mix(F, M, clamp((ele-(uTL-400.0))/400.0, 0.0, 1.0));
              return mix(base, R, clamp(sl/0.8, 0.0, 1.0) * 0.5);
            }
            return F;
          }
        `)
        // #include <color_fragment> is Three.js's vertex-colour hook; we tint
        // the diffuse colour here so it combines correctly with Lambert lighting.
        .replace('#include <color_fragment>', `
          #include <color_fragment>
          diffuseColor.rgb *= terrainDiffuse(vTerrainEle + uBaseEle, vTerrainSlope);
        `);
    };
    mat.customProgramCacheKey = () => `terrain_${base_ele}_${TL}`;
    return mat;
  }

  _buildVistaTerrain(group, tg, nearTg) {
    if (!tg) return;
    const { nx, ny, origin_x, origin_y } = tg;
    const sx = tg.step_x_m ?? tg.step_m;
    const sy = tg.step_y_m ?? tg.step_m;
    const h  = tg.heights;

    // Near-terrain extent — skip wide cells that overlap it (no z-fighting at boundary)
    const nsx   = nearTg ? (nearTg.step_x_m ?? nearTg.step_m) : 0;
    const nsy   = nearTg ? (nearTg.step_y_m ?? nearTg.step_m) : 0;
    const nearX0 = nearTg ? nearTg.origin_x                          - nsx : -Infinity;
    const nearX1 = nearTg ? nearTg.origin_x + (nearTg.nx - 1) * nsx + nsx :  Infinity;
    const nearY0 = nearTg ? nearTg.origin_y                          - nsy : -Infinity;
    const nearY1 = nearTg ? nearTg.origin_y + (nearTg.ny - 1) * nsy + nsy :  Infinity;

    const verts = new Float32Array(nx * ny * 3);
    for (let iy = 0; iy < ny; iy++) {
      for (let ix = 0; ix < nx; ix++) {
        const i3 = (iy * nx + ix) * 3;
        verts[i3]   = origin_x + ix * sx;
        verts[i3+1] = h[iy * nx + ix];
        verts[i3+2] = -(origin_y + iy * sy);
      }
    }
    const indices = [];
    for (let iy = 0; iy < ny - 1; iy++) {
      for (let ix = 0; ix < nx - 1; ix++) {
        const cx = origin_x + (ix + 0.5) * sx;
        const cy = origin_y + (iy + 0.5) * sy;
        if (cx >= nearX0 && cx <= nearX1 && cy >= nearY0 && cy <= nearY1) continue;
        const a = iy * nx + ix;
        indices.push(a, a+1, a+nx,  a+1, a+nx+1, a+nx);
      }
    }
    if (!indices.length) return;
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.Float32BufferAttribute(verts, 3));
    geo.setIndex(indices);
    geo.computeVertexNormals();
    group.add(new THREE.Mesh(geo, this._makeTerrainMaterial()));
  }

  _buildTerrain(group, terrainGrid) {
    const mat = this._makeTerrainMaterial();
    if (!terrainGrid) {
      const geo = new THREE.PlaneGeometry(5000, 5000);
      geo.rotateX(-Math.PI / 2);
      const mesh = new THREE.Mesh(geo, mat);
      mesh.receiveShadow = true;
      group.add(mesh);
      return;
    }

    const { nx, ny, origin_x, origin_y, step_m, heights } = terrainGrid;
    const sx = terrainGrid.step_x_m ?? step_m;
    const sy = terrainGrid.step_y_m ?? step_m;
    const wps = this._wps || [];

    // For each terrain vertex within one grid step of the road, clamp its height
    // to the nearest waypoint's road elevation.  This prevents the terrain mesh
    // from poking through the road ribbon on hillsides and in valley cuttings.
    // _buildVerge reads from the JSON grid (not these clamped values), so the
    // verge outer edge still uses raw EUDEM and correctly shows the slope.
    const clampR2 = (ROAD_HALF_W + 4) ** 2;  // ~81m² — only clamp vertices physically under the road ribbon
    const h = heights.slice();

    // Scrub DEM no-data sentinels (Copernicus uses -9999; also catches null→0 anomalies).
    // First pass: mark bad cells; second pass: fill from 3×3 neighbourhood average.
    const BAD_THRESH = -500;
    const bad = new Uint8Array(h.length);
    for (let i = 0; i < h.length; i++) {
      if (h[i] === null || h[i] !== h[i] /* NaN */ || h[i] < BAD_THRESH) bad[i] = 1;
    }
    for (let iy = 0; iy < ny; iy++) {
      for (let ix = 0; ix < nx; ix++) {
        const i = iy * nx + ix;
        if (!bad[i]) continue;
        let sum = 0, cnt = 0;
        for (let dy = -1; dy <= 1; dy++) {
          for (let dx = -1; dx <= 1; dx++) {
            const j = (iy + dy) * nx + (ix + dx);
            if (j >= 0 && j < h.length && !bad[j]) { sum += heights[j]; cnt++; }
          }
        }
        h[i] = cnt > 0 ? sum / cnt : 0;
      }
    }

    for (let iy = 0; iy < ny; iy++) {
      for (let ix = 0; ix < nx; ix++) {
        const lx = origin_x + ix * sx;
        const ly = origin_y + iy * sy;
        // Collect minimum road elevation among ALL waypoints within clampR2.
        // Using minimum rather than nearest-single handles out-and-back routes where
        // GPS elevation drift on the return leg can produce an erroneously high local_z,
        // which would otherwise raise terrain above the true road level.
        let minZ = Infinity;
        for (const wp of wps) {
          const d2 = (wp.local_x - lx) ** 2 + (wp.local_y - ly) ** 2;
          if (d2 < clampR2 && wp.local_z < minZ) minZ = wp.local_z;
        }
        if (minZ < Infinity && h[iy * nx + ix] > minZ) {
          h[iy * nx + ix] = minZ;
        }
      }
    }
    // Sync the JSON object so _terrainHeight() lookups (houses, trees, land cover)
    // return the same heights that the terrain mesh actually renders.
    terrainGrid.heights = h;

    const verts = new Float32Array(nx * ny * 3);
    for (let iy = 0; iy < ny; iy++) {
      for (let ix = 0; ix < nx; ix++) {
        const i = iy * nx + ix;
        verts[i*3]   = origin_x + ix * sx;     // world X = local_x
        verts[i*3+1] = h[i];                   // world Y = local_z (elevation)
        verts[i*3+2] = -(origin_y + iy * sy); // world Z = -local_y
      }
    }
    const indices = [];
    for (let iy = 0; iy < ny - 1; iy++) {
      for (let ix = 0; ix < nx - 1; ix++) {
        const a = iy*nx+ix, b = a+1, c = (iy+1)*nx+ix, d = c+1;
        indices.push(a, b, c,  b, d, c);
      }
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.Float32BufferAttribute(verts, 3));
    geo.setIndex(indices);
    geo.computeVertexNormals();
    const mesh = new THREE.Mesh(geo, mat);
    mesh.receiveShadow = true;
    group.add(mesh);

    // Fallback plane — 1 m below the minimum terrain height so it is always
    // hidden under the terrain mesh and never causes z-fighting.
    // Use a loop instead of Math.min(...h) to avoid call-stack overflow on
    // large terrain arrays (46k+ elements exceed some JS engine arg limits).
    let minH = Infinity;
    for (let i = 0; i < h.length; i++) if (h[i] < minH) minH = h[i];
    const flatY = minH - 1.0;
    const extGeo = new THREE.PlaneGeometry(30000, 30000);
    extGeo.rotateX(-Math.PI / 2);
    extGeo.translate(
      origin_x + (nx - 1) * sx / 2,
      flatY,
      -(origin_y + (ny - 1) * sy / 2)
    );
    const extMesh = new THREE.Mesh(extGeo, mat);
    extMesh.receiveShadow = true;
    group.add(extMesh);

    // Perimeter skirt — quad strips connecting each edge vertex down to flatY.
    // Fills the visible cliff-face gap between the terrain grid boundary and the
    // flat plane when looking sideways near the grid edge.
    const skirtVerts = [];
    const skirtIdx   = [];
    let sv = 0;
    const skirtQuad = (x0, y0, z0, x1, y1, z1) => {
      skirtVerts.push(x0, y0, z0,  x0, flatY, z0,  x1, y1, z1,  x1, flatY, z1);
      skirtIdx.push(sv, sv+1, sv+2,  sv+1, sv+3, sv+2);
      sv += 4;
    };
    // South edge (iy=0) west→east
    for (let ix = 0; ix < nx - 1; ix++) {
      skirtQuad(origin_x + ix*sx,       h[ix],       -(origin_y),
                origin_x + (ix+1)*sx,   h[ix+1],     -(origin_y));
    }
    // North edge (iy=ny-1) east→west (outward-facing normals)
    for (let ix = 0; ix < nx - 1; ix++) {
      const base = (ny-1)*nx;
      skirtQuad(origin_x + (ix+1)*sx,   h[base+ix+1], -(origin_y+(ny-1)*sy),
                origin_x + ix*sx,        h[base+ix],   -(origin_y+(ny-1)*sy));
    }
    // West edge (ix=0) north→south (outward-facing)
    for (let iy = 0; iy < ny - 1; iy++) {
      skirtQuad(origin_x, h[(iy+1)*nx], -(origin_y+(iy+1)*sy),
                origin_x, h[iy*nx],     -(origin_y+iy*sy));
    }
    // East edge (ix=nx-1) south→north (outward-facing)
    for (let iy = 0; iy < ny - 1; iy++) {
      skirtQuad(origin_x+(nx-1)*sx, h[iy*nx+(nx-1)],     -(origin_y+iy*sy),
                origin_x+(nx-1)*sx, h[(iy+1)*nx+(nx-1)], -(origin_y+(iy+1)*sy));
    }
    const skirtGeo = new THREE.BufferGeometry();
    skirtGeo.setAttribute('position', new THREE.Float32BufferAttribute(skirtVerts, 3));
    skirtGeo.setIndex(skirtIdx);
    skirtGeo.computeVertexNormals();
    group.add(new THREE.Mesh(skirtGeo, mat));
  }

  _buildRoad(group) {
    const wps = this._wps;
    const n   = wps.length;

    // Each segment = 1 quad = 2 triangles = 6 indices, 4 verts
    const verts   = new Float32Array(n * 4 * 3);
    const indices = [];
    const normals = new Float32Array(n * 4 * 3);

    let vi = 0;
    for (let i = 0; i < n - 1; i++) {
      const p  = t3(wps[i].local_x,     wps[i].local_y,     wps[i].local_z);
      const nx = t3(wps[i+1].local_x,   wps[i+1].local_y,   wps[i+1].local_z);

      // Direction and perpendicular in XZ plane
      const dx = nx.x - p.x, dz = nx.z - p.z;
      const len = Math.sqrt(dx*dx + dz*dz) || 1;
      const px = -dz / len * ROAD_HALF_W;
      const pz =  dx / len * ROAD_HALF_W;

      const base = vi * 3;
      // left-p
      verts[base]     = p.x - px;  verts[base+1] = p.y + 0.20;  verts[base+2] = p.z - pz;
      // right-p
      verts[base+3]   = p.x + px;  verts[base+4] = p.y + 0.20;  verts[base+5] = p.z + pz;
      // left-n
      verts[base+6]   = nx.x - px; verts[base+7] = nx.y + 0.20; verts[base+8] = nx.z - pz;
      // right-n
      verts[base+9]   = nx.x + px; verts[base+10]= nx.y + 0.20; verts[base+11]= nx.z + pz;

      // Upward normals
      for (let k = 0; k < 4; k++) {
        normals[(vi+k)*3]   = 0;
        normals[(vi+k)*3+1] = 1;
        normals[(vi+k)*3+2] = 0;
      }

      // Two triangles
      indices.push(vi, vi+1, vi+2,  vi+1, vi+3, vi+2);
      vi += 4;
    }

    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(verts.slice(0, vi*3), 3));
    geo.setAttribute('normal',   new THREE.BufferAttribute(normals.slice(0, vi*3), 3));
    geo.setIndex(indices);

    const mat  = new THREE.MeshLambertMaterial({ color: 0x777777, polygonOffset: true, polygonOffsetFactor: -1, polygonOffsetUnits: -4 });
    const mesh = new THREE.Mesh(geo, mat);
    mesh.receiveShadow = true;
    this._roadMesh   = mesh;
    this._nRoadSegs  = n - 1;
    group.add(mesh);

    // White edge lines
    this._buildRoadEdges(group, wps);
  }

  _buildRoadEdges(group, wps) {
    const EDGE_W = 0.25;
    const EDGE_OFFSET = ROAD_HALF_W - EDGE_W;
    const positions = [];

    // Loop order: i outer, side inner — 12 verts per segment → setDrawRange(12*iA, 12*cnt)
    for (let i = 0; i < wps.length - 1; i++) {
      const p  = t3(wps[i].local_x,   wps[i].local_y,   wps[i].local_z);
      const nx = t3(wps[i+1].local_x, wps[i+1].local_y, wps[i+1].local_z);
      const dx = nx.x - p.x, dz = nx.z - p.z;
      const len = Math.sqrt(dx*dx+dz*dz) || 1;
      const px = -dz/len, pz = dx/len;

      for (const side of [-1, 1]) {
        const o = side * EDGE_OFFSET;
        const w = side * EDGE_W;
        const lx0 = p.x  + px*(o-w), lz0 = p.z  + pz*(o-w);
        const rx0 = p.x  + px*(o+w), rz0 = p.z  + pz*(o+w);
        const lx1 = nx.x + px*(o-w), lz1 = nx.z + pz*(o-w);
        const rx1 = nx.x + px*(o+w), rz1 = nx.z + pz*(o+w);
        positions.push(
          lx0, p.y+0.06,  lz0,
          rx0, p.y+0.06,  rz0,
          lx1, nx.y+0.06, lz1,
          rx0, p.y+0.06,  rz0,
          rx1, nx.y+0.06, rz1,
          lx1, nx.y+0.06, lz1,
        );
      }
    }

    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
    geo.computeVertexNormals();
    const mat  = new THREE.MeshLambertMaterial({ color: 0xffffff });
    const mesh = new THREE.Mesh(geo, mat);
    this._roadEdgeMesh = mesh;
    group.add(mesh);
  }

  _buildJunctions(group, junctions) {
    if (!junctions || !junctions.length) return;
    const STUB_LEN = 80, N = 6;
    const mat = new THREE.MeshLambertMaterial({ color: 0x777777 });
    const verts = [], indices = [];
    for (const jn of junctions) {
      for (const stub of jn.stubs) {
        const hdRad = THREE.MathUtils.degToRad(stub.heading_deg);
        const dx = Math.sin(hdRad), dy = Math.cos(hdRad);
        for (let i = 0; i < N; i++) {
          const d0 = i * STUB_LEN / N, d1 = (i+1) * STUB_LEN / N;
          const t0 = i / N, t1 = (i+1) / N;
          const hw0 = ROAD_HALF_W * (1 - t0 * 0.6);
          const hw1 = ROAD_HALF_W * (1 - t1 * 0.6);
          const base = verts.length / 3;
          const y = jn.local_z + 0.05;
          verts.push(
            jn.local_x + dx*d0 - dy*hw0, y, -(jn.local_y + dy*d0 + dx*hw0),
            jn.local_x + dx*d0 + dy*hw0, y, -(jn.local_y + dy*d0 - dx*hw0),
            jn.local_x + dx*d1 - dy*hw1, y, -(jn.local_y + dy*d1 + dx*hw1),
            jn.local_x + dx*d1 + dy*hw1, y, -(jn.local_y + dy*d1 - dx*hw1),
          );
          indices.push(base, base+1, base+2,  base+1, base+3, base+2);
        }
      }
    }
    if (!verts.length) return;
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.Float32BufferAttribute(verts, 3));
    geo.setIndex(indices);
    geo.computeVertexNormals();
    group.add(new THREE.Mesh(geo, mat));
    console.log(`Junctions: ${junctions.length} intersections rendered`);
  }

  _buildScenery(group, scenery, terrainGrid) {
    const trees    = scenery.filter(s => s.type === 'tree');
    const houses   = scenery.filter(s => s.type === 'house');
    const churches = scenery.filter(s => s.type === 'church');

    // Roadside trees (from full route compiler) — only if any exist
    if (trees.length > 0) {
      const canopyGeo = new THREE.ConeGeometry(2.5, TREE_HEIGHT * 0.7, 6);
      canopyGeo.translate(0, TREE_HEIGHT * 0.35 + TREE_HEIGHT * 0.3, 0);
      const trunkGeo  = new THREE.CylinderGeometry(0.4, 0.6, TREE_HEIGHT * 0.35, 6);
      trunkGeo.translate(0, TREE_HEIGHT * 0.35 / 2, 0);
      const canopyMesh = new THREE.InstancedMesh(canopyGeo,
          new THREE.MeshLambertMaterial({ color: 0x2a7a18, flatShading: true }), trees.length);
      const trunkMesh  = new THREE.InstancedMesh(trunkGeo,
          new THREE.MeshLambertMaterial({ color: 0x6b3c11, flatShading: true }), trees.length);
      canopyMesh.castShadow = true;
      trees.forEach((sc, i) => {
        this._dummy.position.set(sc.local_x, sc.local_z, -sc.local_y);
        this._dummy.rotation.y = (sc.local_x * 13.7 + sc.local_y * 7.3) % (Math.PI * 2);
        this._dummy.updateMatrix();
        canopyMesh.setMatrixAt(i, this._dummy.matrix);
        trunkMesh.setMatrixAt(i, this._dummy.matrix);
      });
      group.add(canopyMesh, trunkMesh);
    }

    // Houses: walls + gable roof
    if (houses.length > 0) {
      const wallGeo = new THREE.BoxGeometry(8, HOUSE_HEIGHT, 8);
      wallGeo.translate(0, HOUSE_HEIGHT / 2, 0);
      const RW = 9.5, RL = 9.5, RH = HOUSE_HEIGHT, RP = HOUSE_HEIGHT * 0.55;
      const roofGeo = new THREE.BufferGeometry();
      roofGeo.setAttribute('position', new THREE.Float32BufferAttribute([
        -RW/2, RH, -RL/2,    RW/2, RH, -RL/2,    RW/2, RH,  RL/2,   -RW/2, RH,  RL/2,
            0, RH+RP, -RL/2,     0, RH+RP,  RL/2,
      ], 3));
      roofGeo.setIndex([0,3,5, 0,5,4,  1,4,5, 1,5,2,  0,4,1,  3,2,5]);
      roofGeo.computeVertexNormals();
      const wallMesh = new THREE.InstancedMesh(wallGeo,
          new THREE.MeshLambertMaterial({ color: 0xccc098, flatShading: true }), houses.length);
      const roofMesh = new THREE.InstancedMesh(roofGeo,
          new THREE.MeshLambertMaterial({ color: 0x883322, flatShading: true }), houses.length);
      wallMesh.castShadow = true;
      houses.forEach((sc, i) => {
        let groundZ = sc.local_z;
        if (terrainGrid) {
          for (let dlx = -10; dlx <= 10; dlx += 5)
            for (let dly = -10; dly <= 10; dly += 5) {
              const h = this._terrainHeight(sc.local_x + dlx, sc.local_y + dly, terrainGrid);
              if (h < groundZ) groundZ = h;
            }
        }
        this._dummy.position.set(sc.local_x, groundZ, -sc.local_y);
        this._dummy.rotation.y = Math.round(sc.local_x * 3.1) * Math.PI / 2;
        this._dummy.updateMatrix();
        wallMesh.setMatrixAt(i, this._dummy.matrix);
        roofMesh.setMatrixAt(i, this._dummy.matrix);
      });
      group.add(wallMesh, roofMesh);
    }

    // Churches: nave + tower + Zwiebelturm (onion dome)
    if (churches.length > 0) {
      // Nave (long body)
      const naveGeo = new THREE.BoxGeometry(9, 6, 22);
      naveGeo.translate(0, 3, 2);
      // Tower at front
      const towerGeo = new THREE.BoxGeometry(6, 18, 6);
      towerGeo.translate(0, 9, -9);
      // Onion dome (Zwiebelturm) via LatheGeometry
      const onionPts = [
        new THREE.Vector2(0,   0),   new THREE.Vector2(0.9, 0.5),
        new THREE.Vector2(2.1, 2.2), new THREE.Vector2(1.8, 3.8),
        new THREE.Vector2(0.7, 5.2), new THREE.Vector2(0.2, 6.0),
        new THREE.Vector2(0,   6.2),
      ];
      const onionGeo = new THREE.LatheGeometry(onionPts, 8);
      onionGeo.translate(0, 18, -9);
      const naveMesh   = new THREE.InstancedMesh(naveGeo,
          new THREE.MeshLambertMaterial({ color: 0xeeeedd, flatShading: true }), churches.length);
      const towerMesh  = new THREE.InstancedMesh(towerGeo,
          new THREE.MeshLambertMaterial({ color: 0xeeeedd, flatShading: true }), churches.length);
      const onionMesh  = new THREE.InstancedMesh(onionGeo,
          new THREE.MeshLambertMaterial({ color: 0x4a7a3a, flatShading: true }), churches.length);
      naveMesh.castShadow = towerMesh.castShadow = true;
      churches.forEach((sc, i) => {
        let groundZ = sc.local_z;
        if (terrainGrid) {
          for (let dlx = -10; dlx <= 10; dlx += 5)
            for (let dly = -10; dly <= 10; dly += 5) {
              const h = this._terrainHeight(sc.local_x + dlx, sc.local_y + dly, terrainGrid);
              if (h < groundZ) groundZ = h;
            }
        }
        this._dummy.position.set(sc.local_x, groundZ, -sc.local_y);
        this._dummy.rotation.y = Math.round(sc.local_x * 3.1) * Math.PI / 2;
        this._dummy.updateMatrix();
        naveMesh.setMatrixAt(i, this._dummy.matrix);
        towerMesh.setMatrixAt(i, this._dummy.matrix);
        onionMesh.setMatrixAt(i, this._dummy.matrix);
      });
      group.add(naveMesh, towerMesh, onionMesh);
    }

    console.log(`Scenery: ${trees.length} trees, ${houses.length} houses, ${churches.length} churches`);
  }

  _buildAvatar() {
    const g = new THREE.Group();
    const mFrame  = new THREE.MeshLambertMaterial({ color: 0x1a1a4a });
    const mTire   = new THREE.MeshLambertMaterial({ color: 0x111111 });
    const mMetal  = new THREE.MeshLambertMaterial({ color: 0x888899 });
    const mJersey = new THREE.MeshLambertMaterial({ color: 0xee5500, flatShading: true });
    const mBibs   = new THREE.MeshLambertMaterial({ color: 0x111111, flatShading: true });  // black shorts
    const mSkin   = new THREE.MeshLambertMaterial({ color: 0xffaa88, flatShading: true });  // pink skin
    const mHelmet = new THREE.MeshLambertMaterial({ color: 0x44aaee, flatShading: true });
    const mShoe   = new THREE.MeshLambertMaterial({ color: 0x111111, flatShading: true });  // black shoes
    const mSock   = new THREE.MeshLambertMaterial({ color: 0xffffff, flatShading: true });  // white socks

    const v3 = (x, y, z) => new THREE.Vector3(x, y, z);

    // Skeleton key points (avatar local: Y-up, -Z forward)
    const BB  = v3(0,      0.29,  0.10);   // bottom bracket
    const RA  = v3(0,      0.335, 0.95);   // rear axle
    const FA  = v3(0,      0.335,-0.95);   // front axle
    const SC  = v3(0,      1.14,  0.28);   // seat cluster
    const HT  = v3(0,      1.05, -0.63);   // head tube centre
    const HTB = v3(0,      0.82, -0.76);   // head tube bottom

    // Connect two points with a cylinder tube
    const tube = (tgt, a, b, r, mat) => {
      const len = a.distanceTo(b);
      if (len < 0.001) return;
      const m = new THREE.Mesh(new THREE.CylinderGeometry(r, r, len, 8), mat);
      m.position.copy(a.clone().lerp(b, 0.5));
      m.quaternion.setFromUnitVectors(v3(0, 1, 0), b.clone().sub(a).normalize());
      m.castShadow = true;
      tgt.add(m);
      return m;
    };

    // Wheels — torus tires standing in YZ plane
    const tireGeo = new THREE.TorusGeometry(0.335, 0.028, 8, 24);
    tireGeo.rotateY(Math.PI / 2);
    [RA, FA].forEach(axle => {
      const tire = new THREE.Mesh(tireGeo, mTire);
      tire.position.copy(axle);
      g.add(tire);
      const hub = new THREE.Mesh(new THREE.CylinderGeometry(0.055, 0.055, 0.10, 8), mMetal);
      hub.rotation.z = Math.PI / 2;
      hub.position.copy(axle);
      g.add(hub);
    });

    // Frame tubes
    tube(g, BB,  SC,  0.028, mFrame);   // seat tube
    tube(g, SC,  HT,  0.024, mFrame);   // top tube
    tube(g, HTB, BB,  0.028, mFrame);   // down tube
    tube(g, SC,  RA,  0.020, mFrame);   // seat stay
    tube(g, BB,  RA,  0.022, mFrame);   // chain stay
    tube(g, HT,  FA,  0.025, mFrame);   // fork

    // Seat post + saddle
    tube(g, SC, v3(0, 1.22, 0.28), 0.016, mMetal);
    const sad = new THREE.Mesh(new THREE.BoxGeometry(0.20, 0.05, 0.30), mBibs);
    sad.position.set(0, 1.24, 0.22);
    sad.rotation.x = 0.08;
    g.add(sad);

    // Stem + drop handlebars
    tube(g, HT, v3(0, 1.07, -0.80), 0.016, mMetal);
    tube(g, v3(-0.23, 1.07, -0.82), v3(0.23, 1.07, -0.82), 0.013, mMetal);   // flat top
    tube(g, v3(-0.23, 1.07, -0.82), v3(-0.23, 0.89, -0.83), 0.013, mMetal);  // right drop
    tube(g, v3(0.23,  1.07, -0.82), v3(0.23,  0.89, -0.83), 0.013, mMetal);  // left drop

    // Chainring
    const crGeo = new THREE.TorusGeometry(0.115, 0.014, 6, 18);
    crGeo.rotateY(Math.PI / 2);
    const chainring = new THREE.Mesh(crGeo, mMetal);
    chainring.position.copy(BB);
    g.add(chainring);

    // Crank group — rotates around BB along X axis
    const crankGroup = new THREE.Group();
    crankGroup.position.copy(BB);
    const CR = 0.175;
    tube(crankGroup, v3(0, 0, 0), v3(0,  CR, 0), 0.014, mFrame);  // right arm (top at θ=0)
    tube(crankGroup, v3(0, 0, 0), v3(0, -CR, 0), 0.014, mFrame);  // left arm
    const pedalGeo = new THREE.BoxGeometry(0.09, 0.025, 0.11);
    const pedalR = new THREE.Mesh(pedalGeo, mShoe);
    pedalR.position.set(0.12, CR, 0);
    crankGroup.add(pedalR);
    const pedalL = new THREE.Mesh(pedalGeo, mShoe);
    pedalL.position.set(-0.12, -CR, 0);
    crankGroup.add(pedalL);
    g.add(crankGroup);

    // Torso — leaning ~50° forward
    const torso = new THREE.Mesh(new THREE.BoxGeometry(0.34, 0.64, 0.26), mJersey);
    torso.position.set(0, 1.40, -0.30);
    torso.rotation.x = -0.90;  // lean forward toward handlebars (-Z = front)
    torso.castShadow = true;
    g.add(torso);

    // Head + helmet
    const head = new THREE.Mesh(new THREE.SphereGeometry(0.14, 8, 6), mSkin);
    head.position.set(0, 1.76, -0.62);
    g.add(head);
    const helmet = new THREE.Mesh(new THREE.SphereGeometry(0.17, 8, 5), mHelmet);
    helmet.scale.set(1, 0.72, 1.2);
    helmet.position.set(0, 1.83, -0.60);
    g.add(helmet);

    // Arms
    tube(g, v3(-0.17, 1.62, -0.48), v3(-0.23, 1.07, -0.82), 0.055, mJersey);
    tube(g, v3(0.17,  1.62, -0.48), v3(0.23,  1.07, -0.82), 0.055, mJersey);

    // Leg bones — unit-height cylinders, posed per-frame in _animLegs
    const bone = (mat) => {
      const m = new THREE.Mesh(new THREE.CylinderGeometry(0.08, 0.08, 1.0, 7), mat);
      m.castShadow = true;
      g.add(m);
      return m;
    };
    const rThigh = bone(mBibs);
    const rShin  = bone(mSkin);  // skin-coloured shins — shorts end at knee
    const lThigh = bone(mBibs);
    const lShin  = bone(mSkin);
    const rShoe  = new THREE.Mesh(new THREE.BoxGeometry(0.10, 0.06, 0.24), mShoe);
    const lShoe  = new THREE.Mesh(new THREE.BoxGeometry(0.10, 0.06, 0.24), mShoe);
    g.add(rShoe, lShoe);
    const sockGeo = new THREE.CylinderGeometry(0.088, 0.088, 0.12, 7);
    const rSock   = new THREE.Mesh(sockGeo, mSock);
    const lSock   = new THREE.Mesh(sockGeo, mSock);
    g.add(rSock, lSock);

    // Store animated refs
    this._crankGroup = crankGroup;
    this._crankCR    = CR;
    this._crankBB    = BB.clone();
    this._legMeshes  = { rThigh, rShin, lThigh, lShin, rShoe, lShoe, rSock, lSock };
    this._hipR = v3( 0.16, 1.18, 0.20);
    this._hipL = v3(-0.16, 1.18, 0.20);
    this._legL1 = 0.48;  // thigh length
    this._legL2 = 0.46;  // shin length

    return g;
  }

  // IK helper — find knee position given hip, pedal, bone lengths
  _solveKnee(hip, pedal, L1, L2) {
    const diff = pedal.clone().sub(hip);
    const d = Math.min(diff.length(), L1 + L2 - 0.01);
    const dir = d > 0.001 ? diff.clone().divideScalar(diff.length()) : new THREE.Vector3(0, -1, 0);
    const cosA = (L1 * L1 + d * d - L2 * L2) / (2 * L1 * d);
    const angA = Math.acos(Math.max(-1, Math.min(1, cosA)));
    // Knee bends forward (-Z in avatar local space)
    const fwd = new THREE.Vector3(0, 0, -1);
    let perp = fwd.clone().sub(dir.clone().multiplyScalar(dir.dot(fwd)));
    if (perp.lengthSq() < 1e-6) perp.set(0, -1, 0);
    perp.normalize();
    return hip.clone()
      .addScaledVector(dir, L1 * Math.cos(angA))
      .addScaledVector(perp, L1 * Math.sin(angA));
  }

  // Orient a unit-Y cylinder mesh to span from a to b
  _setBone(mesh, a, b) {
    const diff = b.clone().sub(a);
    const len  = diff.length();
    mesh.position.copy(a.clone().lerp(b, 0.5));
    mesh.scale.y = len > 0.001 ? len : 0.001;
    const dir = len > 0.001 ? diff.divideScalar(len) : new THREE.Vector3(0, 1, 0);
    mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir);
  }

  // Drive crank rotation and IK legs — called each frame from update()
  _animLegs(crankAngle) {
    const { _crankBB: BB, _crankCR: CR, _hipR, _hipL, _legL1: L1, _legL2: L2 } = this;
    const { rThigh, rShin, lThigh, lShin, rShoe, lShoe } = this._legMeshes;

    this._crankGroup.rotation.x = -crankAngle;  // forward pedaling: top→front→bottom→rear

    // Pedal positions in avatar local space (crank rotates in YZ plane around X)
    const pR = new THREE.Vector3( 0.12, BB.y + CR * Math.cos(crankAngle), BB.z - CR * Math.sin(crankAngle));
    const pL = new THREE.Vector3(-0.12, BB.y - CR * Math.cos(crankAngle), BB.z + CR * Math.sin(crankAngle));

    const kR = this._solveKnee(_hipR, pR, L1, L2);
    const kL = this._solveKnee(_hipL, pL, L1, L2);

    this._setBone(rThigh, _hipR, kR);
    this._setBone(rShin,  kR,    pR);
    this._setBone(lThigh, _hipL, kL);
    this._setBone(lShin,  kL,    pL);

    rShoe.position.copy(pR);
    lShoe.position.copy(pL);

    // Socks — short white cylinder just above each pedal, oriented along shin
    const { rSock, lSock } = this._legMeshes;
    const shinDirR = pR.clone().sub(kR).normalize();
    rSock.position.copy(pR.clone().addScaledVector(shinDirR, 0.07));
    rSock.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), shinDirR);
    const shinDirL = pL.clone().sub(kL).normalize();
    lSock.position.copy(pL.clone().addScaledVector(shinDirL, 0.07));
    lSock.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), shinDirL);
  }

  // ---------------------------------------------------------------------------
  // Per-frame updates
  // ---------------------------------------------------------------------------

  _updateRoadWindow(dist_m) {
    if (!this._roadMesh) return;
    const n  = this._nRoadSegs;
    const iA = Math.max(0,   this._wpIndex(dist_m - 5));
    const iB = Math.min(n,   this._wpIndex(dist_m + 500) + 1);
    const cnt = Math.max(0, iB - iA);
    // Road surface: 6 indices per segment
    this._roadMesh.geometry.setDrawRange(6 * iA, 6 * cnt);
    // Road edges: 12 non-indexed verts per segment (6 per side × 2 sides)
    if (this._roadEdgeMesh) this._roadEdgeMesh.geometry.setDrawRange(12 * iA, 12 * cnt);
    // Verge: 12 indices per segment (6 per side × 2 sides)
    if (this._vergeMesh)    this._vergeMesh.geometry.setDrawRange(12 * iA, 12 * cnt);
  }

  _wpIndex(dist) {
    const wps = this._wps;
    let lo = 0, hi = wps.length - 1;
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1;
      if (wps[mid].dist_m <= dist) lo = mid; else hi = mid - 1;
    }
    return lo;
  }

  _interpPos(dist) {
    const wps = this._wps;
    const i   = this._wpIndex(dist);
    if (i >= wps.length - 1) return t3(wps[i].local_x, wps[i].local_y, wps[i].local_z);
    const a = wps[i], b = wps[i+1];
    const t = (b.dist_m - a.dist_m) > 0 ? (dist - a.dist_m) / (b.dist_m - a.dist_m) : 0;
    return new THREE.Vector3(
      a.local_x + t * (b.local_x - a.local_x),
      (a.local_z + t * (b.local_z - a.local_z)),
      -(a.local_y + t * (b.local_y - a.local_y)),
    );
  }

  _riderOffset(dist) {
    const wps   = this._wps;
    const i     = this._wpIndex(dist);
    const ahead = Math.min(wps.length - 1, this._wpIndex(dist + 5));
    const dx  = wps[ahead].local_x - wps[i].local_x;
    const dz  = -(wps[ahead].local_y - wps[i].local_y);
    const len = Math.sqrt(dx*dx + dz*dz) || 1;
    // right perpendicular in world XZ
    return new THREE.Vector3(dz/len * this._lateralOff, 0, -dx/len * this._lateralOff);
  }

  _moveAvatar(dist) {
    const ROAD_LIFT = 0.20;  // matches +0.20 road ribbon offset in _buildRoad
    const pos  = this._interpPos(dist).add(this._riderOffset(dist));
    pos.y += ROAD_LIFT;
    const look = this._interpPos(dist + 5).add(this._riderOffset(dist + 5));
    look.y += ROAD_LIFT;
    this._avatar.position.copy(pos);
    this._avatar.lookAt(look);
    // Object3D.lookAt makes +Z face the target; avatar is built -Z forward,
    // so rotate 180° to flip the facing direction.
    this._avatar.rotateY(Math.PI);
  }

  _moveCamera(dist) {
    const riderPos  = this._interpPos(dist).add(this._riderOffset(dist));
    const lookAhead = this._interpPos(dist + 25).add(this._riderOffset(dist + 25));

    const forward = lookAhead.clone().sub(riderPos).normalize();

    if (this._cameraMode === 'chase') {
      this._camera.position.copy(riderPos)
        .addScaledVector(forward, -8)
        .add(new THREE.Vector3(0, 2.5, 0));
      this._camera.lookAt(lookAhead);
    } else {
      this._camera.position.copy(riderPos).add(new THREE.Vector3(-60, 50, -60));
      this._camera.lookAt(riderPos);
    }
  }
}
