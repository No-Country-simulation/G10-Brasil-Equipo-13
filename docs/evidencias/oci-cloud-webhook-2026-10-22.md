# Teste de ponta a ponta — OCI real e webhook

Data: 22/10/2026, horário de São Paulo.

Resultado: três cenários concluídos com Gemini real, originais e relatórios
persistidos em Object Storage, dois alertas recebidos por e-mail e leitura
dos documentos confirmada após recriar a API.

## Ambiente

- `APP_MODE=operational`, `STORAGE_MODE=oci` e modelo `gemini-3.5-flash`.
- Arquivos Compose: `docker-compose.yml`, `docker-compose.oci-cloud.yml`,
  `docker-compose.email.yml` e um complemento privado com portas, montagens
  locais de código e CA pública do antivírus.
- O complemento privado não define o armazenamento nem monta a chave OCI:
  essas responsabilidades passaram ao novo `docker-compose.oci-cloud.yml`.
- API local na porta 8002 e interface na 8502; notificador somente na rede Docker.
- Credenciais OCI e SMTP mantidas fora dos arquivos versionados.

A instância validada também continha a correção de canal de origem da issue #27
(PR #30). Essa correção tem revisão própria e não é reapresentada nesta branch.

## Casos concluídos

| Cenário | ID | Origem | Destino | Acompanhamento | E-mail |
| --- | --- | --- | --- | --- | --- |
| Rotina | `E2E-CLOUD-DC4DC3B8E2-ROTINA` | Ambulatorio | Farmacia_Hospitalar | encaminhados | Não esperado |
| Urgência | `E2E-CLOUD-DC4DC3B8E2-URGENCIA` | Pronto_Socorro | Fila_Emergencia_Medica | encaminhados | Recebido |
| Revisão | `E2E-CLOUD-EF8C69CF28-REVISAO` | Recepcao | Fila_Revisao_Humana | revisao_humana | Recebido |

Foram usados os três TXT sintéticos de `presentation_examples/`, enviados por
HTTP multipart a `/triagem/upload`, com IDs novos. Não foi usado o adaptador
simulado de apresentação.

Para cada caso, foram verificadas as seguintes condições:

1. Resposta processada, sem `erro_extracao`, com origem e destino esperados.
2. `status_backup="sucesso"`.
3. Leitura direta do relatório pelo adaptador OCI real, conferindo ID, execução e origem.
4. Comparação byte a byte do original no bucket com o arquivo enviado, tanto
   pelo SDK quanto por `GET /triagem/original`.
5. Um único resultado no histórico para cada ID do teste.
6. Etapa esperada em `GET /triagem/filas/processamento` e acompanhamento gravado em `fluxo/`.

Os relatórios estão em:

```text
processados/rotina/E2E-CLOUD-DC4DC3B8E2-ROTINA.json
processados/urgentes/E2E-CLOUD-DC4DC3B8E2-URGENCIA.json
auditoria_humana/E2E-CLOUD-EF8C69CF28-REVISAO.json
```

Os originais correspondentes estão em `recebidos/<ID>.txt`.

## Alertas e persistência após recriação

O notificador registrou dois POSTs a `/alertas` com HTTP 200 e nenhuma falha
de entrega SMTP durante esta execução. O destinatário confirmou o recebimento
dos assuntos “MediFlow — Urgência” e “MediFlow — Revisão humana”.

A API foi recriada com os mesmos quatro arquivos Compose. Sem enviar novas
triagens ou alertas, os três relatórios e originais foram recuperados novamente,
preservando os mesmos identificadores de execução. Isso confirma a persistência
fora da memória do container.

## Intercorrência preservada

A primeira tentativa de revisão, `E2E-CLOUD-DC4DC3B8E2-REVISAO`, retornou
`erro_extracao.codigo="servico_indisponivel"` do Gemini. Ela não foi contabilizada
como sucesso. Somente esse cenário foi repetido, usando outro ID, e então passou.
A tentativa com erro foi preservada para inspeção; por isso existem quatro IDs
novos associados ao teste, dos quais três tiveram o resultado esperado.

Os objetos sintéticos foram mantidos no bucket para conferência. Nenhum documento
anterior do usuário foi removido ou substituído. A homologação humana da revisão
não foi executada: a etapa final esperada desse cenário é `revisao_humana`.

Esta execução valida a integração nesse ambiente; não constitui avaliação geral
da precisão clínica do modelo ou garantia de disponibilidade futura dos provedores.
