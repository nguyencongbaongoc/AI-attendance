import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

import re
from pathlib import Path

INDEX_PATH = Path("frontend/index.html")

def apply_patches():
    content = INDEX_PATH.read_text(encoding="utf-8")
    
    # Backup
    backup_path = Path("frontend/index.html.bak")
    backup_path.write_text(content, encoding="utf-8")
    print(f"Created backup at {backup_path}")

    # 1. Tab 1 Dashboard: Wire "Xuat bao cao" button
    old_btn = '<button class="px-3 py-2 rounded-full border border-zinc-800 text-[13px] font-medium hover:bg-zinc-900">Xuất báo cáo</button>'
    new_btn = '<button onclick="exportExcel()" class="px-3 py-2 rounded-full border border-zinc-800 text-[13px] font-medium hover:bg-zinc-900">Xuất báo cáo</button>'
    if old_btn in content:
        content = content.replace(old_btn, new_btn, 1)
        print("✓ Patched Tab 1: Xuat bao cao button")
    else:
        print("Note: Tab 1 Xuat bao cao already patched or not matched")

    # 2. Tab 3 ArcFace: Add Reload Embeddings button in header
    old_npy_header = """          <div class="flex items-center justify-between">
            <span class="text-[11px] tracking-[0.12em] font-semibold">DANH SÁCH EMBEDDING ĐÃ TẠO</span>
            <span class="text-[11px] font-mono px-2 py-1 rounded-full bg-white text-black font-bold">12 files</span>
          </div>"""
    new_npy_header = """          <div class="flex items-center justify-between">
            <span class="text-[11px] tracking-[0.12em] font-semibold">DANH SÁCH EMBEDDING ĐÃ TẠO</span>
            <div class="flex items-center gap-2">
              <button id="btnReloadGallery" onclick="reloadGalleryEmbeddings()" class="px-2.5 py-1 rounded-full border border-zinc-700 text-[11px] font-mono hover:bg-zinc-800 flex items-center gap-1">⟳ Reload Embeddings</button>
              <span id="galleryCountBadge" class="text-[11px] font-mono px-2 py-1 rounded-full bg-white text-black font-bold">12 files</span>
            </div>
          </div>"""
    if old_npy_header in content:
        content = content.replace(old_npy_header, new_npy_header, 1)
        print("✓ Patched Tab 3: Reload Embeddings button added")
    
    # Tab 3 ArcFace: Wire "Loc" button
    old_loc_btn = '<button class="px-3 py-2 rounded-full border border-zinc-800 text-[12px] font-medium">Lọc</button>'
    new_loc_btn = '<button onclick="filterNpyList()" class="px-3 py-2 rounded-full border border-zinc-800 text-[12px] font-medium hover:bg-zinc-800">Lọc</button>'
    if old_loc_btn in content:
        content = content.replace(old_loc_btn, new_loc_btn, 1)
        print("✓ Patched Tab 3: Loc button wired")

    # 3. Tab 8 Student Roster: Wire buttons in header
    old_roster_hdr = """          <button id="btnImportExcel" class="px-4 py-2 rounded-full bg-white text-black text-[13px] font-semibold flex items-center gap-1.5 hover:bg-zinc-200 transition">⤓ Nhập Excel</button>
          <button id="btnExportStudents" class="px-4 py-2 rounded-full border border-zinc-700 text-[13px] font-medium hover:bg-zinc-900">Xuất danh sách</button>"""
    new_roster_hdr = """          <button id="btnImportExcel" onclick="openImportModal()" class="px-4 py-2 rounded-full bg-white text-black text-[13px] font-semibold flex items-center gap-1.5 hover:bg-zinc-200 transition">⤓ Nhập Excel</button>
          <button id="btnExportStudents" onclick="exportTableToCSV('danh_sach_hoc_sinh.csv')" class="px-4 py-2 rounded-full border border-zinc-700 text-[13px] font-medium hover:bg-zinc-900">Xuất danh sách</button>
          <button onclick="openAddStudentModal()" class="px-3.5 py-2 rounded-full border border-zinc-700 text-[13px] font-medium hover:bg-zinc-900 flex items-center gap-1.5">＋ Thêm học sinh</button>"""
    if old_roster_hdr in content:
        content = content.replace(old_roster_hdr, new_roster_hdr, 1)
        print("✓ Patched Tab 8: Header buttons (Import, Export, + Them hoc sinh)")

    # 4. Replace lines 2076-2178 (Canvas Line Drawing & Editing logic)
    # Search for start and end markers
    drawing_start_marker = "// canvas line drawing"
    drawing_end_marker = "// ============================================================\n// BACKEND INTEGRATION - Real API Connections"
    
    start_idx = content.find(drawing_start_marker)
    end_idx = content.find(drawing_end_marker)
    
    if start_idx != -1 and end_idx != -1:
        new_drawing_code = """// canvas line drawing & editing
let isDrawing = false, isDraggingHandle = false, dragTarget = null, start = { x: 0, y: 0 };
let lines1 = [], lines2 = [];
let activeCam = 'cam1';
let drawMode = false, editMode = false;

function getCanvasPos(e, canvas) {
  const rect = canvas.getBoundingClientRect();
  const clientX = e.touches ? e.touches[0].clientX : e.clientX;
  const clientY = e.touches ? e.touches[0].clientY : e.clientY;
  return {
    x: clientX - rect.left,
    y: clientY - rect.top,
    w: rect.width,
    h: rect.height
  };
}

function resizeCanvases() {
  ['canvas1', 'canvas2'].forEach(id => {
    const c = document.getElementById(id);
    if (!c) return;
    const r = c.getBoundingClientRect();
    if (r.width > 0 && r.height > 0) {
      c.width = r.width * window.devicePixelRatio;
      c.height = r.height * window.devicePixelRatio;
      const ctx = c.getContext('2d');
      ctx.setTransform(window.devicePixelRatio, 0, 0, window.devicePixelRatio, 0, 0);
    }
  });
  drawAll();
}

function drawSavedCrossingLine(camId) {
  const idStr = String(camId || 'cam1').toLowerCase();
  const isCam2 = idStr.includes('2');
  const canvas = document.getElementById(isCam2 ? 'canvas2' : 'canvas1');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const lines = isCam2 ? lines2 : lines1;
  const rect = canvas.getBoundingClientRect();
  if (rect.width <= 0 || rect.height <= 0) return;

  lines.forEach((l) => {
    const isActive = (isCam2 ? activeCam === 'cam2' : activeCam === 'cam1');
    ctx.save();
    
    // Drop shadow / contrast edge
    ctx.strokeStyle = 'rgba(0,0,0,0.85)';
    ctx.lineWidth = 4;
    ctx.setLineDash([]);
    ctx.beginPath();
    ctx.moveTo(l.x1, l.y1);
    ctx.lineTo(l.x2, l.y2);
    ctx.stroke();

    // High visibility crossing line
    ctx.strokeStyle = isActive ? '#ffffff' : 'rgba(255,255,255,0.85)';
    ctx.lineWidth = 2.2;
    ctx.beginPath();
    ctx.moveTo(l.x1, l.y1);
    ctx.lineTo(l.x2, l.y2);
    ctx.stroke();

    // Endpoints
    const handleRadius = (editMode && isActive) ? 7 : 5;
    ctx.fillStyle = '#ffffff';
    ctx.strokeStyle = '#000000';
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.arc(l.x1, l.y1, handleRadius, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();

    ctx.beginPath();
    ctx.arc(l.x2, l.y2, handleRadius, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();

    // Midpoint label badge
    const mx = (l.x1 + l.x2) / 2;
    const my = (l.y1 + l.y2) / 2 - 10;
    const label = 'LINE IN→OUT';
    ctx.font = '700 11px JetBrains Mono, monospace';
    const tw = ctx.measureText(label).width;
    const badgeW = tw + 12;
    const badgeH = 18;

    ctx.fillStyle = 'rgba(0,0,0,0.85)';
    ctx.strokeStyle = 'rgba(255,255,255,0.4)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    if (ctx.roundRect) {
      ctx.roundRect(mx - badgeW / 2, my - badgeH / 2, badgeW, badgeH, 4);
    } else {
      ctx.rect(mx - badgeW / 2, my - badgeH / 2, badgeW, badgeH);
    }
    ctx.fill();
    ctx.stroke();

    ctx.fillStyle = '#ffffff';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(label, mx, my);

    if (editMode && isActive) {
      ctx.fillStyle = '#00ffff';
      ctx.beginPath();
      ctx.arc(l.x1, l.y1, 2.5, 0, Math.PI * 2);
      ctx.arc(l.x2, l.y2, 2.5, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.restore();
  });
}
window.drawSavedCrossingLine = drawSavedCrossingLine;

function drawAll() {
  ['cam1', 'cam2'].forEach(cid => {
    const c = document.getElementById(cid === 'cam1' ? 'canvas1' : 'canvas2');
    if (!c) return;
    const ctx = c.getContext('2d');
    const r = c.getBoundingClientRect();
    ctx.clearRect(0, 0, r.width, r.height);
    drawSavedCrossingLine(cid);
  });
}

function updateLineToolButtons() {
  const btnDraw = document.getElementById('btnDraw');
  const btnEdit = document.getElementById('btnEdit');
  
  if (btnDraw) {
    btnDraw.className = drawMode
      ? 'px-3 py-1.5 rounded-full bg-white text-black text-[12px] font-semibold flex items-center gap-1.5 shadow-md'
      : 'px-3 py-1.5 rounded-full border border-zinc-700 text-[12px] font-medium hover:bg-zinc-800 flex items-center gap-1.5 text-zinc-300';
  }
  if (btnEdit) {
    btnEdit.className = editMode
      ? 'px-3 py-1.5 rounded-full bg-white text-black text-[12px] font-semibold flex items-center gap-1.5 shadow-md'
      : 'px-3 py-1.5 rounded-full border border-zinc-700 text-[12px] font-medium hover:bg-zinc-800 flex items-center gap-1.5 text-zinc-300';
  }

  ['canvas1', 'canvas2'].forEach(id => {
    const c = document.getElementById(id);
    if (c) {
      c.style.pointerEvents = 'auto';
      c.style.cursor = drawMode ? 'crosshair' : (editMode ? 'grab' : 'crosshair');
    }
  });
}

window.toggleDraw = function() {
  drawMode = !drawMode;
  if (drawMode) editMode = false;
  updateLineToolButtons();
  showToast(drawMode ? 'Chế độ Vẽ Line: Kéo chuột trên video để tạo line mới' : 'Đã tắt chế độ vẽ', 'info');
};

window.toggleEdit = function() {
  editMode = !editMode;
  if (editMode) drawMode = false;
  updateLineToolButtons();
  drawAll();
  showToast(editMode ? 'Chế độ Kéo / Sửa: Kéo 2 đầu mút hoặc thân line để chỉnh sửa' : 'Đã tắt chế độ sửa', 'info');
};

window.deleteLine = function() {
  const lines = activeCam === 'cam1' ? lines1 : lines2;
  if (lines.length > 0) {
    lines.pop();
    drawAll();
    updateGeometryDisplay(false);
    showToast(`Đã xóa line trên ${activeCam.toUpperCase()}`, 'info');
  } else {
    showToast(`Không có line nào trên ${activeCam.toUpperCase()} để xóa`, 'warning');
  }
};

window.clearLines = function() {
  ['canvas1', 'canvas2'].forEach(id => {
    const c = document.getElementById(id);
    const r = c.getBoundingClientRect();
    const is1 = id === 'canvas1';
    const lines = is1 ? lines1 : lines2;
    lines.length = 0;
    lines.push({
      x1: (r.width || 640) * 0.15,
      y1: (r.height || 360) * 0.75,
      x2: (r.width || 640) * 0.85,
      y2: (r.height || 360) * 0.75
    });
  });
  drawAll();
  updateGeometryDisplay(false);
  showToast('Đã reset line về vị trí chuẩn', 'info');
};

function updateGeometryDisplay(isSaved = false) {
  const pre = document.querySelector('#page-live pre');
  if (!pre) return;
  const lines = activeCam === 'cam1' ? lines1 : lines2;
  const canvas = document.getElementById(activeCam === 'cam1' ? 'canvas1' : 'canvas2');
  if (lines.length > 0 && canvas) {
    const rect = canvas.getBoundingClientRect();
    const l = lines[lines.length - 1];
    const nx1 = Number((l.x1 / rect.width).toFixed(3));
    const ny1 = Number((l.y1 / rect.height).toFixed(3));
    const nx2 = Number((l.x2 / rect.width).toFixed(3));
    const ny2 = Number((l.y2 / rect.height).toFixed(3));
    const px1 = Math.round(nx1 * 3840);
    const py1 = Math.round(ny1 * 2160);
    const px2 = Math.round(nx2 * 3840);
    const py2 = Math.round(ny2 * 2160);
    pre.textContent = JSON.stringify({
      cam_id: activeCam,
      normalized_line: [[nx1, ny1], [nx2, ny2]],
      pixel_line: [[px1, py1], [px2, py2]],
      direction: "IN->OUT",
      saved: !!isSaved
    }, null, 2);
  } else {
    pre.textContent = JSON.stringify({
      cam_id: activeCam,
      line: "Chưa thiết lập",
      direction: "IN->OUT",
      saved: false
    }, null, 2);
  }
}
window.updateGeometryDisplay = updateGeometryDisplay;

window.saveLines = async function() {
  try {
    const saves = [];
    let count = 0;
    for (const cid of ['cam1', 'cam2']) {
      const lines = cid === 'cam1' ? lines1 : lines2;
      const canvas = document.getElementById(cid === 'cam1' ? 'canvas1' : 'canvas2');
      if (lines.length > 0 && canvas) {
        const rect = canvas.getBoundingClientRect();
        const l = lines[lines.length - 1];
        const nx1 = Number((l.x1 / rect.width).toFixed(4));
        const ny1 = Number((l.y1 / rect.height).toFixed(4));
        const nx2 = Number((l.x2 / rect.width).toFixed(4));
        const ny2 = Number((l.y2 / rect.height).toFixed(4));
        const payload = {
          cam_id: cid,
          line: [[nx1, ny1], [nx2, ny2]],
          direction: "IN->OUT"
        };
        saves.push(api.post(`/api/v1/cameras/${cid}/line`, payload));
        count++;
      }
    }
    if (count === 0) {
      showToast('Chưa có line nào để lưu', 'warning');
      return;
    }
    await Promise.all(saves);
    updateGeometryDisplay(true);
    showToast('✓ Đã lưu line vào backend (đồng bộ real-time)', 'success');
  } catch (err) {
    console.error('Failed to save lines:', err);
    showToast(`Lỗi lưu line: ${err.message}`, 'error');
  }
};

function setupCanvas(id, linesRef) {
  const c = document.getElementById(id);
  if (!c) return;
  c.style.pointerEvents = 'auto';

  function distToPoint(px, py, x, y) {
    return Math.hypot(px - x, py - y);
  }

  function distToSegment(px, py, x1, y1, x2, y2) {
    const l2 = Math.hypot(x2 - x1, y2 - y1) ** 2;
    if (l2 === 0) return Math.hypot(px - x1, py - y1);
    let t = ((px - x1) * (x2 - x1) + (py - y1) * (y2 - y1)) / l2;
    t = Math.max(0, Math.min(1, t));
    return Math.hypot(px - (x1 + t * (x2 - x1)), py - (y1 + t * (y2 - y1)));
  }

  c.addEventListener('mousedown', e => {
    const p = getCanvasPos(e, c);
    activeCam = id === 'canvas1' ? 'cam1' : 'cam2';

    if (editMode && linesRef.length > 0) {
      const l = linesRef[linesRef.length - 1];
      if (distToPoint(p.x, p.y, l.x1, l.y1) < 18) {
        dragTarget = { handle: 'p1', line: l };
        isDraggingHandle = true;
        return;
      }
      if (distToPoint(p.x, p.y, l.x2, l.y2) < 18) {
        dragTarget = { handle: 'p2', line: l };
        isDraggingHandle = true;
        return;
      }
      if (distToSegment(p.x, p.y, l.x1, l.y1, l.x2, l.y2) < 15) {
        dragTarget = {
          handle: 'body',
          line: l,
          startX: p.x,
          startY: p.y,
          origX1: l.x1,
          origY1: l.y1,
          origX2: l.x2,
          origY2: l.y2
        };
        isDraggingHandle = true;
        return;
      }
    }

    isDrawing = true;
    start = { x: p.x, y: p.y };
    const hint = document.getElementById(id === 'canvas1' ? 'drawHint1' : 'drawHint2');
    if (hint) hint.classList.remove('hidden');
  });

  c.addEventListener('mousemove', e => {
    const p = getCanvasPos(e, c);

    if (isDraggingHandle && dragTarget) {
      if (dragTarget.handle === 'p1') {
        dragTarget.line.x1 = p.x;
        dragTarget.line.y1 = p.y;
      } else if (dragTarget.handle === 'p2') {
        dragTarget.line.x2 = p.x;
        dragTarget.line.y2 = p.y;
      } else if (dragTarget.handle === 'body') {
        const dx = p.x - dragTarget.startX;
        const dy = p.y - dragTarget.startY;
        dragTarget.line.x1 = dragTarget.origX1 + dx;
        dragTarget.line.y1 = dragTarget.origY1 + dy;
        dragTarget.line.x2 = dragTarget.origX2 + dx;
        dragTarget.line.y2 = dragTarget.origY2 + dy;
      }
      drawAll();
      updateGeometryDisplay(false);
      return;
    }

    if (editMode && linesRef.length > 0 && !isDrawing) {
      const l = linesRef[linesRef.length - 1];
      if (distToPoint(p.x, p.y, l.x1, l.y1) < 18 || distToPoint(p.x, p.y, l.x2, l.y2) < 18) {
        c.style.cursor = 'pointer';
      } else if (distToSegment(p.x, p.y, l.x1, l.y1, l.x2, l.y2) < 15) {
        c.style.cursor = 'move';
      } else {
        c.style.cursor = 'grab';
      }
    }

    if (isDrawing) {
      drawAll();
      const ctx = c.getContext('2d');
      ctx.save();
      ctx.strokeStyle = '#00ffff';
      ctx.lineWidth = 2;
      ctx.setLineDash([5, 4]);
      ctx.beginPath();
      ctx.moveTo(start.x, start.y);
      ctx.lineTo(p.x, p.y);
      ctx.stroke();
      ctx.restore();
    }
  });

  const endAction = (e) => {
    if (isDraggingHandle) {
      isDraggingHandle = false;
      dragTarget = null;
      drawAll();
      updateGeometryDisplay(false);
    }
    if (isDrawing) {
      isDrawing = false;
      const hint1 = document.getElementById('drawHint1');
      const hint2 = document.getElementById('drawHint2');
      if (hint1) hint1.classList.add('hidden');
      if (hint2) hint2.classList.add('hidden');

      const p = getCanvasPos(e, c);
      const dx = Math.hypot(p.x - start.x, p.y - start.y);
      if (dx >= 15) {
        linesRef.length = 0;
        linesRef.push({ x1: start.x, y1: start.y, x2: p.x, y2: p.y });
        drawAll();
        updateGeometryDisplay(false);
        showToast(`Đã vẽ line mới cho ${activeCam.toUpperCase()}`, 'success');
      } else {
        drawAll();
      }
    }
  };

  c.addEventListener('mouseup', endAction);
  c.addEventListener('mouseleave', () => {
    if (isDrawing || isDraggingHandle) endAction({ clientX: start.x, clientY: start.y });
  });
  c.addEventListener('touchend', endAction);
  c.addEventListener('touchmove', (e) => {
    if (isDrawing || isDraggingHandle) e.preventDefault();
  }, { passive: false });
}

setupCanvas('canvas1', lines1);
setupCanvas('canvas2', lines2);

"""
        content = content[:start_idx] + new_drawing_code + content[end_idx:]
        print("✓ Patched Canvas Line Drawing & Editing logic (lines ~2076-2178)")
    else:
        print("ERROR: Markers for drawing code not found!")

    # 5. Patch loadGeometryConfigs & applyGeometryToCanvas
    old_geom_load = """async function loadGeometryConfigs() {
  appState.loading.geometry = true;
  try {
    const [cam1Config, cam2Config] = await Promise.all([
      api.get(`${API_CONFIG.endpoints.geometry}/CAM1`),
      api.get(`${API_CONFIG.endpoints.geometry}/CAM2`)
    ]);
    appState.geometryConfigs.CAM1 = cam1Config;
    appState.geometryConfigs.CAM2 = cam2Config;
    
    // Apply loaded lines to canvas
    applyGeometryToCanvas('CAM1', 'canvas1', lines1);
    applyGeometryToCanvas('CAM2', 'canvas2', lines2);
    
    updateGeometryDisplay();
  } catch (error) {
    console.warn('Failed to load geometry configs:', error);
    // Use defaults from config files
    applyDefaultGeometry();
  } finally {
    appState.loading.geometry = false;
  }
}

function applyGeometryToCanvas(cameraId, canvasId, linesArray) {
  const config = appState.geometryConfigs[cameraId];
  if (config && config.line) {
    const canvas = document.getElementById(canvasId);
    const rect = canvas.getBoundingClientRect();
    // Convert from original_frame coordinates (3840x2160) to canvas coordinates
    const scaleX = rect.width / 3840;
    const scaleY = rect.height / 2160;
    
    linesArray.length = 0;
    linesArray.push({
      x1: config.line.p1.x * scaleX,
      y1: config.line.p1.y * scaleY,
      x2: config.line.p2.x * scaleX,
      y2: config.line.p2.y * scaleY
    });
  }
}

function applyDefaultGeometry() {
  // Default vertical center lines from config files
  setTimeout(() => {
    const c1 = document.getElementById('canvas1'), r1 = c1.getBoundingClientRect();
    lines1.push({x1: r1.width * 0.5, y1: 0, x2: r1.width * 0.5, y2: r1.height});
    const c2 = document.getElementById('canvas2'), r2 = c2.getBoundingClientRect();
    lines2.push({x1: r2.width * 0.5, y1: 0, x2: r2.width * 0.5, y2: r2.height});
    resizeCanvases();
    updateGeometryDisplay();
  }, 120);
}

function updateGeometryDisplay() {
  const pre = document.querySelector('#page-live pre');
  if (pre && appState.geometryConfigs.CAM1) {
    const config = appState.geometryConfigs.CAM1;
    pre.textContent = JSON.stringify({
      cam_id: config.camera_id,
      line: [[config.line.p1.x, config.line.p1.y], [config.line.p2.x, config.line.p2.y]],
      direction: config.line.direction_semantics,
      saved: true
    }, null, 2);
  }
}"""

    new_geom_load = """async function loadGeometryConfigs() {
  appState.loading.geometry = true;
  try {
    const [cam1Config, cam2Config] = await Promise.all([
      api.get(`/api/v1/cameras/cam1/line`),
      api.get(`/api/v1/cameras/cam2/line`)
    ]);
    appState.geometryConfigs.cam1 = cam1Config;
    appState.geometryConfigs.cam2 = cam2Config;
    
    applyGeometryToCanvas('cam1', 'canvas1', lines1);
    applyGeometryToCanvas('cam2', 'canvas2', lines2);
    
    updateGeometryDisplay(true);
  } catch (error) {
    console.warn('Failed to load geometry configs from /api/v1/cameras:', error);
    applyDefaultGeometry();
  } finally {
    appState.loading.geometry = false;
  }
}

function applyGeometryToCanvas(cameraId, canvasId, linesArray) {
  const normId = String(cameraId || 'cam1').toLowerCase();
  const config = appState.geometryConfigs[normId] || appState.geometryConfigs[normId.toUpperCase()];
  if (!config) return;
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  const rect = canvas.getBoundingClientRect();
  if (rect.width <= 0 || rect.height <= 0) return;
  
  linesArray.length = 0;
  if (config.normalized_line && config.normalized_line.length === 2) {
    linesArray.push({
      x1: config.normalized_line[0][0] * rect.width,
      y1: config.normalized_line[0][1] * rect.height,
      x2: config.normalized_line[1][0] * rect.width,
      y2: config.normalized_line[1][1] * rect.height
    });
  } else if (config.line && config.line.length === 2) {
    const scaleX = rect.width / 3840;
    const scaleY = rect.height / 2160;
    linesArray.push({
      x1: config.line[0][0] * scaleX,
      y1: config.line[0][1] * scaleY,
      x2: config.line[1][0] * scaleX,
      y2: config.line[1][1] * scaleY
    });
  }
  drawAll();
}

function applyDefaultGeometry() {
  ['canvas1', 'canvas2'].forEach(id => {
    const c = document.getElementById(id);
    if (!c) return;
    const r = c.getBoundingClientRect();
    const is1 = id === 'canvas1';
    const lines = is1 ? lines1 : lines2;
    lines.length = 0;
    lines.push({
      x1: (r.width || 640) * 0.15,
      y1: (r.height || 360) * 0.75,
      x2: (r.width || 640) * 0.85,
      y2: (r.height || 360) * 0.75
    });
  });
  resizeCanvases();
  updateGeometryDisplay(false);
}"""

    if old_geom_load in content:
        content = content.replace(old_geom_load, new_geom_load, 1)
        print("✓ Patched loadGeometryConfigs & applyGeometryToCanvas")
    else:
        print("Warning: old_geom_load block not matched exactly")

    # 6. Tab 3 ArcFace: Add reloadGalleryEmbeddings and filterNpyList functions
    old_enrolled_load = """async function loadEnrolledPersons() {
  appState.loading.enrollment = true;
  try {
    const persons = await api.get(`${API_CONFIG.endpoints.enrollment}/persons`);
    appState.enrolledPersons = persons;
    renderEnrolledPersons(persons);
  } catch (error) {
    console.error('Failed to load enrolled persons:', error);
    showToast('Không thể tải danh sách enrollment', 'error');
    // Show empty state
    renderEnrolledPersons([]);
  } finally {
    appState.loading.enrollment = false;
  }
}"""

    new_enrolled_load = """async function loadEnrolledPersons() {
  appState.loading.enrollment = true;
  try {
    let persons = [];
    try {
      persons = await api.get(`${API_CONFIG.endpoints.enrollment}/persons`);
    } catch (_) {
      // Fallback to students list
      const students = await api.get(`${API_CONFIG.endpoints.students}`);
      persons = (students || []).map(s => ({
        person_id: s.student_id,
        name: s.full_name,
        role: 'student'
      }));
    }
    appState.enrolledPersons = persons || [];
    renderEnrolledPersons(appState.enrolledPersons);
    const badge = document.getElementById('galleryCountBadge');
    if (badge) badge.textContent = `${appState.enrolledPersons.length} files`;
  } catch (error) {
    console.error('Failed to load enrolled persons:', error);
    showToast('Không thể tải danh sách enrollment', 'error');
    renderEnrolledPersons([]);
  } finally {
    appState.loading.enrollment = false;
  }
}

async function reloadGalleryEmbeddings() {
  const btn = document.getElementById('btnReloadGallery');
  if (btn) btn.textContent = 'Đang tải...';
  try {
    const res = await api.post('/api/v1/pipeline/reload-gallery', {});
    showToast(`✓ Đã reload gallery (${res.gallery_size || 0} embeddings)`, 'success');
    await loadEnrolledPersons();
  } catch (err) {
    console.error('Reload gallery error:', err);
    showToast(`Lỗi reload gallery: ${err.message}`, 'error');
  } finally {
    if (btn) btn.textContent = '⟳ Reload Embeddings';
  }
}

function filterNpyList() {
  const q = (document.getElementById('searchNpy')?.value || '').toLowerCase().trim();
  if (!q) {
    renderEnrolledPersons(appState.enrolledPersons || []);
    return;
  }
  const filtered = (appState.enrolledPersons || []).filter(p => 
    (p.name || '').toLowerCase().includes(q) || (p.person_id || '').toLowerCase().includes(q)
  );
  renderEnrolledPersons(filtered);
}
document.getElementById('searchNpy')?.addEventListener('input', filterNpyList);"""

    if old_enrolled_load in content:
        content = content.replace(old_enrolled_load, new_enrolled_load, 1)
        print("✓ Patched Tab 3: loadEnrolledPersons, reloadGalleryEmbeddings, filterNpyList")

    # 7. Tab 4 Video Review: update loadRecordings & wire video controls
    old_video_load = """async function loadRecordings() {
  appState.loading.replay = true;
  try {
    const cameras = await api.get(`${API_CONFIG.endpoints.replay}/cameras`);
    const allRecordings = [];
    
    for (const cam of cameras.cameras) {
      const recs = await api.get(`${API_CONFIG.endpoints.replay}/recordings?camera_id=${cam}`);
      allRecordings.push(...recs.recordings.map(r => ({ ...r, camera_id: cam })));
    }
    
    currentRecordings = allRecordings;
    renderRecordingList(allRecordings);
  } catch (error) {
    console.error('Failed to load recordings:', error);
    showToast('Không thể tải danh sách recordings', 'error');
    renderRecordingList([]);
  } finally {
    appState.loading.replay = false;
  }
}"""

    new_video_load = """async function loadRecordings() {
  appState.loading.replay = true;
  try {
    // 1. Try unified recordings endpoint
    const data = await api.get('/api/v1/recordings');
    if (data && data.recordings && data.recordings.length > 0) {
      currentRecordings = data.recordings.map(r => ({
        recording_id: r.id,
        camera_id: r.camera_id,
        filename: r.filename,
        url_path: r.url,
        duration_seconds: 60,
        start_timestamp: r.timestamp,
        has_recording: true
      }));
      renderRecordingList(currentRecordings);
      if (currentRecordings.length > 0) {
        selectRecording(currentRecordings[0].recording_id);
      }
      return;
    }
  } catch (e) {
    console.warn('Unified /api/v1/recordings failed, trying replay cameras:', e);
  }
  
  // 2. Fallback to replay router
  try {
    const cameras = await api.get(`${API_CONFIG.endpoints.replay}/cameras`);
    const allRecordings = [];
    for (const cam of (cameras.cameras || ['cam1', 'cam2'])) {
      try {
        const recs = await api.get(`${API_CONFIG.endpoints.replay}/recordings?camera_id=${cam}`);
        if (recs && recs.recordings) {
          allRecordings.push(...recs.recordings.map(r => ({ ...r, camera_id: cam })));
        }
      } catch (err) {}
    }
    currentRecordings = allRecordings;
    renderRecordingList(allRecordings);
    if (allRecordings.length > 0) {
      selectRecording(allRecordings[0].recording_id);
    }
  } catch (error) {
    console.error('Failed to load recordings:', error);
    renderRecordingList([]);
  } finally {
    appState.loading.replay = false;
  }
}

// Wire Video Player Controls
function initVideoPlayerControls() {
  const playBtn = document.getElementById('playBtn');
  const reviewVideo = document.getElementById('reviewVideo');
  if (playBtn && reviewVideo) {
    playBtn.addEventListener('click', () => {
      if (reviewVideo.paused) {
        reviewVideo.play();
        playBtn.textContent = '⏸';
      } else {
        reviewVideo.pause();
        playBtn.textContent = '▶';
      }
    });
    reviewVideo.addEventListener('play', () => { playBtn.textContent = '⏸'; });
    reviewVideo.addEventListener('pause', () => { playBtn.textContent = '▶'; });
    reviewVideo.addEventListener('timeupdate', () => {
      const seekBar = document.getElementById('seekBar');
      const timeLabel = document.getElementById('timeLabel');
      if (reviewVideo.duration) {
        const pct = (reviewVideo.currentTime / reviewVideo.duration) * 100;
        if (seekBar) seekBar.value = pct;
        if (timeLabel) timeLabel.textContent = `${formatDuration(reviewVideo.currentTime)} / ${formatDuration(reviewVideo.duration)}`;
      }
    });
  }
  const seekBar = document.getElementById('seekBar');
  if (seekBar && reviewVideo) {
    seekBar.addEventListener('input', (e) => {
      if (reviewVideo.duration) {
        reviewVideo.currentTime = (e.target.value / 100) * reviewVideo.duration;
      }
    });
  }
  const annotBtn = document.getElementById('annotBtn');
  const reviewOverlay = document.getElementById('reviewOverlay');
  if (annotBtn && reviewOverlay) {
    let annotOn = true;
    annotBtn.addEventListener('click', () => {
      annotOn = !annotOn;
      reviewOverlay.classList.toggle('hidden', !annotOn);
      annotBtn.textContent = annotOn ? 'Annotation ON' : 'Annotation OFF';
      annotBtn.className = annotOn 
        ? 'px-2.5 py-1 rounded-full bg-white text-black text-[11px] font-semibold' 
        : 'px-2.5 py-1 rounded-full border border-zinc-700 text-zinc-400 text-[11px] font-semibold';
    });
  }
  const speedSel = document.getElementById('speedSel');
  if (speedSel && reviewVideo) {
    speedSel.addEventListener('change', (e) => {
      const rate = parseFloat(e.target.value.replace('x', '')) || 1.0;
      reviewVideo.playbackRate = rate;
    });
  }
}
setTimeout(initVideoPlayerControls, 500);"""

    if old_video_load in content:
        content = content.replace(old_video_load, new_video_load, 1)
        print("✓ Patched Tab 4: loadRecordings & Video Player Controls wired")

    # 8. Tab 7 Worker Control: wire to pipeline router
    old_worker_ctrl = """async function sendControlCommand(action, target = 'worker', targetId = WORKER_ID) {
  const resultEl = document.getElementById('workerActionResult');
  if (resultEl) resultEl.textContent = `Đang gửi ${action}...`;
  
  // Disable buttons during request
  ['startWorkerBtn', 'stopWorkerBtn', 'restartWorkerBtn', 'getStatusBtn'].forEach(id => {
    const btn = document.getElementById(id);
    if (btn) btn.disabled = true;
  });
  
  try {
    const response = await api.post(`${API_CONFIG.endpoints.ai_worker}/control/${action}`, {
      request_id: `req-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,
      action: action,
      target: target,
      target_id: targetId,
      parameters: {},
      idempotency_key: `idem-${action}-${Date.now()}`,
      expires_at: Date.now() / 1000 + 300
    });
    
    if (resultEl) resultEl.textContent = `✓ ${action}: ${response.status || 'PENDING'}`;
    
    // Refresh status after a short delay
    setTimeout(loadWorkerHealth, 1000);
    
  } catch (error) {
    console.error(`Control ${action} failed:`, error);
    if (resultEl) resultEl.textContent = `✗ ${action}: ${error.message}`;
  } finally {
    ['startWorkerBtn', 'stopWorkerBtn', 'restartWorkerBtn', 'getStatusBtn'].forEach(id => {
      const btn = document.getElementById(id);
      if (btn) btn.disabled = false;
    });
  }
}

async function sendCameraCommand(action, cameraId) {
  const btnEnable = document.getElementById(`enable${cameraId.toUpperCase()}`);
  const btnDisable = document.getElementById(`disable${cameraId.toUpperCase()}`);
  const statusEl = document.getElementById(`cam${cameraId.slice(-1)}Status`);
  
  if (btnEnable) btnEnable.disabled = true;
  if (btnDisable) btnDisable.disabled = true;
  if (statusEl) statusEl.textContent = `Đang ${action === 'ENABLE_CAMERA' ? 'bật' : 'tắt'}...`;
  
  try {
    const response = await api.post(`${API_CONFIG.endpoints.ai_worker}/control/${action}`, {
      request_id: `req-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,
      action: action,
      target: 'camera',
      target_id: cameraId,
      parameters: {},
      idempotency_key: `idem-${action}-${cameraId}-${Date.now()}`,
      expires_at: Date.now() / 1000 + 300
    });
    
    if (statusEl) statusEl.textContent = `✓ ${action}: ${response.status || 'PENDING'}`;
    
    // Refresh health to get updated camera states
    setTimeout(loadWorkerHealth, 1000);
    
  } catch (error) {
    console.error(`Camera ${action} failed:`, error);
    if (statusEl) statusEl.textContent = `✗ ${action}: ${error.message}`;
  } finally {
    if (btnEnable) btnEnable.disabled = false;
    if (btnDisable) btnDisable.disabled = false;
  }
}"""

    new_worker_ctrl = """async function sendControlCommand(action, target = 'worker', targetId = WORKER_ID) {
  const resultEl = document.getElementById('workerActionResult');
  if (resultEl) resultEl.textContent = `Đang gửi ${action}...`;
  
  ['startWorkerBtn', 'stopWorkerBtn', 'restartWorkerBtn', 'getStatusBtn'].forEach(id => {
    const btn = document.getElementById(id);
    if (btn) btn.disabled = true;
  });
  
  try {
    let pipelineRes = null;
    if (action === 'RESTART_WORKER') {
      pipelineRes = await api.post('/api/v1/pipeline/restart', {});
    } else if (action === 'GET_STATUS') {
      pipelineRes = await api.get('/api/v1/pipeline/status');
    } else if (action === 'START_WORKER') {
      await Promise.allSettled([
        api.post('/api/v1/pipeline/camera/cam1/start', {}),
        api.post('/api/v1/pipeline/camera/cam2/start', {})
      ]);
      pipelineRes = { status: 'STARTED' };
    } else if (action === 'STOP_WORKER') {
      await Promise.allSettled([
        api.post('/api/v1/pipeline/camera/cam1/stop', {}),
        api.post('/api/v1/pipeline/camera/cam2/stop', {})
      ]);
      pipelineRes = { status: 'STOPPED' };
    }
    
    try {
      await api.post(`${API_CONFIG.endpoints.ai_worker}/control/${action}`, {
        request_id: `req-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,
        action: action,
        target: target,
        target_id: targetId,
        parameters: {},
        idempotency_key: `idem-${action}-${Date.now()}`,
        expires_at: Date.now() / 1000 + 300
      });
    } catch (_) {}
    
    if (resultEl) resultEl.textContent = `✓ ${action}: ${pipelineRes?.status || 'OK'}`;
    showToast(`✓ Thực thi ${action} thành công`, 'success');
    setTimeout(loadWorkerHealth, 1000);
  } catch (error) {
    console.error(`Control ${action} failed:`, error);
    if (resultEl) resultEl.textContent = `✗ ${action}: ${error.message}`;
    showToast(`Lỗi ${action}: ${error.message}`, 'error');
  } finally {
    ['startWorkerBtn', 'stopWorkerBtn', 'restartWorkerBtn', 'getStatusBtn'].forEach(id => {
      const btn = document.getElementById(id);
      if (btn) btn.disabled = false;
    });
  }
}

async function sendCameraCommand(action, cameraId) {
  const normCam = cameraId.toLowerCase().replace('-', '');
  const btnEnable = document.getElementById(`enable${normCam.toUpperCase()}`);
  const btnDisable = document.getElementById(`disable${normCam.toUpperCase()}`);
  const statusEl = document.getElementById(`cam${normCam.slice(-1)}Status`);
  
  if (btnEnable) btnEnable.disabled = true;
  if (btnDisable) btnDisable.disabled = true;
  if (statusEl) statusEl.textContent = `Đang ${action === 'ENABLE_CAMERA' ? 'bật' : 'tắt'}...`;
  
  try {
    const pipelineAction = action === 'ENABLE_CAMERA' ? 'start' : 'stop';
    await api.post(`/api/v1/pipeline/camera/${normCam}/${pipelineAction}`, {});
    
    try {
      await api.post(`${API_CONFIG.endpoints.ai_worker}/control/${action}`, {
        request_id: `req-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,
        action: action,
        target: 'camera',
        target_id: normCam,
        parameters: {},
        idempotency_key: `idem-${action}-${normCam}-${Date.now()}`,
        expires_at: Date.now() / 1000 + 300
      });
    } catch (_) {}
    
    if (statusEl) statusEl.textContent = `✓ ${action}: SUCCESS`;
    showToast(`✓ Camera ${normCam.toUpperCase()} đã ${pipelineAction === 'start' ? 'bật' : 'tắt'}`, 'success');
    setTimeout(loadWorkerHealth, 1000);
  } catch (error) {
    console.error(`Camera ${action} failed:`, error);
    if (statusEl) statusEl.textContent = `✗ ${action}: ${error.message}`;
    showToast(`Lỗi điều khiển camera: ${error.message}`, 'error');
  } finally {
    if (btnEnable) btnEnable.disabled = false;
    if (btnDisable) btnDisable.disabled = false;
  }
}"""

    if old_worker_ctrl in content:
        content = content.replace(old_worker_ctrl, new_worker_ctrl, 1)
        print("✓ Patched Tab 7: Worker Control & Camera Commands wired to pipeline router")

    # 9. Clean up duplicate saveLines at lines 3459-3507
    old_dup_save = """async function saveLines() {
  const config1 = linesToGeometryConfig('CAM1', lines1, 'canvas1');
  const config2 = linesToGeometryConfig('CAM2', lines2, 'canvas2');
  
  if (!config1 || !config2) {
    showToast('Chưa vẽ line cho camera', 'error');
    return;
  }
  
  try {
    // Save to backend via Geometry API
    await Promise.all([
      api.put(`${API_CONFIG.endpoints.geometry}/CAM1/line`, config1),
      api.put(`${API_CONFIG.endpoints.geometry}/CAM2/line`, config2)
    ]);
    
    showToast('✓ Đã lưu line vào backend', 'success');
    updateGeometryDisplay();
    
    // Update local state
    appState.geometryConfigs.CAM1 = { ...appState.geometryConfigs.CAM1, line: config1 };
    appState.geometryConfigs.CAM2 = { ...appState.geometryConfigs.CAM2, line: config2 };
    
  } catch (error) {
    console.error('Save lines failed:', error);
    showToast(`Lỗi lưu line: ${error.message}`, 'error');
  }
}

function linesToGeometryConfig(cameraId, linesArray, canvasId) {
  if (linesArray.length === 0) return null;
  
  const canvas = document.getElementById(canvasId);
  const rect = canvas.getBoundingClientRect();
  const scaleX = 3840 / rect.width;
  const scaleY = 2160 / rect.height;
  
  const line = linesArray[linesArray.length - 1]; // Last drawn line
  
  return {
    p1: { x: Math.round(line.x1 * scaleX), y: Math.round(line.y1 * scaleY) },
    p2: { x: Math.round(line.x2 * scaleX), y: Math.round(line.y2 * scaleY) },
    direction_semantics: 'side_a_to_b_in'
  };
}

// Override the original saveLines function
window.saveLines = saveLines;"""

    if old_dup_save in content:
        content = content.replace(old_dup_save, "// Duplicate saveLines removed in favor of primary definition\n", 1)
        print("✓ Removed duplicate saveLines block")

    # 10. Tab 8: Add deleteStudent, openAddStudentModal, viewStudentDetail, and pagination
    old_students_table = """          <div class="flex items-center gap-1.5">
            <button onclick="openEnrollmentModal('${student.student_id}', '${student.full_name}', '${student.class_name || student.class_id}')" 
                    class="px-3 py-1.5 rounded-full bg-white text-black text-[11px] font-semibold hover:bg-zinc-200 transition" 
                    ${student.enrollment_status === 'ENROLLED' ? 'disabled' : ''}>
              ${student.enrollment_status === 'ENROLLED' ? '✓ Đã đăng ký' : 'Đăng ký khuôn mặt'}
            </button>
            <button onclick="viewStudentDetail('${student.student_id}')" class="w-8 h-8 rounded-full border border-zinc-700 flex items-center justify-center hover:bg-zinc-900 text-zinc-400" title="Xem chi tiết">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/></svg>
            </button>
          </div>"""

    new_students_table = """          <div class="flex items-center gap-1.5">
            <button onclick="openEnrollmentModal('${student.student_id}', '${student.full_name}', '${student.class_name || student.class_id}')" 
                    class="px-3 py-1.5 rounded-full bg-white text-black text-[11px] font-semibold hover:bg-zinc-200 transition" 
                    ${student.enrollment_status === 'ENROLLED' ? 'disabled' : ''}>
              ${student.enrollment_status === 'ENROLLED' ? '✓ Đã đăng ký' : 'Đăng ký khuôn mặt'}
            </button>
            <button onclick="viewStudentDetail('${student.student_id}')" class="w-8 h-8 rounded-full border border-zinc-700 flex items-center justify-center hover:bg-zinc-900 text-zinc-400" title="Xem chi tiết">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/></svg>
            </button>
            <button onclick="deleteStudent('${student.student_id}')" class="w-8 h-8 rounded-full border border-red-900/50 hover:border-red-600 flex items-center justify-center hover:bg-red-900/30 text-red-400" title="Xóa học sinh">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            </button>
          </div>"""

    if old_students_table in content:
        content = content.replace(old_students_table, new_students_table, 1)
        print("✓ Patched Tab 8: Added delete student button to table")

    student_helper_funcs = """
window.deleteStudent = async function(studentId) {
  if (!confirm(`Bạn có chắc chắn muốn xóa học sinh ${studentId}?`)) return;
  try {
    await api.delete(`${API_CONFIG.endpoints.students}/${studentId}`);
    showToast(`✓ Đã xóa học sinh ${studentId}`, 'success');
    await loadStudents();
  } catch (err) {
    console.error('Delete student error:', err);
    showToast(`Lỗi xóa học sinh: ${err.message}`, 'error');
  }
};

window.viewStudentDetail = async function(studentId) {
  try {
    const student = await api.get(`${API_CONFIG.endpoints.students}/${studentId}`);
    alert(`Thông tin học sinh:\\nMã SV: ${student.student_id}\\nHọ tên: ${student.full_name}\\nLớp: ${student.class_name || student.class_id}\\nTrạng thái: ${student.enrollment_status}\\nEmbedding: ${student.embedding_path || 'Chưa có'}`);
  } catch (err) {
    showToast(`Lỗi xem chi tiết: ${err.message}`, 'error');
  }
};

window.openAddStudentModal = async function() {
  const studentId = prompt('Nhập Mã Học Sinh (VD: SV001):');
  if (!studentId) return;
  const fullName = prompt('Nhập Họ và Tên:');
  if (!fullName) return;
  const classId = prompt('Nhập Lớp (VD: 10A1):') || '10A1';
  
  try {
    await api.post(`${API_CONFIG.endpoints.students}/enroll`, {
      student_id: studentId.trim(),
      full_name: fullName.trim(),
      class_id: classId.trim(),
      gender: 'OTHER'
    });
    showToast(`✓ Đã thêm học sinh ${fullName} (${studentId})`, 'success');
    await loadStudents();
    await loadClasses();
  } catch (err) {
    console.error('Add student failed:', err);
    showToast(`Lỗi thêm học sinh: ${err.message}`, 'error');
  }
};

// Student pagination buttons
document.getElementById('prevStudentsPage')?.addEventListener('click', () => {
  if (studentsPagination.page > 1) {
    studentsPagination.page--;
    loadStudents({ offset: (studentsPagination.page - 1) * studentsPagination.limit });
  }
});
document.getElementById('nextStudentsPage')?.addEventListener('click', () => {
  studentsPagination.page++;
  loadStudents({ offset: (studentsPagination.page - 1) * studentsPagination.limit });
});
"""
    if "window.deleteStudent = async function" not in content:
        insert_marker = "// ============================================================\n// EXCEL IMPORT MODULE (Module C)"
        content = content.replace(insert_marker, student_helper_funcs + "\n" + insert_marker, 1)
        print("✓ Added student helper functions (deleteStudent, viewStudentDetail, openAddStudentModal, pagination)")

    # 11. Fix duplicate onPageSwitch
    dup_on_page_switch = """async function onPageSwitch(page) {
  switch (page) {
    case 'live':
      if (!appState.cameras.cam1) initLiveMonitoring();
      resizeCanvases();
      break;
    case 'arcface':
      if (appState.enrolledPersons.length === 0) await loadEnrolledPersons();
      break;
    case 'video':
      if (currentRecordings.length === 0) await loadRecordings();
      break;
    case 'health':
      await loadBackendHealth();
      break;
    case 'records':
      if (currentRecords.length === 0) await loadAttendanceRecords();
      break;
    case 'students':
      await loadStudents();
      await loadClasses();
      break;
  }
}
async function onPageSwitch(page) {
  switch (page) {
    case 'live':
      if (!appState.cameras.cam1) initLiveMonitoring();
      resizeCanvases();
      break;
    case 'arcface':
      if (appState.enrolledPersons.length === 0) await loadEnrolledPersons();
      break;
    case 'video':
      if (currentRecordings.length === 0) await loadRecordings();
      break;
    case 'health':
      await loadBackendHealth();
      break;
    case 'records':
      if (currentRecords.length === 0) await loadAttendanceRecords();
      break;
  }
}"""

    clean_on_page_switch = """async function onPageSwitch(page) {
  switch (page) {
    case 'dashboard':
      loadInitialHealthData();
      break;
    case 'live':
      if (!appState.cameras.cam1) initLiveMonitoring();
      resizeCanvases();
      startCanvasOverlays();
      break;
    case 'arcface':
      await loadEnrolledPersons();
      break;
    case 'video':
      await loadRecordings();
      break;
    case 'health':
      await loadBackendHealth();
      break;
    case 'records':
      await loadAttendanceRecords();
      break;
    case 'worker':
      await loadWorkerHealth();
      startWorkerHealthPolling();
      break;
    case 'students':
      await loadStudents();
      await loadClasses();
      break;
  }
}"""

    if dup_on_page_switch in content:
        content = content.replace(dup_on_page_switch, clean_on_page_switch, 1)
        print("✓ Deduplicated onPageSwitch and wired all 8 tabs")

    INDEX_PATH.write_text(content, encoding="utf-8")
    print("✓ Successfully saved updated frontend/index.html")

if __name__ == "__main__":
    apply_patches()
