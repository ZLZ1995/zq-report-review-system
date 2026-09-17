"use strict";
let token = null;
let discovery = null;
let connectionVersion = 0;
let testingConnection = false;
let billingNextOffset = null;
const billingUnknown = new Set();
let billingBusy = false;
let releaseItems = [];
let skillReleaseItems = [];
const el = id => document.getElementById(id);
const notice = text => { el("notice").textContent = text; };
function clearSession() {
  token = null;
  billingUnknown.clear();
  billingNextOffset = null;
  billingBusy = false;
  el("billing-choice").replaceChildren();
  el("billing-result").textContent = "";
  el("billing-hold").value = "";
  el("billing-next").disabled = true;
  el("desk").hidden = true;
  el("logout").hidden = true;
  el("login-panel").hidden = false;
  for (const id of ["users", "stats", "model-list", "route-list", "model-choice", "release-choice", "release-list", "skill-release-choice", "skill-release-list"]) el(id).replaceChildren();
  document.querySelectorAll("form").forEach(form => form.reset());
  document.querySelectorAll(".user-choice").forEach(select => select.replaceChildren());
  invalidateConnection();
}
function releaseLabel(item) {
  return item.version + " · " + item.platform + "/" + item.arch + " · " + item.status + " · 序号 " + item.sequence;
}
function updateReleaseButtons() {
  const selected = releaseItems.find(item => item.release_id === el("release-choice").value);
  for (const id of ["release-canary", "release-stable", "release-withdraw"]) el(id).disabled = !selected;
}
function skillReleaseLabel(item) {
  return item.skill_id + " · " + item.version + " · " + item.status;
}
function updateSkillReleaseButtons() {
  const selected = skillReleaseItems.find(item => item.release_id === el("skill-release-choice").value);
  el("skill-release-approve").disabled = !selected || !["draft", "withdrawn"].includes(selected.status);
  el("skill-release-stable").disabled = !selected || selected.status !== "approved";
  el("skill-release-withdraw").disabled = !selected || selected.status === "withdrawn";
}
async function refreshSkillReleases() {
  const data = await api("/admin/skill-releases");
  skillReleaseItems = Array.isArray(data) ? data : [];
  const choice = el("skill-release-choice");
  choice.replaceChildren();
  option(choice, "", skillReleaseItems.length ? "请选择 Skill 版本" : "暂无 Skill 版本");
  const list = el("skill-release-list");
  list.replaceChildren();
  for (const item of skillReleaseItems) {
    option(choice, item.release_id, skillReleaseLabel(item));
    const p = document.createElement("p");
    p.textContent = skillReleaseLabel(item) + " · 包 SHA256 " + item.package_sha256;
    list.append(p);
  }
  updateSkillReleaseButtons();
}
async function transitionSkillRelease(status) {
  const releaseId = el("skill-release-choice").value;
  const selected = skillReleaseItems.find(item => item.release_id === releaseId);
  if (!selected || !confirm("确认将 " + selected.skill_id + " " + selected.version + " 设为 " + status + "？")) return;
  for (const id of ["skill-release-approve", "skill-release-stable", "skill-release-withdraw"]) el(id).disabled = true;
  try {
    await api("/admin/skill-releases/" + encodeURIComponent(releaseId) + "/transition", "POST", {status});
    notice("Skill 版本状态已更新。");
    await refreshSkillReleases();
  } catch (error) { notice(error instanceof TypeError ? "网络异常，请刷新核对状态。" : error.message); updateSkillReleaseButtons(); }
}
async function refreshReleases() {
  const data = await api("/admin/client-releases");
  releaseItems = Array.isArray(data) ? data : [];
  const choice = el("release-choice");
  choice.replaceChildren();
  option(choice, "", releaseItems.length ? "请选择发布版本" : "暂无发布版本");
  for (const item of releaseItems) option(choice, item.release_id, releaseLabel(item));
  const list = el("release-list");
  list.replaceChildren();
  for (const item of releaseItems) {
    const p = document.createElement("p");
    p.textContent = releaseLabel(item) + " · 清单 SHA256 " + item.manifest_sha256;
    list.append(p);
  }
  updateReleaseButtons();
}
async function createReleaseDraft(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector("button");
  button.disabled = true;
  try {
    let manifest;
    try { manifest = JSON.parse(form.elements.manifest.value); }
    catch { throw new Error("发布清单不是有效 JSON。"); }
    await api("/admin/client-releases", "POST", {manifest});
    form.reset();
    notice("发布草稿已创建，签名校验通过。");
    await refreshReleases();
  } catch (error) { notice(error instanceof TypeError ? "网络异常，请刷新核对发布状态。" : error.message); }
  finally { button.disabled = false; }
}
async function transitionRelease(status) {
  const releaseId = el("release-choice").value;
  if (!releaseId) return;
  const selected = releaseItems.find(item => item.release_id === releaseId);
  if (!selected) return;
  const label = status === "stable" ? "激活稳定" : status === "canary" ? "切换灰度" : "撤回版本";
  if (!confirm("确认对 " + selected.version + " 执行“" + label + "”？")) return;
  for (const id of ["release-canary", "release-stable", "release-withdraw"]) el(id).disabled = true;
  try {
    await api("/admin/client-releases/" + encodeURIComponent(releaseId) + "/transition", "POST", {status});
    notice(label + "已提交并完成状态更新。");
    await refreshReleases();
  } catch (error) { notice(error instanceof TypeError ? "网络异常，请刷新核对发布状态。" : error.message); updateReleaseButtons(); }
}
async function api(path, method = "GET", data) {
  const response = await fetch("/api/v1" + path, {
    method, cache: "no-store", credentials: "omit", redirect: "error",
    headers: { "Content-Type": "application/json", ...(token ? {Authorization: "Bearer " + token} : {}) },
    ...(data ? {body: JSON.stringify(data)} : {}),
  });
  if (!response.ok) {
    if (path.startsWith("/admin/channels")) {
      const result = await response.json().catch(() => ({}));
      const code = result.error?.code;
      if (typeof code === "string" && (code.startsWith("discovery_") || code === "route_priority_exists")) {
        throw new Error(result.error.message);
      }
    }
    if (response.status === 401) clearSession();
    // Do not display validation payloads: rejected inputs may contain secrets.
    const error = new Error(response.status === 401 ? "登录失效或凭据错误，请重新登录。" :
      response.status === 422 && (path === "/admin/users" || path.endsWith("/reset-password")) ? "请核对账号字段；客户密码须为8–16位纯数字或数字+英文，区分大小写。" :
      response.status === 403 ? "无管理权限，或账号需要先修改临时密码。" :
      response.status === 409 ? "记录冲突，请刷新确认是否已保存，不要重复提交。" : "操作失败，请核对输入或联系服务管理员。状态码：" + response.status);
    error.status = response.status;
    throw error;
  }
  return response.status === 204 ? null : response.json();
}
function cell(row, value) { const td = document.createElement("td"); td.textContent = value; row.append(td); }
function option(select, id, name) { const opt = document.createElement("option"); opt.value = id; opt.textContent = name; select.append(opt); }
async function refresh() {
  const data = await api("/admin/overview");
  for (const id of ["users", "stats", "model-list", "route-list"]) el(id).replaceChildren();
  document.querySelectorAll(".user-choice").forEach(s => s.replaceChildren());
  for (const user of data.users) {
    const row = document.createElement("tr");
    [user.username, user.display_name, user.status, user.balance, user.billing_multiplier].forEach(v => cell(row, v));
    el("users").append(row);
    if (user.role === "user") document.querySelectorAll(".user-choice").forEach(s => option(s, user.user_id, user.display_name + " · " + user.username));
  }
  for (const [title, count] of [["账号", data.users.length], ["模型", data.models.length], ["渠道", data.routes.length]]) {
    const box = document.createElement("div"); box.className = "stat"; box.textContent = title + " / " + count; el("stats").append(box);
  }
  for (const model of data.models) {
    const p = document.createElement("p"); p.textContent = model.display_name + " · " + model.code + " · 倍率 " + model.model_multiplier; el("model-list").append(p);
  }
  for (const route of data.routes) {
    const p = document.createElement("p"); p.textContent = route.provider_type + " / " + route.provider_model + " · 优先级 " + route.priority + " · 密钥已配置"; el("route-list").append(p);
  }
}
function bind(id, action) {
  el(id).addEventListener("submit", async event => {
    event.preventDefault();
    const form = event.currentTarget;
    const buttons = form.querySelectorAll("button"); buttons.forEach(b => {b.disabled = true;});
    const data = Object.fromEntries(new FormData(form));
    try { await action(data); }
    catch (error) { notice(error instanceof TypeError ? "网络异常。写入结果可能尚未确认，请刷新核对后再操作。" : error.message); }
    finally {
      form.querySelectorAll('input[type="password"]').forEach(input => { input.value = ""; });
      buttons.forEach(b => {b.disabled = false;});
      if (id === "route") invalidateConnection();
    }
  });
}
bind("login", async data => {
  if (location.protocol !== "https:" && !["localhost", "127.0.0.1", "[::1]"].includes(location.hostname)) throw new Error("非本机访问必须使用 HTTPS。");
  const result = await api("/auth/login", "POST", {...data, client_instance_id: "admin-web-" + crypto.randomUUID()});
  token = result.access_token;
  if (result.user.role !== "admin" || result.user.must_change_password) {
    try { await api("/auth/logout", "POST"); } finally { clearSession(); }
    throw new Error("仅支持已完成初始化的管理员账号。临时密码请先通过认证入口修改。");
  }
  try { await refresh(); await refreshReleases(); await refreshSkillReleases(); } catch (error) { clearSession(); throw error; }
  el("desk").hidden = false; el("login-panel").hidden = true; el("logout").hidden = false;
  notice("已登录总控。凭据仅保存在当前页面内存中。");
});
async function save(path, method, data) {
  await api(path, method, data);
  notice("操作已保存。");
  try { await refresh(); } catch { notice("操作已保存，但刷新失败。请手动刷新，不要重复提交。"); }
}
bind("create-user", data => save("/admin/users", "POST", data));
bind("adjust", async ({user_id, amount}) => {
  if (Number(amount) === 0) throw new Error("调整金额不能为零。");
  if (confirm("确认对所选账号调整余额 " + amount + " 元？")) await save("/admin/users/" + encodeURIComponent(user_id) + "/balance-adjustments", "POST", {amount});
});
bind("reset", async ({user_id, temporary_password}) => {
  if (confirm("确认重置密码并使该账号已有会话失效？")) await save("/admin/users/" + encodeURIComponent(user_id) + "/reset-password", "POST", {temporary_password});
});
bind("multiplier", ({user_id, multiplier}) => save("/admin/users/" + encodeURIComponent(user_id) + "/billing-multiplier", "PATCH", {multiplier}));
bind("route", data => {
  if (!discovery || !el("model-choice").value) throw new Error("请先测试连接并手动选择模型。");
  const {input, output, cache_hit, cache_miss, reasoning, ...rest} = data;
  return save("/admin/channels", "POST", {...rest, discovery_token: discovery.discovery_token,
    priority: Number(rest.priority), rates: {input, output, cache_hit, cache_miss, reasoning}});
});
function updateConnectionButtons() {
  el("test-connection").disabled = testingConnection || !el("channel-url").value.trim() || !el("channel-key").value.trim();
  el("save-channel").disabled = testingConnection || !discovery || !el("model-choice").value;
}
function invalidateConnection() {
  connectionVersion++;
  discovery = null;
  el("model-choice").replaceChildren();
  option(el("model-choice"), "", "请先测试连接");
  el("model-choice").disabled = true;
  el("connection-status").textContent = "连接信息变更后需重新测试；请选择返回清单中的模型。";
  updateConnectionButtons();
}
for (const id of ["channel-url", "channel-key"]) el(id).addEventListener("input", invalidateConnection);
el("model-choice").addEventListener("change", updateConnectionButtons);
el("test-connection").addEventListener("click", async () => {
  invalidateConnection();
  const version = connectionVersion;
  const session = token;
  testingConnection = true;
  updateConnectionButtons();
  el("connection-status").textContent = "正在连接并获取模型清单…";
  try {
    const result = await api("/admin/channels/discover", "POST", {
      base_url: el("channel-url").value.trim(), api_key: el("channel-key").value,
    });
    if (version !== connectionVersion || session !== token) return;
    discovery = result;
    el("model-choice").replaceChildren();
    option(el("model-choice"), "", "请选择具体模型");
    result.models.forEach(model => option(el("model-choice"), model, model));
    el("model-choice").disabled = false;
    el("connection-status").textContent = "连接成功，获取 " + result.models.length + " 个模型。请手动选择；本次未调用模型生成内容。";
  } catch (error) {
    if (version === connectionVersion && session === token) el("connection-status").textContent = error instanceof TypeError ? "网络连接失败，请稍后重试。" : error.message;
  } finally {
    testingConnection = false;
    updateConnectionButtons();
  }
});
el("refresh").addEventListener("click", async () => { try { await refresh(); notice("数据已刷新。"); } catch (error) { notice(error.message); } });
el("logout").addEventListener("click", async () => {
  try { await api("/auth/logout", "POST"); notice("已退出。"); }
  catch { notice("本地凭据已清除，服务端退出未确认。"); }
  finally { clearSession(); }
});
el("client-release-create").addEventListener("submit", createReleaseDraft);
el("release-choice").addEventListener("change", updateReleaseButtons);
el("release-refresh").addEventListener("click", async () => { try { await refreshReleases(); notice("发布列表已刷新。"); } catch (error) { notice(error.message); } });
el("release-canary").addEventListener("click", () => transitionRelease("canary"));
el("release-stable").addEventListener("click", () => transitionRelease("stable"));
el("release-withdraw").addEventListener("click", () => transitionRelease("withdrawn"));
bind("skill-release-create", data => save("/admin/skill-releases", "POST", {
  ...data, schema_version: 1, adapter: "report.review",
  capabilities: ["read_selected_files", "generate_artifacts"],
}));
el("skill-release-choice").addEventListener("change", updateSkillReleaseButtons);
el("skill-release-refresh").addEventListener("click", async () => { try { await refreshSkillReleases(); notice("Skill 列表已刷新。"); } catch (error) { notice(error.message); } });
el("skill-release-approve").addEventListener("click", () => transitionSkillRelease("approved"));
el("skill-release-stable").addEventListener("click", () => transitionSkillRelease("stable"));
el("skill-release-withdraw").addEventListener("click", () => transitionSkillRelease("withdrawn"));

function billingReceipt(record) {
  el("billing-result").textContent = "核对回执：" + record.reconciliation_id +
    "；冻结编号：" + record.hold_id + "；已确认总费用：" + record.confirmed_amount +
    " 元。此操作不会重新执行模型请求。";
}
async function loadBillingHolds(offset = 0) {
  const session = token;
  if (!session) return;
  const result = await api("/admin/billing-holds?limit=50&offset=" + offset);
  if (session !== token) return;
  el("billing-choice").replaceChildren();
  option(el("billing-choice"), "", "请选择待核对记录");
  for (const item of result.items) option(el("billing-choice"), item.hold_id,
    item.client_request_id + " · 账号ID " + item.user_id + " · 已知费用 " + item.known_amount + " 元");
  billingNextOffset = result.next_offset;
  el("billing-next").disabled = billingNextOffset === null;
  if (!result.items.length) el("billing-result").textContent = "本页无待核对记录。可输入冻结编号查询历史回执。";
}
async function queryReconciliation() {
  const session = token, hold = el("billing-hold").value.trim();
  if (!session || !hold) return;
  try {
    const result = await api("/admin/billing-holds/" + encodeURIComponent(hold) + "/reconciliation");
    if (session !== token) return;
    billingUnknown.delete(hold);
    billingReceipt(result);
  } catch {
    if (session === token) el("billing-result").textContent = "尚未取得核对回执，不代表提交失败；请稍后查询或联系管理员，不要重复提交。";
  }
}
async function submitReconciliation(data) {
  const session = token, hold = data.hold_id.trim();
  if (!session || !hold || billingBusy) return;
  if (billingUnknown.has(hold)) {
    el("billing-result").textContent = "此前提交结果未确认，请先查询回执，不要重复提交。";
    return;
  }
  if (!confirm("确认已有上游凭证，冻结 " + hold + " 的总费用为 " + data.confirmed_amount +
    " 元？这是总额，不是追加金额；提交后保留审计记录，不可覆盖。")) return;
  billingBusy = true;
  billingUnknown.add(hold);
  try {
    const result = await api("/admin/billing-holds/" + encodeURIComponent(hold) + "/reconciliation", "POST", {
      confirmed_amount: data.confirmed_amount, evidence_sha256: data.evidence_sha256,
      evidence_reference: data.evidence_reference,
    });
    if (session !== token) return;
    billingUnknown.delete(hold);
    billingReceipt(result);
  } catch (error) {
    if (session !== token) return;
    if (error.status === 422) {
      billingUnknown.delete(hold);
      el("billing-result").textContent = "输入校验未通过，未进行结算。请核对金额精度及凭证格式后重新确认。";
    } else {
      el("billing-result").textContent = "提交未得到确认，请先查询回执；不要再次扣款或重复提交。";
    }
  } finally {
    if (session === token) billingBusy = false;
  }
}
bind("billing-reconcile", submitReconciliation);
el("billing-choice").addEventListener("change", () => {el("billing-hold").value = el("billing-choice").value;});
el("billing-query").addEventListener("click", queryReconciliation);
for (const [id, offset] of [["billing-load", () => 0], ["billing-next", () => billingNextOffset]]) {
  el(id).addEventListener("click", async () => {
    try { if (offset() !== null) await loadBillingHolds(offset()); }
    catch { if (token) el("billing-result").textContent = "费用核对列表加载失败，请重新登录或稍后刷新。"; }
  });
}
