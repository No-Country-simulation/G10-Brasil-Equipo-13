# v1.1

- Atestado e Autorização: o texto agora traz idade, CID-10 e diagnóstico (antes só o gabarito tinha).
- Gabaritos e manifest.csv sem alteração.
- Textos alterados: 20
- PDFs/imagens a gerar de novo: DOC-ATES-2026-0001, DOC-ATES-2026-0009, DOC-AUT-2026-0001, DOC-AUT-2026-0006, DOC-AUT-2026-0008

## Casos de teste (pasta casos_teste, sem alterar os 115 documentos)
- urgencia_crm_ausente: 8 documentos novos (urgência com CRM ausente), com gabarito.
- txt: 22 arquivos .txt em UTF-8, reaproveitando os gabaritos existentes.
- txt_codificacao: 5 variantes do documento DOC-LAB-2026-0001 (utf8, utf8_bom, latin1, crlf, base64). Texto esperado após decodificar: DOC-LAB-2026-0001_utf8.txt.
- manifest_casos_teste.csv indexa tudo.

# v2 (proposta)

- Decisões provisórias da MED-03 aplicadas (ver DECISOES.md).
- Relatórios de alta reclassificados (7): DOC-ALTA-2026-0006 (urgencia -> rotina), DOC-ALTA-2026-0007 (urgencia -> rotina), DOC-ALTA-2026-0008 (urgencia -> rotina), DOC-ALTA-2026-0010 (urgencia -> rotina), DOC-ALTA-2026-0016 (urgencia_ambigua -> ambiguo), DOC-ALTA-2026-0018 (urgencia_ambigua -> ambiguo), DOC-ALTA-2026-0020 (urgencia_ambigua -> ambiguo)
- manifest.csv e README.md refeitos.
- PDFs/imagens a gerar de novo (v1.1 + v2): DOC-ALTA-2026-0006, DOC-ALTA-2026-0018, DOC-ATES-2026-0001, DOC-ATES-2026-0009, DOC-AUT-2026-0001, DOC-AUT-2026-0006, DOC-AUT-2026-0008

# v2 (aprovada) - 22/10/2026 15:48

- Revisão do dataset concluída e aprovada pelo time como base dos testes.
- Pasta renomeada de mediflow_v2_proposta para mediflow_v2. Nenhum dado foi alterado.
- Documentação atualizada: status, proposta de bloqueio para alto risco e referências consultadas.
- Pendente: PDFs/imagens dos IDs reclassificados ou corrigidos, e validação clínica.

# v2 congelada - 23/10/2026 09:08

- PDFs e imagens conferidos com os textos dos documentos. Versão de referência para os testes.

# Imagens em png, jpg e jpeg - 23/10/2026 09:22

- casos_teste/imagens_formatos: 120 arquivos (20 documentos x degradada/limpa x png/jpg/jpeg).
- DECISOES.md: sugestões da revisão registradas (comportamento do backend).

# v2 congelada - 23/10/2026 09:25

- PDFs e imagens conferidos com os textos dos documentos. Versão de referência para os testes.
