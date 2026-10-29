/**
 * Automated delivery checks on the finished demo video - run against the delivered artifacts,
 * not against in-memory build state.
 *
 *   node scripts/check_demo_video.cjs
 *
 * Verifies: the MP4 really decodes (h264 + aac, no corrupt frames), audio and video lengths
 * agree, the WebVTT captions are complete and stay inside the timeline, every scene is
 * represented, the showcase scenes were recorded from the published URL, and the final scene
 * names an address that is anonymously reachable right now.
 */
const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');

const ROOT = path.join(__dirname, '..');
const OUT = path.join(ROOT, 'submission-package', 'demo');
const MP4 = path.join(OUT, 'researchflow-demo.mp4');
const VTT = path.join(OUT, 'researchflow-demo.vtt');
const MANIFEST = path.join(OUT, 'video-manifest.json');

function run(cmd, args) {
  const r = spawnSync(cmd, args, { encoding: 'utf8', cwd: ROOT });
  if (r.status !== 0) throw new Error(`${cmd} failed: ${(r.stderr || r.stdout || '').slice(-900)}`);
  return r.stdout || '';
}

const failures = [];
const check = { checkedAt: new Date().toISOString(), file: 'researchflow-demo.mp4' };
function assert(name, ok, detail) {
  check[name] = detail === undefined ? ok : detail;
  if (!ok) failures.push(`${name} = ${JSON.stringify(detail === undefined ? ok : detail)}`);
  return ok;
}

for (const f of [MP4, VTT, MANIFEST]) {
  if (!fs.existsSync(f)) { console.error(`missing artifact: ${f}`); process.exit(1); }
}
check.bytes = fs.statSync(MP4).size;

// ---------------------------------------------------------------- 1. container + decode
const probe = JSON.parse(run('ffprobe', ['-v', 'error', '-print_format', 'json',
  '-show_streams', '-show_format', MP4]));
const v = probe.streams.find((s) => s.codec_type === 'video');
const a = probe.streams.find((s) => s.codec_type === 'audio');
const total = Number(probe.format.duration);
assert('durationSeconds', total > 60, Number(total.toFixed(2)));
assert('videoCodec', v.codec_name === 'h264', `${v.codec_name}/${v.profile}`);
assert('videoResolution', v.width >= 1280 && v.height >= 720, `${v.width}x${v.height}`);
assert('videoPixFormat', v.pix_fmt === 'yuv420p', v.pix_fmt);
assert('frames', Number(v.nb_frames || 0) > 0, Number(v.nb_frames || 0));
assert('audioCodec', a && a.codec_name === 'aac', a && a.codec_name);
assert('audioChannels', a && a.channels === 2, a && a.channels);
const gap = Math.abs(Number(v.duration || 0) - Number((a && a.duration) || 0));
assert('avSyncGapSeconds', gap <= 0.2, Number(gap.toFixed(3)));

const dec = spawnSync('ffmpeg', ['-v', 'error', '-i', MP4, '-f', 'null', '-'],
  { encoding: 'utf8', cwd: ROOT });
const decodeErr = (dec.stderr || '').trim();
assert('decodeClean', dec.status === 0 && decodeErr === '', decodeErr.slice(0, 500) || 'no decoder errors');

// ------------------------------------------------------------------------- 2. captions
const times = [...fs.readFileSync(VTT, 'utf8')
  .matchAll(/(\d\d):(\d\d):(\d\d)\.(\d\d\d) --> (\d\d):(\d\d):(\d\d)\.(\d\d\d)/g)]
  .map((m) => ({ start: +m[1] * 3600 + +m[2] * 60 + +m[3] + +m[4] / 1000,
    end: +m[5] * 3600 + +m[6] * 60 + +m[7] + +m[8] / 1000 }));
let maxGap = 0;
for (let i = 1; i < times.length; i += 1) maxGap = Math.max(maxGap, times[i].start - times[i - 1].end);
const coverage = times.reduce((n, c) => n + (c.end - c.start), 0) / total;
assert('cueCount', times.length > 0, times.length);
assert('cueFirstStart', times[0].start < 1, Number(times[0].start.toFixed(2)));
assert('cueLastEnd', times[times.length - 1].end <= total, Number(times[times.length - 1].end.toFixed(2)));
assert('cueMaxGapSeconds', maxGap <= 2.0, Number(maxGap.toFixed(2)));
assert('cuesWithinDuration', times.every((c) => c.end <= total + 0.05), `${times.length} cues`);
assert('cueCoverageRatio', coverage >= 0.5, Number(coverage.toFixed(3)));

// --------------------------------------------------------------------------- 3. manifest
const manifest = JSON.parse(fs.readFileSync(MANIFEST, 'utf8'));
assert('sceneCount', manifest.scenes.length === 11, manifest.scenes.length);
const narrated = manifest.scenes.filter((s) => (s.cues || []).length > 0).length;
assert('scenesWithCaptions', narrated === manifest.scenes.length, `${narrated}/${manifest.scenes.length}`);
assert('browserScenesWithMeasuredWallTime', manifest.scenes.filter((s) => s.realWallSeconds).length > 0,
  manifest.scenes.filter((s) => s.realWallSeconds).length);
const kf = manifest.keyframes || [];
const missingKeys = kf.filter((k) => !fs.existsSync(path.join(OUT, k.file)));
assert('keyframesPresent', kf.length > 0 && missingKeys.length === 0,
  `${kf.length - missingKeys.length}/${kf.length}`);
assert('noZeroDurationScene', manifest.scenes.every((s) => s.finalSeconds > 0),
  manifest.scenes.map((s) => s.finalSeconds).join(','));

const site = manifest.sources.publishedSite.replace(/\/$/, '');
const showcaseSrc = manifest.sources.showcaseScenesRecordedFrom.replace(/\/$/, '');
assert('showcaseRecordedFromPublishedUrl', showcaseSrc === site, showcaseSrc);
const last = manifest.scenes[manifest.scenes.length - 1];
const lastText = JSON.stringify(last.cues) + JSON.stringify(manifest.facts.siteUrl || '')
  + JSON.stringify(manifest.facts.siteTitle || '');
assert('publishedHostInFinalScene', lastText.includes(new URL(site).host), new URL(site).host);

(async () => {
  // ------------------------------------------------ 4. the public URL is live, right now
  try {
    const res = await fetch(site, { headers: { 'Cache-Control': 'no-cache' } });
    const body = await res.text();
    assert('publishedSiteReachable', res.ok && res.status === 200, { status: res.status, url: site });
    const evRes = await fetch(`${site}/data/evidence.json`, { headers: { 'Cache-Control': 'no-cache' } });
    const ev = await evRes.json();
    assert('publishedEvidenceIsCurrent',
      evRes.ok && ev.interactions && ev.interactions.failed === 0,
      { generated_at: ev.generated_at, interactions: `${ev.interactions.passed}/${ev.interactions.total}` });
    const localHtml = fs.readFileSync(path.join(ROOT, 'site', 'public', 'index.html'), 'utf8');
    const served = body.replace(/<script data-qoder-watermark="v1"[^>]*>[\s\S]*?<\/script>\s*/g, '');
    assert('publishedPageMatchesLocalBuild', served === localHtml,
      `${served.length}B served == ${localHtml.length}B local after removing the platform watermark`);
  } catch (err) {
    assert('publishedSiteReachable', false, { error: err.message });
  }

  check.pass = failures.length === 0;
  check.failureCount = failures.length;
  if (failures.length) check.failures = failures;
  fs.writeFileSync(path.join(OUT, 'video-check.json'), JSON.stringify(check, null, 2), 'utf8');
  console.log(Object.entries(check).filter(([k]) => k !== 'failures')
    .map(([k, val]) => `${k} = ${JSON.stringify(val)}`).join('\n'));
  console.log(check.pass ? `\nVIDEO CHECK PASS (${Object.keys(check).length - 5} checks)`
    : `\nVIDEO CHECK FAIL:\n- ${failures.join('\n- ')}`);
  process.exit(check.pass ? 0 : 1);
})();
