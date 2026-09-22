import { useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import * as THREE from 'three';
import { RoundedBoxGeometry } from 'three/addons/geometries/RoundedBoxGeometry.js';
import { useMotionAllowed } from '../lib/motion-prefs';

/* The hero's 3D scene: a container number as eleven physical tiles.
 *
 * It shows the product's one claim, once. The recogniser's "9" sits face-up in
 * position 7; the tile turns over and "5" is written, because only 5 agrees
 * with the check digit the speaker read out, which sits at the end in the
 * accent colour -- locked, computed, not heard. The flip plays one way only:
 * running it backwards would show the microphone overruling the format, the
 * claim inverted.
 *
 * Under reduced motion the scene is drawn once, already repaired, and nothing
 * moves. If WebGL is unavailable the caller's `fallback` renders instead, so
 * the page never shows an empty box where the argument should be.
 */

export interface ContainerSceneProps {
  /** The identifier as written, e.g. "CSQU3054383". */
  written: string;
  /** 0-based position of the repaired character. */
  repairIndex: number;
  /** What the recogniser heard at that position. */
  heard: string;
  /** 0-based positions of computed check characters. */
  checkPositions: readonly number[];
  /** Spoken description for screen readers. */
  label: string;
  fallback: ReactNode;
}

const TILE = 0.9;
const GAP = 0.14;
const DEPTH = 0.34;

function cssVar(name: string, fallback: string): string {
  try {
    const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return value || fallback;
  } catch {
    return fallback;
  }
}

/** One glyph on a transparent square, sized for a tile face. */
function glyphTexture(char: string, color: string, font: string): THREE.CanvasTexture {
  const size = 256;
  const canvas = document.createElement('canvas');
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext('2d');
  if (ctx) {
    ctx.clearRect(0, 0, size, size);
    ctx.fillStyle = color;
    ctx.font = `600 150px ${font}`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(char, size / 2, size / 2 + 8);
  }
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.anisotropy = 4;
  return texture;
}

const easeInOut = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2);

export default function ContainerScene({
  written,
  repairIndex,
  heard,
  checkPositions,
  label,
  fallback,
}: ContainerSceneProps) {
  const host = useRef<HTMLDivElement>(null);
  const moving = useMotionAllowed();
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const el = host.current;
    if (!el) return;

    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: 'low-power' });
    } catch {
      setFailed(true);
      return;
    }

    const ink = cssVar('--text', '#1d1d1f');
    const faint = cssVar('--text-4', '#aeaeb2');
    const accent = cssVar('--accent-text', '#0066cc');
    const mono = cssVar('--font-mono', 'ui-monospace, monospace');

    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.domElement.setAttribute('aria-hidden', 'true');
    el.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(30, 1, 0.1, 100);
    camera.position.set(0, 0.2, 13);

    scene.add(new THREE.HemisphereLight(0xffffff, 0xdfe3ea, 2.2));
    const key = new THREE.DirectionalLight(0xffffff, 1.6);
    key.position.set(3, 5, 8);
    scene.add(key);

    const group = new THREE.Group();
    group.rotation.set(0.14, -0.3, 0.02);
    scene.add(group);

    const disposables: { dispose: () => void }[] = [];
    const body = new RoundedBoxGeometry(TILE, TILE * 1.3, DEPTH, 4, 0.12);
    const face = new THREE.PlaneGeometry(TILE * 0.9, TILE * 0.9);
    disposables.push(body, face);

    const tileMat = new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.55, metalness: 0 });
    const checkMat = new THREE.MeshStandardMaterial({ color: 0xe6effb, roughness: 0.5, metalness: 0 });
    disposables.push(tileMat, checkMat);

    const faceMat = (char: string, color: string) => {
      const map = glyphTexture(char, color, mono);
      const mat = new THREE.MeshBasicMaterial({ map, transparent: true });
      disposables.push(map, mat);
      return mat;
    };

    const tiles: { mesh: THREE.Group; phase: number }[] = [];
    const count = written.length;
    const width = count * TILE + (count - 1) * GAP;
    let repairTile: THREE.Group | null = null;

    [...written].forEach((char, i) => {
      const isCheck = checkPositions.includes(i);
      const tile = new THREE.Group();
      tile.add(new THREE.Mesh(body, isCheck ? checkMat : tileMat));

      const front = new THREE.Mesh(
        face,
        faceMat(i === repairIndex ? heard : char, i === repairIndex ? faint : isCheck ? accent : ink),
      );
      front.position.z = DEPTH / 2 + 0.002;
      tile.add(front);

      if (i === repairIndex) {
        // The written character waits on the back; the flip turns it up.
        const back = new THREE.Mesh(face, faceMat(char, ink));
        back.position.z = -(DEPTH / 2 + 0.002);
        back.rotation.x = Math.PI;
        tile.add(back);
        repairTile = tile;
      }

      tile.position.x = -width / 2 + TILE / 2 + i * (TILE + GAP);
      group.add(tile);
      tiles.push({ mesh: tile, phase: i * 0.55 });
    });

    const resize = () => {
      const w = el.clientWidth || 1;
      const h = el.clientHeight || 1;
      renderer.setSize(w, h, false);
      camera.aspect = w / h;
      // Fit the row by what the camera actually sees. The group is turned, so
      // the near end projects larger than the far one and a flat-width fit
      // clipped the check digit -- the one tile the scene is about. Project
      // the row's bounding corners and move the camera until the widest one
      // sits inside the frame with a margin.
      const vFov = (camera.fov * Math.PI) / 180;
      const hFov = 2 * Math.atan(Math.tan(vFov / 2) * camera.aspect);
      camera.position.z = Math.max(6, (width * 1.1) / 2 / Math.tan(hFov / 2));
      const box = new THREE.Box3().setFromObject(group);
      const corners = [0, 1, 2, 3, 4, 5, 6, 7].map(
        (k) =>
          new THREE.Vector3(
            k & 1 ? box.max.x : box.min.x,
            k & 2 ? box.max.y : box.min.y,
            k & 4 ? box.max.z : box.min.z,
          ),
      );
      for (let step = 0; step < 40; step += 1) {
        camera.updateProjectionMatrix();
        camera.updateMatrixWorld();
        const reach = Math.max(
          ...corners.map((c) => {
            const p = c.clone().project(camera);
            return Math.max(Math.abs(p.x), Math.abs(p.y) * 0.6);
          }),
        );
        if (reach > 0.94) camera.position.z *= 1.04;
        else if (reach < 0.86) camera.position.z *= 0.97;
        else break;
      }
      camera.updateProjectionMatrix();
      renderer.render(scene, camera);
    };

    const flipStart = performance.now() + 1100;
    const flipMs = 900;
    const pointer = { x: 0, y: 0 };
    let visible = true;
    let frame = 0;

    if (!moving && repairTile) {
      (repairTile as THREE.Group).rotation.x = Math.PI;
    }

    const tick = (now: number) => {
      frame = requestAnimationFrame(tick);
      if (!visible) return;
      const seconds = now / 1000;
      tiles.forEach(({ mesh, phase }) => {
        mesh.position.y = Math.sin(seconds * 1.1 + phase) * 0.06;
      });
      if (repairTile) {
        const p = Math.min(1, Math.max(0, (now - flipStart) / flipMs));
        const e = easeInOut(p);
        const tile = repairTile as THREE.Group;
        tile.rotation.x = e * Math.PI;
        tile.position.z = Math.sin(e * Math.PI) * 0.6;
      }
      group.rotation.y += (-0.3 + pointer.x * 0.12 - group.rotation.y) * 0.05;
      group.rotation.x += (0.14 + pointer.y * 0.06 - group.rotation.x) * 0.05;
      renderer.render(scene, camera);
    };

    const onPointer = (event: PointerEvent) => {
      const rect = el.getBoundingClientRect();
      pointer.x = ((event.clientX - rect.left) / rect.width - 0.5) * 2;
      pointer.y = ((event.clientY - rect.top) / rect.height - 0.5) * 2;
    };

    const observer = new ResizeObserver(resize);
    observer.observe(el);
    const seen = new IntersectionObserver(([entry]) => {
      visible = entry?.isIntersecting ?? true;
    });
    seen.observe(el);

    // Glyph textures are drawn with the page's mono face; wait for it so the
    // tiles are not drawn in a fallback font and never corrected.
    let cancelled = false;
    void (document.fonts?.ready ?? Promise.resolve()).then(() => {
      if (cancelled) return;
      resize();
      if (moving) {
        window.addEventListener('pointermove', onPointer, { passive: true });
        frame = requestAnimationFrame(tick);
      }
    });

    return () => {
      cancelled = true;
      cancelAnimationFrame(frame);
      window.removeEventListener('pointermove', onPointer);
      observer.disconnect();
      seen.disconnect();
      disposables.forEach((d) => d.dispose());
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, [written, repairIndex, heard, checkPositions, moving]);

  if (failed) return <>{fallback}</>;
  return <div ref={host} className="scene" role="img" aria-label={label} />;
}
