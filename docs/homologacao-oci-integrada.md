# Homologação integrada com OCI real — 19/11/2026

Branch: `codex/homologacao-oci-integrada`. Código da aplicação consolidado
em `8e66cae`. Não houve merge em `develop` nem em `main`.

## Composição

| Origem | Commit | Escopo |
|---|---|---|
| develop | 0a7aa9d | OCI/webhook e hotfix de canal de origem (#43) |
| PR #37 | 279960f | Integridade, HTTP 409, reserva e fallback |
| PR #39 | 16543b0 | Validações e classificação da triagem |
| Nova triagem | 081fd0d | Interface, upload JSON e validação dos arquivos |

O PR #35 não foi integrado e não há `dataset/v2` neste checkout. Os exemplos
usados são os documentos fictícios de `presentation_examples/`.

Foram conciliados o schema das sete categorias, o seletor de execução no
teste de fluxo e o endpoint de upload, preservando HTTP 409, JSON, validação
de arquivos e `conteudo_para_extracao()`.

## Ambiente e resultados

A API e a interface executam em Docker **local**, conectadas ao Object
Storage **real** em São Paulo. Não é implantação em VM/Compute OCI.
Projeto Compose `mediflow-oci-e2e`, API em `127.0.0.1:8004` e interface em
`127.0.0.1:8504`. As instâncias anteriores foram preservadas.

O bucket exclusivo `mediflow-testes` teve seu versionamento habilitado pelo
responsável no Console e confirmado pelo SDK antes das gravações.
Não houve alteração do bucket `mediflow-documentos-clinicos`.

| Verificação | Resultado |
|---|---|
| Suíte unitária combinada | 192 aprovados; 15 cenários de emulador omitidos nessa rodada |
| Integridade + integração no emulador, rodada separada | 34 aprovados |
| Ruff crítico e git diff --check | Aprovados |
| Cadastro TXT, resposta, original, relatório e acompanhamento na OCI | Aprovado |
| Upload JSON com BOM | Aprovado |
| JSON inválido | HTTP 422 |
| Cadastro duplicado com conteúdo igual/diferente | HTTP 409; original preservado |
| Urgência e revisão humana | Encaminhamentos esperados |
| Concorrência HTTP | Uma criação + um HTTP 409 |
| Concorrência SDK real com If-None-Match | Uma criação + um HTTP 412 |
| Reprocessamento explícito | Nova execução; execução anterior preservada |
| Reinício real da API isolada | Histórico, hashes e HTTP 409 preservados |
| Objetos preexistentes | Os 17 objetos do snapshot mantiveram seus ETags |
| Nova triagem via AppTest e HTTP real | JSON, quatro seções, resultado e erro de duplicidade aprovados |

A primeira tentativa usou `gemini-3.5-flash` e recebeu 503 por alta demanda,
confirmado em chamada mínima. O original foi preservado e o documento
encaminhado para revisão humana. A evidência foi mantida. A rodada concluída
usou **gemini-3.5-flash-lite**, disponível na mesma credencial, sem alterar
as instâncias anteriores. Isso não comprova disponibilidade do Flash nem
equivalência de qualidade entre os modelos.

Run concluído: `E2E-OCI-20261119T142542Z-c977fcfc`.
Evidências em `docs/evidencias/oci-e2e-integrada/`:

- `preflight.json`: bucket, versionamento e modelo.
- `estado.json`: cenários, execuções, hashes e verificações após reinício.
- `concorrencia-sdk.json`: prova de 200/412 na OCI real.
- `liberacao-reserva-sdk.json`: propriedade da reserva e exclusão com ETag.
- `interface-apptest.json`: resultado real e verificações da Nova triagem.
- `falha-gemini-inicial.json`: contingência observada com Gemini Flash.

## Limites

- A automação do navegador ficou indisponível. O AppTest injetou somente o
  arquivo sintético no seletor; cliente HTTP, API, Gemini e OCI foram reais.
  QA visual no navegador permanece pendente, assim como câmera, PDF e imagens.
- Webhook não configurado: entrega externa de email/alertas não foi validada.
- Encaminhar para revisão foi validado; a decisão manual de homologação
  funcional pela QA não está substituída por estes testes.
- Os testes não investigam nem resolvem possíveis perdas históricas.
- Artefatos sintéticos foram preservados; não há limpeza global do bucket.
- Esta execução não equivale à aprovação formal dos PRs ou à liberação de produção.

## Reproduzir

1. Copiar `.env.oci-e2e.example` para `.env.oci-e2e.local`, preencher em privado
   e manter `key_file=/run/oci/api_key.pem` no config Docker. Não versionar
   a configuração preenchida nem as chaves. O Compose usa `env_file` raw.
2. Confirmar o versionamento do bucket e executar:

```powershell
docker compose --env-file .env.oci-e2e.local -f docker-compose.oci-e2e.yml up --build -d
docker compose --env-file .env.oci-e2e.local -f docker-compose.oci-e2e.yml exec -T api python scripts/validar_oci_integrada.py preflight
docker compose --env-file .env.oci-e2e.local -f docker-compose.oci-e2e.yml exec -T api python scripts/validar_oci_integrada.py executar
docker compose --env-file .env.oci-e2e.local -f docker-compose.oci-e2e.yml exec -T ui python scripts/validar_nova_triagem_real.py
docker compose --env-file .env.oci-e2e.local -f docker-compose.oci-e2e.yml restart api
docker compose --env-file .env.oci-e2e.local -f docker-compose.oci-e2e.yml exec -T api python scripts/validar_oci_integrada.py conferir
```

Cada execução cria IDs exclusivos e conserva os dados anteriores. Arquivar
a pasta de evidências antes de repetir, pois os arquivos de relatório usam
nomes fixos. Os testes usam chamadas reais ao Gemini e gravações reais na OCI.

Para encerrar somente esta instância, usar o mesmo Compose com `down`.
Isso não apaga os objetos na OCI nem altera as outras instâncias locais.
