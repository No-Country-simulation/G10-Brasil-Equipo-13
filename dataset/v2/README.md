# MediFlow: dataset clínico sintético (v2)

Documentos clínicos **fictícios** para desenvolver e testar o agente de triagem. Nenhum dado real de paciente foi utilizado.

## Avisos

- Nomes, CPFs e CRMs são aleatórios (Faker pt_BR). Os CPFs têm formato válido e podem coincidir por acaso com CPFs reais. Utilizar somente para testes.
- Condições, medicamentos e achados são sintéticos e **não passaram por revisão clínica**.
- As regras de roteamento são premissas do MVP e ainda não passaram por validação clínica. Consultar `DECISOES.md`.

## Estrutura versionada no Git

- `data/<tipo>/<cenário>/`: documentos de entrada e seus respectivos gabaritos.
  - `DOC-XXX-2026-NNNN.json`: entrada recebida pelo agente.
  - `DOC-XXX-2026-NNNN.gabarito.json`: resposta correta esperada.
- `schemas/`: schemas JSON de entrada, saída e gabarito.
- `manifest.csv`: índice dos 115 documentos de entrada.
- `DECISOES.md`: registro das decisões e premissas do dataset.
- `CHANGELOG.md`: histórico das alterações.
- `VERSAO.txt`: identificação da versão do dataset.

Os arquivos de entrada e os gabaritos são mantidos no Git para permitir o versionamento e a revisão das alterações.

## Arquivos mantidos no Drive

As pastas `documentos_gerados/` e `casos_teste/` não estão versionadas neste PR e permanecem no Drive do projeto por enquanto.

Entre os materiais previstos estão:

- PDFs digitais e digitalizados.
- Imagens de documentos, incluindo variantes limpas e degradadas.
- Arquivos de casos de teste que ainda precisam ser incorporados ou organizados no repositório.
- Manifestos e checksums associados aos materiais armazenados no Drive.

A organização definitiva desses arquivos e seus caminhos será atualizada após a confirmação da estrutura final com a equipe.

## Documentos por tipo e cenário

| Tipo | rotina | urgencia | ambiguo | urgencia_ambigua |
|---|---:|---:|---:|---:|
| Atestado Médico | 5 | 0 | 5 | 0 |
| Autorização Administrativa | 5 | 0 | 5 | 0 |
| Guia de Solicitação de Procedimento | 5 | 5 | 5 | 5 |
| Laudo de Exame de Imagem | 5 | 5 | 5 | 5 |
| Laudo de Exame Laboratorial | 5 | 5 | 5 | 5 |
| Receituário Médico | 5 | 5 | 5 | 0 |
| Relatório de Alta/Internação | 9 | 1 | 8 | 2 |

## Cenários e destino esperado

- **rotina**: documento completo; destino conforme o tipo, como farmácia, prontuário ou auditoria de autorizações.
- **urgencia**: achado ou condição crítica ativa; destino `Fila_Emergencia_Medica`.
- **ambiguo**: defeito intencional, como CRM inválido, nome ilegível, dosagem ou campo ausente ou CID incompatível; destino `Fila_Revisao_Humana`, com `motivo_ambiguidade`.
- **urgencia_ambigua**: documento urgente com defeito; destino `Fila_Emergencia_Medica`, com `requer_auditoria_humana = true`.

## Como este dataset é mantido

As entradas e os gabaritos versionados no Git são mantidos como referência para o desenvolvimento e os testes. As alterações devem ser registradas no `CHANGELOG.md`.

Os arquivos e materiais gerados associados devem manter correspondência com os IDs dos documentos. A geração, a distribuição e a verificação desses materiais serão documentadas conforme a estrutura definitiva acordada pela equipe.
