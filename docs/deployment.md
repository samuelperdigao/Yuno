# Deployment no Oracle

O Yuno deve rodar no Oracle como uma stack Docker Compose: PostgreSQL, Redis, API FastAPI, bot Discord, dashboard React servido por Nginx e Caddy para HTTPS.

## 1. Preparar a instancia

Na instancia Oracle, instale Git, Docker e Docker Compose. Libere no firewall/security list as portas:

- `80/tcp` para HTTP e emissao inicial do certificado
- `443/tcp` para HTTPS

As portas internas `8000` e `5173` ficam presas em `127.0.0.1` pelo `docker-compose.yml`.

## 2. Clonar o repositorio

```bash
git clone https://github.com/samuelperdigao/Yuno.git
cd Yuno
cp .env.example .env
```

Preencha o `.env` com os valores reais. Em producao, mantenha:

```env
APP_ENV=production
YUNO_DOMAIN=seudominio.com
PUBLIC_BASE_URL=https://seudominio.com
API_BASE_URL=http://api:8000
VITE_API_BASE_URL=https://seudominio.com/api
DISCORD_REDIRECT_URI=https://seudominio.com/auth/discord/callback
```

Use o mesmo valor de `POSTGRES_PASSWORD` dentro de `DATABASE_URL`.

## 3. Subir a stack

```bash
docker compose up -d --build
docker compose ps
```

Verificacoes:

```bash
docker compose logs -f api
docker compose logs -f bot
docker compose logs -f caddy
```

API publica:

```bash
curl https://seudominio.com/api/health
```

Dashboard:

```text
https://seudominio.com
```

## 4. Atualizar deploy

```bash
git pull
docker compose up -d --build
docker compose ps
```

O script `deploy.yuno.ps1` cria e valida um dump `yuno-predeploy-*.sql` antes do `git pull` sempre que o PostgreSQL Docker estiver em execução. No modo legado com `systemd` e SQLite, ele usa a API de backup do próprio SQLite para gerar `yuno-predeploy-*.db` de forma consistente. Se o backup falhar ou ficar vazio, o deploy é interrompido.

## 5. Backups

Use os scripts em `scripts/` para backup e restauracao do PostgreSQL. Salve os backups fora da instancia sempre que possivel.

Exemplo de agendamento diário no `crontab` do usuário de deploy:

```cron
15 3 * * * cd /home/ubuntu/yuno && ./scripts/backup-postgres.sh >> /home/ubuntu/yuno/backups/backup.log 2>&1
```

Teste a restauração em um banco separado antes de considerar o backup validado.
