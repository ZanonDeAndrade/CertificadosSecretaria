# Checklist de implantação local

Marque cada item no servidor alvo após executar o procedimento de
`docs/DEPLOY_LOCAL_SERVER.md`. Itens abaixo não foram marcados pelo ambiente de
preparação quando dependem da rede física, do reboot do servidor alvo ou de um
restore separado.

## Validado no ambiente de preparação

- [x] frontend e backend buildam no perfil LAN
- [x] PostgreSQL inicia e migrations executam
- [x] health checks de Nginx, APIs, banco e worker funcionam
- [x] login HTTP, emissão, upload, geração e downloads funcionam via Nginx
- [x] dados e sessão persistem após reinício dos containers
- [x] backup contém banco, storage, configuração e secrets
- [x] somente `web` publica `80/tcp` no Compose
- [x] Compose de desenvolvimento inicia PostgreSQL, migrations, storage local,
  admin, consulta, worker, Nginx e login
- [x] desenvolvimento nativo responde em Vite `:5173`, API `:8000` e consulta
  `:8001`
- [x] fluxos OAuth/Drive são cobertos por testes simulados

## Obrigatório no servidor alvo

- [ ] frontend builda
- [ ] backend builda
- [ ] banco inicia
- [ ] migrations funcionam
- [ ] aplicação inicia
- [ ] aplicação reinicia
- [ ] aplicação inicia após reboot
- [ ] health check funciona
- [ ] login funciona
- [ ] CRUD principal funciona
- [ ] uploads funcionam
- [ ] downloads funcionam
- [ ] imagens funcionam
- [ ] API funciona
- [ ] frontend funciona via IP
- [ ] nenhuma URL localhost indevida no navegador cliente
- [ ] nenhuma credencial está no Git
- [ ] CORS está configurado para `LOCAL_SERVER_URL`
- [ ] firewall permite apenas SSH e HTTP necessários
- [ ] PostgreSQL não está exposto na rede
- [ ] logs de containers funcionam e possuem rotação do Docker
- [ ] backup externo foi executado
- [ ] restore foi testado em ambiente separado
- [ ] consumo de RAM foi analisado com `docker stats`
- [ ] consumo de disco foi analisado com `df -h` e `du -sh runtime/storage`
- [ ] integrações externas e limites de LAN foram revisados
- [ ] credenciais reais do Google Drive/OAuth foram configuradas e validadas em
  ambiente HTTPS com domínio, caso a integração seja necessária
