'use strict';

// ── FIT Analyzer user profile ─────────────────────────────────────────────────
// Separate from the ERG controller's profile.js — different fields, different key.
// Auto-saves on every input change (no Save button needed).

const fitAnalyzerProfile = {
  restHR:      43,
  maxHR:       173,
  weight:      68,    // kg
  ftpOutdoor:  297,
  ftpIndoor:   250,
};

const FA_PROFILE_KEY = 'fit_analyzer_profile_v1';

function faLoadProfile() {
  try {
    const saved = localStorage.getItem(FA_PROFILE_KEY);
    if (saved) Object.assign(fitAnalyzerProfile, JSON.parse(saved));
  } catch (_) {}
  faWriteToDOM();
}

function faSaveProfile() {
  faReadFromDOM();
  localStorage.setItem(FA_PROFILE_KEY, JSON.stringify(fitAnalyzerProfile));
}

function faReadFromDOM() {
  fitAnalyzerProfile.restHR     = parseInt(document.getElementById('fa-rest').value)     || fitAnalyzerProfile.restHR;
  fitAnalyzerProfile.maxHR      = parseInt(document.getElementById('fa-maxhr').value)     || fitAnalyzerProfile.maxHR;
  fitAnalyzerProfile.weight     = parseFloat(document.getElementById('fa-weight').value)  || fitAnalyzerProfile.weight;
  fitAnalyzerProfile.ftpOutdoor = parseInt(document.getElementById('fa-ftp-out').value)   || fitAnalyzerProfile.ftpOutdoor;
  fitAnalyzerProfile.ftpIndoor  = parseInt(document.getElementById('fa-ftp-in').value)    || fitAnalyzerProfile.ftpIndoor;
}

function faWriteToDOM() {
  document.getElementById('fa-rest').value    = fitAnalyzerProfile.restHR;
  document.getElementById('fa-maxhr').value   = fitAnalyzerProfile.maxHR;
  document.getElementById('fa-weight').value  = fitAnalyzerProfile.weight;
  document.getElementById('fa-ftp-out').value = fitAnalyzerProfile.ftpOutdoor;
  document.getElementById('fa-ftp-in').value  = fitAnalyzerProfile.ftpIndoor;
}

// Returns the appropriate FTP for this activity type.
function faGetFtp(isIndoor) {
  return isIndoor ? fitAnalyzerProfile.ftpIndoor : fitAnalyzerProfile.ftpOutdoor;
}

// Wire up auto-save: call after DOM is ready.
function faInitProfileListeners() {
  ['fa-rest', 'fa-maxhr', 'fa-weight', 'fa-ftp-out', 'fa-ftp-in'].forEach(id => {
    document.getElementById(id).addEventListener('change', () => {
      faSaveProfile();
      // Re-render summary if a file is loaded
      if (typeof onProfileChange === 'function') onProfileChange();
    });
  });
}
