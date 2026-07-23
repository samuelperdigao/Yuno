import { useMemo, useState } from "react";
import { Activity, Box, CheckCircle2, ClipboardList, KeyRound, Save, ShieldCheck, Ticket, ToggleLeft, UserCheck } from "lucide-react";
import { api, modules } from "./api";

const defaultConfig = {
  guild_name: "",
  admin_role_ids: [],
  log_channel_id: "",
  modules: Object.fromEntries(modules.map((module) => [module.id, true])),
  command_permissions: {},
  messages: {},
  settings: {},
};

const moduleIcons = {
  set: UserCheck,
  meta: Activity,
  ticket: Ticket,
  parceria: ShieldCheck,
  encomenda: ClipboardList,
  ausencia: ToggleLeft,
  radio: Activity,
  producao: Box,
};

function asList(value) {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

export default function App() {
  const [adminToken, setAdminToken] = useState("");
  const [guildId, setGuildId] = useState("");
  const [licenseKey, setLicenseKey] = useState("");
  const [ownerId, setOwnerId] = useState("");
  const [config, setConfig] = useState(defaultConfig);
  const [products, setProducts] = useState([]);
  const [productDraft, setProductDraft] = useState({ name: "", unit: "unidade" });
  const [status, setStatus] = useState("Pronto para configurar.");
  const [busy, setBusy] = useState(false);

  const enabledCount = useMemo(() => Object.values(config.modules || {}).filter(Boolean).length, [config.modules]);

  async function run(action, success) {
    setBusy(true);
    try {
      await action();
      setStatus(success);
    } catch (error) {
      setStatus(error.message);
    } finally {
      setBusy(false);
    }
  }

  function updateConfig(patch) {
    setConfig((current) => ({ ...current, ...patch }));
  }

  function toggleModule(moduleId) {
    setConfig((current) => ({
      ...current,
      modules: { ...current.modules, [moduleId]: !current.modules?.[moduleId] },
    }));
  }

  async function loadConfig() {
    await run(async () => {
      const data = await api(`/guilds/${guildId}/config`, { adminToken });
      setConfig({ ...defaultConfig, ...data });
      const productData = await api(`/guilds/${guildId}/products`, { adminToken });
      setProducts(productData);
    }, "Configuracao carregada.");
  }

  async function saveConfig() {
    await run(async () => {
      await api(`/guilds/${guildId}/config`, {
        method: "PUT",
        adminToken,
        body: config,
      });
    }, "Configuracao salva.");
  }

  async function activateLicense() {
    await run(async () => {
      const data = await api("/licenses/activate", {
        method: "POST",
        body: {
          license_key: licenseKey,
          guild_id: guildId,
          guild_name: config.guild_name,
          owner_discord_id: ownerId,
        },
      });
      setStatus(`Licenca ${data.key} ativada para ${data.guild_name || data.guild_id}.`);
    }, "Licenca ativada.");
  }

  async function createProduct() {
    await run(async () => {
      const product = await api(`/guilds/${guildId}/products`, {
        method: "POST",
        adminToken,
        body: { ...productDraft, active: true },
      });
      setProducts((current) => [...current, product]);
      setProductDraft({ name: "", unit: "unidade" });
    }, "Produto adicionado.");
  }

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <img className="brand-mark" src="/Yuno.png" alt="Logo do Yuno" />
          <div>
            <strong>Yuno</strong>
            <span>FiveM Ops</span>
          </div>
        </div>

        <label>
          Token admin
          <input value={adminToken} onChange={(event) => setAdminToken(event.target.value)} type="password" placeholder="x-yuno-admin-token" />
        </label>
        <label>
          ID do servidor
          <input value={guildId} onChange={(event) => setGuildId(event.target.value)} placeholder="Guild ID" />
        </label>
        <button className="primary" onClick={loadConfig} disabled={busy || !adminToken || !guildId}>
          <Activity size={18} /> Carregar
        </button>
        <p className="status">{status}</p>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div>
            <h1>Configuracao do servidor</h1>
            <p>{enabledCount} modulos ativos no MVP lifetime.</p>
          </div>
          <img className="topbar-logo" src="/Yuno.png" alt="" />
          <button className="primary" onClick={saveConfig} disabled={busy || !adminToken || !guildId}>
            <Save size={18} /> Salvar
          </button>
        </header>

        <section className="grid two">
          <div className="panel">
            <h2>Ativacao</h2>
            <div className="form-grid">
              <label>
                Chave lifetime
                <input value={licenseKey} onChange={(event) => setLicenseKey(event.target.value)} placeholder="licenca gerada pelo pagamento" />
              </label>
              <label>
                Dono Discord
                <input value={ownerId} onChange={(event) => setOwnerId(event.target.value)} placeholder="User ID do comprador" />
              </label>
              <label>
                Nome do servidor
                <input value={config.guild_name || ""} onChange={(event) => updateConfig({ guild_name: event.target.value })} placeholder="Nome exibido no painel" />
              </label>
              <button onClick={activateLicense} disabled={busy || !licenseKey || !guildId || !ownerId}>
                <KeyRound size={18} /> Ativar licenca
              </button>
            </div>
          </div>

          <div className="panel">
            <h2>Permissoes base</h2>
            <div className="form-grid">
              <label>
                Cargos administradores
                <input
                  value={(config.admin_role_ids || []).join(", ")}
                  onChange={(event) => updateConfig({ admin_role_ids: asList(event.target.value) })}
                  placeholder="IDs separados por virgula"
                />
              </label>
              <label>
                Canal de logs
                <input value={config.log_channel_id || ""} onChange={(event) => updateConfig({ log_channel_id: event.target.value })} placeholder="Channel ID" />
              </label>
            </div>
          </div>
        </section>

        <section className="panel">
          <h2>Modulos do MVP</h2>
          <div className="module-grid">
            {modules.map((module) => {
              const Icon = moduleIcons[module.id] || CheckCircle2;
              const active = Boolean(config.modules?.[module.id]);
              return (
                <button key={module.id} className={`module-toggle ${active ? "active" : ""}`} onClick={() => toggleModule(module.id)}>
                  <Icon size={20} />
                  <span>{module.label}</span>
                  <strong>{active ? "Ativo" : "Pausado"}</strong>
                </button>
              );
            })}
          </div>
        </section>

        <section className="grid two">
          <div className="panel">
            <h2>Produtos</h2>
            <div className="inline-form">
              <input value={productDraft.name} onChange={(event) => setProductDraft((current) => ({ ...current, name: event.target.value }))} placeholder="Produto" />
              <input value={productDraft.unit} onChange={(event) => setProductDraft((current) => ({ ...current, unit: event.target.value }))} placeholder="Unidade" />
              <button onClick={createProduct} disabled={busy || !guildId || !adminToken || !productDraft.name}>Adicionar</button>
            </div>
            <div className="list">
              {products.map((product) => (
                <div className="row" key={product.id}>
                  <span>{product.name}</span>
                  <small>{product.unit}</small>
                </div>
              ))}
            </div>
          </div>

          <div className="panel">
            <h2>Regras avancadas</h2>
            <textarea
              value={JSON.stringify(config.command_permissions || {}, null, 2)}
              onChange={(event) => {
                try {
                  updateConfig({ command_permissions: JSON.parse(event.target.value || "{}") });
                } catch {
                  setStatus("JSON de permissoes invalido.");
                }
              }}
              spellCheck="false"
            />
          </div>
        </section>
      </section>
    </main>
  );
}
