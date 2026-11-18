# Issue #27 — canal de origem

Referência: https://github.com/No-Country-simulation/G10-Brasil-Equipo-13/issues/27

## Instruções conferidas

Foram consultados o README, `docs/fluxo-de-trabalho-git.md`, o contrato
em `sdd-medflow.md` e a CI. Não foi encontrado `AGENTS.md` no checkout
nem nos diretórios ancestrais. A validação usa dados sintéticos, sem Gemini,
webhooks ou OCI real, conforme a suíte unitária do projeto.

## Reprodução antes da correção

Base: `9591ed4`. Em 22/10/2026, os testes de
`tests/unit/test_canal_origem.py` foram executados antes da alteração no backend.
As 12 combinações de Pronto_Socorro, Ambulatorio e Recepcao, pelas entradas
JSON e multipart e com os dois adaptadores de IA, retornaram HTTP 200,
mas falharam em `doc.get("canal_origem") == canal`: o valor retornado era `None`.
Os quatro testes de compatibilidade também falharam porque o DTO ainda não
possuía o atributo. Resultado anterior: **16 failed**.

O formulário `nova_triagem.py` já inclui o canal selecionado no payload JSON.
O upload multipart também o recebe e repassa ao DTO de entrada. O caso de uso
conserva o valor no estado do grafo e no acompanhamento, mas não o incluía na
montagem de `TriagemResponseDTO`. O contrato de saída também não declarava o
campo. O relatório persistido é serializado desse DTO e perdia a mesma informação.
O resumo usa `Não registrada` quando a origem não existe.

O defeito está no caso de uso compartilhado pelos modos operacional e
apresentação. Os testes exercitam o adaptador real de apresentação e uma LLM
simulada para o caminho operacional; não fazem inferência externa.

## Correção e cobertura

O DTO declara `canal_origem: Optional[str]` com padrão `None`, e o caso de uso
o preenche diretamente da entrada. Não há nova restrição aos valores de canal
aceitos pela API. O relatório persistido e a resposta passam a conter o valor.
Registros antigos, com campo ausente ou nulo, continuam válidos e não recebem
origem inventada; a interface conserva seu fallback existente.

Os testes verificam os três canais na resposta HTTP, relatório armazenado,
histórico e acompanhamento, além da leitura de registros antigos.

Após a correção: **118 testes unitários aprovados**, incluindo os 16 novos,
em container Python 3.11 com o checkout montado somente para leitura.
Compilação Python, leitura do `pyproject.toml` e `git diff --check` aprovados.
Ruff 0.15.8 com os erros críticos da CI (`E9,F63,F7,F82`) também aprovado.

Para executar em um ambiente com as dependências do projeto:

```powershell
python -m pytest tests/unit/test_canal_origem.py -q
python -m pytest tests/unit -q
git diff --check
```

A validação visual pela frente de QA (Maria Flavia), indicada na issue,
permanece pendente.
