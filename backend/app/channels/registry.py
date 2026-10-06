"""Provider → adapter lookup. Twilio and Gmail register here in Session 5."""

from app.channels.base import ChannelAdapter
from app.channels.simulator import SimulatorAdapter
from app.enums import Provider


class AdapterRegistry:
    def __init__(self, adapters: list[ChannelAdapter]) -> None:
        self._adapters = {a.provider: a for a in adapters}

    def get(self, provider: Provider) -> ChannelAdapter:
        try:
            return self._adapters[provider]
        except KeyError:
            raise LookupError(f"No adapter configured for provider {provider!r}") from None

    def providers(self) -> list[Provider]:
        return list(self._adapters)


def build_registry() -> AdapterRegistry:
    return AdapterRegistry([SimulatorAdapter()])
