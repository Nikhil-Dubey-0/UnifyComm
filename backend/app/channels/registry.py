"""Provider → adapter lookup (ARCHITECTURE §9). Real providers register only when their
credentials are configured; the simulator is always available."""

from app.channels.base import ChannelAdapter
from app.channels.gmail import GmailAdapter
from app.channels.simulator import SimulatorAdapter
from app.channels.twilio_whatsapp import TwilioWhatsAppAdapter
from app.config import Settings
from app.enums import Provider


class AdapterRegistry:
    def __init__(self, adapters: list[ChannelAdapter]) -> None:
        self._adapters = {a.provider: a for a in adapters}

    def get(self, provider: Provider) -> ChannelAdapter:
        try:
            return self._adapters[provider]
        except KeyError:
            raise LookupError(f"No adapter configured for provider {provider!r}") from None


def build_registry(settings: Settings) -> AdapterRegistry:
    adapters: list[ChannelAdapter] = [SimulatorAdapter()]
    if settings.email_configured:
        adapters.append(GmailAdapter(settings))
    if settings.twilio_send_configured:
        adapters.append(TwilioWhatsAppAdapter(settings))
    return AdapterRegistry(adapters)
