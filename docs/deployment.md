# Deployment

## GitHub

O projeto deve ser mantido em repositorio privado. Arquivos sensiveis como `.env`, bancos locais, caches, `node_modules` e builds ficam ignorados pelo `.gitignore`.

## Vercel

A Vercel deve hospedar o dashboard React/Vite. A raiz do repositorio possui `vercel.json` configurado para:

- instalar dependencias em `dashboard/`
- rodar `npm run build`
- publicar `dashboard/dist`

Configure `VITE_API_BASE_URL` no painel da Vercel apontando para a URL publica da API do Yuno.

## API e bot

A API FastAPI e o bot Discord precisam de um ambiente com processo persistente, como VPS, Docker Compose, Railway, Render, Fly.io ou outro host de backend. A Vercel nao deve ser usada para manter o bot Discord conectado continuamente.
