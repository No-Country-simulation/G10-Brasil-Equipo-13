# Webhook local com envio de e-mail

O complemento `docker-compose.email.yml` inicia o serviço `notificador` na rede
Docker, sem publicar portas no computador. A API envia os alertas para
`http://notificador:8080/alertas`. O notificador autentica o token Bearer e envia
o corpo da mensagem por SMTP com TLS. Não há dependências adicionais.

## Configuração

1. Copie `.env.notificador.example` para `.env.notificador.local`, ignorado pelo Git.
2. Preencha remetente, destinatário fixo e credenciais SMTP nesse arquivo. No Gmail,
   use uma senha de app com verificação em duas etapas:
   https://support.google.com/accounts/answer/185833?hl=pt-BR
3. Configure um token aleatório de pelo menos 32 caracteres em `WEBHOOK_TOKEN`,
   igual no `.env` da API e no arquivo privado do notificador.
4. Inicie o notificador, acrescentando o complemento aos arquivos Compose usados:

```powershell
docker compose -f docker-compose.yml -f docker-compose.email.yml up -d notificador
```

Se a API usa um complemento OCI local, mantenha também esse `-f` no comando,
com o mesmo projeto Docker da API. O notificador não recebe credenciais OCI.

5. Depois de configurar o SMTP, preencha no `.env` da API:

```dotenv
WEBHOOK_URL="http://notificador:8080/alertas"
```

6. Recrie a API e o notificador com os mesmos arquivos Compose para carregar
as alterações dos arquivos de ambiente. Não basta usar `restart`.

## Comportamento e validação

Os canais aceitos são `Alerta_Plantao_Medico` e `Email_Auditoria`. O destinatário
é fixo na configuração e não pode ser escolhido por quem chama o endpoint.
O assunto distingue urgência de revisão humana. A mensagem pode conter dados
clínicos; use documentos sintéticos nos testes.

`GET /health` verifica somente se a configuração está preenchida; não testa a
conexão SMTP. Sem configuração completa, retorna 503. O POST retorna 401 sem
token válido, 422 para payload inválido e 502 quando o SMTP falha. Erros não
expõem a senha ou o conteúdo da mensagem. Só responde 200 quando o servidor
SMTP aceita o e-mail; isso não comprova chegada à caixa de entrada.

O envio é síncrono, sem fila, retentativas ou garantia de entrega. O timeout
SMTP padrão é de três segundos por operação. A triagem continua mesmo quando
o envio falha. Em apresentação, os webhooks continuam desabilitados. Para URLs
existentes sem autenticação, deixe `WEBHOOK_TOKEN` vazio.

Se o antivírus inspecionar SMTP e apresentar um certificado próprio, exporte
somente sua CA pública já confiável no Windows, monte-a como somente leitura
no notificador e indique o caminho em `SMTP_CA_FILE`. As raízes padrão e a
validação do nome do servidor permanecem ativas. Não desative a validação TLS.

```powershell
python -m pytest tests/unit/test_email_webhook.py -q
```
