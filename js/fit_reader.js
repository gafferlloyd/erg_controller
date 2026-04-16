'use strict';

// ── FIT binary reader ─────────────────────────────────────────────────────────
// parseFit(ArrayBuffer) → { records, isIndoor, hasAltitude, startMs }
//
// records: [{ elapsed,          ← seconds from first record
//             hr,               ← bpm (null if absent/invalid)
//             power,            ← watts
//             cadence,          ← rpm
//             speed,            ← km/h
//             altitude,         ← metres (null if absent)
//             distance }]       ← metres cumulative
//
// Handles: normal + compressed-timestamp headers, dev-field definitions,
//          little-endian and big-endian FIT files.

// FIT epoch: seconds since 1989-12-31 00:00:00 UTC
const FIT_EPOCH = 631065600;

// ── Low-level helpers ─────────────────────────────────────────────────────────

function readUInt(b, pos, len, be) {
  let v = 0;
  if (be) { for (let i = 0;       i < len;  i++) v = v * 256 + b[pos + i]; }
  else     { for (let i = len - 1; i >= 0;  i--) v = v * 256 + b[pos + i]; }
  return v;
}

function isInvalid(val, size) {
  if (size === 1) return val === 0xFF;
  if (size === 2) return val === 0xFFFF;
  if (size === 4) return val === 0xFFFFFFFF;
  return false;
}

// ── Field extractor for a data message ────────────────────────────────────────
// Returns a plain object; keys depend on globalNum (20=Record, 18=Session).

function extractFields(b, pos, def) {
  const out = {};
  let offset = 0;
  for (const f of def.fields) {
    const val = readUInt(b, pos + offset, f.size, def.be);
    offset += f.size;
    if (isInvalid(val, f.size)) continue;

    if (f.fieldNum === 253) {                        // timestamp (all msgs)
      out._ts = val;
    } else if (def.globalNum === 20) {               // Record message
      if      (f.fieldNum === 3)  out.hr       = val;
      else if (f.fieldNum === 7)  out.power    = val;
      else if (f.fieldNum === 4)  out.cadence  = val;
      else if (f.fieldNum === 6)  out.speed    = val / 1000 * 3.6;   // mm/s → km/h
      else if (f.fieldNum === 2)  out.altitude = val / 5 - 500;      // raw → metres
      else if (f.fieldNum === 78) out.altEnhanced = val / 5 - 500;   // enhanced_altitude
      else if (f.fieldNum === 5)  out.distance = val / 100;           // cm → m
    } else if (def.globalNum === 18) {               // Session message
      if      (f.fieldNum === 5)  out.sport    = val;
      else if (f.fieldNum === 6)  out.subSport = val;
    }
  }
  return out;
}

// ── Main parser ───────────────────────────────────────────────────────────────

function parseFit(buffer) {
  const b = new Uint8Array(buffer);

  // Validate ".FIT" magic
  if (b[8] !== 0x2E || b[9] !== 0x46 || b[10] !== 0x49 || b[11] !== 0x54) {
    throw new Error('Not a valid FIT file');
  }

  const headerSize = b[0];
  const dataSize   = readUInt(b, 4, 4, false);
  const dataEnd    = headerSize + dataSize;

  const defs    = {};       // localMsgType → def object
  const rawRecs = [];       // unprocessed record objects with _ts
  let refTs     = 0;        // rolling reference for compressed timestamps
  let isIndoor  = false;

  let pos = headerSize;

  while (pos < dataEnd) {
    const hdr = b[pos++];

    // ── Compressed timestamp header (bit 7 set) ────────────────────────────
    if (hdr & 0x80) {
      const localType = (hdr >> 5) & 0x03;
      const tsOffset  = hdr & 0x1F;
      // 5-bit rollover from reference
      if (tsOffset >= (refTs & 0x1F)) {
        refTs = (refTs & 0xFFFFFFE0) | tsOffset;
      } else {
        refTs = ((refTs & 0xFFFFFFE0) | tsOffset) + 0x20;
      }
      const def = defs[localType];
      if (def && def.globalNum === 20) {
        const rec = extractFields(b, pos, def);
        rec._ts = refTs;
        rawRecs.push(rec);
      }
      if (def) pos += def.dataSize;
      continue;
    }

    // ── Definition message (bit 6 set) ────────────────────────────────────
    if (hdr & 0x40) {
      const hasDevFields = !!(hdr & 0x20);
      const localType    = hdr & 0x0F;
      pos++;                                 // reserved byte
      const arch         = b[pos++];
      const be           = arch === 1;
      const globalNum    = readUInt(b, pos, 2, be);
      pos += 2;
      const numFields    = b[pos++];
      const fields       = [];
      let   dataSize     = 0;
      for (let i = 0; i < numFields; i++) {
        const fieldNum = b[pos++];
        const size     = b[pos++];
        /*baseType*/     b[pos++];
        fields.push({ fieldNum, size });
        dataSize += size;
      }
      if (hasDevFields) {
        const nDev = b[pos++];
        for (let i = 0; i < nDev; i++) {
          pos++;                             // field number
          const sz = b[pos++];
          pos++;                             // dev data index
          dataSize += sz;
        }
      }
      defs[localType] = { globalNum, fields, be, dataSize };
      continue;
    }

    // ── Normal data message ───────────────────────────────────────────────
    const localType = hdr & 0x0F;
    const def       = defs[localType];
    if (!def) { pos++; continue; }

    if (def.globalNum === 20) {
      const rec = extractFields(b, pos, def);
      if (rec._ts != null) refTs = rec._ts;
      else rec._ts = refTs;
      rawRecs.push(rec);
    } else if (def.globalNum === 18) {
      const sess = extractFields(b, pos, def);
      // sub_sport 6 = indoor_cycling, 58 = virtual_activity
      if (sess.subSport === 6 || sess.subSport === 58) isIndoor = true;
    }
    pos += def.dataSize;
  }

  if (!rawRecs.length) throw new Error('No record data found in FIT file');

  // Sort by timestamp and build elapsed-second records
  rawRecs.sort((a, b) => a._ts - b._ts);
  const t0 = rawRecs[0]._ts;
  const startMs = (t0 + FIT_EPOCH) * 1000;

  const records = rawRecs.map(r => {
    const rec = { elapsed: r._ts - t0 };
    if (r.hr        != null) rec.hr       = r.hr;
    if (r.power     != null) rec.power    = r.power;
    if (r.cadence   != null) rec.cadence  = r.cadence;
    if (r.speed     != null) rec.speed    = r.speed;
    if (r.distance  != null) rec.distance = r.distance;
    // Prefer enhanced altitude
    const alt = r.altEnhanced ?? r.altitude;
    if (alt != null) rec.altitude = alt;
    return rec;
  });

  // Detect real altitude: reject if all values identical (flat/no GPS)
  const alts = records.map(r => r.altitude).filter(v => v != null);
  const hasAltitude = alts.length > 10 &&
    alts.some(v => Math.abs(v - alts[0]) > 2);

  return { records, isIndoor, hasAltitude, startMs };
}
