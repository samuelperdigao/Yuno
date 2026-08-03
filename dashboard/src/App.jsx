import { useMemo, useState } from "react";
import { Activity, Box, CheckCircle2, ClipboardCopy, ClipboardList, KeyRound, Plus, Save, ShieldCheck, Ticket, ToggleLeft, UserCheck } from "lucide-react";
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
  const [issuedLicenses, setIssuedLicenses] = useState([]);
  const [licenseDraft, setLicenseDraft] = useState({ reference: "", customer_name: "", customer_email: "", customer_discord_user_id: "" });
  const [ownerId, setOwnerId] = useState("");
  const [config, setConfig] = useState(defaultConfig);
  const [products, setProducts] = useState([]);
  const [productDraft, setProductDraft] = useState({ name: "", unit: "unidade" });
  const [selectedPanelModule, setSelectedPanelModule] = useState("set");
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

  function updatePanelMessage(field, value) {
    setConfig((current) => ({
      ...current,
      messages: {
        ...(current.messages || {}),
        [selectedPanelModule]: {
          ...(current.messages?.[selectedPanelModule] || {}),
          panel: {
            ...(current.messages?.[selectedPanelModule]?.panel || {}),
            [field]: value,
          },
        },
      },
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

  async function loadLicenses() {
    await run(async () => {
      const data = await api("/licenses", { adminToken });
      setIssuedLicenses(data);
    }, "Chaves carregadas.");
  }

  async function issueLicense() {
    await run(async () => {
      const data = await api("/licenses/issue", {
        method: "POST",
        adminToken,
        body: Object.fromEntries(Object.entries(licenseDraft).map(([key, value]) => [key, value.trim() || null])),
      });
      setIssuedLicenses((current) => [data, ...current.filter((item) => item.key !== data.key)]);
      setLicenseKey(data.key);
      setLicenseDraft({ reference: "", customer_name: "", customer_email: "", customer_discord_user_id: "" });
    }, "Chave lifetime emitida e pronta para copiar.");
  }

  async function copyLicense(key) {
    try {
      await navigator.clipboard.writeText(key);
      setStatus("Chave copiada. Envie somente a chave ao cliente; nunca envie o token admin.");
    } catch {
      setLicenseKey(key);
      setStatus("Nao consegui acessar a area de transferencia. A chave foi colocada no campo de ativacao.");
    }
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
            <h2>Emitir chave de produto</h2>
            <p>Fluxo administrativo manual e seguro para vendas. O token admin nunca deve ser entregue ao comprador.</p>
            <div className="form-grid">
              <label>
                Referencia da venda
                <input value={licenseDraft.reference} onChange={(event) => setLicenseDraft((current) => ({ ...current, reference: event.target.value }))} placeholder="Ex: MP-12345 ou PEDIDO-001" />
              </label>
              <label>
                Nome do cliente
                <input value={licenseDraft.customer_name} onChange={(event) => setLicenseDraft((current) => ({ ...current, customer_name: event.target.value }))} placeholder="Nome ou empresa" />
              </label>
              <label>
                E-mail do cliente
                <input value={licenseDraft.customer_email} onChange={(event) => setLicenseDraft((current) => ({ ...current, customer_email: event.target.value }))} type="email" placeholder="cliente@exemplo.com" />
              </label>
              <label>
                Discord do cliente
                <input value={licenseDraft.customer_discord_user_id} onChange={(event) => setLicenseDraft((current) => ({ ...current, customer_discord_user_id: event.target.value }))} placeholder="User ID" />
              </label>
            </div>
            <div className="panel-actions">
              <button onClick={issueLicense} disabled={busy || !adminToken || !licenseDraft.reference}>
                <Plus size={18} /> Emitir chave
              </button>
              <button className="secondary" onClick={loadLicenses} disabled={busy || !adminToken}>
                <Activity size={18} /> Atualizar lista
              </button>
            </div>
            <div className="list license-list">
              {issuedLicenses.slice(0, 20).map((item) => (
                <div className="row" key={item.key}>
                  <div>
                    <strong>{item.payment_reference || "Sem referencia"}</strong>
                    <small>{item.status} · {item.guild_name || item.guild_id || "ainda nao ativada"}</small>
                  </div>
                  <button className="icon-button" onClick={() => copyLicense(item.key)} title="Copiar chave">
                    <ClipboardCopy size={17} /> Copiar
                  </button>
                </div>
              ))}
            </div>
          </div>

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
        </section>

        <section className="panel">
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

        <section className="panel">
          <h2>Personalizacao dos paineis</h2>
          <p>Campos vazios usam o visual profissional padrao do Yuno. Depois de salvar, rode o comando de painel do modulo para atualizar a mensagem fixa.</p>
          <div className="form-grid">
            <label>
              Modulo
              <select value={selectedPanelModule} onChange={(event) => setSelectedPanelModule(event.target.value)}>
                {modules.map((module) => <option key={module.id} value={module.id}>{module.label}</option>)}
              </select>
            </label>
            <label>
              Titulo do painel
              <input
                value={config.messages?.[selectedPanelModule]?.panel?.title || ""}
                onChange={(event) => updatePanelMessage("title", event.target.value)}
                placeholder="Use o titulo padrao"
                maxLength={256}
              />
            </label>
            <label>
              Cor (hexadecimal)
              <input
                value={config.messages?.[selectedPanelModule]?.panel?.color || ""}
                onChange={(event) => updatePanelMessage("color", event.target.value)}
                placeholder="#FFC72C"
                maxLength={9}
              />
            </label>
            <label>
              Descricao do painel
              <textarea
                value={config.messages?.[selectedPanelModule]?.panel?.description || ""}
                onChange={(event) => updatePanelMessage("description", event.target.value)}
                placeholder="Use a descricao padrao do Yuno"
                maxLength={4096}
              />
            </label>
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
