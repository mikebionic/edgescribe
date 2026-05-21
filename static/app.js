const $ = (sel) => document.querySelector(sel);

// -- Elements --
const dropZone      = $("#dropZone");
const fileInput     = $("#fileInput");
const dropLabel     = $("#dropLabel");
const submitBtn     = $("#submitBtn");
const progressWrap  = $("#progressWrap");
const progressFill  = $("#progressFill");
const progressLabel = $("#progressLabel");
const progressPct   = $("#progressPct");
const progressMeta = $("#progressMeta");
const resultPlaceholder = $("#resultPlaceholder");
const alertEl       = $("#alert");
const resultCard    = $("#resultCard");
const resultTxt     = $("#resultTxt");
const resultSrt     = $("#resultSrt");
const micBtn        = $("#micBtn");
const micStatus     = $("#micStatus");
const micTimer      = $("#micTimer");
const waveCanvas    = $("#waveCanvas");

let fileQueue    = [];  // multiple files
let currentIdx   = 0;
let currentJobId = null;
let pollTimer    = null;
let allResults   = { txt: [], srt: [] };
let allJobs      = [];  // history
let selectedJobId = null;  // for history view

// Smooth progress interpolation
let displayPct = 0;
let targetPct  = 0;
let animFrame  = null;

function animateProgress() {
  if (displayPct < targetPct) {
    displayPct += Math.max(0.3, (targetPct - displayPct) * 0.08);
    if (targetPct - displayPct < 0.5) displayPct = targetPct;
    const rounded = Math.round(displayPct);
    progressPct.textContent = `${rounded}%`;
    progressFill.style.width = `${rounded}%`;
  }
  animFrame = requestAnimationFrame(animateProgress);
}

function startProgressAnimation() {
  displayPct = 0;
  targetPct = 0;
  if (animFrame) cancelAnimationFrame(animFrame);
  animFrame = requestAnimationFrame(animateProgress);
}

function stopProgressAnimation() {
  if (animFrame) { cancelAnimationFrame(animFrame); animFrame = null; }
}

// Completion chime (synthesized)
function playChime() {
  try {
    const ctx = new AudioContext();
    const notes = [523.25, 659.25, 783.99]; // C5, E5, G5
    notes.forEach((freq, i) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "sine";
      osc.frequency.value = freq;
      gain.gain.setValueAtTime(0.15, ctx.currentTime + i * 0.12);
      gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + i * 0.12 + 0.5);
      osc.connect(gain).connect(ctx.destination);
      osc.start(ctx.currentTime + i * 0.12);
      osc.stop(ctx.currentTime + i * 0.12 + 0.5);
    });
  } catch {}
}

// ===== ANIMATED BACKGROUND =====
(function initBackground() {
  const canvas = $("#bgCanvas");
  const ctx = canvas.getContext("2d");
  let w, h;
  const orbs = [];

  function resize() {
    w = canvas.width = window.innerWidth;
    h = canvas.height = window.innerHeight;
  }

  window.addEventListener("resize", resize);
  resize();

  // Floating gradient orbs
  for (let i = 0; i < 4; i++) {
    orbs.push({
      x: Math.random() * w,
      y: Math.random() * h,
      r: 200 + Math.random() * 200,
      vx: (Math.random() - 0.5) * 0.3,
      vy: (Math.random() - 0.5) * 0.3,
      hue: 250 + Math.random() * 40,
    });
  }

  function draw() {
    ctx.clearRect(0, 0, w, h);
    for (const orb of orbs) {
      orb.x += orb.vx;
      orb.y += orb.vy;
      if (orb.x < -orb.r) orb.x = w + orb.r;
      if (orb.x > w + orb.r) orb.x = -orb.r;
      if (orb.y < -orb.r) orb.y = h + orb.r;
      if (orb.y > h + orb.r) orb.y = -orb.r;

      const g = ctx.createRadialGradient(orb.x, orb.y, 0, orb.x, orb.y, orb.r);
      g.addColorStop(0, `hsla(${orb.hue}, 60%, 50%, 0.08)`);
      g.addColorStop(1, `hsla(${orb.hue}, 60%, 50%, 0)`);
      ctx.fillStyle = g;
      ctx.fillRect(orb.x - orb.r, orb.y - orb.r, orb.r * 2, orb.r * 2);
    }
    requestAnimationFrame(draw);
  }

  draw();
})();

// ===== MODE TABS =====
document.querySelectorAll(".mode-tab").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".mode-tab").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    const mode = btn.dataset.mode;
    $("#fileMode").classList.toggle("hidden", mode !== "file");
    $("#micMode").classList.toggle("hidden", mode !== "mic");
    $("#historyMode").classList.toggle("hidden", mode !== "history");
    if (mode === "history") loadJobsList();
  });
});

// ===== FILE UPLOAD =====
dropZone.addEventListener("click", () => fileInput.click());
fileInput.addEventListener("change", () => selectFiles(fileInput.files));

dropZone.addEventListener("dragover", (e) => { e.preventDefault(); dropZone.classList.add("dragover"); });
dropZone.addEventListener("dragleave", () => dropZone.classList.remove("dragover"));
dropZone.addEventListener("drop", (e) => {
  e.preventDefault();
  dropZone.classList.remove("dragover");
  if (e.dataTransfer.files.length) selectFiles(e.dataTransfer.files);
});

function selectFiles(files) {
  if (!files || !files.length) return;
  fileQueue = Array.from(files);
  const totalSize = (fileQueue.reduce((s, f) => s + f.size, 0) / 1024 / 1024).toFixed(1);
  if (fileQueue.length === 1) {
    dropLabel.innerHTML = `${fileQueue[0].name} <span class="upload-hint">${totalSize} MB</span>`;
  } else {
    dropLabel.innerHTML = `${fileQueue.length} files <span class="upload-hint">${totalSize} MB</span>`;
  }
  dropZone.classList.add("has-file");
  submitBtn.disabled = false;
  hideAlert();
}

// ===== MIC RECORDING =====
let mediaRecorder = null;
let audioChunks = [];
let micStream = null;
let analyser = null;
let timerInterval = null;
let recordStart = 0;
let waveCtx = waveCanvas.getContext("2d");

micBtn.addEventListener("click", async () => {
  if (mediaRecorder && mediaRecorder.state === "recording") {
    stopRecording();
  } else {
    startRecording();
  }
});

async function startRecording() {
  try {
    micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch {
    micStatus.textContent = "Microphone access denied";
    return;
  }

  const audioCtx = new AudioContext();
  const source = audioCtx.createMediaStreamSource(micStream);
  analyser = audioCtx.createAnalyser();
  analyser.fftSize = 256;
  source.connect(analyser);

  mediaRecorder = new MediaRecorder(micStream);
  audioChunks = [];
  mediaRecorder.ondataavailable = (e) => audioChunks.push(e.data);
  mediaRecorder.onstop = onRecordingDone;
  mediaRecorder.start();

  micBtn.classList.add("recording");
  micStatus.textContent = "Recording... click to stop";
  micTimer.classList.remove("hidden");
  recordStart = Date.now();
  timerInterval = setInterval(updateTimer, 200);
  drawWaveform();
}

function stopRecording() {
  if (mediaRecorder && mediaRecorder.state === "recording") {
    mediaRecorder.stop();
  }
  if (micStream) {
    micStream.getTracks().forEach(t => t.stop());
    micStream = null;
  }
  micBtn.classList.remove("recording");
  clearInterval(timerInterval);
}

function onRecordingDone() {
  const blob = new Blob(audioChunks, { type: "audio/webm" });
  const file = new File([blob], "recording.webm", { type: "audio/webm" });
  fileQueue = [file];
  const dur = ((Date.now() - recordStart) / 1000).toFixed(1);
  micStatus.textContent = `Recorded ${dur}s - ready to transcribe`;
  submitBtn.disabled = false;
  hideAlert();

  // Clear waveform
  waveCtx.clearRect(0, 0, waveCanvas.width, waveCanvas.height);
}

function updateTimer() {
  const s = Math.floor((Date.now() - recordStart) / 1000);
  const m = Math.floor(s / 60);
  micTimer.textContent = `${String(m).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}

function drawWaveform() {
  if (!analyser || !micBtn.classList.contains("recording")) return;
  const data = new Uint8Array(analyser.frequencyBinCount);
  analyser.getByteTimeDomainData(data);

  const w = waveCanvas.width;
  const h = waveCanvas.height;
  waveCtx.clearRect(0, 0, w, h);
  waveCtx.beginPath();
  waveCtx.strokeStyle = "rgba(124, 106, 239, 0.6)";
  waveCtx.lineWidth = 2;

  const step = w / data.length;
  for (let i = 0; i < data.length; i++) {
    const y = (data[i] / 255) * h;
    if (i === 0) waveCtx.moveTo(0, y);
    else waveCtx.lineTo(i * step, y);
  }
  waveCtx.stroke();
  requestAnimationFrame(drawWaveform);
}

// ===== SUBMIT =====
submitBtn.addEventListener("click", () => {
  if (!fileQueue.length) return;
  submitBtn.disabled = true;
  resultCard.classList.add("hidden");
  hideAlert();
  allResults = { txt: [], srt: [] };
  currentIdx = 0;
  processNextFile();
});

async function processNextFile() {
  if (currentIdx >= fileQueue.length) {
    onAllDone();
    return;
  }

  const file = fileQueue[currentIdx];
  const label = fileQueue.length > 1
    ? `[${currentIdx + 1}/${fileQueue.length}] ${file.name}`
    : file.name;

  if (pollTimer) clearInterval(pollTimer);
  startProgressAnimation();
  showProgress(`Uploading ${label}...`, 0);

  const form = new FormData();
  form.append("file", file);
  form.append("language", $("#language").value);
  form.append("model", $("#model").value);
  form.append("timestamps", $("#timestamps").value);
  form.append("speakers", $("#speakers").value);

  try {
    const res = await fetch("/v1/transcribe", { method: "POST", body: form });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    currentJobId = data.job_id;
    showProgress(`Queued: ${label}...`, 0);
    pollTimer = setInterval(pollJob, 1000);
  } catch (err) {
    stopProgressAnimation();
    hideProgress();
    showAlert(`Upload failed: ${err.message}`, "error");
    submitBtn.disabled = false;
  }
}

function onAllDone() {
  stopProgressAnimation();
  hideProgress();
  playChime();

  const count = allResults.txt.length;
  const totalTxt = allResults.txt.join("\n\n");
  const totalSrt = allResults.srt.join("\n\n");

  resultTxt.value = totalTxt;
  resultSrt.value = totalSrt;
  resultPlaceholder.classList.add("hidden");
  resultCard.classList.remove("hidden");
  submitBtn.disabled = false;

  showAlert(
    count === 1
      ? `Done - ${resultTxt.value.split("\n").length} lines`
      : `Done - ${count} files transcribed`,
    "success"
  );
}

// ===== POLLING =====
async function pollJob() {
  try {
    const res = await fetch(`/v1/jobs/${currentJobId}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const job = await res.json();

    if (job.status === "processing") {
      const pct = job.progress || 0;
      const stages = {
        loading_model: "Loading model",
        transcribing: "Transcribing",
        diarizing: "Detecting speakers",
        formatting: "Finishing up",
      };
      const stage = stages[job.stage] || job.stage;
      const meta = [];
      if (job.speed) meta.push(`${job.speed}x`);
      if (job.eta > 0) {
        const m = Math.floor(job.eta / 60);
        const s = job.eta % 60;
        meta.push(m > 0 ? `~${m}m ${s}s remaining` : `~${s}s remaining`);
      }
      targetPct = pct;
      showProgress(`${stage}...`, null, meta.join("  "));
    } else if (job.status === "done") {
      clearInterval(pollTimer);
      stopProgressAnimation();
      hideProgress();
      showResult(job);
    } else if (job.status === "failed") {
      clearInterval(pollTimer);
      stopProgressAnimation();
      hideProgress();
      showAlert(`Error: ${job.error}`, "error");
      submitBtn.disabled = false;
    }
  } catch (err) {
    clearInterval(pollTimer);
    hideProgress();
    showAlert(`Connection lost: ${err.message}`, "error");
    submitBtn.disabled = false;
  }
}

function showResult(job) {
  allResults.txt.push(job.result.txt);
  allResults.srt.push(job.result.srt);
  currentIdx++;
  processNextFile();
}

// ===== RESULT TABS =====
document.querySelectorAll(".result-tabs .tab").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".result-tabs .tab").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    const tab = btn.dataset.tab;
    resultTxt.classList.toggle("hidden", tab !== "txt");
    resultSrt.classList.toggle("hidden", tab !== "srt");
  });
});

// ===== DOWNLOAD & COPY =====
$("#downloadTxt").addEventListener("click", () => download("txt"));
$("#downloadSrt").addEventListener("click", () => download("srt"));

function download(fmt) {
  const jobId = selectedJobId || currentJobId;
  if (!jobId) return;
  const a = document.createElement("a");
  a.href = `/v1/jobs/${jobId}/download/${fmt}`;
  a.click();
}

$("#copyBtn").addEventListener("click", () => {
  const active = resultSrt.classList.contains("hidden") ? resultTxt : resultSrt;
  navigator.clipboard.writeText(active.value).then(() => {
    const btn = $("#copyBtn");
    btn.classList.add("copied");
    btn.querySelector("span").textContent = "Copied!";
    setTimeout(() => {
      btn.classList.remove("copied");
      btn.querySelector("span").textContent = "Copy";
    }, 1500);
  });
});

// ===== HISTORY =====
$("#refreshBtn").addEventListener("click", loadJobsList);

async function loadJobsList() {
  const jobsList = $("#jobsList");
  jobsList.innerHTML = '<p class="loading">Loading jobs...</p>';

  try {
    const res = await fetch("/v1/jobs");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    allJobs = await res.json();

    if (!allJobs || allJobs.length === 0) {
      jobsList.innerHTML = '<p class="empty">No transcriptions yet</p>';
      return;
    }

    jobsList.innerHTML = allJobs.map(job => `
      <div class="job-item" data-job-id="${job.job_id}">
        <div class="job-header">
          <span class="job-name">${escapeHtml(job.filename || 'Unnamed')}</span>
          <span class="job-status job-status-${job.status}">${job.status}</span>
        </div>
        <div class="job-meta">
          <span>${new Date(job.created_at * 1000).toLocaleDateString()}</span>
          ${job.status === 'done' ? `<span>${job.segments_count || 0} segments</span>` : ''}
          ${job.status === 'failed' ? `<span class="error">${escapeHtml(job.error || 'Unknown error')}</span>` : ''}
        </div>
      </div>
    `).join('');

    document.querySelectorAll(".job-item").forEach(item => {
      item.addEventListener("click", () => {
        document.querySelectorAll(".job-item").forEach(i => i.classList.remove("active"));
        item.classList.add("active");
        viewJob(item.dataset.jobId);
      });
    });
  } catch (err) {
    jobsList.innerHTML = `<p class="error">Failed to load: ${escapeHtml(err.message)}</p>`;
  }
}

async function viewJob(jobId) {
  const jobMeta = allJobs.find(j => j.job_id === jobId);
  if (!jobMeta) return;

  selectedJobId = jobId;

  if (jobMeta.status !== "done") {
    resultCard.classList.add("hidden");
    resultPlaceholder.classList.remove("hidden");
    showAlert(`Job status: ${jobMeta.status}${jobMeta.error ? ' - ' + jobMeta.error : ''}`, jobMeta.status === 'failed' ? 'error' : 'info');
    return;
  }

  // Fetch full job details (including result)
  try {
    const res = await fetch(`/v1/jobs/${jobId}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const job = await res.json();

    resultPlaceholder.classList.add("hidden");
    resultCard.classList.remove("hidden");
    resultTxt.value = job.result.txt;
    resultSrt.value = job.result.srt;

    // Reset to text tab view
    document.querySelectorAll(".result-tabs .tab").forEach(t => t.classList.remove("active"));
    document.querySelector(".result-tabs .tab[data-tab='txt']").classList.add("active");
    resultTxt.classList.remove("hidden");
    resultSrt.classList.add("hidden");

    showAlert(`Viewing: ${escapeHtml(job.filename || 'Unnamed')}`, "success");
  } catch (err) {
    resultCard.classList.add("hidden");
    resultPlaceholder.classList.remove("hidden");
    showAlert(`Failed to load transcript: ${err.message}`, "error");
  }
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

// ===== UI HELPERS =====
function showProgress(label, pct, meta) {
  progressWrap.classList.remove("hidden");
  progressLabel.textContent = label;
  if (pct !== null) {
    targetPct = pct;
    progressPct.textContent = `${pct}%`;
    progressFill.style.width = `${Math.max(pct, 1)}%`;
  }
  progressMeta.textContent = meta || "";
}

function hideProgress() { progressWrap.classList.add("hidden"); }

function showAlert(text, type) {
  alertEl.textContent = text;
  alertEl.className = `alert ${type}`;
}

function hideAlert() { alertEl.className = "alert hidden"; }
