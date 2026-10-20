# Fluxo de trabalho Git, Pull Requests e CI

Este documento descreve como a equipe integra mudanças no MediFlow. Ele é uma
proposta viva: para sugerir alterações, abra um PR para `develop` editando este
arquivo e explique o motivo na descrição.

## 1. Branches (Git Flow)

| Branch | Origem | Destino do PR | Uso |
|---|---|---|---|
| `main` | — | — | Código entregue. Recebe apenas `release/*` e `hotfix/*`. |
| `develop` | `main` | — | Integração contínua do trabalho em andamento. |
| `feature/<descricao>` | `develop` | `develop` | Nova funcionalidade. |
| `bugfix/<descricao>` | `develop` | `develop` | Correção de algo ainda não entregue em `main`. |
| `release/<versao>` | `develop` | `main` e sincronização com `develop` | Preparação de entrega. |
| `hotfix/<descricao>` | `main` | `main` e `develop` | Correção urgente do que já está em `main`. |

Destinos habituais: `feature/*` e `bugfix/*` → `develop` ; `release/*` → `main` e
sincronização com `develop` ; `hotfix/*` → `main` e `develop` .

Use nomes curtos, em minúsculas e com hífens, por exemplo
`feature/painel-auditoria` ou `hotfix/alerta-urgencia-sem-crm`.

### Exemplo: hotfix

O hotfix nasce de `main`, não de `develop`, porque corrige o que já foi entregue.

```bash
git switch main
git pull
git switch -c hotfix/alerta-urgencia-sem-crm
# ... correção + testes ...
git push -u origin hotfix/alerta-urgencia-sem-crm
```

1. Abra o PR `hotfix/...` → `main`.
2. Depois do merge em `main`, abra outro PR `hotfix/...` → `develop` (ou
   `main` → `develop`) para que a correção não se perca na próxima release.

### Mensagens de commit

Use Conventional Commits: `feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `ci:`,
`chore:`. Exemplo: `fix: preservar alerta de urgência com CRM ausente`.

## 2. Pull Requests

Todo PR usa o modelo `.github/pull_request_template.md`, preenchido
automaticamente pelo GitHub. Ele pede:

- **O que foi alterado** e **por que** (com a issue relacionada);
- **Como testar**, com passos e resultado esperado;
- **Evidências** sem dados sensíveis: nunca inclua documentos clínicos reais,
  nomes de pacientes, CRMs reais, chaves de API ou credenciais OCI;
- **Checklist** de revisão, testes, segurança e branch de destino.

Prefira PRs pequenos e focados. Um PR com mais de ~400 linhas alteradas deve ser
dividido quando possível.

## 3. Verificações automáticas (CI)

O workflow `.github/workflows/ci.yml` roda em todo PR e push para `main` e
`develop`, com Python 3.11 (a mesma versão do `Dockerfile`).

| Job | O que verifica | Bloqueia? |
|---|---|---|
| **Integridade** | Marcadores de conflito de merge; espaços em branco e finais de linha apenas nas linhas alteradas (`git diff --check`); sintaxe do `pyproject.toml`. | Sim |
| **Qualidade (Python)** | Compilação de todos os módulos; Ruff com erros críticos (`E9,F63,F7,F82`: sintaxe e nomes indefinidos). | Sim |
| | Ruff completo e `ruff format --check`. | Não (informativo) |
| **Segurança** | Arquivos de credenciais versionados (`.env`, `*.pem`, `*.key`, `.oci/`, `secrets.toml`; arquivos `*.example` são permitidos); segredos nos commits novos com gitleaks. | Sim |
| **Testes unitários** | `pytest tests/unit`, sem Gemini, webhooks nem OCI real. | Sim |
| **Integração** | Sobe o emulador OCI e a API de testes do Compose, com LLM simulado, e executa os cenários rotina, urgência e revisão por HTTP. | Sim, após estabilizar (ver fases) |

Uma falha de CI deve ser corrigida antes de integrar o PR. Nenhum job usa
segredos do repositório; os testes com Gemini real continuam manuais
(`scripts/validar_gemini.py`, `tests/demonstracao_cenarios.py`).

### Reproduzir localmente

```powershell
# Qualidade
python -m pip install ruff==0.15.8
ruff check --select E9,F63,F7,F82 .
ruff check .            # informativo
ruff format --check .   # informativo

# Testes unitários
python -m pytest tests/unit -q

# Integração (Docker)
docker compose -p mediflow-ci -f docker-compose.yml -f docker-compose.oci-local.yml -f docker-compose.test.yml up --build -d oci-emulator mediflow-test-api
$env:RUN_COMPOSE_TESTS="1"; $env:OCI_SERVICE_ENDPOINT="http://localhost:4599"
python -m pytest tests/integration/test_compose_cenarios.py -q
docker compose -p mediflow-ci -f docker-compose.yml -f docker-compose.oci-local.yml -f docker-compose.test.yml down -v
```

O projeto `-p mediflow-ci` isola containers e volume; `down -v` não apaga os
dados do emulador usado no desenvolvimento.

### Fases de adoção

A CI foi adotada gradualmente para não bloquear a equipe por débito existente:

1. **Fase 1 (atual):** integridade, erros críticos de Python, segurança e testes
   unitários são obrigatórios. Estilo completo é informativo. Na data de criação,
   o Ruff completo apontava 142 ocorrências (a maioria corrigível com
   `ruff check --fix`) e 75 arquivos fora do formato.
2. **Fase 2:** um PR dedicado aplica `ruff check --fix` e `ruff format`; então o
   passo de estilo deixa de ser informativo (remover `continue-on-error`).
3. **Fase 3:** o job de integração passa a ser check obrigatório depois de
   algumas execuções estáveis no GitHub.

## 4. Proteção de branches

Estas regras são configuradas por quem administra o repositório em
**Settings → Branches** (ou **Rules → Rulesets**); o workflow não as aplica sozinho.

| Regra | `develop` | `main` |
|---|---|---|
| Aprovações exigidas | 1 | 2 |
| Pushes diretos | Bloqueados | Bloqueados |
| Branch atualizada antes do merge | Sim | Sim |
| Checks obrigatórios | `Integridade`, `Qualidade (Python)`, `Segurança`, `Testes unitários` | Os mesmos |

`Integração (Compose + emulador OCI)` entra na lista na fase 3.

## 5. Como propor mudanças neste fluxo

1. Crie uma branch a partir de `develop` (por exemplo
   `feature/ajuste-fluxo-git`).
2. Altere este documento e, se for o caso, `.github/workflows/ci.yml` ou
   `.github/pull_request_template.md` no mesmo PR.
3. Explique no PR o problema que a mudança resolve; a equipe discute na revisão.
