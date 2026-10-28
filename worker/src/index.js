// line-agent-kit の Webhook サーバー（Cloudflare Workers・無料プランで動く形）
// 入口:
//   POST /webhook          LINE からの Webhook（署名を必ず確かめる）
//   POST /stripe/webhook   Stripe の決済完了（STRIPE_WEBHOOK_SECRET があるときだけ）
//   GET  /health           生きているか
//   /admin/*               scripts/ から使う管理用（ADMIN_TOKEN が要る）
// 定期実行（cron）: ステップ配信・予約のリマインド・古い控えの掃除
//
// 流れの中身（あいさつ・ステップ・キーワード…）は config/flow.json に書き、
// scripts/build_flow.py で src/flow.generated.js に変換してから deploy する。

import FLOW from "./flow.generated.js";

const MAX_BATCHES_PER_RUN = 30;   // 無料プランは1回の呼び出しで外への通信50回まで。余裕を残す
const MAX_PUSH_PER_RUN = 30;
const EVENT_KEEP_SECONDS = 7 * 24 * 3600;

// ---------- 小さな道具 ----------

const now = () => Math.floor(Date.now() / 1000);
const json = (obj, status = 200) =>
  new Response(JSON.stringify(obj), { status, headers: { "content-type": "application/json; charset=utf-8" } });

function apiBase(env) { return env.LINE_API_BASE || "https://api.line.me"; }

function randomHex(bytes = 8) {
  const a = new Uint8Array(bytes);
  crypto.getRandomValues(a);
  return [...a].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function timingSafeEqual(a, b) {
  if (typeof a !== "string" || typeof b !== "string" || a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

async function hmacSha256(key, text) {
  const k = await crypto.subtle.importKey("raw", new TextEncoder().encode(key),
    { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  return new Uint8Array(await crypto.subtle.sign("HMAC", k, new TextEncoder().encode(text)));
}
const toBase64 = (u8) => btoa(String.fromCharCode(...u8));
const toHex = (u8) => [...u8].map((b) => b.toString(16).padStart(2, "0")).join("");

// 文字列は text メッセージに。オブジェクトはそのまま（LINE のメッセージオブジェクト）
function toMessages(list, vars = {}) {
  return (list || []).slice(0, 5).map((m) => {
    if (typeof m === "string") return { type: "text", text: fill(m, vars) };
    return JSON.parse(fill(JSON.stringify(m), vars, true));
  });
}

function fill(text, vars, inJson = false) {
  return text.replace(/\{(\w+)\}/g, (all, k) => {
    if (!(k in vars)) return all;
    const v = String(vars[k]);
    return inJson ? JSON.stringify(v).slice(1, -1) : v;
  });
}

function tzOffsetSec() { return (FLOW.timezone_offset_minutes ?? 540) * 60; }

function fmtLocal(epochSec) {
  const d = new Date((epochSec + tzOffsetSec()) * 1000);
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getUTCMonth() + 1}月${d.getUTCDate()}日 ${p(d.getUTCHours())}:${p(d.getUTCMinutes())}`;
}

// "2026-11-02T14:00"（現地時刻）→ 秒（UTC）
function parseLocal(s) {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(s || "");
  if (!m) return null;
  return Math.floor(Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]) / 1000) - tzOffsetSec();
}

function localPickerValue(epochSec) {
  const d = new Date((epochSec + tzOffsetSec()) * 1000);
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getUTCFullYear()}-${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())}T${p(d.getUTCHours())}:${p(d.getUTCMinutes())}`;
}

// ステップの送る時刻。after_minutes か、after_days＋at（現地の時:分）
function stepTime(startedAt, step) {
  if (step.after_minutes != null) return startedAt + step.after_minutes * 60;
  const off = tzOffsetSec();
  const local = new Date((startedAt + off) * 1000);
  const [hh, mm] = String(step.at || "00:00").split(":").map(Number);
  const t = Math.floor(Date.UTC(local.getUTCFullYear(), local.getUTCMonth(),
    local.getUTCDate() + (step.after_days || 0), hh, mm) / 1000) - off;
  return Math.max(t, startedAt);  // 当日の時刻を過ぎて登録した人は、次の cron で送る
}

// ---------- LINE API ----------

async function lineCall(env, path, body, extraHeaders = {}) {
  const res = await fetch(apiBase(env) + path, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      authorization: `Bearer ${env.LINE_CHANNEL_ACCESS_TOKEN}`,
      ...extraHeaders,
    },
    body: JSON.stringify(body),
  });
  if (!res.ok) console.log(`LINE ${path} ${res.status} ${(await res.text()).slice(0, 300)}`);
  return res.status;
}

// reply は通数に数えられない（無料）。1分以内に1回だけ使える
const reply = (env, replyToken, messages) =>
  messages.length ? lineCall(env, "/v2/bot/message/reply", { replyToken, messages }) : 0;

// push / multicast は通数に数えられる。二重送信を防ぐため X-Line-Retry-Key を付ける
const push = (env, to, messages, retryKey) =>
  lineCall(env, "/v2/bot/message/push", { to, messages }, { "X-Line-Retry-Key": retryKey });
const multicast = (env, to, messages, retryKey) =>
  lineCall(env, "/v2/bot/message/multicast", { to, messages }, { "X-Line-Retry-Key": retryKey });

// ---------- D1 ----------

async function getFriend(env, userId) {
  return env.DB.prepare("SELECT * FROM friends WHERE user_id=?").bind(userId).first();
}
async function friendByRef(env, ref) {
  return env.DB.prepare("SELECT * FROM friends WHERE ref=?").bind(ref).first();
}
async function tagsOf(env, userId) {
  const r = await env.DB.prepare("SELECT tag FROM tags WHERE user_id=?").bind(userId).all();
  return new Set(r.results.map((x) => x.tag));
}

async function addTags(env, userId, tags) {
  for (const tag of tags || []) {
    const r = await env.DB.prepare("INSERT OR IGNORE INTO tags(user_id, tag, created_at) VALUES (?,?,?)")
      .bind(userId, tag, now()).run();
    if (r.meta.changes) {
      for (const sc of FLOW.scenarios || []) if (sc.start === `tag:${tag}`) await enroll(env, userId, sc.id);
    }
  }
}
async function removeTags(env, userId, tags) {
  for (const tag of tags || []) await env.DB.prepare("DELETE FROM tags WHERE user_id=? AND tag=?").bind(userId, tag).run();
}

async function enroll(env, userId, scenarioId) {
  const sc = (FLOW.scenarios || []).find((s) => s.id === scenarioId);
  if (!sc || !sc.steps?.length) return false;
  const t = now();
  // 一度入った（終わった・止まった）シナリオには入れ直さない。やり直すときは /admin/enroll の restart
  const r = await env.DB.prepare(
    "INSERT OR IGNORE INTO enrollments(user_id, scenario_id, started_at, next_step, next_at, status) VALUES (?,?,?,?,?, 'active')"
  ).bind(userId, scenarioId, t, 0, stepTime(t, sc.steps[0])).run();
  return !!r.meta.changes;
}

async function stopAll(env, userId) {
  await env.DB.prepare("UPDATE enrollments SET status='stopped' WHERE user_id=? AND status='active'").bind(userId).run();
}

async function seenBefore(env, id) {
  if (!id) return false;
  const r = await env.DB.prepare("INSERT OR IGNORE INTO seen_events(id, received_at) VALUES (?,?)").bind(id, now()).run();
  return !r.meta.changes;
}

// ---------- LINE の Webhook ----------

async function handleLineWebhook(request, env) {
  const body = await request.text();
  const sig = request.headers.get("x-line-signature") || "";
  const expected = toBase64(await hmacSha256(env.LINE_CHANNEL_SECRET || "", body));
  if (!env.LINE_CHANNEL_SECRET || !timingSafeEqual(sig, expected)) return new Response("bad signature", { status: 401 });

  const payload = JSON.parse(body);
  for (const ev of payload.events || []) {
    try {
      if (await seenBefore(env, ev.webhookEventId)) continue;   // 同じイベントが2回届いても1回だけ
      await handleEvent(env, ev);
    } catch (e) {
      console.log("event error", ev.type, String(e && e.stack || e));
    }
  }
  return new Response("ok");  // 届いたら必ず 200（空の events は疎通確認）
}

async function handleEvent(env, ev) {
  const userId = ev.source?.userId;
  if (!userId || ev.source.type !== "user") return;   // グループ・複数人トークは扱わない
  const t = now();

  if (ev.type === "follow") {
    const existing = await getFriend(env, userId);
    if (existing) {
      await env.DB.prepare("UPDATE friends SET status='active', updated_at=? WHERE user_id=?").bind(t, userId).run();
    } else {
      await env.DB.prepare("INSERT INTO friends(user_id, ref, status, followed_at, updated_at) VALUES (?,?, 'active', ?, ?)")
        .bind(userId, randomHex(8), t, t).run();
    }
    for (const sc of FLOW.scenarios || []) if (sc.start === "follow") await enroll(env, userId, sc.id);
    await addTags(env, userId, FLOW.follow_tags || []);
    await reply(env, ev.replyToken, toMessages(FLOW.greeting));
    return;
  }

  if (ev.type === "unfollow") {
    await env.DB.prepare("UPDATE friends SET status='blocked', updated_at=? WHERE user_id=?").bind(t, userId).run();
    await stopAll(env, userId);
    return;
  }

  const friend = await getFriend(env, userId);
  if (!friend) {
    // 友だち追加より前からいた人（Webhook を入れる前の友だち）。ここで台帳に入れる
    await env.DB.prepare("INSERT OR IGNORE INTO friends(user_id, ref, status, followed_at, updated_at) VALUES (?,?, 'active', ?, ?)")
      .bind(userId, randomHex(8), t, t).run();
  }

  if (ev.type === "message" && ev.message?.type === "text") {
    await handleText(env, ev, userId, ev.message.text.trim());
    return;
  }
  if (ev.type === "postback") {
    await handlePostback(env, ev, userId, ev.postback?.data || "", ev.postback?.params || {});
  }
}

function matches(rule, text) {
  const words = rule.words || [];
  if (rule.match === "exact") return words.includes(text);
  return words.some((w) => text.includes(w));
}

async function handleText(env, ev, userId, text) {
  const opt = FLOW.optout || {};
  if ((opt.stop_words || []).includes(text)) {
    await addTags(env, userId, ["optout"]);
    await stopAll(env, userId);
    return reply(env, ev.replyToken, toMessages([opt.stop_reply || "配信を止めました。"]));
  }
  if ((opt.restart_words || []).includes(text)) {
    await removeTags(env, userId, ["optout"]);
    return reply(env, ev.replyToken, toMessages([opt.restart_reply || "配信を再開しました。"]));
  }

  const b = FLOW.booking;
  if (b && (b.trigger_words || []).includes(text)) return startBooking(env, ev);

  for (const sv of FLOW.surveys || []) {
    if ((sv.trigger_words || []).includes(text)) return askQuestion(env, ev.replyToken, sv, 0);
  }
  for (const p of FLOW.products || []) {
    if ((p.buy_words || []).includes(text)) return replyBuy(env, ev.replyToken, userId, p);
  }
  for (const rule of FLOW.keywords || []) {
    if (matches(rule, text)) {
      await addTags(env, userId, rule.add_tags);
      return reply(env, ev.replyToken, toMessages(rule.reply));
    }
  }
  if (FLOW.fallback_reply?.length) return reply(env, ev.replyToken, toMessages(FLOW.fallback_reply));
}

async function handlePostback(env, ev, userId, data, params) {
  const q = new URLSearchParams(data);
  if (q.has("tag")) await addTags(env, userId, [q.get("tag")]);

  if (q.has("kw")) {
    const rule = (FLOW.keywords || []).find((r) => r.id === q.get("kw"));
    if (rule) { await addTags(env, userId, rule.add_tags); return reply(env, ev.replyToken, toMessages(rule.reply)); }
  }
  if (q.has("survey")) {
    const sv = (FLOW.surveys || []).find((s) => s.id === q.get("survey"));
    if (sv) return askQuestion(env, ev.replyToken, sv, 0);
  }
  if (q.has("sv")) return answerQuestion(env, ev, userId, q.get("sv"), q.get("q"), q.get("v"));
  if (q.has("buy")) {
    const p = (FLOW.products || []).find((x) => x.id === q.get("buy"));
    if (p) return replyBuy(env, ev.replyToken, userId, p);
  }
  if (data === "book") return startBooking(env, ev);
  if (data === "book_pick" && params.datetime) return saveBooking(env, ev, userId, params.datetime);
}

// ---------- アンケート（クイックリプライで1問ずつ・返事は reply なので無料） ----------

function askQuestion(env, replyToken, sv, index) {
  const qn = sv.questions[index];
  const items = qn.options.slice(0, 13).map((o) => ({
    type: "action",
    action: { type: "postback", label: o.label.slice(0, 20), data: `sv=${sv.id}&q=${qn.id}&v=${o.value}`, displayText: o.label },
  }));
  return reply(env, replyToken, [{ type: "text", text: qn.text, quickReply: { items } }]);
}

async function answerQuestion(env, ev, userId, surveyId, qid, value) {
  const sv = (FLOW.surveys || []).find((s) => s.id === surveyId);
  if (!sv) return;
  const idx = sv.questions.findIndex((x) => x.id === qid);
  if (idx < 0) return;
  const opt = sv.questions[idx].options.find((o) => o.value === value);
  if (!opt) return;
  await env.DB.prepare("INSERT OR REPLACE INTO answers(user_id, survey_id, question_id, value, answered_at) VALUES (?,?,?,?,?)")
    .bind(userId, surveyId, qid, value, now()).run();
  await addTags(env, userId, opt.add_tags);
  if (idx + 1 < sv.questions.length) return askQuestion(env, ev.replyToken, sv, idx + 1);
  await addTags(env, userId, sv.done_tags);
  return reply(env, ev.replyToken, toMessages(sv.done_reply || ["ご回答ありがとうございました。"]));
}

// ---------- 購入リンク（その人の札つき・reply なので無料） ----------

async function replyBuy(env, replyToken, userId, product) {
  const f = await getFriend(env, userId);
  const sep = product.payment_link_url.includes("?") ? "&" : "?";
  const payUrl = `${product.payment_link_url}${sep}client_reference_id=${f.ref}`;
  return reply(env, replyToken, toMessages(product.buy_reply || ["お申し込みはこちらです\n{pay_url}"], { pay_url: payUrl, name: product.name }));
}

// ---------- 予約（LINE の日時選択）とリマインド ----------

function startBooking(env, ev) {
  const b = FLOW.booking;
  const t = now();
  const min = t + (b.min_days_ahead ?? 1) * 86400;
  const max = t + (b.max_days_ahead ?? 30) * 86400;
  return reply(env, ev.replyToken, [{
    type: "template",
    altText: b.prompt || "ご希望の日時を選んでください",
    template: {
      type: "buttons",
      text: (b.prompt || "ご希望の日時を選んでください").slice(0, 160),
      actions: [{
        type: "datetimepicker", label: "日時を選ぶ", data: "book_pick", mode: "datetime",
        initial: localPickerValue(min), min: localPickerValue(min), max: localPickerValue(max),
      }],
    },
  }]);
}

async function saveBooking(env, ev, userId, localValue) {
  const b = FLOW.booking;
  const startsAt = parseLocal(localValue);
  if (!startsAt || startsAt < now()) return reply(env, ev.replyToken, toMessages(["その日時は選べません。もう一度お選びください。"]));
  await createBooking(env, userId, startsAt, b.title, b.url || null);
  return reply(env, ev.replyToken, toMessages(b.confirm_reply || ["{datetime} で承りました。"], { datetime: fmtLocal(startsAt), title: b.title }));
}

async function createBooking(env, userId, startsAt, title, url) {
  const id = "bk_" + randomHex(8);
  await env.DB.prepare("INSERT INTO bookings(id, user_id, starts_at, title, url, status, sent, created_at) VALUES (?,?,?,?,?, 'scheduled', '[]', ?)")
    .bind(id, userId, startsAt, title, url, now()).run();
  await addTags(env, userId, FLOW.booking?.add_tags || []);
  return id;
}

// ---------- Stripe の決済完了 → LINE でお届け ----------

async function handleStripeWebhook(request, env) {
  if (!env.STRIPE_WEBHOOK_SECRET) return new Response("not configured", { status: 404 });
  const body = await request.text();
  const header = request.headers.get("stripe-signature") || "";
  const parts = header.split(",").map((x) => x.split("="));
  const ts = parts.find((p) => p[0] === "t")?.[1];
  const v1s = parts.filter((p) => p[0] === "v1").map((p) => p[1]);
  if (!ts || !v1s.length || Math.abs(now() - Number(ts)) > 300) return new Response("bad signature", { status: 400 });
  const expected = toHex(await hmacSha256(env.STRIPE_WEBHOOK_SECRET, `${ts}.${body}`));
  if (!v1s.some((v) => timingSafeEqual(v, expected))) return new Response("bad signature", { status: 400 });

  const event = JSON.parse(body);
  const ok = (event.type === "checkout.session.completed" && event.data.object.payment_status === "paid")
    || event.type === "checkout.session.async_payment_succeeded";   // コンビニ払いなどは後から入金
  if (!ok) return new Response("ignored");
  if (await seenBefore(env, event.id)) return new Response("dup");

  const s = event.data.object;
  const friend = s.client_reference_id ? await friendByRef(env, s.client_reference_id) : null;
  const product = (FLOW.products || []).find((p) => p.payment_link_id && p.payment_link_id === s.payment_link)
    || ((FLOW.products || []).length === 1 ? FLOW.products[0] : null);
  await env.DB.prepare("INSERT OR IGNORE INTO purchases(event_id, user_id, product_id, amount, currency, created_at) VALUES (?,?,?,?,?,?)")
    .bind(event.id, friend?.user_id || null, product?.id || null, s.amount_total ?? null, s.currency ?? null, now()).run();

  if (friend && product) {
    await addTags(env, friend.user_id, product.add_tags || [`buyer:${product.id}`]);
    for (const sc of FLOW.scenarios || []) {
      if ((sc.stop_if_tags || []).some((tg) => (product.add_tags || [`buyer:${product.id}`]).includes(tg))) {
        await env.DB.prepare("UPDATE enrollments SET status='stopped' WHERE user_id=? AND scenario_id=? AND status='active'")
          .bind(friend.user_id, sc.id).run();
      }
    }
    if (friend.status === "active" && product.delivery?.length) {
      const st = await push(env, friend.user_id, toMessages(product.delivery, { name: product.name }), crypto.randomUUID());
      await logSend(env, "delivery", product.id, 1, st);
    }
  }
  // LINE の人が分からない決済（リンクを直接開いた等）は purchases に残るだけ。お届けは Stripe のメール等で
  return new Response("ok");
}

// ---------- 定期実行 ----------

async function logSend(env, kind, refId, n, status) {
  await env.DB.prepare("INSERT INTO send_log(kind, ref_id, recipients, status, sent_at) VALUES (?,?,?,?,?)")
    .bind(kind, refId, n, status, now()).run();
}

async function runSteps(env) {
  const t = now();
  // D1 への問い合わせ回数を抑えるため、対象の人とタグをまとめて1回ずつで読む
  const due = await env.DB.prepare(
    `SELECT e.user_id, e.scenario_id, e.next_step, e.started_at FROM enrollments e
     JOIN friends f ON f.user_id = e.user_id
     WHERE e.status='active' AND e.next_at <= ? AND f.status='active' ORDER BY e.next_at LIMIT 2000`
  ).bind(t).all();
  if (!due.results.length) return;
  const tagRows = await env.DB.prepare(
    `SELECT t.user_id, t.tag FROM tags t WHERE t.user_id IN (
       SELECT e.user_id FROM enrollments e WHERE e.status='active' AND e.next_at <= ?)`
  ).bind(t).all();
  const tagMap = new Map();
  for (const r of tagRows.results) {
    if (!tagMap.has(r.user_id)) tagMap.set(r.user_id, new Set());
    tagMap.get(r.user_id).add(r.tag);
  }

  const updates = [];
  const groups = new Map();   // "scenario|step" → [行]
  for (const r of due.results) {
    const sc = (FLOW.scenarios || []).find((s) => s.id === r.scenario_id);
    if (!sc || r.next_step >= sc.steps.length) {
      updates.push(setStatus(env, r, "done"));
      continue;
    }
    const tags = tagMap.get(r.user_id) || new Set();
    if (tags.has("optout") || (sc.stop_if_tags || []).some((x) => tags.has(x))) {
      updates.push(setStatus(env, r, "stopped"));
      continue;
    }
    const step = sc.steps[r.next_step];
    if ((step.only_if_tags || []).length && !step.only_if_tags.some((x) => tags.has(x))) {
      updates.push(advance(env, r, sc));   // この便の対象でない人は飛ばして次の便へ（次の回で次の便を見る）
      continue;
    }
    const key = `${r.scenario_id}|${r.next_step}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(r);
  }
  await runBatch(env, updates);

  let batches = 0;
  for (const [key, rows] of groups) {
    const [scId, stepIdx] = key.split("|");
    const sc = FLOW.scenarios.find((s) => s.id === scId);
    const messages = toMessages(sc.steps[+stepIdx].messages);
    for (let i = 0; i < rows.length; i += 500) {
      if (batches >= MAX_BATCHES_PER_RUN) return;   // 残りは次の回へ
      const chunk = rows.slice(i, i + 500);
      // 送る前に「進めた」と書く。失敗しても二重には送らない（送れなかった分は send_log の status で分かる）
      await runBatch(env, chunk.map((r) => advance(env, r, sc)));
      const st = await multicast(env, chunk.map((r) => r.user_id), messages, crypto.randomUUID());
      await logSend(env, "step", key, chunk.length, st);
      batches++;
    }
  }
}

async function runBatch(env, stmts) {
  for (let i = 0; i < stmts.length; i += 100) await env.DB.batch(stmts.slice(i, i + 100));
}

function setStatus(env, r, status) {
  return env.DB.prepare("UPDATE enrollments SET status=? WHERE user_id=? AND scenario_id=?").bind(status, r.user_id, r.scenario_id);
}

function advance(env, r, sc) {
  const next = r.next_step + 1;
  if (next >= sc.steps.length) {
    return env.DB.prepare("UPDATE enrollments SET next_step=?, status='done', next_at=NULL WHERE user_id=? AND scenario_id=?")
      .bind(next, r.user_id, r.scenario_id);
  }
  return env.DB.prepare("UPDATE enrollments SET next_step=?, next_at=? WHERE user_id=? AND scenario_id=?")
    .bind(next, stepTime(r.started_at, sc.steps[next]), r.user_id, r.scenario_id);
}

async function runReminders(env) {
  const b = FLOW.booking;
  if (!b) return;
  const offsets = b.reminders_minutes || [];
  const t = now();
  const rows = await env.DB.prepare(
    `SELECT bk.* FROM bookings bk JOIN friends f ON f.user_id = bk.user_id
     WHERE bk.status='scheduled' AND f.status='active' AND bk.starts_at > ? AND bk.starts_at <= ?`
  ).bind(t, t + Math.max(0, ...offsets) * 60 + 600).all();
  let pushes = 0;
  for (const bk of rows.results) {
    const sent = JSON.parse(bk.sent || "[]");
    // まだ送っていない中で、いちばん近いリマインドを1通だけ（遅れて気づいたときに何通も重ねない）
    const dueOffsets = offsets.filter((m) => !sent.includes(m) && t >= bk.starts_at - m * 60);
    if (!dueOffsets.length) continue;
    if (pushes >= MAX_PUSH_PER_RUN) break;
    const m = Math.min(...dueOffsets);
    await env.DB.prepare("UPDATE bookings SET sent=? WHERE id=?").bind(JSON.stringify([...sent, ...dueOffsets]), bk.id).run();
    const msgs = toMessages(b.reminder_messages || ["{title}は{datetime}からです。"],
      { title: bk.title, datetime: fmtLocal(bk.starts_at), url: bk.url || "", minutes: m });
    const st = await push(env, bk.user_id, msgs, crypto.randomUUID());
    await logSend(env, "reminder", bk.id, 1, st);
    pushes++;
  }
  await env.DB.prepare("UPDATE bookings SET status='done' WHERE status='scheduled' AND starts_at < ?").bind(t - 3600).run();
}

async function cleanup(env) {
  await env.DB.prepare("DELETE FROM seen_events WHERE received_at < ?").bind(now() - EVENT_KEEP_SECONDS).run();
}

// ---------- 管理用（scripts/ から） ----------

async function handleAdmin(request, env, url) {
  const auth = request.headers.get("authorization") || "";
  if (!env.ADMIN_TOKEN || !timingSafeEqual(auth, `Bearer ${env.ADMIN_TOKEN}`)) return json({ error: "unauthorized" }, 401);
  const path = url.pathname;

  if (path === "/admin/stats" && request.method === "GET") {
    const one = async (sql, ...b) => (await env.DB.prepare(sql).bind(...b).first())?.n ?? 0;
    const tagRows = await env.DB.prepare("SELECT tag, COUNT(*) n FROM tags GROUP BY tag ORDER BY n DESC LIMIT 100").all();
    const sends = await env.DB.prepare(
      "SELECT kind, SUM(recipients) n FROM send_log WHERE sent_at >= ? AND status = 200 GROUP BY kind").bind(now() - 30 * 86400).all();
    const fails = await env.DB.prepare(
      "SELECT kind, status, COUNT(*) n, SUM(recipients) people FROM send_log WHERE sent_at >= ? AND status <> 200 GROUP BY kind, status").bind(now() - 7 * 86400).all();
    return json({
      send_failures_last_7_days: fails.results,
      friends_active: await one("SELECT COUNT(*) n FROM friends WHERE status='active'"),
      friends_blocked: await one("SELECT COUNT(*) n FROM friends WHERE status='blocked'"),
      enrollments_active: await one("SELECT COUNT(*) n FROM enrollments WHERE status='active'"),
      bookings_upcoming: await one("SELECT COUNT(*) n FROM bookings WHERE status='scheduled' AND starts_at > ?", now()),
      purchases: await one("SELECT COUNT(*) n FROM purchases"),
      tags: tagRows.results,
      sent_last_30_days: sends.results,
    });
  }

  if (path === "/admin/audience" && request.method === "GET") {
    const include = url.searchParams.getAll("tag");
    const exclude = [...url.searchParams.getAll("exclude"), "optout"];
    let sql = "SELECT f.user_id FROM friends f WHERE f.status='active'";
    const binds = [];
    for (const tg of include) { sql += " AND EXISTS (SELECT 1 FROM tags t WHERE t.user_id=f.user_id AND t.tag=?)"; binds.push(tg); }
    for (const tg of exclude) { sql += " AND NOT EXISTS (SELECT 1 FROM tags t WHERE t.user_id=f.user_id AND t.tag=?)"; binds.push(tg); }
    const r = await env.DB.prepare(sql).bind(...binds).all();
    return json({ count: r.results.length, user_ids: r.results.map((x) => x.user_id) });
  }

  const body = request.method === "POST" ? await request.json().catch(() => ({})) : {};
  const who = async () => {
    if (body.user_id) return body.user_id;
    if (body.ref) return (await friendByRef(env, body.ref))?.user_id;
    return null;
  };

  if (path === "/admin/tags" && request.method === "POST") {
    const userId = await who();
    if (!userId) return json({ error: "friend not found" }, 404);
    await addTags(env, userId, body.add);
    await removeTags(env, userId, body.remove);
    return json({ ok: true, tags: [...(await tagsOf(env, userId))] });
  }

  if (path === "/admin/enroll" && request.method === "POST") {
    const userId = await who();
    if (!userId) return json({ error: "friend not found" }, 404);
    if (body.restart) await env.DB.prepare("DELETE FROM enrollments WHERE user_id=? AND scenario_id=?").bind(userId, body.scenario_id).run();
    return json({ ok: await enroll(env, userId, body.scenario_id) });
  }

  if (path === "/admin/bookings" && request.method === "POST") {
    const userId = await who();
    if (!userId) return json({ error: "friend not found" }, 404);
    const startsAt = parseLocal(body.starts_at_local);
    if (!startsAt) return json({ error: "starts_at_local は 2026-11-02T14:00 の形で" }, 400);
    return json({ ok: true, id: await createBooking(env, userId, startsAt, body.title || FLOW.booking?.title || "ご予約", body.url || null) });
  }

  if (path === "/admin/bookings/cancel" && request.method === "POST") {
    const r = await env.DB.prepare("UPDATE bookings SET status='cancelled' WHERE id=? AND status='scheduled'").bind(body.id).run();
    return json({ ok: !!r.meta.changes });
  }

  if (path === "/admin/run" && request.method === "POST") {   // 試し用：cron を待たずに1回動かす
    await runSteps(env); await runReminders(env);
    return json({ ok: true });
  }

  return json({ error: "not found" }, 404);
}

// ---------- 入口 ----------

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/webhook" && request.method === "POST") return handleLineWebhook(request, env);
    if (url.pathname === "/stripe/webhook" && request.method === "POST") return handleStripeWebhook(request, env);
    if (url.pathname === "/health") return json({ ok: true, flow: FLOW.name || "flow" });
    if (url.pathname.startsWith("/admin/")) return handleAdmin(request, env, url);
    return new Response("not found", { status: 404 });
  },
  async scheduled(controller, env, ctx) {
    ctx.waitUntil((async () => {
      await runSteps(env);
      await runReminders(env);
      await cleanup(env);
    })());
  },
};
