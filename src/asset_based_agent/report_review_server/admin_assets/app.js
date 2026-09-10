"use strict";
let token = null;
let discovery = null;
let connectionVersion = 0;
let testingConnection = false;
const el = id => document.getElementById(id);
const notice = text => { el("notice").textContent = text; };
function clearSession() {
  token = null;
  el("desk").hidden = true;
  el("logout").hidden = true;
  el("login-panel").hidden = false;
  for (const id of ["users", "stats", "model-list", "route-list", "model-choice"]) el(id).replaceChildren();
  document.querySelectorAll("form").forEach(form => form.reset());
  document.querySelectorAll(".user-choice").forEach(select => select.replaceChildren());
  invalidateConnection();
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
    throw new Error(response.status === 401 ? "登录失效或凭据错误，请重新登录。" :
      response.status === 422 && (path === "/admin/users" || path.endsWith("/reset-password")) ? "请核对账号字段；客户密码须为8–16位纯数字或数字+英文，区分大小写。" :
      response.status === 403 ? "无管理权限，或账号需要先修改临时密码。" :
      response.status === 409 ? "记录冲突，请刷新确认是否已保存，不要重复提交。" : "操作失败，请核对输入或联系服务管理员。状态码：" + response.status);
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
  try { await refresh(); } catch (error) { clearSession(); throw error; }
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
