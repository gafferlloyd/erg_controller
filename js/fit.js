'use strict';

// ── FIT binary file writer ────────────────────────────────────────────────────
// Generates a minimal valid .fit file from the session samples array.
// Implements: File ID, Record (1 Hz), Session, Activity messages.
//
// FIT CRC-16 uses the standard CCITT table baked in below.

// ── CRC-16 ─────────────────────────────────────────────────────────────────────
// Garmin FIT SDK table and algorithm (verbatim from FitCrc_Get16 in the SDK).

const FIT_CRC_TABLE = new Uint16Array([
  0x0000, 0xCC01, 0xD801, 0x1400, 0xF001, 0x3C00, 0x2800, 0xE401,
  0xA001, 0x6C00, 0x7800, 0xB401, 0x5000, 0x9C01, 0x8801, 0x4400,
]);

function fitCrc(bytes) {
  let crc = 0;
  for (const byte of bytes) {
    let tmp = FIT_CRC_TABLE[crc & 0x0F];
    crc = (crc >> 4) & 0x0FFF;
    crc = crc ^ tmp ^ FIT_CRC_TABLE[byte & 0x0F];
    tmp = FIT_CRC_TABLE[crc & 0x0F];
    crc = (crc >> 4) & 0x0FFF;
    crc = crc ^ tmp ^ FIT_CRC_TABLE[(byte >> 4) & 0x0F];
  }
  return crc;
}

// ── Little-endian write helpers ───────────────────────────────────────────────

function u8(v)  { return [v & 0xFF]; }
function u16(v) { return [v & 0xFF, (v >> 8) & 0xFF]; }
function u32(v) { return [v & 0xFF, (v >> 8) & 0xFF, (v >> 16) & 0xFF, (v >> 24) & 0xFF]; }
function i16(v) { const n = v < 0 ? v + 65536 : v; return u16(n); }

// FIT timestamp: seconds since 1989-12-31 00:00:00 UTC
const FIT_EPOCH_OFFSET = 631065600;  // Unix epoch of FIT epoch (seconds)
function toFitTs(msEpoch) {
  return Math.round(msEpoch / 1000) - FIT_EPOCH_OFFSET;
}

// ── Definition + data message builders ───────────────────────────────────────
// Returns arrays of bytes.

// Definition message header: local msg type 0, arch little-endian.
function defMsg(localMsgType, globalMsgNum, fields) {
  // fields: [{fieldDef, size, baseType}]
  const bytes = [
    0x40 | (localMsgType & 0x0F),   // definition header
    0x00,                            // reserved
    0x00,                            // architecture: little-endian
    ...u16(globalMsgNum),
    fields.length,
  ];
  for (const f of fields) {
    bytes.push(f.fieldDef, f.size, f.baseType);
  }
  return bytes;
}

// Data message header
function dataHeader(localMsgType) { return localMsgType & 0x0F; }

// ── File ID message (global 0) ────────────────────────────────────────────────
// Fields: type (field 0, uint8), manufacturer (1, uint16), product (2, uint16),
//         serial (3, uint32), time_created (4, uint32), number (5, uint16)

function buildFileIdDef() {
  return defMsg(0, 0, [
    { fieldDef: 0, size: 1, baseType: 0x00 },  // type uint8
    { fieldDef: 1, size: 2, baseType: 0x84 },  // manufacturer uint16
    { fieldDef: 2, size: 2, baseType: 0x84 },  // product uint16
    { fieldDef: 3, size: 4, baseType: 0x8C },  // serial uint32
    { fieldDef: 4, size: 4, baseType: 0x86 },  // time_created uint32
  ]);
}

function buildFileIdData(fitTs) {
  return [
    dataHeader(0),
    4,             // type = activity
    ...u16(255),   // manufacturer = development
    ...u16(0),     // product
    ...u32(1),     // serial
    ...u32(fitTs), // time_created
  ];
}

// ── Record message (global 20) ────────────────────────────────────────────────
// Fields: timestamp (253, uint32), heart_rate (3, uint8), power (7, uint16),
//         cadence (4, uint8), speed (6, uint16 — unused, set to invalid)

function buildRecordDef() {
  return defMsg(1, 20, [
    { fieldDef: 253, size: 4, baseType: 0x86 }, // timestamp uint32
    { fieldDef: 3,   size: 1, baseType: 0x02 }, // heart_rate uint8
    { fieldDef: 7,   size: 2, baseType: 0x84 }, // power uint16
    { fieldDef: 4,   size: 1, baseType: 0x02 }, // cadence uint8
    { fieldDef: 6,   size: 2, baseType: 0x84 }, // speed uint16 (scale 1000 = mm/s)
  ]);
}

function buildRecordData(fitTs, hr, power, cadence, speed) {
  // FIT speed: m/s × 1000 stored as uint16; 0xFFFF = invalid
  const speedMms = (speed != null) ? Math.min(0xFFFE, Math.round(speed / 3.6 * 1000)) : 0xFFFF;
  return [
    dataHeader(1),
    ...u32(fitTs),
    hr      != null ? (hr      & 0xFF)  : 0xFF,
    ...( power   != null ? u16(power)   : [0xFF, 0xFF] ),
    cadence != null ? (cadence & 0xFF)  : 0xFF,
    ...u16(speedMms),
  ];
}

// ── Session message (global 18) ───────────────────────────────────────────────
// Fields: message_index, timestamp, start_time, total_elapsed_time,
//         total_timer_time, sport, sub_sport, avg_heart_rate, avg_power,
//         normalized_power, total_calories, training_stress_score

function buildSessionDef() {
  return defMsg(2, 18, [
    { fieldDef: 254, size: 2, baseType: 0x84 }, // message_index uint16
    { fieldDef: 253, size: 4, baseType: 0x86 }, // timestamp uint32
    { fieldDef: 2,   size: 4, baseType: 0x86 }, // start_time uint32
    { fieldDef: 7,   size: 4, baseType: 0x86 }, // total_elapsed_time uint32 (ms)
    { fieldDef: 8,   size: 4, baseType: 0x86 }, // total_timer_time uint32 (ms)
    { fieldDef: 5,   size: 1, baseType: 0x00 }, // sport uint8 (2 = cycling)
    { fieldDef: 6,   size: 1, baseType: 0x00 }, // sub_sport uint8 (6 = indoor)
    { fieldDef: 16,  size: 1, baseType: 0x02 }, // avg_heart_rate uint8
    { fieldDef: 20,  size: 2, baseType: 0x84 }, // avg_power uint16
    { fieldDef: 34,  size: 2, baseType: 0x84 }, // normalized_power uint16
    { fieldDef: 11,  size: 2, baseType: 0x84 }, // total_calories uint16
    { fieldDef: 9,   size: 4, baseType: 0x86 }, // total_distance uint32 (scale 100 = cm)
    { fieldDef: 14,  size: 2, baseType: 0x84 }, // avg_speed uint16 (scale 1000 = mm/s)
  ]);
}

function buildSessionData(startTs, endTs, sampleArr) {
  const valid  = sampleArr.filter(s => s.power != null && s.power > 0);
  const avgPwr = valid.length ? Math.round(valid.reduce((a, s) => a + s.power, 0) / valid.length) : 0;
  const np     = calcNP(sampleArr) || avgPwr;
  const hrVals = sampleArr.filter(s => s.hr > 0);
  const avgHR  = hrVals.length ? Math.round(hrVals.reduce((a, s) => a + s.hr, 0) / hrVals.length) : 0;
  const durMs  = sampleArr.length * 1000;
  const cal    = estimateCalories(sampleArr);

  // Distance: integrate speed (km/h → m/s × 1 s per sample)
  const totalDistM  = sampleArr.reduce((acc, s) => acc + (s.speed != null ? s.speed / 3.6 : 0), 0);
  const distCm      = Math.round(totalDistM * 100);
  const spdVals     = sampleArr.filter(s => s.speed != null && s.speed > 0);
  const avgSpdKmh   = spdVals.length ? spdVals.reduce((a, s) => a + s.speed, 0) / spdVals.length : 0;
  const avgSpdMms   = Math.round(avgSpdKmh / 3.6 * 1000);

  return [
    dataHeader(2),
    ...u16(0),               // message_index
    ...u32(endTs),
    ...u32(startTs),
    ...u32(durMs),           // total_elapsed_time in ms
    ...u32(durMs),           // total_timer_time
    2,                       // sport = cycling
    6,                       // sub_sport = indoor
    avgHR & 0xFF,
    ...u16(avgPwr),
    ...u16(np),
    ...u16(cal),
    ...u32(distCm),          // total_distance in cm
    ...u16(avgSpdMms),       // avg_speed in mm/s
  ];
}

// ── Activity message (global 34) ─────────────────────────────────────────────

function buildActivityDef() {
  return defMsg(3, 34, [
    { fieldDef: 253, size: 4, baseType: 0x86 }, // timestamp uint32
    { fieldDef: 1,   size: 4, baseType: 0x86 }, // total_timer_time uint32
    { fieldDef: 2,   size: 2, baseType: 0x84 }, // num_sessions uint16
    { fieldDef: 3,   size: 1, baseType: 0x00 }, // type uint8
    { fieldDef: 4,   size: 1, baseType: 0x00 }, // event uint8
    { fieldDef: 5,   size: 1, baseType: 0x00 }, // event_type uint8
  ]);
}

function buildActivityData(endTs, durationMs) {
  return [
    dataHeader(3),
    ...u32(endTs),
    ...u32(durationMs),
    ...u16(1),  // num_sessions
    0,          // type = manual
    26,         // event = activity
    1,          // event_type = stop
  ];
}

// ── Calorie estimator (crude: 3.5 ml/kg/min from power) ──────────────────────
function estimateCalories(sampleArr) {
  const valid = sampleArr.filter(s => s.power != null && s.power > 0);
  if (!valid.length) return 0;
  const avgW = valid.reduce((a, s) => a + s.power, 0) / valid.length;
  const durH = sampleArr.length / 3600;
  // ~1 kcal ≈ 4.18 kJ; mechanical efficiency ~25%
  return Math.round(avgW * durH * 3600 / 4180 / 0.25);
}

// ── Assemble complete FIT file ────────────────────────────────────────────────

function buildFitFile(sampleArr, startMs) {
  if (!sampleArr.length) throw new Error('No samples to export');

  const startTs = toFitTs(startMs);
  const endTs   = toFitTs(startMs + sampleArr.length * 1000);

  const messages = [];

  // Definition messages
  messages.push(buildFileIdDef());
  messages.push(buildRecordDef());
  messages.push(buildSessionDef());
  messages.push(buildActivityDef());

  // File ID
  messages.push(buildFileIdData(startTs));

  // Records — one per sample
  sampleArr.forEach((s, i) => {
    const ts = startTs + i;
    messages.push(buildRecordData(ts, s.hr, s.power, s.cadence, s.speed));
  });

  // Session + Activity
  messages.push(buildSessionData(startTs, endTs, sampleArr));
  messages.push(buildActivityData(endTs, sampleArr.length * 1000));

  // Flatten to Uint8Array
  const flat = messages.flat();
  const body = new Uint8Array(flat);

  // FIT file header (14 bytes)
  const dataSize  = body.length;
  const headerBytes = [
    14,                          // header size
    0x10,                        // protocol version 1.0
    ...u16(2132),                // profile version 21.32
    ...u32(dataSize),            // data size (excludes header and footer CRC)
    0x2E, 0x46, 0x49, 0x54,     // ".FIT"
  ];
  const headerCRC = fitCrc(headerBytes);
  headerBytes.push(...u16(headerCRC));

  // Combine header + body
  const combined = new Uint8Array(headerBytes.length + body.length + 2);
  combined.set(headerBytes, 0);
  combined.set(body, headerBytes.length);

  // Footer CRC over entire file (header + body)
  const fileCRC = fitCrc(combined.subarray(0, headerBytes.length + body.length));
  combined[headerBytes.length + body.length]     = fileCRC & 0xFF;
  combined[headerBytes.length + body.length + 1] = (fileCRC >> 8) & 0xFF;

  return combined;
}

// ── Public download functions ─────────────────────────────────────────────────

function downloadFit() {
  if (!samples.length) { log('No session data to export', 'warn'); return; }
  try {
    const fitBytes = buildFitFile(samples, sessionStart || Date.now() - samples.length * 1000);
    const blob = new Blob([fitBytes], { type: 'application/octet-stream' });
    triggerDownload(`erg_session_${dateStamp()}.fit`, blob);
    log('FIT file exported', 'ok');
  } catch (e) {
    log(`FIT export failed: ${e.message}`, 'err');
  }
}

function downloadCsv() {
  if (!samples.length) { log('No session data to export', 'warn'); return; }
  const startMs = sessionStart || (Date.now() - samples.length * 1000);
  const rows = ['time_s,elapsed_s,hr_bpm,power_w,cadence_rpm,rmssd_ms'];
  samples.forEach((s, i) => {
    const elapsed = Math.round((s.t - startMs) / 1000);
    rows.push([
      Math.round(s.t / 1000),
      elapsed,
      s.hr      ?? '',
      s.power   ?? '',
      s.cadence ?? '',
      s.rmssd   ?? '',
    ].join(','));
  });
  const blob = new Blob([rows.join('\n')], { type: 'text/csv' });
  triggerDownload(`erg_session_${dateStamp()}.csv`, blob);
  log('CSV exported', 'ok');
}

function dateStamp() {
  const d = new Date();
  return `${d.getFullYear()}${String(d.getMonth()+1).padStart(2,'0')}${String(d.getDate()).padStart(2,'0')}_${String(d.getHours()).padStart(2,'0')}${String(d.getMinutes()).padStart(2,'0')}`;
}
