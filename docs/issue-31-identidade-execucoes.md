# Issue #31 — identidade documental e reprocessamento

Novo cadastro (`POST /triagem` ou `/triagem/upload`) reserva o ID com uma
criação atômica em `cadastros/<sha256(documento_id)>.json`. Em memória há lock;
na OCI usa-se `put_object(if_none_match="*")`, convertendo somente HTTP 412
em conflito de cadastro (HTTP 409). Falhas técnicas não ativam escrita
incondicional. O SDK OCI 2.189.0 instalado documenta explicitamente essa
condição no método `ObjectStorageClient.put_object`.

O Floci 0.5.0 falhou em uma repetição da corrida (dois HTTP 200). Por isso,
o ambiente emulado usa também SQLite com chave primária composta, antes do
PUT condicional. Todos os trabalhadores do emulador devem compartilhar
`MEDIFLOW_RESERVAS_DB` em volume persistente. Os arquivos Compose configuram
esse volume. Não colocar o SQLite em NFS ou em volumes separados por réplica.
O uso direto do adaptador com endpoint emulado permite informar `reservas_db`;
sem configuração, usa um arquivo no diretório temporário local, adequado
somente a testes. Na OCI real o índice SQLite não é usado.

Se a tentativa falhar antes de guardar o original, a API libera sua reserva
depois de confirmar que o original está ausente. A liberação confere
`primeira_execucao_id`: uma execução nunca libera a reserva de outra. Na OCI,
a exclusão exige `if_match` do ETag lido; alterações concorrentes (412), falta
de ETag ou falhas de consulta conservam a reserva. No emulador, uma transação
SQLite serializa a liberação com novas reservas entre processos.
A tentativa interrompida é arquivada em `tentativas_interrompidas/` antes da
liberação; falha ao arquivar mantém a reserva. O reenvio disputa novamente
a criação atômica. Se o original existir ou a verificação falhar, a reserva
permanece para proteger os dados e a API tenta registrar a interrupção para
reprocessamento. Não remover marcadores manualmente para repetir um cadastro.
O modo memória é efêmero. Somente OCI preserva dados após reinício do processo
de armazenamento.
No emulador, preservar tanto o volume do Floci quanto o volume de reservas.

Cada execução tem UUID próprio, data UTC, origem e caminhos por documento
e execução em `recebidos/`, `processados/`, `auditoria_humana/` e `fluxo/`.
Um original não confirmado interrompe a análise antes de inferência ou alerta.

## Reprocessamento explícito

`POST /triagem/reprocessar` recebe `documento_id`, `origem_oci_path` e
`canal_origem`. A origem pode ser um relatório ou acompanhamento de execução
que falhou. A API valida a identidade, lê o original armazenado e cria uma
nova execução; `reprocessamento_de` mantém o vínculo com o caminho anterior.
`execucao_anterior_id` mantém a identidade desse vínculo mesmo se uma
homologação posterior mover o relatório anterior para outra fila.
Não aceita novo arquivo sob a identidade existente. Um arquivo diferente
precisa de novo cadastro. Sem original disponível, retorna 409.

Na página Documentos clínicos, selecionar a execução desejada e usar
Reprocessar documento. Novo cadastro com ID existente orienta a consulta
ou o uso de outro ID. Os seletores de documentos e auditoria, a navegação
das filas e a linha do tempo usam a identidade do registro selecionado.

## Legados e homologação

A leitura acrescenta `registro_id` (caminho real) e marca registros sem a
nova data como legados. Origem e data ausentes são apresentadas como não
registradas. Não há migração, exclusão, renomeação ou deduplicação automática.
Cadastro novo verifica também os arquivos anteriores à reserva de IDs.
Cada legado continua acessível pelo caminho, mesmo compartilhando ID.
A homologação mantém seu fluxo de movimentação, com destino exclusivo por
execução. Os legados recebem uma identidade derivada da chave de origem
para distinguir registros que já compartilhavam o mesmo ID de execução.

## Antes de usar na OCI real

Executar primeiro `python scripts/auditar_issue31_oci.py` no ambiente OCI.
A inspeção é somente leitura: consulta versionamento do bucket, identifica
IDs com múltiplos relatórios, originais ausentes e versões disponíveis.
Não mostra campos clínicos nem baixa originais.

Confirmar versionamento **Enabled** no bucket configurado (originais e
relatórios compartilham esse bucket). Se houver buckets adicionais, verificar
cada um. Resolver/documentar os casos apontados com apoio dos responsáveis;
consultar backups externos antes de declarar qualquer original perdido.
Não ativar a nova escrita em uma implantação com trabalhadores antigos ainda
recebendo cadastros: interromper ingestão, verificar inventário e trocar todas
as instâncias juntas. Escritores antigos não respeitam a reserva atômica.

O emulador não comprova configuração, IAM ou persistência da OCI real.
Validar a concorrência também na nuvem em bucket controlado, após satisfazer
os pré-requisitos de versionamento e impacto. A QA deve repetir o cenário 001
na interface e anexar evidências antes de encerrar a issue.

## Regressão

`python -m pytest tests/unit -q` verifica API, aplicação e Streamlit AppTest.
`RUN_OCI_EMULATOR_TESTS=1` e `OCI_SERVICE_ENDPOINT` local habilitam os mesmos
cenários de integridade de `tests/unit/test_issue31.py` no SDK/emulador.
Esses testes usam buckets com nome aleatório, dados sintéticos e limpeza final.

## Evidências locais — 29/10/2026

- Suíte completa: 144 aprovados e 10 cenários de emulador pulados nessa rodada.
- Rodada com SDK/emulador: 24 aprovados, incluindo os cenários habilitados,
  a corrida forçada e a reserva entre quatro processos independentes.
- HTTP contra API temporária/emulador: quatro cenários aprovados.
- Reinício efetivo da API temporária: novo cadastro retornou 409, original e
  relatório permaneceram idênticos e o reprocessamento criou outra execução.
- Inspeção somente leitura da OCI configurada: bucket
  `mediflow-documentos-clinicos`, versionamento **Disabled**, sete IDs com
  relatórios no inventário atual. Nenhum caso de duplicidade ou original
  ausente foi apontado nesse inventário. Isso não comprova ausência de perdas
  anteriores: o levantamento de backups e de registros perdidos segue pendente.
- Não houve regressão com escrita na OCI real nem ativação de versionamento.
  A entrega à QA na nuvem depende dessas condições e das evidências funcionais.

Referência do SDK: https://docs.oracle.com/en-us/iaas/tools/python/latest/api/object_storage/client/oci.object_storage.ObjectStorageClient.html#oci.object_storage.ObjectStorageClient.put_object

## Decisão de contrato: categoria e falha de classificação

O schema de saída válida da IA aceita somente as sete categorias oficiais,
compatíveis com a correção #38. O DTO público mantém `tipo_documento: str`
para leitura dos registros legados. Não há oitava categoria clínica.
Falhas da OpenAI passam por `FalhaExtracaoIA`, assim como as falhas do Gemini,
e geram estado de erro e encaminhamento à revisão humana. A descrição
`Documento Clínico Não Identificado` permanece na resposta e na interface
por compatibilidade, como apresentação da ausência de classificação, nunca
como categoria válida da IA. Não se inventa uma categoria para completar o
contrato. A restrição futura do DTO público exige contrato explícito para
resultados não classificados e migração compatível dos registros antigos.

### Validação local das decisões — 19/11/2026

- Suíte unitária: 161 aprovados, 15 cenários de emulador omitidos nessa rodada.
- Rodada separada com `RUN_OCI_EMULATOR_TESTS=1`: 34 aprovados em
  `test_issue31.py` e `test_oci_emulator.py`, com buckets sintéticos locais.
- Onze regressões novas cobrem propriedade da reserva, concorrência, ETag,
  falha na consulta/arquivo de auditoria e classificação não identificada.
- Ruff 0.15.8 (E9,F63,F7,F82) e `git diff --check`: aprovados.
- Não houve validação com escrita na OCI real nem nova homologação visual.

### Recuperar uma reserva após interrupção abrupta

Pare todas as instâncias que escrevem no bucket e aguarde o término de
requisições de armazenamento em andamento. Com a configuração do mesmo
bucket e, no emulador, o mesmo volume SQLite, execute:

```powershell
python scripts/recuperar_reserva_interrompida.py DOC-ID EXECUCAO-ID --triagem-parada
```

A recuperação verifica o proprietário da reserva, os relatórios, a etapa
do fluxo e a ausência do original. O registro interrompido é arquivado
antes da liberação condicional. No emulador, também é possível limpar o
índice órfão se não houver cadastro remoto nem documento associado ao ID.
Depois da confirmação, reinicie a API e reenvie o documento.
