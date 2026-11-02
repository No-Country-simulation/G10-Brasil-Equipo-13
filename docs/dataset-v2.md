# Dataset MediFlow v2

## Objetivo

O dataset v2 contém documentos clínicos sintéticos destinados ao desenvolvimento e aos testes do agente de triagem do MediFlow. Os documentos são fictícios e não devem ser utilizados para orientar decisões clínicas reais.

## Estrutura no repositório

Os arquivos versionados no Git ficam em `dataset/v2/`:

- `data/`: documentos de entrada em JSON e seus respectivos gabaritos.
- `schemas/`: schemas JSON de entrada, saída de triagem e gabarito.
- `manifest.csv`: índice dos 115 documentos de entrada.
- `README.md`: descrição original do dataset.
- `CHANGELOG.md`: histórico de alterações.
- `DECISOES.md`: decisões e regras provisórias do dataset.
- `VERSAO.txt`: identificação da versão.

O manifesto principal contém 115 registros classificados como `TEXTO`. Cada registro referencia um arquivo JSON de entrada. Os gabaritos correspondentes são armazenados separadamente, com a extensão `.gabarito.json`.

## Arquivos mantidos no Drive

Os PDFs e as imagens do dataset não são versionados neste repositório. Esses arquivos permanecem no Drive, conforme o alinhamento da equipe.

O dataset original também contém as pastas `documentos_gerados/` e `casos_teste/`, com arquivos binários e manifestos complementares. A disponibilidade desses arquivos depende do acesso ao Drive.

O script para download e validação dos checksums será desenvolvido posteriormente. Até que ele esteja disponível, o clone do repositório, isoladamente, não disponibiliza todos os arquivos binários do dataset original.

## Validações realizadas

Na preparação desta versão para o repositório, foram verificadas:

- A presença dos 115 registros no manifesto.
- A existência dos 115 arquivos JSON de entrada referenciados.
- A existência dos 115 gabaritos correspondentes.
- A presença dos três schemas JSON.

Essas verificações confirmam a presença dos arquivos esperados, mas não substituem a execução dos testes de integração do MediFlow nem a validação clínica do conteúdo.

## Limitações e validação clínica

Os documentos e as regras de roteamento são sintéticos e ainda não passaram por validação clínica profissional.

As decisões registradas em `DECISOES.md` devem ser consideradas provisórias. Questões relacionadas a urgência, auditoria humana, medicamentos de alto risco e encaminhamento de documentos dependem de validação e definição pela equipe responsável.

Este dataset serve como base de desenvolvimento e teste do sistema, não como protocolo clínico validado.