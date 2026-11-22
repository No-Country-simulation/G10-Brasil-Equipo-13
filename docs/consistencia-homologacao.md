# Consistência da homologação

A revisão do [PR #47](https://github.com/No-Country-simulation/G10-Brasil-Equipo-13/pull/47#issuecomment-7082782784) identificou três falhas na homologação humana: decisões concorrentes, pendências que continuam na fila após uma movimentação parcial e acompanhamento desatualizado após salvar a decisão.

## Comportamento esperado

- Uma única decisão é registrada por pendência. Requisições concorrentes com decisões conflitantes recebem um conflito sem alterar o relatório, o acompanhamento ou os alertas da decisão vencedora.
- Após a decisão ser registrada, a pendência deixa de aceitar novas decisões. Se o processo falhar depois de gravar o destino, uma nova tentativa pode concluir a transição sem sobrescrever a decisão nem manter o caso disponível nas duas filas.
- Se a atualização do acompanhamento falhar, o estado parcial fica visível e a reconciliação pode retomar as etapas pendentes sem duplicar histórico.

## Validação

- Enviar aprovação e rejeição concorrentes para a mesma pendência e verificar uma única decisão persistida.
- Simular falha na remoção da origem após gravar o relatório final. Verificar as filas e concluir a movimentação por nova tentativa.
- Simular falha entre etapas do acompanhamento. Repetir a operação e verificar que o painel converge para a decisão registrada, com cada etapa registrada uma única vez.
- Rodar as regressões de homologação e validar os cenários com o emulador OCI.
