# MediFlow: dataset clínico sintético (v2)

Documentos clínicos **fictícios** para desenvolver e testar o agente de triagem. Nenhum dado real de paciente foi usado.

## Avisos
- Nomes, CPFs e CRMs são aleatórios (Faker pt_BR). Os CPFs têm formato válido e podem coincidir por acaso com CPFs reais. Usar somente para teste.
- Condições, medicamentos e achados são sintéticos e **não passaram por revisão clínica**.
- As regras de roteamento foram aprovadas pelo time como premissas do MVP e ainda não passaram por validação clínica (ver DECISOES.md).

## Estrutura
- `data/<tipo>/<cenário>/`: cada documento tem 2 arquivos
  - `DOC-XXX-2026-NNNN.json`: entrada (o que o agente recebe)
  - `DOC-XXX-2026-NNNN.gabarito.json`: resposta correta esperada
- `schemas/`: JSON Schema de entrada, saída e gabarito
- `manifest.csv`: índice dos 115 documentos de `data/`
- `documentos_gerados/`: amostra em PDF digital, PDF digitalizado e imagem degradada, com `manifest_formatos.csv`
- `casos_teste/`: urgência com CRM ausente, arquivos .txt e variantes de codificação, com `manifest_casos_teste.csv`; `casos_teste/imagens_formatos/` traz as imagens dos documentos em png, jpg e jpeg, degradadas e limpas, com `manifest_imagens_formatos.csv`
- `DECISOES.md`, `CHANGELOG.md`

## Documentos por tipo e cenário
| Tipo | rotina | urgencia | ambiguo | urgencia_ambigua |
|---|---|---|---|---|
| Atestado Médico | 5 | 0 | 5 | 0 |
| Autorização Administrativa | 5 | 0 | 5 | 0 |
| Guia de Solicitação de Procedimento | 5 | 5 | 5 | 5 |
| Laudo de Exame de Imagem | 5 | 5 | 5 | 5 |
| Laudo de Exame Laboratorial | 5 | 5 | 5 | 5 |
| Receituário Médico | 5 | 5 | 5 | 0 |
| Relatório de Alta/Internação | 9 | 1 | 8 | 2 |

## Cenários e destino esperado
- **rotina**: documento completo; destino conforme o tipo (farmácia, prontuário ou auditoria de autorizações)
- **urgencia**: achado ou condição crítica ativa; destino `Fila_Emergencia_Medica`
- **ambiguo**: defeito de propósito (CRM inválido, nome ilegível, dosagem ou campo ausente, CID incompatível); destino `Fila_Revisao_Humana`, com `motivo_ambiguidade`
- **urgencia_ambigua**: urgente e com defeito; destino `Fila_Emergencia_Medica` com `requer_auditoria_humana = true`

## Como este dataset é mantido
Esta pasta é a fonte. Mudanças são feitas por scripts de ajuste e registradas no CHANGELOG, sem gerar tudo de novo, para os IDs continuarem batendo com os PDFs.
