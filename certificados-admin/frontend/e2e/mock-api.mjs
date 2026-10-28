/**
 * Contract-faithful mock of the administrative API used only by Playwright.
 * It deliberately returns the backend permission list instead of deriving
 * frontend access from a role, mirroring the production authority boundary.
 */
import { createServer } from "node:http";

const PORT = Number(process.env.MOCK_API_PORT ?? 8000);

const PERMISSIONS = {
  admin: [
    "audit.read",
    "certificates.download",
    "certificates.issue",
    "certificates.read",
    "certificates.reissue",
    "certificates.revoke",
    "dashboard.read",
    "sessions.manage",
    "settings.manage",
    "settings.read",
    "templates.manage",
    "templates.read",
    "users.manage",
  ],
  secretaria: [
    "certificates.download",
    "certificates.issue",
    "certificates.read",
    "certificates.reissue",
    "certificates.revoke",
    "dashboard.read",
  ],
  auditor: ["audit.read", "certificates.read"],
};

const NAMES = [
  "Ana Carolina Souza",
  "João Pedro Lima",
  "Mariana Alves Ferreira",
  "Carlos Eduardo Nunes",
  "Beatriz Rocha",
  "Rafael Monteiro",
  "Luciana Prado",
  "Thiago Barbosa",
  "Fernanda Ribeiro",
  "Gustavo Andrade",
  "Patrícia Gomes",
  "Eduardo Tavares",
  "Camila Duarte",
  "Rodrigo Vasconcelos",
  "Isabela Martins",
  "Marcelo Teixeira",
  "Juliana Castro",
  "Bruno Carvalho",
  "Larissa Moreira",
  "Vinícius Cardoso",
];
const EVENTS = [
  "Semana de Inovação",
  "Jornada Jurídica",
  "Simpósio de Pesquisa",
  "Encontro de Extensão",
];
const COURSES = ["Direito", "Administração", "Psicologia", "Sistemas de Informação"];
const CERTIFICATE_TYPES = [
  ["listener", "Ouvinte"],
  ["speaker", "Palestrante"],
  ["organizing_committee", "Comissão Organizadora"],
  ["teams", "Equipes"],
  ["monitoring", "Monitoria"],
  ["tcc_board_professor", "Professores participantes de Banca de TCC"],
  ["scientific_initiation", "Mostra de Iniciação Científica"],
];

function certificate(index) {
  const status = index % 11 === 3 ? "revogado" : index % 13 === 7 ? "failed" : "ativo";
  const integrityBlocked = index % 29 === 0;
  const [certificateType, certificateTypeLabel] = CERTIFICATE_TYPES[(index - 1) % CERTIFICATE_TYPES.length];
  return {
    unique_code: `CERT-2026-${String(index).padStart(4, "0")}A`,
    participant_name: NAMES[index % NAMES.length],
    participant_email: null,
    course_name: COURSES[index % COURSES.length],
    event_name: EVENTS[index % EVENTS.length],
    certificate_type: certificateType,
    certificate_type_label: certificateTypeLabel,
    workload_hours: 8 + (index % 5) * 4,
    issue_date: "10 de junho de 2026",
    issue_date_iso: "2026-06-10",
    start_date: "2026-06-10",
    end_date: "2026-06-12",
    status,
    download_available: status === "ativo" && !integrityBlocked && index % 9 !== 5,
    integrity_status: integrityBlocked ? "blocked" : "verified",
    integrity_blocked: integrityBlocked,
    storage_provider: "google_drive",
    template_used: "Modelo 2026",
    template_version_id: 4,
    issued_by: { id: 2, name: "Marina Oliveira", username: "m.oliveira" },
    batch_id: index <= 43 ? "batch-e2e-001" : null,
    file_size: 184320,
    certificate_text: "participou da atividade institucional descrita neste certificado.",
    revoked_at: status === "revogado" ? "2026-06-11T10:00:00Z" : null,
    revoke_reason: status === "revogado" ? "Correção administrativa" : null,
    reissue_count: 0,
    reissued_at: null,
    created_at: new Date(Date.UTC(2026, 5, 10, 12, index % 60)).toISOString(),
    updated_at: new Date(Date.UTC(2026, 5, 10, 12, index % 60)).toISOString(),
  };
}

const ALL = Array.from({ length: 137 }, (_, index) => certificate(index + 1));

/* Per-work (Mostra) certificates with 1, 3 and 8 authors. Synthetic names. */
const WORK_AUTHORS = [
  "Pessoa Exemplo Alfa",
  "Pessoa Exemplo Beta",
  "Pessoa Exemplo Gama",
  "Pessoa Exemplo Delta",
  "Pessoa Exemplo Épsilon",
  "Pessoa Exemplo Zeta",
  "Pessoa Exemplo Eta",
  "Pessoa Exemplo Teta",
];
function workCertificate(code, title, authorCount) {
  return {
    ...certificate(1),
    unique_code: code,
    participant_name: WORK_AUTHORS[0],
    event_name: "Mostra de Iniciação Científica 2026",
    course_name: null,
    certificate_type: "scientific_initiation",
    certificate_type_label: "Mostra de Iniciação Científica",
    workload_hours: null,
    status: "ativo",
    download_available: true,
    integrity_status: "verified",
    integrity_blocked: false,
    batch_id: "batch-e2e-mostra",
    authors: WORK_AUTHORS.slice(0, authorCount),
    team_name: "Equipe Verde",
    work_title: title,
    revoked_at: null,
    revoke_reason: null,
  };
}
/* What the history and the dashboard list: the works first, then ALL. */
const LISTED = [
  workCertificate("CERT-2026-9001A", "Compostagem doméstica", 1),
  workCertificate("CERT-2026-9003A", "Horta vertical automatizada", 3),
  workCertificate("CERT-2026-9008A", "Robô seguidor de linha", 8),
  ...ALL,
];

/** Search form of a name, as the backend normalises it: no accents or case. */
function foldName(value) {
  return String(value ?? "")
    .normalize("NFKD")
    .replace(/\p{M}/gu, "")
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean)
    .join(" ");
}

const USERS = [
  { id: 1, name: "Administrador da Secretaria", username: "secretaria", role: "admin", is_active: true, must_change_password: false, password_changed_at: "2026-05-01T10:00:00Z", created_at: "2026-01-15T10:00:00Z", updated_at: "2026-05-01T10:00:00Z" },
  { id: 2, name: "Marina Oliveira", username: "m.oliveira", role: "secretaria", is_active: true, must_change_password: false, password_changed_at: "2026-05-02T10:00:00Z", created_at: "2026-02-03T10:00:00Z", updated_at: "2026-05-02T10:00:00Z" },
  { id: 3, name: "Joana Almeida", username: "j.almeida", role: "secretaria", is_active: true, must_change_password: true, password_changed_at: null, created_at: "2026-03-11T10:00:00Z", updated_at: "2026-03-11T10:00:00Z" },
  { id: 4, name: "Auditoria Interna", username: "auditoria.interna", role: "auditor", is_active: true, must_change_password: false, password_changed_at: "2026-04-03T10:00:00Z", created_at: "2026-04-02T10:00:00Z", updated_at: "2026-04-03T10:00:00Z" },
  { id: 5, name: "Rafael Antigo", username: "r.antigo", role: "secretaria", is_active: false, must_change_password: false, password_changed_at: "2025-09-21T10:00:00Z", created_at: "2025-09-20T10:00:00Z", updated_at: "2026-01-02T10:00:00Z" },
];

const AUDIT = [
  { id: 90, action: "emission_completed", actor_id: 2, actor_username: "m.oliveira", target_type: "batch", target_id: "batch-e2e-001", details: { generated: 41, duplicates: 1, invalid: 2, failed: 0 }, created_at: "2026-06-10T14:32:00Z" },
  { id: 89, action: "certificate_revoked", actor_id: 1, actor_username: "secretaria", target_type: "certificate", target_id: "CERT-2026-0004A", details: { fields: ["status", "reason"] }, created_at: "2026-06-10T11:05:00Z" },
  { id: 88, action: "template_version_activated", actor_id: 1, actor_username: "secretaria", target_type: "template", target_id: "4", details: { version_number: 4 }, created_at: "2026-06-09T17:20:00Z" },
  { id: 87, action: "user_updated", actor_id: 1, actor_username: "secretaria", target_type: "admin_user", target_id: "3", details: { fields: ["role"] }, created_at: "2026-06-09T09:12:00Z" },
  { id: 86, action: "login_success", actor_id: 3, actor_username: "j.almeida", target_type: "auth", target_id: "3", details: null, created_at: "2026-06-09T08:02:00Z" },
  { id: 85, action: "login_failed", actor_id: null, actor_username: "desconhecido", target_type: "auth", target_id: null, details: { reason: "invalid_credentials" }, created_at: "2026-06-08T22:41:00Z" },
  { id: 84, action: "certificate_reissued", actor_id: 2, actor_username: "m.oliveira", target_type: "certificate", target_id: "CERT-2026-0031A", details: { reissue_count: 1 }, created_at: "2026-06-08T16:00:00Z" },
  { id: 83, action: "user_sessions_revoked", actor_id: 1, actor_username: "secretaria", target_type: "admin_user", target_id: "5", details: { count: 2 }, created_at: "2026-06-08T15:44:00Z" },
];

let SETTINGS = {
  id: 1,
  institution_name: "Instituto Acadêmico de Demonstração",
  issue_location: "São Paulo",
  signatory_name: "Prof.ª Helena Martins",
  signatory_title: "Diretora Acadêmica",
  public_url: "https://certificados.example.test",
  retention_days: 730,
  max_batch_rows: 2000,
  max_upload_mb: 10,
  secretaria_can_revoke: true,
  secretaria_can_reissue: true,
  updated_at: "2026-06-10T09:00:00Z",
  updated_by: 1,
};

const PNG_1PX = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
  "base64",
);
const TEMPLATE_VERSIONS = [
  { id: 4, version_number: 4, name: "Modelo 2026", is_active: true, certificate_type: null, image_width: 3508, image_height: 2480, background_url: "/templates/versions/4/background", created_at: "2026-05-02T10:00:00Z", activated_at: "2026-05-02T10:30:00Z" },
  { id: 3, version_number: 3, name: "Ajuste de assinatura", is_active: false, certificate_type: null, image_width: 3508, image_height: 2480, background_url: "/templates/versions/3/background", created_at: "2026-03-18T10:00:00Z", activated_at: null },
  { id: 2, version_number: 2, name: "Modelo 2025", is_active: false, certificate_type: null, image_width: 3508, image_height: 2480, background_url: "/templates/versions/2/background", created_at: "2025-08-01T10:00:00Z", activated_at: null },
];

const BATCHES = new Map();
const BATCH_KEYS = new Map();

function authUser(role) {
  const normalized = Object.hasOwn(PERMISSIONS, role) ? role : "auditor";
  return {
    id: normalized === "admin" ? 1 : normalized === "secretaria" ? 2 : 4,
    name: normalized === "admin" ? "Administrador da Secretaria" : normalized === "secretaria" ? "Marina Oliveira" : "Auditoria Interna",
    username: normalized === "admin" ? "secretaria" : normalized === "secretaria" ? "m.oliveira" : "auditoria.interna",
    role: normalized,
    permissions: PERMISSIONS[normalized],
    must_change_password: false,
  };
}

function send(res, status, body, headers = {}) {
  const payload = typeof body === "string" ? body : JSON.stringify(body);
  res.writeHead(status, {
    "content-type": "application/json; charset=utf-8",
    "access-control-allow-origin": res.req?.headers?.origin ?? "*",
    "access-control-allow-credentials": "true",
    "access-control-allow-headers": "content-type,idempotency-key,x-mock-scenario,x-mock-role",
    "access-control-allow-methods": "GET,POST,PATCH,PUT,OPTIONS",
    "access-control-expose-headers": "x-skipped-certificates,content-disposition",
    ...headers,
  });
  res.end(payload);
}

/** Same shape as the real API: ASCII `filename` plus the exact UTF-8 `filename*`. */
function contentDisposition(filename) {
  const ascii = filename
    .replace(/…/g, "...")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^\x20-\x7e]|["\\]/g, "_");
  return `attachment; filename="${ascii}"; filename*=UTF-8''${encodeURIComponent(filename)}`;
}

function sendBinary(res, status, body, contentType, filename) {
  res.writeHead(status, {
    "content-type": contentType,
    "content-disposition": contentDisposition(filename),
    "access-control-allow-origin": res.req?.headers?.origin ?? "*",
    "access-control-allow-credentials": "true",
    "access-control-expose-headers": "content-disposition,x-skipped-certificates",
  });
  res.end(body);
}

async function readText(req) {
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  return Buffer.concat(chunks).toString("utf8");
}

/* Same elements as the backend's default template (`_default_layout`) for a
 * 3508×2480 art, so the editor works on a realistic generic layout. */
function defaultLayout(id) {
  const text = (key, y, fontSize, extra = {}) => ({
    type: "text", key, x: 1754, y, fontSize, fontFamily: "Times New Roman",
    color: "#000000", align: "center", bold: false, italic: false, ...extra,
  });
  return {
    background: `/templates/versions/${id}/background`,
    image_width: 3508,
    image_height: 2480,
    elements: [
      text("static", 297, 124, { staticText: "CERTIFICADO", bold: true }),
      text("static", 744, 54, { staticText: "Certificamos, para os devidos fins, que" }),
      text("name", 880, 111, { bold: true }),
      text("texto_certificado", 1140, 59, { x: 175, align: "left" }),
      text("issue_line", 1785, 54),
      text("signatory_name", 1959, 44),
      text("signatory_title", 2046, 39),
      text("validation_code", 2281, 34),
      { type: "qr", key: "qr", x: 175, y: 2033, width: 297, height: 297 },
    ],
  };
}

/* A Mostra batch: one certificate per work, every author on it. */
function workPreview(problem) {
  const works = [
    ["Horta vertical automatizada", ["Ana Carolina Souza", "João Pedro Lima", "Mariana Alves Ferreira"], 60],
    ["Robô seguidor de linha", ["Carlos Eduardo Nunes"], null],
  ];
  return {
    total: 2,
    valid_count: 2,
    invalid_count: 0,
    valid: works.map(([title, authors, hours], index) => ({
      row_number: index + 2,
      nome: authors[0],
      curso: "",
      evento: "Mostra de Iniciação Científica 2026",
      carga_horaria: hours,
      data_emissao: "10 de junho de 2026",
      data_inicio: "",
      data_fim: "",
      autores: authors,
      equipe: "",
      titulo_trabalho: title,
    })),
    invalid: [],
    events: [{ key: "Mostra de Iniciação Científica 2026", label: "Mostra de Iniciação Científica 2026", count: 2 }],
    resolved_text_preview:
      'Certificamos que o trabalho "Horta vertical automatizada" foi apresentado no evento ' +
      "Mostra de Iniciação Científica 2026, com carga horária de 60 horas.",
    warnings: [],
    layout_warnings: [],
    missing_settings: [],
    missing_settings_message: null,
    empty_fields: [],
    can_manage_settings: true,
    template_problem: problem,
    can_manage_templates: true,
  };
}

async function readJson(req) {
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  if (!chunks.length) return {};
  try {
    return JSON.parse(Buffer.concat(chunks).toString("utf8"));
  } catch {
    return {};
  }
}

function completedBatch(id) {
  const generated = ALL.slice(0, 41).map((row) => ({
    name: row.participant_name,
    code: row.unique_code,
  }));
  const result = {
    batch_id: id,
    generated,
    generated_count: 41,
    duplicates: [{ name: "Ana Carolina Souza", existing_code: "CERT-2025-0091B" }],
    duplicate_count: 1,
    failed: [],
    failed_count: 0,
    invalid: [
      { row_number: 8, errors: ["carga_horaria deve ser um número inteiro"] },
      { row_number: 23, errors: ["nome é obrigatório"] },
    ],
    invalid_count: 2,
    total_rows: 44,
  };
  return {
    id,
    status: "completed",
    total_rows: 44,
    valid_count: 42,
    invalid_count: 2,
    processed_count: 42,
    generated_count: 41,
    duplicate_count: 1,
    failed_count: 0,
    certificate_type: "listener",
    certificate_type_label: "Ouvinte",
    progress_percent: 100,
    result,
    invalid_report: result.invalid.map((row) => ({ ...row, data: {} })),
    error_message: null,
    created_by: 2,
    created_at: "2026-06-10T14:30:00Z",
    started_at: "2026-06-10T14:30:01Z",
    completed_at: "2026-06-10T14:32:00Z",
    updated_at: "2026-06-10T14:32:00Z",
  };
}

const server = createServer(async (req, res) => {
  res.req = req;
  const url = new URL(req.url, "http://localhost");
  const path = url.pathname;
  if (req.method === "OPTIONS") return send(res, 204, "");

  const scenario = req.headers["x-mock-scenario"] ?? "default";
  const role = req.headers["x-mock-role"] ?? "admin";
  const current = authUser(role);

  if (path === "/institution") {
    return send(res, 200, {
      institution_name: SETTINGS.institution_name,
      public_url: SETTINGS.public_url,
    });
  }
  if (path === "/auth/me") return send(res, 200, current);
  if (path === "/auth/login") return send(res, 200, { user: current });
  if (path === "/auth/change-password") {
    return send(res, 200, { ok: true, sessions_revoked: 1 });
  }
  if (path === "/auth/logout" || path === "/auth/sessions/revoke-all") {
    return send(res, 200, { ok: true, revoked: 2 });
  }

  if (scenario === "error") return send(res, 500, { detail: "Erro interno simulado." });
  if (scenario === "forbidden") {
    return send(res, 403, { detail: "Seu perfil não permite esta consulta." });
  }
  if (scenario === "rate-limited") {
    return send(res, 429, { detail: "Muitas solicitações." }, { "retry-after": "30" });
  }
  const empty = scenario === "empty";

  if (path === "/admin/stats") {
    return send(res, 200, empty
      ? { total: 0, active: 0, revoked: 0, failed: 0, pending: 0, recent: 0, recent_days: 30, integrity_blocked: 0, active_without_file: 0 }
      : { total: 137, active: 124, revoked: 9, failed: 4, pending: 0, recent: 42, recent_days: 30, integrity_blocked: 2, active_without_file: 3 });
  }
  if (path === "/admin/recent-certificates") {
    return send(res, 200, empty ? [] : LISTED.slice(0, 8));
  }

  if (path === "/admin/users" && req.method === "GET") {
    const items = empty ? [] : USERS;
    return send(res, 200, { items, total: items.length });
  }
  if (path === "/admin/users" && req.method === "POST") {
    const body = await readJson(req);
    const created = {
      id: Math.max(...USERS.map((user) => user.id)) + 1,
      name: String(body.name ?? "Novo usuário"),
      username: String(body.username ?? `novo.${Date.now()}`),
      role: String(body.role ?? "secretaria"),
      is_active: true,
      must_change_password: true,
      password_changed_at: null,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };
    USERS.push(created);
    return send(res, 201, created);
  }
  const userMatch = path.match(/^\/admin\/users\/(\d+)(?:\/(activate|deactivate|reset-password|sessions\/revoke-all))?$/);
  if (userMatch) {
    const target = USERS.find((user) => user.id === Number(userMatch[1]));
    if (!target) return send(res, 404, { detail: "Usuário não encontrado." });
    const action = userMatch[2];
    if (req.method === "PATCH") {
      const changes = await readJson(req);
      Object.assign(target, changes, { updated_at: new Date().toISOString() });
      return send(res, 200, { user: target, sessions_revoked: changes.role ? 1 : 0 });
    }
    if (req.method === "POST" && action === "sessions/revoke-all") {
      return send(res, 200, { revoked: 2 });
    }
    if (req.method === "POST" && action === "reset-password") {
      target.must_change_password = true;
      return send(res, 200, { user: target, sessions_revoked: 2 });
    }
    if (req.method === "POST" && (action === "activate" || action === "deactivate")) {
      target.is_active = action === "activate";
      return send(res, 200, { user: target, sessions_revoked: action === "deactivate" ? 2 : 0 });
    }
  }

  if (path === "/admin/audit") {
    const action = url.searchParams.get("action");
    const actor = (url.searchParams.get("actor") ?? "").toLowerCase();
    const limit = Number(url.searchParams.get("limit") ?? 50);
    const offset = Number(url.searchParams.get("offset") ?? 0);
    let rows = empty ? [] : AUDIT;
    if (action) rows = rows.filter((entry) => entry.action === action);
    if (actor) rows = rows.filter((entry) => entry.actor_username?.toLowerCase().includes(actor));
    return send(res, 200, { items: rows.slice(offset, offset + limit), total: rows.length, limit, offset });
  }

  if (path === "/admin/settings" && req.method === "GET") return send(res, 200, SETTINGS);
  if (path === "/admin/settings" && req.method === "PUT") {
    const body = await readJson(req);
    SETTINGS = { ...SETTINGS, ...body, id: 1, updated_at: new Date().toISOString(), updated_by: 1 };
    return send(res, 200, SETTINGS);
  }

  if (path === "/certificates/body-variables" && req.method === "GET") {
    // Mirrors BODY_VARIABLES in services/certificate_text.py.
    const variables = [
      ["nome", "Nome"],
      ["carga_horaria", "Carga horária"],
      ["certificate_type", "Tipo do certificado"],
      ["evento", "Evento"],
      ["equipe", "Equipe"],
      ["titulo_trabalho", "Título do trabalho"],
    ].map(([name, label]) => ({ name, token: `{{${name}}}`, label, per_work: name !== "nome" }));
    return send(res, 200, {
      variables,
      per_work_automatic_text:
        'Certificamos que o trabalho "{{titulo_trabalho}}" foi apresentado no evento ' +
        "{{evento}}, com carga horária de {{carga_horaria}} horas.",
    });
  }
  if (path === "/certificates/spreadsheet-template") {
    return sendBinary(res, 200, Buffer.from("PK\u0003\u0004mock-xlsx"), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "modelo-certificados.xlsx");
  }
  if (path === "/integrations/google-drive/status") {
    return send(res, 200, {
      connected: true,
      account_email: "secretaria.sintetica@instituicao.example",
      expires_at: "2026-08-14T18:00:00Z",
    });
  }
  if (path === "/integrations/google-drive/picker-session") {
    return send(res, 200, {
      access_token: "synthetic-e2e-picker-session",
      api_key: "synthetic-e2e-picker-key",
      app_id: "123456789",
      expires_at: "2026-08-14T18:00:00Z",
    });
  }
  if (path === "/integrations/google-drive/folders/select" && req.method === "POST") {
    return send(res, 200, { folder_name: "Semana de Inovação 2026", ready: true });
  }
  if (path === "/integrations/google-drive/disconnect" && req.method === "POST") {
    return send(res, 200, { disconnected: true, existing_certificates_unchanged: true });
  }
  if (path === "/certificates/validate-spreadsheet") {
    const form = await readText(req);
    if (/name="certificate_type"\r\n\r\nscientific_initiation/.test(form)) {
      return send(res, 200, workPreview(
        scenario === "mostra-sem-template"
          ? "Não há template ativo do tipo Mostra de Iniciação Científica. Este tipo não usa o template genérico, porque o certificado vale para todos os autores e não destaca nenhum nome. Em Template, use “Editar (nova versão)”, escolha o tipo Mostra de Iniciação Científica (o editor monta o ponto de partida sem o nome e com o bloco Autores), ajuste, salve e ative a versão."
          : null,
      ));
    }
    return send(res, 200, {
      total: 44,
      valid_count: 42,
      invalid_count: 2,
      valid: ALL.slice(0, 42).map((row, index) => ({
        row_number: index + 2,
        nome: row.participant_name,
        curso: row.course_name,
        evento: row.event_name,
        carga_horaria: row.workload_hours,
        data_emissao: "10/06/2026",
        data_inicio: "10/06/2026",
        data_fim: "12/06/2026",
      })),
      invalid: [
        { row_number: 8, errors: ["carga_horaria deve ser um número inteiro"], data: {} },
        { row_number: 23, errors: ["nome é obrigatório"], data: {} },
      ],
      events: [{ key: "Semana de Inovação", label: "Semana de Inovação", count: 42 }],
      resolved_text_preview: "participou da Semana de Inovação, com carga horária total de 12 horas.",
      warnings: [],
      layout_warnings: [],
      missing_settings: [],
      missing_settings_message: null,
      empty_fields: [],
      can_manage_settings: role === "admin",
    });
  }
  if (path === "/emission-batches" && req.method === "POST") {
    const key = String(req.headers["idempotency-key"] ?? `key-${Date.now()}`);
    let id = BATCH_KEYS.get(key);
    if (!id) {
      id = `batch-e2e-${String(BATCHES.size + 1).padStart(3, "0")}`;
      BATCH_KEYS.set(key, id);
      const finished = completedBatch(id);
      BATCHES.set(id, finished);
    }
    const finished = BATCHES.get(id);
    return send(res, 202, {
      ...finished,
      status: "queued",
      processed_count: 0,
      generated_count: 0,
      duplicate_count: 0,
      progress_percent: 0,
      result: null,
      completed_at: null,
    });
  }
  const batchByKey = path.match(/^\/emission-batches\/by-idempotency-key\/(.+)$/);
  if (batchByKey) {
    const id = BATCH_KEYS.get(decodeURIComponent(batchByKey[1]));
    return id ? send(res, 200, BATCHES.get(id)) : send(res, 404, { detail: "Lote não encontrado." });
  }
  const batchMatch = path.match(/^\/emission-batches\/([^/]+)$/);
  if (batchMatch) {
    const batch = BATCHES.get(decodeURIComponent(batchMatch[1]));
    return batch ? send(res, 200, batch) : send(res, 404, { detail: "Lote não encontrado." });
  }

  if (path === "/certificates/download-zip" && req.method === "POST") {
    return sendBinary(res, 200, Buffer.from("PK\u0003\u0004mock-zip"), "application/zip", "certificados.zip");
  }
  if (path.startsWith("/certificate-file/") && req.method === "GET") {
    const code = decodeURIComponent(path.slice("/certificate-file/".length));
    const row = LISTED.find((item) => item.unique_code === code);
    const holder = row?.work_title && row.certificate_type === "scientific_initiation" ? row.work_title : row?.participant_name;
    const filename = row ? `${holder} - ${row.event_name} - ${code}.pdf` : `${code}.pdf`;
    return sendBinary(res, 200, Buffer.from("%PDF-1.4 mock"), "application/pdf", filename);
  }
  if (path === "/certificates" && req.method === "GET") {
    const limit = Number(url.searchParams.get("limit") ?? 20);
    const offset = Number(url.searchParams.get("offset") ?? 0);
    const filters = {
      status: url.searchParams.get("status") ?? "",
      name: foldName(url.searchParams.get("name")),
      code: (url.searchParams.get("code") ?? "").toLowerCase(),
      course: (url.searchParams.get("course") ?? "").toLowerCase(),
      event: (url.searchParams.get("event") ?? "").toLowerCase(),
      certificateType: url.searchParams.get("certificate_type") ?? "",
      batch: url.searchParams.get("batch_id") ?? "",
    };
    let rows = empty ? [] : LISTED;
    if (filters.status) rows = rows.filter((row) => row.status === filters.status);
    // Like the backend: the holder or any author of a per-work certificate.
    if (filters.name) {
      rows = rows.filter((row) =>
        [row.participant_name, ...(row.authors ?? [])].some((name) => foldName(name).includes(filters.name)),
      );
    }
    if (filters.code) rows = rows.filter((row) => row.unique_code.toLowerCase().includes(filters.code));
    if (filters.course) rows = rows.filter((row) => (row.course_name ?? "").toLowerCase().includes(filters.course));
    if (filters.event) rows = rows.filter((row) => row.event_name.toLowerCase().includes(filters.event));
    if (filters.certificateType) rows = rows.filter((row) => row.certificate_type === filters.certificateType);
    if (filters.batch) rows = rows.filter((row) => row.batch_id === filters.batch);
    return send(res, 200, { items: rows.slice(offset, offset + limit), total: rows.length, limit, offset });
  }
  const certificateAction = path.match(/^\/certificates\/([^/]+)(?:\/(revoke|reissue))?$/);
  if (certificateAction) {
    const code = decodeURIComponent(certificateAction[1]);
    const found = LISTED.find((row) => row.unique_code === code);
    if (!found) return send(res, 404, { detail: "Certificado não encontrado." });
    if (req.method === "GET" && !certificateAction[2]) return send(res, 200, found);
    if (req.method === "POST" && certificateAction[2] === "revoke") {
      found.status = "revogado";
      found.download_available = false;
      found.revoked_at = new Date().toISOString();
      return send(res, 200, found);
    }
    if (req.method === "POST" && certificateAction[2] === "reissue") {
      found.reissue_count += 1;
      found.reissued_at = new Date().toISOString();
      return send(res, 200, found);
    }
  }

  if (path === "/templates/sample-data") {
    // Same shape the backend produces: institutional values come from SETTINGS.
    const body = "participou da Semana de Inovação, com carga horária total de 12 horas.";
    return send(res, 200, {
      values: {
        name: "Joao Silva",
        event: "Workshop de Inteligencia Artificial",
        course: "Sistemas de Informação",
        date: "27 de abril de 2026",
        institution_name: SETTINGS.institution_name,
        issue_location: SETTINGS.issue_location,
        issue_line: `${SETTINGS.issue_location}, 27 de abril de 2026.`,
        signatory_name: SETTINGS.signatory_name,
        signatory_title: SETTINGS.signatory_title,
        validation_code: "CERT-2026-EXEMPL",
        texto_certificado: body,
        certificate_text: body,
        certificate_type: "Ouvinte",
      },
      empty_settings: [],
      can_manage_settings: role === "admin",
    });
  }
  if (path === "/templates/text-layout" && req.method === "POST") {
    // Line breaks are measured by the real backend; the mock lets the editor
    // fall back to its local approximation by answering with no items.
    return send(res, 200, { items: [] });
  }
  if (path === "/templates/versions" && req.method === "GET") {
    return send(res, 200, empty ? [] : TEMPLATE_VERSIONS);
  }
  if (path === "/templates/active") {
    return empty ? send(res, 404, { detail: "Nenhuma versão ativa." }) : send(res, 200, TEMPLATE_VERSIONS[0]);
  }
  if (/^\/templates\/versions\/\d+\/background$/.test(path)) {
    res.writeHead(200, { "content-type": "image/png", "access-control-allow-origin": req.headers.origin ?? "*", "cache-control": "no-store" });
    return res.end(PNG_1PX);
  }
  if (/^\/templates\/versions\/\d+$/.test(path)) {
    const id = Number(path.split("/").pop());
    const version = TEMPLATE_VERSIONS.find((entry) => entry.id === id);
    return send(res, 200, { ...version, layout: defaultLayout(id) });
  }

  return send(res, 404, { detail: "Rota não encontrada no mock." });
});

server.listen(PORT, () => {
  console.log(`mock-api listening on http://localhost:${PORT}`);
});
