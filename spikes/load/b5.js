// B5 load test (#94, System Design 12.1): mixed API traffic at a fixed arrival rate
// plus Blind learners sending a heartbeat every 5 s (System Design 9.2).
//
// Run by `spike-b5` (spikes/src/listenup_spikes/b5_load.py), which seeds the learners
// with apps/api/scripts/seed_load.py and passes the manifest. Every request carries the
// tags the runner groups by: kind (read, write or heartbeat), name (method and route)
// and phase (warmup or measure).
import exec from "k6/execution";
import http from "k6/http";
import { Counter } from "k6/metrics";
import { sleep } from "k6";

const BASE = `${__ENV.BASE_URL || "http://api:8000"}/api/v1`;
const MIXED_RPS = Number(__ENV.MIXED_RPS || 15);
const BLIND_LEARNERS = Number(__ENV.BLIND_LEARNERS || 20);
const WARMUP_S = Number(__ENV.WARMUP_S || 60);
const DURATION_S = Number(__ENV.DURATION_S || 600);
const TOTAL_S = WARMUP_S + DURATION_S;
const HEARTBEAT_S = 5;
const CSRF = "b5-load-test";

const manifest = JSON.parse(open(__ENV.MANIFEST));
const learners = manifest.learners;
const passage = manifest.passage;

const blindStops = new Counter("blind_stops");

// Mixed traffic: each flow is one or two requests; the weights give about 74% reads and
// 26% writes by request (the plan in docs/spikes/94-b5-load-test.md).
const FLOWS = [
  { weight: 10, requests: 1, run: (l) => get("GET /me", "/me") },
  { weight: 10, requests: 1, run: (l) => get("GET /sessions", "/sessions") },
  {
    weight: 20,
    requests: 1,
    run: (l) => get("GET /sessions/{id}", `/sessions/${pick(Object.values(l.sessions))}`),
  },
  { weight: 8, requests: 1, run: (l) => get("GET /library/contents", "/library/contents") },
  { weight: 4, requests: 1, run: (l) => get("GET /contents", "/contents") },
  {
    weight: 8,
    requests: 1,
    run: (l) =>
      get("GET /sessions/{id}/transcript", `/sessions/${l.sessions.transcript}/transcript`),
  },
  {
    weight: 8,
    requests: 1,
    run: (l) => get("GET /sessions/{id}/marks", `/sessions/${l.sessions.transcript}/marks`),
  },
  { weight: 4, requests: 1, run: (l) => get("GET /cards", "/cards") },
  {
    weight: 4,
    requests: 1,
    run: (l) => get("GET /sessions/{id}/blind", `/sessions/${l.sessions.blind}/blind`),
  },
  {
    weight: 4,
    requests: 1,
    run: (l) =>
      get("GET /dictation/attempts/{id}", `/dictation/attempts/${l.dictation_attempt_id}`),
  },
  { weight: 6, requests: 2, run: (l) => autosaveDraft(l) },
  { weight: 5, requests: 2, run: (l) => markAndUnmark(l) },
  {
    weight: 6,
    requests: 1,
    run: (l) =>
      send("write", "PATCH /sessions/{id}/marks/{id}", "PATCH",
        `/sessions/${l.sessions.transcript}/marks/${l.mark_id}`, { note: `heard ${Date.now()}` }),
  },
];
const TOTAL_WEIGHT = FLOWS.reduce((sum, f) => sum + f.weight, 0);
const REQUESTS_PER_FLOW = FLOWS.reduce((sum, f) => sum + f.weight * f.requests, 0) / TOTAL_WEIGHT;

export const options = {
  discardResponseBodies: false,
  scenarios: {
    mixed: {
      executor: "constant-arrival-rate",
      // Flows per minute that make MIXED_RPS requests per second on average.
      rate: Math.round((MIXED_RPS * 60) / REQUESTS_PER_FLOW),
      timeUnit: "1m",
      duration: `${TOTAL_S}s`,
      preAllocatedVUs: 30,
      maxVUs: 200,
      exec: "mixed",
    },
    blind: {
      executor: "per-vu-iterations",
      vus: BLIND_LEARNERS,
      iterations: 1,
      maxDuration: `${TOTAL_S + 30}s`,
      exec: "blind",
    },
  },
};

export function setup() {
  if (learners.length < BLIND_LEARNERS) {
    throw new Error(`the manifest has ${learners.length} learners, fewer than ${BLIND_LEARNERS}`);
  }
  return { startedAt: Date.now() };
}

let startedAt = 0;

function phase() {
  return Date.now() - startedAt < WARMUP_S * 1000 ? "warmup" : "measure";
}

function headers(learner, json) {
  const cookies = manifest.cookies;
  const h = {
    Cookie: `${cookies.session}=${learner.token}; ${cookies.csrf}=${CSRF}`,
    "X-CSRF-Token": CSRF,
  };
  if (json) h["Content-Type"] = "application/json";
  return h;
}

function request(learner, kind, name, method, path, body) {
  return http.request(method, `${BASE}${path}`, body === undefined ? null : JSON.stringify(body), {
    headers: headers(learner, body !== undefined),
    tags: { kind, name, phase: phase() },
    timeout: "10s",
  });
}

function pick(items) {
  return items[Math.floor(Math.random() * items.length)];
}

function uuid4() {
  const hex = [...Array(32)].map(() => Math.floor(Math.random() * 16).toString(16));
  hex[12] = "4";
  hex[16] = ((parseInt(hex[16], 16) & 0x3) | 0x8).toString(16);
  const s = hex.join("");
  return `${s.slice(0, 8)}-${s.slice(8, 12)}-${s.slice(12, 16)}-${s.slice(16, 20)}-${s.slice(20)}`;
}

// Bound to the iteration's learner by `mixed` below.
let current = null;
const get = (name, path) => request(current, "read", name, "GET", path);
const send = (kind, name, method, path, body) => request(current, kind, name, method, path, body);

function autosaveDraft(learner) {
  // As the Dictation page does: resume the attempt for its draft version, then save.
  const opened = send("write", "POST /sessions/{id}/dictation/attempts", "POST",
    `/sessions/${learner.sessions.dictation}/dictation/attempts`);
  if (opened.status !== 200 && opened.status !== 201) return;
  const work = opened.json();
  send("write", "PUT /dictation/attempts/{id}/draft", "PUT",
    `/dictation/attempts/${work.id}/draft`,
    { draft_text: `So the first thing ${Date.now() % 1000}`, draft_version: work.draft_version });
}

function markAndUnmark(learner) {
  // Words 5 and 6 of the seeded transcript; the seeded mark covers words 0 and 1.
  const session = learner.sessions.transcript;
  const id = uuid4();
  const made = send("write", "POST /sessions/{id}/marks", "POST", `/sessions/${session}/marks`,
    { id, word_from: 5, word_to: 6 });
  if (made.status !== 201) return;
  send("write", "DELETE /sessions/{id}/marks/{id}", "DELETE",
    `/sessions/${session}/marks/${id}`);
}

export function mixed(data) {
  startedAt = data.startedAt;
  // Round robin over learners: at stage-0 rates a learner's previous flow has long
  // finished, so a draft version or a mark is never raced by the load itself.
  current = learners[exec.scenario.iterationInTest % learners.length];
  let roll = Math.random() * TOTAL_WEIGHT;
  for (const flow of FLOWS) {
    roll -= flow.weight;
    if (roll < 0) {
      flow.run(current);
      return;
    }
  }
}

// True when the listen is over. A beat that got no answer is not the end: the player
// keeps its clock and sends the next beat (one lost beat is a 10 s gap, under the
// server's 15 s silence limit), so the heartbeat load does not collapse into restarts.
function stopped(response) {
  if (response.status === 0) return false;
  if (response.status !== 200) return true; // a refusal; the request summary lists it
  const answer = response.json();
  if (answer.action === "stop") {
    blindStops.add(1, { reason: answer.attempt.void_reason || "stopped", phase: phase() });
    return true;
  }
  return false;
}

export function blind(data) {
  startedAt = data.startedAt;
  const learner = learners[exec.scenario.iterationInTest];
  const lengthMs = passage.end_ms - passage.start_ms;
  for (const session of learner.blind_sessions) {
    if (Date.now() - startedAt > TOTAL_S * 1000) return;
    const started = request(learner, "write", "POST /sessions/{id}/blind/attempts", "POST",
      `/sessions/${session}/blind/attempts`);
    if (started.status !== 201) continue;
    const attempt = started.json().attempt.id;
    const t0 = Date.now();
    const beat = (body) => request(learner, "heartbeat", "POST /blind/attempts/{id}/heartbeat",
      "POST", `/blind/attempts/${attempt}/heartbeat`, body);
    let ended = false;
    if (stopped(beat({ position_ms: passage.start_ms, state: "playing" }))) continue;
    while (!ended) {
      if (Date.now() - startedAt > TOTAL_S * 1000) return;
      sleep(HEARTBEAT_S);
      const elapsed = Date.now() - t0;
      ended = elapsed >= lengthMs;
      const body = ended
        ? { position_ms: passage.end_ms, state: "ended" }
        : { position_ms: passage.start_ms + elapsed, state: "playing" };
      if (stopped(beat(body))) break;
    }
  }
}
