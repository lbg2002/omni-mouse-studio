/* Real-Time WebGL 3D Model of Delux M618XSD (Right-Handed Vertical Ergonomic Edition)
 * Coordinate Convention (True Right-Handed):
 *   +X = Right side of mouse (Main vertical scroll wheel, Left/Right primary buttons, DELUX logo, right palm skirt)
 *   -X = Left side of mouse  (Deep thumb groove, upper-left spherical thumb wheel, lower-left Forward/Backward buttons)
 *   +Y = Up                  (Top curved OLED display strip + oval DPI button)
 *   -Z = Front nose          (Fingertip front)
 *   +Z = Rear                (Glowing honeycomb hex cutouts + rear magnetic perforated palm rest)
 */
(function () {
  "use strict";

  const TAU = Math.PI * 2;

  function clamp(v, lo, hi) {
    return Math.max(lo, Math.min(hi, v));
  }

  function smoothstep(e0, e1, x) {
    const t = clamp((x - e0) / (e1 - e0), 0, 1);
    return t * t * (3 - 2 * t);
  }

  const Mat4 = {
    perspective(fovRad, aspect, near, far) {
      const f = 1.0 / Math.tan(fovRad / 2);
      const nf = 1 / (near - far);
      return new Float32Array([
        f / aspect, 0, 0, 0,
        0, f, 0, 0,
        0, 0, (far + near) * nf, -1,
        0, 0, 2 * far * near * nf, 0,
      ]);
    },
    lookAt(eye, target, up) {
      let zx = eye[0] - target[0], zy = eye[1] - target[1], zz = eye[2] - target[2];
      let len = Math.hypot(zx, zy, zz) || 1;
      zx /= len; zy /= len; zz /= len;
      let xx = up[1] * zz - up[2] * zy;
      let xy = up[2] * zx - up[0] * zz;
      let xz = up[0] * zy - up[1] * zx;
      len = Math.hypot(xx, xy, xz) || 1;
      xx /= len; xy /= len; xz /= len;
      const yx = zy * xz - zz * xy;
      const yy = zz * xx - zx * xz;
      const yz = zx * xy - zy * xx;
      return new Float32Array([
        xx, yx, zx, 0,
        xy, yy, zy, 0,
        xz, yz, zz, 0,
        -(xx * eye[0] + xy * eye[1] + xz * eye[2]),
        -(yx * eye[0] + yy * eye[1] + yz * eye[2]),
        -(zx * eye[0] + zy * eye[1] + zz * eye[2]),
        1,
      ]);
    },
    mul(a, b) {
      const out = new Float32Array(16);
      for (let c = 0; c < 4; c++) {
        for (let r = 0; r < 4; r++) {
          out[c * 4 + r] =
            a[0 * 4 + r] * b[c * 4 + 0] +
            a[1 * 4 + r] * b[c * 4 + 1] +
            a[2 * 4 + r] * b[c * 4 + 2] +
            a[3 * 4 + r] * b[c * 4 + 3];
        }
      }
      return out;
    },
    project(vp, pt, width, height) {
      const x = pt[0], y = pt[1], z = pt[2];
      const cx = vp[0] * x + vp[4] * y + vp[8] * z + vp[12];
      const cy = vp[1] * x + vp[5] * y + vp[9] * z + vp[13];
      const cz = vp[2] * x + vp[6] * y + vp[10] * z + vp[14];
      const cw = vp[3] * x + vp[7] * y + vp[11] * z + vp[15];
      if (cw <= 0.05) return null;
      return {
        x: ((cx / cw) * 0.5 + 0.5) * width,
        y: (0.5 - (cy / cw) * 0.5) * height,
        z: cz / cw,
      };
    },
  };

  class MeshBuilder {
    constructor() {
      this.verts = [];
      this.indices = [];
    }

    get vertexCount() {
      return this.verts.length / 13;
    }

    pushVertex(p, n, uv, col, matId, extra) {
      const idx = this.verts.length / 13;
      this.verts.push(
        p[0], p[1], p[2],
        n[0], n[1], n[2],
        uv[0], uv[1],
        col[0], col[1], col[2],
        matId,
        extra || 0
      );
      return idx;
    }

    pushTri(a, b, c) {
      this.indices.push(a, b, c);
    }

    pushQuad(a, b, c, d) {
      this.indices.push(a, b, c, a, c, d);
    }

    addGrid(gridPts, rows, cols, wrapCols, colFn, matId, extraFn) {
      const norms = new Array(rows * cols);
      for (let r = 0; r < rows; r++) {
        for (let c = 0; c < cols; c++) {
          const p = gridPts[r * cols + c];
          const rPrev = Math.max(0, r - 1);
          const rNext = Math.min(rows - 1, r + 1);
          const cPrev = wrapCols ? (c - 1 + cols) % cols : Math.max(0, c - 1);
          const cNext = wrapCols ? (c + 1) % cols : Math.min(cols - 1, c + 1);
          const pu = gridPts[r * cols + cNext];
          const pd = gridPts[r * cols + cPrev];
          const pv = gridPts[rNext * cols + c];
          const pw = gridPts[rPrev * cols + c];
          const tx = pu[0] - pd[0], ty = pu[1] - pd[1], tz = pu[2] - pd[2];
          const bx = pv[0] - pw[0], by = pv[1] - pw[1], bz = pv[2] - pw[2];
          let nx = ty * bz - tz * by;
          let ny = tz * bx - tx * bz;
          let nz = tx * by - ty * bx;
          // Ensure outward pointing normal relative to mouse interior center (0, 0.55, 0)
          const rx = p[0], ry = p[1] - 0.50, rz = p[2];
          if (nx * rx + ny * ry + nz * rz < 0) {
            nx = -nx; ny = -ny; nz = -nz;
          }
          const nl = Math.hypot(nx, ny, nz) || 1;
          norms[r * cols + c] = [nx / nl, ny / nl, nz / nl];
        }
      }

      const baseIdx = this.vertexCount;
      for (let r = 0; r < rows; r++) {
        const v = rows > 1 ? r / (rows - 1) : 0;
        for (let c = 0; c < cols; c++) {
          const u = wrapCols ? c / cols : (cols > 1 ? c / (cols - 1) : 0);
          const p = gridPts[r * cols + c];
          const n = norms[r * cols + c];
          const color = colFn(u, v, p, n);
          const ex = extraFn ? extraFn(u, v, p, n) : 0;
          this.pushVertex(p, n, [u, v], color, matId, ex);
        }
      }

      const colLimit = wrapCols ? cols : cols - 1;
      for (let r = 0; r < rows - 1; r++) {
        for (let c = 0; c < colLimit; c++) {
          const c2 = wrapCols ? (c + 1) % cols : c + 1;
          const i00 = baseIdx + r * cols + c;
          const i10 = baseIdx + r * cols + c2;
          const i11 = baseIdx + (r + 1) * cols + c2;
          const i01 = baseIdx + (r + 1) * cols + c;
          this.pushQuad(i00, i10, i11, i01);
        }
      }
    }

    addEllipsoid(center, radii, rotEuler, color, matId, extra, segU = 24, segV = 16) {
      const [cx, cy, cz] = center;
      const [rx, ry, rz] = radii;
      const [ax, ay, az] = rotEuler;
      const cosX = Math.cos(ax), sinX = Math.sin(ax);
      const cosY = Math.cos(ay), sinY = Math.sin(ay);
      const cosZ = Math.cos(az), sinZ = Math.sin(az);

      function rot(x, y, z) {
        const x1 = x * cosZ - y * sinZ;
        const y1 = x * sinZ + y * cosZ;
        const y2 = y1 * cosX - z * sinX;
        const z2 = y1 * sinX + z * cosX;
        const x3 = x1 * cosY + z2 * sinY;
        const z3 = -x1 * sinY + z2 * cosY;
        return [x3, y2, z3];
      }

      const pts = [];
      for (let r = 0; r <= segV; r++) {
        const v = r / segV;
        const phi = (v - 0.5) * Math.PI;
        const cp = Math.cos(phi), sp = Math.sin(phi);
        for (let c = 0; c < segU; c++) {
          const th = (c / segU) * TAU;
          const rp = rot(rx * cp * Math.cos(th), ry * sp, rz * cp * Math.sin(th));
          pts.push([cx + rp[0], cy + rp[1], cz + rp[2]]);
        }
      }
      this.addGrid(pts, segV + 1, segU, true, () => color, matId, () => extra || 0);
    }

    addHexCell(center, normal, radius, phase, bezelColor) {
      let nx = normal[0], ny = normal[1], nz = normal[2];
      const nl = Math.hypot(nx, ny, nz) || 1;
      nx /= nl; ny /= nl; nz /= nl;

      let ux = 1, uy = 0, uz = 0;
      if (Math.abs(nx) > 0.85) { ux = 0; uy = 1; uz = 0; }
      let tx = uy * nz - uz * ny;
      let ty = uz * nx - ux * nz;
      let tz = ux * ny - uy * nx;
      const tl = Math.hypot(tx, ty, tz) || 1;
      tx /= tl; ty /= tl; tz /= tl;
      const bx = ny * tz - nz * ty;
      const by = nz * tx - nx * tz;
      const bz = nx * ty - ny * tx;

      const innerR = radius * 0.72;
      const bezelOff = 0.010;
      const glowOff = 0.013;

      // Glowing core (matId = 3.0, pure uniform matId across all 7 vertices)
      const cIdx = this.pushVertex(
        [center[0] + nx * glowOff, center[1] + ny * glowOff, center[2] + nz * glowOff],
        [nx, ny, nz],
        [0.5, 0.5],
        [0.35, 0.98, 0.96],
        3.0,
        phase
      );
      const glowRing = [];
      for (let i = 0; i < 6; i++) {
        const ang = (i / 6) * TAU + Math.PI / 6;
        const ca = Math.cos(ang), sa = Math.sin(ang);
        glowRing.push(
          this.pushVertex(
            [
              center[0] + (tx * ca + bx * sa) * innerR + nx * glowOff,
              center[1] + (ty * ca + by * sa) * innerR + ny * glowOff,
              center[2] + (tz * ca + bz * sa) * innerR + nz * glowOff,
            ],
            [nx, ny, nz],
            [0.5, 0.5],
            [0.35, 0.98, 0.96],
            3.0,
            phase
          )
        );
      }
      for (let i = 0; i < 6; i++) {
        this.pushTri(cIdx, glowRing[i], glowRing[(i + 1) % 6]);
      }

      // Dark hex bezel collar (matId = 0.0, separate vertices so zero vMat interpolation!)
      const bIn = [];
      const bOut = [];
      for (let i = 0; i < 6; i++) {
        const ang = (i / 6) * TAU + Math.PI / 6;
        const ca = Math.cos(ang), sa = Math.sin(ang);
        bIn.push(
          this.pushVertex(
            [
              center[0] + (tx * ca + bx * sa) * innerR + nx * bezelOff,
              center[1] + (ty * ca + by * sa) * innerR + ny * bezelOff,
              center[2] + (tz * ca + bz * sa) * innerR + nz * bezelOff,
            ],
            [nx, ny, nz],
            [0, 0],
            bezelColor,
            0.0,
            0.0
          )
        );
        bOut.push(
          this.pushVertex(
            [
              center[0] + (tx * ca + bx * sa) * radius + nx * bezelOff,
              center[1] + (ty * ca + by * sa) * radius + ny * bezelOff,
              center[2] + (tz * ca + bz * sa) * radius + nz * bezelOff,
            ],
            [nx, ny, nz],
            [0, 0],
            bezelColor,
            0.0,
            0.0
          )
        );
      }
      for (let i = 0; i < 6; i++) {
        const ni = (i + 1) % 6;
        this.pushQuad(bIn[i], bOut[i], bOut[ni], bIn[ni]);
      }
    }
  }

  /*
   * Right-handed parametric M618XSD vertical shell:
   *   th = u * 2pi:
   *     u = 0.00 (th = 0)      -> +X (RIGHT side: Left/Right primary buttons, main vertical wheel, DELUX logo)
   *     u = 0.25 (th = pi/2)   -> +Z (REAR slope: glowing Honeycomb hex cutouts)
   *     u = 0.50 (th = pi)     -> -X (LEFT side: deep Thumb groove, spherical thumb wheel, Fwd/Back buttons)
   *     u = 0.75 (th = 3pi/2)  -> -Z (FRONT nose: curved top OLED display strip)
   */
  function evalM618Body(u, v) {
    const th = u * TAU;
    const c = Math.cos(th);  // +1 = RIGHT (+X), -1 = LEFT (-X)
    const s = Math.sin(th);  // +1 = REAR  (+Z), -1 = FRONT (-Z)

    const y = 0.09 + 1.39 * Math.pow(v, 0.88);

    // Ergonomic 57-deg vertical lean: crest leans slightly left (-X) and forward (-Z)
    const spineX = -0.05 * Math.sin(v * Math.PI * 0.85) + 0.03 * (1 - v);
    const spineZ = 0.06 * (1 - v) - 0.24 * Math.pow(v, 1.15) + 0.08 * Math.pow(v, 3.0);

    const taperX = (1 - 0.74 * smoothstep(0.05, 1.0, v)) * Math.sqrt(Math.max(0.015, 1 - Math.pow(v, 6.5)));
    const taperZFront = (1 - 0.36 * Math.pow(v, 1.5)) * Math.sqrt(Math.max(0.02, 1 - Math.pow(v, 7.0)));
    const taperZRear = (1 - 0.62 * smoothstep(0.0, 0.92, v)) * Math.sqrt(Math.max(0.02, 1 - Math.pow(v, 6.5)));

    const rx = (c >= 0 ? 0.50 : 0.53) * taperX;
    const rz = (s <= 0 ? 0.82 * taperZFront : 0.76 * taperZRear);

    let x = spineX + rx * c;
    let z = spineZ + rz * s;

    // 1. LEFT Thumb Groove (c < 0, front-mid s < 0.25) — matches Photo 2!
    const leftMask = smoothstep(-0.15, -0.92, c) * smoothstep(0.25, -0.65, s);
    const scoopHeight = Math.sin(clamp((v - 0.10) / 0.66, 0, 1) * Math.PI);
    x += 0.19 * leftMask * Math.pow(Math.max(0, scoopHeight), 1.15);

    // Subtle vertical grip ribs inside thumb groove (Photo 2!)
    const ribMask = leftMask * smoothstep(0.20, 0.35, v) * (1 - smoothstep(0.55, 0.68, v));
    x -= 0.008 * Math.sin(z * 42.0) * ribMask;

    // Lower-left thumb rest lip
    x -= 0.07 * smoothstep(-0.2, -0.95, c) * smoothstep(0.32, 0.06, v) * smoothstep(0.2, -0.6, s);

    // 2. Concave S-curve on REAR Honeycomb Slope (s > 0) — matches Photo 1 & 2!
    const rearMask = smoothstep(0.15, 0.95, s);
    z -= 0.11 * rearMask * Math.sin(clamp((v - 0.12) / 0.78, 0, 1) * Math.PI);

    // 3. RIGHT Primary Button Split Seam Groove (c > 0, front-right s < 0) — matches Photo 1!
    const rightFrontMask = smoothstep(0.15, 0.9, c) * smoothstep(0.1, -0.75, s);
    x -= 0.014 * rightFrontMask * Math.exp(-Math.pow((v - 0.56) / 0.016, 2));

    return [x, y, z];
  }

  function buildM618XSDGeometry() {
    const mb = new MeshBuilder();

    const ROYAL_BLUE = [0.135, 0.345, 0.645];
    const DEEP_BLUE = [0.095, 0.255, 0.505];
    const RIM_BLUE = [0.155, 0.385, 0.705];
    const CHROME_ICE = [0.66, 0.86, 0.99];
    const THUMB_METAL = [0.27, 0.58, 0.96];
    const DARK_BEZEL = [0.035, 0.05, 0.085];

    // =========================================================================
    // 1. Detachable Magnetic Perforated Palm Rest (Flaring Rear +Z & Right +X — Photo 3!)
    // =========================================================================
    const prRings = 16;
    const prCols = 64;
    const prPts = [];
    for (let r = 0; r < prRings; r++) {
      const rv = r / (prRings - 1);
      for (let c = 0; c < prCols; c++) {
        const th = (c / prCols) * TAU;
        const cs = Math.cos(th), sn = Math.sin(th); // cs>0 = +X (Right), sn>0 = +Z (Rear)
        const radX = 0.88 + 0.14 * cs + 0.05 * sn;
        const radZ = sn > 0 ? 1.10 : 0.74;
        let radial, py;
        if (rv < 0.76) {
          radial = rv / 0.76;
          const lip = smoothstep(0.84, 1.0, radial) * 0.018;
          py = 0.115 - 0.022 * radial * radial + lip;
        } else {
          const edgeT = (rv - 0.76) / 0.24;
          radial = 1.0 + 0.045 * Math.sin(edgeT * Math.PI * 0.75);
          py = 0.111 * (1 - edgeT) + 0.005;
        }
        // Offset toward +X (Right) and +Z (Rear) exactly like Photo 3!
        const px = 0.09 + radX * radial * cs;
        const pz = 0.44 + radZ * radial * sn;
        prPts.push([px, py, pz]);
      }
    }
    mb.addGrid(
      prPts,
      prRings,
      prCols,
      true,
      (u, v) => (v < 0.70 ? DEEP_BLUE : RIM_BLUE),
      1.0,
      () => 0.0
    );

    // =========================================================================
    // 2. Sculpted Vertical Main Body Shell
    // =========================================================================
    const bRows = 44;
    const bCols = 72;
    const bPts = [];
    for (let r = 0; r < bRows; r++) {
      const v = r / (bRows - 1);
      for (let c = 0; c < bCols; c++) {
        bPts.push(evalM618Body(c / bCols, v));
      }
    }
    mb.addGrid(
      bPts,
      bRows,
      bCols,
      true,
      (u, v) => {
        const th = u * TAU;
        const c = Math.cos(th), s = Math.sin(th);
        // Shell seam between front grip (s < 0) and rear honeycomb shell (s > 0)
        if (Math.abs(s - 0.10 + 0.12 * v) < 0.012 && v > 0.08 && v < 0.88) {
          return DARK_BEZEL;
        }
        // Horizontal split seam between Left & Right primary buttons on RIGHT (+X, front s < 0)
        if (c > 0.22 && s < 0.02 && Math.abs(v - 0.56) < 0.009) {
          return DARK_BEZEL;
        }
        // Chrome lower contour strip on RIGHT flank (+X) — Photo 1!
        if (c > 0.05 && s < 0.15 && v > 0.045 && v < 0.088) {
          return CHROME_ICE;
        }
        // Chrome upper crest trim on RIGHT side of OLED — Photo 1 & 3!
        if (c > 0.18 && c < 0.68 && s < -0.05 && v > 0.84 && v < 0.89) {
          return CHROME_ICE;
        }
        return ROYAL_BLUE;
      },
      0.0,
      (u, v) => {
        const th = u * TAU;
        const c = Math.cos(th), s = Math.sin(th);
        if (c > 0.25 && s < 0.0) {
          return v > 0.56 ? 11.0 : 12.0;
        }
        return 0.0;
      }
    );

    // DELUX white wordmark decal on RIGHT lower flank (+X, u around 0.96..1.04) — Photo 1!
    const logoRows = 6, logoCols = 14;
    const logoPts = [];
    for (let r = 0; r < logoRows; r++) {
      const rv = r / (logoRows - 1);
      const bodyV = 0.24 - rv * 0.095;
      for (let c = 0; c < logoCols; c++) {
        const cu = c / (logoCols - 1);
        // c=0 at rear-right (+Z), c=1 toward front-right (-Z) -> reads left-to-right "DELUX" when viewing right side!
        const u = (0.045 - cu * 0.115 + 1.0) % 1.0;
        const bp = evalM618Body(u, bodyV);
        logoPts.push([bp[0] + 0.005, bp[1], bp[2]]);
      }
    }
    mb.addGrid(logoPts, logoRows, logoCols, false, () => [1, 1, 1], 5.0, () => 0.0);

    // =========================================================================
    // 3. Rear Honeycomb Hexagonal Cutout Array (centered around u = 0.25, +Z Rear!)
    // =========================================================================
    const hexRows = 7;
    for (let hr = 0; hr < hexRows; hr++) {
      const v = 0.17 + (hr / (hexRows - 1)) * 0.58;
      const colsInRow = hr < 2 ? 6 : (hr < 5 ? 7 : (hr === 5 ? 5 : 4));
      const arcSpan = 0.22 * (1 - 0.36 * (hr / hexRows));
      for (let hc = 0; hc < colsInRow; hc++) {
        const frac = colsInRow > 1 ? hc / (colsInRow - 1) - 0.5 : 0;
        const stagger = hr % 2 === 1 ? 0.012 : -0.012;
        const u = (0.25 + frac * arcSpan + stagger + 1.0) % 1.0; // u=0.25 -> +Z Rear!
        const p = evalM618Body(u, v);
        const pu = evalM618Body((u + 0.008) % 1.0, v);
        const pv = evalM618Body(u, Math.min(0.99, v + 0.012));
        const tx = pu[0] - p[0], ty = pu[1] - p[1], tz = pu[2] - p[2];
        const bx = pv[0] - p[0], by = pv[1] - p[1], bz = pv[2] - p[2];
        let nx = ty * bz - tz * by;
        let ny = tz * bx - tx * bz;
        let nz = tx * by - ty * bx;
        if (nx * p[0] + ny * (p[1] - 0.5) + nz * p[2] < 0) {
          nx = -nx; ny = -ny; nz = -nz;
        }
        const edgeFactor = 1.0 - 0.38 * Math.abs(frac * 2);
        const heightScale = 1.0 - 0.28 * (hr / hexRows);
        const radius = 0.043 * edgeFactor * heightScale;
        const phase = hr * 0.14 + (frac + 0.5) * 0.25;
        mb.addHexCell(p, [nx, ny, nz], radius, phase, [0.05, 0.15, 0.32]);
      }
    }

    // =========================================================================
    // 4. Top Curved Glossy OLED Display Strip (Front-Top Spine u = 0.75, -Z) + Oval DPI Button
    // =========================================================================
    const oledRows = 16;
    const oledCols = 10;
    const oledPts = [];
    for (let r = 0; r < oledRows; r++) {
      const rv = r / (oledRows - 1);
      const bodyV = 0.985 - rv * 0.27;
      for (let c = 0; c < oledCols; c++) {
        const cu = c / (oledCols - 1) - 0.5;
        const u = (0.75 + cu * 0.11 + 1.0) % 1.0; // u=0.75 -> -Z Front Spine!
        const baseP = evalM618Body(u, bodyV);
        const arch = (1 - 4 * cu * cu) * 0.018 + 0.008;
        oledPts.push([baseP[0] + cu * 0.02, baseP[1] + arch, baseP[2] - arch * 0.65]);
      }
    }
    mb.addGrid(oledPts, oledRows, oledCols, false, () => [0.02, 0.03, 0.05], 4.0, () => 16.0);

    // Oval Ice-Blue Metallic DPI Cycle Button right behind OLED on top peak (+Z side of peak) — Photo 3!
    const topPeak = evalM618Body(0.25, 0.97);
    mb.addEllipsoid(
      [topPeak[0] - 0.01, topPeak[1] + 0.032, topPeak[2] - 0.04],
      [0.052, 0.024, 0.082],
      [0.18, 0.0, 0.05],
      CHROME_ICE,
      2.0,
      16.0
    );

    // =========================================================================
    // 5. LEFT Upper Metallic-Blue Spherical/Barrel Thumb Scroll Wheel (u = 0.54, -X Left — Photo 2!)
    // =========================================================================
    const thumbAnchor = evalM618Body(0.54, 0.72);
    mb.addEllipsoid(
      [thumbAnchor[0] + 0.01, thumbAnchor[1], thumbAnchor[2]],
      [0.048, 0.115, 0.115],
      [0.0, -0.12, 0.25],
      DARK_BEZEL,
      0.0,
      15.0
    );
    mb.addEllipsoid(
      [thumbAnchor[0] - 0.032, thumbAnchor[1], thumbAnchor[2]],
      [0.078, 0.092, 0.092],
      [0.0, -0.12, 0.25],
      THUMB_METAL,
      2.2,
      15.0,
      28,
      18
    );

    // =========================================================================
    // 6. LEFT Lower Silver-Blue Metallic Forward & Backward Buttons (-X Left — Photo 2 & 3!)
    // =========================================================================
    const fwdAnchor = evalM618Body(0.58, 0.24); // Front-left (-Z, -X)
    const bwdAnchor = evalM618Body(0.52, 0.23); // Rear-left  (+Z, -X)
    mb.addEllipsoid(
      [fwdAnchor[0] - 0.022, fwdAnchor[1], fwdAnchor[2] - 0.02],
      [0.036, 0.042, 0.098],
      [-0.08, 0.24, -0.18],
      CHROME_ICE,
      2.0,
      13.0
    );
    mb.addEllipsoid(
      [bwdAnchor[0] - 0.024, bwdAnchor[1] - 0.005, bwdAnchor[2] + 0.03],
      [0.036, 0.042, 0.098],
      [-0.04, 0.06, -0.18],
      CHROME_ICE,
      2.0,
      14.0
    );

    // =========================================================================
    // 7. RIGHT Flank Recessed Vertical Main Scroll Wheel (+X Right, Front -Z — Photo 1 & 3!)
    // =========================================================================
    const wheelAnchor = evalM618Body(0.89, 0.56);
    mb.addEllipsoid(
      [wheelAnchor[0] - 0.015, wheelAnchor[1], wheelAnchor[2]],
      [0.045, 0.042, 0.118],
      [0.0, -0.36, 0.0],
      DARK_BEZEL,
      0.0,
      17.0
    );
    mb.addEllipsoid(
      [wheelAnchor[0] + 0.018, wheelAnchor[1], wheelAnchor[2]],
      [0.048, 0.034, 0.096],
      [0.0, -0.36, 0.0],
      [0.32, 0.62, 0.95],
      2.1,
      17.0,
      26,
      16
    );

    // =========================================================================
    // 8. Subtle Technical Calibration Ring on Floor (matId = 6.0)
    // =========================================================================
    const pRingPts = [];
    const pRingCols = 72;
    for (let r = 0; r < 2; r++) {
      const rad = r === 0 ? 1.24 : 1.50;
      for (let c = 0; c < pRingCols; c++) {
        const th = (c / pRingCols) * TAU;
        pRingPts.push([0.05 + rad * Math.cos(th), -0.015, 0.25 + rad * Math.sin(th)]);
      }
    }
    mb.addGrid(pRingPts, 2, pRingCols, true, () => [0.0, 0.82, 1.0], 6.0, () => 0.0);

    return {
      vertices: new Float32Array(mb.verts),
      indices: new Uint32Array(mb.indices),
      anchors: {
        thumb_wheel: { p: [thumbAnchor[0] - 0.08, thumbAnchor[1] + 0.02, thumbAnchor[2]], n: [-0.92, 0.25, -0.20] },
        forward: { p: [fwdAnchor[0] - 0.06, fwdAnchor[1], fwdAnchor[2] - 0.03], n: [-0.92, 0.15, -0.25] },
        backward: { p: [bwdAnchor[0] - 0.06, bwdAnchor[1], bwdAnchor[2] + 0.03], n: [-0.92, 0.15, 0.15] },
        oled_dpi: { p: [topPeak[0], topPeak[1] + 0.07, topPeak[2] - 0.14], n: [0.0, 0.92, -0.30] },
        main_wheel: { p: [wheelAnchor[0] + 0.06, wheelAnchor[1], wheelAnchor[2]], n: [0.92, 0.15, -0.35] },
        honeycomb_rgb: { p: evalM618Body(0.25, 0.46), n: [0.0, 0.35, 0.94] },
      },
    };
  }

  const VS_SRC = `
    attribute vec3 aPos;
    attribute vec3 aNorm;
    attribute vec2 aUv;
    attribute vec3 aCol;
    attribute float aMat;
    attribute float aExtra;

    uniform mat4 uVP;

    varying vec3 vWorldPos;
    varying vec3 vWorldNorm;
    varying vec2 vUv;
    varying vec3 vCol;
    varying float vMat;
    varying float vExtra;

    void main() {
      vWorldPos = aPos;
      vWorldNorm = normalize(aNorm);
      vUv = aUv;
      vCol = aCol;
      vMat = aMat;
      vExtra = aExtra;
      gl_Position = uVP * vec4(aPos, 1.0);
    }
  `;

  const FS_SRC = `
    precision highp float;

    varying vec3 vWorldPos;
    varying vec3 vWorldNorm;
    varying vec2 vUv;
    varying vec3 vCol;
    varying float vMat;
    varying float vExtra;

    uniform vec3 uCamPos;
    uniform float uTime;
    uniform vec3 uRgbColor;
    uniform float uRgbMode;
    uniform float uRgbBright;
    uniform float uRgbSpeed;
    uniform float uHoverZone;
    uniform sampler2D uOledTex;
    uniform sampler2D uLogoTex;

    vec3 hsv2rgb(vec3 c) {
      vec4 K = vec4(1.0, 2.0 / 3.0, 1.0 / 3.0, 3.0);
      vec3 p = abs(fract(c.xxx + K.xyz) * 6.0 - K.www);
      return c.z * mix(K.xxx, clamp(p - K.xxx, 0.0, 1.0), c.y);
    }

    float hexPattern(vec2 p) {
      p *= 26.0;
      vec2 r = vec2(1.0, 1.7320508);
      vec2 h = r * 0.5;
      vec2 a = mod(p, r) - h;
      vec2 b = mod(p - h, r) - h;
      vec2 gv = dot(a, a) < dot(b, b) ? a : b;
      float d = max(abs(gv.x), dot(abs(gv), normalize(vec2(1.0, 1.7320508))));
      return smoothstep(0.32, 0.44, d);
    }

    vec3 evalHoneycombGlow(float phase) {
      if (uRgbMode < 0.5 || uRgbBright <= 0.02) {
        return vec3(0.30, 0.80, 0.88);
      }
      float spd = 0.45 + uRgbSpeed * 0.32;
      vec3 base = uRgbColor;
      float pulse = 1.0;
      if (abs(uRgbMode - 8.0) < 0.4) {
        float h = fract(0.50 + 0.20 * sin(uTime * spd * 1.4 - phase * 4.2) + phase * 0.32 - uTime * spd * 0.16);
        base = hsv2rgb(vec3(h, 0.78, 1.0));
        base = mix(base, vec3(0.36, 0.99, 0.95), 0.35);
      } else if (abs(uRgbMode - 3.0) < 0.4) {
        base = hsv2rgb(vec3(fract(uTime * spd * 0.15), 0.85, 1.0));
      } else if (abs(uRgbMode - 4.0) < 0.4) {
        pulse = 0.25 + 0.75 * (0.5 + 0.5 * sin(uTime * spd * 1.6));
        base = hsv2rgb(vec3(fract(uTime * 0.08 + phase * 0.2), 0.85, 1.0));
      } else if (abs(uRgbMode - 2.0) < 0.4 || abs(uRgbMode - 6.0) < 0.4) {
        pulse = 0.18 + 0.82 * (0.5 + 0.5 * sin(uTime * spd * 1.8));
      }
      return base * (0.35 + 1.35 * uRgbBright * pulse);
    }

    void main() {
      vec3 N = normalize(vWorldNorm);
      vec3 V = normalize(uCamPos - vWorldPos);

      // Technical floor calibration ring (mat == 6)
      if (abs(vMat - 6.0) < 0.3) {
        float radial = vUv.y;
        float ring1 = smoothstep(0.06, 0.0, abs(radial - 0.08));
        float ring2 = smoothstep(0.04, 0.0, abs(radial - 0.90));
        float ticks = step(0.76, sin(vUv.x * 6.2831853 * 36.0)) * smoothstep(0.35, 0.52, radial) * (1.0 - smoothstep(0.56, 0.72, radial));
        vec3 glowCol = vec3(0.15, 0.65, 0.95);
        float alpha = clamp(ring1 * 0.45 + ring2 * 0.28 + ticks * 0.22, 0.0, 0.65);
        gl_FragColor = vec4(glowCol, alpha);
        return;
      }

      vec3 L1 = normalize(vec3(1.8, 2.6, 2.2));
      vec3 L2 = normalize(vec3(-2.2, 1.5, 1.6));
      vec3 L3 = normalize(vec3(0.0, 1.0, -2.5));

      float diff1 = max(dot(N, L1), 0.0);
      float diff2 = max(dot(N, L2), 0.0);
      float diff3 = max(dot(N, L3), 0.0);
      float fresnel = pow(1.0 - max(dot(N, V), 0.0), 3.4);

      vec3 albedo = vCol;
      float shininess = 28.0;
      float specStrength = 0.24;

      if (abs(vMat - 1.0) < 0.3) {
        float innerMask = 1.0 - smoothstep(0.66, 0.74, vUv.y);
        float hex = mix(1.0, hexPattern(vWorldPos.xz), innerMask);
        albedo = mix(albedo * 0.72, albedo * 1.08, hex);
        specStrength = mix(0.12, 0.28, hex);
      }

      if (vMat > 1.8 && vMat < 2.5) {
        shininess = 76.0;
        specStrength = 0.92;
        if (abs(vMat - 2.1) < 0.06) {
          float tread = smoothstep(0.2, 0.7, abs(sin(vUv.x * 6.2831853 * 18.0)));
          albedo = mix(vec3(0.07, 0.12, 0.22), vec3(0.45, 0.80, 1.0), tread * 0.45);
        }
      }

      if (abs(vMat - 3.0) < 0.3) {
        vec3 hc = evalHoneycombGlow(vExtra);
        gl_FragColor = vec4(hc, 1.0);
        return;
      }

      if (abs(vMat - 4.0) < 0.3) {
        vec2 oledUv = vec2(clamp(vUv.y, 0.0, 1.0), clamp(vUv.x, 0.0, 1.0));
        vec4 tex = texture2D(uOledTex, oledUv);
        vec3 H1 = normalize(L1 + V);
        float glassSpec = pow(max(dot(N, H1), 0.0), 110.0) * 0.85;
        vec3 col = vec3(0.012, 0.018, 0.030) + tex.rgb * 1.25 + vec3(0.55, 0.85, 1.0) * (glassSpec + fresnel * 0.18);
        gl_FragColor = vec4(col, 1.0);
        return;
      }

      if (abs(vMat - 5.0) < 0.3) {
        vec4 logo = texture2D(uLogoTex, vec2(vUv.x, vUv.y));
        if (logo.a < 0.08) discard;
        gl_FragColor = vec4(0.95, 0.99, 1.0, logo.a * 0.96);
        return;
      }

      vec3 H1 = normalize(L1 + V);
      vec3 H2 = normalize(L2 + V);
      float spec1 = pow(max(dot(N, H1), 0.0), shininess);
      float spec2 = pow(max(dot(N, H2), 0.0), shininess * 0.7);

      vec3 ambient = albedo * vec3(0.30, 0.35, 0.46);
      vec3 diffuse = albedo * (diff1 * 0.72 + diff2 * 0.38 * vec3(0.80, 0.92, 1.0) + diff3 * 0.24);
      vec3 spec = vec3(0.85, 0.94, 1.0) * (spec1 + spec2 * 0.45) * specStrength;
      vec3 rim = vec3(0.18, 0.56, 0.98) * fresnel * 0.34;

      vec3 color = ambient + diffuse + spec + rim;

      if (uHoverZone > 0.5 && abs(uHoverZone - vExtra) < 0.4) {
        float blink = 0.65 + 0.35 * sin(uTime * 6.0);
        color = mix(color, vec3(0.0, 0.85, 1.0), 0.40 * blink) + vec3(0.0, 0.28, 0.45) * blink;
      }

      gl_FragColor = vec4(color, 1.0);
    }
  `;

  function compileShader(gl, type, src) {
    const sh = gl.createShader(type);
    gl.shaderSource(sh, src);
    gl.compileShader(sh);
    if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) {
      const info = gl.getShaderInfoLog(sh);
      gl.deleteShader(sh);
      throw new Error("WebGL shader error: " + info);
    }
    return sh;
  }

  class M618XSDViewer3D {
    constructor(canvas, overlayEl, onHotspotClick) {
      this.canvas = canvas;
      this.overlayEl = overlayEl;
      this.onHotspotClick = onHotspotClick;

      // yaw=0 is directly behind (+Z); yaw=+0.78 is Right-Rear 3/4 matching Factory Photo 1!
      this.yaw = 0.78;
      this.pitch = 0.26;
      this.distance = 5.10;
      this.targetYaw = this.yaw;
      this.targetPitch = this.pitch;
      this.targetDistance = this.distance;
      this.autoRotate = false;
      this.dragging = false;
      this.lastX = 0;
      this.lastY = 0;
      this.hoverZone = 0;

      this.state = {
        dpi: 1200,
        hz: 250,
        battery: null,
        rgbMode: 8,
        rgbColor: [0.0, 1.0, 0.85],
        rgbBright: 1.0,
        rgbSpeed: 3,
      };

      this.gl = canvas.getContext("webgl", { antialias: true, alpha: true, premultipliedAlpha: false });
      if (!this.gl) return;
      this.gl.getExtension("OES_element_index_uint");

      this._initShaders();
      this._initGeometry();
      this._initTextures();
      this._initHotspots();
      this._bindEvents();

      this._startTime = performance.now();
      this._raf = requestAnimationFrame(() => this._frame());
    }

    _initShaders() {
      const gl = this.gl;
      const vs = compileShader(gl, gl.VERTEX_SHADER, VS_SRC);
      const fs = compileShader(gl, gl.FRAGMENT_SHADER, FS_SRC);
      const prog = gl.createProgram();
      gl.attachShader(prog, vs);
      gl.attachShader(prog, fs);
      gl.linkProgram(prog);
      gl.useProgram(prog);
      this.prog = prog;

      this.attribs = {
        aPos: gl.getAttribLocation(prog, "aPos"),
        aNorm: gl.getAttribLocation(prog, "aNorm"),
        aUv: gl.getAttribLocation(prog, "aUv"),
        aCol: gl.getAttribLocation(prog, "aCol"),
        aMat: gl.getAttribLocation(prog, "aMat"),
        aExtra: gl.getAttribLocation(prog, "aExtra"),
      };
      this.uniforms = {
        uVP: gl.getUniformLocation(prog, "uVP"),
        uCamPos: gl.getUniformLocation(prog, "uCamPos"),
        uTime: gl.getUniformLocation(prog, "uTime"),
        uRgbColor: gl.getUniformLocation(prog, "uRgbColor"),
        uRgbMode: gl.getUniformLocation(prog, "uRgbMode"),
        uRgbBright: gl.getUniformLocation(prog, "uRgbBright"),
        uRgbSpeed: gl.getUniformLocation(prog, "uRgbSpeed"),
        uHoverZone: gl.getUniformLocation(prog, "uHoverZone"),
        uOledTex: gl.getUniformLocation(prog, "uOledTex"),
        uLogoTex: gl.getUniformLocation(prog, "uLogoTex"),
      };
    }

    _initGeometry() {
      const gl = this.gl;
      const geom = buildM618XSDGeometry();
      this.anchors = geom.anchors;
      this.indexCount = geom.indices.length;

      this.vbo = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, this.vbo);
      gl.bufferData(gl.ARRAY_BUFFER, geom.vertices, gl.STATIC_DRAW);

      this.ibo = gl.createBuffer();
      gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, this.ibo);
      gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, geom.indices, gl.STATIC_DRAW);
    }

    _initTextures() {
      const gl = this.gl;
      this.oledCanvas = document.createElement("canvas");
      this.oledCanvas.width = 256;
      this.oledCanvas.height = 96;
      this.oledTex = gl.createTexture();
      gl.bindTexture(gl.TEXTURE_2D, this.oledTex);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
      this._redrawOledTexture();

      const lc = document.createElement("canvas");
      lc.width = 256;
      lc.height = 64;
      const lctx = lc.getContext("2d");
      lctx.clearRect(0, 0, 256, 64);
      lctx.fillStyle = "#ffffff";
      lctx.font = "900 38px 'Inter', 'Noto Sans CJK SC', sans-serif";
      lctx.textAlign = "center";
      lctx.textBaseline = "middle";
      lctx.fillText("DELUX", 128, 34);

      this.logoTex = gl.createTexture();
      gl.bindTexture(gl.TEXTURE_2D, this.logoTex);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, lc);
    }

    _redrawOledTexture() {
      if (!this.gl || !this.oledCanvas) return;
      const ctx = this.oledCanvas.getContext("2d");
      const w = this.oledCanvas.width, h = this.oledCanvas.height;
      ctx.fillStyle = "#02050a";
      ctx.fillRect(0, 0, w, h);

      ctx.strokeStyle = "rgba(0, 200, 255, 0.25)";
      ctx.lineWidth = 2;
      ctx.strokeRect(8, 8, w - 16, h - 16);

      ctx.fillStyle = "#8be9ff";
      ctx.font = "bold 15px 'JetBrains Mono', monospace";
      ctx.fillText("2.4G", 18, 28);

      const hasBat = typeof this.state.battery === "number";
      const bat = hasBat ? clamp(Math.round(this.state.battery), 0, 100) : 100;
      ctx.fillStyle = "#e6faff";
      ctx.fillText(hasBat ? bat + "%" : "SYNC", 150, 28);
      ctx.strokeStyle = "#8be9ff";
      ctx.strokeRect(204, 15, 32, 14);
      ctx.fillStyle = bat > 20 ? "#00e5a3" : "#ff4d6d";
      ctx.fillRect(206, 17, Math.round(28 * (bat / 100)), 10);

      ctx.fillStyle = "#ffffff";
      ctx.font = "900 24px 'JetBrains Mono', monospace";
      ctx.fillText("DPI:" + (this.state.dpi || 1200), 18, 57);

      ctx.fillStyle = "#62d8ff";
      ctx.font = "bold 15px 'JetBrains Mono', monospace";
      ctx.fillText("MODE:2.4G  " + (this.state.hz || 250) + "Hz", 18, 80);

      const gl = this.gl;
      gl.bindTexture(gl.TEXTURE_2D, this.oledTex);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, this.oledCanvas);
    }

    _initHotspots() {
      this.hotspotDefs = [
        { id: "thumb_wheel", zone: 15, title: "左侧拇指滚轮", sub: "标签切换 / 页面缩放", nav: "bindings" },
        { id: "backward", zone: 14, title: "左侧前进 / 后退键", sub: "前后退 / 按住四向手势", nav: "bindings" },
        { id: "oled_dpi", zone: 16, title: "顶部 OLED 与 DPI 键", sub: "400 - 4000 DPI", nav: "dpi" },
        { id: "main_wheel", zone: 17, title: "右侧垂直主滚轮", sub: "左/右键与滚轮中键", nav: "bindings" },
        { id: "honeycomb_rgb", zone: 3, title: "尾部蜂巢背光区", sub: "8 种板载灯光模式", nav: "rgb" },
      ];
      this.hotspotNodes = {};
      if (!this.overlayEl) return;
      this.overlayEl.innerHTML = "";
      for (const h of this.hotspotDefs) {
        const el = document.createElement("button");
        el.type = "button";
        el.className = "hud-hotspot";
        el.innerHTML = `<span class="hs-dot"></span><span class="hs-body"><strong>${h.title}</strong><small>${h.sub}</small></span>`;
        el.addEventListener("mouseenter", () => { this.hoverZone = h.zone; });
        el.addEventListener("mouseleave", () => { this.hoverZone = 0; });
        el.addEventListener("click", (e) => {
          e.stopPropagation();
          if (this.onHotspotClick) this.onHotspotClick(h);
        });
        this.overlayEl.appendChild(el);
        this.hotspotNodes[h.id] = el;
      }
    }

    _bindEvents() {
      const c = this.canvas;
      c.addEventListener("pointerdown", (e) => {
        this.dragging = true;
        this.autoRotate = false;
        this.lastX = e.clientX;
        this.lastY = e.clientY;
        c.setPointerCapture(e.pointerId);
        const autoBtn = document.getElementById("btn-3d-autorotate");
        if (autoBtn) autoBtn.classList.remove("active");
      });
      c.addEventListener("pointermove", (e) => {
        if (!this.dragging) return;
        const dx = e.clientX - this.lastX;
        const dy = e.clientY - this.lastY;
        this.lastX = e.clientX;
        this.lastY = e.clientY;
        this.targetYaw -= dx * 0.009;
        this.targetPitch = clamp(this.targetPitch + dy * 0.007, -0.10, 1.42);
      });
      const stopDrag = () => { this.dragging = false; };
      c.addEventListener("pointerup", stopDrag);
      c.addEventListener("pointercancel", stopDrag);
      c.addEventListener("wheel", (e) => {
        e.preventDefault();
        this.targetDistance = clamp(this.targetDistance + (e.deltaY > 0 ? 0.28 : -0.28), 3.2, 7.2);
      }, { passive: false });
    }

    setCameraPreset(preset) {
      this.autoRotate = false;
      const autoBtn = document.getElementById("btn-3d-autorotate");
      if (autoBtn) autoBtn.classList.remove("active");
      if (preset === "hero") {
        // Matches Factory Photo 1: Right-Rear 3/4 view (+X, +Z) -> Palm rest left-bottom, Honeycomb center-left, DELUX & Main Wheel right!
        this.targetYaw = 0.78;
        this.targetPitch = 0.26;
        this.targetDistance = 5.10;
      } else if (preset === "left") {
        // Matches Factory Photo 2: Left Thumb View (-X, +Z) -> Thumb wheel upper-left, Side buttons lower-left, Honeycomb center, Palm rest right!
        this.targetYaw = -1.02;
        this.targetPitch = 0.22;
        this.targetDistance = 4.95;
      } else if (preset === "top") {
        // Matches Factory Photo 3: Top-Down View -> Nose UP, Side buttons LEFT, Main wheel + DELUX + Palm rest RIGHT!
        this.targetYaw = 0.0;
        this.targetPitch = 1.38;
        this.targetDistance = 5.20;
      } else if (preset === "front") {
        // Right-Front view -> Split L/R primary buttons, vertical main scroll wheel, OLED front!
        this.targetYaw = 2.15;
        this.targetPitch = 0.22;
        this.targetDistance = 4.85;
      }
    }

    toggleAutoRotate() {
      this.autoRotate = !this.autoRotate;
      return this.autoRotate;
    }

    updateTelemetry(next) {
      let needOled = false;
      if (next.dpi !== undefined && next.dpi !== this.state.dpi) {
        this.state.dpi = next.dpi;
        needOled = true;
      }
      if (next.hz !== undefined && next.hz !== this.state.hz) {
        this.state.hz = next.hz;
        needOled = true;
      }
      if (next.battery !== undefined && next.battery !== this.state.battery) {
        this.state.battery = next.battery;
        needOled = true;
      }
      if (next.rgbMode !== undefined) this.state.rgbMode = next.rgbMode;
      if (next.rgbColor !== undefined) this.state.rgbColor = next.rgbColor;
      if (next.rgbBright !== undefined) this.state.rgbBright = next.rgbBright;
      if (next.rgbSpeed !== undefined) this.state.rgbSpeed = next.rgbSpeed;
      if (needOled) this._redrawOledTexture();
    }

    _frame() {
      const gl = this.gl;
      if (!gl) return;

      const dpr = window.devicePixelRatio || 1;
      const cw = Math.max(2, Math.floor(this.canvas.clientWidth * dpr));
      const ch = Math.max(2, Math.floor(this.canvas.clientHeight * dpr));
      if (this.canvas.width !== cw || this.canvas.height !== ch) {
        this.canvas.width = cw;
        this.canvas.height = ch;
      }

      if (this.autoRotate && !this.dragging) {
        this.targetYaw += 0.0045;
      }
      this.yaw += (this.targetYaw - this.yaw) * 0.12;
      this.pitch += (this.targetPitch - this.pitch) * 0.12;
      this.distance += (this.targetDistance - this.distance) * 0.14;

      const target = [0.04, 0.54, 0.16];
      const cp = Math.cos(this.pitch), sp = Math.sin(this.pitch);
      // Spherical orbit where yaw=0 is directly behind (+Z), yaw=+pi/2 is right (+X), yaw=-pi/2 is left (-X)
      const eye = [
        target[0] + this.distance * cp * Math.sin(this.yaw),
        target[1] + this.distance * sp,
        target[2] + this.distance * cp * Math.cos(this.yaw),
      ];

      const proj = Mat4.perspective((38 * Math.PI) / 180, cw / ch, 0.1, 25.0);
      const view = Mat4.lookAt(eye, target, [0, 1, 0]);
      const vp = Mat4.mul(proj, view);

      gl.viewport(0, 0, cw, ch);
      gl.clearColor(0, 0, 0, 0);
      gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
      gl.enable(gl.DEPTH_TEST);
      gl.enable(gl.BLEND);
      gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);

      gl.useProgram(this.prog);
      const stride = 13 * 4;
      gl.bindBuffer(gl.ARRAY_BUFFER, this.vbo);
      gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, this.ibo);

      const enableAttr = (loc, size, offsetFloats) => {
        if (loc < 0) return;
        gl.enableVertexAttribArray(loc);
        gl.vertexAttribPointer(loc, size, gl.FLOAT, false, stride, offsetFloats * 4);
      };
      enableAttr(this.attribs.aPos, 3, 0);
      enableAttr(this.attribs.aNorm, 3, 3);
      enableAttr(this.attribs.aUv, 2, 6);
      enableAttr(this.attribs.aCol, 3, 8);
      enableAttr(this.attribs.aMat, 1, 11);
      enableAttr(this.attribs.aExtra, 1, 12);

      const elapsed = (performance.now() - this._startTime) * 0.001;
      gl.uniformMatrix4fv(this.uniforms.uVP, false, vp);
      gl.uniform3fv(this.uniforms.uCamPos, eye);
      gl.uniform1f(this.uniforms.uTime, elapsed);
      gl.uniform3fv(this.uniforms.uRgbColor, this.state.rgbColor);
      gl.uniform1f(this.uniforms.uRgbMode, this.state.rgbMode);
      gl.uniform1f(this.uniforms.uRgbBright, this.state.rgbBright);
      gl.uniform1f(this.uniforms.uRgbSpeed, this.state.rgbSpeed);
      gl.uniform1f(this.uniforms.uHoverZone, this.hoverZone);

      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D, this.oledTex);
      gl.uniform1i(this.uniforms.uOledTex, 0);

      gl.activeTexture(gl.TEXTURE1);
      gl.bindTexture(gl.TEXTURE_2D, this.logoTex);
      gl.uniform1i(this.uniforms.uLogoTex, 1);

      gl.drawElements(gl.TRIANGLES, this.indexCount, gl.UNSIGNED_INT, 0);

      const cssW = this.canvas.clientWidth;
      const cssH = this.canvas.clientHeight;
      if (cssW > 10 && cssH > 10) {
        const vis = [];
        for (const h of this.hotspotDefs) {
          const el = this.hotspotNodes[h.id];
          const anc = this.anchors[h.id];
          if (!el || !anc) continue;
          const pt = anc.p;
          const nm = anc.n;
          const vx = eye[0] - pt[0], vy = eye[1] - pt[1], vz = eye[2] - pt[2];
          const vl = Math.hypot(vx, vy, vz) || 1;
          const facing = (nm[0] * vx + nm[1] * vy + nm[2] * vz) / vl;
          const scr = Mat4.project(vp, pt, cssW, cssH);
          if (!scr || facing < 0.08 || scr.x < 24 || scr.x > cssW - 155 || scr.y < 48 || scr.y > cssH - 56) {
            el.style.opacity = "0";
            el.style.pointerEvents = "none";
          } else {
            vis.push({ el, x: scr.x, y: scr.y, op: clamp((facing + 0.02) * 2.4, 0.55, 1.0) });
          }
        }
        vis.sort((a, b) => a.y - b.y);
        for (let i = 1; i < vis.length; i++) {
          if (Math.abs(vis[i].x - vis[i - 1].x) < 155 && vis[i].y - vis[i - 1].y < 44) {
            vis[i].y = Math.min(cssH - 54, vis[i - 1].y + 44);
          }
        }
        for (const v of vis) {
          v.el.style.transform = `translate3d(${Math.round(v.x)}px, ${Math.round(v.y)}px, 0)`;
          v.el.style.opacity = String(v.op);
          v.el.style.pointerEvents = "auto";
        }
      }

      this._raf = requestAnimationFrame(() => this._frame());
    }
  }

  window.M618XSDViewer3D = M618XSDViewer3D;
})();
