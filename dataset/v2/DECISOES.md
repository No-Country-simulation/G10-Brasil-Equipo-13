# Decisões (MED-03) aplicadas na v2

Versão aprovada pelo time como base dos testes (revisão do dataset concluída). Nenhuma regra clínica foi validada por profissional de saúde.
A v1.1 continua disponível: para desfazer qualquer item, basta usar a v1.1.

| # | Tema | Decisão provisória | Efeito no dataset |
|---|---|---|---|
| D1 | Urgência + ambiguidade | A urgência define o destino (Fila_Emergencia_Medica) e a auditoria humana fica marcada em paralelo (requer_auditoria_humana = true; sinalização revisao_humana_paralela). | Sem mudança (cenário urgencia_ambigua). |
| D2 | Relatório de alta com evento grave já tratado | Relatório do subtipo "alta" é evento crítico histórico, não emergência ativa. Vai para Prontuario_Eletronico (rotina) ou Fila_Revisao_Humana (se houver defeito). Sinalização evento_critico_historico. O subtipo "evolucao" é quadro em acompanhamento e mantém a urgência. | Relatórios de alta reclassificados (ver CHANGELOG): texto sem "URGENTE", gabarito e pasta atualizados. |
| D3 | Medicamento de alto risco | O agente reconhece uma lista fechada (Varfarina, Enoxaparina, Insulina NPH, Tramadol), sinaliza (medicamento_alto_risco) e encaminha para revisão humana, mantendo o destino. Contraindicação por idade ou dose fica fora do escopo do MVP. | Sem mudança. DOC-CLIN-2026-0004 (tramadol em criança) permanece como caso conhecido de contraindicação. |
| D4 | "Relatório Clínico" | Mantém o nome "Relatório de Alta/Internação" com subtipo opcional (alta ou evolucao). Renomear exigiria mudar schema e todos os documentos. | Sem mudança. |

## Vocabulário de sinalizacoes
- urgencia_medica: achado ou condição crítica ativa.
- revisao_humana_paralela: urgente que também exige revisão humana.
- medicamento_alto_risco: medicamento da lista fechada de alto risco.
- evento_critico_historico: relatório de alta que descreve evento grave já tratado.

## Pontos que ainda dependem de validação clínica
- Se todo relatório de alta com evento grave tratado deve mesmo seguir como rotina.
- Se alto risco deve manter o destino na farmácia ou ir direto para a fila de revisão humana.
- Como o mesmo documento aparece nas filas de urgência e de auditoria.

## Proposta em discussão (não aplicada ao dataset)
- Medicamento de alto risco: avaliar uma etapa de autorização e eventual bloqueio de liberação antes de qualquer liberação do medicamento. O dataset atual só sinaliza e pede revisão humana. O comportamento final ainda será definido pelo time.

## Referências consultadas (apoio, não substituem validação clínica)
- ISMP, lista de medicamentos de alta vigilância: inclui anticoagulantes, insulina e opioides como classes de alto risco.
- Listas hospitalares brasileiras de alta vigilância: confirmam varfarina, enoxaparina e insulinas.
- FDA (2017): tramadol contraindicado para dor em menores de 12 anos.
- Resolução CFM 2381/2024: CRM é elemento obrigatório de documento médico; diagnóstico e CID em atestado dependem de pedido ou concordância do paciente.

## Sugestões da revisão (comportamento do backend, não aplicadas ao dataset)
- Medicamento de alto risco: manter a Farmácia como destino principal, com encaminhamento paralelo para auditoria humana; a liberação da medicação fica bloqueada até a aprovação da revisão.
- Urgência com auditoria humana: o agente define o destino e a necessidade de auditoria (campos destino_esperado e requer_auditoria_humana) e uma regra do backend cria o encaminhamento e a pendência de revisão. Na urgência a auditoria não bloqueia o encaminhamento; na farmácia a entrega é bloqueada até a liberação humana.
- Em aberto: se o agente deve identificar contraindicações e incompatibilidades clínicas (como no DOC-CLIN-2026-0004) ou apenas sinalizar medicamentos de alto risco; e a proposta de incluir a descrição "Medicamento aparentemente incompatível com o diagnóstico informado".
