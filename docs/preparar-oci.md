# Preparar a OCI para o MediFlow

Guia para reproduzir a configuração de Object Storage usada pelo projeto.
A aplicação pode continuar no computador local, com os documentos persistidos
na OCI. Não é necessário criar uma máquina virtual para essa configuração.

Os exemplos usam Windows, PowerShell e Docker Compose. Substitua os valores
entre `<...>` e os caminhos com `SEU_USUARIO` pelos valores do novo ambiente.
Nunca copie os OCIDs, fingerprints ou chaves de outra conta.

## 1. Recursos e nomes de referência

| Recurso | Nome de referência | Finalidade |
| --- | --- | --- |
| Região | São Paulo (`sa-saopaulo-1`) | Região do bucket neste exemplo |
| Compartimento | `mediflow` | Organizar os recursos do projeto |
| Domínio de identidade | `Default`, já existente | Conter usuários e grupos |
| Bucket | `mediflow-documentos-clinicos` | Guardar originais, resultados e acompanhamento |
| Grupo | `mediflow-storage` | Receber as permissões do bucket |
| Usuário da aplicação | `mediflow-app` | Autenticar chamadas do SDK |
| Política IAM | `mediflow-storage-policy` | Limitar o acesso do grupo |

É necessário usar uma conta com permissão para criar esses recursos durante
a preparação. A aplicação usará o usuário restrito, sem adicioná-lo ao grupo
`Administrators`. Verifique limites e condições de uso da sua conta no console;
este guia não garante gratuidade de qualquer volume de armazenamento ou uso.

## 2. Criar o compartimento

1. No console OCI, abra **☰ → Identidade e Segurança → Compartimentos**.
2. Selecione o compartimento raiz da conta e clique em **Criar compartimento**.
3. Informe nome `mediflow` e descrição `Recursos do projeto MediFlow`.
4. Confirme que o compartimento ficou ativo.

Se o recurso já existe, confira seus dados e reutilize-o. Não crie uma segunda
estrutura apenas para repetir a instalação local.

## 3. Criar o bucket privado

1. Selecione a região de destino no topo do console; neste exemplo, São Paulo.
2. Abra **Armazenamento → Object Storage e Archive Storage → Buckets**.
3. No filtro de compartimento, selecione `mediflow`.
4. Clique em **Criar bucket** e use:

| Campo | Configuração inicial |
| --- | --- |
| Nome | `mediflow-documentos-clinicos` |
| Escopo | `Namespace` |
| Camada padrão | Padrão / Standard |
| Camadas automáticas | Desativadas |
| Versionamento | Desativado neste roteiro inicial |
| Eventos de objeto | Desativados |
| Criptografia | Chave gerenciada pela Oracle |

5. Depois da criação, confirme **Visibilidade: Privado** e o compartimento correto.
6. Anote o **Namespace** exibido nos detalhes. Ele não é o nome do compartimento,
   o OCID da conta ou o nome do bucket; será usado em `OCI_NAMESPACE`.

Os prefixos `recebidos/`, `processados/`, `auditoria_humana/` e `fluxo/` são
criados pelas chaves dos objetos quando o MediFlow grava dados. Não é necessário
criar pastas manualmente. Em OCI real, o MediFlow não cria o bucket automaticamente.

O versionamento fica fora desta configuração inicial; sem ele, uma escrita na
mesma chave substitui o objeto. Use IDs diferentes para documentos diferentes.
O versionamento não substitui a validação de identidade dos documentos na aplicação.

## 4. Localizar o domínio existente

1. Abra **Identidade e Segurança → Domínios**.
2. Troque o filtro de compartimento para a **raiz da conta**.
3. Abra o domínio `Default` e confirme que está ativo.

O domínio padrão pertence à raiz. Se o filtro continuar em `mediflow`, a lista
pode aparecer vazia. Não clique em **Criar domínio** para resolver esse filtro.
Domínio de identidade e compartimento são recursos diferentes.

## 5. Criar grupo e usuário da aplicação

Dentro de **Default → Gerenciamento de usuários**:

1. Na seção **Grupos**, clique em **Criar**.
2. Use nome `mediflow-storage` e descrição `Acesso do MediFlow ao bucket de documentos`.
3. Na seção **Usuários**, clique em **Criar**.
4. Use nome `MediFlow` e sobrenome `Aplicacao`.
5. Desative **Usar o endereço de e-mail como nome de usuário** e informe
   `mediflow-app` como nome de usuário.
6. Se solicitado, use um e-mail controlado pelo responsável pelo ambiente.
7. Associe o usuário ao grupo `mediflow-storage` e crie-o.
8. Abra os detalhes do usuário, confirme o estado ativo e confira a aba **Grupos**.

Não associe o usuário da aplicação ao grupo `Administrators`. Não é necessário
utilizar o login desse usuário no console para a aplicação funcionar via SDK.

## 6. Criar a política restrita ao bucket

1. Abra **Identidade e Segurança → Políticas**.
2. Selecione o compartimento `mediflow` e clique em **Criar política**.
3. Nome: `mediflow-storage-policy`.
4. Descrição: `Permite ao MediFlow acessar seu bucket`.
5. Ative o editor manual e informe:

```text
Allow group 'Default'/'mediflow-storage' to read buckets in compartment mediflow where target.bucket.name = 'mediflow-documentos-clinicos'
Allow group 'Default'/'mediflow-storage' to manage objects in compartment mediflow where target.bucket.name = 'mediflow-documentos-clinicos'
```

6. Crie a política e confira as duas linhas na aba **Instruções**.

O grupo poderá consultar os detalhes desse bucket e listar, ler, criar,
sobrescrever e excluir seus objetos. Isso permite a movimentação de resultados
na homologação. As regras não concedem administração da conta nem criação ou
exclusão de buckets. Ajuste o domínio, grupo, compartimento e bucket nas regras
caso os nomes adotados sejam diferentes.

## 7. Criar a chave de API do usuário restrito

1. Volte a **Default → Gerenciamento de usuários → mediflow-app**.
2. Abra **Chaves de API → Adicionar chave de API**.
3. Selecione **Gerar par de chaves de API**.
4. Baixe a **chave privada** antes de confirmar; ela não será exibida novamente.
5. Guarde-a fora do repositório, por exemplo:
   `C:\Users\SEU_USUARIO\.oci\mediflow_api_key.pem`.
6. Clique em **Adicionar** e copie o exemplo de configuração exibido pela OCI.
7. Salve-o como `C:\Users\SEU_USUARIO\.oci\config`, sem extensão `.txt`.

Exemplo do formato, sem credenciais reais:

```ini
[DEFAULT]
user=<OCID_DO_USUARIO_MEDIFLOW_APP>
fingerprint=<FINGERPRINT_DA_CHAVE_REGISTRADA>
tenancy=<OCID_DA_TENANCY>
region=sa-saopaulo-1
key_file=C:/Users/SEU_USUARIO/.oci/mediflow_api_key.pem
```

Copie `user`, `tenancy` e `fingerprint` do exemplo gerado para essa chave.
`user` não é o OCID do domínio, grupo ou compartimento. Remova o comentário
`# TODO` do caminho de exemplo e aponte `key_file` para o arquivo que existe.

Restrinja o acesso à pasta e à chave privada ao responsável e às contas de
sistema necessárias. Não publique os arquivos, não envie a chave por chat e
não a coloque no Git, na imagem Docker ou em uma pasta compartilhada.
Ao restaurar outro computador, gere uma chave própria ou restaure um backup
privado autorizado; uma chave pública não substitui a privada.

## 8. Configurar o MediFlow

No diretório do projeto, crie `.env` a partir de `.env.example` somente se
ainda não existir. Preserve os demais valores de um arquivo já configurado.

```dotenv
APP_ENV="local"
APP_MODE="operational"
PRESENTATION_USE_LLM="false"
STORAGE_MODE="oci"
OCI_NAMESPACE="<NAMESPACE_EXIBIDO_NO_BUCKET>"
OCI_BUCKET_NAME="mediflow-documentos-clinicos"
OCI_CONFIG_FILE="C:/Users/SEU_USUARIO/.oci/config"
OCI_CONFIG_PROFILE="DEFAULT"
GEMINI_API_KEY="<CHAVE_GEMINI_VALIDA>"
```

`APP_ENV=local` descreve onde a aplicação roda; usar Object Storage real não
transforma a hospedagem local em cloud. `PRESENTATION_USE_LLM` é ignorado em
modo operacional. O modo `presentation` exige `STORAGE_MODE=memory` e não serve
para testar persistência real na OCI. `OCI_SERVICE_ENDPOINT` é usado somente
no emulador e não precisa ser preenchido para `oci`.

### Executar Python diretamente no Windows

Com as dependências de `requirements.txt` instaladas no ambiente virtual,
o SDK usa o arquivo `config` e o caminho Windows acima. Inicie a API e a
interface conforme o README. Não use os caminhos Linux da seção seguinte
para executar a API diretamente no Windows.

### Executar em Docker

O container precisa acessar a configuração e a chave privada. O caminho
Windows escrito no `config` não existe dentro do Linux do container.

Crie uma cópia local chamada `.oci/config.docker`, ao lado do `config`,
preservando o mesmo perfil e dados. Altere somente:

```ini
key_file=/run/oci/mediflow_api_key.pem
```

Use o complemento versionado `docker-compose.oci-cloud.yml`. No `.env`,
configure os caminhos absolutos dos arquivos privados no computador host:

```dotenv
OCI_CONFIG_HOST_FILE="C:/Users/SEU_USUARIO/.oci/config.docker"
OCI_KEY_HOST_FILE="C:/Users/SEU_USUARIO/.oci/mediflow_api_key.pem"
```

O complemento monta somente esses dois arquivos na API, como leitura, define
`STORAGE_MODE=oci` e troca `OCI_CONFIG_FILE` para `/run/oci/config` no container.
O perfil continua sendo o de `OCI_CONFIG_PROFILE`. Os caminhos devem existir;
nenhuma pasta ou credencial e criada automaticamente. Não monte uma chave de
administrador; use a chave do usuário restrito criado neste guia.

Execute na raiz do repositório:

```powershell
docker compose -f docker-compose.yml -f docker-compose.oci-cloud.yml config --quiet
docker compose -f docker-compose.yml -f docker-compose.oci-cloud.yml up --build -d
```

As portas padrão são 8000 para a API e 8501 para a interface. Se houver outra
instância em execução, preserve-a e use um complemento local adicional para
alterar nomes de containers e portas. Na preparação original foram utilizadas
8002/8502 dessa forma; esses números não são obrigatórios para OCI.

O código é copiado para a imagem. Após alterá-lo, reconstrua com `--build`.
Após alterar `.env`, `config.docker` ou a chave, recrie a API com os mesmos
arquivos Compose; apenas `restart` não recarrega o ambiente:

```powershell
docker compose -f docker-compose.yml -f docker-compose.oci-cloud.yml up -d --force-recreate --no-deps mediflow-api
```

Não acrescente `docker-compose.oci-local.yml`: ele força `STORAGE_MODE=emulator`.
Não substitua um complemento local existente sem preservar suas configurações
adicionais. Se houver conflito de nomes ou portas, identifique os containers
existentes e adapte os nomes/portas, preservando a outra instalação.
Mantenha o mesmo projeto Compose entre comandos; mudar de checkout ou usar
outro `-p` pode criar outra instância em vez de atualizar a existente.

## 9. Validar a conexão e uma triagem

Com o exemplo Docker em execução:

```powershell
Invoke-RestMethod 'http://localhost:8000/health'
Invoke-RestMethod 'http://localhost:8000/health/ready'
Invoke-RestMethod 'http://localhost:8000/triagem/diagnostico?conexoes=true'
```

Se a autenticação da API estiver ativa, as rotas protegidas precisam do token
de serviço; siga [Autenticação OIDC](autenticacao.md). Não confunda esse token
com a chave OCI ou a senha da conta Oracle.

Abra [MediFlow local](http://localhost:8501) e, em **Armazenamento e integrações**,
verifique a conexão. O modo deve ser `oci`, com consulta ao bucket concluída.
A consulta confirma leitura; ainda não comprova escrita ou inferência Gemini.

Para validar o fluxo completo:

1. Envie um documento sintético em **Nova triagem**, usando um ID novo.
2. Confirme ausência de `erro_extracao` e `status_backup="sucesso"`.
3. Abra o histórico e recupere o original do documento.
4. No console OCI, abra **Bucket → Objetos** e confira o original em
   `recebidos/`, o relatório no destino escolhido e o acompanhamento em `fluxo/`.
5. Se necessário, recrie a API e confirme que o mesmo documento continua
   acessível. A persistência está no bucket, não na memória do container.

As triagens operacionais fazem chamadas Gemini e podem consumir cota.
Não use documentos clínicos reais na validação inicial. Exclua somente objetos
sintéticos identificados como pertencentes ao teste; não esvazie o bucket.

## 10. Usuário humano para testes no console

O usuário `mediflow-app` é a identidade técnica da aplicação. Para uma pessoa
testar pelo console, crie outro usuário em `Default`, com seu nome e e-mail,
e siga o fluxo de ativação apresentado pela OCI. Não compartilhe a senha ou
a chave da aplicação com a pessoa.

Associar esse usuário a `mediflow-storage` concede também escrita e exclusão.
Se precisar somente consultar, crie um grupo separado, por exemplo
`mediflow-consulta`, e uma política com:

```text
Allow group 'Default'/'mediflow-consulta' to read buckets in compartment mediflow where target.bucket.name = 'mediflow-documentos-clinicos'
Allow group 'Default'/'mediflow-consulta' to read objects in compartment mediflow where target.bucket.name = 'mediflow-documentos-clinicos'
```

Para navegar pelas listas do console, pode ser necessário conceder também
`inspect compartments in tenancy` e `inspect buckets in compartment mediflow`.
Essas permissões permitem visualizar metadados adicionais na navegação; avalie
esse alcance antes de concedê-las. A política mínima da aplicação foi validada
com acesso direto ao bucket pelo SDK, sem depender dessas listas do console.

## 11. Problemas encontrados e recuperação

| Sintoma | Verificação / ação |
| --- | --- |
| Domínios vazios | Troque o filtro de `mediflow` para o compartimento raiz e procure `Default`. |
| Arquivo de configuração ausente | Confira se foi salvo como `config.txt`; o SDK espera o nome configurado em `OCI_CONFIG_FILE`. |
| Chave não encontrada | Confira o nome real do PEM e o `key_file`; no Docker use o caminho Linux montado. |
| Falha de assinatura / autenticação | Confira usuário, tenancy, fingerprint, chave correspondente e relógio do computador. |
| HTTP 403 ou 404 ao consultar o bucket | Confira política, associação ao grupo, região, namespace e nome exato do bucket. Um 404 também pode ocultar falta de autorização. |
| Armazenamento continua em memória/emulador | Confira variáveis do container, arquivos `-f` e recrie a API. Não imprima a configuração completa com segredos. |
| Triagem bloqueada por Gemini | Configure a chave Gemini válida e recrie a API; acesso OCI não valida Gemini. |
| Nomes de containers já usados | Confira `docker ps -a`; ajuste os nomes ou use a instância correta, sem remover outra aplicação às cegas. |
| Mudança de computador | Restaure os arquivos privados autorizados ou gere nova chave; adapte os caminhos e valide novamente. |

Para substituir uma chave, registre o novo par para `mediflow-app`, atualize
as configurações locais e valide a aplicação. Depois revogue a chave antiga
no console. Em caso de exposição, revogue a chave comprometida imediatamente.
Não é necessário recriar o compartimento ou o bucket para trocar credenciais.

## 12. Validação realizada e referências

Na preparação de 22/10/2026, foram confirmados consulta ao bucket privado,
gravação, leitura, listagem e exclusão de um marcador sintético pelo adaptador
real, além de três triagens com originais e relatórios persistidos. Esses
resultados pertencem ao ambiente configurado e devem ser repetidos em outra conta.

O envio de e-mail é opcional e tem configuração própria em
[Webhook local com envio de e-mail](webhook-email.md). Ele não é necessário
para criar o bucket ou conectar o SDK OCI.

Documentação oficial:

- [Criar um compartimento](https://docs.oracle.com/en-us/iaas/Content/Identity/compartments/To_create_a_compartment.htm)
- [Criar um bucket](https://docs.oracle.com/en-us/iaas/Content/Object/Tasks/managingbuckets_topic-To_create_a_bucket.htm)
- [Domínio Default](https://docs.oracle.com/en-us/iaas/Content/Identity/domains/the_default_domain.htm)
- [Gerenciar grupos](https://docs.oracle.com/en-us/iaas/Content/Identity/groups/managinggroups.htm)
- [Permissões de Object Storage](https://docs.oracle.com/en-us/iaas/Content/Identity/Reference/objectstoragepolicyreference.htm)
- [Chaves de assinatura e OCIDs](https://docs.oracle.com/en-us/iaas/Content/API/Concepts/apisigningkey.htm)
