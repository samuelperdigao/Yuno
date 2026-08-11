"""Fundacao transversal da Yuno Platform.

Os modulos de negocio dependem dos contratos deste pacote. Este pacote nunca
importa um dominio concreto.
"""

from app.platform.registry import PLATFORM_CONTRACT_VERSION, module_registry

__all__ = ["PLATFORM_CONTRACT_VERSION", "module_registry"]
