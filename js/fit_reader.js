'use strict';

// ── FIT binary reader ─────────────────────────────────────────────────────────
// parseFit(ArrayBuffer) →
//   { records, presentFields, isIndoor, hasAltitude, startMs }
//
// records: [{ elapsed, [key]: value, … }]
//   All numeric Record-message fields are extracted dynamically.
//   Keys come from RECORD_FIELDS (see below). GPS lat/lon are excluded.
//
// presentFields: [{ key, name, unit }] ordered by field number (descending
//   so enhanced fields shadow basic ones for deduplication).

const FIT_EPOCH = 631065600;   // seconds since 1989-12-31 00:00:00 UTC

// ── Record-message (global 20) field registry ─────────────────────────────────
// GPS coords (0, 1) excluded — not useful as time series.
// Enhanced fields (66, 78) share key with basic (6, 2); both write same property,
// higher field-number wins for naming in presentFields.
const RECORD_FIELDS = {
  2:  { key: 'altitude',  name: 'Altitude',   unit: 'm',     scale: 0.2,    offset: -500 },
  3:  { key: 'hr',        name: 'HR',          unit: 'bpm'   },
  4:  { key: 'cadence',   name: 'Cadence',     unit: 'rpm'   },
  5:  { key: 'distance',  name: 'Distance',    unit: 'm',     scale: 0.01  },
  6:  { key: 'speed',     name: 'Speed',       unit: 'km/h',  scale: 0.0036 },
  7:  { key: 'power',     name: 'Power',       unit: 'W'     },
  9:  { key: 'grade',     name: 'Grade',       unit: '%',     scale: 0.01  },
  13: { key: 'temp',      name: 'Temp',        unit: '°C'    },
  30: { key: 'vspeed',    name: 'Vert Spd',    unit: 'm/s',   scale: 0.001 },
  31: { key: 'calories',  name: 'Calories',    unit: 'kcal'  },
  40: { key: 'lte',       name: 'L Torque',    unit: '%',     scale: 0.5   },
  41: { key: 'rte',       name: 'R Torque',    unit: '%',     scale: 0.5   },
  42: { key: 'lps',       name: 'L Smooth',    unit: '%',     scale: 0.5   },
  43: { key: 'rps',       name: 'R Smooth',    unit: '%',     scale: 0.5   },
  44: { key: 'cps',       name: 'Pedal Smt',   unit: '%',     scale: 0.5   },
  51: { key: 'thb',       name: 'tHb',         unit: 'g/dL',  scale: 0.01  },
  54: { key: 'smo2',      name: 'SmO2',        unit: '%',     scale: 0.1   },
  66: { key: 'speed',     name: 'Speed',       unit: 'km/h',  scale: 0.0036 }, // enhanced
  78: { key: 'altitude',  name: 'Altitude',    unit: 'm',     scale: 0.2,  offset: -500 }, // enhanced
};

// Native byte size per base type — fields where def.size ≠ nativeSize are arrays, skipped.
const BT_SIZE = {
  0x00:1, 0x01:1, 0x02:1, 0x07:1,
  0x83:2, 0x84:2, 0x8B:2,
  0x85:4, 0x86:4, 0x8C:4, 0x88:4,
  0x8E:8, 0x8F:8, 0x90:8, 0x89:8,
};

function isSigned(bt) { return bt===0x01 || bt===0x83 || bt===0x85 || bt===0x8E; }

function readUInt(b, pos, len, be) {
  let v = 0;
  if (be) { for (let i = 0;       i < len;  i++) v = v*256 + b[pos+i]; }
  else     { for (let i = len - 1; i >= 0;  i--) v = v*256 + b[pos+i]; }
  return v;
}

function toSigned(v, size) {
  const half = Math.pow(2, size*8 - 1);
  return v >= half ? v - half*2 : v;
}

function isInvalid(v, size, signed) {
  if (signed) {
    if (size===1) return v===0x7F;
    if (size===2) return v===0x7FFF;
    if (size===4) return v===0x7FFFFFFF;
  } else {
    if (size===1) return v===0xFF;
    if (size===2) return v===0xFFFF;
    if (size===4) return v===0xFFFFFFFF;
  }
  return false;
}

// ── Extract fields from one data message ──────────────────────────────────────

function extractFields(b, pos, def) {
  const out = {};
  let offset = 0;
  for (const f of def.fields) {
    const native = BT_SIZE[f.bt] || 0;
    if (f.size !== native) { offset += f.size; continue; }   // skip arrays

    let val = readUInt(b, pos + offset, f.size, def.be);
    offset += f.size;
    const signed = isSigned(f.bt);
    if (isInvalid(val, f.size, signed)) continue;
    if (signed) val = toSigned(val, f.size);

    if (f.fieldNum === 253) {
      out._ts = val;
    } else if (def.globalNum === 20) {
      const fd = RECORD_FIELDS[f.fieldNum];
      if (fd) {
        let v = val;
        if (fd.scale)  v *= fd.scale;
        if (fd.offset) v += fd.offset;
        out[fd.key] = parseFloat(v.toFixed(6));
      }
    } else if (def.globalNum === 18) {
      if (f.fieldNum === 5) out.sport    = val;
      if (f.fieldNum === 6) out.subSport = val;
    }
  }
  return out;
}

// ── Main parser ───────────────────────────────────────────────────────────────

function parseFit(buffer) {
  const b = new Uint8Array(buffer);
  if (b[8]!==0x2E || b[9]!==0x46 || b[10]!==0x49 || b[11]!==0x54)
    throw new Error('Not a valid FIT file');

  const headerSize = b[0];
  const dataEnd    = headerSize + readUInt(b, 4, 4, false);

  const defs    = {};
  const rawRecs = [];
  let refTs     = 0;
  let isIndoor  = false;
  let pos       = headerSize;

  while (pos < dataEnd) {
    const hdr = b[pos++];

    if (hdr & 0x80) {                              // compressed timestamp
      const localType = (hdr >> 5) & 0x03;
      const tsOffset  = hdr & 0x1F;
      refTs = tsOffset >= (refTs & 0x1F)
        ? (refTs & 0xFFFFFFE0) | tsOffset
        : ((refTs & 0xFFFFFFE0) | tsOffset) + 0x20;
      const def = defs[localType];
      if (def && def.globalNum === 20) {
        const rec = extractFields(b, pos, def);
        rec._ts = refTs;
        rawRecs.push(rec);
      }
      if (def) pos += def.dataSize;
      continue;
    }

    if (hdr & 0x40) {                              // definition message
      const hasDevFields = !!(hdr & 0x20);
      const localType    = hdr & 0x0F;
      pos++;                                       // reserved
      const arch      = b[pos++];
      const be        = arch === 1;
      const globalNum = readUInt(b, pos, 2, be);
      pos += 2;
      const numFields = b[pos++];
      const fields    = [];
      let   dataSize  = 0;
      for (let i = 0; i < numFields; i++) {
        const fieldNum = b[pos++], size = b[pos++], bt = b[pos++];
        fields.push({ fieldNum, size, bt });
        dataSize += size;
      }
      if (hasDevFields) {
        const nDev = b[pos++];
        for (let i = 0; i < nDev; i++) { pos++; dataSize += b[pos++]; pos++; }
      }
      defs[localType] = { globalNum, fields, be, dataSize };
      continue;
    }

    const localType = hdr & 0x0F;                 // data message
    const def       = defs[localType];
    if (!def) { pos++; continue; }

    if (def.globalNum === 20) {
      const rec = extractFields(b, pos, def);
      if (rec._ts != null) refTs = rec._ts; else rec._ts = refTs;
      rawRecs.push(rec);
    } else if (def.globalNum === 18) {
      const sess = extractFields(b, pos, def);
      if (sess.subSport === 6 || sess.subSport === 58) isIndoor = true;
    }
    pos += def.dataSize;
  }

  if (!rawRecs.length) throw new Error('No record data found in FIT file');

  rawRecs.sort((a, b) => a._ts - b._ts);
  const t0      = rawRecs[0]._ts;
  const startMs = (t0 + FIT_EPOCH) * 1000;
  const allKeys = [...new Set(Object.values(RECORD_FIELDS).map(f => f.key))];

  const records = rawRecs.map(r => {
    const rec = { elapsed: r._ts - t0 };
    for (const key of allKeys) { if (r[key] != null) rec[key] = r[key]; }
    return rec;
  });

  // Build presentFields; scan descending so enhanced fields name the key
  const seen = new Set();
  const presentFields = [];
  for (const fnum of Object.keys(RECORD_FIELDS).map(Number).sort((a,b) => b-a)) {
    const fd = RECORD_FIELDS[fnum];
    if (seen.has(fd.key)) continue;
    if (records.some(r => r[fd.key] != null)) {
      presentFields.push({ key: fd.key, name: fd.name, unit: fd.unit });
      seen.add(fd.key);
    }
  }

  const alts = records.map(r => r.altitude).filter(v => v != null);
  const hasAltitude = alts.length > 10 && alts.some(v => Math.abs(v - alts[0]) > 2);

  return { records, presentFields, isIndoor, hasAltitude, startMs };
}
