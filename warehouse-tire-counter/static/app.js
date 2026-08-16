/**
 * Mining & Warehouse Tire Object Counter Frontend Controller
 */

document.addEventListener('DOMContentLoaded', () => {
  // Elements
  const videoStream = document.getElementById('videoStream');
  const sourceBadge = document.getElementById('sourceBadge');
  const fpsDisplay = document.getElementById('fpsDisplay');
  const streamStatusPill = document.getElementById('streamStatusPill');
  const streamStatusText = document.getElementById('streamStatusText');

  // KPI Metrics
  const valTotalLive = document.getElementById('valTotalLive');
  const valInflow = document.getElementById('valInflow');
  const valOutflow = document.getElementById('valOutflow');
  const valNetDelta = document.getElementById('valNetDelta');
  const bayListContainer = document.getElementById('bayListContainer');
  const eventTableBody = document.getElementById('eventTableBody');

  // Buttons & Controls
  const btnRefreshStream = document.getElementById('btnRefreshStream');
  const btnResetCounters = document.getElementById('btnResetCounters');
  const btnExportJson = document.getElementById('btnExportJson');
  const tabButtons = document.querySelectorAll('.tab-btn');

  // Forms
  const sampleConfRange = document.getElementById('sampleConfRange');
  const sampleConfVal = document.getElementById('sampleConfVal');
  const sampleModelSelect = document.getElementById('sampleModelSelect');
  const btnApplySample = document.getElementById('btnApplySample');

  const webcamIndexSelect = document.getElementById('webcamIndexSelect');
  const webcamModelSelect = document.getElementById('webcamModelSelect');
  const btnStartWebcam = document.getElementById('btnStartWebcam');

  const dropzoneBox = document.getElementById('dropzoneBox');
  const videoFileInput = document.getElementById('videoFileInput');
  const selectedFileName = document.getElementById('selectedFileName');
  const uploadVideoForm = document.getElementById('uploadVideoForm');
  const uploadModelSelect = document.getElementById('uploadModelSelect');

  const rtspUrlInput = document.getElementById('rtspUrlInput');
  const rtspModelSelect = document.getElementById('rtspModelSelect');
  const btnStartRtsp = document.getElementById('btnStartRtsp');

  let currentSourceType = 'sample';
  const bayColorPalette = ['#00a5ff', '#ff6400', '#00ffc8', '#c832ff', '#f85149', '#d29922'];

  // Update confidence slider label
  if (sampleConfRange && sampleConfVal) {
    sampleConfRange.addEventListener('input', (e) => {
      sampleConfVal.textContent = parseFloat(e.target.value).toFixed(2);
    });
  }

  // Refresh stream element
  function reloadStream() {
    videoStream.src = `/api/stream?t=${Date.now()}`;
  }

  btnRefreshStream.addEventListener('click', reloadStream);

  // Tab switching
  tabButtons.forEach((btn) => {
    btn.addEventListener('click', () => {
      tabButtons.forEach((b) => b.classList.remove('active'));
      btn.classList.add('active');

      const targetSource = btn.getAttribute('data-source');
      currentSourceType = targetSource;

      // Hide all forms
      document.querySelectorAll('.source-form').forEach((f) => f.classList.remove('active'));

      // Show relevant form
      if (targetSource === 'sample' || targetSource === 'sample_conveyor') {
        document.getElementById('formSample').classList.add('active');
      } else if (targetSource === 'webcam') {
        document.getElementById('formWebcam').classList.add('active');
      } else if (targetSource === 'upload') {
        document.getElementById('formUpload').classList.add('active');
      } else if (targetSource === 'rtsp') {
        document.getElementById('formRtsp').classList.add('active');
      }
    });
  });

  // Apply Sample Source
  btnApplySample.addEventListener('click', async () => {
    const formData = new FormData();
    formData.append('source_type', currentSourceType);
    formData.append('model_name', sampleModelSelect.value);
    formData.append('conf', sampleConfRange.value);

    try {
      btnApplySample.disabled = true;
      btnApplySample.textContent = 'Switching...';
      const res = await fetch('/api/source/select', { method: 'POST', body: formData });
      const data = await res.json();
      if (data.status === 'ok') {
        sourceBadge.textContent = currentSourceType === 'sample' ? 'SIMULATED MINING YARD' : 'SIMULATED CONVEYOR';
        setTimeout(reloadStream, 400);
      }
    } catch (err) {
      alert(`Failed to apply sample source: ${err.message}`);
    } finally {
      btnApplySample.disabled = false;
      btnApplySample.textContent = 'Apply & Stream';
    }
  });

  // Start Webcam
  btnStartWebcam.addEventListener('click', async () => {
    const formData = new FormData();
    formData.append('source_type', 'webcam');
    formData.append('camera_index', webcamIndexSelect.value);
    formData.append('model_name', webcamModelSelect.value);
    formData.append('conf', '0.25');

    try {
      btnStartWebcam.disabled = true;
      btnStartWebcam.textContent = 'Connecting Camera...';
      const res = await fetch('/api/source/select', { method: 'POST', body: formData });
      const data = await res.json();
      if (data.status === 'ok') {
        sourceBadge.textContent = `LIVE WEBCAM #${webcamIndexSelect.value}`;
        setTimeout(reloadStream, 500);
      }
    } catch (err) {
      alert(`Webcam connection failed: ${err.message}`);
    } finally {
      btnStartWebcam.disabled = false;
      btnStartWebcam.textContent = 'Start Live Camera';
    }
  });

  // Drag & Drop / File Selection
  dropzoneBox.addEventListener('click', () => videoFileInput.click());

  videoFileInput.addEventListener('change', (e) => {
    if (e.target.files && e.target.files[0]) {
      selectedFileName.textContent = `Selected: ${e.target.files[0].name}`;
    }
  });

  uploadVideoForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!videoFileInput.files || !videoFileInput.files[0]) {
      alert('Please select a video file first.');
      return;
    }

    const formData = new FormData();
    formData.append('file', videoFileInput.files[0]);
    formData.append('model_name', uploadModelSelect.value);
    formData.append('conf', '0.25');

    const submitBtn = document.getElementById('btnUploadSubmit');
    try {
      submitBtn.disabled = true;
      submitBtn.textContent = 'Uploading & Initializing...';
      const res = await fetch('/api/source/upload', { method: 'POST', body: formData });
      const data = await res.json();
      if (data.status === 'ok') {
        sourceBadge.textContent = `UPLOADED: ${data.filename}`;
        setTimeout(reloadStream, 500);
      }
    } catch (err) {
      alert(`Upload error: ${err.message}`);
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = 'Upload & Count';
    }
  });

  // Start RTSP
  btnStartRtsp.addEventListener('click', async () => {
    const url = rtspUrlInput.value.trim();
    if (!url) {
      alert('Please enter a valid RTSP stream URL.');
      return;
    }

    const formData = new FormData();
    formData.append('source_type', 'rtsp');
    formData.append('rtsp_url', url);
    formData.append('model_name', rtspModelSelect.value);
    formData.append('conf', '0.25');

    try {
      btnStartRtsp.disabled = true;
      btnStartRtsp.textContent = 'Connecting RTSP...';
      const res = await fetch('/api/source/select', { method: 'POST', body: formData });
      const data = await res.json();
      if (data.status === 'ok') {
        sourceBadge.textContent = 'CCTV RTSP LIVE';
        setTimeout(reloadStream, 600);
      }
    } catch (err) {
      alert(`RTSP connection error: ${err.message}`);
    } finally {
      btnStartRtsp.disabled = false;
      btnStartRtsp.textContent = 'Connect RTSP';
    }
  });

  // Reset Counters
  btnResetCounters.addEventListener('click', async () => {
    if (!confirm('Are you sure you want to reset all counts and tracking logs?')) return;
    try {
      await fetch('/api/reset', { method: 'POST' });
    } catch (err) {
      console.error('Reset error:', err);
    }
  });

  // Export JSON
  btnExportJson.addEventListener('click', () => {
    window.open('/api/export/json', '_blank');
  });

  // Telemetry Polling Loop
  async function pollTelemetry() {
    try {
      const res = await fetch('/api/telemetry');
      if (res.ok) {
        const data = await res.json();
        const summary = data.summary || {};
        const logs = data.recent_events || [];

        // Update Header & FPS
        fpsDisplay.textContent = (summary.fps || 0.0).toFixed(1);
        if (summary.status === 'running') {
          streamStatusPill.classList.add('active');
          streamStatusText.textContent = 'LIVE FEED';
        }

        // Update KPIs
        valTotalLive.textContent = summary.total_live_count || 0;
        valInflow.textContent = summary.in_count || 0;
        valOutflow.textContent = summary.out_count || 0;
        
        const net = (summary.in_count || 0) - (summary.out_count || 0);
        valNetDelta.textContent = net >= 0 ? `+${net}` : `${net}`;

        // Update Bay Breakdown List
        const zoneCounts = summary.zone_counts || {};
        const zoneKeys = Object.keys(zoneCounts);
        if (zoneKeys.length > 0) {
          bayListContainer.innerHTML = zoneKeys
            .map((key, idx) => {
              const color = bayColorPalette[idx % bayColorPalette.length];
              return `
                <div class="bay-item">
                  <div class="bay-info">
                    <span class="bay-color-dot" style="background:${color};"></span>
                    <span class="bay-name">${key}</span>
                  </div>
                  <span class="bay-count">${zoneCounts[key]} units</span>
                </div>
              `;
            })
            .join('');
        }

        // Update Activity Table
        if (logs.length > 0) {
          eventTableBody.innerHTML = logs
            .slice(-10)
            .reverse()
            .map((log) => {
              const timeStr = log.timestamp ? log.timestamp.split('T')[1].split('.')[0] : '--:--:--';
              const dirColor = log.direction === 'IN' ? 'var(--accent-green)' : 'var(--accent-orange)';
              return `
                <tr>
                  <td>${timeStr}</td>
                  <td>#${log.track_id}</td>
                  <td>${log.class || 'tire'}</td>
                  <td style="color:${dirColor}; font-weight:700;">${log.direction}</td>
                </tr>
              `;
            })
            .join('');
        }
      }
    } catch (err) {
      console.warn('Telemetry polling error:', err);
    } finally {
      setTimeout(pollTelemetry, 500);
    }
  }

  // Start polling
  pollTelemetry();
});
