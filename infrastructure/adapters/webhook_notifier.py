"""
Adaptador de Infraestrutura: Webhook Notifier
Implementa a porta NotifierPort realizando disparos HTTP POST reais
para serviços de mensageria externa (Slack, Discord, Microsoft Teams ou Webhook REST).
"""

import json
import logging
from typing import Optional
import requests

from domain.ports.notifier_port import NotifierPort

logger = logging.getLogger("MediFlowNotifier")


class WebhookNotifierAdapter(NotifierPort):
    """
    Despacha alertas de emergência médica e notificações clínicas para webhooks externos.
    Mantém fallback resiliente para logs estruturados em caso de ausência de URL ou falha de rede.
    """

    def __init__(self, webhook_url: Optional[str] = None, timeout_segundos: int = 5, webhook_token: str = ""):
        self.webhook_url = webhook_url.strip() if webhook_url and webhook_url.strip() else None
        self.timeout = timeout_segundos
        self.webhook_token = webhook_token

    def enviar_alerta_urgencia(self, canal: str, mensagem: str) -> bool:
        """
        Dispara a notificação de urgência formatada para o webhook configurado.
        Gera log de auditoria obrigatório no contêiner.
        """
        # Registro local obrigatório para auditoria no stdout/docker logs
        logger.warning("[%s] - ALERTA CRÍTICO: %s", canal, mensagem)

        # Se não houver webhook configurado, mantém a notificação apenas nos logs locais
        if not self.webhook_url:
            logger.info("Nenhuma URL de webhook configurada. Alerta retido apenas em log estruturado.")
            return True

        # Payload universal compatível com Slack Incoming Webhooks, Teams e endpoints REST customizados
        payload = {
            "canal": canal,
            "text": f"🚨 *[MediFlow Alerta]* ({canal})\n{mensagem}",
            "mensagem": mensagem,
            "prioridade": "URGENTE"
        }

        try:
            headers = {"Content-Type": "application/json"}
            if self.webhook_token:
                headers["Authorization"] = "Bearer " + self.webhook_token
            resposta = requests.post(
                self.webhook_url,
                data=json.dumps(payload),
                headers=headers,
                timeout=self.timeout
            )

            if resposta.status_code in [200, 201, 204]:
                logger.info(
                    "Alerta para [%s] despachado com sucesso via Webhook HTTP %s.",
                    canal,
                    resposta.status_code
                )
                return True

            logger.error(
                "Falha ao despachar webhook para [%s]. Status: %s - Resposta: %s",
                canal,
                resposta.status_code,
                resposta.text
            )
            return False

        except requests.exceptions.Timeout:
            logger.error("Timeout (%ss) ao tentar conectar ao Webhook para o canal [%s].", self.timeout, canal)
            return False
        except requests.exceptions.RequestException as exc:
            logger.error("Erro de conexão ao disparar Webhook para [%s]: %s", canal, exc)
            return False
